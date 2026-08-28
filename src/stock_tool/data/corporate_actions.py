"""Explicit, point-in-time corporate-action contracts for research backtests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
import hashlib
import io
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, cast

import pandas as pd

from stock_tool.domain.models import Market, Symbol


class CorporateActionDataError(ValueError):
    """Raised when a corporate-action input cannot be used safely."""


CORPORATE_ACTION_POLICY_VERSION = "corporate-action-contract-v1"


class CorporateActionType(StrEnum):
    """Corporate actions supported by the deterministic Sprint 13 contract."""

    SPLIT = "split"
    CASH_DIVIDEND = "cash_dividend"


class PricePolicy(StrEnum):
    """How a backtest price series handles splits and cash dividends."""

    RAW_PRICE_WITH_EXPLICIT_ACTIONS = "raw_price_with_explicit_actions"
    ADJUSTED_TOTAL_RETURN = "adjusted_total_return"
    UNKNOWN = "unknown"


class ReturnBasis(StrEnum):
    """Return basis used for strategy and benchmark comparison."""

    PRICE_RETURN = "price_return"
    TOTAL_RETURN = "total_return"


@dataclass(frozen=True, slots=True)
class AdjustedSeriesContract:
    """Explicit evidence that ``adjusted_close`` is a verified total-return series.

    A column named ``adjusted_close`` is not evidence by itself. Callers must
    opt in with a source-backed contract before the engine can execute or mark
    a total-return backtest from adjusted prices.
    """

    source: str
    verified: bool
    price_column: str = "adjusted_close"
    return_basis: ReturnBasis | str = ReturnBasis.TOTAL_RETURN
    provenance: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not str(self.source).strip():
            raise CorporateActionDataError("adjusted series contract source is required")
        if not self.verified:
            raise CorporateActionDataError("adjusted series contract must be verified")
        if self.price_column != "adjusted_close":
            raise CorporateActionDataError("adjusted series contract requires adjusted_close")
        try:
            basis = ReturnBasis(str(self.return_basis))
        except ValueError as exc:
            raise CorporateActionDataError("unsupported adjusted series return basis") from exc
        if basis is not ReturnBasis.TOTAL_RETURN:
            raise CorporateActionDataError("adjusted series contract requires total_return")
        object.__setattr__(self, "source", str(self.source).strip())
        object.__setattr__(self, "return_basis", basis)
        object.__setattr__(self, "provenance", dict(self.provenance or {}))


@dataclass(frozen=True, slots=True)
class CorporateAction:
    """One market-qualified, source-backed corporate action.

    The local import contract intentionally does not claim comprehensive live
    coverage. ``available_date`` is therefore optional in the data model so an
    incomplete row can be preserved and rejected explicitly by the engine.
    """

    symbol: Symbol
    action_type: CorporateActionType | str
    effective_date: str
    available_date: str | None
    payable_date: str | None = None
    split_ratio: float | None = None
    cash_per_share: float | None = None
    currency: str | None = None
    tax_rate: float | None = None
    source: str = ""
    provenance: Mapping[str, Any] | None = None
    confidence: str = "unknown"
    completeness: str = "unknown"
    notes: str | None = None
    source_evidence: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, Symbol):
            raise TypeError("symbol must be a market-qualified Symbol")
        if self.symbol.market in {Market.AUTO, Market.CUSTOM}:
            raise CorporateActionDataError("corporate actions require a known market")
        try:
            action_type = CorporateActionType(str(self.action_type))
        except ValueError as exc:
            raise CorporateActionDataError("unsupported corporate action type") from exc
        effective = _required_date(self.effective_date, "effective_date")
        available = _optional_date(self.available_date, "available_date")
        payable = _optional_date(self.payable_date, "payable_date")
        if payable is not None and payable < effective:
            raise CorporateActionDataError("payable_date must not precede effective_date")
        source = str(self.source).strip()
        if not source:
            raise CorporateActionDataError("corporate action source is required")
        confidence = str(self.confidence).strip().lower()
        if confidence not in {"complete", "partial", "unknown"}:
            raise CorporateActionDataError("confidence must be complete, partial, or unknown")
        completeness = str(self.completeness).strip().lower()
        if completeness not in {"complete", "partial", "unknown"}:
            raise CorporateActionDataError("completeness must be complete, partial, or unknown")

        split_ratio = _optional_positive_float(self.split_ratio, "split_ratio")
        cash_per_share = _optional_positive_float(self.cash_per_share, "cash_per_share")
        tax_rate = _optional_tax_rate(self.tax_rate)
        currency = _optional_text(self.currency)
        if action_type is CorporateActionType.SPLIT:
            if split_ratio is None:
                raise CorporateActionDataError("split actions require split_ratio")
            if cash_per_share is not None:
                raise CorporateActionDataError("split actions cannot include cash_per_share")
        else:
            if cash_per_share is None:
                raise CorporateActionDataError("cash dividend actions require cash_per_share")
            if split_ratio is not None:
                raise CorporateActionDataError("cash dividend actions cannot include split_ratio")
            if not currency:
                raise CorporateActionDataError("cash dividend actions require currency")

        object.__setattr__(self, "action_type", action_type)
        object.__setattr__(self, "effective_date", effective.isoformat())
        object.__setattr__(self, "available_date", available.isoformat() if available else None)
        object.__setattr__(self, "payable_date", payable.isoformat() if payable else None)
        object.__setattr__(self, "split_ratio", split_ratio)
        object.__setattr__(self, "cash_per_share", cash_per_share)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "tax_rate", tax_rate)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "provenance", dict(self.provenance or {}))
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "completeness", completeness)
        object.__setattr__(self, "notes", _optional_text(self.notes))
        normalized_evidence = tuple(dict(item) for item in self.source_evidence)
        object.__setattr__(self, "source_evidence", normalized_evidence)

    @property
    def event_id(self) -> str:
        """Return a deterministic provenance identity for one source record."""

        payload = {
            "symbol": self.symbol.to_dict(),
            "action_type": self.kind.value,
            "effective_date": self.effective_date,
            "available_date": self.available_date,
            "payable_date": self.payable_date,
            "split_ratio": self.split_ratio,
            "cash_per_share": self.cash_per_share,
            "currency": self.currency,
            "tax_rate": self.tax_rate,
            "source": self.source,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()

    @property
    def economic_event_key(self) -> str:
        """Return the source-independent identity of an economic event."""

        payload = {
            "market": self.symbol.market.value,
            "symbol": self.symbol.code,
            "action_type": self.kind.value,
            "effective_date": self.effective_date,
        }
        return _stable_digest(payload)

    @property
    def economic_terms_key(self) -> str:
        """Return the source-independent economic terms used for conflict checks."""

        payload = {
            "split_ratio": self.split_ratio,
            "cash_per_share": self.cash_per_share,
            "currency": self.currency,
            "payable_date": self.payable_date,
            "tax_rate": self.tax_rate,
        }
        return _stable_digest(payload)

    def evidence_record(self) -> dict[str, Any]:
        """Return safe provenance needed to audit an equivalent-source group."""

        return {
            "event_id": self.event_id,
            "source": self.source,
            "available_date": self.available_date,
            "provenance": dict(self.provenance or {}),
            "confidence": self.confidence,
            "completeness": self.completeness,
        }

    def is_available_on(self, decision_date: str | date) -> bool:
        """Return whether the action was known no later than ``decision_date``."""

        available = _optional_date(self.available_date, "available_date")
        if available is None:
            return False
        return available <= _required_date(decision_date, "decision_date")

    @property
    def kind(self) -> CorporateActionType:
        """Return the validated action type with a narrow runtime type."""

        return cast(CorporateActionType, self.action_type)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the action without making a coverage claim."""

        return {
            "symbol": self.symbol.code,
            "market": self.symbol.market.value,
            "action_type": self.kind.value,
            "effective_date": self.effective_date,
            "available_date": self.available_date,
            "payable_date": self.payable_date,
            "split_ratio": self.split_ratio,
            "cash_per_share": self.cash_per_share,
            "currency": self.currency,
            "tax_rate": self.tax_rate,
            "source": self.source,
            "provenance": dict(self.provenance or {}),
            "confidence": self.confidence,
            "completeness": self.completeness,
            "notes": self.notes,
            "event_id": self.event_id,
            "economic_event_key": self.economic_event_key,
            "economic_terms_key": self.economic_terms_key,
            "source_evidence": [dict(item) for item in self.source_evidence],
        }


