"""Canonical, explicit registry for the supported research strategies."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from stock_tool.strategies.base import StrategyBase
from stock_tool.strategies.breakout import BreakoutStrategy
from stock_tool.strategies.fundamental_growth import FundamentalGrowthStrategy
from stock_tool.strategies.ma_cross import MACrossStrategy
from stock_tool.strategies.macd_trend import MACDTrendStrategy
from stock_tool.strategies.rsi_reversal import RSIReversalStrategy
from stock_tool.strategies.volume_price_breakout import VolumePriceBreakoutStrategy


class StrategyRegistryError(ValueError):
    """Raised when a caller requests a strategy outside the approved registry."""


@dataclass(frozen=True, slots=True)
class StrategyParameterSpec:
    """One user-visible and validation-safe strategy parameter definition."""

    key: str
    label_zh: str
    value_type: str
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    """Immutable metadata and factory boundary for one existing strategy."""

    key: str
    display_name_zh: str
    strategy_type: type[StrategyBase]
    description: str
    risk_notes: tuple[str, ...]
    default_parameters: Mapping[str, Any]
    parameter_schema: tuple[StrategyParameterSpec, ...]
    required_price_fields: tuple[str, ...]
    requires_fundamentals: bool
    minimum_rows: int
    sensitivity_parameters: tuple[str, ...]
    forbidden_sensitivity_parameters: tuple[str, ...]

    def create(self, parameters: Mapping[str, Any] | None = None) -> StrategyBase:
        """Create and validate a fresh strategy without mutating registry defaults."""

        # StrategyBase owns default merging and the sizing mutual-exclusion
        # contract. Passing registry defaults back as explicit kwargs would turn
        # its default ``target_percent`` into an explicit setting and conflict
        # with an explicit quantity or cash amount.
        values = dict(parameters or {})
        return self.strategy_type(**values)


_SIZING_AND_SAFETY_PARAMETERS = (
    "quantity",
    "cash_amount",
    "target_percent",
)


def _definition(
    *,
    key: str,
    display_name_zh: str,
    strategy_type: type[StrategyBase],
    parameter_schema: tuple[StrategyParameterSpec, ...],
    required_price_fields: tuple[str, ...],
    requires_fundamentals: bool,
    minimum_rows: int,
    sensitivity_parameters: tuple[str, ...],
) -> StrategyDefinition:
    return StrategyDefinition(
        key=key,
        display_name_zh=display_name_zh,
        strategy_type=strategy_type,
        description=strategy_type.description,
        risk_notes=tuple(strategy_type.risk_notes),
        default_parameters=MappingProxyType(dict(strategy_type.default_parameters)),
        parameter_schema=parameter_schema,
        required_price_fields=required_price_fields,
        requires_fundamentals=requires_fundamentals,
        minimum_rows=minimum_rows,
        sensitivity_parameters=sensitivity_parameters,
        forbidden_sensitivity_parameters=_SIZING_AND_SAFETY_PARAMETERS,
    )


STRATEGY_REGISTRY: Mapping[str, StrategyDefinition] = MappingProxyType(
    {
        "ma_cross": _definition(
            key="ma_cross",
            display_name_zh="均線交叉",
            strategy_type=MACrossStrategy,
            parameter_schema=(
                StrategyParameterSpec("short_window", "短均線", "integer", 2),
                StrategyParameterSpec("long_window", "長均線", "integer", 3),
            ),
            required_price_fields=("date", "symbol", "close", "open"),
            requires_fundamentals=False,
            minimum_rows=61,
            sensitivity_parameters=("short_window", "long_window"),
        ),
        "breakout": _definition(
            key="breakout",
            display_name_zh="區間突破",
            strategy_type=BreakoutStrategy,
            parameter_schema=(StrategyParameterSpec("lookback", "突破回看天數", "integer", 2),),
            required_price_fields=("date", "symbol", "open", "high", "low", "close"),
            requires_fundamentals=False,
            minimum_rows=21,
            sensitivity_parameters=("lookback",),
        ),
        "rsi_reversal": _definition(
            key="rsi_reversal",
            display_name_zh="RSI 反轉",
            strategy_type=RSIReversalStrategy,
            parameter_schema=(
                StrategyParameterSpec("period", "RSI 期間", "integer", 2),
                StrategyParameterSpec("oversold", "RSI 超賣門檻", "number", 0, 100),
                StrategyParameterSpec("overbought", "RSI 過熱門檻", "number", 0, 100),
            ),
            required_price_fields=("date", "symbol", "open", "close"),
            requires_fundamentals=False,
            minimum_rows=15,
            sensitivity_parameters=("period", "oversold", "overbought"),
        ),
        "macd_trend": _definition(
            key="macd_trend",
            display_name_zh="MACD 趨勢",
            strategy_type=MACDTrendStrategy,
            parameter_schema=(
                StrategyParameterSpec("fast_period", "MACD 快線", "integer", 1),
                StrategyParameterSpec("slow_period", "MACD 慢線", "integer", 2),
                StrategyParameterSpec("signal_period", "MACD 訊號線", "integer", 1),
            ),
            required_price_fields=("date", "symbol", "open", "close"),
            requires_fundamentals=False,
            minimum_rows=35,
            sensitivity_parameters=("fast_period", "slow_period", "signal_period"),
        ),
        "volume_price_breakout": _definition(
            key="volume_price_breakout",
            display_name_zh="價量突破",
            strategy_type=VolumePriceBreakoutStrategy,
            parameter_schema=(
                StrategyParameterSpec("lookback", "價格突破回看天數", "integer", 2),
                StrategyParameterSpec("volume_window", "成交量均線天數", "integer", 2),
                StrategyParameterSpec("volume_multiplier", "成交量倍數", "number", 0.1),
            ),
            required_price_fields=("date", "symbol", "open", "high", "low", "close", "volume"),
            requires_fundamentals=False,
            minimum_rows=21,
            sensitivity_parameters=("lookback", "volume_window", "volume_multiplier"),
        ),
        "fundamental_growth": _definition(
            key="fundamental_growth",
            display_name_zh="基本面成長",
            strategy_type=FundamentalGrowthStrategy,
            parameter_schema=(
                StrategyParameterSpec("eps_growth_min", "EPS 成長門檻", "number"),
                StrategyParameterSpec("revenue_growth_min", "營收成長門檻", "number"),
                StrategyParameterSpec("roe_min", "ROE 門檻", "number", 0),
                StrategyParameterSpec("debt_ratio_max", "負債比上限", "number", 0),
            ),
            required_price_fields=("date", "symbol", "open"),
            requires_fundamentals=True,
            minimum_rows=2,
            sensitivity_parameters=(
                "eps_growth_min",
                "revenue_growth_min",
                "roe_min",
                "debt_ratio_max",
            ),
        ),
    }
)


def get_strategy_definition(key: str) -> StrategyDefinition:
    """Return one registered strategy or reject unknown keys explicitly."""

    normalized = str(key).strip().lower()
    try:
        return STRATEGY_REGISTRY[normalized]
    except KeyError as exc:
        raise StrategyRegistryError(f"Strategy key is not registered: {key!r}") from exc


def create_strategy(key: str, parameters: Mapping[str, Any] | None = None) -> StrategyBase:
    """Create one validated registered strategy from explicit parameters."""

    return get_strategy_definition(key).create(parameters)


def strategy_display_labels() -> Mapping[str, str]:
    """Return a fresh UI label mapping derived only from the canonical registry."""

    return {key: definition.display_name_zh for key, definition in STRATEGY_REGISTRY.items()}
