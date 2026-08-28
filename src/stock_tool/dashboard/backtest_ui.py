"""Pure, testable presentation logic for the beginner backtest workflow.

The helpers in this module translate Dashboard form values into the existing
``BrokerConfig`` and strategy parameters.  They deliberately do not execute a
backtest, mutate a DataFrame, or alter any broker or strategy formula.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Mapping

from stock_tool.backtest import BrokerConfig
from stock_tool.domain.models import Market
from stock_tool.strategies.registry import get_strategy_definition


class BacktestCostPreset(StrEnum):
    """Named research cost assumptions selectable in the Dashboard."""

    TAIWAN_STOCK = "taiwan_stock"
    US_STOCK = "us_stock"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class BacktestCostAssumptions:
    """One explicit set of non-personalized trading-cost assumptions."""

    commission_rate: float
    tax_rate: float
    slippage_rate: float
    currency: str | None
    label: str
    limitation: str


@dataclass(frozen=True, slots=True)
class StrategyGuidance:
    """Short research-only explanation for an existing strategy."""

    title: str
    observe: str
    buy_signal: str
    sell_signal: str
    data_requirement: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BacktestFormValues:
    """Immutable Dashboard inputs used to validate one planned backtest."""

    symbol: str
    market: str
    strategy_key: str
    strategy_parameters: Mapping[str, object]
    data_rows: int
    data_start: str | None
    data_end: str | None
    data_source: str | None
    initial_cash: float
    allocation_rate: float
    max_position_pct: float
    commission_rate: float
    tax_rate: float
    slippage_rate: float
    cost_preset: BacktestCostPreset
    trailing_stop_pct: float | None
    has_fundamentals: bool
    market_costs_confirmed: bool


@dataclass(frozen=True, slots=True)
class BacktestValidationResult:
    """Structured preflight outcome shown before a backtest can run."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()

    @property
    def can_execute(self) -> bool:
        """Return whether the planned backtest has no blocking validation error."""

        return not self.errors


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    """Plain-language view of the values passed to the existing engine."""

    symbol: str
    market: str
    currency: str | None
    strategy_key: str
    data_range: str
    data_rows: int
    data_source: str
    allocation_rate: float
    max_position_pct: float
    broker_config: BrokerConfig
    execution_model: str
    trailing_stop_status: str


@dataclass(frozen=True, slots=True)
class BacktestRunBinding:
    """Immutable record of the exact form values used by one completed run."""

    summary: BacktestSummary
    strategy_parameters: tuple[tuple[str, object], ...]
    initial_cash: float
    allocation_rate: float
    max_position_pct: float
    commission_rate: float
    tax_rate: float
    slippage_rate: float
    trailing_stop_pct: float | None
    data_start: str | None
    data_end: str | None
    data_source: str | None
    cost_preset: BacktestCostPreset

    def matches(self, values: BacktestFormValues) -> bool:
        """Return whether the currently visible form equals this executed run."""

        return self == build_backtest_run_binding(values)

    def to_parameters(self) -> dict[str, object]:
        """Return a compatibility payload for existing report and research consumers."""

        return {
            "symbol": self.summary.symbol,
            "market": self.summary.market if self.summary.market != "UNKNOWN" else None,
            "strategy": self.summary.strategy_key,
            "strategy_parameters": dict(self.strategy_parameters),
            "initial_cash": self.initial_cash,
            "commission_rate": self.commission_rate,
            "tax_rate": self.tax_rate,
            "slippage_rate": self.slippage_rate,
            "execution_price_col": self.summary.broker_config.execution_price_col,
            "max_position_pct": self.max_position_pct,
            "allocation_rate": self.allocation_rate,
            "cost_preset": self.cost_preset.value,
            "trailing_stop_pct": self.trailing_stop_pct,
            "data_start": self.data_start,
            "data_end": self.data_end,
            "data_source": self.data_source,
        }


