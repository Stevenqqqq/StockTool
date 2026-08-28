"""Deterministic, append-only Prediction Lab Phase 0.

The lab is deliberately a research experiment, not a forecasting engine.  It
samples the already validated post-market ranking and stores immutable records
which can be replayed without a provider call.  No score in this module is an
investment recommendation or a prediction of future returns.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence, cast

from stock_tool.application.market_monitor import MarketSnapshot
from stock_tool.domain import Market, Symbol

PREDICTION_SCHEMA_VERSION = 1
OUTCOME_SCHEMA_VERSION = 2
PREDICTION_RULE_VERSION = "market-ranking-v1"
PREDICTION_GENERATOR_VERSION = "prediction-lab-phase0-v1"
PREDICTION_BUCKETS = ("top", "middle", "bottom")
PREDICTION_HORIZONS = (5, 20)
OFFICIAL_CALENDAR_DATA_PATH = Path(__file__).with_name("official_trading_calendars.json")
# Only years with a captured official response may be used at runtime.  These
# hashes are the raw bytes captured from the exchange/NYSE endpoints, not a
# digest of the normalized date list.
_OFFICIAL_CALENDAR_SOURCES: dict[tuple[str, int], dict[str, Any]] = {
    ("TWSE", 2025): {
        "source": "TWSE official holiday schedule",
        "endpoint": "https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&date=2025",
        "raw_payload_sha256": "5c85396aa2c0bf45add08a257aa6343aac2d48f9d6bb54da17c7f88fefcb71f8",
        "raw_payload_size_bytes": 2227,
        "normalized_payload_sha256": "a30e656b3b0e450faa5d8678e6f288396b078c0d8fa73a8b455250fc2c585bc8",
    },
    ("TWSE", 2026): {
        "source": "TWSE official holiday schedule",
        "endpoint": "https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&date=2026",
        "raw_payload_sha256": "7fefe785ea7155a5004a2eb74486ad865ea5c4b5f02ee0cffbbdacb1ca2ea390",
        "raw_payload_size_bytes": 2783,
        "normalized_payload_sha256": "88304739c22e68d94d0be02df90446549ceaeab0cec50ce44471ad04c2a02ff9",
    },
    ("TPEX", 2025): {
        "source": "TPEx official trading dates",
        "endpoint": "https://www.tpex.org.tw/www/en-us/bulletin/tradingDate?date=2025",
        "raw_payload_sha256": "e0ac10810635db8501e43e84027367fa0f079d1a314a1fb15c2148a8198877a5",
        "raw_payload_size_bytes": 5104,
        "normalized_payload_sha256": "e0469d1dfe8488197a305f9e051e56797909abf66830a011ab0e229a0428eb03",
    },
    ("TPEX", 2026): {
        "source": "TPEx official trading dates",
        "endpoint": "https://www.tpex.org.tw/www/en-us/bulletin/tradingDate?date=2026",
        "raw_payload_sha256": "01c25dd3052c9e108007ed2af0fc06173188f1c56676be49ae8b556acf35cd9f",
        "raw_payload_size_bytes": 5167,
        "normalized_payload_sha256": "05f7b0f7be0f67fd99078abde72357374c01884acb35457525e5b72f020aeee8",
    },
    ("US", 2026): {
        "source": "NYSE official trading calendar",
        "endpoint": "https://www.nyse.com/publicdocs/Trading_Days.pdf",
        "raw_payload_sha256": "f90b6d08c4f3e82af53e6139837058abb7a1e7770ea6c716b1ab5dbcb413139f",
        "raw_payload_size_bytes": 79739,
        "normalized_payload_sha256": "4733655be72359118247678a920c484735fbd95440f737123e3453d70e501238",
    },
}
_BENCHMARK_IDENTITY_BY_MARKET: Mapping[str, str] = {
    "TWSE": "TWSE:TAIEX",
    "TPEX": "TPEX:OTC",
    "US": "US:SPX",
}
PredictionBucket = Literal["top", "middle", "bottom"]
PredictionStatus = Literal["pending", "eligible", "evaluated", "unavailable"]


class PredictionOutcomeProvider(Protocol):
    """Verified, already-loaded market evidence used by the evaluator.

    Implementations are supplied by the application composition root.  The
    evaluator never performs network I/O and therefore cannot accidentally
    turn a render or replay into a provider refresh.
    """

    def calendar(self, market: str) -> "MarketTradingCalendar": ...

    def price(self, identity: str, effective_date: str) -> "PriceEvidence | None": ...

    def benchmark(
        self, identity: str, effective_date: str, start_date: str | None = None
    ) -> "BenchmarkEvidence | None": ...


# Status transitions are a contract, not an ordering.  ``unavailable`` is a
# terminal result for a prediction attempt; a later refresh must register a
# new prediction identity rather than silently turning an unavailable record
# back into an eligible/evaluated one.
OUTCOME_TRANSITIONS: Mapping[PredictionStatus, frozenset[PredictionStatus]] = {
    "pending": frozenset({"eligible", "evaluated", "unavailable"}),
    "eligible": frozenset({"evaluated"}),
    "evaluated": frozenset(),
    "unavailable": frozenset(),
}


class PredictionLabError(ValueError):
    """Raised when a prediction/outcome graph is not safe to consume."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _hashes(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(str(value).strip().lower() for value in values)
    if any(
        len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
        for value in result
    ):
        raise PredictionLabError("prediction source hash is not a SHA-256")
    return result


def _safe_reason(value: Any) -> str:
    """Return a short, non-sensitive diagnostic suitable for a run record."""

    text = str(value or "").strip()
    # Reasons crossing this boundary are type names or provider summaries only;
    # aggressively remove path/credential-shaped material before persistence.
    lowered = text.lower()
    if any(token in lowered for token in ("token", "api_key", "apikey", "credential", "secret")):
        return "provider error"
    if "\\" in text or "/" in text or "=" in text:
        return "provider error"
    return text[:160] or "provider error"


def _enum_value(value: Any) -> Any:
    """Return a stable scalar for enum-like provider metadata.

    Provider contracts use :class:`DataSourceType`, while installed-like
    adapters may expose a plain string.  Reading ``.value`` when present keeps
    both forms equivalent without persisting an enum repr such as
    ``DataSourceType.CACHE``.
    """

    candidate = getattr(value, "value", None)
    return candidate if isinstance(candidate, str) else value


