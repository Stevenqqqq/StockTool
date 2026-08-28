"""Point-in-time visibility rules for fundamental records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd


class FundamentalPointInTimeMode(StrEnum):
    """Controls whether legacy fundamental dates may be used by a strategy."""

    LEGACY = "legacy"
    STRICT = "strict"


@dataclass(frozen=True, slots=True)
class FundamentalAvailabilityResult:
    """Non-mutating fundamental data plus explicit availability limitations."""

    data: pd.DataFrame
    warnings: tuple[str, ...] = ()


def visible_fundamentals_as_of(
    fundamentals: pd.DataFrame,
    decision_date: str,
    *,
    mode: FundamentalPointInTimeMode | str = FundamentalPointInTimeMode.LEGACY,
) -> FundamentalAvailabilityResult:
    """Return rows visible by ``available_date`` on a historical decision date."""

    resolved_mode = FundamentalPointInTimeMode(mode)
    frame = fundamentals.copy(deep=True)
    if resolved_mode is FundamentalPointInTimeMode.STRICT:
        if "available_date" not in frame.columns:
            return FundamentalAvailabilityResult(
                frame.iloc[0:0].copy(),
                ("Strict point-in-time mode requires available_date; no fundamentals were used.",),
            )
        availability = pd.to_datetime(frame["available_date"], errors="coerce").astype(
            "datetime64[ns]"
        )
        target = pd.Timestamp(decision_date)
        missing = availability.isna()
        warnings = (
            ()
            if not missing.any()
            else ("Rows without available_date were excluded in strict mode.",)
        )
        visible = frame.loc[~missing & (availability <= target)].copy()
        visible_availability = availability.loc[visible.index]
        visible["available_date"] = visible_availability
        visible["date"] = visible_availability
        return FundamentalAvailabilityResult(visible, warnings)

    if "date" not in frame.columns and "available_date" not in frame.columns:
        return FundamentalAvailabilityResult(
            frame.iloc[0:0].copy(),
            ("Legacy mode has no available_date or date; no fundamentals were used.",),
        )

    legacy_dates = (
        pd.to_datetime(frame["date"], errors="coerce").astype("datetime64[ns]")
        if "date" in frame.columns
        else pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    )
    available_dates = (
        pd.to_datetime(frame["available_date"], errors="coerce").astype("datetime64[ns]")
        if "available_date" in frame.columns
        else pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    )
    effective_dates = available_dates.where(available_dates.notna(), legacy_dates)
    if not effective_dates.notna().any():
        empty = frame.iloc[0:0].copy()
        empty["date"] = pd.Series(dtype="datetime64[ns]")
        empty["available_date"] = pd.Series(dtype="datetime64[ns]")
        return FundamentalAvailabilityResult(
            empty,
            ("Legacy mode has no usable available_date or date; no fundamentals were used.",),
        )

    frame["available_date"] = available_dates
    frame["date"] = effective_dates
    return FundamentalAvailabilityResult(
        frame,
        (
            "Legacy mode may use fundamental dates without verified available_date and can contain look-ahead bias.",
        ),
    )


def prepare_fundamental_strategy_frame(
    fundamentals: pd.DataFrame,
    *,
    mode: FundamentalPointInTimeMode | str = FundamentalPointInTimeMode.LEGACY,
) -> FundamentalAvailabilityResult:
    """Prepare non-mutating fundamental rows for backward-asof strategy joins."""

    return visible_fundamentals_as_of(fundamentals, "2262-04-11", mode=mode)
