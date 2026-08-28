"""Simple stock screener built on the latest available indicator rows."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ScreenerCriteria:
    """Optional filters for the latest row of each symbol."""

    min_close: float | None = None
    max_close: float | None = None
    min_volume: float | None = None
    min_return_20d: float | None = None
    max_volatility_20d: float | None = None
    min_rsi: float | None = None
    max_rsi: float | None = None


@dataclass(frozen=True)
class ScreenerResult:
    """Screener matches and warnings for filters that could not be applied."""

    matches: pd.DataFrame
    warnings: tuple[str, ...] = ()


def screen_stocks(indicators: pd.DataFrame, criteria: ScreenerCriteria) -> ScreenerResult:
    """Filter the latest indicator row for each symbol.

    The function does not calculate indicators itself and never mutates the
    input DataFrame. When a requested filter column is missing, the filter is
    not applied and a warning is returned so the UI can avoid implying false
    precision.
    """

    if indicators.empty:
        return ScreenerResult(matches=pd.DataFrame(), warnings=("沒有可用的技術指標資料。",))
    if "symbol" not in indicators.columns:
        return ScreenerResult(matches=pd.DataFrame(), warnings=("缺少 symbol 欄位。",))

    latest = _latest_rows(indicators)
    warnings: list[str] = []
    mask = pd.Series(True, index=latest.index)

    mask = _apply_min(latest, mask, "close", criteria.min_close, warnings)
    mask = _apply_max(latest, mask, "close", criteria.max_close, warnings)
    mask = _apply_min(latest, mask, "volume", criteria.min_volume, warnings)
    mask = _apply_min(latest, mask, "return_20", criteria.min_return_20d, warnings)
    mask = _apply_max(latest, mask, "volatility_20", criteria.max_volatility_20d, warnings)
    mask = _apply_min(latest, mask, "rsi_14", criteria.min_rsi, warnings)
    mask = _apply_max(latest, mask, "rsi_14", criteria.max_rsi, warnings)

    matches = latest.loc[mask].reset_index(drop=True)
    return ScreenerResult(matches=matches, warnings=tuple(warnings))


def _latest_rows(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy(deep=True)
    if "date" in output.columns:
        output = output.sort_values(["symbol", "date"])
    return output.groupby("symbol", as_index=False, sort=False).tail(1).reset_index(drop=True)


def _apply_min(
    frame: pd.DataFrame,
    mask: pd.Series,
    column: str,
    threshold: float | None,
    warnings: list[str],
) -> pd.Series:
    if threshold is None:
        return mask
    if column not in frame.columns:
        warnings.append(f"因缺少欄位而略過篩選條件：{column}")
        return mask
    return mask & (pd.to_numeric(frame[column], errors="coerce") >= threshold)


def _apply_max(
    frame: pd.DataFrame,
    mask: pd.Series,
    column: str,
    threshold: float | None,
    warnings: list[str],
) -> pd.Series:
    if threshold is None:
        return mask
    if column not in frame.columns:
        warnings.append(f"因缺少欄位而略過篩選條件：{column}")
        return mask
    return mask & (pd.to_numeric(frame[column], errors="coerce") <= threshold)
