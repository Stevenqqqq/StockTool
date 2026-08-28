"""Simulated broker for research backtests."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Any, Mapping

from stock_tool.backtest.orders import Order, Trade
from stock_tool.backtest.portfolio import Portfolio


@dataclass(frozen=True)
class BrokerConfig:
    """Configurable simulated execution and cost settings."""

    commission_rate: float = 0.0
    tax_rate: float = 0.0
    slippage_rate: float = 0.0
    min_commission: float = 0.0
    execution_price_col: str = "open"
    allow_partial_fill: bool = True

    def __post_init__(self) -> None:
        if min(self.commission_rate, self.tax_rate, self.slippage_rate, self.min_commission) < 0:
            raise ValueError("Broker cost settings cannot be negative.")


class BrokerSimulator:
    """Fill research orders against next-bar market data.

    This class never connects to a real broker. It only simulates fills using
    the configured execution price column and cost model.
    """

    def __init__(self, config: BrokerConfig | None = None) -> None:
        self.config = config or BrokerConfig()

    def execute_order(
        self,
        order: Order,
        market_row: Mapping[str, Any],
        portfolio: Portfolio,
        *,
        max_position_pct: float | None = None,
        max_positions: int | None = None,
    ) -> Trade | None:
        """Attempt to execute an order and update the portfolio when filled."""

        base_price = _read_positive_price(market_row, self.config.execution_price_col)
        if base_price is None:
            order.reject(f"成交價格缺失或無效：{self.config.execution_price_col}")
            return None

        symbol = str(order.symbol)
        execution_date = str(market_row["date"])
        fill_price = self._fill_price(base_price, order.side)
        quantity = self._resolve_quantity(
            order=order,
            portfolio=portfolio,
            fill_price=fill_price,
            max_position_pct=max_position_pct,
            max_positions=max_positions,
        )
        if quantity <= 0:
            if order.status != "rejected":
                order.reject("換算後下單數量為 0")
            return None

        gross_amount = fill_price * quantity
        commission = self._commission(gross_amount)
        tax = gross_amount * self.config.tax_rate if order.side == "sell" else 0.0
        slippage = abs(fill_price - base_price) * quantity

        if order.side == "buy":
            total_cash_out = gross_amount + commission
            if total_cash_out > float(portfolio.cash or 0.0) + 1e-9:
                if not self.config.allow_partial_fill:
                    order.reject("現金不足")
                    return None
                quantity = self._max_affordable_quantity(portfolio, fill_price)
                if quantity <= 0:
                    order.reject("現金不足")
                    return None
                gross_amount = fill_price * quantity
                commission = self._commission(gross_amount)
                slippage = abs(fill_price - base_price) * quantity
                total_cash_out = gross_amount + commission

            portfolio.buy(
                symbol=symbol,
                quantity=quantity,
                total_cash_out=total_cash_out,
                effective_cost_per_share=total_cash_out / quantity,
                execution_date=execution_date,
                last_price=fill_price,
            )
            trade = Trade(
                order_id=order.order_id,
                symbol=symbol,
                side="buy",
                quantity=quantity,
                signal_date=order.signal_date,
                execution_date=execution_date,
                execution_price=fill_price,
                gross_amount=gross_amount,
                commission=commission,
                tax=0.0,
                slippage=slippage,
                net_cash_flow=-total_cash_out,
                reason=order.reason,
            )
        else:
            position = portfolio.positions.get(symbol)
            if position is None:
                order.reject("no position to sell")
                return None
            if quantity > position.quantity:
                if not self.config.allow_partial_fill:
                    order.reject("持股數量不足")
                    return None
                quantity = position.quantity
                gross_amount = fill_price * quantity
                commission = self._commission(gross_amount)
                tax = gross_amount * self.config.tax_rate
                slippage = abs(fill_price - base_price) * quantity

            net_cash_in = gross_amount - commission - tax
            realized_pnl, holding_days = portfolio.sell(
                symbol=symbol,
                quantity=quantity,
                net_cash_in=net_cash_in,
                execution_date=execution_date,
                last_price=fill_price,
            )
            trade = Trade(
                order_id=order.order_id,
                symbol=symbol,
                side="sell",
                quantity=quantity,
                signal_date=order.signal_date,
                execution_date=execution_date,
                execution_price=fill_price,
                gross_amount=gross_amount,
                commission=commission,
                tax=tax,
                slippage=slippage,
                net_cash_flow=net_cash_in,
                realized_pnl=realized_pnl,
                holding_days=holding_days,
                reason=order.reason,
            )

        order.status = "filled"
        return trade

    def _resolve_quantity(
        self,
        *,
        order: Order,
        portfolio: Portfolio,
        fill_price: float,
        max_position_pct: float | None,
        max_positions: int | None,
    ) -> int:
        if order.side == "sell":
            position = portfolio.positions.get(order.symbol)
            if position is None:
                return 0
            if order.target_percent is not None:
                target_value = portfolio.total_equity * order.target_percent
                current_value = position.quantity * fill_price
                return floor(max(current_value - target_value, 0.0) / fill_price)
            return int(order.quantity or position.quantity)

        if max_positions is not None and order.symbol not in portfolio.positions:
            if len(portfolio.positions) >= max_positions:
                order.reject("已達最大持股數限制")
                return 0

        if order.target_percent is not None:
            target_value = portfolio.total_equity * order.target_percent
            current_value = portfolio.positions.get(order.symbol)
            current_market_value = 0.0 if current_value is None else current_value.quantity * fill_price
            raw_quantity = floor(max(target_value - current_market_value, 0.0) / fill_price)
        elif order.cash_amount is not None:
            raw_quantity = floor(order.cash_amount / max(fill_price, 1e-12))
        else:
            raw_quantity = int(order.quantity or 0)

        if raw_quantity <= 0:
            return 0

        if max_position_pct is not None:
            if not 0 < max_position_pct <= 1:
                raise ValueError("max_position_pct 必須介於 0 到 1 之間。")
            position = portfolio.positions.get(order.symbol)
            current_quantity = 0 if position is None else position.quantity
            current_value = current_quantity * fill_price
            max_value = portfolio.total_equity * max_position_pct
            additional_value = max(max_value - current_value, 0.0)
            raw_quantity = min(raw_quantity, floor(additional_value / fill_price))

        return max(raw_quantity, 0)

    def _fill_price(self, base_price: float, side: str) -> float:
        if side == "buy":
            return base_price * (1.0 + self.config.slippage_rate)
        return base_price * (1.0 - self.config.slippage_rate)

    def _commission(self, gross_amount: float) -> float:
        commission = gross_amount * self.config.commission_rate
        if commission > 0 and self.config.min_commission > 0:
            return max(commission, self.config.min_commission)
        if commission == 0 and self.config.min_commission > 0:
            return self.config.min_commission
        return commission

    def _max_affordable_quantity(self, portfolio: Portfolio, fill_price: float) -> int:
        cash = float(portfolio.cash or 0.0)
        if cash <= 0:
            return 0

        rough = floor(cash / max(fill_price * (1.0 + self.config.commission_rate), 1e-12))
        while rough > 0:
            gross = rough * fill_price
            if gross + self._commission(gross) <= cash + 1e-9:
                return rough
            rough -= 1
        return 0


def _read_positive_price(row: Mapping[str, Any], price_col: str) -> float | None:
    try:
        value = float(row[price_col])
    except (KeyError, TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value