def _aware_datetime(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PredictionLabError(f"{field} must be an ISO-8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PredictionLabError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise PredictionLabError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _date(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PredictionLabError(f"{field} is required")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise PredictionLabError(f"{field} is invalid") from exc


def _market_symbol(market: Any, symbol: Any) -> Symbol:
    try:
        parsed = Symbol.parse(str(symbol), market=Market.parse(market))
    except (TypeError, ValueError) as exc:
        raise PredictionLabError("unknown or conflicting market-qualified identity") from exc
    if parsed.market in {Market.AUTO, Market.CUSTOM}:
        raise PredictionLabError("prediction identity requires a known market")
    return parsed


def _parse_canonical_identity(value: Any, *, field: str = "identity") -> Symbol:
    """Parse a market-qualified identity without leaking tuple/split errors."""

    if not isinstance(value, str) or value.count(":") != 1:
        raise PredictionLabError(f"{field} must be market-qualified")
    market, symbol = (part.strip() for part in value.split(":", 1))
    if not market or not symbol:
        raise PredictionLabError(f"{field} must be market-qualified")
    parsed = _market_symbol(market, symbol)
    if parsed.canonical != f"{market.upper()}:{symbol.upper()}":
        raise PredictionLabError(f"{field} is not canonical")
    return parsed


def _finite_number(value: Any, *, field: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PredictionLabError(f"{field} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized) or (minimum is not None and normalized < minimum):
        raise PredictionLabError(f"{field} must be a finite number")
    return normalized


def _normalize_reference(
    value: Mapping[str, Any] | None,
    *,
    identity: str,
    effective_date: str,
    field: str,
    include_value: bool = False,
) -> dict[str, Any] | None:
    """Normalize immutable price/benchmark provenance at the boundary."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise PredictionLabError(f"{field} reference is invalid")
    raw_identity = str(value.get("identity") or "").strip()
    if ":" not in raw_identity:
        raise PredictionLabError(f"{field} reference identity is invalid")
    parsed = _market_symbol(*raw_identity.split(":", 1))
    if parsed.canonical != identity:
        raise PredictionLabError(f"{field} reference identity mismatch")
    actual_date = _date(
        value.get("effective_trading_date", value.get("effective_date", effective_date)),
        field=f"{field}.effective_trading_date",
    )
    if actual_date != effective_date:
        raise PredictionLabError(f"{field} reference date mismatch")
    payload_hash = value.get("payload_hash", value.get("payload_sha256"))
    provenance = _hashes((payload_hash,))[0]
    normalized: dict[str, Any] = {
        "identity": parsed.canonical,
        "price_field": str(value.get("price_field", value.get("field", "close"))),
        "effective_trading_date": actual_date,
        "provider": str(value.get("provider", value.get("source", "unknown"))),
        "payload_hash": provenance,
        "adjusted_raw_policy": str(value.get("adjusted_raw_policy", "raw")),
    }
    if include_value:
        normalized["value"] = _finite_number(
            value.get("value"), field=f"{field}.value", minimum=0.0000000001
        )
    return normalized


@dataclass(frozen=True, slots=True)
class PriceEvidence:
    """One verified close price and its source identity."""

    identity: str
    value: float
    effective_trading_date: str
    provider: str
    payload_hash: str
    price_field: str = "close"
    adjusted_raw_policy: str = "raw"

    def __post_init__(self) -> None:
        parsed = _parse_canonical_identity(self.identity)
        object.__setattr__(self, "identity", parsed.canonical)
        object.__setattr__(
            self,
            "effective_trading_date",
            _date(self.effective_trading_date, field="price effective date"),
        )
        _hashes((self.payload_hash,))
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise PredictionLabError("price provider is required")
        if self.price_field not in {"close", "adjusted_close"}:
            raise PredictionLabError("price field is invalid")
        if self.adjusted_raw_policy not in {"raw", "adjusted"}:
            raise PredictionLabError("price adjusted/raw policy is invalid")
        object.__setattr__(
            self,
            "value",
            _finite_number(self.value, field="price value", minimum=1e-12),
        )

    def to_reference(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "value": self.value,
            "effective_trading_date": self.effective_trading_date,
            "provider": self.provider,
            "payload_hash": self.payload_hash,
            "price_field": self.price_field,
            "adjusted_raw_policy": self.adjusted_raw_policy,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkEvidence:
    """One verified benchmark observation pair and its source identity.

    ``return_value`` is retained for schema-v2 compatibility, but a production
    provider also supplies the start/end observations so the return can be
    recomputed from provenance.  The legacy fields remain optional solely so
    old deterministic test providers can be replayed; the production runtime
    provider marks itself strict and never emits an incomplete reference.
    """

    identity: str
    return_value: float
    effective_trading_date: str
    provider: str
    payload_hash: str
    start_trading_date: str | None = None
    end_trading_date: str | None = None
    start_value: float | None = None
    end_value: float | None = None
    price_field: str = "close"
    adjusted_raw_policy: str = "raw"
    payload_hashes: tuple[str, ...] = ()
    provider_symbol: str | None = None
    source_type: str | None = None
    checked_at: str | None = None
    fetched_at: str | None = None

    def __post_init__(self) -> None:
        parsed = _parse_canonical_identity(self.identity, field="benchmark identity")
        object.__setattr__(self, "identity", parsed.canonical)
        if self.provider_symbol is not None:
            expected_provider_symbol = _BENCHMARK_PROVIDER_SYMBOLS.get(parsed.market.value)
            supplied_provider_symbol = self.provider_symbol.strip()
            # Legacy installed-like sidecars used the canonical benchmark
            # symbol itself (``TAIEX``/``OTC``/``SPX``) as the provider
            # symbol.  Keep that explicitly supported alias while still
            # rejecting arbitrary or cross-market provider identities.  The
            # production refresh path persists the official provider symbol
            # (for example ``^TWII``), so no provenance is weakened.
            allowed_provider_symbols = {
                expected_provider_symbol,
                parsed.code,
            }
            if (
                expected_provider_symbol is None
                or supplied_provider_symbol not in allowed_provider_symbols
            ):
                raise PredictionLabError("benchmark provider symbol does not match identity")
            object.__setattr__(self, "provider_symbol", supplied_provider_symbol)
        if self.source_type is not None:
            normalized_source_type = self.source_type.strip().lower()
            if normalized_source_type not in {
                "online",
                "cache",
                "manual",
                "upload",
                "user_upload",
                "local_file",
            }:
                raise PredictionLabError("benchmark source type is invalid")
            object.__setattr__(self, "source_type", normalized_source_type)
        object.__setattr__(
            self,
            "effective_trading_date",
            _date(self.effective_trading_date, field="benchmark effective date"),
        )
        _hashes((self.payload_hash,))
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise PredictionLabError("benchmark provider is required")
        if self.provider_symbol is not None and (
            not isinstance(self.provider_symbol, str) or not self.provider_symbol.strip()
        ):
            raise PredictionLabError("benchmark provider symbol is invalid")
        if self.source_type is not None and (
            not isinstance(self.source_type, str) or not self.source_type.strip()
        ):
            raise PredictionLabError("benchmark source type is invalid")
        for name in ("checked_at", "fetched_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    _iso(_aware_datetime(value, field=f"benchmark {name}")),
                )
        hashes = self.payload_hashes or (self.payload_hash,)
        object.__setattr__(self, "payload_hashes", _hashes(tuple(hashes)))
        normalized_return = _finite_number(self.return_value, field="benchmark_return")
        object.__setattr__(self, "return_value", normalized_return)
        if self.start_trading_date is None and self.end_trading_date is None:
            return
        if not all(
            value is not None
            for value in (
                self.start_trading_date,
                self.end_trading_date,
                self.start_value,
                self.end_value,
            )
        ):
            raise PredictionLabError("benchmark evidence observations are incomplete")
        start_date = _date(self.start_trading_date, field="benchmark start date")
        end_date = _date(self.end_trading_date, field="benchmark end date")
        if end_date != self.effective_trading_date or start_date > end_date:
            raise PredictionLabError("benchmark evidence date range is invalid")
        start_value = _finite_number(self.start_value, field="benchmark start value", minimum=1e-12)
        end_value = _finite_number(self.end_value, field="benchmark end value", minimum=1e-12)
        derived = end_value / start_value - 1.0
        if not math.isclose(derived, normalized_return, rel_tol=0.0, abs_tol=1e-12):
            raise PredictionLabError("benchmark return cannot be recomputed from evidence")
        object.__setattr__(self, "start_trading_date", start_date)
        object.__setattr__(self, "end_trading_date", end_date)
        object.__setattr__(self, "start_value", start_value)
        object.__setattr__(self, "end_value", end_value)
        if self.price_field not in {"close", "adjusted_close"}:
            raise PredictionLabError("benchmark price field is invalid")
        if self.adjusted_raw_policy not in {"raw", "adjusted"}:
            raise PredictionLabError("benchmark adjusted/raw policy is invalid")

    def to_reference(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "return_value": self.return_value,
            "effective_trading_date": self.effective_trading_date,
            "provider": self.provider,
            "payload_hash": self.payload_hash,
            "payload_hashes": list(self.payload_hashes),
            "start_trading_date": self.start_trading_date,
            "end_trading_date": self.end_trading_date,
            "start_value": self.start_value,
            "end_value": self.end_value,
            "price_field": self.price_field,
            "adjusted_raw_policy": self.adjusted_raw_policy,
            "provider_symbol": self.provider_symbol,
            "source_type": self.source_type,
            "checked_at": self.checked_at,
            "fetched_at": self.fetched_at,
        }


@dataclass(frozen=True, slots=True)
class MarketTradingCalendar:
    """Hash-bound sequence of verified trading dates for one market.

    The sequence, rather than a weekday rule, is the authority used to derive
    prediction targets.  ``default_for`` reads an explicit, versioned payload
    collected from the exchange calendars.  Runtime code never derives dates
    from weekdays, security rows, or a hand-written holiday formula.
    """

    market: str
    dates: tuple[str, ...]
    source_hash: str
    identity: str
    source: str = "explicit-test"
    endpoint: str = ""
    fetched_at: str = ""
    schema_version: int = 1
    raw_payload_sha256: str | None = None
    raw_payload_hashes: tuple[str, ...] = ()
    normalized_payload_sha256: str | None = None
    normalization_algorithm_version: str | None = None
    raw_payload_size_bytes: int | None = None
    year: int | None = None
    calendar_years: tuple[int, ...] = ()

    OFFICIAL_SCHEMA_VERSION = 3

    @classmethod
    def from_dates(
        cls,
        *,
        market: str,
        dates: Sequence[str],
        source_hash: str,
        source: str = "explicit-test",
        endpoint: str = "",
        fetched_at: str = "",
        schema_version: int = 1,
        raw_payload_sha256: str | None = None,
        raw_payload_hashes: Sequence[str] = (),
        normalized_payload_sha256: str | None = None,
        normalization_algorithm_version: str | None = None,
        raw_payload_size_bytes: int | None = None,
        year: int | None = None,
        calendar_years: Sequence[int] = (),
    ) -> "MarketTradingCalendar":
        parsed_market = Market.parse(market)
        if parsed_market in {Market.AUTO, Market.CUSTOM}:
            raise PredictionLabError("calendar requires a known market")
        normalized = tuple(_date(item, field="calendar date") for item in dates)
        if not normalized or len(set(normalized)) != len(normalized):
            raise PredictionLabError("calendar dates must be unique and non-empty")
        if tuple(sorted(normalized)) != normalized:
            raise PredictionLabError("calendar dates must be sorted")
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise PredictionLabError("trading calendar schema is invalid")
        if schema_version not in {1, cls.OFFICIAL_SCHEMA_VERSION}:
            raise PredictionLabError("unsupported trading calendar schema")
        if not isinstance(source, str) or not source.strip():
            raise PredictionLabError("trading calendar source is required")
        if not isinstance(endpoint, str):
            raise PredictionLabError("trading calendar endpoint is invalid")
        if fetched_at:
            _aware_datetime(fetched_at, field="calendar fetched_at")
        if year is not None and (isinstance(year, bool) or not isinstance(year, int)):
            raise PredictionLabError("trading calendar year is invalid")
        years = tuple(sorted(set(calendar_years)))
        if any(isinstance(item, bool) or not isinstance(item, int) for item in years):
            raise PredictionLabError("trading calendar years are invalid")
        hashes = _hashes((source_hash,))
        raw_hash = _hashes((raw_payload_sha256 or hashes[0],))[0]
        raw_hashes = _hashes(tuple(raw_payload_hashes or (raw_hash,)))
        semantic: dict[str, Any]
        if schema_version == 1:
            # Keep the legacy explicit-test identity stable for callers which
            # provide a calendar directly in unit tests.
            semantic = {
                "schema_version": 1,
                "market": parsed_market.value,
                "dates": list(normalized),
                "source_hash": hashes[0],
            }
        else:
            if not endpoint.strip() or not fetched_at or not years:
                raise PredictionLabError("official trading calendar provenance is incomplete")
            if (
                not isinstance(normalization_algorithm_version, str)
                or not normalization_algorithm_version.strip()
                or normalized_payload_sha256 is None
            ):
                raise PredictionLabError(
                    "official trading calendar normalization provenance is incomplete"
                )
            if (len(years) == 1 and year != years[0]) or (len(years) > 1 and year is not None):
                raise PredictionLabError("trading calendar year is inconsistent")
            normalized_payload = _sha(
                {
                    "market": parsed_market.value,
                    "year": year,
                    "dates": list(normalized),
                }
            )
            if normalized_payload_sha256.lower() != normalized_payload:
                raise PredictionLabError(
                    "official trading calendar normalized payload hash mismatch"
                )
            if raw_payload_size_bytes is not None and (
                isinstance(raw_payload_size_bytes, bool)
                or not isinstance(raw_payload_size_bytes, int)
                or raw_payload_size_bytes <= 0
            ):
                raise PredictionLabError("official trading calendar raw payload size is invalid")
            semantic = {
                "schema_version": schema_version,
                "market": parsed_market.value,
                "dates": list(normalized),
                "source_hash": hashes[0],
                "source": source.strip(),
                "endpoint": endpoint.strip(),
                "fetched_at": _iso(_aware_datetime(fetched_at, field="calendar fetched_at")),
                "raw_payload_sha256": raw_hash,
                "raw_payload_hashes": list(raw_hashes),
                "normalized_payload_sha256": normalized_payload_sha256.lower(),
                "normalization_algorithm_version": normalization_algorithm_version.strip(),
                "raw_payload_size_bytes": raw_payload_size_bytes,
                "year": year,
                "calendar_years": list(years),
            }
        return cls(
            market=parsed_market.value,
            dates=normalized,
            source_hash=hashes[0],
            identity=f"calendar-{_sha(semantic)}",
            source=source.strip(),
            endpoint=endpoint.strip(),
            fetched_at=(
                _iso(_aware_datetime(fetched_at, field="calendar fetched_at")) if fetched_at else ""
            ),
            schema_version=schema_version,
            raw_payload_sha256=raw_hash,
            raw_payload_hashes=raw_hashes,
            normalized_payload_sha256=(
                normalized_payload_sha256.lower() if normalized_payload_sha256 else None
            ),
            normalization_algorithm_version=(
                normalization_algorithm_version.strip()
                if isinstance(normalization_algorithm_version, str)
                else None
            ),
            raw_payload_size_bytes=raw_payload_size_bytes,
            year=year,
            calendar_years=years,
        )

    @classmethod
    def default_for(cls, market: str, year: int | None = None) -> "MarketTradingCalendar":
        """Return the bundled, official, hash-bound calendar for ``market``."""

        parsed = Market.parse(market)
        if parsed in {Market.AUTO, Market.CUSTOM}:
            raise PredictionLabError("calendar requires a known market")
        path = Path(OFFICIAL_CALENDAR_DATA_PATH)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PredictionLabError("official trading calendar is unavailable") from exc
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != cls.OFFICIAL_SCHEMA_VERSION
        ):
            raise PredictionLabError("official trading calendar schema is invalid")
        if set(payload) != {"schema_version", "calendars", "fetched_at"}:
            raise PredictionLabError("official trading calendar payload contains unknown fields")
        if not isinstance(payload.get("fetched_at"), str):
            raise PredictionLabError("official trading calendar provenance is invalid")
        _aware_datetime(payload["fetched_at"], field="calendar fetched_at")
        rows = payload.get("calendars")
        if not isinstance(rows, list):
            raise PredictionLabError("official trading calendar payload is invalid")
        requested_year = year
        if requested_year is not None and (
            isinstance(requested_year, bool) or not isinstance(requested_year, int)
        ):
            raise PredictionLabError("official trading calendar year is invalid")
        selected: list[Mapping[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise PredictionLabError("official trading calendar payload is invalid")
            if raw.get("market") != parsed.value:
                continue
            # The bundled payload is an external contract.  Unknown aliases
            # (for example the historical ``payload_sha256`` field) are not
            # harmless metadata: accepting them would let a caller mutate a
            # provenance field that the loader never validates.  Reject the
            # row instead of silently ignoring untrusted keys.
            allowed_row_keys = {
                "dates",
                "endpoint",
                "fetched_at",
                "market",
                "normalization_algorithm_version",
                "normalized_payload_sha256",
                "raw_payload_sha256",
                "raw_payload_size_bytes",
                "schema_version",
                "source",
                "year",
            }
            if set(raw) != allowed_row_keys:
                raise PredictionLabError(
                    "official trading calendar payload contains unknown fields"
                )
            raw_year = raw.get("year")
            if requested_year is not None and raw_year != requested_year:
                continue
            if raw.get("schema_version") != cls.OFFICIAL_SCHEMA_VERSION:
                raise PredictionLabError("official trading calendar schema is invalid")
            dates = raw.get("dates")
            source = raw.get("source")
            endpoint = raw.get("endpoint")
            fetched_at = raw.get("fetched_at")
            payload_hash = raw.get("raw_payload_sha256")
            normalized_hash = raw.get("normalized_payload_sha256")
            normalization_version = raw.get("normalization_algorithm_version")
            raw_size = raw.get("raw_payload_size_bytes")
            if (
                isinstance(raw_year, bool)
                or not isinstance(raw_year, int)
                or not isinstance(dates, list)
                or not isinstance(source, str)
                or not isinstance(endpoint, str)
                or not isinstance(fetched_at, str)
                or not isinstance(payload_hash, str)
                or not isinstance(normalized_hash, str)
                or not isinstance(normalization_version, str)
                or isinstance(raw_size, bool)
                or not isinstance(raw_size, int)
            ):
                raise PredictionLabError("official trading calendar provenance is invalid")
            if fetched_at != payload["fetched_at"]:
                raise PredictionLabError("official trading calendar provenance is inconsistent")
            trusted = _OFFICIAL_CALENDAR_SOURCES.get((parsed.value, raw_year))
            if trusted is None:
                # Do not infer a date list for an unproven year (notably 2027).
                continue
            if (
                payload_hash.lower() != trusted["raw_payload_sha256"]
                or endpoint != trusted["endpoint"]
                or source != trusted["source"]
                or raw_size != trusted["raw_payload_size_bytes"]
            ):
                raise PredictionLabError("official trading calendar raw provenance mismatch")
            expected_hash = _sha({"market": parsed.value, "year": raw_year, "dates": dates})
            if normalized_hash.lower() != expected_hash:
                raise PredictionLabError(
                    "official trading calendar normalized payload hash mismatch"
                )
            _hashes((payload_hash, normalized_hash))
            _aware_datetime(fetched_at, field="calendar fetched_at")
            selected.append(raw)
        if not selected:
            raise PredictionLabError("official trading calendar is unavailable")
        selected.sort(key=lambda item: int(item["year"]))
        values: list[str] = []
        for row in selected:
            values.extend(str(item) for item in row["dates"])
        if len(values) != len(set(values)) or tuple(sorted(values)) != tuple(values):
            raise PredictionLabError("official trading calendar dates are invalid")
        # The singular compatibility field denotes the newest selected
        # official payload; ``raw_payload_hashes`` retains every year in
        # ascending order for complete provenance.
        first = selected[-1]
        fetched_values = {str(item["fetched_at"]) for item in selected}
        if len(fetched_values) != 1:
            raise PredictionLabError("official trading calendar provenance is inconsistent")
        source = str(first["source"])
        endpoint = str(first["endpoint"])
        years = tuple(int(item["year"]) for item in selected)
        selected_year = years[0] if len(years) == 1 else None
        # ``source_hash`` is the immutable normalized calendar identity.  Raw
        # payload hashes remain separate provenance and are never relabelled as
        # the normalized/self digest.
        combined_hash = _sha(
            {
                "schema_version": cls.OFFICIAL_SCHEMA_VERSION,
                "market": parsed.value,
                "dates": values,
                "source": source,
                "endpoint": endpoint,
                "calendar_years": list(years),
                "normalized_payload_hashes": [
                    str(item["normalized_payload_sha256"]) for item in selected
                ],
            }
        )
        return cls.from_dates(
            market=parsed.value,
            dates=values,
            source_hash=combined_hash,
            source=source,
            endpoint=endpoint,
            fetched_at=str(first["fetched_at"]),
            schema_version=cls.OFFICIAL_SCHEMA_VERSION,
            raw_payload_sha256=str(first["raw_payload_sha256"]),
            raw_payload_hashes=tuple(str(item["raw_payload_sha256"]) for item in selected),
            normalized_payload_sha256=_sha(
                {"market": parsed.value, "year": selected_year, "dates": values}
            ),
            normalization_algorithm_version="official-calendar-normalize-v1",
            raw_payload_size_bytes=sum(int(item["raw_payload_size_bytes"]) for item in selected),
            year=selected_year,
            calendar_years=years,
        )

    def target_date(self, trading_date: str, horizon: int) -> str:
        start = _date(trading_date, field="trading_date")
        if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon <= 0:
            raise PredictionLabError("calendar horizon is invalid")
        try:
            index = self.dates.index(start)
            return self.dates[index + horizon]
        except (ValueError, IndexError) as exc:
            raise PredictionLabError("insufficient verified trading dates") from exc

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "market": self.market,
            "dates": list(self.dates),
            "source_hash": self.source_hash,
            "identity": self.identity,
        }
        if self.schema_version >= self.OFFICIAL_SCHEMA_VERSION:
            payload.update(
                {
                    "source": self.source,
                    "endpoint": self.endpoint,
                    "fetched_at": self.fetched_at,
                    "raw_payload_sha256": self.raw_payload_sha256,
                    "raw_payload_hashes": list(self.raw_payload_hashes),
                    "normalized_payload_sha256": self.normalized_payload_sha256,
                    "normalization_algorithm_version": self.normalization_algorithm_version,
                    "raw_payload_size_bytes": self.raw_payload_size_bytes,
                    "year": self.year,
                    "calendar_years": list(self.calendar_years),
                }
            )
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MarketTradingCalendar":
        schema_version = payload.get("schema_version")
        if schema_version != 1 and schema_version != cls.OFFICIAL_SCHEMA_VERSION:
            raise PredictionLabError("unsupported trading calendar schema")
        if isinstance(schema_version, bool):
            raise PredictionLabError("unsupported trading calendar schema")
        market = payload.get("market")
        source_hash = payload.get("source_hash")
        if not isinstance(market, str) or not isinstance(source_hash, str):
            raise PredictionLabError("trading calendar provenance is invalid")
        base_fields = {"schema_version", "market", "dates", "source_hash", "identity"}
        if schema_version == 1:
            missing = base_fields - set(payload)
            extra = set(payload) - base_fields
            if missing:
                raise PredictionLabError("trading calendar provenance is incomplete")
            if extra:
                raise PredictionLabError("trading calendar payload contains unknown fields")
        else:
            official_fields = base_fields | {
                "source",
                "endpoint",
                "fetched_at",
                "raw_payload_sha256",
                "raw_payload_hashes",
                "normalized_payload_sha256",
                "normalization_algorithm_version",
                "raw_payload_size_bytes",
                "year",
                "calendar_years",
            }
            missing = official_fields - set(payload)
            extra = set(payload) - official_fields
            if missing:
                raise PredictionLabError("official trading calendar provenance is incomplete")
            if extra:
                raise PredictionLabError(
                    "official trading calendar payload contains unknown fields"
                )
        kwargs: dict[str, Any] = {}
        if schema_version == cls.OFFICIAL_SCHEMA_VERSION:
            for name in (
                "source",
                "endpoint",
                "fetched_at",
                "raw_payload_sha256",
                "raw_payload_hashes",
                "normalized_payload_sha256",
                "normalization_algorithm_version",
                "raw_payload_size_bytes",
                "year",
                "calendar_years",
            ):
                if name not in payload:
                    raise PredictionLabError("official trading calendar provenance is incomplete")
            kwargs.update(
                source=payload.get("source"),
                endpoint=payload.get("endpoint"),
                fetched_at=payload.get("fetched_at"),
                schema_version=schema_version,
                raw_payload_sha256=payload.get("raw_payload_sha256"),
                raw_payload_hashes=payload.get("raw_payload_hashes", ()),
                normalized_payload_sha256=payload.get("normalized_payload_sha256"),
                normalization_algorithm_version=payload.get("normalization_algorithm_version"),
                raw_payload_size_bytes=payload.get("raw_payload_size_bytes"),
                year=payload.get("year"),
                calendar_years=payload.get("calendar_years", ()),
            )
            raw_payload_sha256 = payload.get("raw_payload_sha256")
            years = payload.get("calendar_years", ())
            if not isinstance(years, (list, tuple)) or any(
                isinstance(item, bool) or not isinstance(item, int) for item in years
            ):
                raise PredictionLabError("official trading calendar years are invalid")
            normalized_hash = payload.get("normalized_payload_sha256")
            expected_normalized = _sha(
                {
                    "market": market,
                    "year": payload.get("year"),
                    "dates": payload.get("dates", ()),
                }
            )
            if (
                not isinstance(normalized_hash, str)
                or normalized_hash.lower() != expected_normalized
            ):
                raise PredictionLabError(
                    "official trading calendar normalized payload hash mismatch"
                )
            raw_hashes = payload.get("raw_payload_hashes", ())
            if not isinstance(raw_hashes, (list, tuple)) or not raw_hashes:
                raise PredictionLabError("official trading calendar raw provenance is incomplete")
            normalized_raw_hashes = _hashes(tuple(str(item) for item in raw_hashes))
            if str(raw_payload_sha256).lower() != normalized_raw_hashes[-1]:
                raise PredictionLabError("official trading calendar raw provenance mismatch")
            if len(normalized_raw_hashes) != len(years):
                raise PredictionLabError("official trading calendar raw provenance is incomplete")
            if tuple(years) != tuple(sorted(set(years))):
                raise PredictionLabError("official trading calendar years are invalid")
            if payload.get("year") is not None and (
                isinstance(payload.get("year"), bool)
                or not isinstance(payload.get("year"), int)
                or len(years) != 1
                or payload.get("year") != years[0]
            ):
                raise PredictionLabError("official trading calendar year is inconsistent")
            if payload.get("year") is None and len(years) < 2:
                raise PredictionLabError("official trading calendar year is incomplete")
            expected_sources = []
            expected_size = 0
            for raw_year, raw_hash in zip(years, normalized_raw_hashes):
                trusted = _OFFICIAL_CALENDAR_SOURCES.get((str(market).upper(), raw_year))
                if trusted is None or raw_hash != trusted["raw_payload_sha256"]:
                    raise PredictionLabError("official trading calendar raw provenance mismatch")
                expected_sources.append(trusted)
                expected_size += int(trusted["raw_payload_size_bytes"])
            if (
                str(payload.get("source")) != expected_sources[-1]["source"]
                or str(payload.get("endpoint")) != expected_sources[-1]["endpoint"]
                or payload.get("raw_payload_size_bytes") != expected_size
            ):
                raise PredictionLabError("official trading calendar source binding mismatch")
            # Every yearly normalized hash and the aggregate identity are
            # pinned to the trusted source contract.  Re-signing a tampered
            # payload therefore cannot make it look like an official calendar.
            raw_dates = payload.get("dates", ())
            if not isinstance(raw_dates, (list, tuple)):
                raise PredictionLabError("official trading calendar dates are invalid")
            normalized_year_hashes: list[str] = []
            for raw_year, trusted in zip(years, expected_sources):
                year_dates = [
                    str(item) for item in raw_dates if str(item).startswith(f"{raw_year:04d}-")
                ]
                expected_year_hash = _sha(
                    {"market": str(market).upper(), "year": raw_year, "dates": year_dates}
                )
                if expected_year_hash != str(trusted["normalized_payload_sha256"]):
                    raise PredictionLabError(
                        "official trading calendar normalized payload mismatch"
                    )
                normalized_year_hashes.append(expected_year_hash)
            expected_source_hash = _sha(
                {
                    "schema_version": cls.OFFICIAL_SCHEMA_VERSION,
                    "market": str(market).upper(),
                    "dates": list(raw_dates),
                    "source": expected_sources[-1]["source"],
                    "endpoint": expected_sources[-1]["endpoint"],
                    "calendar_years": list(years),
                    "normalized_payload_hashes": normalized_year_hashes,
                }
            )
            if source_hash.lower() != expected_source_hash:
                raise PredictionLabError("official trading calendar source identity mismatch")
        result = cls.from_dates(
            market=market, dates=payload.get("dates", ()), source_hash=source_hash, **kwargs
        )
        if payload.get("identity") != result.identity:
            raise PredictionLabError("trading calendar identity mismatch")
        return result


@dataclass(frozen=True, slots=True)
class PredictionCostPolicy:
    """Versioned, market-qualified transaction-cost assumptions."""

    market: str
    version: str
    commission_rate: float
    tax_rate: float
    slippage_rate: float
    buy_commission_rate: float | None = None
    sell_commission_rate: float | None = None
    buy_slippage_rate: float | None = None
    sell_slippage_rate: float | None = None
    sell_tax_rate: float | None = None

    # The policy version is the public configuration identity.  Keep a
    # separate formula marker in the persisted components so a future policy
    # can change the calculation without making a historical outcome
    # ambiguous.
    formula_version: str = "broker-cashflow-v1"

    def __post_init__(self) -> None:
        parsed = Market.parse(self.market)
        if parsed in {Market.AUTO, Market.CUSTOM}:
            raise PredictionLabError("prediction cost policy requires a known market")
        object.__setattr__(self, "market", parsed.value)
        if not isinstance(self.version, str) or not self.version.strip():
            raise PredictionLabError("prediction cost policy version is required")
        if not isinstance(self.formula_version, str) or not self.formula_version.strip():
            raise PredictionLabError("prediction cost formula version is required")
        for name in ("commission_rate", "tax_rate", "slippage_rate"):
            normalized = _finite_number(getattr(self, name), field=name, minimum=0.0)
            object.__setattr__(self, name, normalized)
        # The historical three rates remain accepted as constructor inputs;
        # they are the defaults for each corresponding buy/sell leg.  Explicit
        # per-leg values are persisted so the evaluated cost is auditable.
        defaults = {
            "buy_commission_rate": self.commission_rate,
            "sell_commission_rate": self.commission_rate,
            "buy_slippage_rate": self.slippage_rate,
            "sell_slippage_rate": self.slippage_rate,
            "sell_tax_rate": self.tax_rate,
        }
        for name, default in defaults.items():
            value = getattr(self, name)
            object.__setattr__(
                self,
                name,
                _finite_number(
                    default if value is None else value,
                    field=name,
                    minimum=0.0,
                ),
            )

    @property
    def total_rate(self) -> float:
        return float(
            float(self.buy_commission_rate or 0.0)
            + float(self.sell_commission_rate or 0.0)
            + float(self.buy_slippage_rate or 0.0)
            + float(self.sell_slippage_rate or 0.0)
            + float(self.sell_tax_rate or 0.0)
        )

    def components(self, *, position_side: str = "long") -> dict[str, Any]:
        if position_side not in {"long", "short"}:
            raise PredictionLabError("unsupported prediction position side")
        return {
            "commission_rate": float(self.commission_rate),
            "tax_rate": float(self.tax_rate),
            "slippage_rate": float(self.slippage_rate),
            "buy_commission_rate": float(self.buy_commission_rate or 0.0),
            "sell_commission_rate": float(self.sell_commission_rate or 0.0),
            "buy_slippage_rate": float(self.buy_slippage_rate or 0.0),
            "sell_slippage_rate": float(self.sell_slippage_rate or 0.0),
            "sell_tax_rate": float(self.sell_tax_rate or 0.0),
            "total_rate": self.total_rate,
            "formula_version": self.formula_version,
            "position_side": position_side,
        }


def _round_trip_cost(
    entry_price: float,
    exit_price: float,
    components: Mapping[str, Any],
    *,
    position_side: str = "long",
) -> dict[str, float | str]:
    """Apply the BrokerSimulator cash-flow model to one round trip.

    Slippage changes the execution price first; commission and (where
    applicable) sell tax are then charged on that executed notional.  The
    returned values are per-share cash flows and deterministic return fields,
    allowing an outcome to be recomputed from its persisted evidence.
    """

    if position_side not in {"long", "short"}:
        raise PredictionLabError("unsupported prediction position side")
    entry = _finite_number(entry_price, field="entry_price", minimum=1e-12)
    exit_value = _finite_number(exit_price, field="exit_price", minimum=1e-12)
    buy_commission_rate = _finite_number(
        components.get("buy_commission_rate", components.get("commission_rate", 0.0)),
        field="buy_commission_rate",
        minimum=0.0,
    )
    sell_commission_rate = _finite_number(
        components.get("sell_commission_rate", components.get("commission_rate", 0.0)),
        field="sell_commission_rate",
        minimum=0.0,
    )
    buy_slippage_rate = _finite_number(
        components.get("buy_slippage_rate", components.get("slippage_rate", 0.0)),
        field="buy_slippage_rate",
        minimum=0.0,
    )
    sell_slippage_rate = _finite_number(
        components.get("sell_slippage_rate", components.get("slippage_rate", 0.0)),
        field="sell_slippage_rate",
        minimum=0.0,
    )
    sell_tax_rate = _finite_number(
        components.get("sell_tax_rate", components.get("tax_rate", 0.0)),
        field="sell_tax_rate",
        minimum=0.0,
    )

    if position_side == "long":
        buy_execution = entry * (1.0 + buy_slippage_rate)
        sell_execution = exit_value * (1.0 - sell_slippage_rate)
    else:
        sell_execution = entry * (1.0 - sell_slippage_rate)
        buy_execution = exit_value * (1.0 + buy_slippage_rate)
    buy_notional = buy_execution
    sell_notional = sell_execution
    buy_commission = buy_notional * buy_commission_rate
    sell_commission = sell_notional * sell_commission_rate
    # Report the slippage on the leg where it was applied.  For a long
    # position the buy leg uses the entry quote and the sell leg uses the
    # exit quote; a short position reverses those base quotes.
    buy_base = entry if position_side == "long" else exit_value
    sell_base = exit_value if position_side == "long" else entry
    buy_slippage = abs(buy_execution - buy_base)
    sell_slippage = abs(sell_execution - sell_base)
    sell_tax = sell_notional * sell_tax_rate

    if position_side == "long":
        entry_cash_flow = buy_notional + buy_commission
        exit_cash_flow = sell_notional - sell_commission - sell_tax
        gross = exit_value / entry - 1.0
        net = exit_cash_flow / entry_cash_flow - 1.0
    else:
        # A short opens with a sell at the entry date and closes with a buy at
        # the exit date, mirroring the same BrokerSimulator leg economics.
        entry_cash_flow = sell_notional - sell_commission - sell_tax
        exit_cash_flow = exit_value * (1.0 + buy_slippage_rate) * (1.0 + buy_commission_rate)
        gross = entry / exit_value - 1.0
        net = entry_cash_flow / exit_cash_flow - 1.0
    transaction_cost = gross - net
    return {
        "position_side": position_side,
        "buy_execution_price": buy_execution,
        "sell_execution_price": sell_execution,
        "buy_slippage_amount": buy_slippage,
        "sell_slippage_amount": sell_slippage,
        "buy_commission_amount": buy_commission,
        "sell_commission_amount": sell_commission,
        "sell_tax_amount": sell_tax,
        "entry_cash_flow": entry_cash_flow,
        "exit_cash_flow": exit_cash_flow,
        "transaction_cost_return": transaction_cost,
        "gross_return": gross,
        "net_return": net,
    }


def _normalize_cost_components(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Validate the auditable round-trip cost components.

    Numeric component values are rates and must remain finite/non-negative.
    ``formula_version`` is the sole textual field and is required whenever a
    caller supplies a formula marker.  Unknown fields are rejected so a
    caller cannot smuggle an unverified cost assumption into an outcome.
    """

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise PredictionLabError("cost policy components are invalid")
    allowed = {
        "commission_rate",
        "tax_rate",
        "slippage_rate",
        "buy_commission_rate",
        "sell_commission_rate",
        "buy_slippage_rate",
        "sell_slippage_rate",
        "sell_tax_rate",
        "total_rate",
        "formula_version",
        "position_side",
        "buy_execution_price",
        "sell_execution_price",
        "buy_slippage_amount",
        "sell_slippage_amount",
        "buy_commission_amount",
        "sell_commission_amount",
        "sell_tax_amount",
        "entry_cash_flow",
        "exit_cash_flow",
        "transaction_cost_return",
        "gross_return",
        "net_return",
    }
    if set(str(key) for key in value) - allowed:
        raise PredictionLabError("cost policy components contain unknown fields")
    normalized: dict[str, Any] = {}
    for key, raw in value.items():
        name = str(key)
        if name == "formula_version":
            if not isinstance(raw, str) or not raw.strip():
                raise PredictionLabError("cost formula version is invalid")
            normalized[name] = raw.strip()
        elif name == "position_side":
            if raw not in {"long", "short"}:
                raise PredictionLabError("cost position side is invalid")
            normalized[name] = str(raw)
        else:
            minimum = (
                0.0
                if name
                in {
                    "commission_rate",
                    "tax_rate",
                    "slippage_rate",
                    "buy_commission_rate",
                    "sell_commission_rate",
                    "buy_slippage_rate",
                    "sell_slippage_rate",
                    "sell_tax_rate",
                    "total_rate",
                    "buy_execution_price",
                    "sell_execution_price",
                    "buy_slippage_amount",
                    "sell_slippage_amount",
                    "buy_commission_amount",
                    "sell_commission_amount",
                    "sell_tax_amount",
                    "entry_cash_flow",
                    "exit_cash_flow",
                }
                else None
            )
            normalized[name] = _finite_number(
                raw,
                field=f"cost_components.{name}",
                **({"minimum": minimum} if minimum is not None else {}),
            )
    if "total_rate" in normalized:
        leg_names = (
            "buy_commission_rate",
            "sell_commission_rate",
            "buy_slippage_rate",
            "sell_slippage_rate",
            "sell_tax_rate",
        )
        if all(name in normalized for name in leg_names):
            expected = sum(float(normalized[name]) for name in leg_names)
            if not math.isclose(
                float(normalized["total_rate"]), expected, rel_tol=0.0, abs_tol=1e-12
            ):
                raise PredictionLabError("cost policy total rate is not reproducible")
    return normalized


def default_prediction_cost_policy(market: str) -> PredictionCostPolicy:
    """Return the existing versioned research cost assumptions by market."""

    parsed = Market.parse(market)
    if parsed in {Market.TWSE, Market.TPEX}:
        return PredictionCostPolicy(
            market=parsed.value,
            version="backtest-cost-policy-v1",
            commission_rate=0.001425,
            tax_rate=0.003,
            slippage_rate=0.001,
        )
    if parsed is Market.US:
        return PredictionCostPolicy(
            market=parsed.value,
            version="backtest-cost-policy-v1",
            commission_rate=0.001,
            tax_rate=0.0,
            slippage_rate=0.001,
        )
    raise PredictionLabError("prediction cost policy is unavailable for market")


def _action_payload_hash(value: Any) -> str | None:
    """Extract one source payload hash from an action evidence mapping."""

    if not isinstance(value, Mapping):
        return None
    for key in ("payload_hash", "payload_sha256", "raw_payload_sha256", "source_payload_hash"):
        raw = value.get(key)
        if raw is None:
            continue
        try:
            return _hashes((str(raw),))[0]
        except PredictionLabError:
            return None
    return None


def _normalize_corporate_action_coverage(value: Any) -> dict[str, Any]:
    """Validate an explicit source-backed no-action coverage interval."""

    if not isinstance(value, Mapping):
        raise PredictionLabError("corporate action coverage is invalid")
    source = value.get("source")
    start = value.get("coverage_start", value.get("start_date"))
    end = value.get("coverage_end", value.get("end_date"))
    confirmed = value.get("no_action_confirmed")
    policy_version = value.get("policy_version")
    payload_hash = _action_payload_hash(value)
    if (
        not isinstance(source, str)
        or not source.strip()
        or not isinstance(start, str)
        or not isinstance(end, str)
        or not isinstance(confirmed, bool)
        or not confirmed
        or not isinstance(policy_version, str)
        or not policy_version.strip()
        or payload_hash is None
    ):
        raise PredictionLabError("corporate action coverage is incomplete")
    start_date = _date(start, field="corporate action coverage start date")
    end_date = _date(end, field="corporate action coverage end date")
    if start_date > end_date:
        raise PredictionLabError("corporate action coverage range is invalid")
    return {
        "source": source.strip(),
        "coverage_start": start_date,
        "coverage_end": end_date,
        "payload_hash": payload_hash,
        "policy_version": policy_version.strip(),
        "no_action_confirmed": True,
    }


def _row_corporate_action_event(evidence: Any, *, row_date: str) -> dict[str, Any]:
    """Normalize persisted sidecar evidence without trusting transient flags."""

    event: dict[str, Any] = {
        "effective_date": row_date,
        "available_date": None,
        "requires_availability": False,
        "valid": False,
        "event_id": "",
        "terms": "",
    }
    if not isinstance(evidence, Mapping):
        return event
    effective = evidence.get("effective_date") or row_date
    source = evidence.get("source")
    payload_hash = _action_payload_hash(evidence)
    policy_version = evidence.get("policy_version")
    try:
        effective_date = _date(effective, field="corporate action effective date")
        available_raw = evidence.get("available_date")
        available_date = (
            _date(available_raw, field="corporate action available date")
            if available_raw is not None and str(available_raw).strip()
            else None
        )
    except PredictionLabError:
        return event
    if not isinstance(source, str) or not source.strip() or not payload_hash:
        return event
    policy_value = evidence.get("adjusted_raw_policy")
    if isinstance(policy_value, str):
        policy_value = policy_value.strip().lower()
    event.update(
        {
            "effective_date": effective_date,
            "available_date": available_date,
            "requires_availability": True,
            "source": source.strip(),
            "payload_hash": payload_hash,
            "policy_version": str(policy_version or "").strip(),
            "adjusted_raw_policy": policy_value,
            "event_id": str(evidence.get("event_id") or _sha(dict(sorted(evidence.items())))),
            "terms": str(
                evidence.get("terms")
                or _sha(
                    {
                        "source": source.strip(),
                        "effective_date": effective_date,
                        "policy_version": str(policy_version or "").strip(),
                        "action_type": evidence.get("action_type"),
                        "split_ratio": evidence.get("split_ratio"),
                        "cash_per_share": evidence.get("cash_per_share"),
                        "currency": evidence.get("currency"),
                        "payable_date": evidence.get("payable_date"),
                        "tax_rate": evidence.get("tax_rate"),
                    }
                )
            ),
            "valid": True,
        }
    )
    return event


def _corporate_action_event(action: Any) -> dict[str, Any]:
    """Convert an existing ``CorporateAction`` (or strict mapping) to evidence."""

    if hasattr(action, "symbol") and hasattr(action, "effective_date"):
        symbol = getattr(action, "symbol")
        identity = getattr(symbol, "canonical", None)
        source = getattr(action, "source", None)
        effective = getattr(action, "effective_date", None)
        available = getattr(action, "available_date", None)
        confidence = str(getattr(action, "confidence", "unknown")).lower()
        completeness = str(getattr(action, "completeness", "unknown")).lower()
        event_id = str(getattr(action, "event_id", ""))
        terms = str(getattr(action, "economic_terms_key", ""))
        provenance = getattr(action, "provenance", {})
        source_evidence = getattr(action, "source_evidence", ())
        evidence_values = [provenance, *tuple(source_evidence or ())]
        payload_hash = next((_action_payload_hash(item) for item in evidence_values), None)
        policy = provenance.get("adjusted_raw_policy") if isinstance(provenance, Mapping) else None
        if isinstance(policy, str):
            policy = policy.strip().lower()
        policy_version = (
            provenance.get("policy_version") if isinstance(provenance, Mapping) else None
        )
        coverage: dict[str, Any] | None = None
        for evidence in evidence_values:
            if isinstance(evidence, Mapping) and evidence.get("no_action_confirmed") is True:
                try:
                    coverage = _normalize_corporate_action_coverage(evidence)
                except PredictionLabError:
                    coverage = None
                if coverage is not None:
                    break
        valid = (
            isinstance(identity, str)
            and isinstance(source, str)
            and bool(source.strip())
            and isinstance(effective, str)
            and payload_hash is not None
            and confidence == "complete"
            and completeness == "complete"
            and bool(available)
        )
        if not isinstance(identity, str) or not isinstance(effective, str):
            return {
                "identity": "",
                "effective_date": "",
                "valid": False,
                "requires_availability": True,
                "event_id": event_id,
                "terms": terms,
            }
        try:
            canonical = _parse_canonical_identity(identity).canonical
            effective_date = _date(effective, field="corporate action effective date")
            available_date = (
                _date(available, field="corporate action available date") if available else None
            )
        except PredictionLabError:
            canonical = ""
            effective_date = ""
            available_date = None
            valid = False
        return {
            "identity": canonical,
            "effective_date": effective_date,
            "available_date": available_date,
            "requires_availability": True,
            "valid": valid and bool(canonical),
            "event_id": event_id,
            "terms": terms or _sha(getattr(action, "to_dict", lambda: {})()),
            "source": str(source or ""),
            "payload_hash": payload_hash,
            "policy_version": str(policy_version or "").strip(),
            "adjusted_raw_policy": policy,
            "coverage": coverage,
        }
    if not isinstance(action, Mapping):
        raise PredictionLabError("corporate action evidence is invalid")
    identity_value = action.get("identity")
    if (
        identity_value is None
        and action.get("market") is not None
        and action.get("symbol") is not None
    ):
        identity_value = f"{action.get('market')}:{action.get('symbol')}"
    try:
        identity = _parse_canonical_identity(identity_value).canonical
        effective = _date(action.get("effective_date"), field="corporate action effective date")
        available = (
            _date(action.get("available_date"), field="corporate action available date")
            if action.get("available_date")
            else None
        )
    except PredictionLabError:
        return {
            "identity": "",
            "effective_date": "",
            "valid": False,
            "requires_availability": True,
            "event_id": "",
            "terms": "",
        }
    payload_hash = _action_payload_hash(action)
    source = action.get("source")
    valid = isinstance(source, str) and bool(source.strip()) and payload_hash is not None
    coverage_evidence: dict[str, Any] | None = None
    if action.get("no_action_confirmed") is True:
        try:
            coverage_evidence = _normalize_corporate_action_coverage(action)
        except PredictionLabError:
            coverage_evidence = None
    policy_value = action.get("adjusted_raw_policy")
    if isinstance(policy_value, str):
        policy_value = policy_value.strip().lower()
    return {
        "identity": identity,
        "effective_date": effective,
        "available_date": available,
        "requires_availability": True,
        "valid": valid,
        "event_id": str(action.get("event_id") or _sha(dict(sorted(action.items())))),
        "terms": _sha(
            {
                "action_type": action.get("action_type"),
                "effective_date": effective,
                "split_ratio": action.get("split_ratio"),
                "cash_per_share": action.get("cash_per_share"),
            }
        ),
        "source": str(source or ""),
        "payload_hash": payload_hash,
        "adjusted_raw_policy": policy_value,
        "coverage": coverage_evidence,
    }


_BENCHMARK_BY_MARKET = {
    "TWSE": "TWSE:TAIEX",
    "TPEX": "TPEX:OTC",
    "US": "US:SPX",
}


class RuntimeCachedOutcomeProvider:
    """Strict read-only outcome provider over validated market-qualified rows.

    This adapter is shared by dashboard, scheduler and packaged headless
    composition.  It never refreshes or writes data; its calendar is the
    bundled, versioned market calendar rather than a date list inferred from
    whichever security rows happen to be cached.
    """

    strict_evidence = True

    def __init__(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        price_policy: str = "raw",
        corporate_actions: Sequence[Any] = (),
    ) -> None:
        if price_policy not in {"raw", "adjusted"}:
            raise PredictionLabError("unsupported corporate-action price policy")
        self.price_policy = price_policy
        self._records = tuple(dict(record) for record in records)
        self._by_identity: dict[str, list[Mapping[str, Any]]] = {}
        self._corporate_actions: dict[str, list[dict[str, Any]]] = {}
        self._corporate_action_coverage: dict[str, list[dict[str, Any]]] = {}
        for raw in self._records:
            symbol = str(raw.get("symbol", "")).strip()
            market = str(raw.get("market", "")).strip()
            parsed = _market_symbol(market, symbol)
            self._by_identity.setdefault(parsed.canonical, []).append(dict(raw))
            raw_coverage = raw.get("corporate_action_coverage")
            if raw_coverage is not None:
                try:
                    coverage = _normalize_corporate_action_coverage(raw_coverage)
                except PredictionLabError:
                    coverage = None
                if coverage is not None:
                    self._corporate_action_coverage.setdefault(parsed.canonical, []).append(
                        coverage
                    )
            if raw.get("corporate_action_required"):
                evidence = raw.get("corporate_action_evidence")
                self._corporate_actions.setdefault(parsed.canonical, []).append(
                    _row_corporate_action_event(evidence, row_date=str(raw.get("date", "")))
                )
            elif raw.get("corporate_action_evidence") is not None:
                self._corporate_actions.setdefault(parsed.canonical, []).append(
                    _row_corporate_action_event(
                        raw.get("corporate_action_evidence"), row_date=str(raw.get("date", ""))
                    )
                )
        for action in corporate_actions:
            if isinstance(action, Mapping) and action.get("no_action_confirmed") is True:
                identity_value = action.get("identity")
                if (
                    identity_value is None
                    and action.get("market") is not None
                    and action.get("symbol") is not None
                ):
                    identity_value = f"{action.get('market')}:{action.get('symbol')}"
                try:
                    identity = _parse_canonical_identity(identity_value).canonical
                    coverage = _normalize_corporate_action_coverage(action)
                except PredictionLabError:
                    identity = ""
                    coverage = None
                if coverage is not None:
                    self._corporate_action_coverage.setdefault(identity, []).append(coverage)
                    continue
            event = _corporate_action_event(action)
            self._corporate_actions.setdefault(event["identity"], []).append(event)
            coverage = event.get("coverage")
            if coverage is not None:
                self._corporate_action_coverage.setdefault(event["identity"], []).append(coverage)
        for rows in self._by_identity.values():
            rows.sort(key=lambda row: str(row.get("date", "")))
        for events in self._corporate_actions.values():
            events.sort(
                key=lambda item: (
                    str(item.get("effective_date", "")),
                    str(item.get("event_id", "")),
                )
            )
        for coverage_rows in self._corporate_action_coverage.values():
            coverage_rows.sort(
                key=lambda item: (
                    str(item.get("coverage_start", "")),
                    str(item.get("coverage_end", "")),
                    str(item.get("payload_hash", "")),
                )
            )

    @staticmethod
    def _payload_hash(rows: Sequence[Mapping[str, Any]]) -> str:
        supplied = [
            str(row.get("payload_sha256") or "").strip().lower()
            for row in rows
            if row.get("payload_sha256")
        ]
        if len(supplied) == len(rows) and supplied:
            _hashes(supplied)
            return supplied[0] if len(supplied) == 1 else _sha(supplied)
        return _sha([dict(sorted(row.items())) for row in rows])

    def calendar(self, market: str) -> MarketTradingCalendar:
        # Do not infer a trading calendar from local security rows.  The
        # explicit bundled calendar is versioned and persisted in outcomes.
        return MarketTradingCalendar.default_for(market)

    def price(self, identity: str, effective_date: str) -> PriceEvidence | None:
        parsed = _parse_canonical_identity(identity)
        rows = self._by_identity.get(parsed.canonical, ())
        row = next((item for item in rows if str(item.get("date")) == effective_date), None)
        if row is None:
            return None
        if row.get("corporate_action_required") and not row.get("corporate_action_evidence"):
            # A row that advertises an action without its source-backed
            # adjustment evidence is retryable, never silently raw.
            return None
        action_evidence = row.get("corporate_action_evidence")
        if isinstance(action_evidence, Mapping):
            policy = action_evidence.get("adjusted_raw_policy")
            if policy is not None and policy != self.price_policy:
                return None
        price_field = "adjusted_close" if self.price_policy == "adjusted" else "close"
        value = row.get(price_field)
        if value is None:
            return None
        return PriceEvidence(
            identity=parsed.canonical,
            value=_finite_number(value, field="price", minimum=1e-12),
            effective_trading_date=effective_date,
            provider=str(row.get("provider") or "local-cache"),
            payload_hash=self._payload_hash((row,)),
            price_field=price_field,
            adjusted_raw_policy=self.price_policy,
        )

    def corporate_action_status(
        self, identity: str, start_date: str, end_date: str
    ) -> tuple[str, str | None]:
        """Return whether action evidence is sufficient for an evaluation window.

        The sidecar rows and the existing ``CorporateAction`` contract are
        normalized into one read-only evidence view.  A missing or conflicting
        action record is retryable; it never gets interpreted as proof that no
        action occurred.
        """

        parsed = _parse_canonical_identity(identity)
        start = _date(start_date, field="corporate action start date")
        end = _date(end_date, field="corporate action end date")
        if start > end:
            raise PredictionLabError("corporate action date range is invalid")
        events = [
            event
            for event in self._corporate_actions.get(parsed.canonical, ())
            if start <= str(event.get("effective_date", "")) <= end
        ]
        if not events:
            # An empty action list is not evidence that no action occurred.
            # Only an explicit, source-backed coverage interval may clear the
            # corporate-action gate.
            for coverage in self._corporate_action_coverage.get(parsed.canonical, ()):
                try:
                    coverage_start = _date(
                        coverage.get("coverage_start"),
                        field="corporate action coverage start date",
                    )
                    coverage_end = _date(
                        coverage.get("coverage_end"),
                        field="corporate action coverage end date",
                    )
                    payload_hash = _action_payload_hash(coverage)
                except PredictionLabError:
                    continue
                if (
                    coverage.get("no_action_confirmed") is True
                    and payload_hash is not None
                    and coverage_start <= start
                    and coverage_end >= end
                ):
                    return "clear", None
            return "insufficient", "公司行動缺少涵蓋該期間的來源證據；可稍後重試"
        seen: dict[tuple[str, str], str] = {}
        for event in events:
            effective = str(event.get("effective_date", ""))
            event_id = str(event.get("event_id", ""))
            key = (effective, event_id or "unknown")
            if not event.get("valid"):
                return "insufficient", "公司行動缺少可驗證來源證據；可稍後重試"
            policy = event.get("adjusted_raw_policy")
            if policy not in {"raw", "adjusted"}:
                return "insufficient", "公司行動缺少明確的 raw/adjusted 價格政策；可稍後重試"
            if policy != self.price_policy:
                return "insufficient", "公司行動的價格政策與結算資料不一致；可稍後重試"
            # The evaluator currently has no economic adjustment engine for
            # raw prices.  Even a source-backed event explicitly labelled
            # ``raw`` must therefore remain retryable; otherwise a split or
            # dividend can be misread as a negative/positive performance.
            if self.price_policy == "raw":
                return "insufficient", "公司行動尚未套用 raw 價格調整；可稍後重試"
            available = event.get("available_date")
            if (
                available is not None
                and _date(available, field="corporate action available date") > end
            ):
                return "insufficient", "公司行動證據尚未到可驗證日期；可稍後重試"
            if available is None and event.get("requires_availability"):
                return "insufficient", "公司行動缺少可驗證公布日期；可稍後重試"
            terms = str(event.get("terms", ""))
            prior = seen.get(key)
            if prior is not None and prior != terms:
                return "insufficient", "公司行動來源互相衝突；可稍後重試"
            seen[key] = terms
        if self.price_policy == "adjusted":
            # An adjusted event is safe only when both endpoint observations
            # actually expose the adjusted series consumed by the evaluator.
            # A matching event label alone must not turn a raw-only cache into
            # a clear/evaluable window.
            required_dates = {start, end}
            endpoint_rows = [
                row
                for row in self._by_identity.get(parsed.canonical, ())
                if str(row.get("date", "")) in required_dates
            ]
            if len(endpoint_rows) != len(required_dates) or any(
                row.get("adjusted_close") is None for row in endpoint_rows
            ):
                return "insufficient", "公司行動缺少 adjusted_close 價格證據；可稍後重試"
            try:
                for row in endpoint_rows:
                    _finite_number(
                        row.get("adjusted_close"),
                        field="adjusted_close",
                        minimum=1e-12,
                    )
            except PredictionLabError:
                return "insufficient", "公司行動缺少有效 adjusted_close 價格證據；可稍後重試"
        return "clear", None

    def benchmark(
        self,
        identity: str,
        effective_date: str,
        start_date: str | None = None,
    ) -> BenchmarkEvidence | None:
        parsed = _parse_canonical_identity(identity)
        expected = _BENCHMARK_BY_MARKET.get(parsed.market.value)
        if expected != parsed.canonical:
            return None
        rows = self._by_identity.get(parsed.canonical, ())
        end = next((item for item in rows if str(item.get("date")) == effective_date), None)
        if end is None:
            return None
        start_row: Mapping[str, Any] | None = None
        if start_date is not None:
            start_row = next((item for item in rows if str(item.get("date")) == start_date), None)
        else:
            prior = [item for item in rows if str(item.get("date", "")) < effective_date]
            start_row = prior[-1] if prior else None
        if start_row is None:
            return None
        if any(
            item.get("corporate_action_required") and not item.get("corporate_action_evidence")
            for item in (start_row, end)
        ):
            return None
        for item in (start_row, end):
            action_evidence = item.get("corporate_action_evidence")
            if isinstance(action_evidence, Mapping):
                policy = action_evidence.get("adjusted_raw_policy")
                if policy is not None and policy != self.price_policy:
                    return None
        price_field = "adjusted_close" if self.price_policy == "adjusted" else "close"
        start_raw = start_row.get(price_field)
        end_raw = end.get(price_field)
        if start_raw is None or end_raw is None:
            return None
        start_value = _finite_number(start_raw, field="benchmark start", minimum=1e-12)
        end_value = _finite_number(end_raw, field="benchmark end", minimum=1e-12)
        payload_hashes = (
            self._payload_hash((start_row,)),
            self._payload_hash((end,)),
        )
        return BenchmarkEvidence(
            identity=parsed.canonical,
            return_value=end_value / start_value - 1.0,
            effective_trading_date=effective_date,
            provider=str(end.get("provider") or "local-cache"),
            payload_hash=self._payload_hash((start_row, end)),
            start_trading_date=str(start_row["date"]),
            end_trading_date=str(end["date"]),
            start_value=start_value,
            end_value=end_value,
            price_field=price_field,
            adjusted_raw_policy=self.price_policy,
            payload_hashes=payload_hashes,
            provider_symbol=(
                str(end.get("provider_symbol")) if end.get("provider_symbol") is not None else None
            ),
            source_type=(
                str(end.get("source_type")) if end.get("source_type") is not None else None
            ),
            checked_at=(str(end.get("checked_at")) if end.get("checked_at") is not None else None),
            fetched_at=(str(end.get("fetched_at")) if end.get("fetched_at") is not None else None),
        )


_BENCHMARK_PROVIDER_SYMBOLS: Mapping[str, str] = {
    "TWSE": "^TWII",
    "TPEX": "^TWO",
    "US": "^GSPC",
}

# Taiwan benchmark indexes have authoritative exchange endpoints.  Keep the
# existing automatic provider contract for US (where the project has no
# bundled exchange feed), but do not route the two Taiwan indexes through a
# security-ticker suffix resolver.  The response bytes are hashed before any
# normalization so the persisted benchmark retains source provenance.
_OFFICIAL_BENCHMARK_ENDPOINTS: Mapping[str, str] = {
    "TWSE": "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?response=json&date=",
    "TPEX": "https://www.tpex.org.tw/openapi/v1/tpex_index",
}


@dataclass(frozen=True, slots=True)
class BenchmarkRefreshResult:
    """Result of one bounded benchmark refresh/persistence attempt."""

    status: str
    identities: tuple[str, ...] = ()
    source_type: str | None = None
    warnings: tuple[str, ...] = ()
    fetched_at: str | None = None
    payload_hashes: Mapping[str, str] = field(default_factory=dict)


class BenchmarkRefreshService:
    """Refresh and persist the three market benchmarks through the existing provider path.

    The service is deliberately separate from :class:`RuntimeCachedOutcomeProvider`:
    the provider remains read-only, while this application boundary performs an
    explicit user/scheduler-triggered refresh and then reloads a fresh provider.
    A callable/object fetcher is injectable for deterministic installed-like
    tests; the default uses the existing ``fetch_prices_result`` contract.
    """

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        fetcher: Any | None = None,
        now_fn: Callable[[], datetime] | None = None,
        cache_dir: str | os.PathLike[str] | None = None,
        log_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.fetcher = fetcher
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.cache_dir = (
            Path(cache_dir) if cache_dir is not None else self.database_path.parent / "cache"
        )
        self.log_dir = Path(log_dir) if log_dir is not None else self.database_path.parent / "logs"

    @staticmethod
    def provider_symbol(market: str) -> str:
        canonical = str(market).strip().upper()
        try:
            return _BENCHMARK_PROVIDER_SYMBOLS[canonical]
        except KeyError as exc:
            raise PredictionLabError("benchmark market is unavailable") from exc

    def refresh(self, *, markets: Sequence[str] = ("TWSE", "TPEX", "US")) -> BenchmarkRefreshResult:
        requested = tuple(dict.fromkeys(str(item).strip().upper() for item in markets))
        if not requested or any(item not in _BENCHMARK_PROVIDER_SYMBOLS for item in requested):
            return BenchmarkRefreshResult(
                "unavailable", warnings=("benchmark market is unavailable",)
            )
        fetched: list[tuple[str, Mapping[str, Any], list[dict[str, Any]]]] = []
        errors: list[str] = []
        payload_hashes: dict[str, str] = {}
        for market in requested:
            provider_symbol = self.provider_symbol(market)
            try:
                raw = self._fetch(market, provider_symbol)
                meta, records = self._normalize_fetch(market, provider_symbol, raw)
                payload_hash = str(meta.get("payload_sha256") or "")
                if not payload_hash:
                    # Mapping-based fetchers do not have a cache file whose
                    # bytes can be hashed.  Hash the provider payload shape
                    # (including its raw metadata and observations), rather
                    # than the normalized records alone, so provenance remains
                    # tied to the response that was received.
                    payload_hash = _sha(
                        {
                            "metadata": (
                                {
                                    key: value
                                    for key, value in dict(raw).items()
                                    if key not in {"records", "data"}
                                }
                                if isinstance(raw, Mapping)
                                else {"records": records}
                            ),
                            "records": records,
                        }
                    )
                _hashes((payload_hash,))
                payload_hashes[market] = payload_hash
                fetched.append((market, meta, records))
            except Exception as exc:
                errors.append(f"{market}: {_safe_reason(type(exc).__name__)}")
        if errors:
            # Benchmarks are one atomic evidence set.  Do not persist a
            # subset and combine new rows with stale identities on reload.
            return BenchmarkRefreshResult(
                "unavailable" if not fetched else "partial",
                warnings=tuple(errors),
                fetched_at=(
                    max(str(meta.get("fetched_at")) for _, meta, _ in fetched) if fetched else None
                ),
                payload_hashes=payload_hashes,
            )
        from stock_tool.data.storage import PersistedPriceProvenance, SQLitePriceStorage

        storage = SQLitePriceStorage(self.database_path)
        identities: list[str] = []
        observed_at: list[str] = []
        source_types: set[str] = set()
        try:
            batch: list[tuple[list[dict[str, Any]], PersistedPriceProvenance]] = []
            for market, meta, records in fetched:
                parsed = _market_symbol(market, str(meta["symbol"]))
                payload_hash = payload_hashes[market]
                for record in records:
                    record.setdefault("payload_sha256", payload_hash)
                    record.setdefault("provider", str(meta["provider"]))
                # A refresh must carry the provider's actual observation time;
                # substituting the local clock would make an unverifiable
                # response look freshly fetched.
                fetched_at = str(meta["fetched_at"])
                batch.append(
                    (
                        records,
                        PersistedPriceProvenance(
                            symbol=parsed,
                            provider=str(meta["provider"]),
                            provider_symbol=str(meta["provider_symbol"]),
                            source_type=str(meta["source_type"]),
                            last_data_date=str(meta["last_data_date"]),
                            checked_at=fetched_at,
                            fetched_at=fetched_at,
                            payload_sha256=payload_hash,
                        ),
                    )
                )
                identities.append(parsed.canonical)
                observed_at.append(fetched_at)
                source_types.add(str(meta["source_type"]))
            storage.save_market_qualified_price_batch(batch)
        except Exception as exc:
            return BenchmarkRefreshResult(
                "unavailable",
                (),
                None,
                tuple(errors)
                + (f"benchmark persistence failed: {_safe_reason(type(exc).__name__)}",),
                max(observed_at) if observed_at else None,
                payload_hashes,
            )
        status = "fresh" if not errors and len(fetched) == len(requested) else "partial"
        return BenchmarkRefreshResult(
            status,
            tuple(identities),
            sorted(source_types)[0] if source_types else None,
            tuple(errors),
            max(observed_at) if observed_at else None,
            payload_hashes,
        )

    def load_provider(self, *, price_policy: str = "raw") -> RuntimeCachedOutcomeProvider | None:
        return build_runtime_cached_outcome_provider(self.database_path, price_policy=price_policy)

    def _fetch(self, market: str, provider_symbol: str) -> Any:
        if self.fetcher is not None:
            method = getattr(self.fetcher, "fetch", None)
            if callable(method):
                try:
                    return method(market, provider_symbol)
                except TypeError:
                    return method(market)
            if callable(self.fetcher):
                try:
                    return self.fetcher(market, provider_symbol)
                except TypeError:
                    return self.fetcher(market)
        if market in _OFFICIAL_BENCHMARK_ENDPOINTS:
            return self._fetch_official_index(market, provider_symbol)
        # Reuse the established provider contract.  This is only called by an
        # explicit refresh action; render/replay continues using the sidecar.
        from stock_tool.data.auto_fetch import default_date_range, fetch_prices_result

        start, end = default_date_range(None, None)
        return fetch_prices_result(
            provider_symbol,
            market=cast(Literal["TWSE", "TPEX", "US", "TW", "TPEx", "AUTO", "CUSTOM"], market),
            start=start,
            end=end,
            interval="1d",
            provider="auto",
            use_cache=True,
            force_refresh=True,
            cache_dir=self.cache_dir,
            log_dir=self.log_dir,
            contracts_enabled=True,
        )

    def _fetch_official_index(self, market: str, provider_symbol: str) -> Mapping[str, Any]:
        """Fetch one Taiwan benchmark from its exchange-owned index endpoint.

        This path is deliberately limited to the two index feeds listed in
        ``_OFFICIAL_BENCHMARK_ENDPOINTS``.  It does not alter the general
        security provider order, and it returns the raw response digest so a
        later sidecar reload can prove which exchange payload was used.
        """

        endpoint = _OFFICIAL_BENCHMARK_ENDPOINTS[market]
        if market == "TWSE":
            now = self.now_fn()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            endpoint = endpoint + now.astimezone(timezone.utc).strftime("%Y%m%d")
        request = urllib.request.Request(
            endpoint,
            headers={
                "Accept": "application/json",
                "User-Agent": "StockTool benchmark refresh/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
        payload_hash = hashlib.sha256(payload).hexdigest()
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PredictionLabError("official benchmark payload is invalid") from exc

        if market == "TWSE":
            records = _parse_twse_index_payload(decoded)
            provider = "twse-official"
        else:
            records = _parse_tpex_index_payload(decoded)
            provider = "tpex-official"
        if not records:
            raise PredictionLabError("official benchmark observations are unavailable")
        fetched_now = self.now_fn()
        if fetched_now.tzinfo is None:
            fetched_now = fetched_now.replace(tzinfo=timezone.utc)
        return {
            "market": market,
            "symbol": _BENCHMARK_IDENTITY_BY_MARKET[market].split(":", 1)[1],
            "provider": provider,
            "provider_symbol": provider_symbol,
            "source_type": "online",
            "last_data_date": _last_record_date(records),
            # ``now_fn`` is injectable for deterministic tests and may return
            # a naive datetime.  Treat a naive value as UTC at this boundary
            # rather than raising after the network response was received.
            "fetched_at": _iso(fetched_now),
            "payload_sha256": payload_hash,
            "records": records,
        }

    @staticmethod
    def _normalize_fetch(
        market: str, provider_symbol: str, raw: Any
    ) -> tuple[Mapping[str, Any], list[dict[str, Any]]]:
        if isinstance(raw, Mapping):
            meta = dict(raw)
            nested_metadata = meta.get("metadata")
            metadata_source: Mapping[str, Any] = (
                nested_metadata if isinstance(nested_metadata, Mapping) else meta
            )

            def metadata_value(name: str, default: Any = None) -> Any:
                value = meta.get(name)
                if value is None and metadata_source is not meta:
                    value = metadata_source.get(name)
                return default if value is None else value

            records = meta.get("records")
            if not isinstance(records, list):
                data = meta.get("data")
                to_dict = getattr(data, "to_dict", None)
                converted = to_dict(orient="records") if callable(to_dict) else None
                records = converted if isinstance(converted, list) else None
            if not isinstance(records, list):
                raise PredictionLabError("benchmark payload has no records")
            metadata_market = _enum_value(metadata_value("market", market))
            metadata = {
                # Preserve the provider-declared market so a conflicting
                # response is rejected below instead of being overwritten by
                # the requested market before validation.
                "market": str(metadata_market).strip().upper(),
                "symbol": str(
                    metadata_value("symbol")
                    or _BENCHMARK_IDENTITY_BY_MARKET[market].split(":", 1)[1]
                ),
                "provider": _enum_value(metadata_value("provider")),
                "provider_symbol": _enum_value(
                    metadata_value("provider_symbol") or provider_symbol
                ),
                "source_type": _enum_value(metadata_value("source_type", "online")),
                "last_data_date": metadata_value("last_data_date") or _last_record_date(records),
                "fetched_at": metadata_value("fetched_at"),
                "payload_sha256": metadata_value("payload_sha256")
                or metadata_value("payload_hash"),
                "cache_path": metadata_value("cache_path") or metadata_value("cache_file"),
            }
            if not isinstance(metadata["provider"], str) or not str(metadata["provider"]).strip():
                raise PredictionLabError("benchmark provider is required")
            metadata["provider"] = str(metadata["provider"]).strip()
            if "yfinance" in metadata["provider"].lower():
                metadata["provider"] = "yfinance"
            metadata["provider_symbol"] = str(metadata["provider_symbol"]).strip().upper()
            metadata["source_type"] = str(_enum_value(metadata["source_type"])).strip().lower()
            if not metadata["payload_sha256"] and not metadata.get("cache_path"):
                try:
                    metadata["payload_sha256"] = _sha(
                        {
                            "metadata": {
                                key: value
                                for key, value in meta.items()
                                if key not in {"records", "data"}
                            },
                            "records": records,
                        }
                    )
                except (TypeError, ValueError):
                    # The refresh caller will still validate the resulting
                    # digest; this fallback keeps unusual mapping values from
                    # bypassing the explicit payload-hash contract.
                    metadata["payload_sha256"] = None
        else:
            metadata_obj = getattr(raw, "metadata", None)
            data = getattr(raw, "data", None)
            to_dict = getattr(data, "to_dict", None)
            converted = to_dict(orient="records") if callable(to_dict) else None
            records = converted if isinstance(converted, list) else None
            cache_path_value = (
                getattr(metadata_obj, "cache_path", None)
                or getattr(raw, "cache_path", None)
                or getattr(raw, "cache_file", None)
            )
            payload_hash = getattr(metadata_obj, "payload_sha256", None)
            if payload_hash is None:
                payload_hash = getattr(metadata_obj, "payload_hash", None)
            if payload_hash is None:
                payload_hash = getattr(raw, "payload_sha256", None)
            if payload_hash is None:
                payload_hash = getattr(raw, "payload_hash", None)
            if payload_hash is None and cache_path_value is not None:
                try:
                    cache_path = Path(cache_path_value)
                    if cache_path.is_file():
                        payload_hash = hashlib.sha256(cache_path.read_bytes()).hexdigest()
                except (OSError, TypeError, ValueError):
                    payload_hash = None
            provider_value = _enum_value(getattr(metadata_obj, "provider", None))
            source_value = _enum_value(
                getattr(metadata_obj, "source_type", None)
                or getattr(raw, "source_type", None)
                or "online"
            )
            metadata_market = _enum_value(getattr(metadata_obj, "market", market))
            metadata = {
                "market": str(metadata_market).strip().upper(),
                "symbol": _BENCHMARK_IDENTITY_BY_MARKET[market].split(":", 1)[1],
                "provider": provider_value,
                "provider_symbol": _enum_value(
                    getattr(metadata_obj, "provider_symbol", None) or provider_symbol
                ),
                "source_type": source_value,
                "last_data_date": getattr(metadata_obj, "last_data_date", None)
                or _last_record_date(records or []),
                "fetched_at": getattr(metadata_obj, "fetched_at", None),
                "payload_sha256": payload_hash,
                "cache_path": cache_path_value,
            }
            if not isinstance(metadata["provider"], str) or not str(metadata["provider"]).strip():
                raise PredictionLabError("benchmark provider is required")
            metadata["provider"] = str(metadata["provider"]).strip()
            if "yfinance" in metadata["provider"].lower():
                metadata["provider"] = "yfinance"
            metadata["provider_symbol"] = str(metadata["provider_symbol"]).strip().upper()
            metadata["source_type"] = str(_enum_value(metadata["source_type"])).strip().lower()
            if not bool(getattr(raw, "succeeded", bool(records))):
                raise PredictionLabError("benchmark provider returned no verified data")
        cache_path_raw = metadata.get("cache_path")
        if cache_path_raw is not None:
            try:
                cache_path = Path(str(cache_path_raw))
                if not cache_path.is_file():
                    raise PredictionLabError("benchmark cache provenance is unavailable")
                actual_cache_hash = hashlib.sha256(cache_path.read_bytes()).hexdigest()
                declared_hash = metadata.get("payload_sha256")
                if (
                    declared_hash is not None
                    and str(declared_hash).strip().lower() != actual_cache_hash
                ):
                    raise PredictionLabError("benchmark payload hash mismatch")
                metadata["payload_sha256"] = actual_cache_hash
            except PredictionLabError:
                raise
            except (OSError, TypeError, ValueError) as exc:
                raise PredictionLabError("benchmark cache provenance is unavailable") from exc
        if metadata["market"] != market:
            raise PredictionLabError("benchmark market identity mismatch")
        if (
            str(metadata.get("provider_symbol") or provider_symbol).strip().upper()
            != str(provider_symbol).strip().upper()
        ):
            raise PredictionLabError("benchmark provider symbol mismatch")
        expected_symbol = _BENCHMARK_IDENTITY_BY_MARKET[market].split(":", 1)[1]
        if str(metadata["symbol"]).strip().upper() != expected_symbol:
            raise PredictionLabError("benchmark symbol identity mismatch")
        if not metadata.get("last_data_date"):
            raise PredictionLabError("benchmark data date is unavailable")
        _date(metadata["last_data_date"], field="benchmark data date")
        fetched_at = metadata.get("fetched_at")
        if not isinstance(fetched_at, str) or not fetched_at.strip():
            raise PredictionLabError("benchmark fetched_at is required")
        _aware_datetime(fetched_at, field="benchmark fetched_at")
        if str(metadata.get("source_type") or "").lower() not in {
            "online",
            "cache",
            "manual",
            "upload",
            "user_upload",
            "local_file",
        }:
            raise PredictionLabError("benchmark source type is invalid")
        if not isinstance(records, list) or not records:
            raise PredictionLabError("benchmark observations are unavailable")
        normalized: list[dict[str, Any]] = []
        for row in records:
            if not isinstance(row, Mapping):
                raise PredictionLabError("benchmark observation is invalid")
            day = str(row.get("date") or "")
            value = row.get("close", row.get("adjusted_close"))
            _date(day, field="benchmark observation date")
            _finite_number(value, field="benchmark observation", minimum=1e-12)
            normalized.append(
                {
                    "date": day,
                    "symbol": expected_symbol,
                    "open": float(row.get("open", value)),
                    "high": float(row.get("high", value)),
                    "low": float(row.get("low", value)),
                    "close": float(value),
                    "volume": float(row.get("volume", 0.0) or 0.0),
                    "adjusted_close": (
                        float(row["adjusted_close"])
                        if row.get("adjusted_close") is not None
                        else None
                    ),
                }
            )
        normalized.sort(key=lambda item: item["date"])
        if len({item["date"] for item in normalized}) != len(normalized):
            raise PredictionLabError("benchmark observations contain duplicate dates")
        return metadata, normalized


def _last_record_date(records: Sequence[Mapping[str, Any]]) -> str | None:
    dates = [str(row.get("date")) for row in records if row.get("date")]
    return max(dates) if dates else None


def _official_index_date(value: Any) -> str:
    """Normalize an exchange index date without guessing arbitrary formats."""

    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        year = int(text[:4])
        if year < 1911:
            year += 1911
        return _date(f"{year:04d}-{text[4:6]}-{text[6:8]}", field="benchmark date")
    parts = text.replace("-", "/").split("/")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        year, month, day = (int(part) for part in parts)
        if year < 1911:
            year += 1911
        return _date(f"{year:04d}-{month:02d}-{day:02d}", field="benchmark date")
    raise PredictionLabError("official benchmark date is invalid")


def _official_number(value: Any, *, field: str) -> float:
    """Parse an exchange number while rejecting placeholders and non-finite data."""

    if value is None or isinstance(value, bool):
        raise PredictionLabError(f"official benchmark {field} is invalid")
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "—", "-", "N/A", "NA"}:
        raise PredictionLabError(f"official benchmark {field} is invalid")
    try:
        parsed = float(text)
    except (TypeError, ValueError) as exc:
        raise PredictionLabError(f"official benchmark {field} is invalid") from exc
    return _finite_number(parsed, field=f"official benchmark {field}", minimum=1e-12)


def _parse_twse_index_payload(payload: Any) -> list[dict[str, Any]]:
    """Parse TWSE ``MI_5MINS_HIST`` daily index rows."""

    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise PredictionLabError("official TWSE benchmark payload has no data")
    fields = payload.get("fields")
    expected_fields = ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"]
    if fields != expected_fields:
        raise PredictionLabError("official TWSE benchmark schema is unsupported")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in payload["data"]:
        if not isinstance(raw, list) or len(raw) != len(expected_fields):
            raise PredictionLabError("official TWSE benchmark row is invalid")
        day = _official_index_date(raw[0])
        if day in seen:
            raise PredictionLabError("official TWSE benchmark has duplicate dates")
        seen.add(day)
        rows.append(
            {
                "date": day,
                "symbol": "TAIEX",
                "open": _official_number(raw[1], field="open"),
                "high": _official_number(raw[2], field="high"),
                "low": _official_number(raw[3], field="low"),
                "close": _official_number(raw[4], field="close"),
                "volume": 0.0,
                "adjusted_close": None,
            }
        )
    return sorted(rows, key=lambda row: str(row["date"]))


def _parse_tpex_index_payload(payload: Any) -> list[dict[str, Any]]:
    """Parse TPEx ``tpex_index`` daily index rows."""

    if not isinstance(payload, list):
        raise PredictionLabError("official TPEx benchmark payload has no data")
    required = {"Date", "Open", "High", "Low", "Close"}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in payload:
        if not isinstance(raw, Mapping) or set(raw) < required:
            raise PredictionLabError("official TPEx benchmark row is invalid")
        day = _official_index_date(raw["Date"])
        if day in seen:
            raise PredictionLabError("official TPEx benchmark has duplicate dates")
        seen.add(day)
        rows.append(
            {
                "date": day,
                "symbol": "OTC",
                "open": _official_number(raw["Open"], field="open"),
                "high": _official_number(raw["High"], field="high"),
                "low": _official_number(raw["Low"], field="low"),
                "close": _official_number(raw["Close"], field="close"),
                "volume": 0.0,
                "adjusted_close": None,
            }
        )
    return sorted(rows, key=lambda row: str(row["date"]))


class CorporateActionImportService:
    """Import the source-backed corporate-action contract for runtime use.

    Dashboard, manual and scheduled composition roots all consume the same
    validated loader.  Import validates the complete source bytes before an
    atomic replacement, so a malformed or partially written contract can
    never become the active runtime sidecar.
    """

    @staticmethod
    def load(path: str | os.PathLike[str]) -> tuple[Any, ...]:
        from stock_tool.data.corporate_actions import load_corporate_actions_csv

        return load_corporate_actions_csv(Path(path))

    def import_source(
        self,
        source_path: str | os.PathLike[str],
        destination_path: str | os.PathLike[str],
    ) -> tuple[Any, ...]:
        source = Path(source_path)
        destination = Path(destination_path)
        actions = self.load(source)
        try:
            payload = source.read_bytes()
        except OSError as exc:
            raise PredictionLabError("corporate action source cannot be read") from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except Exception:
            if fd >= 0:
                os.close(fd)
            temporary.unlink(missing_ok=True)
            raise
        return actions

    def import_no_action_coverage(
        self,
        database_path: str | os.PathLike[str],
        records: Sequence[Mapping[str, Any]],
        *,
        provenance: Any,
    ) -> int:
        """Persist an explicit source-backed no-action coverage contract.

        The existing market-qualified storage remains the authority for price
        rows and coverage provenance; this boundary only validates that every
        imported row carries the explicit coverage contract before delegating
        to that atomic storage API.  It is shared by all runtime composition
        roots through :func:`build_runtime_cached_outcome_provider`.
        """

        if not records:
            raise PredictionLabError("corporate action coverage import is empty")
        for record in records:
            coverage = record.get("corporate_action_coverage")
            if not isinstance(coverage, Mapping):
                raise PredictionLabError("corporate action coverage import is incomplete")
            _normalize_corporate_action_coverage(coverage)
        from stock_tool.data.storage import SQLitePriceStorage

        return SQLitePriceStorage(Path(database_path)).save_market_qualified_price_data(
            [dict(record) for record in records], provenance=provenance
        )


def build_runtime_cached_outcome_provider(
    database_path: str | os.PathLike[str],
    *,
    price_policy: str = "raw",
    corporate_actions: Sequence[Any] = (),
    corporate_actions_path: str | os.PathLike[str] | None = None,
) -> RuntimeCachedOutcomeProvider | None:
    """Build the shared strict provider from validated local sidecars.

    The optional CSV is the existing :class:`CorporateAction` contract used by
    every composition root.  A malformed file disables the provider entirely
    (rather than being treated as an empty/no-action result), while an absent
    file leaves the evaluator retryable through its normal evidence gate.
    """

    # Import lazily so the domain/evaluator module remains independent from
    # dashboard and avoids an import cycle during package startup.
    from stock_tool.data.storage import SQLitePriceStorage

    database = Path(database_path)
    context = SQLitePriceStorage(database).load_market_qualified_price_context()
    if context.warnings or not context.records:
        return None
    action_path = (
        Path(corporate_actions_path)
        if corporate_actions_path is not None
        else database.with_name("corporate_actions.csv")
    )
    loaded_actions: tuple[Any, ...] = ()
    if action_path.exists():
        if not action_path.is_file():
            return None
        try:
            loaded_actions = CorporateActionImportService.load(action_path)
        except Exception:
            # Corporate-action evidence is a trust boundary.  Returning no
            # provider is safer than silently evaluating with an incomplete or
            # corrupt action contract.
            return None
    return RuntimeCachedOutcomeProvider(
        context.records,
        price_policy=price_policy,
        corporate_actions=(*loaded_actions, *tuple(corporate_actions)),
    )


def economic_input_fingerprint(snapshot: MarketSnapshot, *, trading_date: str) -> str:
    """Hash only economics that can alter ranking/prediction records."""

    trading = _date(trading_date, field="trading_date")
    quotes = []
    for quote in snapshot.quotes:
        identity = _market_symbol(quote.market, quote.symbol).canonical
        quotes.append(
            {
                "identity": identity,
                "close": quote.close,
                "change": quote.change,
                "change_pct": quote.change_pct,
                "volume": quote.volume,
                "value": quote.value,
                "status": quote.status,
                "product_type": quote.product_type,
            }
        )
    source = [
        {
            "market": item.market,
            "data_date": item.data_date,
            "source": item.source,
            "payload_sha256": item.payload_sha256,
            "valid_rows": item.valid_rows,
            "coverage": item.coverage,
        }
        for item in snapshot.source_metadata
    ]
    metadata = {
        "market": snapshot.metadata.market,
        "data_date": snapshot.metadata.data_date,
        "payload_sha256": snapshot.metadata.payload_sha256,
        "valid_rows": snapshot.metadata.valid_rows,
        "coverage": snapshot.metadata.coverage,
    }
    selections: list[dict[str, Any]] = []
    grouped: dict[str, list[Any]] = {}
    for quote in snapshot.quotes:
        if quote.change_pct is None or not math.isfinite(float(quote.change_pct)):
            continue
        parsed_identity = _market_symbol(quote.market, quote.symbol)
        grouped.setdefault(parsed_identity.market.value, []).append(quote)
    for market, rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda row: (-float(row.change_pct), str(row.symbol).upper()))
        n = len(ordered)
        for horizon in PREDICTION_HORIZONS:
            for bucket, index in (("top", 0), ("middle", (n - 1) // 2), ("bottom", n - 1)):
                if n:
                    selected = ordered[index]
                    selections.append(
                        {
                            "market": market,
                            "symbol": str(selected.symbol).upper(),
                            "score": float(selected.change_pct),
                            "rank": index + 1,
                            "bucket": bucket,
                            "universe": n,
                            "horizon": horizon,
                        }
                    )
    return _sha(
        {
            "schema_version": 1,
            "trading_date": trading,
            "metadata": metadata,
            "quotes": sorted(quotes, key=lambda item: item["identity"]),
            "sources": sorted(source, key=lambda item: item["market"]),
            "selections": selections,
            "rule_version": PREDICTION_RULE_VERSION,
            "generator_version": PREDICTION_GENERATOR_VERSION,
        }
    )


def _semantic_prediction(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": record["schema_version"],
        "trading_date": record["trading_date"],
        "market": record["market"],
        "symbol": record["symbol"],
        "horizon_trading_days": record["horizon_trading_days"],
        "bucket": record["bucket"],
        "rank": record["rank"],
        "universe_size": record["universe_size"],
        "deterministic_score": record["deterministic_score"],
        "rule_version": record["rule_version"],
        "source_cutoff": record["source_cutoff"],
        "input_hashes": list(record["input_hashes"]),
        "source_hashes": list(record["source_hashes"]),
        "candidate_generator_version": record["candidate_generator_version"],
        "benchmark_identity": record["benchmark_identity"],
        "warnings": list(record["warnings"]),
        "limitations": list(record["limitations"]),
    }


def _record_hash(record: Mapping[str, Any]) -> str:
    body = dict(record)
    body.pop("record_sha256", None)
    return _sha(body)


def _outcome_datetime(outcome: "PredictionOutcome") -> datetime:
    return _aware_datetime(outcome.evaluated_at, field="evaluated_at")


def _validate_outcome_history(entries: Sequence["PredictionOutcome"]) -> None:
    ordered = sorted(entries, key=lambda item: (_outcome_datetime(item), item.outcome_fingerprint))
    for previous, current in zip(ordered, ordered[1:]):
        previous_at = _outcome_datetime(previous)
        current_at = _outcome_datetime(current)
        if current_at <= previous_at:
            raise PredictionLabError("outcome timestamps must advance strictly")
        if current.status not in OUTCOME_TRANSITIONS[previous.status]:
            raise PredictionLabError(
                f"invalid outcome transition: {previous.status} -> {current.status}"
            )


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    """Immutable deterministic sample registration."""

    schema_version: int
    prediction_id: str
    created_at: str
    trading_date: str
    market: str
    symbol: str
    horizon: int
    bucket: PredictionBucket
    rank: int
    universe_size: int
    deterministic_score: float
    rule_version: str
    source_cutoff: str | None
    input_hashes: tuple[str, ...]
    source_hashes: tuple[str, ...]
    candidate_generator_version: str
    benchmark_identity: str
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    semantic_fingerprint: str
    record_sha256: str
    entry_price_reference: Mapping[str, Any] | None = None

    @property
    def identity(self) -> str:
        return f"{self.market}:{self.symbol}"

    @property
    def canonical_symbol(self) -> str:
        return self.identity

    @property
    def horizon_trading_days(self) -> int:
        """Canonical contract name; ``horizon`` remains a compatibility alias."""

        return self.horizon

    @classmethod
    def create(
        cls,
        *,
        created_at: datetime,
        trading_date: str,
        market: str,
        symbol: str,
        horizon: int,
        bucket: PredictionBucket,
        rank: int,
        universe_size: int,
        deterministic_score: float,
        rule_version: str = PREDICTION_RULE_VERSION,
        source_cutoff: str | None = None,
        input_hashes: Sequence[str] = (),
        source_hashes: Sequence[str] = (),
        candidate_generator_version: str = PREDICTION_GENERATOR_VERSION,
        benchmark_identity: str = "TWSE:TAIEX",
        warnings: Sequence[str] = (),
        limitations: Sequence[str] = (),
        entry_price_reference: Mapping[str, Any] | None = None,
    ) -> "PredictionRecord":
        parsed = _market_symbol(market, symbol)
        if parsed.code != str(symbol).strip().upper():
            raise PredictionLabError("symbol must be canonical code without provider suffix")
        created = _iso(created_at)
        trading = _date(trading_date, field="trading_date")
        cutoff = _date(source_cutoff, field="source_cutoff") if source_cutoff else None
        hashes = _hashes(tuple(input_hashes))
        provenance = _hashes(tuple(source_hashes))
        entry_reference = _normalize_reference(
            entry_price_reference,
            identity=parsed.canonical,
            effective_date=trading,
            field="entry_price",
            include_value=True,
        )
        data: dict[str, Any] = {
            "schema_version": PREDICTION_SCHEMA_VERSION,
            "trading_date": trading,
            "market": parsed.market.value,
            "symbol": parsed.code,
            "horizon_trading_days": horizon,
            "bucket": bucket,
            "rank": rank,
            "universe_size": universe_size,
            "deterministic_score": deterministic_score,
            "rule_version": rule_version,
            "source_cutoff": cutoff,
            "input_hashes": list(hashes),
            "source_hashes": list(provenance),
            "candidate_generator_version": candidate_generator_version,
            "benchmark_identity": benchmark_identity,
            "warnings": list(warnings),
            "limitations": list(limitations),
        }
        if entry_reference is not None:
            data["entry_price_reference"] = entry_reference
        semantic = _sha(data)
        prediction_id = f"prediction-{_sha({**data, 'semantic_fingerprint': semantic})}"
        record = cls(
            schema_version=PREDICTION_SCHEMA_VERSION,
            prediction_id=prediction_id,
            created_at=created,
            trading_date=trading,
            market=parsed.market.value,
            symbol=parsed.code,
            horizon=horizon,
            bucket=bucket,
            rank=rank,
            universe_size=universe_size,
            deterministic_score=float(deterministic_score),
            rule_version=str(rule_version),
            source_cutoff=cutoff,
            input_hashes=hashes,
            source_hashes=provenance,
            candidate_generator_version=str(candidate_generator_version),
            benchmark_identity=str(benchmark_identity),
            warnings=tuple(str(item) for item in warnings),
            limitations=tuple(str(item) for item in limitations),
            semantic_fingerprint=semantic,
            record_sha256="",
            entry_price_reference=entry_reference,
        )
        return cls.from_dict({**record.to_dict(), "record_sha256": _record_hash(record.to_dict())})

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "prediction_id": self.prediction_id,
            "created_at": self.created_at,
            "trading_date": self.trading_date,
            "market": self.market,
            "symbol": self.symbol,
            "identity": self.identity,
            "horizon_trading_days": self.horizon,
            # Keep the pre-Phase-0 Python/JSON alias so existing callers can
            # still read it; from_dict requires the canonical field and
            # rejects any disagreement between the two values.
            "horizon": self.horizon,
            "bucket": self.bucket,
            "rank": self.rank,
            "universe_size": self.universe_size,
            "deterministic_score": self.deterministic_score,
            "rule_version": self.rule_version,
            "source_cutoff": self.source_cutoff,
            "input_hashes": list(self.input_hashes),
            "source_hashes": list(self.source_hashes),
            "candidate_generator_version": self.candidate_generator_version,
            "benchmark_identity": self.benchmark_identity,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
            "semantic_fingerprint": self.semantic_fingerprint,
            "record_sha256": self.record_sha256,
        }
        if self.entry_price_reference is not None:
            payload["entry_price_reference"] = dict(self.entry_price_reference)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PredictionRecord":
        required = {
            "schema_version",
            "prediction_id",
            "created_at",
            "trading_date",
            "market",
            "symbol",
            "horizon_trading_days",
            "bucket",
            "rank",
            "universe_size",
            "deterministic_score",
            "rule_version",
            "source_cutoff",
            "input_hashes",
            "source_hashes",
            "candidate_generator_version",
            "benchmark_identity",
            "warnings",
            "limitations",
            "semantic_fingerprint",
            "record_sha256",
        }
        if not required.issubset(payload):
            raise PredictionLabError("prediction record is missing fields")
        if payload["schema_version"] != PREDICTION_SCHEMA_VERSION or isinstance(
            payload["schema_version"], bool
        ):
            raise PredictionLabError("unsupported prediction schema")
        parsed = _market_symbol(payload["market"], payload["symbol"])
        if parsed.market.value != payload["market"] or parsed.code != payload["symbol"]:
            raise PredictionLabError("prediction identity is not canonical")
        created = _aware_datetime(payload["created_at"], field="created_at")
        if created > datetime.now(timezone.utc) + timedelta(seconds=2):
            raise PredictionLabError("prediction created_at is in the future")
        trading = _date(payload["trading_date"], field="trading_date")
        cutoff = (
            _date(payload["source_cutoff"], field="source_cutoff")
            if payload["source_cutoff"]
            else None
        )
        horizon = payload["horizon_trading_days"]
        if "horizon" in payload and payload["horizon"] != horizon:
            raise PredictionLabError("prediction horizon alias mismatch")
        if horizon not in PREDICTION_HORIZONS or isinstance(horizon, bool):
            raise PredictionLabError("unsupported prediction horizon")
        if payload["bucket"] not in PREDICTION_BUCKETS:
            raise PredictionLabError("unsupported prediction bucket")
        if (
            not isinstance(payload["rank"], int)
            or isinstance(payload["rank"], bool)
            or payload["rank"] < 1
        ):
            raise PredictionLabError("invalid prediction rank")
        if (
            not isinstance(payload["universe_size"], int)
            or isinstance(payload["universe_size"], bool)
            or payload["universe_size"] < 3
        ):
            raise PredictionLabError("invalid prediction universe")
        if (
            payload["rank"] > payload["universe_size"]
            or not isinstance(payload["deterministic_score"], (int, float))
            or isinstance(payload["deterministic_score"], bool)
            or not math.isfinite(float(payload["deterministic_score"]))
        ):
            raise PredictionLabError("invalid deterministic prediction score")
        if not isinstance(payload["input_hashes"], (list, tuple)) or not isinstance(
            payload["source_hashes"], (list, tuple)
        ):
            raise PredictionLabError("invalid prediction provenance")
        hashes = _hashes(payload["input_hashes"])
        provenance = _hashes(payload["source_hashes"])
        warnings = tuple(str(item) for item in payload["warnings"])
        limitations = tuple(str(item) for item in payload["limitations"])
        entry_reference = _normalize_reference(
            payload.get("entry_price_reference"),
            identity=parsed.canonical,
            effective_date=trading,
            field="entry_price",
            include_value=True,
        )
        data = {
            "schema_version": payload["schema_version"],
            "trading_date": trading,
            "market": parsed.market.value,
            "symbol": parsed.code,
            "horizon_trading_days": horizon,
            "bucket": payload["bucket"],
            "rank": payload["rank"],
            "universe_size": payload["universe_size"],
            "deterministic_score": float(payload["deterministic_score"]),
            "rule_version": payload["rule_version"],
            "source_cutoff": cutoff,
            "input_hashes": list(hashes),
            "source_hashes": list(provenance),
            "candidate_generator_version": payload["candidate_generator_version"],
            "benchmark_identity": payload["benchmark_identity"],
            "warnings": list(warnings),
            "limitations": list(limitations),
        }
        if entry_reference is not None:
            data["entry_price_reference"] = entry_reference
        semantic = _sha(data)
        expected_id = f"prediction-{_sha({**data, 'semantic_fingerprint': semantic})}"
        if payload["semantic_fingerprint"] != semantic or payload["prediction_id"] != expected_id:
            raise PredictionLabError("prediction fingerprint or identity mismatch")
        if payload.get("identity") not in (None, parsed.canonical):
            raise PredictionLabError("prediction identity field mismatch")
        record = cls(
            schema_version=payload["schema_version"],
            prediction_id=payload["prediction_id"],
            created_at=_iso(created),
            trading_date=trading,
            market=parsed.market.value,
            symbol=parsed.code,
            horizon=horizon,
            bucket=payload["bucket"],
            rank=payload["rank"],
            universe_size=payload["universe_size"],
            deterministic_score=float(payload["deterministic_score"]),
            rule_version=str(payload["rule_version"]),
            source_cutoff=cutoff,
            input_hashes=hashes,
            source_hashes=provenance,
            candidate_generator_version=str(payload["candidate_generator_version"]),
            benchmark_identity=str(payload["benchmark_identity"]),
            warnings=warnings,
            limitations=limitations,
            semantic_fingerprint=semantic,
            record_sha256=str(payload["record_sha256"]),
            entry_price_reference=entry_reference,
        )
        if record.record_sha256 != _record_hash(record.to_dict()):
            raise PredictionLabError("prediction record hash mismatch")
        return record


@dataclass(frozen=True, slots=True)
class PredictionOutcome:
    """Append-only evaluation with explicit market and price provenance."""

    schema_version: int
    prediction_id: str
    evaluated_at: str
    target_trading_date: str
    actual_available_date: str | None
    entry_price: float | None
    exit_price: float | None
    benchmark_return: float | None
    gross_return: float | None
    transaction_cost: float | None
    net_return: float | None
    net_excess_return: float | None
    raw_return: float | None
    excess_return: float | None
    transaction_cost_assumption: float
    status: PredictionStatus
    missing_reason: str | None
    source_hashes: tuple[str, ...]
    calendar_provenance: Mapping[str, Any]
    entry_price_identity: Mapping[str, Any] | None
    exit_price_identity: Mapping[str, Any] | None
    benchmark_identity: Mapping[str, Any] | None
    cost_policy_version: str | None
    cost_components: Mapping[str, Any] | None
    outcome_fingerprint: str
    record_sha256: str

    @staticmethod
    def _identity(
        value: Mapping[str, Any] | None,
        *,
        field: str,
        required: bool,
        default_identity: str | None = None,
        effective_date: str | None = None,
    ) -> dict[str, Any] | None:
        if value is None:
            if required:
                raise PredictionLabError(f"{field} identity is required")
            return None
        if not isinstance(value, Mapping):
            raise PredictionLabError(f"{field} identity is invalid")
        identity = str(value.get("identity") or default_identity or "").strip()
        if ":" not in identity:
            raise PredictionLabError(f"{field} identity is invalid")
        market, symbol = identity.split(":", 1)
        parsed = _market_symbol(market, symbol)
        date_value = _date(
            value.get("effective_trading_date", value.get("effective_date", effective_date)),
            field=f"{field}.effective_trading_date",
        )
        payload_hash = value.get("payload_hash", value.get("payload_sha256"))
        provenance = _hashes((payload_hash,))[0]
        result: dict[str, Any] = {
            "identity": parsed.canonical,
            "price_field": str(value.get("price_field", value.get("field", "close"))),
            "effective_trading_date": date_value,
            "provider": str(value.get("provider", value.get("source", "unknown"))),
            "payload_hash": provenance,
            "adjusted_raw_policy": str(value.get("adjusted_raw_policy", "raw")),
        }
        if "provider_symbol" in value and value["provider_symbol"] is not None:
            provider_symbol = value["provider_symbol"]
            if not isinstance(provider_symbol, str) or not provider_symbol.strip():
                raise PredictionLabError(f"{field}.provider_symbol is invalid")
            result["provider_symbol"] = provider_symbol.strip()
        if "source_type" in value and value["source_type"] is not None:
            source_type = value["source_type"]
            if not isinstance(source_type, str) or not source_type.strip():
                raise PredictionLabError(f"{field}.source_type is invalid")
            result["source_type"] = source_type.strip()
        for name in ("checked_at", "fetched_at"):
            if name in value and value[name] is not None:
                result[name] = _iso(_aware_datetime(value[name], field=f"{field}.{name}"))
        if "payload_hashes" in value:
            raw_hashes = value.get("payload_hashes")
            if not isinstance(raw_hashes, (list, tuple)):
                raise PredictionLabError(f"{field}.payload_hashes is invalid")
            result["payload_hashes"] = list(_hashes(tuple(str(item) for item in raw_hashes)))
        for name in ("start_trading_date", "end_trading_date"):
            if name in value and value[name] is not None:
                result[name] = _date(value[name], field=f"{field}.{name}")
        for name in ("start_value", "end_value"):
            if name in value and value[name] is not None:
                result[name] = _finite_number(value[name], field=f"{field}.{name}", minimum=1e-12)
        if "return_value" in value and value["return_value"] is not None:
            result["return_value"] = _finite_number(
                value["return_value"], field=f"{field}.return_value"
            )
        if all(name in result for name in ("start_value", "end_value")):
            derived = float(result["end_value"]) / float(result["start_value"]) - 1.0
            given = float(result.get("return_value", 0.0))
            if not math.isclose(derived, given, rel_tol=0.0, abs_tol=1e-12):
                raise PredictionLabError(f"{field} return is not reproducible from evidence")
        return result

    @classmethod
    def create(
        cls,
        *,
        prediction: PredictionRecord,
        evaluated_at: datetime,
        actual_available_date: str | None = None,
        entry_price: float | None = None,
        exit_price: float | None = None,
        benchmark_return: float | None = None,
        transaction_cost_assumption: float = 0.0,
        status: PredictionStatus | None = None,
        missing_reason: str | None = None,
        source_hashes: Sequence[str] = (),
        calendar: MarketTradingCalendar | None = None,
        entry_price_identity: Mapping[str, Any] | None = None,
        exit_price_identity: Mapping[str, Any] | None = None,
        benchmark_identity: Mapping[str, Any] | None = None,
        cost_policy_version: str | None = None,
        cost_components: Mapping[str, Any] | None = None,
        position_side: str = "long",
    ) -> "PredictionOutcome":
        evaluated_dt = _aware_datetime(_iso(evaluated_at), field="evaluated_at")
        chosen_calendar = calendar or MarketTradingCalendar.default_for(prediction.market)
        if chosen_calendar.market != prediction.market:
            raise PredictionLabError("trading calendar market mismatch")
        target = chosen_calendar.target_date(prediction.trading_date, prediction.horizon)
        actual = (
            _date(actual_available_date, field="actual_available_date")
            if actual_available_date
            else None
        )
        if actual is not None and actual not in chosen_calendar.dates:
            raise PredictionLabError("actual date is not a verified trading date")
        if status is None:
            if actual is None or actual < target:
                status = "pending"
            elif (
                entry_price is None
                or exit_price is None
                or benchmark_return is None
                or not source_hashes
            ):
                status = "unavailable"
                missing_reason = (
                    missing_reason or "price, benchmark, or source evidence unavailable"
                )
            else:
                status = "evaluated"
        if status not in {"pending", "eligible", "evaluated", "unavailable"}:
            raise PredictionLabError("invalid prediction outcome status")
        if status in {"eligible", "evaluated"} and (actual is None or actual < target):
            raise PredictionLabError("outcome requires actual data at target date")
        if status == "pending" and actual is not None and actual >= target:
            raise PredictionLabError("pending outcome cannot have eligible actual data")
        if status == "unavailable" and not str(missing_reason or "").strip():
            raise PredictionLabError("unavailable outcome requires a missing reason")
        rate = _finite_number(
            transaction_cost_assumption, field="transaction_cost_assumption", minimum=0.0
        )
        provenance = _hashes(tuple(source_hashes))
        if status == "evaluated" and not provenance:
            raise PredictionLabError("evaluated outcome requires source hashes")
        normalized_entry = (
            _finite_number(entry_price, field="entry_price", minimum=0.0000000001)
            if entry_price is not None
            else None
        )
        normalized_exit = (
            _finite_number(exit_price, field="exit_price", minimum=0.0000000001)
            if exit_price is not None
            else None
        )
        normalized_benchmark = (
            _finite_number(benchmark_return, field="benchmark_return")
            if benchmark_return is not None
            else None
        )
        entry_identity = cls._identity(
            entry_price_identity,
            field="entry_price",
            required=status == "evaluated",
            default_identity=prediction.identity,
            effective_date=actual,
        )
        exit_identity = cls._identity(
            exit_price_identity,
            field="exit_price",
            required=status == "evaluated",
            default_identity=prediction.identity,
            effective_date=actual,
        )
        benchmark_identity_value = cls._identity(
            benchmark_identity,
            field="benchmark",
            required=status == "evaluated",
            default_identity=prediction.benchmark_identity,
            effective_date=actual,
        )
        normalized_cost_components = _normalize_cost_components(cost_components)
        selected_position_side = (
            str(normalized_cost_components.get("position_side", position_side))
            if normalized_cost_components is not None
            else position_side
        )
        if selected_position_side not in {"long", "short"}:
            raise PredictionLabError("unsupported prediction position side")
        gross: float | None
        cost: float | None
        net: float | None
        net_excess: float | None
        if status == "evaluated":
            if normalized_entry is None or normalized_exit is None or normalized_benchmark is None:
                raise PredictionLabError("evaluated outcome requires prices and benchmark return")
            if (
                entry_identity is None
                or exit_identity is None
                or benchmark_identity_value is None
                or entry_identity["identity"] != prediction.identity
                or exit_identity["identity"] != prediction.identity
                or benchmark_identity_value["identity"] != prediction.benchmark_identity
            ):
                raise PredictionLabError("outcome price or benchmark identity mismatch")
            if benchmark_identity_value and "start_value" in benchmark_identity_value:
                derived_benchmark = (
                    float(benchmark_identity_value["end_value"])
                    / float(benchmark_identity_value["start_value"])
                    - 1.0
                )
                if not math.isclose(
                    derived_benchmark, normalized_benchmark, rel_tol=0.0, abs_tol=1e-12
                ):
                    raise PredictionLabError("benchmark return is not reproducible")
            if (
                entry_identity is not None
                and exit_identity is not None
                and benchmark_identity_value is not None
                and (
                    entry_identity["adjusted_raw_policy"] != exit_identity["adjusted_raw_policy"]
                    or entry_identity["adjusted_raw_policy"]
                    != benchmark_identity_value["adjusted_raw_policy"]
                )
            ):
                raise PredictionLabError("raw/adjusted price policy mismatch")
            gross = (
                normalized_exit / normalized_entry - 1.0
                if selected_position_side == "long"
                else normalized_entry / normalized_exit - 1.0
            )
            if normalized_cost_components is not None and all(
                name in normalized_cost_components
                for name in (
                    "buy_commission_rate",
                    "sell_commission_rate",
                    "buy_slippage_rate",
                    "sell_slippage_rate",
                    "sell_tax_rate",
                )
            ):
                calculated_cost = _round_trip_cost(
                    normalized_entry,
                    normalized_exit,
                    normalized_cost_components,
                    position_side=selected_position_side,
                )
                normalized_cost_components = {
                    **normalized_cost_components,
                    **calculated_cost,
                }
                cost = float(calculated_cost["transaction_cost_return"])
                net = float(calculated_cost["net_return"])
            else:
                cost = rate
                net = gross - cost
            net_excess = net - normalized_benchmark
        else:
            gross = cost = net = net_excess = None
            normalized_benchmark = None
            entry_identity = exit_identity = benchmark_identity_value = None
        normalized_reason = str(missing_reason) if missing_reason else None
        if status == "evaluated" and normalized_cost_components is not None:
            if "formula_version" not in normalized_cost_components:
                raise PredictionLabError("evaluated outcome cost formula version is required")
            if "total_rate" in normalized_cost_components and not math.isclose(
                float(normalized_cost_components["total_rate"]), rate, rel_tol=0.0, abs_tol=1e-12
            ):
                raise PredictionLabError("evaluated outcome cost total does not match assumption")
        data = {
            "schema_version": OUTCOME_SCHEMA_VERSION,
            "prediction_id": prediction.prediction_id,
            "target_trading_date": target,
            "actual_available_date": actual,
            "entry_price": normalized_entry,
            "exit_price": normalized_exit,
            "benchmark_return": normalized_benchmark,
            "gross_return": gross,
            "transaction_cost": cost,
            "net_return": net,
            "net_excess_return": net_excess,
            "raw_return": gross,
            "excess_return": net_excess,
            "transaction_cost_assumption": rate,
            "status": status,
            "missing_reason": normalized_reason,
            "source_hashes": list(provenance),
            "calendar_provenance": chosen_calendar.to_dict(),
            "entry_price_identity": entry_identity,
            "exit_price_identity": exit_identity,
            "benchmark_identity": benchmark_identity_value,
            "cost_policy_version": cost_policy_version,
            "cost_components": normalized_cost_components,
        }
        temporary = cls(
            schema_version=OUTCOME_SCHEMA_VERSION,
            prediction_id=prediction.prediction_id,
            evaluated_at=_iso(evaluated_dt),
            target_trading_date=target,
            actual_available_date=actual,
            entry_price=normalized_entry,
            exit_price=normalized_exit,
            benchmark_return=normalized_benchmark,
            gross_return=gross,
            transaction_cost=cost,
            net_return=net,
            net_excess_return=net_excess,
            raw_return=gross,
            excess_return=net_excess,
            transaction_cost_assumption=rate,
            status=status,
            missing_reason=normalized_reason,
            source_hashes=provenance,
            calendar_provenance=chosen_calendar.to_dict(),
            entry_price_identity=entry_identity,
            exit_price_identity=exit_identity,
            benchmark_identity=benchmark_identity_value,
            cost_policy_version=(str(cost_policy_version) if cost_policy_version else None),
            cost_components=normalized_cost_components,
            outcome_fingerprint=_sha(data),
            record_sha256="",
        )
        return cls.from_dict(
            {**temporary.to_dict(), "record_sha256": _record_hash(temporary.to_dict())},
            prediction=prediction,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "prediction_id": self.prediction_id,
            "evaluated_at": self.evaluated_at,
            "target_trading_date": self.target_trading_date,
            "actual_available_date": self.actual_available_date,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "benchmark_return": self.benchmark_return,
            "gross_return": self.gross_return,
            "transaction_cost": self.transaction_cost,
            "net_return": self.net_return,
            "net_excess_return": self.net_excess_return,
            "raw_return": self.raw_return,
            "excess_return": self.excess_return,
            "transaction_cost_assumption": self.transaction_cost_assumption,
            "status": self.status,
            "missing_reason": self.missing_reason,
            "source_hashes": list(self.source_hashes),
            "calendar_provenance": dict(self.calendar_provenance),
            "entry_price_identity": (
                dict(self.entry_price_identity) if self.entry_price_identity else None
            ),
            "exit_price_identity": (
                dict(self.exit_price_identity) if self.exit_price_identity else None
            ),
            "benchmark_identity": (
                dict(self.benchmark_identity) if self.benchmark_identity else None
            ),
            "cost_policy_version": self.cost_policy_version,
            "cost_components": (
                dict(self.cost_components) if self.cost_components is not None else None
            ),
            "outcome_fingerprint": self.outcome_fingerprint,
            "record_sha256": self.record_sha256,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, prediction: PredictionRecord | None = None
    ) -> "PredictionOutcome":
        required = {
            "schema_version",
            "prediction_id",
            "evaluated_at",
            "target_trading_date",
            "actual_available_date",
            "entry_price",
            "exit_price",
            "benchmark_return",
            "gross_return",
            "transaction_cost",
            "net_return",
            "net_excess_return",
            "raw_return",
            "excess_return",
            "transaction_cost_assumption",
            "status",
            "missing_reason",
            "source_hashes",
            "calendar_provenance",
            "entry_price_identity",
            "exit_price_identity",
            "benchmark_identity",
            "outcome_fingerprint",
            "record_sha256",
        }
        if not required.issubset(payload):
            raise PredictionLabError("outcome record is missing fields")
        if payload["schema_version"] != OUTCOME_SCHEMA_VERSION or isinstance(
            payload["schema_version"], bool
        ):
            raise PredictionLabError("unsupported outcome schema")
        evaluated = _aware_datetime(payload["evaluated_at"], field="evaluated_at")
        target = _date(payload["target_trading_date"], field="target_trading_date")
        actual = (
            _date(payload["actual_available_date"], field="actual_available_date")
            if payload["actual_available_date"]
            else None
        )
        status = payload["status"]
        if status not in {"pending", "eligible", "evaluated", "unavailable"}:
            raise PredictionLabError("invalid outcome status")
        if not isinstance(payload["source_hashes"], (list, tuple)):
            raise PredictionLabError("invalid outcome provenance")
        provenance = _hashes(payload["source_hashes"])
        calendar = MarketTradingCalendar.from_dict(payload["calendar_provenance"])
        if prediction is not None:
            if (
                payload["prediction_id"] != prediction.prediction_id
                or calendar.market != prediction.market
            ):
                raise PredictionLabError("outcome prediction or calendar mismatch")
            expected_target = calendar.target_date(prediction.trading_date, prediction.horizon)
            if target != expected_target:
                raise PredictionLabError("outcome target date mismatch")
        if actual is not None and actual not in calendar.dates:
            raise PredictionLabError("actual date is not a verified trading date")
        if status in {"eligible", "evaluated"} and (actual is None or actual < target):
            raise PredictionLabError("outcome requires actual data at target date")
        if status == "pending" and actual is not None and actual >= target:
            raise PredictionLabError("pending outcome cannot have eligible actual data")
        if status == "unavailable" and not str(payload["missing_reason"] or "").strip():
            raise PredictionLabError("unavailable outcome requires a missing reason")
        rate = _finite_number(
            payload["transaction_cost_assumption"], field="transaction_cost_assumption", minimum=0.0
        )
        entry = (
            _finite_number(payload["entry_price"], field="entry_price", minimum=0.0000000001)
            if payload["entry_price"] is not None
            else None
        )
        exit_price = (
            _finite_number(payload["exit_price"], field="exit_price", minimum=0.0000000001)
            if payload["exit_price"] is not None
            else None
        )
        benchmark = (
            _finite_number(payload["benchmark_return"], field="benchmark_return")
            if payload["benchmark_return"] is not None
            else None
        )
        entry_identity = cls._identity(
            payload["entry_price_identity"],
            field="entry_price",
            required=status == "evaluated",
            effective_date=actual,
        )
        exit_identity = cls._identity(
            payload["exit_price_identity"],
            field="exit_price",
            required=status == "evaluated",
            effective_date=actual,
        )
        benchmark_identity = cls._identity(
            payload["benchmark_identity"],
            field="benchmark",
            required=status == "evaluated",
            effective_date=actual,
        )
        cost_policy_version = payload.get("cost_policy_version")
        if cost_policy_version is not None and (
            not isinstance(cost_policy_version, str) or not cost_policy_version.strip()
        ):
            raise PredictionLabError("cost policy version is invalid")
        raw_components = payload.get("cost_components")
        if raw_components is not None and not isinstance(raw_components, Mapping):
            raise PredictionLabError("cost policy components are invalid")
        cost_components = _normalize_cost_components(raw_components)
        selected_position_side = (
            str(cost_components.get("position_side", "long"))
            if cost_components is not None
            else "long"
        )
        if selected_position_side not in {"long", "short"}:
            raise PredictionLabError("cost position side is invalid")
        if status == "evaluated" and cost_components is not None:
            if "formula_version" not in cost_components:
                raise PredictionLabError("evaluated outcome cost formula version is required")
            if "total_rate" in cost_components and not math.isclose(
                float(cost_components["total_rate"]), rate, rel_tol=0.0, abs_tol=1e-12
            ):
                raise PredictionLabError("evaluated outcome cost total does not match assumption")
        gross: float | None
        cost: float | None
        net: float | None
        net_excess: float | None
        if status == "evaluated":
            if entry is None or exit_price is None or benchmark is None:
                raise PredictionLabError("evaluated outcome requires complete prices and benchmark")
            if (
                entry_identity is None
                or exit_identity is None
                or benchmark_identity is None
                or prediction is not None
                and (
                    entry_identity["identity"] != prediction.identity
                    or exit_identity["identity"] != prediction.identity
                    or benchmark_identity["identity"] != prediction.benchmark_identity
                )
            ):
                raise PredictionLabError("outcome price or benchmark identity mismatch")
            if benchmark_identity and "start_value" in benchmark_identity:
                derived_benchmark = (
                    float(benchmark_identity["end_value"])
                    / float(benchmark_identity["start_value"])
                    - 1.0
                )
                if not math.isclose(derived_benchmark, benchmark, rel_tol=0.0, abs_tol=1e-12):
                    raise PredictionLabError("benchmark return is not reproducible")
            if (
                entry_identity is not None
                and exit_identity is not None
                and benchmark_identity is not None
                and (
                    entry_identity["adjusted_raw_policy"] != exit_identity["adjusted_raw_policy"]
                    or entry_identity["adjusted_raw_policy"]
                    != benchmark_identity["adjusted_raw_policy"]
                )
            ):
                raise PredictionLabError("raw/adjusted price policy mismatch")
            gross = (
                exit_price / entry - 1.0
                if selected_position_side == "long"
                else entry / exit_price - 1.0
            )
            if cost_components is not None and all(
                name in cost_components
                for name in (
                    "buy_commission_rate",
                    "sell_commission_rate",
                    "buy_slippage_rate",
                    "sell_slippage_rate",
                    "sell_tax_rate",
                )
            ):
                calculated_cost = _round_trip_cost(
                    entry,
                    exit_price,
                    cost_components,
                    position_side=selected_position_side,
                )
                for key, value in calculated_cost.items():
                    if key in cost_components and isinstance(value, (float, int)):
                        if not math.isclose(
                            float(cost_components[key]),
                            float(value),
                            rel_tol=0.0,
                            abs_tol=1e-12,
                        ):
                            raise PredictionLabError("cost evidence is not reproducible")
                cost = float(calculated_cost["transaction_cost_return"])
                net = float(calculated_cost["net_return"])
            else:
                cost = rate
                net = gross - cost
            net_excess = net - benchmark
            if not math.isclose(float(payload["gross_return"]), gross, rel_tol=0, abs_tol=1e-12):
                raise PredictionLabError("gross return mismatch")
            if not math.isclose(float(payload["transaction_cost"]), cost, rel_tol=0, abs_tol=1e-12):
                raise PredictionLabError("transaction cost mismatch")
            if not math.isclose(float(payload["net_return"]), net, rel_tol=0, abs_tol=1e-12):
                raise PredictionLabError("net return mismatch")
            if not math.isclose(
                float(payload["net_excess_return"]), net_excess, rel_tol=0, abs_tol=1e-12
            ):
                raise PredictionLabError("net excess return mismatch")
        else:
            gross = cost = net = net_excess = None
            if any(
                payload[name] is not None
                for name in (
                    "entry_price",
                    "exit_price",
                    "benchmark_return",
                    "gross_return",
                    "transaction_cost",
                    "net_return",
                    "net_excess_return",
                    "raw_return",
                    "excess_return",
                )
            ):
                raise PredictionLabError("non-evaluated outcome contains performance values")
            entry = exit_price = benchmark = None
            entry_identity = exit_identity = benchmark_identity = None
        data = {
            "schema_version": payload["schema_version"],
            "prediction_id": payload["prediction_id"],
            "target_trading_date": target,
            "actual_available_date": actual,
            "entry_price": entry,
            "exit_price": exit_price,
            "benchmark_return": benchmark,
            "gross_return": gross,
            "transaction_cost": cost,
            "net_return": net,
            "net_excess_return": net_excess,
            "raw_return": gross,
            "excess_return": net_excess,
            "transaction_cost_assumption": rate,
            "status": status,
            "missing_reason": payload["missing_reason"] if payload["missing_reason"] else None,
            "source_hashes": list(provenance),
            "calendar_provenance": calendar.to_dict(),
            "entry_price_identity": entry_identity,
            "exit_price_identity": exit_identity,
            "benchmark_identity": benchmark_identity,
            "cost_policy_version": cost_policy_version,
            "cost_components": cost_components,
        }
        if payload["outcome_fingerprint"] != _sha(data) or payload["record_sha256"] != _record_hash(
            payload
        ):
            raise PredictionLabError("outcome fingerprint or hash mismatch")
        if prediction is not None and evaluated < _aware_datetime(
            prediction.created_at, field="created_at"
        ):
            raise PredictionLabError("outcome predates prediction claim")
        return cls(
            schema_version=payload["schema_version"],
            prediction_id=str(payload["prediction_id"]),
            evaluated_at=_iso(evaluated),
            target_trading_date=target,
            actual_available_date=actual,
            entry_price=entry,
            exit_price=exit_price,
            benchmark_return=benchmark,
            gross_return=gross,
            transaction_cost=cost,
            net_return=net,
            net_excess_return=net_excess,
            raw_return=gross,
            excess_return=net_excess,
            transaction_cost_assumption=rate,
            status=status,
            missing_reason=str(payload["missing_reason"]) if payload["missing_reason"] else None,
            source_hashes=provenance,
            calendar_provenance=calendar.to_dict(),
            entry_price_identity=entry_identity,
            exit_price_identity=exit_identity,
            benchmark_identity=benchmark_identity,
            cost_policy_version=cost_policy_version,
            cost_components=cost_components,
            outcome_fingerprint=str(payload["outcome_fingerprint"]),
            record_sha256=str(payload["record_sha256"]),
        )


def _target_date(
    trading_date: str,
    horizon: int,
    *,
    calendar: MarketTradingCalendar | None = None,
    market: str = "TWSE",
) -> str:
    """Resolve a target only through an explicit hash-bound date sequence."""

    chosen = calendar or MarketTradingCalendar.default_for(market)
    return chosen.target_date(trading_date, horizon)


def _atomic_create_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Publish complete immutable bytes without exposing a partial final file.

    A private claim is created exclusively first.  The JSON is written and
    fsynced to a private temporary file, then a hard-link creates the final
    authority with no overwrite semantics.  A loser never removes a winner.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    invocation_id = uuid.uuid4().hex
    claim = path.with_name(f".{path.name}.{os.getpid()}.{invocation_id}.claim")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{invocation_id}.tmp")
    encoded = (_canonical(payload) + "\n").encode("utf-8")
    own_claim = False
    own_temp = False
    claim_fd: int | None = None
    temp_fd: int | None = None
    try:
        try:
            claim_fd = os.open(
                claim,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
            )
            own_claim = True
        except FileExistsError:
            # This is another invocation's claim.  It is never ours to unlink.
            raise
        with os.fdopen(claim_fd, "wb") as handle:
            claim_fd = None
            handle.write(b"prediction-record-claim-v1\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_fd = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
        )
        own_temp = True
        with os.fdopen(temp_fd, "wb") as handle:
            temp_fd = None
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Hard-link publication is atomic and fails if a winner already
            # owns the destination.  It does not replace an existing file.
            os.link(temporary, path)
        except FileExistsError:
            # The final authority already has a winner.  Cleanup is handled
            # below, and only for the private files owned by this invocation.
            raise
        temporary.unlink()
        claim.unlink()
    except FileExistsError:
        # A claim collision belongs to another invocation and must be left
        # untouched.  Once this invocation owns its claim, only its own
        # private files may be cleaned up (including a final-link race).
        if own_claim:
            if claim_fd is not None:
                os.close(claim_fd)
            if temp_fd is not None:
                os.close(temp_fd)
            private_paths = (claim, temporary) if own_temp else (claim,)
            for private_path in private_paths:
                try:
                    private_path.unlink()
                except FileNotFoundError:
                    pass
        raise
    except Exception:
        if claim_fd is not None:
            os.close(claim_fd)
        if temp_fd is not None:
            os.close(temp_fd)
        if own_claim:
            try:
                claim.unlink()
            except FileNotFoundError:
                pass
        if own_temp:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        raise


def _read_after_publish_race(path: Path, *, attempts: int = 25) -> dict[str, Any]:
    """Bounded replay of an immutable winner after a publish race.

    A hard-link publication makes a visible final file complete.  The only
    transient state a loser may observe is that the winner has not linked its
    final authority yet, so retry that absence for a short, fixed window and
    fail closed afterwards.  Corrupt bytes are never retried or repaired.
    """

    for attempt in range(attempts):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if attempt + 1 < attempts:
            time.sleep(0.01)
    raise PredictionLabError("immutable record publish is still pending")


def _atomic_replace_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write((_canonical(payload) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except Exception:
        try:
            Path(name).unlink()
        except FileNotFoundError:
            pass
        raise


class PredictionLabStore:
    """Immutable record store; index.json is a rebuildable projection."""

    def __init__(
        self,
        root: str | Path,
        outcomes_dir: str | Path | None = None,
        index_path: str | Path | None = None,
        *,
        max_records: int = 5000,
    ) -> None:
        base = Path(root)
        if outcomes_dir is None:
            self.root = base
            self.predictions_dir = base / "predictions"
            self.outcomes_dir = base / "outcomes"
            self.index_path = base / "index.json" if index_path is None else Path(index_path)
        else:
            self.root = base.parent
            self.predictions_dir = base
            self.outcomes_dir = Path(outcomes_dir)
            self.index_path = (
                Path(index_path) if index_path is not None else self.root / "index.json"
            )
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        self.max_records = max_records

    @classmethod
    def from_runtime_paths(cls, paths: Any) -> "PredictionLabStore":
        return cls(paths.prediction_lab_dir)

    def ensure(self) -> "PredictionLabStore":
        self.predictions_dir.mkdir(parents=True, exist_ok=True)
        self.outcomes_dir.mkdir(parents=True, exist_ok=True)
        return self

    def _prediction_path(self, prediction_id: str) -> Path:
        return self.predictions_dir / f"{prediction_id}.json"

    def _outcome_path(self, fingerprint: str) -> Path:
        return self.outcomes_dir / f"outcome-{fingerprint}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PredictionLabError(f"prediction record unreadable: {path.name}") from exc

    @staticmethod
    def _record_files(directory: Path, prefix: str) -> tuple[Path, ...]:
        files: list[Path] = []
        for path in sorted(directory.iterdir() if directory.exists() else ()):
            if path.name.startswith(".") and (
                path.name.endswith(".claim") or path.name.endswith(".tmp")
            ):
                # Private claims/temps are never authority.  They are exposed
                # through orphan_artifacts() for diagnosis and are ignored by
                # graph reads so a crashed writer cannot poison a valid record.
                continue
            if not path.is_file() or path.is_symlink() or path.name.startswith("."):
                raise PredictionLabError("prediction record directory contains an unsafe entry")
            if not path.name.endswith(".json") or not path.name.startswith(prefix):
                raise PredictionLabError("prediction record directory contains an unexpected file")
            files.append(path)
        return tuple(files)

    def orphan_artifacts(self) -> tuple[Path, ...]:
        """Return private claim/temp files for safe diagnostic cleanup."""

        artifacts: list[Path] = []
        for directory in (self.predictions_dir, self.outcomes_dir):
            for path in sorted(directory.iterdir() if directory.exists() else ()):
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and path.name.startswith(".")
                    and (path.name.endswith(".claim") or path.name.endswith(".tmp"))
                ):
                    artifacts.append(path)
        return tuple(artifacts)

    def predictions(self) -> tuple[PredictionRecord, ...]:
        self.ensure()
        records: list[PredictionRecord] = []
        for path in self._record_files(self.predictions_dir, "prediction-"):
            if (
                path.name != path.name.lower()
                or path.resolve().parent != self.predictions_dir.resolve()
            ):
                raise PredictionLabError("prediction path is invalid")
            record = PredictionRecord.from_dict(self._read(path))
            if path.stem != record.prediction_id:
                raise PredictionLabError("prediction filename identity mismatch")
            records.append(record)
        if len({record.prediction_id for record in records}) != len(records):
            raise PredictionLabError("duplicate prediction id")
        return tuple(records)

    def outcomes(
        self, predictions: Mapping[str, PredictionRecord] | None = None
    ) -> tuple[PredictionOutcome, ...]:
        self.ensure()
        known = dict(predictions or {record.prediction_id: record for record in self.predictions()})
        outcomes: list[PredictionOutcome] = []
        for path in self._record_files(self.outcomes_dir, "outcome-"):
            payload = self._read(path)
            prediction = known.get(str(payload.get("prediction_id", "")))
            if prediction is None:
                raise PredictionLabError("outcome references unknown prediction")
            outcome = PredictionOutcome.from_dict(payload, prediction=prediction)
            if path.stem != f"outcome-{outcome.outcome_fingerprint}":
                raise PredictionLabError("outcome filename identity mismatch")
            outcomes.append(outcome)
        identities = [outcome.outcome_fingerprint for outcome in outcomes]
        if len(set(identities)) != len(identities):
            raise PredictionLabError("duplicate outcome fingerprint")
        return tuple(outcomes)

    def validate_graph(self) -> tuple[tuple[PredictionRecord, ...], tuple[PredictionOutcome, ...]]:
        predictions = self.predictions()
        outcomes = self.outcomes({record.prediction_id: record for record in predictions})
        if len(predictions) > self.max_records:
            raise PredictionLabError("prediction history exceeds bound")
        by_prediction: dict[str, list[PredictionOutcome]] = {}
        for outcome in outcomes:
            by_prediction.setdefault(outcome.prediction_id, []).append(outcome)
        for entries in by_prediction.values():
            _validate_outcome_history(entries)
        return predictions, outcomes

    def save_prediction(self, record: PredictionRecord) -> PredictionRecord:
        self.ensure()
        path = self._prediction_path(record.prediction_id)
        try:
            _atomic_create_json(path, record.to_dict())
        except FileExistsError:
            existing = PredictionRecord.from_dict(_read_after_publish_race(path))
            # created_at is audit metadata, not prediction identity.  A replay
            # with the same semantic input therefore returns the original
            # immutable winner even when the replay happened later.
            if existing.semantic_fingerprint != record.semantic_fingerprint:
                raise PredictionLabError("prediction identity collision")
            return existing
        self.rebuild_index()
        return record

    def save_outcome(self, outcome: PredictionOutcome) -> PredictionOutcome:
        self.ensure()
        predictions, graph_outcomes = self.validate_graph()
        known = {record.prediction_id: record for record in predictions}
        prediction = known.get(outcome.prediction_id)
        if prediction is None:
            raise PredictionLabError("cannot save outcome without prediction")
        validated = PredictionOutcome.from_dict(outcome.to_dict(), prediction=prediction)
        existing_outcomes = [
            item for item in graph_outcomes if item.prediction_id == prediction.prediction_id
        ]
        for existing in existing_outcomes:
            if existing.outcome_fingerprint == validated.outcome_fingerprint:
                existing_payload = existing.to_dict()
                validated_payload = validated.to_dict()
                # evaluated_at and the exact record hash are operational
                # metadata; semantic replay must preserve the first winner
                # bytes even when a later process runs at a new time.
                existing_payload.pop("evaluated_at", None)
                validated_payload.pop("evaluated_at", None)
                existing_payload.pop("record_sha256", None)
                validated_payload.pop("record_sha256", None)
                if existing_payload != validated_payload:
                    raise PredictionLabError("outcome identity collision")
                return existing
        if existing_outcomes:
            latest = max(existing_outcomes, key=_outcome_datetime)
            if _outcome_datetime(validated) <= _outcome_datetime(latest):
                raise PredictionLabError("outcome timestamp must advance")
            if validated.status not in OUTCOME_TRANSITIONS[latest.status]:
                raise PredictionLabError(
                    f"invalid outcome transition: {latest.status} -> {validated.status}"
                )
        path = self._outcome_path(outcome.outcome_fingerprint)
        try:
            _atomic_create_json(path, validated.to_dict())
        except FileExistsError:
            existing = PredictionOutcome.from_dict(
                _read_after_publish_race(path), prediction=prediction
            )
            existing_payload = existing.to_dict()
            validated_payload = validated.to_dict()
            existing_payload.pop("evaluated_at", None)
            validated_payload.pop("evaluated_at", None)
            existing_payload.pop("record_sha256", None)
            validated_payload.pop("record_sha256", None)
            if existing_payload != validated_payload:
                raise PredictionLabError("outcome identity collision")
            return existing
        self.rebuild_index()
        return validated

    def rebuild_index(self) -> dict[str, Any]:
        predictions, outcomes = self.validate_graph()
        payload = {
            "schema_version": 1,
            "predictions": [record.prediction_id for record in predictions[-self.max_records :]],
            "outcomes": [outcome.outcome_fingerprint for outcome in outcomes[-self.max_records :]],
        }
        _atomic_replace_json(self.index_path, payload)
        return payload

    def load_index(self) -> dict[str, Any]:
        predictions, outcomes = self.validate_graph()
        if not self.index_path.exists():
            return self.rebuild_index()
        payload = self._read(self.index_path)
        if payload != {
            "schema_version": 1,
            "predictions": [record.prediction_id for record in predictions[-self.max_records :]],
            "outcomes": [outcome.outcome_fingerprint for outcome in outcomes[-self.max_records :]],
        }:
            raise PredictionLabError("prediction index is stale or corrupt")
        return payload

    def summary(self, *, trading_date: str | None = None) -> "PredictionLabSummary":
        predictions, outcomes = self.validate_graph()
        selected = [
            record
            for record in predictions
            if trading_date is None or record.trading_date == trading_date
        ]
        counts = {
            bucket: sum(record.bucket == bucket for record in selected)
            for bucket in PREDICTION_BUCKETS
        }
        latest_outcome: dict[str, PredictionOutcome] = {}
        for outcome in sorted(outcomes, key=_outcome_datetime):
            latest_outcome[outcome.prediction_id] = outcome
        by_horizon = {
            str(horizon): {
                status: 0 for status in ("pending", "eligible", "evaluated", "unavailable")
            }
            for horizon in PREDICTION_HORIZONS
        }
        for record in selected:
            latest = latest_outcome.get(record.prediction_id)
            outcome_status = latest.status if latest else "pending"
            by_horizon[str(record.horizon)][outcome_status] += 1
        evaluated = [
            outcome
            for outcome in (latest_outcome.get(record.prediction_id) for record in selected)
            if outcome is not None and outcome.status == "evaluated"
        ]
        horizon_coverage = {
            str(horizon): (
                sum(
                    1
                    for record in selected
                    if record.horizon == horizon
                    and latest_outcome.get(record.prediction_id) is not None
                    and latest_outcome[record.prediction_id].status == "evaluated"
                )
                / sum(1 for record in selected if record.horizon == horizon)
                if any(record.horizon == horizon for record in selected)
                else 0.0
            )
            for horizon in PREDICTION_HORIZONS
        }
        top_returns = [
            float(item.net_return)
            for item in evaluated
            if item.net_return is not None
            and next(
                (
                    record.bucket
                    for record in selected
                    if record.prediction_id == item.prediction_id
                ),
                None,
            )
            == "top"
        ]
        bottom_returns = [
            float(item.net_return)
            for item in evaluated
            if item.net_return is not None
            and next(
                (
                    record.bucket
                    for record in selected
                    if record.prediction_id == item.prediction_id
                ),
                None,
            )
            == "bottom"
        ]
        bucket_metrics: dict[str, dict[str, float | int | None]] = {}
        for bucket in PREDICTION_BUCKETS:
            bucket_evaluated = [
                item
                for item in evaluated
                if next(
                    (
                        record.bucket
                        for record in selected
                        if record.prediction_id == item.prediction_id
                    ),
                    None,
                )
                == bucket
            ]
            net_values = [
                float(item.net_return) for item in bucket_evaluated if item.net_return is not None
            ]
            excess_values = [
                float(item.net_excess_return)
                for item in bucket_evaluated
                if item.net_excess_return is not None
            ]
            bucket_metrics[bucket] = {
                "count": len(bucket_evaluated),
                "median_net_return": median(net_values) if net_values else None,
                "median_net_excess_return": median(excess_values) if excess_values else None,
            }
        summary_status = "ready" if selected else "unavailable"
        warnings = ("樣本不足 30 筆，只能觀察，不能判定有效性。",) if len(selected) < 30 else ()
        return PredictionLabSummary(
            status=summary_status,
            message="樣本累積中" if selected else "尚未有可驗證樣本",
            registered_today=len(selected),
            bucket_counts=counts,
            outcome_counts=by_horizon,
            prediction_count=len(predictions),
            outcome_count=len(outcomes),
            last_trading_date=max((record.trading_date for record in predictions), default=None),
            warnings=warnings,
            limitations=("這是確定性研究實驗，不是投資建議；尚未產生勝率或預測。",),
            evaluated_count=len(evaluated),
            coverage_by_horizon=horizon_coverage,
            median_net_return=(
                median([item.net_return for item in evaluated if item.net_return is not None])
                if any(item.net_return is not None for item in evaluated)
                else None
            ),
            median_net_excess_return=(
                median(
                    [
                        item.net_excess_return
                        for item in evaluated
                        if item.net_excess_return is not None
                    ]
                )
                if any(item.net_excess_return is not None for item in evaluated)
                else None
            ),
            top_bottom_spread=(
                median(top_returns) - median(bottom_returns)
                if top_returns and bottom_returns
                else None
            ),
            last_evaluated_at=max((item.evaluated_at for item in evaluated), default=None),
            bucket_metrics=bucket_metrics,
        )


@dataclass(frozen=True, slots=True)
class PredictionLabSummary:
    status: str
    message: str
    registered_today: int
    bucket_counts: Mapping[str, int]
    outcome_counts: Mapping[str, Mapping[str, int]]
    prediction_count: int
    outcome_count: int
    last_trading_date: str | None
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evaluated_count: int = 0
    coverage_by_horizon: Mapping[str, float] = field(default_factory=dict)
    median_net_return: float | None = None
    median_net_excess_return: float | None = None
    top_bottom_spread: float | None = None
    last_evaluated_at: str | None = None
    bucket_metrics: Mapping[str, Mapping[str, float | int | None]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PredictionLabRegistrationResult:
    status: str
    records: tuple[PredictionRecord, ...]
    message: str
    warnings: tuple[str, ...] = ()
    created_count: int = 0
    skipped_count: int = 0


@dataclass(frozen=True, slots=True)
class PredictionOutcomeEvaluationResult:
    """Deterministic settlement report for one bounded evaluator run."""

    status: str
    outcomes: tuple[PredictionOutcome, ...]
    evaluated_count: int = 0
    eligible_count: int = 0
    pending_count: int = 0
    unavailable_count: int = 0
    message: str = ""


def _coerce_price_evidence(value: Any, *, field: str) -> PriceEvidence | None:
    if value is None:
        return None
    if isinstance(value, PriceEvidence):
        return value
    if not isinstance(value, Mapping):
        raise PredictionLabError(f"{field} evidence is invalid")
    return PriceEvidence(
        identity=str(value.get("identity", "")),
        value=_finite_number(value.get("value"), field=f"{field}.value", minimum=0.0000000001),
        effective_trading_date=str(
            value.get("effective_trading_date", value.get("effective_date", ""))
        ),
        provider=str(value.get("provider", value.get("source", "unknown"))),
        payload_hash=str(value.get("payload_hash", value.get("payload_sha256", ""))),
        price_field=str(value.get("price_field", value.get("field", "close"))),
        adjusted_raw_policy=str(value.get("adjusted_raw_policy", "raw")),
    )


def _coerce_benchmark_evidence(value: Any) -> BenchmarkEvidence | None:
    if value is None:
        return None
    if isinstance(value, BenchmarkEvidence):
        return value
    if not isinstance(value, Mapping):
        raise PredictionLabError("benchmark evidence is invalid")
    return BenchmarkEvidence(
        identity=str(value.get("identity", "")),
        return_value=_finite_number(value.get("return_value"), field="benchmark_return"),
        effective_trading_date=str(
            value.get("effective_trading_date", value.get("effective_date", ""))
        ),
        provider=str(value.get("provider", value.get("source", "unknown"))),
        payload_hash=str(value.get("payload_hash", value.get("payload_sha256", ""))),
        start_trading_date=(
            str(value["start_trading_date"]) if value.get("start_trading_date") else None
        ),
        end_trading_date=(
            str(value["end_trading_date"]) if value.get("end_trading_date") else None
        ),
        start_value=(float(value["start_value"]) if value.get("start_value") is not None else None),
        end_value=(float(value["end_value"]) if value.get("end_value") is not None else None),
        price_field=str(value.get("price_field", "close")),
        adjusted_raw_policy=str(value.get("adjusted_raw_policy", "raw")),
        payload_hashes=tuple(str(item) for item in value.get("payload_hashes", ()) or ()),
        provider_symbol=(
            str(value["provider_symbol"]) if value.get("provider_symbol") is not None else None
        ),
        source_type=(str(value["source_type"]) if value.get("source_type") is not None else None),
        checked_at=(str(value["checked_at"]) if value.get("checked_at") is not None else None),
        fetched_at=(str(value["fetched_at"]) if value.get("fetched_at") is not None else None),
    )


class PredictionOutcomeEvaluator:
    """Settle due predictions using one injected, hash-bound evidence source.

    The provider is deliberately a narrow read-only protocol.  It may be
    backed by a verified cache or an application refresh context, but the
    evaluator itself never fetches, writes market data, or guesses dates.
    """

    def __init__(
        self,
        store: PredictionLabStore,
        provider: PredictionOutcomeProvider,
        *,
        transaction_cost_assumption: float | None = None,
        cost_policy: PredictionCostPolicy | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.transaction_cost_assumption = (
            _finite_number(
                transaction_cost_assumption,
                field="transaction_cost_assumption",
                minimum=0.0,
            )
            if transaction_cost_assumption is not None
            else None
        )
        self.cost_policy = cost_policy
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _count(status: str) -> str:
        return {
            "evaluated": "evaluated_count",
            "eligible": "eligible_count",
            "pending": "pending_count",
            "unavailable": "unavailable_count",
        }[status]

    def evaluate_due(self, *, as_of: str | None = None) -> PredictionOutcomeEvaluationResult:
        as_of_date = _date(
            as_of or self.now_fn().astimezone(timezone.utc).date().isoformat(),
            field="as_of",
        )
        predictions, existing_outcomes = self.store.validate_graph()
        latest: dict[str, PredictionOutcome] = {}
        for outcome in sorted(existing_outcomes, key=_outcome_datetime):
            latest[outcome.prediction_id] = outcome
        results: list[PredictionOutcome] = []
        counts = {
            "evaluated_count": 0,
            "eligible_count": 0,
            "pending_count": 0,
            "unavailable_count": 0,
        }
        for prediction in sorted(predictions, key=lambda item: item.prediction_id):
            current = latest.get(prediction.prediction_id)
            if current is not None and current.status in {"evaluated", "unavailable"}:
                results.append(current)
                counts[self._count(current.status)] += 1
                continue
            try:
                calendar = self.provider.calendar(prediction.market)
                if calendar.market != prediction.market:
                    raise PredictionLabError("calendar market mismatch")
                target = calendar.target_date(prediction.trading_date, prediction.horizon)
                if target > as_of_date:
                    candidate = PredictionOutcome.create(
                        prediction=prediction,
                        evaluated_at=self.now_fn(),
                        calendar=calendar,
                        status="pending",
                    )
                else:
                    action_status_fn = getattr(self.provider, "corporate_action_status", None)
                    if callable(action_status_fn):
                        action_status, action_reason = action_status_fn(
                            prediction.identity, prediction.trading_date, target
                        )
                        if action_status != "clear":
                            candidate = PredictionOutcome.create(
                                prediction=prediction,
                                evaluated_at=self.now_fn(),
                                actual_available_date=target,
                                calendar=calendar,
                                status="eligible",
                                missing_reason=(action_reason or "公司行動證據不足；可稍後重試"),
                            )
                            saved = self.store.save_outcome(candidate)
                            results.append(saved)
                            counts[self._count(saved.status)] += 1
                            latest[prediction.prediction_id] = saved
                            continue
                    reference = prediction.entry_price_reference
                    if reference is None:
                        candidate = PredictionOutcome.create(
                            prediction=prediction,
                            evaluated_at=self.now_fn(),
                            actual_available_date=target,
                            calendar=calendar,
                            status="unavailable",
                            missing_reason="immutable entry price evidence unavailable",
                        )
                    else:
                        entry = _coerce_price_evidence(reference, field="entry_price")
                        if entry is None:
                            raise PredictionLabError("entry price evidence unavailable")
                        if (
                            entry.identity != prediction.identity
                            or _date(entry.effective_trading_date, field="entry date")
                            != prediction.trading_date
                        ):
                            raise PredictionLabError("entry price identity mismatch")
                        exit_evidence = _coerce_price_evidence(
                            self.provider.price(prediction.identity, target), field="exit_price"
                        )
                        try:
                            raw_benchmark = self.provider.benchmark(
                                prediction.benchmark_identity, target, prediction.trading_date
                            )
                        except TypeError:
                            # Backwards-compatible test providers from Phase 1
                            # accepted only the original two-argument method.
                            raw_benchmark = self.provider.benchmark(
                                prediction.benchmark_identity, target
                            )
                        benchmark_evidence = _coerce_benchmark_evidence(raw_benchmark)
                        if exit_evidence is None or benchmark_evidence is None:
                            candidate = PredictionOutcome.create(
                                prediction=prediction,
                                evaluated_at=self.now_fn(),
                                actual_available_date=target,
                                calendar=calendar,
                                status="eligible",
                            )
                        else:
                            if (
                                exit_evidence.identity != prediction.identity
                                or _date(
                                    exit_evidence.effective_trading_date,
                                    field="exit date",
                                )
                                != target
                                or benchmark_evidence.identity != prediction.benchmark_identity
                                or _date(
                                    benchmark_evidence.effective_trading_date,
                                    field="benchmark date",
                                )
                                != target
                            ):
                                raise PredictionLabError(
                                    "price or benchmark evidence identity mismatch"
                                )
                            strict = bool(getattr(self.provider, "strict_evidence", False))
                            if strict and (
                                benchmark_evidence.start_trading_date is None
                                or benchmark_evidence.end_trading_date is None
                                or benchmark_evidence.start_value is None
                                or benchmark_evidence.end_value is None
                            ):
                                raise PredictionLabError(
                                    "benchmark evidence lacks recomputable observations"
                                )
                            policy = self.cost_policy
                            if policy is None and strict:
                                policy = default_prediction_cost_policy(prediction.market)
                            cost_rate = (
                                policy.total_rate
                                if policy is not None
                                else self.transaction_cost_assumption
                            )
                            if strict and cost_rate is None:
                                raise PredictionLabError(
                                    "versioned transaction cost policy unavailable"
                                )
                            candidate = PredictionOutcome.create(
                                prediction=prediction,
                                evaluated_at=self.now_fn(),
                                actual_available_date=target,
                                entry_price=entry.value,
                                exit_price=exit_evidence.value,
                                benchmark_return=benchmark_evidence.return_value,
                                transaction_cost_assumption=(cost_rate or 0.0),
                                cost_policy_version=(policy.version if policy else None),
                                cost_components=(policy.components() if policy else None),
                                calendar=calendar,
                                entry_price_identity=reference,
                                exit_price_identity=exit_evidence.to_reference(),
                                benchmark_identity=benchmark_evidence.to_reference(),
                                source_hashes=(
                                    entry.payload_hash,
                                    exit_evidence.payload_hash,
                                    *benchmark_evidence.payload_hashes,
                                ),
                                status="evaluated",
                            )
                saved = self.store.save_outcome(candidate)
            except OSError:
                # Transport/cache faults are retryable.  Preserve the graph as
                # pending/eligible instead of making a temporary outage
                # terminal ``unavailable``.
                try:
                    calendar = self.provider.calendar(prediction.market)
                    target = calendar.target_date(prediction.trading_date, prediction.horizon)
                    saved = self.store.save_outcome(
                        PredictionOutcome.create(
                            prediction=prediction,
                            evaluated_at=self.now_fn(),
                            actual_available_date=(target if target <= as_of_date else None),
                            calendar=calendar,
                            status=("eligible" if target <= as_of_date else "pending"),
                            missing_reason=(
                                "結算來源暫時不可用；可稍後重試" if target <= as_of_date else None
                            ),
                        )
                    )
                except Exception:
                    if current is not None:
                        saved = current
                    else:
                        continue
            except (PredictionLabError, TypeError, ValueError) as exc:
                # An evidence integrity error is an explicit unavailable
                # result only when a verified calendar exists.  Never invent a
                # date or a performance value on provider failure.
                try:
                    calendar = self.provider.calendar(prediction.market)
                    target = calendar.target_date(prediction.trading_date, prediction.horizon)
                    saved = self.store.save_outcome(
                        PredictionOutcome.create(
                            prediction=prediction,
                            evaluated_at=self.now_fn(),
                            actual_available_date=(target if target <= as_of_date else None),
                            calendar=calendar,
                            status=("unavailable" if target <= as_of_date else "pending"),
                            missing_reason=(
                                _safe_evaluation_reason(exc) if target <= as_of_date else None
                            ),
                        )
                    )
                except Exception:
                    # No verified calendar means no safe durable outcome.  Keep
                    # the graph untouched and report the bounded failure.
                    if current is not None:
                        saved = current
                    else:
                        continue
            results.append(saved)
            counts[self._count(saved.status)] += 1
            latest[prediction.prediction_id] = saved
        status = "success"
        if counts["unavailable_count"] or counts["eligible_count"]:
            status = "partial"
        if not results:
            status = "unavailable"
        return PredictionOutcomeEvaluationResult(
            status=status,
            outcomes=tuple(results),
            **counts,
            message="到期樣本已完成可信結算" if status == "success" else "部分樣本仍待資料或不可用",
        )

    def has_due_or_retryable(self, *, as_of: str | None = None) -> bool:
        """Return whether an existing sample needs settlement or a retry.

        This read-only preflight is intentionally independent of registration.
        A run with no new predictions must still settle an older due sample,
        while a run with only future samples can safely mark the stage skipped
        without manufacturing a pending outcome.
        """

        as_of_date = _date(
            as_of or self.now_fn().astimezone(timezone.utc).date().isoformat(),
            field="as_of",
        )
        predictions, existing_outcomes = self.store.validate_graph()
        latest: dict[str, PredictionOutcome] = {}
        for outcome in sorted(existing_outcomes, key=_outcome_datetime):
            latest[outcome.prediction_id] = outcome
        for prediction in predictions:
            current = latest.get(prediction.prediction_id)
            if current is not None and current.status in {"evaluated", "unavailable"}:
                continue
            try:
                target = self.provider.calendar(prediction.market).target_date(
                    prediction.trading_date, prediction.horizon
                )
            except Exception:
                # A verified calendar/provider failure is retryable.  Let the
                # normal evaluator produce an explicit eligible/unavailable
                # record rather than silently skipping the sample.
                return True
            if target <= as_of_date:
                return True
        return False


def _safe_evaluation_reason(exc: BaseException) -> str:
    return f"結算證據不可用：{type(exc).__name__}"


class PredictionLabApplicationService:
    """Register/evaluate samples from a validated MarketSnapshot only."""

    def __init__(
        self, store: PredictionLabStore, *, now_fn: Callable[[], datetime] | None = None
    ) -> None:
        self.store = store
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def register_from_market_snapshot(
        self,
        snapshot: MarketSnapshot | None,
        *,
        trading_date: str,
        input_hashes: Sequence[str] = (),
        benchmark_identity: str = "TWSE:TAIEX",
        horizons: Sequence[int] = PREDICTION_HORIZONS,
        min_universe: int = 3,
    ) -> PredictionLabRegistrationResult:
        try:
            if (
                snapshot is None
                or snapshot.metadata.status != "ready"
                or snapshot.metadata.freshness != "fresh"
            ):
                raise PredictionLabError("market snapshot is not fresh and complete")
            parsed_benchmark = (
                _market_symbol(*benchmark_identity.split(":", 1))
                if ":" in benchmark_identity
                else None
            )
            if parsed_benchmark is None:
                raise PredictionLabError("benchmark identity is invalid")
            trading = _date(trading_date, field="trading_date")
            requested = tuple(dict.fromkeys(horizons))
            if not requested or any(horizon not in PREDICTION_HORIZONS for horizon in requested):
                raise PredictionLabError("unsupported prediction horizon")
            source_by_market = {item.market: item for item in snapshot.source_metadata}
            default_benchmarks = {
                "TWSE": "TWSE:TAIEX",
                "TPEX": "TPEX:OTC",
                "US": "US:SPX",
            }
            groups: dict[str, list[Any]] = {}
            for quote in snapshot.quotes:
                identity = _market_symbol(quote.market, quote.symbol)
                if quote.change_pct is None or not math.isfinite(float(quote.change_pct)):
                    continue
                groups.setdefault(identity.market.value, []).append(quote)
            if not groups or any(len(rows) < min_universe for rows in groups.values()):
                raise PredictionLabError(
                    "market universe is too small for top/middle/bottom samples"
                )
            # Callers may carry a transport/brief hash, but it must not become
            # prediction identity: fetched/checked/generated timestamps are
            # operational metadata.  The service owns the economic contract so
            # dashboard and scheduler cannot accidentally bypass it.
            input_provenance = (economic_input_fingerprint(snapshot, trading_date=trading),)
            candidates: list[PredictionRecord] = []
            for market, rows in sorted(groups.items()):
                rows.sort(key=lambda row: (-float(row.change_pct), str(row.symbol).upper()))
                n = len(rows)
                choices: tuple[tuple[PredictionBucket, int], ...] = (
                    ("top", 0),
                    ("middle", (n - 1) // 2),
                    ("bottom", n - 1),
                )
                source = source_by_market.get(market)
                source_hashes = (source.payload_sha256,) if source and source.payload_sha256 else ()
                if not source_hashes or source is None or not source.data_date:
                    raise PredictionLabError(f"source provenance missing for {market}")
                market_benchmark = (
                    parsed_benchmark.canonical
                    if parsed_benchmark.market.value == market
                    else default_benchmarks.get(market)
                )
                if market_benchmark is None:
                    raise PredictionLabError(f"benchmark identity is unavailable for {market}")
                cutoff = source.data_date if source else snapshot.metadata.data_date
                for horizon in requested:
                    for bucket, index in choices:
                        quote = rows[index]
                        candidates.append(
                            PredictionRecord.create(
                                created_at=self.now_fn(),
                                trading_date=trading,
                                market=market,
                                symbol=quote.symbol,
                                horizon=horizon,
                                bucket=bucket,
                                rank=index + 1,
                                universe_size=n,
                                deterministic_score=float(quote.change_pct),
                                source_cutoff=cutoff,
                                input_hashes=input_provenance,
                                source_hashes=source_hashes,
                                benchmark_identity=market_benchmark,
                                warnings=("僅為既有官方盤後排名的研究抽樣",),
                                limitations=("樣本累積中；沒有預測報酬、勝率或買賣建議",),
                                entry_price_reference=(
                                    {
                                        "identity": _market_symbol(market, quote.symbol).canonical,
                                        "value": quote.close,
                                        "effective_trading_date": trading,
                                        "provider": source.source,
                                        "payload_hash": source.payload_sha256,
                                        "price_field": "close",
                                        "adjusted_raw_policy": "raw",
                                    }
                                    if quote.close is not None
                                    else None
                                ),
                            )
                        )
            existing_ids = {record.prediction_id for record in self.store.predictions()}
            saved = tuple(self.store.save_prediction(record) for record in candidates)
            created_count = sum(record.prediction_id not in existing_ids for record in saved)
            skipped_count = len(saved) - created_count
            return PredictionLabRegistrationResult(
                "success",
                saved,
                "今日研究樣本已登錄；樣本累積中",
                created_count=created_count,
                skipped_count=skipped_count,
            )
        except (PredictionLabError, OSError, TypeError, ValueError) as exc:
            return PredictionLabRegistrationResult(
                "unavailable", (), "預測評估實驗室暫不可用；樣本未登錄", (type(exc).__name__,)
            )

    def summary(self, *, trading_date: str | None = None) -> PredictionLabSummary:
        try:
            return self.store.summary(trading_date=trading_date)
        except (PredictionLabError, OSError, ValueError) as exc:
            return PredictionLabSummary(
                "unavailable",
                "預測評估實驗室資料無法驗證；未顯示樣本",
                0,
                {bucket: 0 for bucket in PREDICTION_BUCKETS},
                {str(h): {} for h in PREDICTION_HORIZONS},
                0,
                0,
                None,
                (type(exc).__name__,),
                (),
            )

    def evaluate(self, outcome: PredictionOutcome) -> PredictionOutcome:
        return self.store.save_outcome(outcome)


__all__ = [
    "OUTCOME_SCHEMA_VERSION",
    "PREDICTION_BUCKETS",
    "PREDICTION_GENERATOR_VERSION",
    "PREDICTION_HORIZONS",
    "PREDICTION_RULE_VERSION",
    "PREDICTION_SCHEMA_VERSION",
    "PredictionLabApplicationService",
    "PredictionLabError",
    "PredictionLabRegistrationResult",
    "PredictionOutcomeEvaluationResult",
    "PredictionOutcomeEvaluator",
    "PredictionOutcomeProvider",
    "PriceEvidence",
    "BenchmarkEvidence",
    "BenchmarkRefreshResult",
    "BenchmarkRefreshService",
    "CorporateActionImportService",
    "PredictionCostPolicy",
    "RuntimeCachedOutcomeProvider",
    "default_prediction_cost_policy",
    "PredictionLabStore",
    "PredictionLabSummary",
    "PredictionOutcome",
    "PredictionRecord",
    "MarketTradingCalendar",
    "economic_input_fingerprint",
    "_atomic_create_json",
]
