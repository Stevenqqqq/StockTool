"""Deterministic market-qualified watchlist comparison regressions."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from stock_tool.application.watchlist_comparison import compare_symbol, comparison_notices
from stock_tool.domain.models import Symbol

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def prices(symbol="3006", market="TWSE", count=65):
    return pd.DataFrame(
        {
            "symbol": symbol,
            "market": market,
            "date": pd.bdate_range(end="2026-10-13", periods=count),
            "close": [100.0 + i for i in range(count)],
            "volume": 1000.0,
            "provider": "synthetic",
            "fetched_at": "2026-10-13T12:00:00Z",
        }
    )


def compare(frame, symbol="3006", market="TWSE", now=NOW):
    return compare_symbol(frame, Symbol.parse(symbol, market=market), now=now)


def test_known_metrics_and_raw_unchanged():
    frame = prices()
    frame.loc[64, "volume"] = 3000
    original = frame.copy(deep=True)
    row = compare(frame)
    assert row.close == 164
    assert row.return_5 == pytest.approx(164 / 159 - 1)
    assert row.return_20 == pytest.approx(164 / 144 - 1)
    assert row.sma_20_position == pytest.approx(164 / 154.5 - 1)
    assert row.sma_60_position == pytest.approx(164 / 134.5 - 1)
    assert row.volume_ratio == 3
    assert row.date == "2026-10-13"
    assert not row.notices
    pd.testing.assert_frame_equal(frame, original)


def test_partial_metrics_do_not_erase_other_results():
    row = compare(prices(count=10))
    assert row.close == 109 and row.return_5 is not None
    assert row.return_20 is None and row.sma_20_position is None
    assert row.volume_ratio is None


@pytest.mark.parametrize("value", [None, -1, float("inf"), "bad"])
def test_bad_volume_retains_prices_and_does_not_skip_rows(value):
    frame = prices()
    frame["volume"] = frame.volume.astype(object)
    frame.loc[60, "volume"] = value
    row = compare(frame)
    assert row.volume_ratio is None and row.return_20 is not None


def test_zero_volume_and_zero_baseline():
    frame = prices()
    frame.loc[64, "volume"] = 0
    assert compare(frame).volume_ratio == 0
    frame["volume"] = 0
    assert compare(frame).volume_ratio is None


def test_bad_close_window_not_filled():
    frame = prices()
    frame.loc[60, "close"] = float("nan")
    row = compare(frame)
    assert row.close == 164 and row.return_5 is None
    assert row.sma_60_position is None and row.volume_ratio == 1


@pytest.mark.parametrize("column", ["fetched_at", "provider", "market", "close"])
def test_missing_metadata_or_price(column):
    row = compare(prices().drop(columns=column))
    assert row.close is None
    assert row.notices


def test_identity_and_missing_security_are_independent():
    frame = pd.concat([prices(), prices("3006", "TPEX").assign(close=999), prices("6669")])
    assert compare(frame).close == 164
    assert compare(frame, market="TPEX").close == 999
    assert compare(frame, "6933").close is None
    assert compare(frame, "6669").close == 164
    assert compare(frame, market="AUTO").close is None


def test_date_mismatch_is_explicit():
    first = compare(prices())
    other = compare(prices("6933").iloc[:-1], "6933")
    assert "基準不一致" in comparison_notices((first, other))[0]
    us = compare(prices("MU", "US"), "MU", "US")
    assert any("跨市場" in n for n in comparison_notices((first, us)))


def test_duplicate_dates_rejected_not_silently_selected():
    frame = prices()
    assert compare(pd.concat([frame, frame.tail(1)])).close is None


def test_intraday_tail_never_promoted_on_later_cache_read():
    frame = prices()
    frame.loc[64, "date"] = pd.Timestamp("2026-10-14")
    frame.loc[64, "fetched_at"] = "2026-10-14T02:00:00Z"
    result = compare(frame)
    assert result.close == 163
    assert compare(frame, now=datetime(2026, 11, 1, tzinfo=UTC)) == result
    assert result.notices


@pytest.mark.parametrize(
    "market,date,acquired",
    [
        ("TWSE", "2026-10-12T16:00Z", "2026-10-13T12:00Z"),
        ("US", "2026-10-14T00:00Z", "2026-10-14T01:00Z"),
    ],
)
def test_exchange_local_date(market, date, acquired):
    frame = prices(market=market, count=1).assign(date=date, fetched_at=acquired)
    assert compare(frame, market=market).date == "2026-10-13"


def test_selection_refresh_failure_and_research_route(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    script = """
import streamlit as st
import pandas as pd
from stock_tool.dashboard.components.watchlist_comparison import render_watchlist_comparison
from stock_tool.dashboard.shell import _route_explore_research
from stock_tool.dashboard.state import initialize_dashboard_state
initialize_dashboard_state(st.session_state)
watchlist = pd.DataFrame([dict(symbol=s,market="TWSE") for s in ("6669","6933","3006")])
def failure(symbol):
    raise RuntimeError("simulated offline")
