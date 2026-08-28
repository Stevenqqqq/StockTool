from __future__ import annotations

import pandas as pd
import pandas.testing as pdt
import pytest

from stock_tool.backtest.orders import Trade
from stock_tool.backtest.portfolio import Portfolio
from stock_tool.risk import PositionSizer, RiskConfig, RiskManager


def _portfolio_with_position() -> Portfolio:
    portfolio = Portfolio(initial_cash=10_000)
    portfolio.buy(
        symbol="2330",
        quantity=20,
        total_cash_out=2_000,
        effective_cost_per_share=100,
        execution_date="2024-01-01",
        last_price=100,
    )
    return portfolio


def test_exceeding_max_position_pct_blocks_buy() -> None:
    portfolio = Portfolio(initial_cash=10_000)
    manager = RiskManager(RiskConfig(max_position_pct=0.20, min_cash_ratio=0.0))

    decision = manager.evaluate_buy_order(
        portfolio=portfolio,
        symbol="2330",
        price=100,
        quantity=30,
    )

    assert decision.allowed is False
    assert any(alert.code == "max_position_pct_exceeded" for alert in decision.alerts)


def test_insufficient_cash_blocks_buy() -> None:
    portfolio = Portfolio(initial_cash=1_000)
    manager = RiskManager(RiskConfig(max_position_pct=0.90, min_cash_ratio=0.0))

    decision = manager.evaluate_buy_order(
        portfolio=portfolio,
        symbol="2330",
        price=100,
        quantity=20,
    )

    assert decision.allowed is False
    assert any(alert.code == "insufficient_cash" for alert in decision.alerts)


def test_max_trade_loss_blocks_buy() -> None:
    portfolio = Portfolio(initial_cash=10_000)
    manager = RiskManager(
        RiskConfig(
            max_position_pct=0.90,
            max_trade_loss_pct=0.01,
            min_cash_ratio=0.0,
            default_stop_loss_pct=0.10,
        )
    )

    decision = manager.evaluate_buy_order(
        portfolio=portfolio,
        symbol="2330",
        price=100,
        quantity=20,
    )

    assert decision.allow is False
    assert decision.reason == "max_trade_loss_exceeded"
    assert any(alert.code == "max_trade_loss_exceeded" for alert in decision.alerts)


def test_risk_decision_reports_adjusted_order_size() -> None:
    portfolio = Portfolio(initial_cash=10_000)
    manager = RiskManager(
        RiskConfig(
            max_position_pct=0.20,
            max_trade_loss_pct=0.99,
            min_cash_ratio=0.0,
            default_stop_loss_pct=0.01,
        )
    )

    decision = manager.evaluate_buy_order(
        portfolio=portfolio,
        symbol="2330",
        price=100,
        quantity=30,
    )

    assert decision.allowed is False
    assert decision.adjusted_order_size == 20
    assert "max_position_pct_exceeded" in decision.reason


def test_stop_loss_generates_sell_order() -> None:
    portfolio = _portfolio_with_position()
    manager = RiskManager(RiskConfig(default_stop_loss_pct=0.10))

    order = manager.generate_stop_loss_order(
        portfolio=portfolio,
        symbol="2330",
        current_price=89,
        current_date="2024-01-02",
        order_id=7,
    )

    assert order is not None
    assert order.side == "sell"
    assert order.symbol == "2330"
    assert order.quantity == 20
    assert order.signal_date == "2024-01-02"
    assert order.reason == "risk_stop_loss"


def test_max_drawdown_alert_is_emitted() -> None:
    equity_curve = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "total_equity": [100.0, 120.0, 80.0],
        }
    )
    manager = RiskManager(RiskConfig(max_drawdown_pct=0.20))

    alerts = manager.check_portfolio_alerts(equity_curve=equity_curve)

    assert len(alerts) == 1
    assert alerts[0].code == "max_drawdown_exceeded"
    assert alerts[0].severity == "critical"
    assert alerts[0].value == pytest.approx(1 - 80 / 120)