@dataclass(frozen=True, slots=True)
class BacktestResultDisplay:
    """Safe display decision for a retained backtest result."""

    summary: BacktestSummary | None
    is_current: bool
    message: str | None


_COST_ASSUMPTIONS: dict[BacktestCostPreset, BacktestCostAssumptions] = {
    BacktestCostPreset.TAIWAN_STOCK: BacktestCostAssumptions(
        commission_rate=0.001425,
        tax_rate=0.003,
        slippage_rate=0.001,
        currency="TWD",
        label="台股研究假設",
        limitation="此為研究用費率假設；不同券商、商品與交易條件可能不同。",
    ),
    BacktestCostPreset.US_STOCK: BacktestCostAssumptions(
        commission_rate=0.001,
        tax_rate=0.0,
        slippage_rate=0.001,
        currency="USD",
        label="美股研究假設",
        limitation="此為研究用費率假設；未包含匯率、券商最低費用或所有市場規費。",
    ),
    BacktestCostPreset.CUSTOM: BacktestCostAssumptions(
        commission_rate=0.0,
        tax_rate=0.0,
        slippage_rate=0.0,
        currency=None,
        label="自訂研究假設",
        limitation="請自行確認市場、幣別與交易成本；系統不會猜測。",
    ),
}

BACKTEST_RESEARCH_NOTICE = (
    "策略回測用歷史資料檢驗交易規則，不會自動下單。策略回測與投資組合風險是獨立功能；"
    "使用投資組合風險不需要先執行回測。"
)


NO_TRADE_EXPLANATION = (
    "此期間沒有成交，不代表策略成功或失敗。可能原因包括：尚未出現訊號、"
    "訊號出現在最後一根 K 棒而無下一根可成交，或部位／風控限制阻擋成交。"
)


def percent_to_rate(percent: float) -> float:
    """Convert a user-facing percentage, such as ``0.1425``, to a rate."""

    return float(Decimal(str(percent)) / Decimal("100"))


def rate_to_percent(rate: float) -> float:
    """Convert an engine rate, such as ``0.001425``, to a percentage."""

    return float(Decimal(str(rate)) * Decimal("100"))


def resolve_backtest_currency(market: Market | str) -> str | None:
    """Return the known native research currency without guessing UNKNOWN markets."""

    parsed = _parse_market(market)
    if parsed in {Market.TWSE, Market.TPEX}:
        return "TWD"
    if parsed is Market.US:
        return "USD"
    return None


def resolve_cost_preset(
    market: Market | str,
    *,
    current_preset: BacktestCostPreset | None = None,
    is_user_edited: bool = False,
) -> BacktestCostPreset:
    """Choose a market default unless a user explicitly retained custom costs."""

    if is_user_edited and current_preset is not None:
        return BacktestCostPreset(current_preset)
    parsed = _parse_market(market)
    if parsed in {Market.TWSE, Market.TPEX}:
        return BacktestCostPreset.TAIWAN_STOCK
    if parsed is Market.US:
        return BacktestCostPreset.US_STOCK
    return BacktestCostPreset.CUSTOM


def cost_assumptions(preset: BacktestCostPreset) -> BacktestCostAssumptions:
    """Return immutable defaults for a named preset without changing user inputs."""

    return _COST_ASSUMPTIONS[BacktestCostPreset(preset)]


def strategy_guidance(strategy_key: str) -> StrategyGuidance:
    """Return Chinese explanatory text for an existing strategy implementation."""

    try:
        definition = get_strategy_definition(str(strategy_key))
    except ValueError:
        return StrategyGuidance(
            title="策略",
            observe="請確認策略規則與資料條件。",
            buy_signal="依策略既有規則產生研究買入訊號。",
            sell_signal="依策略既有規則產生研究賣出訊號。",
            data_requirement="需要足夠且可用的歷史資料。",
            limitations=("策略僅供歷史研究，不構成投資建議。",),
        )
    fields = "、".join(definition.required_price_fields)
    return StrategyGuidance(
        title=definition.display_name_zh,
        observe=definition.description,
        buy_signal="依既有策略規則產生研究買入訊號，最早於下一根 K 棒成交。",
        sell_signal="依既有策略規則產生研究賣出訊號，最早於下一根 K 棒成交。",
        data_requirement=f"至少 {definition.minimum_rows} 筆資料；需要欄位：{fields}。",
        limitations=definition.risk_notes,
    )


