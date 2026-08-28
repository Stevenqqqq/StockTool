"""Backtesting engine enforcing next-bar execution and portfolio accounting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from math import floor
from typing import Any, Mapping, Sequence, cast

import pandas as pd

from stock_tool.backtest.broker import BrokerConfig, BrokerSimulator
from stock_tool.backtest.metrics import PerformanceMetrics
from stock_tool.backtest.orders import Order, OrderSide, Trade
from stock_tool.backtest.portfolio import Portfolio, PortfolioSnapshot
from stock_tool.data.corporate_actions import (
    AdjustedSeriesContract,
    CorporateAction,
    CorporateActionType,
    PricePolicy,
    ReturnBasis,
)
from stock_tool.domain.models import Market
from stock_tool.data.universe import HistoricalUniverse, survivorship_bias_warnings
from stock_tool.risk import RiskConfig, RiskDecision, RiskManager

TRAILING_STOP_DAILY_MODEL_NOTICE = (
    "Trailing stop uses a conservative daily model: the highest close is updated after each "
    "completed daily bar, trigger checks use the same day's close, and exit orders can execute "
    "no earlier than the next bar using the configured execution price model."
)


@dataclass(frozen=True)
class BacktestResult:
    """Complete result of a backtest run."""

    portfolio: Portfolio
    orders: list[Order]
    trades: list[Trade]
    rejected_orders: list[Order]
    equity_curve: pd.DataFrame
    positions_history: pd.DataFrame
    metrics: PerformanceMetrics
    warnings: tuple[str, ...] = ()
    corporate_action_audit: pd.DataFrame = field(default_factory=pd.DataFrame)
    daily_reconciliation: pd.DataFrame = field(default_factory=pd.DataFrame)
    price_policy: str = PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS.value
    return_basis: str = ReturnBasis.PRICE_RETURN.value


class BacktestEngine:
    """Run research backtests with strict T+1 execution.

    Signals produced on date T are converted to simulated orders after that
    date's execution phase has already passed. The earliest possible fill is
    therefore the next available bar for the same symbol.
    """

    def __init__(
        self,
        *,
        initial_cash: float = 1_000_000.0,
        broker: BrokerSimulator | None = None,
        broker_config: BrokerConfig | None = None,
        max_position_pct: float | None = None,
        max_positions: int | None = None,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        trailing_stop_pct: float | None = None,
        trailing_take_profit_pct: float | None = None,
        mark_price_col: str = "close",
        risk_manager: RiskManager | None = None,
        risk_config: RiskConfig | None = None,
        industry_map: Mapping[str, str] | None = None,
        point_in_time_mode: str = "legacy",
        historical_universe: HistoricalUniverse | None = None,
        corporate_actions: Sequence[CorporateAction] | None = None,
        price_policy: PricePolicy | str = PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
        return_basis: ReturnBasis | str = ReturnBasis.PRICE_RETURN,
        benchmark_return_basis: ReturnBasis | str | None = None,
        benchmark_price_policy: PricePolicy | str | None = None,
        benchmark_source: str | None = None,
        adjusted_series_contract: AdjustedSeriesContract | None = None,
    ) -> None:
        if initial_cash <= 0:
            raise ValueError("initial_cash 必須大於 0。")
        if max_position_pct is not None and not 0 < max_position_pct <= 1:
            raise ValueError("max_position_pct 必須介於 0 到 1 之間。")
        if max_positions is not None and max_positions <= 0:
            raise ValueError("max_positions 必須大於 0。")
        if stop_loss_pct is not None and not 0 < stop_loss_pct < 1:
            raise ValueError("stop_loss_pct 必須介於 0 到 1 之間。")
        if take_profit_pct is not None and take_profit_pct <= 0:
            raise ValueError("take_profit_pct 必須大於 0。")
        if trailing_stop_pct is not None and not 0 < trailing_stop_pct < 1:
            raise ValueError("trailing_stop_pct 必須介於 0 到 1 之間。")
        if trailing_take_profit_pct is not None and not 0 < trailing_take_profit_pct < 1:
            raise ValueError("trailing_take_profit_pct 必須介於 0 到 1 之間。")
        if trailing_stop_pct is not None and trailing_take_profit_pct is not None:
            raise ValueError("trailing_stop_pct 與 trailing_take_profit_pct 只能擇一設定。")
        if risk_manager is not None and risk_config is not None:
            raise ValueError("risk_manager 與 risk_config 只能擇一設定。")

        if point_in_time_mode not in {"legacy", "strict"}:
            raise ValueError("point_in_time_mode must be legacy or strict")
        try:
            resolved_price_policy = PricePolicy(str(price_policy))
        except ValueError as exc:
            raise ValueError("unsupported price policy") from exc
        try:
            resolved_return_basis = ReturnBasis(str(return_basis))
        except ValueError as exc:
            raise ValueError("unsupported return basis") from exc
        resolved_actions = tuple(corporate_actions or ())
        if resolved_actions and resolved_price_policy is PricePolicy.UNKNOWN:
            raise ValueError("price policy is unknown; corporate actions cannot be applied")
        if resolved_actions and resolved_price_policy is PricePolicy.ADJUSTED_TOTAL_RETURN:
            raise ValueError(
                "adjusted total-return prices plus explicit corporate actions would double-count"
            )
        if (
            resolved_price_policy is PricePolicy.ADJUSTED_TOTAL_RETURN
            and resolved_return_basis is not ReturnBasis.TOTAL_RETURN
        ):
            raise ValueError("adjusted total-return prices require total_return")
        if (
            resolved_price_policy is PricePolicy.ADJUSTED_TOTAL_RETURN
            and adjusted_series_contract is None
        ):
            raise ValueError(
                "adjusted series contract is required for adjusted total-return prices"
            )
        if any(
            action.kind is CorporateActionType.CASH_DIVIDEND for action in resolved_actions
        ) and (resolved_return_basis is not ReturnBasis.TOTAL_RETURN):
            raise ValueError("cash dividends require total_return")
        if benchmark_return_basis is not None:
            try:
                benchmark_return_basis = ReturnBasis(str(benchmark_return_basis))
            except ValueError as exc:
                raise ValueError("unsupported benchmark return basis") from exc
        if benchmark_price_policy is not None:
            try:
                benchmark_price_policy = PricePolicy(str(benchmark_price_policy))
            except ValueError as exc:
                raise ValueError("unsupported benchmark price policy") from exc

        self.initial_cash = initial_cash
        if resolved_price_policy is PricePolicy.ADJUSTED_TOTAL_RETURN:
            if broker is not None and broker.config.execution_price_col != "adjusted_close":
                raise ValueError("adjusted total-return prices require adjusted_close execution")
            adjusted_broker_config = replace(
                broker_config or BrokerConfig(), execution_price_col="adjusted_close"
            )
            self.broker = broker or BrokerSimulator(adjusted_broker_config)
        else:
            self.broker = broker or BrokerSimulator(broker_config)
        self.max_position_pct = max_position_pct
        self.max_positions = max_positions
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = (
            trailing_stop_pct if trailing_stop_pct is not None else trailing_take_profit_pct
        )
        self.mark_price_col = (
            "adjusted_close"
            if resolved_price_policy is PricePolicy.ADJUSTED_TOTAL_RETURN
            else mark_price_col
        )
        self.risk_manager = risk_manager or RiskManager(
            risk_config or _permissive_risk_config(max_position_pct, max_positions)
        )
        self.industry_map = dict(industry_map or {})
        self.point_in_time_mode = point_in_time_mode
        self.historical_universe = historical_universe
        self.corporate_actions = resolved_actions
        self.price_policy = resolved_price_policy
        self.return_basis = resolved_return_basis
        self.benchmark_return_basis = benchmark_return_basis
        self.benchmark_price_policy = benchmark_price_policy
        self.benchmark_source = benchmark_source
        self.adjusted_series_contract = adjusted_series_contract
        self._next_order_id = 1

    def run(
        self,
        price_data: pd.DataFrame,
        signals: pd.DataFrame | Sequence[Order] | None = None,
        *,
        benchmark: pd.DataFrame | None = None,
    ) -> BacktestResult:
        """Run a backtest from OHLCV price data and optional strategy signals.

        Signal DataFrame columns can use either ``action`` (``buy``/``sell``)
        or numeric ``signal`` (``1``/``0``/``-1``). Optional sizing columns are
        ``quantity``, ``cash_amount``, ``target_percent``, and ``reason``.
        """

        prices = _prepare_price_data(
            price_data, self.broker.config.execution_price_col, self.mark_price_col
        )
        actions, conflicting_actions, corporate_action_warnings = _prepare_corporate_actions(
            self.corporate_actions,
            prices,
        )
        if self.point_in_time_mode == "strict" and self.historical_universe is None:
            raise ValueError("strict point-in-time mode requires historical universe data")
        point_in_time_warnings = survivorship_bias_warnings(self.historical_universe)
        if self.point_in_time_mode == "legacy":
            point_in_time_warnings = (
                *point_in_time_warnings,
                "Legacy mode does not filter trading signals with the historical universe; "
                "survivorship bias may remain.",
            )
        signal_frame = _prepare_signal_data(signals)
        if self.point_in_time_mode == "strict" and self.historical_universe is not None:
            signal_frame, universe_warnings = _restrict_signals_to_historical_universe(
                signal_frame,
                self.historical_universe,
            )
            point_in_time_warnings = (*point_in_time_warnings, *universe_warnings)
        point_in_time_warnings = (*point_in_time_warnings, *corporate_action_warnings)

        portfolio = Portfolio(initial_cash=self.initial_cash)
        pending_orders: list[Order] = []
        all_orders: list[Order] = []
        trades: list[Trade] = []
        snapshots: list[PortfolioSnapshot] = []
        positions_rows: list[dict[str, Any]] = []
        reconciliation_rows: list[dict[str, Any]] = []
        corporate_action_audit_rows: list[dict[str, Any]] = []
        for conflict in conflicting_actions:
            _append_action_audit(
                corporate_action_audit_rows,
                action=conflict,
                price_policy=self.price_policy,
                return_basis=self.return_basis,
                status="unavailable",
                reason="conflicting sources reported different economic terms; no action applied",
            )
        trailing_high_closes: dict[str, float] = {}
        trailing_entry_dates: dict[str, str] = {}
        processed_effective_actions: set[str] = set()
        paid_actions: set[str] = set()
        dividend_entitlements: dict[str, int] = {}

        dates = list(prices["date"].drop_duplicates())
        for current_date in dates:
            day_prices = prices.loc[prices["date"] == current_date]
            rows_by_symbol = {str(row["symbol"]): row.to_dict() for _, row in day_prices.iterrows()}

            _apply_corporate_actions_for_date(
                current_date=current_date,
                rows_by_symbol=rows_by_symbol,
                portfolio=portfolio,
                actions=actions,
                processed_effective_actions=processed_effective_actions,
                paid_actions=paid_actions,
                dividend_entitlements=dividend_entitlements,
                audit_rows=corporate_action_audit_rows,
                price_policy=self.price_policy,
                return_basis=self.return_basis,
            )

            portfolio.update_market_prices(
                _prices_for_column(rows_by_symbol, self.broker.config.execution_price_col)
            )

            pending_orders = self._execute_pending_orders(
                pending_orders=pending_orders,
                current_date=current_date,
                rows_by_symbol=rows_by_symbol,
                portfolio=portfolio,
                trades=trades,
            )

            portfolio.update_market_prices(_prices_for_column(rows_by_symbol, self.mark_price_col))
            snapshot = portfolio.snapshot(current_date)
            snapshots.append(snapshot)
            reconciliation_rows.append(
                {
                    "date": current_date,
                    "cash": snapshot.cash,
                    "holdings_market_value": snapshot.market_value,
                    "total_equity": snapshot.total_equity,
                    "reconciled_equity": snapshot.cash + snapshot.market_value,
                    "difference": snapshot.total_equity - (snapshot.cash + snapshot.market_value),
                }
            )
            _sync_trailing_state(
                trailing_high_closes=trailing_high_closes,
                trailing_entry_dates=trailing_entry_dates,
                portfolio=portfolio,
            )

            new_orders = self._risk_orders_for_date(
                current_date=current_date,
                portfolio=portfolio,
                rows_by_symbol=rows_by_symbol,
                pending_orders=pending_orders,
                trailing_high_closes=trailing_high_closes,
            )
            positions_rows.extend(
                _position_rows(
                    current_date=current_date,
                    portfolio=portfolio,
                    trailing_high_closes=trailing_high_closes,
                )
            )
            new_orders.extend(self._signal_orders_for_date(signal_frame, current_date))
            pending_orders.extend(new_orders)
            all_orders.extend(new_orders)

        _finalize_unresolved_corporate_actions(
            actions=actions,
            processed_effective_actions=processed_effective_actions,
            paid_actions=paid_actions,
            dividend_entitlements=dividend_entitlements,
            audit_rows=corporate_action_audit_rows,
            price_policy=self.price_policy,
            return_basis=self.return_basis,
        )

        equity_curve = pd.DataFrame([asdict(snapshot) for snapshot in snapshots])
        positions_history = pd.DataFrame(positions_rows)
        metrics = PerformanceMetrics.calculate(
            equity_curve=equity_curve,
            trades=trades,
            initial_cash=self.initial_cash,
            benchmark=benchmark,
            strategy_return_basis=self.return_basis,
            benchmark_return_basis=(self.benchmark_return_basis or self.return_basis),
            benchmark_price_policy=self.benchmark_price_policy,
            benchmark_source=self.benchmark_source,
        )
        rejected_orders = [order for order in all_orders if order.status == "rejected"]

        return BacktestResult(
            portfolio=portfolio,
            orders=all_orders,
            trades=trades,
            rejected_orders=rejected_orders,
            equity_curve=equity_curve,
            positions_history=positions_history,
            metrics=metrics,
            warnings=point_in_time_warnings,
            corporate_action_audit=pd.DataFrame(corporate_action_audit_rows),
            daily_reconciliation=pd.DataFrame(reconciliation_rows),
            price_policy=self.price_policy.value,
            return_basis=self.return_basis.value,
        )

    def _execute_pending_orders(
        self,
        *,
        pending_orders: list[Order],
        current_date: str,
        rows_by_symbol: dict[str, dict[str, Any]],
        portfolio: Portfolio,
        trades: list[Trade],
    ) -> list[Order]:
        remaining: list[Order] = []
        current_timestamp = pd.Timestamp(current_date)

        for order in pending_orders:
            if pd.Timestamp(order.signal_date) >= current_timestamp:
                remaining.append(order)
                continue
            market_row = rows_by_symbol.get(order.symbol)
            if market_row is None:
                remaining.append(order)
                continue

            risk_decision = self._evaluate_order_risk(
                order=order,
                market_row=market_row,
                portfolio=portfolio,
            )
            if not risk_decision.allowed:
                order.reject(_risk_rejection_reason(risk_decision))
                continue

            trade = self.broker.execute_order(
                order,
                market_row,
                portfolio,
                max_position_pct=self.max_position_pct,
                max_positions=self.max_positions,
            )
            if trade is not None:
                trades.append(trade)

        return remaining

    def _evaluate_order_risk(
        self,
        *,
        order: Order,
        market_row: dict[str, Any],
        portfolio: Portfolio,
    ) -> RiskDecision:
        base_price = _optional_float(market_row.get(self.broker.config.execution_price_col))
        if base_price is None or base_price <= 0:
            return RiskDecision(
                allowed=False,
                alerts=(),
                reason=f"missing_or_invalid_execution_price:{self.broker.config.execution_price_col}",
            )

        fill_price = _risk_fill_price(
            base_price=base_price,
            side=order.side,
            slippage_rate=self.broker.config.slippage_rate,
        )
        quantity = _risk_order_quantity(
            order=order,
            portfolio=portfolio,
            fill_price=fill_price,
            max_position_pct=self.max_position_pct,
        )
        if quantity <= 0:
            return RiskDecision(
                allowed=False,
                alerts=(),
                adjusted_quantity=0,
                reason="resolved_order_quantity_is_zero",
            )

        if order.side == "buy":
            return self.risk_manager.evaluate_buy_order(
                portfolio=portfolio,
                symbol=order.symbol,
                price=fill_price,
                quantity=quantity,
                stop_loss_pct=self.stop_loss_pct,
                industry_map=self.industry_map,
            )
        return self.risk_manager.evaluate_sell_order(
            portfolio=portfolio,
            symbol=order.symbol,
            quantity=quantity,
        )

    def _signal_orders_for_date(self, signals: pd.DataFrame, current_date: str) -> list[Order]:
        if signals.empty:
            return []

        today = signals.loc[signals["date"] == current_date]
        orders: list[Order] = []
        for _, signal in today.iterrows():
            orders.append(
                self._new_order(
                    symbol=str(signal["symbol"]),
                    side=cast(OrderSide, str(signal["action"])),
                    signal_date=current_date,
                    quantity=_optional_int(signal.get("quantity")),
                    cash_amount=_optional_float(signal.get("cash_amount")),
                    target_percent=_optional_float(signal.get("target_percent")),
                    reason=str(signal.get("reason") or "signal"),
                )
            )
        return orders

    def _risk_orders_for_date(
        self,
        *,
        current_date: str,
        portfolio: Portfolio,
        rows_by_symbol: dict[str, dict[str, Any]],
        pending_orders: list[Order],
        trailing_high_closes: dict[str, float],
    ) -> list[Order]:
        if (
            self.stop_loss_pct is None
            and self.take_profit_pct is None
            and self.trailing_stop_pct is None
        ):
            return []

        orders: list[Order] = []
        for symbol, position in list(portfolio.positions.items()):
            if _has_pending_exit(symbol, pending_orders):
                continue
            row = rows_by_symbol.get(symbol)
            if row is None:
                continue
            mark_price = _optional_float(row.get(self.mark_price_col))
            if mark_price is None:
                continue

            if self.stop_loss_pct is not None:
                stop_price = position.average_cost * (1.0 - self.stop_loss_pct)
                if mark_price <= stop_price:
                    orders.append(
                        self._new_order(
                            symbol=symbol,
                            side="sell",
                            signal_date=current_date,
                            quantity=position.quantity,
                            reason="stop_loss",
                        )
                    )
                    continue

            if self.take_profit_pct is not None:
                take_profit_price = position.average_cost * (1.0 + self.take_profit_pct)
                if mark_price >= take_profit_price:
                    orders.append(
                        self._new_order(
                            symbol=symbol,
                            side="sell",
                            signal_date=current_date,
                            quantity=position.quantity,
                            reason="take_profit",
                        )
                    )
                    continue

            if self.trailing_stop_pct is not None:
                highest_close = max(trailing_high_closes.get(symbol, mark_price), mark_price)
                trailing_high_closes[symbol] = highest_close
                trigger_price = highest_close * (1.0 - self.trailing_stop_pct)
                if mark_price <= trigger_price and mark_price < highest_close:
                    orders.append(
                        self._new_order(
                            symbol=symbol,
                            side="sell",
                            signal_date=current_date,
                            quantity=position.quantity,
                            reason="trailing_stop",
                        )
                    )

        return orders

    def _new_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        signal_date: str,
        quantity: int | None = None,
        cash_amount: float | None = None,
        target_percent: float | None = None,
        reason: str = "signal",
    ) -> Order:
        order = Order(
            order_id=self._next_order_id,
            symbol=str(symbol),
            side=side,
            signal_date=signal_date,
            quantity=quantity,
            cash_amount=cash_amount,
            target_percent=target_percent,
            reason=reason,
        )
        self._next_order_id += 1
        return order


def _prepare_corporate_actions(
    actions: Sequence[CorporateAction],
    prices: pd.DataFrame,
) -> tuple[tuple[CorporateAction, ...], tuple[CorporateAction, ...], tuple[str, ...]]:
    """Validate identity and consolidate only equivalent source observations."""

    if not actions:
        return (), (), ()
    if "market" not in prices.columns:
        raise ValueError("corporate actions require market-qualified price data")
    for value in prices["market"].dropna().astype(str):
        Market.parse(value)
    duplicate_symbol_dates = prices.groupby(["date", "symbol"], dropna=False)["market"].nunique()
    if (duplicate_symbol_dates > 1).any():
        raise ValueError(
            "corporate actions cannot safely process duplicate symbol/date rows across markets"
        )
    markets_by_symbol: dict[str, set[Market]] = {}
    for symbol, group in prices.groupby("symbol", dropna=False):
        markets_by_symbol[str(symbol)] = {Market.parse(str(value)) for value in group["market"]}
    for action in actions:
        observed_markets = markets_by_symbol.get(action.symbol.code, set())
        if observed_markets != {action.symbol.market}:
            observed = ", ".join(sorted(market.value for market in observed_markets)) or "none"
            raise ValueError(
                "corporate action market identity ambiguity for "
                f"{action.symbol.code}: expected {action.symbol.market.value}, observed {observed}"
            )

    grouped: dict[str, list[CorporateAction]] = {}
    for action in sorted(actions, key=lambda item: (item.effective_date, item.event_id)):
        grouped.setdefault(action.economic_event_key, []).append(action)

    prepared: list[CorporateAction] = []
    conflicts: list[CorporateAction] = []
    warnings: list[str] = []
    for event_key, group in grouped.items():
        term_groups = {action.economic_terms_key for action in group}
        if len(term_groups) > 1:
            conflicts.extend(group)
            warnings.append(
                f"Corporate action {event_key} has conflicting sources; no action was applied."
            )
            continue
        evidence = _source_evidence(group)
        representative = group[0]
        available_dates = [
            action.available_date for action in group if action.available_date is not None
        ]
        representative = replace(
            representative,
            available_date=min(available_dates) if available_dates else None,
            source_evidence=evidence,
        )
        if len(evidence) > 1:
            warnings.append(
                f"Equivalent corporate action {event_key} was consolidated from multiple sources."
            )
        prepared.append(representative)
    return tuple(prepared), tuple(conflicts), tuple(warnings)


def _source_evidence(actions: Sequence[CorporateAction]) -> tuple[Mapping[str, Any], ...]:
    """Collect source records without treating provenance as economic terms."""

    evidence: dict[str, Mapping[str, Any]] = {}
    for action in actions:
        for item in (*action.source_evidence, action.evidence_record()):
            event_id = str(item.get("event_id", ""))
            if event_id:
                evidence[event_id] = dict(item)
    return tuple(evidence[key] for key in sorted(evidence))


def _apply_corporate_actions_for_date(
    *,
    current_date: str,
    rows_by_symbol: Mapping[str, Mapping[str, Any]],
    portfolio: Portfolio,
    actions: Sequence[CorporateAction],
    processed_effective_actions: set[str],
    paid_actions: set[str],
    dividend_entitlements: dict[str, int],
    audit_rows: list[dict[str, Any]],
    price_policy: PricePolicy,
    return_basis: ReturnBasis,
) -> None:
    """Apply known actions before the day's pending orders and marking phase."""

    for action in actions:
        event_id = action.event_id
        if action.effective_date != current_date or event_id in processed_effective_actions:
            continue
        processed_effective_actions.add(event_id)
        row = _action_market_row(action, rows_by_symbol)
        if row is None:
            _append_action_audit(
                audit_rows,
                action=action,
                price_policy=price_policy,
                return_basis=return_basis,
                status="unavailable",
                reason="market-qualified price identity unavailable on effective_date",
            )
            continue
        if not action.is_available_on(current_date):
            _append_action_audit(
                audit_rows,
                action=action,
                price_policy=price_policy,
                return_basis=return_basis,
                status="unavailable",
                reason="available_date is missing or later than effective_date",
            )
            continue
        position = portfolio.positions.get(action.symbol.code)
        if position is None:
            _append_action_audit(
                audit_rows,
                action=action,
                price_policy=price_policy,
                return_basis=return_basis,
                status="unavailable",
                reason="no eligible position at prior trading-day close",
            )
            continue
        if action.kind is CorporateActionType.SPLIT:
            _apply_split_action(
                action=action,
                portfolio=portfolio,
                price_policy=price_policy,
                return_basis=return_basis,
                audit_rows=audit_rows,
            )
            continue
        if action.payable_date is None:
            _append_action_audit(
                audit_rows,
                action=action,
                price_policy=price_policy,
                return_basis=return_basis,
                status="unavailable",
                reason="payable_date is required for the conservative cash-dividend model",
                position=position,
            )
            continue
        dividend_entitlements[event_id] = position.quantity

    for action in actions:
        event_id = action.event_id
        if (
            action.kind is not CorporateActionType.CASH_DIVIDEND
            or action.payable_date != current_date
            or event_id not in dividend_entitlements
            or event_id in paid_actions
        ):
            continue
        quantity = dividend_entitlements[event_id]
        gross_cash = quantity * float(action.cash_per_share or 0.0)
        tax = gross_cash * float(action.tax_rate or 0.0)
        net_cash = gross_cash - tax
        position = portfolio.positions.get(action.symbol.code)
        quantity_after = None if position is None else position.quantity
        average_cost_after = None if position is None else position.average_cost
        portfolio.credit_cash(net_cash)
        paid_actions.add(event_id)
        _append_action_audit(
            audit_rows,
            action=action,
            price_policy=price_policy,
            return_basis=return_basis,
            status="applied",
            reason="cash dividend credited on payable_date",
            quantity_before=quantity,
            quantity_after=quantity_after,
            average_cost_before=average_cost_after,
            average_cost_after=average_cost_after,
            gross_cash_delta=gross_cash,
            tax=tax,
            net_cash_delta=net_cash,
        )


