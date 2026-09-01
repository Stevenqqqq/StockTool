"""Risk configuration, alerts, checks, and position sizing."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Any, Literal, Mapping, Sequence

import pandas as pd

from stock_tool.backtest.orders import Order
from stock_tool.backtest.portfolio import Portfolio

RiskSeverity = Literal["info", "warning", "critical"]


@dataclass(frozen=True)
class RiskConfig:
    """Configurable risk limits for research portfolio controls."""

    max_position_pct: float = 0.25
    max_trade_loss_pct: float = 0.01
    max_positions: int = 10
    min_cash_ratio: float = 0.05
    max_drawdown_pct: float = 0.20
    max_volatility: float = 0.40
    max_consecutive_losses: int = 3
    max_industry_pct: float = 0.40
    default_stop_loss_pct: float = 0.08

    def __post_init__(self) -> None:
        if not 0 < self.max_position_pct < 1:
            raise ValueError("max_position_pct 必須介於 0 到 1 之間；不允許單一股票滿倉。")
        if not 0 < self.max_trade_loss_pct < 1:
            raise ValueError("max_trade_loss_pct 必須介於 0 到 1 之間。")
        if self.max_positions <= 0:
            raise ValueError("max_positions 必須大於 0。")
        if not 0 <= self.min_cash_ratio < 1:
            raise ValueError("min_cash_ratio 必須介於 0 到 1 之間。")
        if not 0 < self.max_drawdown_pct < 1:
            raise ValueError("max_drawdown_pct 必須介於 0 到 1 之間。")
        if self.max_volatility <= 0:
            raise ValueError("max_volatility 必須大於 0。")
        if self.max_consecutive_losses <= 0:
            raise ValueError("max_consecutive_losses 必須大於 0。")
        if not 0 < self.max_industry_pct < 1:
            raise ValueError("max_industry_pct 必須介於 0 到 1 之間。")
        if not 0 < self.default_stop_loss_pct < 1:
            raise ValueError("default_stop_loss_pct 必須介於 0 到 1 之間。")


@dataclass(frozen=True)
class RiskAlert:
    """Risk event or warning emitted by risk controls."""

    code: str
    severity: RiskSeverity
    message: str
    symbol: str | None = None
    date: str | None = None
    value: float | None = None
    threshold: float | None = None


@dataclass(frozen=True)
class RiskDecision:
    """Allow/deny decision with associated risk alerts."""

    allowed: bool
    alerts: tuple[RiskAlert, ...]
    adjusted_quantity: int | None = None
    reason: str = ""
    warnings: tuple[RiskAlert, ...] = ()

    @property
    def allow(self) -> bool:
        """Alias for callers that prefer ``allow`` naming."""

        return self.allowed

    @property
    def adjusted_order_size(self) -> int | None:
        """Alias for adjusted quantity naming in order workflows."""

        return self.adjusted_quantity


class PositionSizer:
    """Calculate position quantities using configurable sizing methods."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    def fixed_amount(self, *, amount: float, price: float) -> int:
        """Return quantity for a fixed cash amount."""

        _validate_positive("amount", amount)
        _validate_positive("price", price)
        return floor(amount / price)

    def fixed_percent(self, *, portfolio_value: float, percent: float, price: float) -> int:
        """Return quantity for a fixed portfolio percentage."""

        _validate_positive("portfolio_value", portfolio_value)
        _validate_positive("price", price)
        if not 0 < percent < 1:
            raise ValueError("percent 必須介於 0 到 1 之間。")
        return floor((portfolio_value * percent) / price)

    def atr_based(
        self,
        *,
        portfolio_value: float,
        risk_pct: float,
        atr: float,
        atr_multiplier: float,
    ) -> int:
        """Return quantity sized by ATR stop distance."""

        _validate_positive("portfolio_value", portfolio_value)
        _validate_positive("atr", atr)
        _validate_positive("atr_multiplier", atr_multiplier)
        if not 0 < risk_pct < 1:
            raise ValueError("risk_pct 必須介於 0 到 1 之間。")
        risk_budget = portfolio_value * risk_pct
        stop_distance = atr * atr_multiplier
        return floor(risk_budget / stop_distance)

    def max_loss_based(
        self,
        *,
        portfolio_value: float,
        entry_price: float,
        stop_price: float,
        max_loss_pct: float | None = None,
    ) -> int:
        """Return quantity such that stop-loss loss is within the risk budget."""

        _validate_positive("portfolio_value", portfolio_value)
        _validate_positive("entry_price", entry_price)
        _validate_positive("stop_price", stop_price)
        risk_pct = self.config.max_trade_loss_pct if max_loss_pct is None else max_loss_pct
        if not 0 < risk_pct < 1:
            raise ValueError("max_loss_pct 必須介於 0 到 1 之間。")
        loss_per_share = entry_price - stop_price
        if loss_per_share <= 0:
            raise ValueError("做多部位的停損價必須低於進場價。")
        return floor((portfolio_value * risk_pct) / loss_per_share)


