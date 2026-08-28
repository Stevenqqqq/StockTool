from __future__ import annotations

import pandas as pd
import pandas.testing as pdt
import pytest

from stock_tool.backtest import (
    BacktestEngine,
    BrokerConfig,
    PerformanceMetrics,
    TRAILING_STOP_DAILY_MODEL_NOTICE,
)
from stock_tool.risk import RiskConfig, RiskManager


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [
                "2024-01-01",
                "2024-01-02",
                "2024-01-03",
                "2024-01-04",
            ],
            "symbol": ["2330", "2330", "2330", "2330"],
            "open": [100.0, 101.0, 105.0, 95.0],
            "high": [102.0, 103.0, 106.0, 96.0],
            "low": [99.0, 100.0, 104.0, 90.0],
            "close": [100.0, 102.0, 104.0, 91.0],
            "volume": [1000, 1100, 1200, 1300],
        }
    )


class RecordingRiskManager(RiskManager):
    def __init__(self, config: RiskConfig) -> None:
        super().__init__(config)
        self.buy_calls: list[dict[str, object]] = []

    def evaluate_buy_order(self, **kwargs: object) -> object:
        self.buy_calls.append(dict(kwargs))
        return super().evaluate_buy_order(**kwargs)


def _permissive_test_risk_config(
    *,
    max_position_pct: float = 0.99,
    max_positions: int = 10,
    min_cash_ratio: float = 0.0,
) -> RiskConfig:
    return RiskConfig(
        max_position_pct=max_position_pct,
        max_trade_loss_pct=0.99,
        max_positions=max_positions,
        min_cash_ratio=min_cash_ratio,
        max_drawdown_pct=0.99,
        max_volatility=1_000_000.0,
        max_consecutive_losses=1_000_000,
        max_industry_pct=0.99,
        default_stop_loss_pct=0.01,
    )


def test_buy_reduces_cash_and_holding_quantity_is_correct() -> None:
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    engine = BacktestEngine(initial_cash=10_000)

    result = engine.run(_prices(), signals)

    assert len(result.trades) == 1
    assert result.trades[0].side == "buy"
    assert result.trades[0].execution_date == "2024-01-02"
    assert result.portfolio.cash == pytest.approx(10_000 - 101.0 * 10)
    assert result.portfolio.positions["2330"].quantity == 10


