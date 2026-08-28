"""Pluggable research strategies."""

from stock_tool.strategies.base import StrategyBase, StrategyParameterError
from stock_tool.strategies.breakout import BreakoutStrategy
from stock_tool.strategies.fundamental_growth import FundamentalGrowthStrategy
from stock_tool.strategies.ma_cross import MACrossStrategy
from stock_tool.strategies.macd_trend import MACDTrendStrategy
from stock_tool.strategies.rsi_reversal import RSIReversalStrategy
from stock_tool.strategies.volume_price_breakout import VolumePriceBreakoutStrategy
from stock_tool.strategies.registry import (
    STRATEGY_REGISTRY,
    StrategyDefinition,
    StrategyParameterSpec,
    StrategyRegistryError,
    create_strategy,
    get_strategy_definition,
    strategy_display_labels,
)

__all__ = [
    "BreakoutStrategy",
    "FundamentalGrowthStrategy",
    "MACDTrendStrategy",
    "MACrossStrategy",
    "RSIReversalStrategy",
    "StrategyBase",
    "StrategyParameterError",
    "VolumePriceBreakoutStrategy",
    "STRATEGY_REGISTRY",
    "StrategyDefinition",
    "StrategyParameterSpec",
    "StrategyRegistryError",
    "create_strategy",
    "get_strategy_definition",
    "strategy_display_labels",
]
