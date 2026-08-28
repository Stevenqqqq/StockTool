"""Official Taiwan post-market monitoring contracts and application service.

The module deliberately keeps network access behind :meth:`refresh`.  Rendering
and cache reads are side-effect free, which makes the Explore workspace safe to
rerun and straightforward to test with an isolated cache path.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import urllib.request
import csv
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

MARKET_MONITOR_SCHEMA_VERSION = 2
TWSE_QUOTES_ENDPOINT = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_QUOTES_ENDPOINT = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TWSE_UNIVERSE_ENDPOINT = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_UNIVERSE_ENDPOINT = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TWSE_BREADTH_ENDPOINT = "https://openapi.twse.com.tw/v1/opendata/twtazu_od"
OFFICIAL_ENDPOINTS = {"TWSE": TWSE_QUOTES_ENDPOINT, "TPEX": TPEX_QUOTES_ENDPOINT}
UNIVERSE_ENDPOINTS = {"TWSE": TWSE_UNIVERSE_ENDPOINT, "TPEX": TPEX_UNIVERSE_ENDPOINT}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "--"}:
        return None
    candidates = (text, text.replace("/", "-"))
    roc_match = re.fullmatch(r"(\d{3})[/-]?(\d{2})[/-]?(\d{2})", text)
    if roc_match:
        year, month, day = (int(part) for part in roc_match.groups())
        if year < 1911:
            try:
                return datetime(year + 1911, month, day, tzinfo=timezone.utc)
            except ValueError:
                return None
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            return (
                parsed.replace(tzinfo=timezone.utc)
                if parsed.tzinfo is None
                else parsed.astimezone(timezone.utc)
            )
        except ValueError:
            continue
    for fmt in ("%Y%m%d", "%Y/%m/%d", "%Y-%m-%d", "%Y%m%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _key(value: Any) -> str:
    return re.sub(r"[^0-9a-zA-Z\u0080-\uffff]+", "", str(value).strip().lower())


def _field(row: Mapping[str, Any], *names: str) -> Any:
    normalized = {_key(name): value for name, value in row.items()}
    for name in names:
        if _key(name) in normalized:
            return normalized[_key(name)]
    return None


def parse_number(value: Any, *, percent: bool = False) -> float | None:
    """Parse an official numeric cell without turning missing values into zero."""

    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "").replace("＋", "+").replace("−", "-")
    if not text or text in {"--", "—", "-", "N/A", "NA", "null", "None"}:
        return None
    if percent:
        text = text.removesuffix("%").strip()
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _rows_from_payload(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for name in ("data", "aaData", "records", "result", "rows"):
            value = _field(payload, name)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                return [row for row in value if isinstance(row, Mapping)]
    return []


@dataclass(frozen=True, slots=True)
class MarketSnapshotMetadata:
    """Provenance and validation facts for one immutable snapshot."""

    schema_version: int
    source: str
    endpoint: str
    market: str
    data_date: str | None
    fetched_at: str
    valid_rows: int
    excluded_rows: int
    coverage: float
    payload_sha256: str
    status: str = "ready"
    freshness: str = "fresh"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketSourceMetadata:
    """Per-source provenance; combined views must not erase date differences."""

    market: str
    source: str
    endpoint: str
    data_date: str | None
    fetched_at: str
    valid_rows: int
    excluded_rows: int
    coverage: float
    payload_sha256: str
    universe_source: str = "official_company_list"
    universe_endpoint: str = ""
    universe_available: bool | None = None
    universe_payload_sha256: str = ""
    included_common_stock: int = 0
    excluded_non_stock: int = 0
    official_breadth_date: str | None = None
    breadth_status: str = "derived_only"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MarketQuoteRow:
    """One market-qualified official close quote."""

    symbol: str
    market: str
    name: str = ""
    close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    value: float | None = None
    status: str = "normal"
    industry: str | None = None
    product_type: str = "common_stock"

    @property
    def identity(self) -> str:
        return f"{self.market}:{self.symbol}"


@dataclass(frozen=True, slots=True)
class MarketBreadth:
    """Breadth counts and ratios derived only from valid close/change cells."""

    up: int
    down: int
    flat: int
    unknown: int
    valid_total: int

    @property
    def total(self) -> int:
        return self.up + self.down + self.flat + self.unknown

    @property
    def up_ratio(self) -> float:
        return self.up / self.valid_total if self.valid_total else 0.0

    @property
    def down_ratio(self) -> float:
        return self.down / self.valid_total if self.valid_total else 0.0

    @property
    def flat_ratio(self) -> float:
        return self.flat / self.valid_total if self.valid_total else 0.0


@dataclass(frozen=True, slots=True)
class RankingEntry:
    """Deterministically sorted ranking row."""

    category: str
    rank: int
    symbol: str
    market: str
    name: str
    value: float


@dataclass(frozen=True, slots=True)
class IndustryHeatRow:
    """Heat summary for the classified subset, including an explicit unknown row."""

    industry: str
    total_components: int
    valid_samples: int
    coverage: float
    average_change_pct: float | None
    up: int
    down: int
    flat: int
    unknown: int


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Serializable post-market data with derived, reproducible summaries."""

    metadata: MarketSnapshotMetadata
    quotes: tuple[MarketQuoteRow, ...]
    breadth: MarketBreadth
    rankings: tuple[RankingEntry, ...] = ()
    industry_heat: tuple[IndustryHeatRow, ...] = ()
    warnings: tuple[str, ...] = ()
    official_breadth: tuple[Mapping[str, Any], ...] = ()
    source_metadata: tuple[MarketSourceMetadata, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": {
                **asdict(self.metadata),
                "warnings": list(self.metadata.warnings),
            },
            "quotes": [asdict(row) for row in self.quotes],
            "breadth": asdict(self.breadth),
            "rankings": [asdict(row) for row in self.rankings],
            "industry_heat": [asdict(row) for row in self.industry_heat],
            "warnings": list(self.warnings),
            "official_breadth": [dict(row) for row in self.official_breadth],
            "source_metadata": [
                {**asdict(row), "warnings": list(row.warnings)} for row in self.source_metadata
            ],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MarketSnapshot:
        metadata_payload = dict(payload["metadata"])
        metadata_payload["warnings"] = tuple(metadata_payload.get("warnings", ()))
        return cls(
            metadata=MarketSnapshotMetadata(**metadata_payload),
            quotes=tuple(MarketQuoteRow(**row) for row in payload.get("quotes", ())),
            breadth=MarketBreadth(**payload["breadth"]),
            rankings=tuple(RankingEntry(**row) for row in payload.get("rankings", ())),
            industry_heat=tuple(IndustryHeatRow(**row) for row in payload.get("industry_heat", ())),
            warnings=tuple(payload.get("warnings", ())),
            official_breadth=tuple(dict(row) for row in payload.get("official_breadth", ())),
            source_metadata=tuple(
                MarketSourceMetadata(
                    **{**dict(row), "warnings": tuple(dict(row).get("warnings", ()))}
                )
                for row in payload.get("source_metadata", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class UniverseResolution:
    """Auditable official allow-list of ordinary stock identities."""

    market: str
    source: str
    endpoint: str
    codes: tuple[str, ...]
    available: bool
    included_common_stock: int
    excluded_non_stock: int
    warnings: tuple[str, ...] = ()


def parse_official_universe(payload: Any, *, market: str, endpoint: str = "") -> UniverseResolution:
    """Parse only official company-list rows; all other product types are excluded.

    The quote API contains ETFs, warrants and bonds.  A company-list allow-list is
    therefore required before a row may contribute to stock breadth/rankings.
    """

    canonical_market = str(market).strip().upper()
    if canonical_market not in OFFICIAL_ENDPOINTS:
        raise ValueError(f"Unsupported official market: {market!r}")
    rows = _rows_from_payload(payload)
    codes: set[str] = set()
    excluded = 0
    warnings: list[str] = []
    for raw in rows:
        symbol = (
            str(_field(raw, "Code", "SecuritiesCompanyCode", "股票代號", "公司代號") or "")
            .strip()
            .upper()
        )
        product_type = (
            str(
                _field(
                    raw,
                    "ProductType",
                    "SecurityType",
                    "Type",
                    "商品類型",
                    "證券種類",
                    "基金類型",
                )
                or ""
            )
            .strip()
            .lower()
        )
        is_non_stock = any(
            marker in product_type
            for marker in (
                "etf",
                "warrant",
                "權證",
                "債券",
                "bond",
                "convertible",
                "可轉債",
            )
        )
        if re.fullmatch(r"\d{4}", symbol) and not is_non_stock:
            codes.add(symbol)
        else:
            excluded += 1
    if not rows:
        warnings.append(f"{canonical_market} official stock universe is unavailable")
    elif not codes:
        warnings.append(f"{canonical_market} official stock universe has no ordinary stock codes")
    return UniverseResolution(
        market=canonical_market,
        source="official_company_list",
        endpoint=endpoint or UNIVERSE_ENDPOINTS[canonical_market],
        codes=tuple(sorted(codes)),
        available=bool(codes),
        included_common_stock=len(codes),
        excluded_non_stock=excluded,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True, slots=True)
class OfficialPayload:
    market: str
    payload: Any
    endpoint: str
    payload_sha256: str
    data_date: str | None = None
    official_breadth: Mapping[str, Any] | None = None
    universe_codes: tuple[str, ...] = ()
    universe_available: bool | None = None
    universe_endpoint: str = ""
    universe_payload_sha256: str = ""
    universe_source: str = "official_company_list"
    universe_warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CacheReadResult:
    status: str
    snapshot: MarketSnapshot | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class MarketRefreshResult:
    status: str
    source_state: str
    snapshot: MarketSnapshot | None
    warnings: tuple[str, ...] = ()


class MarketFetcher(Protocol):
    def fetch(self, market: str) -> OfficialPayload: ...


class EvidenceFixtureMarketFetcher:
    """Replay explicit official-shaped payloads only in guarded evidence mode.

    This seam is intentionally opt-in and never selected by normal product
    execution.  The caller must set ``STOCK_TOOL_EVIDENCE_MODE`` to the exact
    Sprint 32.1.1 value and run beneath a fresh system-temp data root.  The
    fixture is still parsed by the normal ``build_snapshot``/quote parser, so
    evidence cannot bypass the production data contract.
    """

    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir

    def fetch(self, market: str) -> OfficialPayload:
        canonical = str(market).strip().upper()
        path = self.fixture_dir / f"{canonical}.json"
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ValueError("evidence fixture must be UTF-8 without BOM")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("evidence fixture must be a JSON object")
        rows = payload.get("payload")
        data_date = payload.get("data_date")
        universe_codes = payload.get("universe_codes")
        official_breadth = payload.get("official_breadth")
        if (
            not isinstance(rows, (list, dict))
            or not isinstance(data_date, str)
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data_date)
            or not isinstance(universe_codes, list)
            or not universe_codes
            or not all(
                isinstance(code, str) and re.fullmatch(r"\d{4}", code) for code in universe_codes
            )
            or (official_breadth is not None and not isinstance(official_breadth, Mapping))
        ):
            raise ValueError("evidence fixture fields are invalid")
        endpoint = str(payload.get("endpoint") or OFFICIAL_ENDPOINTS[canonical])
        return OfficialPayload(
            market=canonical,
            payload=rows,
            endpoint=endpoint,
            payload_sha256=hashlib.sha256(raw).hexdigest(),
            data_date=data_date,
            official_breadth=dict(official_breadth) if official_breadth is not None else None,
            universe_codes=tuple(sorted(set(universe_codes))),
            universe_available=True,
            universe_endpoint=f"fixture://{canonical}/official-company-list",
            universe_payload_sha256=hashlib.sha256(
                (canonical + "|" + "|".join(sorted(set(universe_codes)))).encode("utf-8")
            ).hexdigest(),
            universe_source="official_company_list_fixture_replay",
        )


def _evidence_fixture_dir_from_environment() -> Path | None:
    """Return a validated fixture directory for explicit isolated evidence only."""

    if os.environ.get("STOCK_TOOL_EVIDENCE_MODE", "").strip() != "sprint32.1.1":
        return None
    raw_data_root = os.environ.get("STOCK_TOOL_USER_DATA_DIR", "").strip()
    raw_fixture_dir = os.environ.get("STOCK_TOOL_EVIDENCE_FIXTURE_DIR", "").strip()
    if not raw_data_root or not raw_fixture_dir:
        raise ValueError("evidence fixture mode requires isolated data and fixture roots")
    data_root = Path(raw_data_root).expanduser()
    fixture_dir = Path(raw_fixture_dir).expanduser()
    if not data_root.is_absolute() or not fixture_dir.is_absolute():
        raise ValueError("evidence fixture roots must be absolute")
    data_root = data_root.resolve(strict=False)
    fixture_dir = fixture_dir.resolve(strict=False)
    temp_root = Path(tempfile.gettempdir()).resolve()
    if temp_root not in data_root.parents or data_root == temp_root:
        raise ValueError("evidence fixture requires a child of the system temp root")
    if not fixture_dir.is_dir() or fixture_dir.is_symlink():
        raise ValueError("evidence fixture directory must be a regular directory")
    return fixture_dir


class OfficialMarketFetcher:
    """Small urllib-only client for the two official post-market endpoints."""

    def __init__(self, *, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def fetch(self, market: str) -> OfficialPayload:
        canonical = str(market).strip().upper()
        try:
            endpoint = OFFICIAL_ENDPOINTS[canonical]
        except KeyError as exc:
            raise ValueError(f"Unsupported official market: {market!r}") from exc
        payload, raw = self._get_json(endpoint)
        universe_codes: tuple[str, ...] = ()
        universe_available = False
        universe_endpoint = UNIVERSE_ENDPOINTS[canonical]
        universe_hash = ""
        universe_warnings: tuple[str, ...] = ()
        try:
            universe_payload, universe_raw = self._get_json(universe_endpoint)
            universe = parse_official_universe(
                universe_payload, market=canonical, endpoint=universe_endpoint
            )
            universe_codes = universe.codes
            universe_available = universe.available
            universe_hash = hashlib.sha256(universe_raw).hexdigest()
            universe_warnings = universe.warnings
        except Exception:
            # Quote data is retained for provenance, but no row is a stock unless
            # the official company-list allow-list was successfully obtained.
            universe_warnings = (
                f"{canonical} official stock universe unavailable; stock rows rejected",
            )
        official_breadth: Mapping[str, Any] | None = None
        official_breadth_hash: str | None = None
        if canonical == "TWSE":
            try:
                breadth_payload, _breadth_raw = self._get_json(TWSE_BREADTH_ENDPOINT)
                official_breadth = _parse_twse_official_breadth(breadth_payload)
                official_breadth_hash = _sha256_text(_canonical_json(breadth_payload))
            except Exception:
                official_breadth = None
        return OfficialPayload(
            market=canonical,
            payload=payload,
            endpoint=endpoint,
            payload_sha256=hashlib.sha256(raw).hexdigest(),
            data_date=_payload_data_date(payload),
            official_breadth=(
                {**official_breadth, "payload_sha256": official_breadth_hash}
                if official_breadth is not None and official_breadth_hash
                else official_breadth
            ),
            universe_codes=universe_codes,
            universe_available=universe_available,
            universe_endpoint=universe_endpoint,
            universe_payload_sha256=universe_hash,
            universe_warnings=universe_warnings,
        )

    def _get_json(self, endpoint: str) -> tuple[Any, bytes]:
        request = urllib.request.Request(
            endpoint,
            headers={"Accept": "application/json", "User-Agent": "StockTool/1.2"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8-sig")), raw


def parse_official_quotes(
    payload: Any,
    *,
    market: str,
    data_date: str | None = None,
    universe_codes: Iterable[str] | None = None,
    universe_available: bool | None = None,
) -> tuple[tuple[MarketQuoteRow, ...], int, tuple[str, ...]]:
    """Normalize a TWSE/TPEx list while retaining explicit exclusion warnings."""

    canonical_market = str(market).strip().upper()
    if canonical_market not in OFFICIAL_ENDPOINTS:
        raise ValueError(f"Unsupported official market: {market!r}")
    rows = _rows_from_payload(payload)
    normalized: list[MarketQuoteRow] = []
    warnings: list[str] = []
    identities: set[str] = set()
    excluded = 0
    non_stock_symbols: list[str] = []
    non_stock_excluded = 0
    allowed_codes = {str(code).strip().upper() for code in universe_codes or ()}
    if universe_available is False or (universe_available is True and not allowed_codes):
        excluded += len(rows)
        warnings.append(
            f"{canonical_market} official stock universe unavailable; all quote rows rejected"
        )
        return (), excluded, tuple(warnings)
    for raw in rows:
        symbol = (
            str(
                _field(raw, "Code", "Symbol", "SecurityCode", "SecuritiesCompanyCode", "股票代號")
                or ""
            )
            .strip()
            .upper()
        )
        row_market = _field(raw, "Market", "Exchange", "市場")
        if row_market is not None and str(row_market).strip().upper() not in {
            canonical_market,
            "TW" if canonical_market == "TWSE" else "TWO",
            "TPEX" if canonical_market == "TPEX" else "TWSE",
        }:
            excluded += 1
            warnings.append(f"excluded market-mismatch row for {symbol or 'unknown'}")
            continue
        if not symbol:
            excluded += 1
            warnings.append("excluded row without a symbol")
            continue
        if allowed_codes and symbol not in allowed_codes:
            excluded += 1
            non_stock_excluded += 1
            if len(non_stock_symbols) < 5:
                non_stock_symbols.append(symbol)
            continue
        identity = f"{canonical_market}:{symbol}"
        if identity in identities:
            excluded += 1
            warnings.append(f"excluded duplicate row {identity}")
            continue
        identities.add(identity)
        close = parse_number(_field(raw, "ClosingPrice", "Close", "Closing", "收盤價"))
        change = parse_number(_field(raw, "Change", "PriceChange", "漲跌", "漲跌價差"))
        change_pct = parse_number(
            _field(raw, "ChangePercent", "PriceChangePercent", "ChangePct", "漲跌幅"),
            percent=True,
        )
        if change_pct is None and change is not None and close is not None and close != change:
            previous = close - change
            if previous != 0:
                change_pct = change / previous * 100
        status_value = str(_field(raw, "Status", "TradingStatus", "狀態") or "").strip().lower()
        if close is not None and close <= 0:
            excluded += 1
            warnings.append(f"excluded invalid close for {identity}")
            continue
        status = "normal"
        if "suspend" in status_value or "停牌" in status_value:
            status = "suspended"
        elif close is None:
            status = "no_trade"
        normalized.append(
            MarketQuoteRow(
                symbol=symbol,
                market=canonical_market,
                name=str(_field(raw, "Name", "CompanyName", "證券名稱") or "").strip(),
                close=close,
                change=change,
                change_pct=change_pct,
                volume=parse_number(
                    _field(raw, "TradeVolume", "TradingShares", "Volume", "成交股數")
                ),
                value=parse_number(
                    _field(
                        raw,
                        "TradeValue",
                        "TradingAmount",
                        "TransactionAmount",
                        "Value",
                        "成交金額",
                    )
                ),
                status=status,
                industry=(str(_field(raw, "Industry", "Sector", "產業別") or "").strip() or None),
                product_type="common_stock",
            )
        )
    if not rows:
        warnings.append(f"{canonical_market} payload contained no recognizable rows")
    if non_stock_symbols:
        warnings.append(
            f"excluded non-stock products: {non_stock_excluded} "
            f"({', '.join(non_stock_symbols)})"
        )
    if data_date is None:
        data_date = _payload_data_date(payload)
    del data_date  # parsed here for validation; metadata owns the canonical date.
    return tuple(normalized), excluded, tuple(dict.fromkeys(warnings))


def parse_twse_quotes(
    payload: Any,
    *,
    data_date: str | None = None,
    universe_codes: Iterable[str] | None = None,
    universe_available: bool | None = None,
) -> tuple[tuple[MarketQuoteRow, ...], int, tuple[str, ...]]:
    """Convenience parser bound to the TWSE market identity."""

    return parse_official_quotes(
        payload,
        market="TWSE",
        data_date=data_date,
        universe_codes=universe_codes,
        universe_available=universe_available,
    )


def parse_tpex_quotes(
    payload: Any,
    *,
    data_date: str | None = None,
    universe_codes: Iterable[str] | None = None,
    universe_available: bool | None = None,
) -> tuple[tuple[MarketQuoteRow, ...], int, tuple[str, ...]]:
    """Convenience parser bound to the TPEx market identity."""

    return parse_official_quotes(
        payload,
        market="TPEX",
        data_date=data_date,
        universe_codes=universe_codes,
        universe_available=universe_available,
    )


def compute_breadth(rows: Iterable[MarketQuoteRow]) -> MarketBreadth:
    up = down = flat = unknown = 0
    for row in rows:
        if row.close is None or row.change is None:
            unknown += 1
        elif row.change > 0:
            up += 1
        elif row.change < 0:
            down += 1
        else:
            flat += 1
    return MarketBreadth(up=up, down=down, flat=flat, unknown=unknown, valid_total=up + down + flat)


def compare_official_breadth(
    derived: MarketBreadth, official: Mapping[str, Any] | None
) -> tuple[str, ...]:
    """Return an explicit warning when an official summary disagrees with rows."""

    if not official:
        return ()
    aliases = {
        "up": ("up", "advance", "advances", "上漲家數"),
        "down": ("down", "decline", "declines", "下跌家數"),
        "flat": ("flat", "unchanged", "平盤家數"),
    }
    observed: dict[str, int] = {}
    for label, names in aliases.items():
        for name in names:
            value = _field(official, name)
            number = parse_number(value)
            if number is not None:
                observed[label] = int(number)
                break
    warnings: list[str] = []
    for label, expected in (("up", derived.up), ("down", derived.down), ("flat", derived.flat)):
        if label in observed and observed[label] != expected:
            warnings.append(
                f"official breadth mismatch for {label}: official={observed[label]}, derived={expected}"
            )
    return tuple(warnings)


def _official_breadth_values(official: Mapping[str, Any] | None) -> dict[str, int] | None:
    """Parse complete official breadth without inventing missing values."""

    if not official:
        return None
    aliases = {
        "up": ("up", "advance", "advances", "銝撞摰嗆"),
        "down": ("down", "decline", "declines", "銝?摰嗆"),
        "flat": ("flat", "unchanged", "撟喟摰嗆"),
    }
    parsed: dict[str, int] = {}
    for label, names in aliases.items():
        value = next(
            (_field(official, name) for name in names if _field(official, name) is not None), None
        )
        number = parse_number(value)
        if number is None:
            return None
        parsed[label] = int(number)
    return parsed


def build_rankings(
    rows: Iterable[MarketQuoteRow], *, limit: int | None = 20
) -> tuple[RankingEntry, ...]:
    candidates = tuple(rows)
    result: list[RankingEntry] = []
    for category, attribute, reverse, predicate in (
        ("gainers", "change_pct", True, lambda value: value > 0),
        ("losers", "change_pct", False, lambda value: value < 0),
        ("volume", "volume", True, lambda _value: True),
        ("value", "value", True, lambda _value: True),
    ):
        valued = [
            row
            for row in candidates
            if getattr(row, attribute) is not None and predicate(getattr(row, attribute))
        ]
        valued.sort(
            key=lambda row: (
                -float(getattr(row, attribute)) if reverse else float(getattr(row, attribute)),
                row.market,
                row.symbol,
            )
        )
        if limit is not None:
            valued = valued[:limit]
        result.extend(
            RankingEntry(
                category=category,
                rank=index,
                symbol=row.symbol,
                market=row.market,
                name=row.name,
                value=float(getattr(row, attribute)),
            )
            for index, row in enumerate(valued, start=1)
        )
    return tuple(result)


def build_industry_heat(
    rows: Iterable[MarketQuoteRow],
    classifications: Mapping[tuple[str, str], str] | None = None,
) -> tuple[IndustryHeatRow, ...]:
    """Aggregate only known classifications; unknown securities remain visible."""

    groups: dict[str, list[MarketQuoteRow]] = defaultdict(list)
    for row in rows:
        industry = row.industry or (classifications or {}).get((row.market, row.symbol))
        groups[
            industry.strip() if isinstance(industry, str) and industry.strip() else "未分類"
        ].append(row)
    output: list[IndustryHeatRow] = []
    for industry in sorted(groups):
        group = groups[industry]
        changes = [row.change_pct for row in group if row.change_pct is not None]
        breadth = compute_breadth(group)
        output.append(
            IndustryHeatRow(
                industry=industry,
                total_components=len(group),
                valid_samples=len(changes),
                coverage=len(changes) / len(group) if group else 0.0,
                average_change_pct=sum(changes) / len(changes) if changes else None,
                up=breadth.up,
                down=breadth.down,
                flat=breadth.flat,
                unknown=breadth.unknown,
            )
        )
    return tuple(output)


def load_local_classifications(path: str | Path) -> dict[tuple[str, str], str]:
    """Read only existing local concept/industry labels; never performs network I/O."""

    result: dict[tuple[str, str], str] = {}
    source = Path(path)
    if not source.is_file():
        return result
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                symbol = str(row.get("symbol") or row.get("Code") or "").strip().upper()
                market = str(row.get("market") or row.get("Market") or "").strip().upper()
                industry = str(
                    row.get("industry") or row.get("sector") or row.get("concept") or ""
                ).strip()
                if symbol and market and industry:
                    result[(market, symbol)] = industry
    except (OSError, csv.Error):
        return {}
    return result


def build_snapshot(
    payloads: Sequence[OfficialPayload],
    *,
    fetched_at: datetime | None = None,
    classifications: Mapping[tuple[str, str], str] | None = None,
    status: str = "ready",
    extra_warnings: Sequence[str] = (),
) -> MarketSnapshot:
    if not payloads:
        raise ValueError("at least one official payload is required")
    fetched = fetched_at or _utc_now()
    all_rows: list[MarketQuoteRow] = []
    excluded = 0
    warnings: list[str] = list(extra_warnings)
    dates: list[str] = []
    endpoint_names: list[str] = []
    raw_hashes: list[str] = []
    official_breadth: list[Mapping[str, Any]] = []
    source_metadata: list[MarketSourceMetadata] = []
    for item in payloads:
        item_date = item.data_date or _payload_data_date(item.payload)
        rows, item_excluded, item_warnings = parse_official_quotes(
            item.payload,
            market=item.market,
            data_date=item_date,
            universe_codes=item.universe_codes,
            universe_available=item.universe_available,
        )
        if classifications:
            rows = tuple(
                MarketQuoteRow(
                    **{
                        **asdict(row),
                        "industry": row.industry or classifications.get((row.market, row.symbol)),
                    }
                )
                for row in rows
            )
        item_warning_list = list(item.universe_warnings) + list(item_warnings)
        item_breadth = compute_breadth(rows)
        breadth_status = "derived_only"
        official_breadth_date: str | None = None
        breadth_comparable = False
        if item.official_breadth:
            official_breadth.append(dict(item.official_breadth))
            official_breadth_date = _as_date_string(
                _field(item.official_breadth, "data_date", "Date", "資料日期")
            )
            parsed_official = _official_breadth_values(item.official_breadth)
            breadth_comparable = bool(
                parsed_official is not None
                and official_breadth_date
                and item_date
                and official_breadth_date == item_date
            )
            if breadth_comparable:
                breadth_status = "compared"
                item_warning_list.extend(
                    compare_official_breadth(item_breadth, item.official_breadth)
                )
            elif parsed_official is None:
                item_warning_list.append(
                    f"{item.market} official breadth unavailable or malformed; derived only"
                )
            elif not official_breadth_date or not item_date:
                item_warning_list.append(
                    f"{item.market} official breadth date missing; derived only"
                )
            else:
                breadth_status = "official_stale"
                item_warning_list.append(
                    f"{item.market} official breadth date {official_breadth_date} differs from quote date {item_date}; derived only"
                )
        else:
            item_warning_list.append(
                f"{item.market} breadth is derived only; no reliable official breadth number"
            )
        all_rows.extend(rows)
        excluded += item_excluded
        warnings.extend(item_warning_list)
        if item_date:
            dates.append(item_date)
        endpoint_names.append(item.endpoint)
        raw_hashes.append(item.payload_sha256)
        valid_rows = sum(1 for row in rows if row.close is not None)
        total_seen = len(rows) + item_excluded
        raw_symbols = {
            str(
                _field(
                    raw,
                    "Code",
                    "Symbol",
                    "SecurityCode",
                    "SecuritiesCompanyCode",
                    "股票代號",
                )
                or ""
            )
            .strip()
            .upper()
            for raw in _rows_from_payload(item.payload)
        }
        excluded_non_stock = (
            sum(1 for symbol in raw_symbols if symbol and symbol not in item.universe_codes)
            if item.universe_available
            else 0
        )
        source_metadata.append(
            MarketSourceMetadata(
                market=str(item.market).strip().upper(),
                source=f"{str(item.market).strip().upper()} official OpenAPI",
                endpoint=item.endpoint,
                data_date=item_date,
                fetched_at=_iso_datetime(fetched),
                valid_rows=valid_rows,
                excluded_rows=item_excluded,
                coverage=valid_rows / total_seen if total_seen else 0.0,
                payload_sha256=item.payload_sha256,
                universe_source=item.universe_source,
                universe_endpoint=item.universe_endpoint,
                universe_available=item.universe_available,
                universe_payload_sha256=item.universe_payload_sha256,
                included_common_stock=(
                    len(item.universe_codes) if item.universe_available else len(rows)
                ),
                excluded_non_stock=excluded_non_stock,
                official_breadth_date=official_breadth_date,
                breadth_status=breadth_status,
                warnings=tuple(dict.fromkeys(item_warning_list)),
            )
        )
    all_rows.sort(key=lambda row: (row.market, row.symbol))
    total_seen = len(all_rows) + excluded
    breadth = compute_breadth(all_rows)
    unique_dates = tuple(dict.fromkeys(dates))
    combined_date = unique_dates[0] if len(unique_dates) == 1 else None
    if len(unique_dates) > 1:
        warnings.append(
            "source data dates differ: "
            + ", ".join(f"{item.market}={item.data_date or '無資料'}" for item in source_metadata)
        )
    valid_rows = sum(1 for row in all_rows if row.close is not None)
    metadata = MarketSnapshotMetadata(
        schema_version=MARKET_MONITOR_SCHEMA_VERSION,
        source="TWSE/TPEx official OpenAPI",
        endpoint=";".join(endpoint_names),
        market="COMBINED" if len(payloads) > 1 else payloads[0].market,
        data_date=combined_date,
        fetched_at=_iso_datetime(fetched),
        valid_rows=valid_rows,
        excluded_rows=excluded,
        coverage=(valid_rows / total_seen if total_seen else 0.0),
        payload_sha256=_sha256_text("|".join(sorted(raw_hashes))),
        status=status,
        freshness="fresh",
        warnings=tuple(dict.fromkeys(warnings)),
    )
    return MarketSnapshot(
        metadata=metadata,
        quotes=tuple(all_rows),
        breadth=breadth,
        rankings=build_rankings(all_rows),
        industry_heat=build_industry_heat(all_rows, classifications),
        warnings=tuple(dict.fromkeys(warnings)),
        official_breadth=tuple(official_breadth),
        source_metadata=tuple(source_metadata),
    )


class MarketSnapshotCache:
    """Atomic, schema- and hash-validated JSON cache."""

    def __init__(self, path: str | Path, *, max_age: timedelta = timedelta(days=2)) -> None:
        self.path = Path(path)
        self.max_age = max_age

    def save(self, snapshot: MarketSnapshot) -> None:
        body = snapshot.to_dict()
        wrapper = {
            "schema_version": MARKET_MONITOR_SCHEMA_VERSION,
            "snapshot": body,
            "content_sha256": _sha256_text(_canonical_json(body)),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False, suffix=".tmp"
        ) as handle:
            json.dump(wrapper, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            temp_path = Path(handle.name)
        try:
            temp_path.replace(self.path)
        finally:
            temp_path.unlink(missing_ok=True)

    def load(self, *, now: datetime | None = None) -> CacheReadResult:
        if not self.path.is_file():
            return CacheReadResult(status="missing")
        try:
            wrapper = json.loads(self.path.read_text(encoding="utf-8"))
            if wrapper.get("schema_version") != MARKET_MONITOR_SCHEMA_VERSION:
                raise ValueError("unsupported schema")
            body = wrapper["snapshot"]
            if wrapper.get("content_sha256") != _sha256_text(_canonical_json(body)):
                raise ValueError("cache hash mismatch")
            snapshot = MarketSnapshot.from_dict(body)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return CacheReadResult(status="corrupt", warning=f"cache rejected: {exc}")
        fetched = _parse_datetime(snapshot.metadata.fetched_at)
        current = now or _utc_now()
        if fetched is not None and current - fetched > self.max_age:
            stale = _replace_snapshot_metadata(snapshot, freshness="stale", status="stale")
            return CacheReadResult(status="stale", snapshot=stale, warning="cache is stale")
        return CacheReadResult(status="fresh", snapshot=snapshot)


def _replace_snapshot_metadata(
    snapshot: MarketSnapshot, *, freshness: str, status: str
) -> MarketSnapshot:
    metadata = MarketSnapshotMetadata(
        **{**asdict(snapshot.metadata), "freshness": freshness, "status": status}
    )
    return MarketSnapshot(
        metadata=metadata,
        quotes=snapshot.quotes,
        breadth=snapshot.breadth,
        rankings=snapshot.rankings,
        industry_heat=snapshot.industry_heat,
        warnings=snapshot.warnings,
        official_breadth=snapshot.official_breadth,
        source_metadata=snapshot.source_metadata,
    )


class MarketMonitorApplicationService:
    """Application boundary for explicit official refresh and local replay."""

    def __init__(
        self,
        cache_path: str | Path,
        *,
        fetcher: MarketFetcher | Callable[[str], OfficialPayload] | None = None,
        now_fn: Callable[[], datetime] = _utc_now,
        classifications: Mapping[tuple[str, str], str] | None = None,
    ) -> None:
        self.cache = MarketSnapshotCache(cache_path)
        if fetcher is not None:
            self.fetcher = fetcher
        else:
            fixture_dir = _evidence_fixture_dir_from_environment()
            self.fetcher = (
                EvidenceFixtureMarketFetcher(fixture_dir)
                if fixture_dir is not None
                else OfficialMarketFetcher()
            )
        self.now_fn = now_fn
        self.classifications = classifications

    def load_cached(self) -> MarketRefreshResult:
        result = self.cache.load(now=self.now_fn())
        if result.snapshot is None:
            return MarketRefreshResult(
                status="unavailable",
                source_state=result.status,
                snapshot=None,
                warnings=((result.warning,) if result.warning else ()),
            )
        warnings = (result.warning,) if result.warning else ()
        return MarketRefreshResult(
            status=result.status,
            source_state="offline_cache" if result.status == "stale" else "local_cache",
            snapshot=result.snapshot,
            warnings=warnings + result.snapshot.warnings,
        )

    def refresh(self, *, markets: Sequence[str] = ("TWSE", "TPEX")) -> MarketRefreshResult:
        payloads: list[OfficialPayload] = []
        errors: list[str] = []
        for market in markets:
            try:
                payloads.append(self._fetch(market))
            except Exception:  # provider errors are user-visible but sanitized below
                errors.append(f"{str(market).upper()} official source unavailable")
        if payloads and not errors:
            universe_blocked = any(item.universe_available is False for item in payloads)
            snapshot = build_snapshot(
                payloads,
                fetched_at=self.now_fn(),
                classifications=self.classifications,
                status="partial" if universe_blocked else "ready",
            )
            if not universe_blocked:
                self.cache.save(snapshot)
            return MarketRefreshResult(
                status="partial" if universe_blocked else "fresh",
                source_state="official",
                snapshot=snapshot,
                warnings=snapshot.warnings,
            )
        if payloads:
            snapshot = build_snapshot(
                payloads,
                fetched_at=self.now_fn(),
                classifications=self.classifications,
                status="partial",
                extra_warnings=errors,
            )
            return MarketRefreshResult(
                status="partial",
                source_state="official",
                snapshot=snapshot,
                warnings=tuple(dict.fromkeys(errors + list(snapshot.warnings))),
            )
        cached = self.load_cached()
        if cached.snapshot is not None:
            warnings = tuple(dict.fromkeys(errors + list(cached.warnings)))
            return MarketRefreshResult(
                status="stale",
                source_state="offline_cache",
                snapshot=cached.snapshot,
                warnings=warnings,
            )
        return MarketRefreshResult(
            status="unavailable",
            source_state="missing",
            snapshot=None,
            warnings=tuple(errors) or ("official source unavailable",),
        )

    def _fetch(self, market: str) -> OfficialPayload:
        fetch = getattr(self.fetcher, "fetch", None)
        if callable(fetch):
            return _coerce_payload(fetch(market), market)
        if callable(self.fetcher):
            return _coerce_payload(self.fetcher(market), market)
        raise TypeError("invalid market fetcher")


MarketMonitorService = MarketMonitorApplicationService
MarketSnapshotService = MarketMonitorApplicationService


def _coerce_payload(value: Any, market: str) -> OfficialPayload:
    if isinstance(value, OfficialPayload):
        return value
    canonical = str(market).strip().upper()
    endpoint = OFFICIAL_ENDPOINTS.get(canonical, "")
    if isinstance(value, tuple) and len(value) == 2:
        payload, endpoint_value = value
        endpoint = str(endpoint_value)
    else:
        payload = value
    raw = _canonical_json(payload)
    return OfficialPayload(
        market=canonical,
        payload=payload,
        endpoint=endpoint,
        payload_sha256=_sha256_text(raw),
        data_date=_payload_data_date(payload),
    )


def _payload_data_date(payload: Any) -> str | None:
    for row in _rows_from_payload(payload):
        value = _field(row, "Date", "DataDate", "TradeDate", "資料日期")
        parsed = _parse_datetime(value)
        if parsed is not None:
            return parsed.date().isoformat()
        if value:
            return str(value).strip()
    if isinstance(payload, Mapping):
        value = _field(payload, "Date", "DataDate", "TradeDate", "資料日期")
        parsed = _parse_datetime(value)
        return (
            parsed.date().isoformat()
            if parsed is not None
            else (str(value).strip() if value else None)
        )
    return None


def _as_date_string(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed.date().isoformat()
    text = str(value).strip() if value is not None else ""
    return text or None


def _parse_twse_official_breadth(payload: Any) -> Mapping[str, Any] | None:
    """Extract the official TWSE stock breadth row, retaining its own date."""

    rows = _rows_from_payload(payload)
    for row in rows:
        kind = str(_field(row, "類型", "Type", "MarketType") or "").strip()
        if kind not in {"股票", "Stock", "stocks"}:
            continue
        return {
            "up": int(parse_number(_field(row, "上漲", "Up", "Advances")) or 0),
            "down": int(parse_number(_field(row, "下跌", "Down", "Declines")) or 0),
            "flat": int(parse_number(_field(row, "持平", "平盤", "Flat", "Unchanged")) or 0),
            "data_date": _as_date_string(_field(row, "出表日期", "Date", "資料日期")),
            "source": TWSE_BREADTH_ENDPOINT,
        }
    return None