def test_sell_increases_cash_and_closes_position() -> None:
    signals = pd.DataFrame(
        [
            {"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10},
            {"date": "2024-01-02", "symbol": "2330", "action": "sell", "quantity": 10},
        ]
    )
    engine = BacktestEngine(initial_cash=10_000)

    result = engine.run(_prices(), signals)

    assert [trade.side for trade in result.trades] == ["buy", "sell"]
    assert result.trades[1].execution_date == "2024-01-03"
    assert result.portfolio.cash == pytest.approx(10_000 - 101.0 * 10 + 105.0 * 10)
    assert "2330" not in result.portfolio.positions


def test_transaction_costs_and_slippage_are_deducted_from_cash() -> None:
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    engine = BacktestEngine(
        initial_cash=10_000,
        broker_config=BrokerConfig(
            commission_rate=0.01,
            tax_rate=0.02,
            slippage_rate=0.01,
            execution_price_col="open",
        ),
    )

    result = engine.run(_prices(), signals)

    trade = result.trades[0]
    assert trade.execution_price == pytest.approx(101.0 * 1.01)
    assert trade.gross_amount == pytest.approx(101.0 * 1.01 * 10)
    assert trade.commission == pytest.approx(trade.gross_amount * 0.01)
    assert trade.tax == 0.0
    assert trade.slippage == pytest.approx((101.0 * 0.01) * 10)
    assert result.portfolio.cash == pytest.approx(10_000 + trade.net_cash_flow)


def test_sell_transaction_costs_tax_and_slippage_are_deducted_from_cash() -> None:
    signals = pd.DataFrame(
        [
            {"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10},
            {"date": "2024-01-02", "symbol": "2330", "action": "sell", "quantity": 10},
        ]
    )
    engine = BacktestEngine(
        initial_cash=10_000,
        broker_config=BrokerConfig(
            commission_rate=0.01,
            tax_rate=0.02,
            slippage_rate=0.01,
            execution_price_col="open",
        ),
    )

    result = engine.run(_prices(), signals)

    buy, sell = result.trades
    assert sell.execution_price == pytest.approx(105.0 * 0.99)
    assert sell.commission == pytest.approx(sell.gross_amount * 0.01)
    assert sell.tax == pytest.approx(sell.gross_amount * 0.02)
    assert sell.slippage == pytest.approx((105.0 * 0.01) * 10)
    assert sell.net_cash_flow == pytest.approx(sell.gross_amount - sell.commission - sell.tax)
    assert result.portfolio.cash == pytest.approx(10_000 + buy.net_cash_flow + sell.net_cash_flow)


def test_signal_does_not_execute_on_same_day() -> None:
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    engine = BacktestEngine(initial_cash=10_000)

    result = engine.run(_prices(), signals)

    assert result.trades[0].signal_date == "2024-01-01"
    assert result.trades[0].execution_date == "2024-01-02"
    day_one = result.equity_curve.loc[result.equity_curve["date"] == "2024-01-01"].iloc[0]
    assert day_one["positions_count"] == 0
    assert day_one["cash"] == pytest.approx(10_000)


def test_last_bar_signal_does_not_execute_without_next_bar() -> None:
    signals = pd.DataFrame(
        [{"date": "2024-01-04", "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    engine = BacktestEngine(initial_cash=10_000)

    result = engine.run(_prices(), signals)

    assert result.trades == []
    assert result.orders[0].status == "pending"
    assert result.equity_curve["total_equity"].tolist() == [10_000.0] * 4


def test_max_drawdown_calculation_is_correct() -> None:
    equity_curve = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "cash": [100.0, 120.0, 90.0, 110.0],
            "market_value": [0.0, 0.0, 0.0, 0.0],
            "total_equity": [100.0, 120.0, 90.0, 110.0],
        }
    )

    metrics = PerformanceMetrics.calculate(equity_curve, [], initial_cash=100.0)

    assert metrics.max_drawdown == pytest.approx(-0.25)


def test_no_trades_does_not_raise() -> None:
    engine = BacktestEngine(initial_cash=10_000)

    result = engine.run(_prices(), signals=None)

    assert result.trades == []
    assert result.metrics.number_of_trades == 0
    assert result.metrics.total_return == pytest.approx(0.0)
    assert result.equity_curve["total_equity"].tolist() == [10_000.0] * 4


def test_risk_gate_blocks_buy_when_cash_is_insufficient() -> None:
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 200}]
    )
    engine = BacktestEngine(
        initial_cash=1_000,
        risk_config=_permissive_test_risk_config(),
    )

    result = engine.run(_prices(), signals)

    assert result.trades == []
    assert len(result.rejected_orders) == 1
    assert "insufficient_cash" in str(result.rejected_orders[0].rejection_reason)


def test_risk_gate_blocks_buy_over_single_position_limit() -> None:
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 30}]
    )
    engine = BacktestEngine(
        initial_cash=10_000,
        risk_config=_permissive_test_risk_config(max_position_pct=0.20),
    )

    result = engine.run(_prices(), signals)

    assert result.trades == []
    assert len(result.rejected_orders) == 1
    assert "max_position_pct_exceeded" in str(result.rejected_orders[0].rejection_reason)


def test_risk_gate_blocks_buy_over_max_positions() -> None:
    prices = pd.concat(
        [
            _prices(),
            _prices().assign(symbol="0050", open=50.0, high=51.0, low=49.0, close=50.0),
        ],
        ignore_index=True,
    )
    signals = pd.DataFrame(
        [
            {"date": "2024-01-01", "symbol": "0050", "action": "buy", "quantity": 10},
            {"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10},
        ]
    )
    engine = BacktestEngine(
        initial_cash=10_000,
        risk_config=_permissive_test_risk_config(max_positions=1),
    )

    result = engine.run(prices, signals)

    assert len(result.trades) == 1
    assert len(result.rejected_orders) == 1
    assert result.rejected_orders[0].rejection_reason == "已達最大持股數限制"


def test_risk_gate_allows_valid_buy() -> None:
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    engine = BacktestEngine(
        initial_cash=10_000,
        risk_config=_permissive_test_risk_config(max_position_pct=0.50),
    )

    result = engine.run(_prices(), signals)

    assert len(result.trades) == 1
    assert result.trades[0].side == "buy"
    assert result.rejected_orders == []


def test_risk_gate_does_not_mutate_price_or_signal_inputs() -> None:
    prices = _prices()
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    original_prices = prices.copy(deep=True)
    original_signals = signals.copy(deep=True)
    engine = BacktestEngine(
        initial_cash=10_000,
        risk_config=_permissive_test_risk_config(max_position_pct=0.50),
    )

    engine.run(prices, signals)

    pdt.assert_frame_equal(prices, original_prices)
    pdt.assert_frame_equal(signals, original_signals)


def test_backtest_engine_calls_risk_manager_for_each_buy_order() -> None:
    risk_manager = RecordingRiskManager(_permissive_test_risk_config(max_position_pct=0.90))
    prices = pd.concat(
        [
            _prices(),
            _prices().assign(symbol="0050", open=50.0, high=51.0, low=49.0, close=50.0),
        ],
        ignore_index=True,
    )
    signals = pd.DataFrame(
        [
            {"date": "2024-01-01", "symbol": "0050", "action": "buy", "quantity": 10},
            {"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10},
        ]
    )
    engine = BacktestEngine(initial_cash=10_000, risk_manager=risk_manager)

    engine.run(prices, signals)

    assert len(risk_manager.buy_calls) == 2
    assert {str(call["symbol"]) for call in risk_manager.buy_calls} == {"0050", "2330"}


def test_risk_gate_rejects_sell_without_enough_position() -> None:
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "sell", "quantity": 10}]
    )
    engine = BacktestEngine(
        initial_cash=10_000,
        risk_config=_permissive_test_risk_config(),
    )

    result = engine.run(_prices(), signals)

    assert result.trades == []
    assert len(result.rejected_orders) == 1
    assert "no_position_to_sell" in str(result.rejected_orders[0].rejection_reason)


