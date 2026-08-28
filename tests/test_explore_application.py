from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
import os

import pandas as pd

from stock_tool.application.explore import ExploreApplicationService


def _write_index(path: Path) -> None:
    pd.DataFrame(
        [
            {
                "symbol": "2330",
                "name": "台積電",
                "market": "TWSE",
                "exchange": "TWSE",
                "industry": "半導體",
                "concept": "先進製程",
                "keywords": "晶圓代工;AI",
                "source": "manual_seed",
                "note": "本機索引",
            },
            {
                "symbol": "6488",
                "name": "環球晶",
                "market": "TPEX",
                "exchange": "TPEx",
                "industry": "半導體",
                "concept": "矽晶圓",
                "keywords": "晶圓材料",
                "source": "manual_seed",
                "note": "本機索引",
            },
            {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "market": "US",
                "exchange": "NASDAQ",
                "industry": "Technology",
                "concept": "消費電子",
                "keywords": "手機;電腦",
                "source": "manual_seed",
                "note": "本機索引",
            },
        ]
    ).to_csv(path, index=False, encoding="utf-8")


def test_explore_search_filters_markets_and_is_deterministic(tmp_path: Path) -> None:
    index = tmp_path / "concept_stocks.csv"
    _write_index(index)
    service = ExploreApplicationService(
        concept_path=index,
        watchlist_path=tmp_path / "watchlist.csv",
    )

    first = service.search("半導體", markets=("TW", "TPEX"))
    second = service.search("半導體", markets=("TPEX", "TWSE"))

    assert first.status == "stale"
    assert list(first.matches["symbol"]) == ["6488", "2330"]
    assert list(first.matches["symbol"]) == list(second.matches["symbol"])
    assert set(first.matches["market"]) == {"TWSE", "TPEX"}
    assert first.matches["match_reason"].notna().all()
    assert first.matches["source"].eq("manual_seed").all()
    assert first.updated_at


def test_explore_empty_missing_and_no_results_are_honest(tmp_path: Path) -> None:
    missing = ExploreApplicationService(
        concept_path=tmp_path / "missing.csv",
        watchlist_path=tmp_path / "watchlist.csv",
    )
    assert missing.search("").status == "initial"
    assert missing.search("2330").status == "missing"

    index = tmp_path / "concept_stocks.csv"
    _write_index(index)
    service = ExploreApplicationService(
        concept_path=index,
        watchlist_path=tmp_path / "watchlist.csv",
    )
    result = service.search("不存在的查詢")
    assert result.status == "no_results"
    assert result.matches.empty
    assert all("不存在" not in str(value) for value in result.matches.to_dict().values())


def test_explore_partial_rows_are_labeled_without_fabricating_fields(tmp_path: Path) -> None:
    index = tmp_path / "concept_stocks.csv"
    pd.DataFrame([{"symbol": "2330", "market": "TWSE", "concept": "半導體"}]).to_csv(
        index, index=False, encoding="utf-8"
    )
    service = ExploreApplicationService(
        concept_path=index,
        watchlist_path=tmp_path / "watchlist.csv",
    )

    result = service.search("2330", markets=("TWSE",))

    assert result.status == "partial"
    assert result.matches.loc[0, "name"] == ""
    assert result.matches.loc[0, "source"] == "資料不足"
    assert result.matches.loc[0, "display_status"] == "partial"


def test_explore_marks_complete_non_seed_source_as_fresh(tmp_path: Path) -> None:
    index = tmp_path / "concept_stocks.csv"
    _write_index(index)
    frame = pd.read_csv(index, dtype=str)
    frame["source"] = "official_index"
    frame.to_csv(index, index=False, encoding="utf-8")
    service = ExploreApplicationService(
        concept_path=index,
        watchlist_path=tmp_path / "watchlist.csv",
    )

    result = service.search("2330", markets=("TWSE",))

    assert result.status == "fresh"
    assert result.matches.loc[0, "display_status"] == "fresh"
    assert result.warnings == ()


def test_explore_watchlist_write_is_idempotent_and_uses_canonical_market(tmp_path: Path) -> None:
    index = tmp_path / "concept_stocks.csv"
    _write_index(index)
    watchlist = tmp_path / "watchlist.csv"
    service = ExploreApplicationService(concept_path=index, watchlist_path=watchlist)

    service.add_to_watchlist("2330.TW", "TWSE", note="探索")
    service.add_to_watchlist("2330", "TW", note="再次探索")

    saved = pd.read_csv(watchlist, dtype=str)
    assert len(saved) == 1
    assert saved.loc[0, "symbol"] == "2330"
    assert saved.loc[0, "market"] == "TWSE"
    assert saved.loc[0, "note"] == "再次探索"


def test_explore_watchlist_add_remove_is_idempotent_for_all_markets(tmp_path: Path) -> None:
    index = tmp_path / "concept_stocks.csv"
    _write_index(index)
    watchlist = tmp_path / "watchlist.csv"
    service = ExploreApplicationService(concept_path=index, watchlist_path=watchlist)

    for symbol, market in (("2330.TW", "TWSE"), ("6488", "TPEX"), ("AAPL", "US")):
        service.add_to_watchlist(symbol, market)
        service.add_to_watchlist(symbol, market)
        assert service.is_in_watchlist(symbol, market)

    saved = pd.read_csv(watchlist, dtype=str)
    assert set(zip(saved["symbol"], saved["market"])) == {
        ("2330", "TWSE"),
        ("6488", "TPEX"),
        ("AAPL", "US"),
    }

    for symbol, market in (("2330", "TWSE"), ("6488", "TPEX"), ("AAPL", "US")):
        service.remove_from_watchlist(symbol, market)
        service.remove_from_watchlist(symbol, market)
        assert not service.is_in_watchlist(symbol, market)
    assert service.current_watchlist().empty


def test_explore_source_state_is_local_index_and_freshness_uses_mtime(tmp_path: Path) -> None:
    index = tmp_path / "concept_stocks.csv"
    _write_index(index)
    frame = pd.read_csv(index, dtype=str)
    frame["source"] = "official_index"
    frame.to_csv(index, index=False, encoding="utf-8")
    service = ExploreApplicationService(
        concept_path=index, watchlist_path=tmp_path / "watchlist.csv"
    )

    fresh = service.search("2330", markets=("TWSE",))
    assert fresh.source_state == "local_index"
    assert fresh.matches.loc[0, "display_status"] == "fresh"

    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=8)).timestamp()
    os.utime(index, (old_timestamp, old_timestamp))
    stale = service.search("2330", markets=("TWSE",))
    assert stale.source_state == "local_index"
    assert stale.matches.loc[0, "display_status"] == "stale"


def test_explore_missing_and_partial_source_states_are_explicit(tmp_path: Path) -> None:
    missing = ExploreApplicationService(
        concept_path=tmp_path / "missing.csv", watchlist_path=tmp_path / "watchlist.csv"
    )
    missing_result = missing.search("2330")
    assert missing_result.source_state == "missing"

    index = tmp_path / "partial.csv"
    pd.DataFrame([{"symbol": "2330", "market": "TWSE"}]).to_csv(index, index=False)
    partial = ExploreApplicationService(
        concept_path=index, watchlist_path=tmp_path / "watchlist.csv"
    )
    partial_result = partial.search("2330", markets=("TWSE",))
    assert partial_result.source_state == "local_index"
    assert partial_result.status == "partial"