def test_risk_manager_does_not_mutate_inputs() -> None:
    portfolio = _portfolio_with_position()
    before_cash = portfolio.cash
    before_quantity = portfolio.positions["2330"].quantity
    before_last_price = portfolio.positions["2330"].last_price
    equity_curve = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "total_equity": [10_000.0, 9_500.0],
        }
    )
    original_curve = equity_curve.copy(deep=True)
    manager = RiskManager()

    manager.evaluate_buy_order(
        portfolio=portfolio,
        symbol="2317",
        price=50,
        quantity=10,
        industry="electronics",
        industry_map={"2330": "semiconductor"},
    )
    manager.generate_stop_loss_order(
        portfolio=portfolio,
        symbol="2330",
        current_price=90,
        current_date="2024-01-02",
    )
    manager.check_portfolio_alerts(equity_curve=equity_curve, portfolio=portfolio)

    assert portfolio.cash == before_cash
    assert portfolio.positions["2330"].quantity == before_quantity
    assert portfolio.positions["2330"].last_price == before_last_price
    pdt.assert_frame_equal(equity_curve, original_curve)


def test_position_sizer_supports_all_methods() -> None:
    sizer = PositionSizer(RiskConfig(max_trade_loss_pct=0.02))

    assert sizer.fixed_amount(amount=1_000, price=90) == 11
    assert sizer.fixed_percent(portfolio_value=10_000, percent=0.25, price=100) == 25
    assert sizer.atr_based(
        portfolio_value=10_000,
        risk_pct=0.01,
        atr=2,
        atr_multiplier=2,
    ) == 25
    assert sizer.max_loss_based(
        portfolio_value=10_000,
        entry_price=100,
        stop_price=95,
    ) == 40


def test_cash_ratio_position_count_and_industry_limits_emit_alerts() -> None:
    portfolio = _portfolio_with_position()
    manager = RiskManager(
        RiskConfig(
            max_position_pct=0.5,
            max_positions=1,
            min_cash_ratio=0.90,
            max_industry_pct=0.2,
        )
    )

    decision = manager.evaluate_buy_order(
        portfolio=portfolio,
        symbol="2317",
        price=100,
        quantity=1,
        industry="semiconductor",
        industry_map={"2330": "semiconductor"},
    )

    assert decision.allowed is False
    codes = {alert.code for alert in decision.alerts}
    assert "max_positions_exceeded" in codes
    assert "min_cash_ratio_breached" in codes
    assert "industry_concentration_exceeded" in codes


def test_volatility_and_consecutive_loss_alerts() -> None:
    manager = RiskManager(RiskConfig(max_volatility=0.05, max_consecutive_losses=2))
    returns = pd.Series([0.10, -0.10, 0.08, -0.08])
    trades = [
        Trade(
            order_id=1,
            symbol="2330",
            side="sell",
            quantity=1,
            signal_date="2024-01-01",
            execution_date="2024-01-02",
            execution_price=90,
            gross_amount=90,
            commission=0,
            tax=0,
            slippage=0,
            net_cash_flow=90,
            realized_pnl=-10,
        ),
        Trade(
            order_id=2,
            symbol="2330",
            side="sell",
            quantity=1,
            signal_date="2024-01-03",
            execution_date="2024-01-04",
            execution_price=80,
            gross_amount=80,
            commission=0,
            tax=0,
            slippage=0,
            net_cash_flow=80,
            realized_pnl=-20,
        ),
    ]

    alerts = manager.check_portfolio_alerts(returns=returns, trades=trades)
    codes = {alert.code for alert in alerts}

    assert "volatility_too_high" in codes
    assert "consecutive_losses" in codes


def test_full_single_stock_allocation_is_not_allowed() -> None:
    with pytest.raises(ValueError, match="單一股票滿倉"):
        RiskConfig(max_position_pct=1.0)
