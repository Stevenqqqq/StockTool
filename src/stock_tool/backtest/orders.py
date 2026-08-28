"""Order, trade, and position models used by the backtesting engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OrderSide = Literal["buy", "sell"]
OrderStatus = Literal["pending", "filled", "rejected", "cancelled"]


@dataclass
class Order:
    """A simulated research order generated from a strategy signal.

    ``signal_date`` is the date on which the strategy produced the signal.
    The engine is responsible for enforcing that execution happens strictly
    after this date.
    """

    order_id: int
    symbol: str
    side: OrderSide
    signal_date: str
    quantity: int | None = None
    cash_amount: float | None = None
    target_percent: float | None = None
    reason: str = "signal"
    status: OrderStatus = "pending"
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        self.side = _normalize_side(self.side)
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError("Order quantity 若有設定，必須大於 0。")
        if self.cash_amount is not None and self.cash_amount <= 0:
            raise ValueError("Order cash_amount 若有設定，必須大於 0。")
        if self.target_percent is not None and not 0 <= self.target_percent <= 1:
            raise ValueError("Order target_percent 必須介於 0 到 1 之間。")

    def reject(self, reason: str) -> None:
        """Mark the order as rejected with a reason."""

        self.status = "rejected"
        self.rejection_reason = reason


@dataclass(frozen=True)
class Trade:
    """A filled simulated trade with full cost and cash-flow details."""

    order_id: int
    symbol: str
    side: OrderSide
    quantity: int
    signal_date: str
    execution_date: str
    execution_price: float
    gross_amount: float
    commission: float
    tax: float
    slippage: float
    net_cash_flow: float
    realized_pnl: float | None = None
    holding_days: int | None = None
    reason: str = "signal"


@dataclass
class Position:
    """Current position state for one symbol."""

    symbol: str
    quantity: int
    average_cost: float
    entry_date: str
    last_price: float

    @property
    def market_value(self) -> float:
        """Return current marked-to-market value."""

        return self.quantity * self.last_price

    def update_market_price(self, price: float) -> None:
        """Update the latest mark price for this position."""

        if price > 0:
            self.last_price = price


def _normalize_side(side: str) -> OrderSide:
    normalized = side.strip().lower()
    if normalized not in {"buy", "sell"}:
        raise ValueError(f"Unsupported order side: {side!r}")
    return normalized  # type: ignore[return-value]
