"""Read-only, cached home-summary data for the Dashboard shell."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from stock_tool.domain.models import Market
from stock_tool.portfolio_management import load_portfolio_result
from stock_tool.watchlist import build_effective_watchlist, load_watchlist

_CACHE_KEY = "dashboard_home_summary_cache"


@dataclass(frozen=True, slots=True)
class HomeDataSummary:
    """Non-sensitive counts for the first Dashboard screen."""

    portfolio_count: int | None
    watchlist_count: int | None
    warnings: tuple[str, ...] = ()


def load_home_summary(
    session: MutableMapping[str, Any],
    *,
    portfolio_path: Path,
    watchlist_path: Path,
) -> HomeDataSummary:
    """Load local counts once per unchanged file state without writing user data."""

    signature = (_file_signature(portfolio_path), _file_signature(watchlist_path))
    cached = session.get(_CACHE_KEY)
    if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == signature:
        summary = cached[1]
        if isinstance(summary, HomeDataSummary):
            return summary

    portfolio_count, portfolio_warning = _portfolio_count(portfolio_path)
    manual_watchlist, watchlist_warning = _manual_watchlist(watchlist_path)
    portfolio = load_portfolio_result(portfolio_path).frame
    watchlist_count = (
        None
        if manual_watchlist is None
        else len(build_effective_watchlist(manual_watchlist, portfolio))
    )
    warnings = tuple(item for item in (portfolio_warning, watchlist_warning) if item)
    summary = HomeDataSummary(
        portfolio_count=portfolio_count,
        watchlist_count=watchlist_count,
        warnings=warnings,
    )
    session[_CACHE_KEY] = (signature, summary)
    return summary


def _file_signature(path: Path) -> tuple[str, int, int] | tuple[str]:
    """Return metadata sufficient to invalidate the small read-only summary cache."""

    try:
        stat = path.stat()
    except FileNotFoundError:
        return ("missing",)
    except OSError:
        return ("unavailable",)
    return ("file", stat.st_mtime_ns, stat.st_size)


def _portfolio_count(path: Path) -> tuple[int | None, str | None]:
    """Read only market-resolved portfolio rows and explain unresolved rows concretely."""

    if not path.exists():
        return 0, None
    result = load_portfolio_result(path)
    if result.frame.empty:
        if result.warnings or result.missing_data:
            return None, "持股摘要資料不足：無法安全讀取持股檔。"
        return 0, None
    known_markets = {"TWSE", "TPEX", "US"}
    resolved = result.frame.loc[result.frame["market"].isin(known_markets)]
    unresolved = result.frame.loc[~result.frame["market"].isin(known_markets)]
    if not unresolved.empty:
        details = "；".join(_unresolved_market_details(path, unresolved))
        message = f"持股摘要資料不足：無法解析 {details}；未納入價格覆蓋率。"
        return (len(resolved) if not resolved.empty else None), message
    if result.warnings or result.missing_data:
        return len(resolved), "持股摘要：部分非價格欄位資料不足，但已讀取可辨識的持股。"
    return len(resolved), None


def _unresolved_market_details(path: Path, normalized: pd.DataFrame) -> tuple[str, ...]:
    """Report original invalid market codes when the local CSV remains readable."""

    details: list[str] = []
    try:
        source = pd.read_csv(path, dtype={"symbol": str, "market": str})
    except (OSError, UnicodeDecodeError, pd.errors.ParserError):
        source = pd.DataFrame()
    if {"symbol", "market"}.issubset(source.columns):
        for index, row in source[["symbol", "market"]].iterrows():
            raw_market = str(row["market"] or "").strip()
            try:
                market = Market.parse(raw_market)
            except ValueError:
                details.append(
                    f"第 {int(index) + 2} 筆 {str(row['symbol']).strip()}（市場代碼 {raw_market or '空白'}）"
                )
                continue
            if market not in {Market.TWSE, Market.TPEX, Market.US}:
                details.append(
                    f"第 {int(index) + 2} 筆 {str(row['symbol']).strip()}（市場代碼 {raw_market or '空白'}）"
                )
    if details:
        return tuple(details)
    return tuple(
        f"第 {int(row.Index) + 2} 筆 {row.symbol}（市場代碼 {row.market}）"
        for row in normalized.itertuples(index=True)
    )


def _manual_watchlist(path: Path) -> tuple[pd.DataFrame | None, str | None]:
    """Read the optional manual file while preserving first-use as a normal state."""

    if not path.exists():
        return load_watchlist(path), None
    try:
        source = pd.read_csv(path, dtype={"symbol": str, "market": str, "note": str})
        if "symbol" not in source.columns:
            return None, "自選股摘要資料不足：自選股檔缺少股票代號欄位。"
        return load_watchlist(path), None
    except (OSError, UnicodeDecodeError, pd.errors.ParserError):
        return None, "自選股摘要資料不足：無法安全讀取自選股檔。"
