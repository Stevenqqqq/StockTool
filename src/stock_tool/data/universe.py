"""Explicit historical-universe import and point-in-time membership queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from stock_tool.data.corporate_models import DatasetCompleteness, MembershipStatus
from stock_tool.domain.models import Market, Symbol


class UniverseDataError(ValueError):
    """Raised when an historical-universe import cannot be used safely."""


@dataclass(frozen=True, slots=True)
class UniverseMembership:
    """One market-qualified membership interval from an imported source."""

    symbol: Symbol
    effective_from: str
    effective_to: str | None
    status: str
    source: str
    dataset_completeness: str

    def __post_init__(self) -> None:
        start = _date(self.effective_from, "effective_from")
        end = _optional_date(self.effective_to)
        if end is not None and end < start:
            raise UniverseDataError("effective_to must not precede effective_from")
        try:
            MembershipStatus(str(self.status))
            DatasetCompleteness(str(self.dataset_completeness))
        except ValueError as exc:
            raise UniverseDataError("invalid membership status or dataset completeness") from exc
        if self.symbol.market in {Market.AUTO, Market.CUSTOM}:
            raise UniverseDataError("historical universe requires a known market")
        if not str(self.source).strip():
            raise UniverseDataError("source is required")
        object.__setattr__(self, "effective_from", start.isoformat())
        object.__setattr__(self, "effective_to", None if end is None else end.isoformat())


@dataclass(frozen=True, slots=True)
class HistoricalUniverse:
    """Validated historical membership data; no current-universe fallback occurs."""

    memberships: tuple[UniverseMembership, ...]
    dataset_completeness: str
    source: str

    def __post_init__(self) -> None:
        try:
            DatasetCompleteness(str(self.dataset_completeness))
        except ValueError as exc:
            raise UniverseDataError("invalid dataset_completeness") from exc
        _validate_intervals(self.memberships)

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> HistoricalUniverse:
        """Build a validated copy from the documented CSV import columns."""

        required = {
            "symbol",
            "market",
            "effective_from",
            "effective_to",
            "status",
            "source",
            "dataset_completeness",
        }
        missing = sorted(required - set(frame.columns))
        if missing:
            raise UniverseDataError(f"historical universe missing columns: {', '.join(missing)}")
        memberships: list[UniverseMembership] = []
        for row in frame.copy(deep=True).to_dict(orient="records"):
            try:
                symbol = Symbol.parse(str(row["symbol"]), market=Market.parse(str(row["market"])))
            except ValueError as exc:
                raise UniverseDataError(
                    f"invalid market-qualified symbol: {row.get('symbol')!r}"
                ) from exc
            memberships.append(
                UniverseMembership(
                    symbol=symbol,
                    effective_from=str(row["effective_from"]),
                    effective_to=(
                        None
                        if pd.isna(row["effective_to"])
                        or str(row["effective_to"]).strip() in {"", "<NA>"}
                        else str(row["effective_to"])
                    ),
                    status=str(row["status"]),
                    source=str(row["source"]),
                    dataset_completeness=str(row["dataset_completeness"]),
                )
            )
        completeness = _aggregate_completeness(item.dataset_completeness for item in memberships)
        source = ", ".join(sorted({item.source for item in memberships})) or "unknown"
        return cls(tuple(memberships), completeness, source)

    def members_as_of(self, as_of: str | date) -> tuple[UniverseMembership, ...]:
        """Return only memberships active on the requested historical date."""

        target = _date(as_of, "as_of")
        return tuple(
            item
            for item in self.memberships
            if _date(item.effective_from, "effective_from") <= target
            and (item.effective_to is None or target <= _date(item.effective_to, "effective_to"))
        )


def load_historical_universe_csv(path: str | Path) -> HistoricalUniverse:
    """Import a local, deterministic historical-universe CSV contract."""

    frame = pd.read_csv(Path(path), dtype="string")
    if frame.empty:
        raise UniverseDataError("historical universe CSV is empty")
    return HistoricalUniverse.from_frame(frame)


def survivorship_bias_warnings(universe: HistoricalUniverse | None) -> tuple[str, ...]:
    """Describe remaining survivorship limitations without claiming resolution."""

    if universe is None:
        return (
            "此回測可能受存活者偏誤影響：未提供 point-in-time 股票池或下市證券資料。 "
            "This backtest may be affected by survivorship bias because no point-in-time universe or delisted securities data was provided.",
        )
    completeness = DatasetCompleteness(universe.dataset_completeness)
    warnings: list[str] = []
    if completeness is not DatasetCompleteness.COMPLETE:
        warnings.append(
            f"歷史股票池資料集為 {completeness.value}；存活者偏誤尚未完全解決。 "
            f"Historical universe dataset is {completeness.value}; survivorship bias is not fully resolved."
        )
    if not any(item.status == MembershipStatus.DELISTED.value for item in universe.memberships):
        warnings.append(
            "Delisted securities data is missing or incomplete; survivorship bias may remain."
        )
    if any(
        item.status == MembershipStatus.DELISTED_PLACEHOLDER.value for item in universe.memberships
    ):
        warnings.append(
            "Delisted placeholders identify data gaps and do not provide complete delisted history."
        )
    return tuple(warnings)


def _validate_intervals(memberships: Iterable[UniverseMembership]) -> None:
    grouped: dict[str, list[UniverseMembership]] = {}
    for membership in memberships:
        grouped.setdefault(membership.symbol.canonical, []).append(membership)
    for identity, items in grouped.items():
        ordered = sorted(items, key=lambda item: item.effective_from)
        for previous, current in zip(ordered, ordered[1:]):
            previous_end = _optional_date(previous.effective_to)
            if (
                previous_end is None
                or _date(current.effective_from, "effective_from") <= previous_end
            ):
                raise UniverseDataError(f"overlap detected for {identity}")


def _aggregate_completeness(values: Iterable[str]) -> str:
    parsed = {DatasetCompleteness(value) for value in values}
    if DatasetCompleteness.UNKNOWN in parsed:
        return DatasetCompleteness.UNKNOWN.value
    if DatasetCompleteness.PARTIAL in parsed:
        return DatasetCompleteness.PARTIAL.value
    return DatasetCompleteness.COMPLETE.value


def _date(value: str | date, field: str) -> date:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise UniverseDataError(f"{field} must be a valid date")
    return parsed.date()


def _optional_date(value: str | None) -> date | None:
    if value is None or not str(value).strip():
        return None
    return _date(value, "effective_to")