def build_backtest_broker_config(values: BacktestFormValues) -> BrokerConfig:
    """Build the unchanged broker configuration from the submitted form rates."""

    return BrokerConfig(
        commission_rate=values.commission_rate,
        tax_rate=values.tax_rate,
        slippage_rate=values.slippage_rate,
        execution_price_col="open",
    )


def validate_backtest_form(values: BacktestFormValues) -> BacktestValidationResult:
    """Validate a planned backtest without executing or modifying any input."""

    errors: list[str] = []
    warnings: list[str] = []
    next_steps: list[str] = []
    parameters = dict(values.strategy_parameters)
    required_rows = _required_rows(values.strategy_key, parameters)

    if values.initial_cash <= 0:
        errors.append("初始資金必須大於 0。")
    if not 0 < values.allocation_rate <= 1:
        errors.append("策略投入比例必須介於 0% 到 100%。")
    if not 0 < values.max_position_pct <= 1:
        errors.append("單一持股上限必須介於 0% 到 100%。")
    if values.allocation_rate > values.max_position_pct:
        errors.append("策略投入比例不可高於單一持股上限。")
    if min(values.commission_rate, values.tax_rate, values.slippage_rate) < 0:
        errors.append("手續費、賣出稅費與滑價不可為負數。")
    if values.data_rows < required_rows:
        errors.append(f"目前資料只有 {values.data_rows} 筆；此策略至少需要 {required_rows} 筆。")
        next_steps.append("請延長資料期間或選擇所需歷史資料較少的策略。")
    if values.strategy_key == "ma_cross":
        short = _integer_parameter(parameters, "short_window", 20)
        long = _integer_parameter(parameters, "long_window", 60)
        if short >= long:
            errors.append("短均線天數必須小於長均線天數。")
    if values.strategy_key == "fundamental_growth" and not values.has_fundamentals:
        errors.append("基本面成長策略需要可取得日期的基本面資料。")
        next_steps.append("請先載入或更新該股票的基本面資料，再執行此策略。")
    if _parse_market(values.market) not in {Market.TWSE, Market.TPEX, Market.US}:
        if not values.market_costs_confirmed:
            errors.append("市場未確認；請確認幣別與交易成本假設後再執行。")
        warnings.append("市場未確認時，系統不會猜測幣別、稅費或交易成本。")
    total_cost = values.commission_rate + values.tax_rate + values.slippage_rate
    if total_cost >= 0.02:
        warnings.append("目前單邊研究成本假設偏高，請確認是否符合研究目的。")
    if values.trailing_stop_pct is not None and not 0 < values.trailing_stop_pct < 1:
        errors.append("移動停利回落比例必須介於 0% 到 100% 之間。")
    if not values.data_source:
        warnings.append("資料來源未標示；請確認資料的新舊程度與完整性。")
    return BacktestValidationResult(tuple(errors), tuple(warnings), tuple(next_steps))


def build_backtest_summary(values: BacktestFormValues) -> BacktestSummary:
    """Build a concise, auditable summary of actual parameters sent to the engine."""

    data_range = (
        f"{values.data_start} 至 {values.data_end}"
        if values.data_start and values.data_end
        else "資料期間未完整標示"
    )
    trailing = (
        f"啟用（{rate_to_percent(values.trailing_stop_pct):.2f}%）"
        if values.trailing_stop_pct is not None
        else "未啟用"
    )
    return BacktestSummary(
        symbol=str(values.symbol).strip().upper(),
        market=_market_label(values.market),
        currency=resolve_backtest_currency(values.market),
        strategy_key=str(values.strategy_key),
        data_range=data_range,
        data_rows=int(values.data_rows),
        data_source=str(values.data_source or "資料不足"),
        allocation_rate=values.allocation_rate,
        max_position_pct=values.max_position_pct,
        broker_config=build_backtest_broker_config(values),
        execution_model="次一根 K 棒開盤價",
        trailing_stop_status=trailing,
    )