render_watchlist_comparison(st, watchlist, load_prices=lambda: None,
    refresh=failure, on_research=lambda s: _route_explore_research(st,s))
"""
    at = AppTest.from_string(script).run()
    assert not at.exception
    assert 'aria-label="自選股價量比較"' in at.markdown[0].value
    assert at.markdown[0].value.count('<th scope="row">') == 3
    at.button(key="watchlist_comparison_refresh").click().run()
    assert not at.exception
    assert any("更新失敗" in c.value for c in at.caption)
    at.multiselect(key="watchlist_comparison_selection").set_value(["TWSE:3006", "TWSE:6669"]).run()
    at.selectbox(key="watchlist_comparison_research").select("TWSE:3006").run()
    assert at.markdown[0].value.count('<th scope="row">') == 2
    at.run()
    assert at.multiselect(key="watchlist_comparison_selection").value == ["TWSE:3006", "TWSE:6669"]
    at.button(key="watchlist_comparison_open").click().run()
    assert at.session_state["dashboard_pending_search"].symbol == "3006"
    at.selectbox(key="watchlist_comparison_research").select("TWSE:6669").run()
    at.button(key="watchlist_comparison_open").click().run()
    assert at.session_state["dashboard_pending_search"].symbol == "6669"
    at.multiselect(key="watchlist_comparison_selection").set_value(["TWSE:3006"]).run()
    assert not at.exception and not at.markdown


def test_display_sort_numeric_missing_last_and_mismatched_dates():
    from dataclasses import replace

    from stock_tool.dashboard.components.watchlist_comparison import sorted_comparison

    first = replace(compare(prices()), return_20=-0.02)
    second = replace(compare(prices("6669"), "6669"), return_20=0.15)
    missing = compare(prices(), "6933")
    rows = (first, missing, second)
    assert sorted_comparison(rows, "20日表現") == (second, first, missing)
    assert sorted_comparison(rows, "20日表現", True) == (first, second, missing)
    assert sorted_comparison(rows, "選取順序") == rows
    different = (first, replace(second, date="2026-10-12"))
    assert sorted_comparison(different, "20日表現") == different
    assert sorted_comparison((missing,), "20日表現") == (missing,)
    for metric in ("5日表現", "相對SMA20", "相對SMA60", "量比"):
        assert sorted_comparison(rows, metric)[-1] == missing


def test_readable_table_escapes_names_and_distinguishes_signs_and_missing():
    from dataclasses import replace

    from stock_tool.dashboard.components.watchlist_comparison import comparison_html

    row = replace(
        compare(prices()), return_5=-0.05, return_20=0.1, sma_20_position=0.0, volume_ratio=None
    )
    html = comparison_html((row,), lambda key: "晶豪科 <script>bad()</script>")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert 'wc-down">-5.00%' in html and 'wc-up">+10.00%' in html
    assert 'wc-flat">+0.00%' in html and "資料不足" in html
    assert "晶豪科" in html and "TWSE · TWD" in html
    assert "名稱未確認" in comparison_html((row,), lambda key: "3006")


def test_comparison_uses_shared_names_and_market_identity(tmp_path):
    from stock_tool.application.instrument_names import InstrumentName, NameDirectory
    from stock_tool.dashboard.instrument_names import current_names
    from stock_tool.dashboard.presentation_mapper import format_taiwan_company_display

    directory = NameDirectory(tmp_path / "names.json")
    directory.records["TWSE:companies"] = {
        "3006": InstrumentName(
            "TWSE", "3006", "晶豪科", "晶豪科", "fixture", "2026-10-13", "2026-10-13T12:00:00+00:00"
        )
    }
    token = current_names.set(directory)
    try:
        assert format_taiwan_company_display("3006", market="TWSE") == "晶豪科 (3006)"
        assert format_taiwan_company_display("3006", market="TPEX") == "3006"
    finally:
        current_names.reset(token)
