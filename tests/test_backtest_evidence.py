from dataclasses import replace

import pandas as pd
import pytest

from stock_tool.backtest import BacktestEngine, BrokerConfig
from stock_tool.backtest.trade_evidence import completed_round_trips, round_trip_statistics


def run_cycle(*, config=None, missing=False):
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=5).strftime("%Y-%m-%d"),
            "symbol": ["TEST"] * 5,
            "open": [100, 100, 110, 105, 1000],
            "high": [101, 120, 115, 900, 2000],
            "low": [99, 80, 90, 1, 1],
            "close": [100, 100, 110, 105, 1000],
        }
    )
    if missing:
        prices = prices.drop(columns=["high", "low"])
    signals = pd.DataFrame(
        [
            dict(date="2024-01-01", symbol="TEST", action="buy", quantity=10),
            dict(date="2024-01-03", symbol="TEST", action="sell", quantity=10),
        ]
    )
    return BacktestEngine(initial_cash=100000, broker_config=config).run(prices, signals), prices


def test_counts_and_exact_holding_interval():
    result, _ = run_cycle()
    m = result.metrics
    assert m.fill_count == m.number_of_trades == 2
    assert m.closed_round_trip_count == 1
    t = m.round_trips[0]
    assert t.realized_pnl == 50
    assert t.trade_return == pytest.approx(0.05)
    assert t.mfe == pytest.approx(0.2)
    assert t.mae == pytest.approx(-0.2)
    assert t.holding_days == 2
    assert m.median_mfe == m.average_mfe == t.mfe
    assert m.median_mae == m.average_mae == t.mae


def test_costs_reconcile_without_double_counting_slippage():
    result, _ = run_cycle(
        config=BrokerConfig(commission_rate=0.01, tax_rate=0.02, slippage_rate=0.01)
    )
    buy, sell = result.trades
    trip = result.metrics.round_trips[0]
    expected = 105 * 0.99 * 10 * 0.97 - 100 * 1.01 * 10 * 1.01
    assert trip.realized_pnl == pytest.approx(expected)
    assert trip.realized_pnl == pytest.approx(sell.realized_pnl)
    assert trip.realized_pnl == pytest.approx(buy.net_cash_flow + sell.net_cash_flow)
    assert trip.trade_return == pytest.approx(expected / -buy.net_cash_flow)
    assert result.metrics.expectancy == pytest.approx(expected)
    assert trip.mfe == pytest.approx(120 / buy.execution_price - 1)


def test_multiple_cycles_outlier_and_open_position():
    result, _ = run_cycle()
    buy, sell = result.trades
    fills = []
    for i, pnl in enumerate([100, -50, 0, 10000]):
        day = pd.Timestamp("2024-02-01") + pd.Timedelta(days=i * 3)
        fills += [
            replace(buy, execution_date=str(day.date())),
            replace(
                sell,
                execution_date=str((day + pd.Timedelta(days=1)).date()),
                net_cash_flow=1000 + pnl,
                realized_pnl=pnl,
            ),
        ]
    fills.append(replace(buy, execution_date="2024-03-01"))
    trips, reason = completed_round_trips(fills)
    assert reason is None
    assert len(trips) == 4
    stats = round_trip_statistics(trips)
    assert stats["average_win"] == 5050
    assert stats["average_loss"] == -50
    assert stats["payoff_ratio"] == 101
    assert stats["expectancy"] == 2512.5
    assert stats["median_trade_return"] == pytest.approx(0.05)
    assert stats["win_rate"] == 0.5
    assert stats["profit_factor"] == 202


def test_partial_sells_reconcile_as_one_cycle():
    result, _ = run_cycle()
    buy, sell = result.trades
    partial = replace(sell, quantity=5, net_cash_flow=525, realized_pnl=25)
    trips, reason = completed_round_trips([buy, partial, partial])
    assert reason is None
    assert len(trips) == 1
    assert trips[0].realized_pnl == 50
    assert trips[0].exit_price is None
    assert trips[0].mfe is None
    assert "分批" in trips[0].excursion_unavailable_reason
    assert completed_round_trips([buy, partial])[0] == ()


def test_missing_high_low_is_unavailable_not_close_proxy():
    result, _ = run_cycle(missing=True)
    assert result.metrics.closed_round_trip_count == 1
    assert result.metrics.median_mfe is None
    assert result.metrics.median_mae is None
    assert "OHLC" in result.metrics.round_trips[0].excursion_unavailable_reason


@pytest.mark.parametrize("mode", ["close", "adjusted_close", None])
def test_unknown_execution_phase_has_no_excursion(mode):
    result, prices = run_cycle()
    trips, _ = completed_round_trips(result.trades, prices=prices, execution_price_col=mode)
    assert trips[0].mfe is None


def test_corporate_actions_and_accounting_mismatch_are_unavailable():
    result, _ = run_cycle()
    assert completed_round_trips(result.trades, has_corporate_actions=True)[1]
    buy, sell = result.trades
    assert completed_round_trips([buy, replace(sell, realized_pnl=999)])[1]
    assert completed_round_trips([sell])[1]


def test_invalid_ohlc_fails_closed():
    result, prices = run_cycle()
    prices.loc[1, "high"] = 1
    trips, _ = completed_round_trips(result.trades, prices=prices, execution_price_col="open")
    assert trips[0].mfe is None
    assert trips[0].mae is None


def test_ui_sections_and_explicit_fill_label():
    from streamlit.testing.v1 import AppTest

    result, _ = run_cycle()
    app = AppTest.from_string("""
import streamlit as st
from stock_tool.dashboard.components.backtest_evidence import render_backtest_evidence
render_backtest_evidence(st, st.session_state["metrics"])
""")
    app.session_state["metrics"] = result.metrics
    app.run(timeout=30)
    assert not app.exception
    assert [x.value for x in app.markdown if x.value.startswith("### ")] == [
        "### 整體績效",
        "### 交易品質",
        "### 持倉體感",
    ]
    assert any("成交筆數（fills）：2" in x.value for x in app.caption)
    assert not any("交易次數" in x.label for x in app.metric)
    assert next(x.value for x in app.metric if x.label == "完整交易（已平倉）") == "1"
    assert app.dataframe[0].value.iloc[0]["MFE／MAE 缺口"] == "可計算"
