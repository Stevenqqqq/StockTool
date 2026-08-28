from __future__ import annotations

from pathlib import Path

import pandas as pd

from stock_tool.dashboard.home_data import load_home_summary


def _write_portfolio(path: Path, rows: int) -> None:
    pd.DataFrame(
        {
            "symbol": [f"T{index}" for index in range(rows)],
            "quantity": [1.0] * rows,
            "average_cost": [10.0] * rows,
            "market": ["TWSE"] * rows,
            "currency": ["TWD"] * rows,
            "note": [""] * rows,
        }
    ).to_csv(path, index=False, encoding="utf-8")


def _write_watchlist(path: Path, rows: int) -> None:
    pd.DataFrame(
        {
            "symbol": [f"W{index}" for index in range(rows)],
            "market": ["US"] * rows,
            "note": [""] * rows,
        }
    ).to_csv(path, index=False, encoding="utf-8")


def test_home_summary_reads_existing_counts_without_mutating_source(tmp_path: Path) -> None:
    portfolio = tmp_path / "portfolio.csv"
    watchlist = tmp_path / "watchlist.csv"
    _write_portfolio(portfolio, 4)
    _write_watchlist(watchlist, 3)
    before_portfolio = portfolio.read_bytes()
    before_watchlist = watchlist.read_bytes()

    summary = load_home_summary({}, portfolio_path=portfolio, watchlist_path=watchlist)

    assert summary.portfolio_count == 4
    assert summary.watchlist_count == 7
    assert summary.warnings == ()
    assert portfolio.read_bytes() == before_portfolio
    assert watchlist.read_bytes() == before_watchlist


def test_home_summary_distinguishes_empty_file_from_missing_or_unreadable_data(
    tmp_path: Path,
) -> None:
    empty_portfolio = tmp_path / "portfolio.csv"
    empty_watchlist = tmp_path / "watchlist.csv"
    _write_portfolio(empty_portfolio, 0)
    _write_watchlist(empty_watchlist, 0)

    empty = load_home_summary({}, portfolio_path=empty_portfolio, watchlist_path=empty_watchlist)
    missing = load_home_summary(
        {},
        portfolio_path=tmp_path / "missing_portfolio.csv",
        watchlist_path=tmp_path / "missing_watchlist.csv",
    )
    empty_portfolio.write_bytes(b"\xff\xfe")
    unreadable = load_home_summary(
        {}, portfolio_path=empty_portfolio, watchlist_path=empty_watchlist
    )

    assert (empty.portfolio_count, empty.watchlist_count) == (0, 0)
    assert (missing.portfolio_count, missing.watchlist_count) == (0, 0)
    assert missing.warnings == ()
    assert unreadable.portfolio_count is None
    assert unreadable.watchlist_count == 0
    assert unreadable.warnings


def test_home_summary_reuses_cached_value_until_a_source_file_changes(tmp_path: Path) -> None:
    portfolio = tmp_path / "portfolio.csv"
    watchlist = tmp_path / "watchlist.csv"
    _write_portfolio(portfolio, 1)
    _write_watchlist(watchlist, 1)
    session: dict[str, object] = {}

    first = load_home_summary(session, portfolio_path=portfolio, watchlist_path=watchlist)
    second = load_home_summary(session, portfolio_path=portfolio, watchlist_path=watchlist)

    assert second is first


def test_home_summary_missing_manual_watchlist_uses_portfolio_tracking_without_warning(
    tmp_path: Path,
) -> None:
    portfolio = tmp_path / "portfolio.csv"
    _write_portfolio(portfolio, 4)

    summary = load_home_summary(
        {},
        portfolio_path=portfolio,
        watchlist_path=tmp_path / "watchlist.csv",
    )

    assert summary.portfolio_count == 4
    assert summary.watchlist_count == 4
    assert not any("自選股" in warning for warning in summary.warnings)
