"""Backtesting engine, portfolio accounting, broker simulation, and metrics."""

from stock_tool.backtest.broker import BrokerConfig, BrokerSimulator
from stock_tool.backtest.engine import BacktestEngine, BacktestResult, TRAILING_STOP_DAILY_MODEL_NOTICE
from stock_tool.backtest.metrics import BenchmarkComparison, PerformanceMetrics
from stock_tool.backtest.orders import Order, Position, Trade
from stock_tool.backtest.portfolio import Portfolio, PortfolioSnapshot
from stock_tool.backtest.validation import (
    OutOfSampleConfig,
    OutOfSampleValidationResult,
    ParameterSensitivityConfig,
    ParameterSensitivityResult,
    StrategyValidationResult,
    StrategyValidationService,
    ValidationPeriod,
    ValidationRun,
    ValidationWarning,
    WalkForwardConfig,
    WalkForwardValidationResult,
)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "BrokerConfig",
    "BrokerSimulator",
    "BenchmarkComparison",
    "Order",
    "PerformanceMetrics",
    "Portfolio",
    "PortfolioSnapshot",
    "Position",
    "Trade",
    "TRAILING_STOP_DAILY_MODEL_NOTICE",
    "OutOfSampleConfig",
    "OutOfSampleValidationResult",
    "ParameterSensitivityConfig",
    "ParameterSensitivityResult",
    "StrategyValidationResult",
    "StrategyValidationService",
    "ValidationPeriod",
    "ValidationRun",
    "ValidationWarning",
    "WalkForwardConfig",
    "WalkForwardValidationResult",
]