def test_max_positions_rejects_additional_symbol() -> None:
    prices = pd.concat(
        [
            _prices(),
            _prices().assign(symbol="0050", open=50.0, high=51.0, low=49.0, close=50.0),
        ],
        ignore_index=True,
    )
    signals = pd.DataFrame(
        [
            {"date": "2024-01-01", "symbol": "0050", "action": "buy", "quantity": 10},
            {"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10},
        ]
    )
    engine = BacktestEngine(initial_cash=10_000, max_positions=1)

    result = engine.run(prices, signals)

    assert len(result.trades) == 1
    assert len(result.rejected_orders) == 1
    assert result.rejected_orders[0].rejection_reason == "已達最大持股數限制"


def test_max_position_percent_caps_buy_quantity() -> None:
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 1000}]
    )
    engine = BacktestEngine(initial_cash=10_000, max_position_pct=0.10)

    result = engine.run(_prices(), signals)

    assert result.trades[0].quantity == 9
    assert result.portfolio.positions["2330"].quantity == 9


def test_stop_loss_generates_next_day_exit() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "symbol": ["2330", "2330", "2330", "2330"],
            "open": [100.0, 100.0, 95.0, 94.0],
            "high": [101.0, 101.0, 96.0, 95.0],
            "low": [99.0, 90.0, 94.0, 93.0],
            "close": [100.0, 90.0, 95.0, 94.0],
            "volume": [1000, 1000, 1000, 1000],
        }
    )
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    engine = BacktestEngine(initial_cash=10_000, stop_loss_pct=0.05)

    result = engine.run(prices, signals)

    assert [trade.side for trade in result.trades] == ["buy", "sell"]
    assert result.trades[1].reason == "stop_loss"
    assert result.trades[1].signal_date == "2024-01-02"
    assert result.trades[1].execution_date == "2024-01-03"


def test_trailing_stop_generates_next_day_exit_without_same_day_fill() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
            "symbol": ["2330"] * 5,
            "open": [100.0, 100.0, 121.0, 106.0, 99.0],
            "high": [101.0, 112.0, 123.0, 108.0, 100.0],
            "low": [99.0, 99.0, 119.0, 104.0, 98.0],
            "close": [100.0, 110.0, 120.0, 105.0, 99.0],
            "volume": [1000] * 5,
        }
    )
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    engine = BacktestEngine(initial_cash=10_000, trailing_stop_pct=0.10)

    result = engine.run(prices, signals)

    assert [trade.side for trade in result.trades] == ["buy", "sell"]
    sell = result.trades[1]
    assert sell.reason == "trailing_stop"
    assert sell.signal_date == "2024-01-04"
    assert sell.execution_date == "2024-01-05"
    assert sell.execution_price == pytest.approx(99.0)
    day_four = result.equity_curve.loc[result.equity_curve["date"] == "2024-01-04"].iloc[0]
    assert day_four["positions_count"] == 1
    day_five = result.equity_curve.loc[result.equity_curve["date"] == "2024-01-05"].iloc[0]
    assert day_five["positions_count"] == 0
    highest_close = result.positions_history.loc[
        result.positions_history["date"] == "2024-01-04", "trailing_high_close"
    ].iloc[0]
    assert highest_close == pytest.approx(120.0)


