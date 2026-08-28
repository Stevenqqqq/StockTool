from __future__ import annotations

import pytest

from stock_tool.strategies import (
    BreakoutStrategy,
    FundamentalGrowthStrategy,
    MACDTrendStrategy,
    MACrossStrategy,
    RSIReversalStrategy,
    VolumePriceBreakoutStrategy,
)
from stock_tool.strategies.registry import (
    STRATEGY_REGISTRY,
    StrategyRegistryError,
    create_strategy,
    get_strategy_definition,
)


@pytest.mark.parametrize(
    ("key", "strategy_type"),
    [
        ("ma_cross", MACrossStrategy),
        ("breakout", BreakoutStrategy),
        ("rsi_reversal", RSIReversalStrategy),
        ("macd_trend", MACDTrendStrategy),
        ("volume_price_breakout", VolumePriceBreakoutStrategy),
        ("fundamental_growth", FundamentalGrowthStrategy),
    ],
)
def test_registry_defines_the_six_supported_strategies(
    key: str, strategy_type: type[object]
) -> None:
    definition = get_strategy_definition(key)

    assert definition.key == key
    assert definition.display_name_zh
    assert definition.description
    assert definition.risk_notes
    assert definition.default_parameters
    assert definition.parameter_schema
    assert definition.minimum_rows > 0
    assert definition.strategy_type is strategy_type
    assert create_strategy(key).__class__ is strategy_type


def test_registry_is_the_canonical_strategy_key_source() -> None:
    assert tuple(STRATEGY_REGISTRY) == (
        "ma_cross",
        "breakout",
        "rsi_reversal",
        "macd_trend",
        "volume_price_breakout",
        "fundamental_growth",
    )
    assert "target_percent" not in get_strategy_definition("ma_cross").sensitivity_parameters
    assert "target_percent" in get_strategy_definition("ma_cross").forbidden_sensitivity_parameters


def test_registry_rejects_unknown_strategy_without_fallback() -> None:
    with pytest.raises(StrategyRegistryError, match="not registered"):
        get_strategy_definition("not-a-strategy")


def test_registry_factory_keeps_original_default_parameter_mapping_unchanged() -> None:
    definition = get_strategy_definition("breakout")
    before = dict(definition.default_parameters)

    strategy = create_strategy("breakout", {"lookback": 7})

    assert strategy.parameters["lookback"] == 7
    assert dict(definition.default_parameters) == before
