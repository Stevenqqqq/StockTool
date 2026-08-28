"""Performance metrics for research backtests."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Sequence

import pandas as pd

from stock_tool.backtest.orders import Trade
from stock_tool.data.corporate_actions import PricePolicy, ReturnBasis


@dataclass(frozen=True)
class PerformanceMetrics:
    """Summary statistics derived from equity curve and trades."""

    total_return: float
    cagr: float
    annualized_volatility: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown: float
    win_rate: float
    profit_factor: float | None
    average_holding_period: float | None
    number_of_trades: int
    exposure: float
    benchmark_total_return: float | None = None
    benchmark_max_drawdown: float | None = None
    benchmark_excess_return: float | None = None
    benchmark_aligned_start_date: str | None = None
    benchmark_aligned_end_date: str | None = None
    benchmark_observations: int = 0
    benchmark_missing_reason: str | None = None

    @classmethod
    def calculate(
        cls: type[PerformanceMetrics],
        equity_curve: pd.DataFrame,
        trades: Sequence[Trade],
        *,
        initial_cash: float,
        benchmark: pd.DataFrame | None = None,
        risk_free_rate: float = 0.0,
        trading_days: int = 252,
        strategy_return_basis: ReturnBasis | str | None = None,
        benchmark_return_basis: ReturnBasis | str | None = None,
        benchmark_price_policy: PricePolicy | str | None = None,
        benchmark_source: str | None = None,
    ) -> "PerformanceMetrics":
        """Calculate backtest performance metrics.

        ``max_drawdown`` is returned as a negative number, for example
        ``-0.25`` means a 25% drawdown from the prior equity peak.
        """

        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive.")
        if trading_days <= 0:
            raise ValueError("trading_days must be positive.")
        if equity_curve.empty:
            return cls(
                total_return=0.0,
                cagr=0.0,
                annualized_volatility=0.0,
                sharpe_ratio=None,
                sortino_ratio=None,
                max_drawdown=0.0,
                win_rate=0.0,
                profit_factor=None,
                average_holding_period=None,
                number_of_trades=len(trades),
                exposure=0.0,
            )

        curve = equity_curve.copy()
        curve["date"] = _normalize_trade_dates(curve["date"])
        curve = curve.sort_values("date")
        equity = curve["total_equity"].astype(float)
        returns = equity.pct_change().dropna()

        ending_equity = float(equity.iloc[-1])
        total_return = (ending_equity / initial_cash) - 1.0
        cagr = _calculate_cagr(
            total_return=total_return,
            start_date=curve["date"].iloc[0],
            end_date=curve["date"].iloc[-1],
        )
        annualized_volatility = (
            float(returns.std(ddof=0) * sqrt(trading_days)) if len(returns) else 0.0
        )
        sharpe_ratio = _calculate_sharpe_ratio(
            returns=returns,
            risk_free_rate=risk_free_rate,
            trading_days=trading_days,
        )
        sortino_ratio = _calculate_sortino_ratio(
            returns=returns,
            risk_free_rate=risk_free_rate,
            trading_days=trading_days,
        )
        max_drawdown = _calculate_max_drawdown(equity)
        win_rate, profit_factor, average_holding_period = _trade_metrics(trades)
        exposure = (
            float(
                (
                    curve["market_value"] / curve["total_equity"].where(curve["total_equity"] != 0)
                ).mean()
            )
            if "market_value" in curve.columns
            else 0.0
        )
        comparison = calculate_benchmark_comparison(
            curve,
            benchmark,
            strategy_total_return=total_return,
            strategy_return_basis=strategy_return_basis,
            benchmark_return_basis=benchmark_return_basis,
            benchmark_price_policy=benchmark_price_policy,
            benchmark_source=benchmark_source,
        )

        return cls(
            total_return=total_return,
            cagr=cagr,
            annualized_volatility=annualized_volatility,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            average_holding_period=average_holding_period,
            number_of_trades=len(trades),
            exposure=exposure,
            benchmark_total_return=comparison.total_return,
            benchmark_max_drawdown=comparison.max_drawdown,
            benchmark_excess_return=comparison.excess_return,
            benchmark_aligned_start_date=comparison.aligned_start_date,
            benchmark_aligned_end_date=comparison.aligned_end_date,
            benchmark_observations=comparison.observations,
            benchmark_missing_reason=comparison.missing_reason,
        )


@dataclass(frozen=True)
class BenchmarkComparison:
    """Strictly date-aligned benchmark comparison for one equity curve."""

    available: bool
    total_return: float | None
    max_drawdown: float | None
    excess_return: float | None
    aligned_start_date: str | None
    aligned_end_date: str | None
    observations: int
    missing_reason: str | None = None
    return_basis: str | None = None
    price_policy: str | None = None
    source: str | None = None


def _calculate_cagr(total_return: float, start_date: pd.Timestamp, end_date: pd.Timestamp) -> float:
    days = max((end_date - start_date).days, 0)
    if days == 0:
        return total_return
    years = days / 365.25
    if total_return <= -1:
        return -1.0
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def _calculate_sharpe_ratio(
    *,
    returns: pd.Series,
    risk_free_rate: float,
    trading_days: int,
) -> float | None:
    if returns.empty:
        return None
    daily_rf = risk_free_rate / trading_days
    excess = returns - daily_rf
    volatility = excess.std(ddof=0)
    if volatility == 0:
        return None
    return float(excess.mean() / volatility * sqrt(trading_days))


def _calculate_sortino_ratio(
    *,
    returns: pd.Series,
    risk_free_rate: float,
    trading_days: int,
) -> float | None:
    if returns.empty:
        return None
    daily_rf = risk_free_rate / trading_days
    downside = (returns - daily_rf).clip(upper=0)
    downside_deviation = downside.std(ddof=0)
    if downside_deviation == 0:
        return None
    return float((returns.mean() - daily_rf) / downside_deviation * sqrt(trading_days))


def _calculate_max_drawdown(equity: pd.Series) -> float:
    running_peak = equity.cummax()
    drawdown = (equity / running_peak.where(running_peak != 0)) - 1.0
    return float(drawdown.min())


def _trade_metrics(trades: Sequence[Trade]) -> tuple[float, float | None, float | None]:
    closed_trades = [
        trade for trade in trades if trade.side == "sell" and trade.realized_pnl is not None
    ]
    if not closed_trades:
        return 0.0, None, None

    wins = [trade.realized_pnl or 0.0 for trade in closed_trades if (trade.realized_pnl or 0.0) > 0]
    losses = [
        trade.realized_pnl or 0.0 for trade in closed_trades if (trade.realized_pnl or 0.0) < 0
    ]
    win_rate = len(wins) / len(closed_trades)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss == 0:
        profit_factor = None if gross_profit == 0 else float("inf")
    else:
        profit_factor = gross_profit / gross_loss

    holding_periods = [
        trade.holding_days for trade in closed_trades if trade.holding_days is not None
    ]
    average_holding_period = (
        sum(holding_periods) / len(holding_periods) if holding_periods else None
    )
    return win_rate, profit_factor, average_holding_period


def calculate_benchmark_comparison(
    equity_curve: pd.DataFrame,
    benchmark: pd.DataFrame | None,
    *,
    strategy_total_return: float,
    strategy_return_basis: ReturnBasis | str | None = None,
    benchmark_return_basis: ReturnBasis | str | None = None,
    benchmark_price_policy: PricePolicy | str | None = None,
    benchmark_source: str | None = None,
) -> BenchmarkComparison:
    """Return benchmark metrics only when every equity-curve date matches exactly.

    Benchmark values are never forward-filled or deduplicated.  The caller gets
    an explicit unavailable result when date boundaries or observations cannot
    be compared reliably.
    """

    basis, basis_error = _resolve_benchmark_return_basis(
        strategy_return_basis=strategy_return_basis,
        benchmark_return_basis=benchmark_return_basis,
    )
    if basis_error is not None:
        return _unavailable_benchmark(
            basis_error,
            return_basis=basis,
            price_policy=_parse_price_policy(benchmark_price_policy),
            source=benchmark_source,
        )
    if benchmark is None or benchmark.empty:
        return _unavailable_benchmark("benchmark_unavailable")
    if equity_curve.empty or "date" not in equity_curve.columns:
        return _unavailable_benchmark("equity_curve_unavailable")

    frame = benchmark.copy()
    value_col = "total_equity" if "total_equity" in frame.columns else "close"
    if "date" not in frame.columns or value_col not in frame.columns:
        return _unavailable_benchmark("benchmark_missing_required_columns")

    frame["date"] = _normalize_trade_dates(frame["date"])
    frame["_benchmark_value"] = pd.to_numeric(frame[value_col], errors="coerce")
    if frame.empty:
        return _unavailable_benchmark("benchmark_unavailable")
    if frame["date"].isna().any():
        return _unavailable_benchmark("benchmark_contains_invalid_dates")
    if frame["_benchmark_value"].isna().any():
        return _unavailable_benchmark("benchmark_contains_invalid_values")
    if frame["date"].duplicated().any():
        return _unavailable_benchmark("benchmark_contains_duplicate_dates")

    strategy = equity_curve.copy()
    strategy["date"] = _normalize_trade_dates(strategy["date"])
    if strategy.empty or strategy["date"].duplicated().any():
        return _unavailable_benchmark("equity_curve_dates_invalid")
    if strategy["date"].isna().any():
        return _unavailable_benchmark("equity_curve_contains_invalid_dates")
    strategy = strategy.sort_values("date")

    expected_dates = pd.DatetimeIndex(strategy["date"])
    in_window = frame.loc[
        (frame["date"] >= expected_dates.min()) & (frame["date"] <= expected_dates.max())
    ].sort_values("date")
    if in_window["date"].tolist() != list(expected_dates):
        return _unavailable_benchmark("benchmark_dates_do_not_match_equity_curve")
    aligned = in_window

    values = aligned["_benchmark_value"].astype(float)
    first = float(values.iloc[0])
    last = float(values.iloc[-1])
    if first == 0:
        return _unavailable_benchmark("benchmark_initial_value_zero")
    total_return = (last / first) - 1.0
    return BenchmarkComparison(
        available=True,
        total_return=total_return,
        max_drawdown=_calculate_max_drawdown(values),
        excess_return=strategy_total_return - total_return,
        aligned_start_date=aligned["date"].iloc[0].date().isoformat(),
        aligned_end_date=aligned["date"].iloc[-1].date().isoformat(),
        observations=len(aligned),
        return_basis=basis,
        price_policy=_parse_price_policy(benchmark_price_policy),
        source=None if benchmark_source is None else str(benchmark_source).strip() or None,
    )


def _unavailable_benchmark(
    reason: str,
    *,
    return_basis: str | None = None,
    price_policy: str | None = None,
    source: str | None = None,
) -> BenchmarkComparison:
    """Create an explicit unavailable benchmark result."""

    return BenchmarkComparison(
        available=False,
        total_return=None,
        max_drawdown=None,
        excess_return=None,
        aligned_start_date=None,
        aligned_end_date=None,
        observations=0,
        missing_reason=reason,
        return_basis=return_basis,
        price_policy=price_policy,
        source=source,
    )


def _resolve_benchmark_return_basis(
    *,
    strategy_return_basis: ReturnBasis | str | None,
    benchmark_return_basis: ReturnBasis | str | None,
) -> tuple[str | None, str | None]:
    """Require equal explicit bases while keeping legacy no-policy calls compatible."""

    if strategy_return_basis is None and benchmark_return_basis is None:
        return ReturnBasis.PRICE_RETURN.value, None
    if strategy_return_basis is None or benchmark_return_basis is None:
        return None, "benchmark_return_basis_unavailable"
    try:
        strategy = ReturnBasis(str(strategy_return_basis)).value
        benchmark = ReturnBasis(str(benchmark_return_basis)).value
    except ValueError:
        return None, "benchmark_return_basis_invalid"
    if strategy != benchmark:
        return None, "benchmark_return_basis_mismatch"
    return strategy, None


def _parse_price_policy(value: PricePolicy | str | None) -> str | None:
    """Return a known policy label without silently selecting one."""

    if value is None:
        return None
    try:
        return PricePolicy(str(value)).value
    except ValueError:
        return None


def _normalize_trade_dates(values: pd.Series) -> pd.Series:
    """Normalize mixed timezone dates without forward-filling or dropping rows."""

    normalized = pd.to_datetime(values, errors="coerce", utc=True)
    return normalized.dt.tz_localize(None).dt.normalize()