def _apply_split_action(
    *,
    action: CorporateAction,
    portfolio: Portfolio,
    price_policy: PricePolicy,
    return_basis: ReturnBasis,
    audit_rows: list[dict[str, Any]],
) -> None:
    """Apply an integral split without changing cost basis or cash."""

    position = portfolio.positions[action.symbol.code]
    quantity_before = position.quantity
    average_cost_before = position.average_cost
    split_ratio = float(action.split_ratio or 0.0)
    quantity_after_float = quantity_before * split_ratio
    if not quantity_after_float.is_integer():
        _append_action_audit(
            audit_rows,
            action=action,
            price_policy=price_policy,
            return_basis=return_basis,
            status="unavailable",
            reason="fractional split quantity is unsupported; no rounding was applied",
            position=position,
        )
        return
    position.quantity = int(quantity_after_float)
    position.average_cost = average_cost_before / split_ratio
    _append_action_audit(
        audit_rows,
        action=action,
        price_policy=price_policy,
        return_basis=return_basis,
        status="applied",
        reason="split applied before daily trading",
        quantity_before=quantity_before,
        quantity_after=position.quantity,
        average_cost_before=average_cost_before,
        average_cost_after=position.average_cost,
    )


def _action_market_row(
    action: CorporateAction,
    rows_by_symbol: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Return a price row only when its known market matches the action identity."""

    row = rows_by_symbol.get(action.symbol.code)
    if row is None:
        return None
    try:
        row_market = Market.parse(str(row.get("market", "")))
    except ValueError:
        return None
    return row if row_market is action.symbol.market else None


def _finalize_unresolved_corporate_actions(
    *,
    actions: Sequence[CorporateAction],
    processed_effective_actions: set[str],
    paid_actions: set[str],
    dividend_entitlements: Mapping[str, int],
    audit_rows: list[dict[str, Any]],
    price_policy: PricePolicy,
    return_basis: ReturnBasis,
) -> None:
    """Record explicit unavailable outcomes for action dates absent from the price range."""

    for action in actions:
        event_id = action.event_id
        if event_id not in processed_effective_actions:
            _append_action_audit(
                audit_rows,
                action=action,
                price_policy=price_policy,
                return_basis=return_basis,
                status="unavailable",
                reason="effective_date is not present in the price series",
            )
        elif (
            action.kind is CorporateActionType.CASH_DIVIDEND
            and event_id in dividend_entitlements
            and event_id not in paid_actions
        ):
            _append_action_audit(
                audit_rows,
                action=action,
                price_policy=price_policy,
                return_basis=return_basis,
                status="unavailable",
                reason="payable_date is not present in the price series",
                quantity_before=dividend_entitlements[event_id],
                quantity_after=dividend_entitlements[event_id],
            )


def _append_action_audit(
    audit_rows: list[dict[str, Any]],
    *,
    action: CorporateAction,
    price_policy: PricePolicy,
    return_basis: ReturnBasis,
    status: str,
    reason: str,
    position: Any | None = None,
    quantity_before: int | None = None,
    quantity_after: int | None = None,
    average_cost_before: float | None = None,
    average_cost_after: float | None = None,
    gross_cash_delta: float = 0.0,
    tax: float = 0.0,
    net_cash_delta: float = 0.0,
) -> None:
    """Append a complete, source-backed action audit row."""

    if position is not None:
        quantity_before = position.quantity if quantity_before is None else quantity_before
        quantity_after = position.quantity if quantity_after is None else quantity_after
        average_cost_before = (
            position.average_cost if average_cost_before is None else average_cost_before
        )
        average_cost_after = (
            position.average_cost if average_cost_after is None else average_cost_after
        )
    audit_rows.append(
        {
            "event_id": action.event_id,
            "symbol": action.symbol.code,
            "market": action.symbol.market.value,
            "action_type": action.kind.value,
            "event_date": action.effective_date,
            "available_date": action.available_date,
            "payable_date": action.payable_date,
            "source": action.source,
            "source_evidence": tuple(
                str(item.get("source", ""))
                for item in (action.source_evidence or (action.evidence_record(),))
            ),
            "price_policy": price_policy.value,
            "return_basis": return_basis.value,
            "quantity_before": quantity_before,
            "quantity_after": quantity_after,
            "average_cost_before": average_cost_before,
            "average_cost_after": average_cost_after,
            "gross_cash_delta": gross_cash_delta,
            "tax": tax,
            "net_cash_delta": net_cash_delta,
            "status": status,
            "reason": reason,
        }
    )


def _prepare_price_data(
    price_data: pd.DataFrame,
    execution_price_col: str,
    mark_price_col: str,
) -> pd.DataFrame:
    required = {"date", "symbol", execution_price_col, mark_price_col}
    missing = sorted(required - set(price_data.columns))
    if missing:
        raise ValueError(f"price_data 缺少必要欄位：{', '.join(missing)}")

    prices = price_data.copy(deep=True)
    prices["date"] = pd.to_datetime(prices["date"]).dt.strftime("%Y-%m-%d")
    prices["symbol"] = prices["symbol"].astype(str)
    prices = prices.sort_values(["date", "symbol"], kind="mergesort").reset_index(drop=True)
    return prices


def _restrict_signals_to_historical_universe(
    signals: pd.DataFrame,
    universe: HistoricalUniverse,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Fail closed when a strict signal lacks one unambiguous historical membership."""

    if signals.empty:
        return signals.copy(deep=True), ()

    allowed_rows: list[int] = []
    warnings: list[str] = []
    for index, row in signals.iterrows():
        candidates = [
            membership
            for membership in universe.members_as_of(str(row["date"]))
            if membership.symbol.code == str(row["symbol"]).strip().upper()
        ]
        if len(candidates) == 1:
            allowed_rows.append(index)
        elif len(candidates) == 0:
            warnings.append(
                f"Strict point-in-time mode skipped {row['symbol']} on {row['date']}: "
                "no historical-universe membership was available."
            )
        else:
            warnings.append(
                f"Strict point-in-time mode skipped {row['symbol']} on {row['date']}: "
                "market identity was ambiguous."
            )
    return signals.loc[allowed_rows].copy(), tuple(dict.fromkeys(warnings))


def _prepare_signal_data(signals: pd.DataFrame | Sequence[Order] | None) -> pd.DataFrame:
    columns = [
        "date",
        "symbol",
        "action",
        "signal",
        "quantity",
        "cash_amount",
        "target_percent",
        "reason",
    ]
    if signals is None:
        return pd.DataFrame(columns=columns)

    if isinstance(signals, pd.DataFrame):
        frame = signals.copy(deep=True)
    else:
        frame = pd.DataFrame(
            [
                {
                    "date": order.signal_date,
                    "symbol": order.symbol,
                    "action": order.side,
                    "signal": 1 if order.side == "buy" else -1,
                    "quantity": order.quantity,
                    "cash_amount": order.cash_amount,
                    "target_percent": order.target_percent,
                    "reason": order.reason,
                }
                for order in signals
            ]
        )

    if frame.empty:
        return pd.DataFrame(columns=columns)
    required_action_or_signal = "action" in frame.columns or "signal" in frame.columns
    missing_base = sorted({"date", "symbol"} - set(frame.columns))
    missing = missing_base if required_action_or_signal else [*missing_base, "action or signal"]
    if missing:
        raise ValueError(f"signals 缺少必要欄位：{', '.join(missing)}")

    if "action" not in frame.columns:
        signal_values = frame["signal"].fillna(0).astype(int)
        invalid = sorted(set(signal_values) - {-1, 0, 1})
        if invalid:
            raise ValueError(f"signals.signal 只能包含 -1、0 或 1；收到：{invalid}")
        frame = frame.loc[signal_values != 0].copy()
        frame["signal"] = signal_values.loc[signal_values != 0]
        frame["action"] = frame["signal"].map({1: "buy", -1: "sell"})
    elif "signal" not in frame.columns:
        action_values = frame["action"].astype(str).str.lower()
        frame["signal"] = action_values.map({"buy": 1, "sell": -1})

    for column in columns:
        if column not in frame.columns:
            frame[column] = None

    if frame.empty:
        return pd.DataFrame(columns=columns)

    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    frame["symbol"] = frame["symbol"].astype(str)
    frame["action"] = frame["action"].astype(str).str.lower()
    invalid_actions = sorted(set(frame["action"]) - {"buy", "sell"})
    if invalid_actions:
        raise ValueError(f"signals.action 只能包含 buy 或 sell；收到：{invalid_actions}")
    return frame.sort_values(["date", "symbol"], kind="mergesort").reset_index(drop=True)


def _prices_for_column(
    rows_by_symbol: dict[str, dict[str, Any]],
    price_col: str,
) -> dict[str, float]:
    prices: dict[str, float] = {}
    for symbol, row in rows_by_symbol.items():
        value = _optional_float(row.get(price_col))
        if value is not None and value > 0:
            prices[symbol] = value
    return prices


def _position_rows(
    *,
    current_date: str,
    portfolio: Portfolio,
    trailing_high_closes: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total_equity = portfolio.total_equity
    for position in portfolio.positions.values():
        market_value = position.market_value
        rows.append(
            {
                "date": current_date,
                "symbol": position.symbol,
                "quantity": position.quantity,
                "average_cost": position.average_cost,
                "last_price": position.last_price,
                "trailing_high_close": (
                    None
                    if trailing_high_closes is None
                    else trailing_high_closes.get(position.symbol)
                ),
                "market_value": market_value,
                "weight": 0.0 if total_equity <= 0 else market_value / total_equity,
            }
        )
    return rows


def _sync_trailing_state(
    *,
    trailing_high_closes: dict[str, float],
    trailing_entry_dates: dict[str, str],
    portfolio: Portfolio,
) -> None:
    open_symbols = set(portfolio.positions)
    for symbol in list(trailing_high_closes):
        if symbol not in open_symbols:
            trailing_high_closes.pop(symbol, None)
            trailing_entry_dates.pop(symbol, None)

    for symbol, position in portfolio.positions.items():
        if trailing_entry_dates.get(symbol) != position.entry_date:
            trailing_entry_dates[symbol] = position.entry_date
            trailing_high_closes.pop(symbol, None)


def _has_pending_exit(symbol: str, pending_orders: Sequence[Order]) -> bool:
    return any(order.symbol == symbol and order.side == "sell" for order in pending_orders)


def _optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    number = _optional_float(value)
    if number is None:
        return None
    return int(number)


def _risk_fill_price(*, base_price: float, side: str, slippage_rate: float) -> float:
    if side == "buy":
        return base_price * (1.0 + slippage_rate)
    return base_price * (1.0 - slippage_rate)


def _risk_order_quantity(
    *,
    order: Order,
    portfolio: Portfolio,
    fill_price: float,
    max_position_pct: float | None,
) -> int:
    if order.side == "sell":
        position = portfolio.positions.get(order.symbol)
        if position is None:
            return int(order.quantity or 0)
        if order.target_percent is not None:
            target_value = portfolio.total_equity * order.target_percent
            current_value = position.quantity * fill_price
            return floor(max(current_value - target_value, 0.0) / fill_price)
        return int(order.quantity or position.quantity)

    if order.target_percent is not None:
        target_value = portfolio.total_equity * order.target_percent
        position = portfolio.positions.get(order.symbol)
        current_value = 0.0 if position is None else position.quantity * fill_price
        raw_quantity = floor(max(target_value - current_value, 0.0) / fill_price)
    elif order.cash_amount is not None:
        raw_quantity = floor(order.cash_amount / max(fill_price, 1e-12))
    else:
        raw_quantity = int(order.quantity or 0)

    if raw_quantity <= 0:
        return 0

    if max_position_pct is not None:
        position = portfolio.positions.get(order.symbol)
        current_quantity = 0 if position is None else position.quantity
        current_value = current_quantity * fill_price
        max_value = portfolio.total_equity * max_position_pct
        additional_value = max(max_value - current_value, 0.0)
        raw_quantity = min(raw_quantity, floor(additional_value / fill_price))

    return max(raw_quantity, 0)


def _permissive_risk_config(
    max_position_pct: float | None,
    max_positions: int | None,
) -> RiskConfig:
    position_pct = 0.999999 if max_position_pct is None else min(max_position_pct, 0.999999)
    return RiskConfig(
        max_position_pct=position_pct,
        max_trade_loss_pct=0.999999,
        max_positions=max_positions or 1_000_000,
        min_cash_ratio=0.0,
        max_drawdown_pct=0.999999,
        max_volatility=1_000_000.0,
        max_consecutive_losses=1_000_000,
        max_industry_pct=0.999999,
        default_stop_loss_pct=0.999999,
    )


def _risk_rejection_reason(decision: RiskDecision) -> str:
    reason = decision.reason or "blocked"
    if reason == "max_positions_exceeded":
        return "已達最大持股數限制"
    return f"風控拒絕：{reason}"