def test_trailing_stop_applies_sell_cost_tax_and_slippage() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
            "symbol": ["2330"] * 5,
            "open": [100.0, 100.0, 121.0, 106.0, 99.0],
            "high": [101.0, 112.0, 123.0, 108.0, 100.0],
            "low": [99.0, 99.0, 119.0, 104.0, 98.0],
            "close": [100.0, 110.0, 120.0, 105.0, 99.0],
            "volume": [1000] * 5,
        }
    )
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    engine = BacktestEngine(
        initial_cash=10_000,
        trailing_stop_pct=0.10,
        broker_config=BrokerConfig(
            commission_rate=0.01,
            tax_rate=0.02,
            slippage_rate=0.01,
            execution_price_col="open",
        ),
    )

    result = engine.run(prices, signals)

    sell = result.trades[1]
    assert sell.execution_price == pytest.approx(99.0 * 0.99)
    assert sell.commission == pytest.approx(sell.gross_amount * 0.01)
    assert sell.tax == pytest.approx(sell.gross_amount * 0.02)
    assert sell.slippage == pytest.approx(99.0 * 0.01 * sell.quantity)


def test_trailing_stop_last_bar_signal_does_not_execute_without_next_bar() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "symbol": ["2330"] * 4,
            "open": [100.0, 100.0, 121.0, 106.0],
            "high": [101.0, 112.0, 123.0, 108.0],
            "low": [99.0, 99.0, 119.0, 104.0],
            "close": [100.0, 110.0, 120.0, 105.0],
            "volume": [1000] * 4,
        }
    )
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    engine = BacktestEngine(initial_cash=10_000, trailing_stop_pct=0.10)

    result = engine.run(prices, signals)

    assert [trade.side for trade in result.trades] == ["buy"]
    trailing_orders = [order for order in result.orders if order.reason == "trailing_stop"]
    assert len(trailing_orders) == 1
    assert trailing_orders[0].signal_date == "2024-01-04"
    assert trailing_orders[0].status == "pending"


def test_trailing_stop_uses_close_peak_not_intraday_high() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "symbol": ["2330"] * 4,
            "open": [100.0, 100.0, 96.0, 95.0],
            "high": [101.0, 150.0, 97.0, 96.0],
            "low": [99.0, 99.0, 94.0, 94.0],
            "close": [100.0, 100.0, 95.0, 96.0],
            "volume": [1000] * 4,
        }
    )
    signals = pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    engine = BacktestEngine(initial_cash=10_000, trailing_stop_pct=0.10)

    result = engine.run(prices, signals)

    assert [trade.side for trade in result.trades] == ["buy"]
    assert all(order.reason != "trailing_stop" for order in result.orders)
    assert "highest close" in TRAILING_STOP_DAILY_MODEL_NOTICE.lower()


def test_benchmark_comparison_is_reported() -> None:
    equity_curve = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "cash": [100.0, 110.0],
            "market_value": [0.0, 0.0],
            "total_equity": [100.0, 110.0],
        }
    )
    benchmark = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "close": [100.0, 105.0],
        }
    )

    metrics = PerformanceMetrics.calculate(
        equity_curve,
        [],
        initial_cash=100.0,
        benchmark=benchmark,
    )

    assert metrics.benchmark_total_return == pytest.approx(0.05)
    assert metrics.benchmark_excess_return == pytest.approx(0.05)


def test_benchmark_comparison_is_aligned_to_equity_curve_period() -> None:
    equity_curve = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03"],
            "cash": [100.0, 110.0],
            "market_value": [0.0, 0.0],
            "total_equity": [100.0, 110.0],
        }
    )
    benchmark = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "close": [50.0, 100.0, 105.0, 200.0],
        }
    )

    metrics = PerformanceMetrics.calculate(
        equity_curve,
        [],
        initial_cash=100.0,
        benchmark=benchmark,
    )

    assert metrics.benchmark_total_return == pytest.approx(0.05)
    assert metrics.benchmark_excess_return == pytest.approx(0.05)


def test_malformed_benchmark_does_not_raise() -> None:
    equity_curve = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "cash": [100.0, 110.0],
            "market_value": [0.0, 0.0],
            "total_equity": [100.0, 110.0],
        }
    )

    metrics = PerformanceMetrics.calculate(
        equity_curve,
        [],
        initial_cash=100.0,
        benchmark=pd.DataFrame({"close": [100.0, 105.0]}),
    )

    assert metrics.benchmark_total_return is None
    assert metrics.benchmark_excess_return is None
