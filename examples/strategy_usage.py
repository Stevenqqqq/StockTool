"""Run sample strategy backtests and print a compact performance comparison."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from stock_tool.backtest import BacktestEngine, BrokerConfig
from stock_tool.strategies import (
    BreakoutStrategy,
    MACDTrendStrategy,
    MACrossStrategy,
    VolumePriceBreakoutStrategy,
)


def run_sample_comparison() -> pd.DataFrame:
    """Run several strategies on local sample data and return metrics."""

    prices = pd.read_csv(
        PROJECT_ROOT / "data" / "sample" / "sample_tw_prices_for_indicators.csv",
        dtype={"symbol": str},
    )
    strategies = [
        BreakoutStrategy(
            lookback=10,
            high_col="close",
            low_col="close",
            target_percent=0.5,
        ),
        MACDTrendStrategy(target_percent=0.5),
        MACrossStrategy(short_window=5, long_window=20, target_percent=0.5),
        VolumePriceBreakoutStrategy(
            lookback=10,
            volume_window=10,
            high_col="close",
            low_col="close",
            volume_multiplier=0.95,
            target_percent=0.5,
        ),
    ]
    engine_config = BrokerConfig(
        commission_rate=0.001425,
        tax_rate=0.003,
        slippage_rate=0.001,
        execution_price_col="open",
    )

    rows: list[dict[str, float | int | str | None]] = []
    for strategy in strategies:
        signals = strategy.generate_signals(prices)
        engine = BacktestEngine(
            initial_cash=1_000_000,
            broker_config=engine_config,
            max_position_pct=0.5,
        )
        benchmark = prices[["date", "close"]].copy()
        result = engine.run(prices, signals, benchmark=benchmark)
        rows.append(
            {
                "strategy": strategy.name,
                "total_return": result.metrics.total_return,
                "cagr": result.metrics.cagr,
                "max_drawdown": result.metrics.max_drawdown,
                "sharpe_ratio": result.metrics.sharpe_ratio,
                "trades": result.metrics.number_of_trades,
                "win_rate": result.metrics.win_rate,
                "exposure": result.metrics.exposure,
                "benchmark_total_return": result.metrics.benchmark_total_return,
                "benchmark_excess_return": result.metrics.benchmark_excess_return,
            }
        )

    comparison = pd.DataFrame(rows)
    output_path = PROJECT_ROOT / "data" / "sample" / "sample_strategy_performance.csv"
    comparison.to_csv(output_path, index=False)
    return comparison


if __name__ == "__main__":
    print(run_sample_comparison().to_string(index=False))