def build_backtest_run_binding(values: BacktestFormValues) -> BacktestRunBinding:
    """Freeze the exact user-visible values passed to one backtest execution."""

    return BacktestRunBinding(
        summary=build_backtest_summary(values),
        strategy_parameters=tuple(
            sorted(
                (str(name), _freeze_strategy_parameter(value))
                for name, value in values.strategy_parameters.items()
            )
        ),
        initial_cash=float(values.initial_cash),
        allocation_rate=float(values.allocation_rate),
        max_position_pct=float(values.max_position_pct),
        commission_rate=float(values.commission_rate),
        tax_rate=float(values.tax_rate),
        slippage_rate=float(values.slippage_rate),
        trailing_stop_pct=(
            float(values.trailing_stop_pct) if values.trailing_stop_pct is not None else None
        ),
        data_start=values.data_start,
        data_end=values.data_end,
        data_source=values.data_source,
        cost_preset=BacktestCostPreset(values.cost_preset),
    )


def resolve_backtest_result_display(
    values: BacktestFormValues, binding: BacktestRunBinding | None
) -> BacktestResultDisplay:
    """Choose a saved summary without ever relabeling a prior result as current."""

    if binding is None:
        return BacktestResultDisplay(
            summary=None,
            is_current=False,
            message="現有回測結果沒有保存當次設定快照；請重新執行後再解讀結果。",
        )
    if binding.matches(values):
        return BacktestResultDisplay(summary=binding.summary, is_current=True, message=None)
    return BacktestResultDisplay(
        summary=binding.summary,
        is_current=False,
        message=(
            "目前表單設定已變更。下方顯示的是上一次回測實際使用的設定與結果，"
            "請重新執行回測以取得目前設定的結果。"
        ),
    )


def no_trade_explanation(number_of_trades: int) -> str | None:
    """Return a neutral explanation only when a completed run has no fills."""

    return NO_TRADE_EXPLANATION if number_of_trades == 0 else None


def _parse_market(market: Market | str) -> Market | None:
    try:
        return Market.parse(market)
    except ValueError:
        return None


def _market_label(market: Market | str) -> str:
    parsed = _parse_market(market)
    return parsed.value if parsed is not None else "UNKNOWN"


def _integer_parameter(parameters: Mapping[str, object], name: str, default: int) -> int:
    value = parameters.get(name, default)
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _freeze_strategy_parameter(value: object) -> object:
    """Convert container values into deterministic immutable equivalents."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return tuple(
            sorted((str(name), _freeze_strategy_parameter(item)) for name, item in value.items())
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_strategy_parameter(item) for item in value)
    return str(value)


def _required_rows(strategy_key: str, parameters: Mapping[str, object]) -> int:
    try:
        definition = get_strategy_definition(strategy_key)
    except ValueError:
        return 2
    if strategy_key == "ma_cross":
        return (
            max(
                _integer_parameter(parameters, "short_window", 20),
                _integer_parameter(parameters, "long_window", 60),
            )
            + 1
        )
    if strategy_key == "macd_trend":
        return _integer_parameter(parameters, "slow_period", 26) + _integer_parameter(
            parameters, "signal_period", 9
        )
    if strategy_key == "volume_price_breakout":
        return (
            max(
                _integer_parameter(parameters, "lookback", 20),
                _integer_parameter(parameters, "volume_window", 20),
            )
            + 1
        )
    if strategy_key in {"breakout", "rsi_reversal"}:
        parameter = "lookback" if strategy_key == "breakout" else "period"
        return _integer_parameter(parameters, parameter, definition.minimum_rows - 1) + 1
    return definition.minimum_rows
