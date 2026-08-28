"""Portfolio accounting for cash, positions, and daily equity snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Mapping

from stock_tool.backtest.orders import Position


@dataclass(frozen=True)
class PortfolioSnapshot:
    """End-of-day portfolio state."""

    date: str
    cash: float
    market_value: float
    total_equity: float
    cash_ratio: float
    exposure: float
    positions_count: int


@dataclass
class Portfolio:
    """Track simulated cash, positions, and market value."""

    initial_cash: float
    cash: float | None = None
    positions: dict[str, Position] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive.")
        if self.cash is None:
            self.cash = float(self.initial_cash)
        if self.cash < 0:
            raise ValueError("cash cannot be negative.")

    def buy(
        self,
        *,
        symbol: str,
        quantity: int,
        total_cash_out: float,
        effective_cost_per_share: float,
        execution_date: str,
        last_price: float,
    ) -> None:
        """Apply a filled buy trade to cash and positions."""

        if quantity <= 0:
            raise ValueError("quantity must be positive.")
        assert self.cash is not None
        if total_cash_out > self.cash + 1e-9:
            raise ValueError("insufficient cash for buy trade.")

        self.cash -= total_cash_out
        position = self.positions.get(symbol)
        if position is None:
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                average_cost=effective_cost_per_share,
                entry_date=execution_date,
                last_price=last_price,
            )
            return

        current_cost = position.average_cost * position.quantity
        added_cost = effective_cost_per_share * quantity
        new_quantity = position.quantity + quantity
        position.quantity = new_quantity
        position.average_cost = (current_cost + added_cost) / new_quantity
        position.update_market_price(last_price)

    def sell(
        self,
        *,
        symbol: str,
        quantity: int,
        net_cash_in: float,
        execution_date: str,
        last_price: float,
    ) -> tuple[float, int | None]:
        """Apply a filled sell trade and return realized PnL plus holding days."""

        if quantity <= 0:
            raise ValueError("quantity must be positive.")
        assert self.cash is not None

        position = self.positions.get(symbol)
        if position is None or position.quantity < quantity:
            raise ValueError("insufficient position quantity for sell trade.")

        realized_pnl = net_cash_in - (position.average_cost * quantity)
        holding_days = _date_diff_days(position.entry_date, execution_date)

        self.cash += net_cash_in
        position.quantity -= quantity
        position.update_market_price(last_price)
        if position.quantity == 0:
            del self.positions[symbol]

        return realized_pnl, holding_days

    def update_market_prices(self, prices: Mapping[str, float]) -> None:
        """Update latest mark prices for open positions."""

        for symbol, price in prices.items():
            position = self.positions.get(symbol)
            if position is not None:
                position.update_market_price(float(price))

    def credit_cash(self, amount: float) -> None:
        """Credit a validated non-trade cash flow, such as a paid dividend."""

        if amount < 0:
            raise ValueError("cash credit cannot be negative.")
        self.cash = float(self.cash or 0.0) + amount

    @property
    def market_value(self) -> float:
        """Return total market value of all open positions."""

        return sum(position.market_value for position in self.positions.values())

    @property
    def total_equity(self) -> float:
        """Return cash plus marked-to-market position value."""

        return float(self.cash or 0.0) + self.market_value

    @property
    def cash_ratio(self) -> float:
        """Return cash divided by total equity."""

        equity = self.total_equity
        return 0.0 if equity <= 0 else float(self.cash or 0.0) / equity

    @property
    def exposure(self) -> float:
        """Return invested market value divided by total equity."""

        equity = self.total_equity
        return 0.0 if equity <= 0 else self.market_value / equity

    def snapshot(self, snapshot_date: str) -> PortfolioSnapshot:
        """Create an end-of-day portfolio snapshot."""

        return PortfolioSnapshot(
            date=snapshot_date,
            cash=float(self.cash or 0.0),
            market_value=self.market_value,
            total_equity=self.total_equity,
            cash_ratio=self.cash_ratio,
            exposure=self.exposure,
            positions_count=len(self.positions),
        )


def _date_diff_days(start: str, end: str) -> int | None:
    try:
        start_date = _parse_date(start)
        end_date = _parse_date(end)
    except ValueError:
        return None
    return (end_date - start_date).days


def _parse_date(value: str) -> date:
    return datetime.fromisoformat(value).date()
