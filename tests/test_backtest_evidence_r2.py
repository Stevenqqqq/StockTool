from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from stock_tool.backtest import PerformanceMetrics
from stock_tool.reports.models import metrics_to_frame


@pytest.mark.parametrize(
    "count,reason,expected",
    [
        (None, "公司行動現金流無法核對", "資料不足：公司行動現金流無法核對"),
        (1, "損益不一致", "資料不足：損益不一致"),
        (0, None, "資料不足：尚無已平倉的完整交易"),
        (None, None, "資料不足：完整交易樣本數未確認"),
        (1, None, "0.00%"),
    ],
)
def test_report_and_legacy_ui_respect_trade_sample_status(count, reason, expected):
    metrics = PerformanceMetrics.calculate(pd.DataFrame(), [], initial_cash=1000)
    metrics = replace(
        metrics,
        closed_round_trip_count=count,
        trade_evidence_unavailable_reason=reason,
        win_rate=0.0,
    )
    report = metrics_to_frame(metrics).set_index("指標")
    assert report.loc["勝率", "數值"] == expected
    app = AppTest.from_string("""
import streamlit as st
from stock_tool.dashboard.app import _display_metrics
_display_metrics(st, st.session_state["result"])
""")
    app.session_state["result"] = SimpleNamespace(metrics=metrics)
    app.run(timeout=30)
    assert not app.exception
    frame = app.dataframe[0].value.set_index("指標")
    assert frame.loc["勝率", "數值"] == expected
    assert metrics.win_rate == 0.0


def test_actual_closed_losing_trade_keeps_zero_win_rate():
    from stock_tool.backtest import BacktestEngine

    prices = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "symbol": ["TEST"] * 3,
            "open": [100, 100, 90],
            "close": [100, 100, 90],
        }
    )
    signals = pd.DataFrame(
        [
            dict(date="2024-01-01", symbol="TEST", action="buy", quantity=1),
            dict(date="2024-01-02", symbol="TEST", action="sell", quantity=1),
        ]
    )
    result = BacktestEngine(initial_cash=10000).run(prices, signals)
    assert result.metrics.closed_round_trip_count == 1
    assert result.metrics.round_trips[0].realized_pnl == -10
    assert metrics_to_frame(result.metrics).set_index("指標").loc["勝率", "數值"] == "0.00%"
    app = AppTest.from_string("""
import streamlit as st
from stock_tool.dashboard.app import _display_metrics
_display_metrics(st, st.session_state["result"])
""")
    app.session_state["result"] = result
    app.run(timeout=30)
    assert not app.exception
    assert app.dataframe[0].value.set_index("指標").loc["勝率", "數值"] == "0.00%"
