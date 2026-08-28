"""Transparent deterministic portfolio stress scenarios, not forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from stock_tool.domain.models import MissingData, MissingDataState
from stock_tool.portfolio_valuation import PortfolioValuationResult


class StressScenarioType(str, Enum):
    """Supported transparent stress assumptions."""

    ALL_HOLDINGS_DECLINE = "all_holdings_decline"
    LARGEST_HOLDING_DECLINE = "largest_holding_decline"
    MARKET_DECLINE = "market_decline"
    USD_TWD_MOVE = "usd_twd_move"


@dataclass(frozen=True, slots=True)
class StressScenario:
    """One explicit percentage shock and optional market filter."""

    name: str
    scenario_type: StressScenarioType
    shock_pct: float
    market: str | None = None

    def __post_init__(self) -> None:
        if self.scenario_type is StressScenarioType.USD_TWD_MOVE:
            if not -1 < self.shock_pct <= 1:
                raise ValueError("USD/TWD shock_pct must be greater than -1 and no more than 1.")
        elif not 0 <= self.shock_pct <= 1:
            raise ValueError("Decline shock_pct must be between 0 and 1.")
        if self.scenario_type is StressScenarioType.MARKET_DECLINE and not self.market:
            raise ValueError("Market decline scenarios require a market.")


@dataclass(frozen=True, slots=True)
class PortfolioStressResult:
    """Base-currency impact for an explicit deterministic scenario."""

    scenario: StressScenario
    base_currency: str
    base_value_before: float | None
    base_value_after: float | None
    base_impact: float | None
    assumptions: tuple[str, ...]
    missing_data: tuple[MissingData, ...]
    disclaimer: str


class PortfolioStressService:
    """Calculate scenario arithmetic without modifying portfolio source data."""

    def run(
        self,
        *,
        valuation: PortfolioValuationResult,
        scenario: StressScenario,
    ) -> PortfolioStressResult:
        """Apply an explicit scenario only when a consolidated base value is available."""

        if valuation.base_market_value is None:
            return PortfolioStressResult(
                scenario=scenario,
                base_currency=valuation.base_currency.value,
                base_value_before=None,
                base_value_after=None,
                base_impact=None,
                assumptions=("Cross-currency valuation requires complete FX and price inputs.",),
                missing_data=(
                    MissingData(
                        field="stress_test_base_value",
                        state=MissingDataState.UNKNOWN,
                        reason="No consolidated base-currency valuation is available.",
                    ),
                ),
                disclaimer="This scenario is not a forecast and does not modify actual portfolio data.",
            )
        positions = valuation.positions.copy(deep=True)
        before = float(valuation.base_market_value)
        shocked_values = pd.to_numeric(positions["base_market_value"], errors="coerce").copy()
        shock_mask = _shock_mask(positions, scenario)
        if scenario.scenario_type is StressScenarioType.USD_TWD_MOVE:
            fx_factor = 1.0 + scenario.shock_pct
            base_currency = valuation.base_currency.value
            if base_currency == "TWD":
                shock_mask = positions["native_currency"].astype(str).eq("USD")
                shocked_values.loc[shock_mask] *= fx_factor
                adjusted_currency = "USD"
                multiplier = fx_factor
            elif base_currency == "USD":
                shock_mask = positions["native_currency"].astype(str).eq("TWD")
                shocked_values.loc[shock_mask] *= 1.0 / fx_factor
                adjusted_currency = "TWD"
                multiplier = 1.0 / fx_factor
            else:
                return PortfolioStressResult(
                    scenario=scenario,
                    base_currency=base_currency,
                    base_value_before=before,
                    base_value_after=None,
                    base_impact=None,
                    assumptions=("USD/TWD stress testing supports only TWD or USD base currency.",),
                    missing_data=(
                        MissingData(
                            field="stress_test_fx_base_currency",
                            state=MissingDataState.NOT_APPLICABLE,
                            reason=f"Unsupported base currency: {base_currency}.",
                        ),
                    ),
                    disclaimer="This scenario is not a forecast and does not modify actual portfolio data.",
                )
            direction = "+" if scenario.shock_pct >= 0 else ""
            assumption = (
                f"USD/TWD {direction}{scenario.shock_pct:.1%}: one USD exchanges for "
                f"{fx_factor:.4f} times as many TWD; base currency is {base_currency}; "
                f"{adjusted_currency} positions use multiplier {multiplier:.6f}."
            )
        else:
            shocked_values.loc[shock_mask] *= 1.0 - scenario.shock_pct
            assumption = f"Selected market values decline by {scenario.shock_pct:.1%}."
        after = float(shocked_values.sum())
        return PortfolioStressResult(
            scenario=scenario,
            base_currency=valuation.base_currency.value,
            base_value_before=before,
            base_value_after=after,
            base_impact=after - before,
            assumptions=(assumption, "No change is made to the stored portfolio or source prices."),
            missing_data=(),
            disclaimer="This deterministic stress scenario is not a forecast or investment recommendation.",
        )


def _shock_mask(positions: pd.DataFrame, scenario: StressScenario) -> pd.Series:
    if scenario.scenario_type is StressScenarioType.ALL_HOLDINGS_DECLINE:
        return pd.Series(True, index=positions.index)
    if scenario.scenario_type is StressScenarioType.LARGEST_HOLDING_DECLINE:
        largest_index = pd.to_numeric(positions["base_market_value"], errors="coerce").idxmax()
        return positions.index.to_series().eq(largest_index)
    if scenario.scenario_type is StressScenarioType.MARKET_DECLINE:
        return positions["market"].astype(str).str.upper().eq(str(scenario.market).upper())
    return pd.Series(False, index=positions.index)