class RiskManager:
    """Evaluate risk limits and produce alerts without mutating inputs."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()
        self.position_sizer = PositionSizer(self.config)

    def evaluate_buy_order(
        self,
        *,
        portfolio: Portfolio,
        symbol: str,
        price: float,
        quantity: int,
        stop_loss_pct: float | None = None,
        industry: str | None = None,
        industry_map: Mapping[str, str] | None = None,
    ) -> RiskDecision:
        """Return whether a proposed buy order passes portfolio risk limits."""

        _validate_positive("price", price)
        if quantity <= 0:
            raise ValueError("quantity 必須大於 0。")

        alerts: list[RiskAlert] = []
        order_value = price * quantity
        equity = portfolio.total_equity
        projected_cash = float(portfolio.cash or 0.0) - order_value
        current_position_value = 0.0
        if symbol in portfolio.positions:
            current_position_value = portfolio.positions[symbol].market_value

        if order_value > float(portfolio.cash or 0.0) + 1e-9:
            alerts.append(
                RiskAlert(
                    code="insufficient_cash",
                    severity="critical",
                    message="預計買入金額超過可用現金。",
                    symbol=symbol,
                    value=order_value,
                    threshold=float(portfolio.cash or 0.0),
                )
            )

        if equity > 0:
            threshold = (
                self.config.default_stop_loss_pct if stop_loss_pct is None else stop_loss_pct
            )
            if not 0 < threshold < 1:
                raise ValueError("stop_loss_pct 必須介於 0 到 1 之間。")
            estimated_loss = order_value * threshold
            max_trade_loss = equity * self.config.max_trade_loss_pct
            if estimated_loss > max_trade_loss:
                alerts.append(
                    RiskAlert(
                        code="max_trade_loss_exceeded",
                        severity="critical",
                        message="預計買入超過單筆交易最大風險預算。",
                        symbol=symbol,
                        value=estimated_loss,
                        threshold=max_trade_loss,
                    )
                )

        projected_position_pct = (
            (current_position_value + order_value) / equity if equity > 0 else 1.0
        )
        if projected_position_pct > self.config.max_position_pct:
            alerts.append(
                RiskAlert(
                    code="max_position_pct_exceeded",
                    severity="critical",
                    message="預計買入會超過單一股票最大持倉比例。",
                    symbol=symbol,
                    value=projected_position_pct,
                    threshold=self.config.max_position_pct,
                )
            )

        if (
            symbol not in portfolio.positions
            and len(portfolio.positions) >= self.config.max_positions
        ):
            alerts.append(
                RiskAlert(
                    code="max_positions_exceeded",
                    severity="critical",
                    message="預計買入會超過最大持股數量。",
                    symbol=symbol,
                    value=float(len(portfolio.positions) + 1),
                    threshold=float(self.config.max_positions),
                )
            )

        projected_cash_ratio = projected_cash / equity if equity > 0 else 0.0
        if projected_cash_ratio < self.config.min_cash_ratio:
            alerts.append(
                RiskAlert(
                    code="min_cash_ratio_breached",
                    severity="critical",
                    message="預計買入後會低於最低現金水位。",
                    symbol=symbol,
                    value=projected_cash_ratio,
                    threshold=self.config.min_cash_ratio,
                )
            )

        industry_alert = self._industry_concentration_alert(
            portfolio=portfolio,
            symbol=symbol,
            industry=industry,
            industry_map=industry_map,
            added_value=order_value,
        )
        if industry_alert is not None:
            alerts.append(industry_alert)

        adjusted_quantity = _suggest_adjusted_buy_quantity(
            portfolio=portfolio,
            symbol=symbol,
            price=price,
            quantity=quantity,
            max_position_pct=self.config.max_position_pct,
            min_cash_ratio=self.config.min_cash_ratio,
        )
        if adjusted_quantity is not None and adjusted_quantity >= quantity:
            adjusted_quantity = None

        warnings_found = tuple(alert for alert in alerts if alert.severity != "critical")
        critical_codes = [alert.code for alert in alerts if alert.severity == "critical"]
        return RiskDecision(
            allowed=not critical_codes,
            alerts=tuple(alerts),
            adjusted_quantity=adjusted_quantity,
            reason="allowed" if not critical_codes else "; ".join(critical_codes),
            warnings=warnings_found,
        )

    def evaluate_sell_order(
        self,
        *,
        portfolio: Portfolio,
        symbol: str,
        quantity: int,
    ) -> RiskDecision:
        """Return whether a proposed sell order has enough holdings to execute."""

        if quantity <= 0:
            raise ValueError("quantity 必須大於 0。")

        position = portfolio.positions.get(symbol)
        alerts: list[RiskAlert] = []
        if position is None:
            alerts.append(
                RiskAlert(
                    code="no_position_to_sell",
                    severity="critical",
                    message="預計賣出沒有對應持股。",
                    symbol=symbol,
                    value=float(quantity),
                    threshold=0.0,
                )
            )
        elif quantity > position.quantity:
            alerts.append(
                RiskAlert(
                    code="insufficient_position_quantity",
                    severity="critical",
                    message="預計賣出數量超過目前持股數量。",
                    symbol=symbol,
                    value=float(quantity),
                    threshold=float(position.quantity),
                )
            )

        critical_codes = [alert.code for alert in alerts if alert.severity == "critical"]
        adjusted_quantity = None
        if position is not None and quantity > position.quantity and position.quantity > 0:
            adjusted_quantity = position.quantity
        return RiskDecision(
            allowed=not critical_codes,
            alerts=tuple(alerts),
            adjusted_quantity=adjusted_quantity,
            reason="allowed" if not critical_codes else "; ".join(critical_codes),
            warnings=tuple(alert for alert in alerts if alert.severity != "critical"),
        )

    def generate_stop_loss_order(
        self,
        *,
        portfolio: Portfolio,
        symbol: str,
        current_price: float,
        current_date: str,
        stop_loss_pct: float | None = None,
        order_id: int = 0,
    ) -> Order | None:
        """Return a sell order when a position breaches its stop-loss level."""

        _validate_positive("current_price", current_price)
        position = portfolio.positions.get(symbol)
        if position is None:
            return None
        threshold = (
            stop_loss_pct if stop_loss_pct is not None else self.config.default_stop_loss_pct
        )
        if not 0 < threshold < 1:
            raise ValueError("stop_loss_pct 必須介於 0 到 1 之間。")
        stop_price = position.average_cost * (1.0 - threshold)
        if current_price <= stop_price:
            return Order(
                order_id=order_id,
                symbol=symbol,
                side="sell",
                signal_date=current_date,
                quantity=position.quantity,
                reason="risk_stop_loss",
            )
        return None

    def check_portfolio_alerts(
        self,
        *,
        equity_curve: pd.DataFrame | None = None,
        returns: pd.Series | None = None,
        trades: Sequence[Any] | None = None,
        portfolio: Portfolio | None = None,
        industry_map: Mapping[str, str] | None = None,
    ) -> tuple[RiskAlert, ...]:
        """Evaluate drawdown, volatility, consecutive losses, and concentration alerts."""

        alerts: list[RiskAlert] = []
        if equity_curve is not None and not equity_curve.empty:
            alerts.extend(self._drawdown_alerts(equity_curve))
        if returns is not None and not returns.empty:
            volatility = float(returns.std(ddof=0) * (252**0.5))
            if volatility > self.config.max_volatility:
                alerts.append(
                    RiskAlert(
                        code="volatility_too_high",
                        severity="warning",
                        message="年化波動率超過設定門檻。",
                        value=volatility,
                        threshold=self.config.max_volatility,
                    )
                )
        if trades is not None:
            consecutive_losses = _max_consecutive_losses(trades)
            if consecutive_losses >= self.config.max_consecutive_losses:
                alerts.append(
                    RiskAlert(
                        code="consecutive_losses",
                        severity="warning",
                        message="連續虧損交易次數達到設定門檻。",
                        value=float(consecutive_losses),
                        threshold=float(self.config.max_consecutive_losses),
                    )
                )
        if portfolio is not None:
            if portfolio.cash_ratio < self.config.min_cash_ratio:
                alerts.append(
                    RiskAlert(
                        code="cash_ratio_low",
                        severity="warning",
                        message="現金水位低於設定下限。",
                        value=portfolio.cash_ratio,
                        threshold=self.config.min_cash_ratio,
                    )
                )
            if industry_map is not None:
                alerts.extend(self._industry_alerts(portfolio, industry_map))
        return tuple(alerts)

    def _drawdown_alerts(self, equity_curve: pd.DataFrame) -> list[RiskAlert]:
        frame = equity_curve.copy(deep=True)
        if "total_equity" not in frame.columns:
            raise ValueError("equity_curve must contain total_equity.")
        equity = frame["total_equity"].astype(float)
        peak = equity.cummax()
        drawdown = (equity / peak.where(peak != 0)) - 1.0
        max_drawdown = float(drawdown.min())
        if abs(max_drawdown) > self.config.max_drawdown_pct:
            date = None
            if "date" in frame.columns:
                date = str(frame.loc[drawdown.idxmin(), "date"])
            return [
                RiskAlert(
                    code="max_drawdown_exceeded",
                    severity="critical",
                    message="最大回撤超過設定門檻。",
                    date=date,
                    value=abs(max_drawdown),
                    threshold=self.config.max_drawdown_pct,
                )
            ]
        return []

    def _industry_concentration_alert(
        self,
        *,
        portfolio: Portfolio,
        symbol: str,
        industry: str | None,
        industry_map: Mapping[str, str] | None,
        added_value: float,
    ) -> RiskAlert | None:
        resolved_industry = industry or (industry_map or {}).get(symbol)
        if resolved_industry is None:
            return None
        industry_values = _industry_values(portfolio, industry_map or {})
        industry_values[resolved_industry] = (
            industry_values.get(resolved_industry, 0.0) + added_value
        )
        equity = portfolio.total_equity
        pct = industry_values[resolved_industry] / equity if equity > 0 else 1.0
        if pct > self.config.max_industry_pct:
            return RiskAlert(
                code="industry_concentration_exceeded",
                severity="critical",
                message="預計買入會超過產業集中度限制。",
                symbol=symbol,
                value=pct,
                threshold=self.config.max_industry_pct,
            )
        return None

    def _industry_alerts(
        self,
        portfolio: Portfolio,
        industry_map: Mapping[str, str],
    ) -> list[RiskAlert]:
        alerts: list[RiskAlert] = []
        equity = portfolio.total_equity
        if equity <= 0:
            return alerts
        for industry, value in _industry_values(portfolio, industry_map).items():
            pct = value / equity
            if pct > self.config.max_industry_pct:
                alerts.append(
                    RiskAlert(
                        code="industry_concentration_exceeded",
                        severity="warning",
                        message="產業曝險超過設定限制。",
                        value=pct,
                        threshold=self.config.max_industry_pct,
                    )
                )
        return alerts


def _validate_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} 必須大於 0。")


def _suggest_adjusted_buy_quantity(
    *,
    portfolio: Portfolio,
    symbol: str,
    price: float,
    quantity: int,
    max_position_pct: float,
    min_cash_ratio: float,
) -> int | None:
    equity = portfolio.total_equity
    cash = float(portfolio.cash or 0.0)
    if equity <= 0 or price <= 0:
        return None

    position = portfolio.positions.get(symbol)
    current_value = 0.0 if position is None else position.market_value
    max_position_value = max((equity * max_position_pct) - current_value, 0.0)
    max_cash_value = max(cash - (equity * min_cash_ratio), 0.0)
    adjusted = min(quantity, floor(max_position_value / price), floor(max_cash_value / price))
    return max(adjusted, 0)


def _industry_values(
    portfolio: Portfolio,
    industry_map: Mapping[str, str],
) -> dict[str, float]:
    values: dict[str, float] = {}
    for symbol, position in portfolio.positions.items():
        industry = industry_map.get(symbol)
        if industry is None:
            continue
        values[industry] = values.get(industry, 0.0) + position.market_value
    return values


def _max_consecutive_losses(trades: Sequence[Any]) -> int:
    max_losses = 0
    current_losses = 0
    for trade in trades:
        pnl = getattr(trade, "realized_pnl", None)
        if pnl is None:
            continue
        if pnl < 0:
            current_losses += 1
            max_losses = max(max_losses, current_losses)
        else:
            current_losses = 0
    return max_losses