def load_corporate_actions_csv(path: str | Path) -> tuple[CorporateAction, ...]:
    """Import the documented deterministic corporate-action CSV contract."""

    source_path = Path(path)
    try:
        raw = source_path.read_bytes()
        raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CorporateActionDataError("corporate action CSV is not valid UTF-8") from exc
    payload_hash = hashlib.sha256(raw).hexdigest()
    frame = pd.read_csv(io.BytesIO(raw), dtype="string")
    if frame.empty:
        raise CorporateActionDataError("corporate action CSV is empty")
    actions = corporate_actions_from_frame(frame)
    # Keep the existing immutable CorporateAction contract while attaching
    # enough source evidence for a production restart to re-verify the same
    # input.  Only the basename-independent payload identity is persisted.
    return tuple(
        replace(
            action,
            provenance={
                **dict(action.provenance or {}),
                "payload_sha256": payload_hash,
                "policy_version": CORPORATE_ACTION_POLICY_VERSION,
            },
        )
        for action in actions
    )


def corporate_actions_from_frame(frame: pd.DataFrame) -> tuple[CorporateAction, ...]:
    """Create validated actions from local CSV-compatible rows."""

    required = {"symbol", "market", "action_type", "effective_date", "available_date", "source"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise CorporateActionDataError(
            f"corporate action data missing columns: {', '.join(missing)}"
        )
    actions: list[CorporateAction] = []
    for row in frame.copy(deep=True).to_dict(orient="records"):
        policy = _row_optional_text(row.get("adjusted_raw_policy"))
        actions.append(
            CorporateAction(
                symbol=Symbol.parse(str(row["symbol"]), market=Market.parse(str(row["market"]))),
                action_type=str(row["action_type"]),
                effective_date=str(row["effective_date"]),
                available_date=_row_optional_text(row.get("available_date")),
                payable_date=_row_optional_text(row.get("payable_date")),
                split_ratio=_row_optional_float(row.get("split_ratio")),
                cash_per_share=_row_optional_float(row.get("cash_per_share")),
                currency=_row_optional_text(row.get("currency")),
                tax_rate=_row_optional_float(row.get("tax_rate")),
                source=str(row["source"]),
                provenance={
                    "import": "corporate_actions_csv",
                    **({"adjusted_raw_policy": policy} if policy is not None else {}),
                },
                confidence=_row_optional_text(row.get("confidence")) or "unknown",
                completeness=_row_optional_text(row.get("completeness")) or "unknown",
                notes=_row_optional_text(row.get("notes")),
            )
        )
    return tuple(actions)


def _required_date(value: str | date, field: str) -> date:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise CorporateActionDataError(f"{field} must be a valid date")
    return parsed.date()


def _optional_date(value: str | date | None, field: str) -> date | None:
    if value is None or not str(value).strip() or str(value).strip() == "<NA>":
        return None
    return _required_date(value, field)


def _optional_positive_float(value: float | None, field: str) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CorporateActionDataError(f"{field} must be numeric") from exc
    if not isfinite(parsed) or parsed <= 0:
        raise CorporateActionDataError(f"{field} must be a finite positive value")
    return parsed


def _optional_tax_rate(value: float | None) -> float:
    if value is None or pd.isna(value):
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CorporateActionDataError("tax_rate must be numeric") from exc
    if not isfinite(parsed) or not 0 <= parsed <= 1:
        raise CorporateActionDataError("tax_rate must be between 0 and 1")
    return parsed


def _optional_text(value: object) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _stable_digest(payload: Mapping[str, Any]) -> str:
    """Hash a JSON-compatible value using deterministic representation."""

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()


def _row_optional_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return _optional_text(value)


def _row_optional_float(value: object) -> float | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    return float(str(value))
