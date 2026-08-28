"""Application service for the productized Explore workspace.

The service deliberately consumes the existing local concept index and the
existing watchlist helpers.  It does not fetch a new provider or write to a
path owned by the UI, which keeps Explore usable when providers are offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd

from stock_tool.concepts import (
    CONCEPT_COLUMNS,
    MARKET_LABELS,
    load_concept_stocks,
    search_concept_stocks,
)
from stock_tool.domain.models import Market, Symbol
from stock_tool.watchlist import (
    add_watchlist_symbol,
    load_watchlist,
    remove_watchlist_symbol,
    save_watchlist,
)


@dataclass(frozen=True, slots=True)
class ExploreResult:
    """One deterministic, explainable Explore query result."""

    query: str
    markets: tuple[str, ...]
    matches: pd.DataFrame
    status: str
    source: str
    updated_at: str | None
    source_state: str = "local_index"
    warnings: tuple[str, ...] = ()


class ExploreApplicationService:
    """Coordinate local Explore search and existing watchlist persistence."""

    def __init__(
        self,
        *,
        concept_path: str | Path,
        watchlist_path: str | Path,
    ) -> None:
        self.concept_path = Path(concept_path)
        self.watchlist_path = Path(watchlist_path)

    def search(
        self,
        query: str,
        *,
        markets: Sequence[str] = ("TWSE", "TPEX", "US"),
        limit: int = 100,
    ) -> ExploreResult:
        """Search only the existing local index and attach honest data metadata."""

        query_text = str(query or "").strip()
        market_values = _canonical_markets(markets)
        if not query_text:
            return ExploreResult(
                query="",
                markets=market_values,
                matches=_empty_matches(),
                status="initial",
                source="尚未搜尋",
                updated_at=None,
            )

        if not self.concept_path.is_file():
            return ExploreResult(
                query=query_text,
                markets=market_values,
                matches=_empty_matches(),
                status="missing",
                source="資料不足",
                updated_at=None,
                source_state="missing",
                warnings=("目前找不到本機探索索引；請確認資料匯入或稍後再試。",),
            )

        try:
            source_frame = load_concept_stocks(self.concept_path)
            matches = search_concept_stocks(
                query_text,
                source_frame,
                markets=market_values,
                limit=limit,
            )
        except (OSError, ValueError, pd.errors.ParserError):
            return ExploreResult(
                query=query_text,
                markets=market_values,
                matches=_empty_matches(),
                status="partial",
                source="本機索引讀取失敗",
                updated_at=None,
                source_state="local_index",
                warnings=("本機探索索引目前無法讀取；既有資料未被修改。",),
            )

        updated_at = _file_updated_at(self.concept_path)
        if matches.empty:
            return ExploreResult(
                query=query_text,
                markets=market_values,
                matches=_empty_matches(),
                status="no_results",
                source="本機探索索引",
                updated_at=updated_at,
                source_state="local_index",
                warnings=("沒有符合目前索引的結果；可換用股票代號、公司名稱或題材。",),
            )

        output = _prepare_matches(matches, index_updated_at=updated_at)
        status = "partial" if _has_missing_fields(output) else _result_freshness(output)
        warning = (
            ("部分結果缺少公司或來源欄位，未補造內容。",)
            if status == "partial"
            else (
                ("目前索引為本機資料，可能不是最新；請留意更新時間。",) if status == "stale" else ()
            )
        )
        return ExploreResult(
            query=query_text,
            markets=market_values,
            matches=output,
            status=status,
            source="本機探索索引",
            updated_at=updated_at,
            source_state="local_index",
            warnings=warning,
        )

    def canonical_symbol(self, symbol: str, market: str) -> Symbol:
        """Normalize an Explore result through the shared domain identity."""

        return Symbol.parse(symbol, market=Market.parse(market))

    def add_to_watchlist(self, symbol: str, market: str, *, note: str = "") -> Path:
        """Idempotently persist one canonical Explore identity via existing helpers."""

        identity = self.canonical_symbol(symbol, market)
        current = load_watchlist(self.watchlist_path)
        updated = add_watchlist_symbol(
            current,
            symbol=identity.code,
            market=identity.market.value,
            note=str(note or "").strip(),
        )
        return save_watchlist(updated, self.watchlist_path)

    def remove_from_watchlist(self, symbol: str, market: str) -> Path:
        """Idempotently remove one canonical Explore identity via existing helpers."""

        identity = self.canonical_symbol(symbol, market)
        current = load_watchlist(self.watchlist_path)
        updated = remove_watchlist_symbol(
            current,
            symbol=identity.code,
            market=identity.market.value,
        )
        return save_watchlist(updated, self.watchlist_path)

    def current_watchlist(self) -> pd.DataFrame:
        """Read the persisted watchlist through the existing helper."""

        return load_watchlist(self.watchlist_path)

    def is_in_watchlist(self, symbol: str, market: str) -> bool:
        """Return whether a canonical identity is currently persisted."""

        identity = self.canonical_symbol(symbol, market)
        current = self.current_watchlist()
        return bool(
            (
                (current["symbol"] == identity.code) & (current["market"] == identity.market.value)
            ).any()
        )


def _canonical_markets(markets: Sequence[str]) -> tuple[str, ...]:
    values: set[str] = set()
    for value in markets:
        try:
            market = Market.parse(value)
        except ValueError:
            continue
        if market in {Market.TWSE, Market.TPEX, Market.US}:
            values.add(market.value)
    return tuple(sorted(values))


def _empty_matches() -> pd.DataFrame:
    return pd.DataFrame(columns=[*CONCEPT_COLUMNS, "market_label", "match_score", "match_reason"])


def _prepare_matches(matches: pd.DataFrame, *, index_updated_at: str | None) -> pd.DataFrame:
    output = matches.copy(deep=True)
    for column in CONCEPT_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    output["market_label"] = output["market"].map(MARKET_LABELS).fillna(output["market"])
    output["source"] = output["source"].replace("", "資料不足").fillna("資料不足")
    output["match_reason"] = (
        output["match_reason"].replace("", "符合目前索引條件").fillna("符合目前索引條件")
    )
    output["display_status"] = output.apply(
        _row_status,
        axis=1,
        index_updated_at=index_updated_at,
    )
    output = output.sort_values(
        ["match_score", "market", "symbol", "name"],
        ascending=[False, True, True, True],
        kind="stable",
    )
    return output.reset_index(drop=True)


def _row_status(row: pd.Series, *, index_updated_at: str | None) -> str:
    required = ("symbol", "name", "market", "match_reason", "source")
    if any(not str(row.get(column, "")).strip() for column in required):
        return "partial"
    if str(row.get("source", "")).strip() == "manual_seed":
        return "stale"
    return "fresh" if _index_is_recent(index_updated_at) else "stale"


def _has_missing_fields(frame: pd.DataFrame) -> bool:
    return bool(frame.get("display_status", pd.Series(dtype=str)).eq("partial").any())


def _result_freshness(frame: pd.DataFrame) -> str:
    statuses = set(frame.get("display_status", pd.Series(dtype=str)).astype(str))
    return "fresh" if statuses and statuses <= {"fresh"} else "stale"


def _file_updated_at(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _index_is_recent(value: str | None) -> bool:
    """Use the index file timestamp as evidence; source labels alone are insufficient."""

    if not value:
        return False
    try:
        updated = datetime.fromisoformat(value)
    except ValueError:
        return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - updated).total_seconds()
    return 0 <= age_seconds <= 7 * 24 * 60 * 60
