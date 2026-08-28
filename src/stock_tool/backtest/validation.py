"""Research-only OOS, walk-forward, and bounded parameter validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Callable, Literal, Mapping, Sequence

import pandas as pd

from stock_tool.backtest.engine import BacktestEngine, BacktestResult
from stock_tool.backtest.metrics import PerformanceMetrics
from stock_tool.fundamentals.models import FundamentalPointInTimeMode
from stock_tool.strategies.base import StrategyBase
from stock_tool.strategies.fundamental_growth import FundamentalGrowthStrategy
from stock_tool.strategies.registry import get_strategy_definition

ValidationStatus = Literal["ready", "unavailable"]


class ParameterSensitivityError(ValueError):
    """Raised when a requested sensitivity sweep violates the approved boundary."""


@dataclass(frozen=True, slots=True)
class ValidationWarning:
    """Structured, research-only limitation or preflight warning."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationPeriod:
    """Closed, normalized date interval used by one validation run."""

    start: str
    end: str

    def __post_init__(self) -> None:
        start = _normalize_date(self.start)
        end = _normalize_date(self.end)
        if start > end:
            raise ValueError("ValidationPeriod start must be on or before end.")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


@dataclass(frozen=True, slots=True)
class OutOfSampleConfig:
    """Explicit chronological train/test split for one research validation."""

    train_period: ValidationPeriod
    test_period: ValidationPeriod
    minimum_test_rows: int = 2

    def __post_init__(self) -> None:
        if self.minimum_test_rows < 2:
            raise ValueError("minimum_test_rows must be at least 2.")


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    """Bounded chronological walk-forward configuration expressed in bars."""

    train_bars: int
    test_bars: int
    step_bars: int
    window_mode: Literal["expanding", "rolling"] = "expanding"
    max_folds: int = 10

    def __post_init__(self) -> None:
        if min(self.train_bars, self.test_bars, self.step_bars) <= 0:
            raise ValueError("walk-forward bar counts must be positive.")
        if self.window_mode not in {"expanding", "rolling"}:
            raise ValueError("window_mode must be expanding or rolling.")
        if not 1 <= self.max_folds <= 10:
            raise ValueError("max_folds must be between 1 and 10.")


@dataclass(frozen=True, slots=True)
class ParameterSensitivityConfig:
    """Bounded list of allowed nearby strategy parameter values."""

    parameter_values: Mapping[str, Sequence[object]]
    max_combinations: int = 25

    def __post_init__(self) -> None:
        if not 1 <= self.max_combinations <= 25:
            raise ValueError("max_combinations must be between 1 and 25.")
        if not self.parameter_values:
            raise ValueError("parameter_values must not be empty.")
        for key, values in self.parameter_values.items():
            if not str(key).strip() or not tuple(values):
                raise ValueError("each sensitivity parameter needs at least one value.")

    @property
    def expected_combinations(self) -> int:
        """Return the exact Cartesian-product count without executing a backtest."""

        count = 1
        for values in self.parameter_values.values():
            count *= len(tuple(values))
        return count


@dataclass(frozen=True, slots=True)
class ValidationRun:
    """Immutable snapshot of one engine execution scoped to a requested period."""

    period: ValidationPeriod
    result: BacktestResult
    signal_count: int
    warmup_rows: int
    warnings: tuple[ValidationWarning, ...] = ()

    @property
    def metrics(self) -> PerformanceMetrics:
        """Return the engine metrics for presentation without recalculation."""

        return self.result.metrics

    @property
    def trades(self) -> tuple[Any, ...]:
        """Return immutable trade references produced by the scoped engine run."""

        return tuple(self.result.trades)

    @property
    def equity_curve(self) -> pd.DataFrame:
        """Return a copy so consumer presentation cannot alter the engine result."""

        return self.result.equity_curve.copy(deep=True)


@dataclass(frozen=True, slots=True)
class OutOfSampleValidationResult:
    """Separate in-sample and out-of-sample execution evidence."""

    status: ValidationStatus
    in_sample: ValidationRun | None
    out_of_sample: ValidationRun | None
    warnings: tuple[ValidationWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    """One non-overlapping chronological train/test fold."""

    fold_number: int
    train_period: ValidationPeriod
    test_period: ValidationPeriod
    train_rows: int
    test_rows: int
    frozen_parameters: tuple[tuple[str, object], ...]
    train_run: ValidationRun
    test_run: ValidationRun


@dataclass(frozen=True, slots=True)
class WalkForwardValidationResult:
    """Deterministic fold-level walk-forward evidence without pooled restatement."""

    status: ValidationStatus
    folds: tuple[WalkForwardFold, ...]
    warnings: tuple[ValidationWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class ParameterSensitivityRun:
    """One fixed-parameter sensitivity execution on a shared dataset and costs."""

    parameters: tuple[tuple[str, object], ...]
    run: ValidationRun

    @property
    def total_return(self) -> float:
        """Expose the comparable after-cost total return already calculated by the engine."""

        return self.run.metrics.total_return


@dataclass(frozen=True, slots=True)
class ParameterSensitivityResult:
    """All bounded nearby parameter results, not only a best-performing row."""

    status: ValidationStatus
    runs: tuple[ParameterSensitivityRun, ...]
    warnings: tuple[ValidationWarning, ...] = ()

    @property
    def parameter_sets(self) -> tuple[tuple[tuple[str, object], ...], ...]:
        """Return deterministic parameter combinations for compact UI presentation."""

        return tuple(run.parameters for run in self.runs)


@dataclass(frozen=True, slots=True)
class StrategyValidationResult:
    """Optional aggregate model for callers that need all validation dimensions."""

    out_of_sample: OutOfSampleValidationResult | None = None
    walk_forward: WalkForwardValidationResult | None = None
    sensitivity: ParameterSensitivityResult | None = None
    warnings: tuple[ValidationWarning, ...] = ()


class StrategyValidationService:
    """Run deterministic research validation around, never inside, BacktestEngine."""

    def __init__(self, *, engine_factory: Callable[[], BacktestEngine] | None = None) -> None:
        self._engine_factory = engine_factory or BacktestEngine

    def run_out_of_sample(
        self,
        *,
        strategy: StrategyBase,
        price_data: pd.DataFrame,
        config: OutOfSampleConfig,
        fundamentals: pd.DataFrame | None = None,
    ) -> OutOfSampleValidationResult:
        """Evaluate frozen strategy parameters on strict chronological train/test ranges."""

        if config.train_period.end >= config.test_period.start:
            return OutOfSampleValidationResult(
                status="unavailable",
                in_sample=None,
                out_of_sample=None,
                warnings=(
                    ValidationWarning(
                        "invalid_time_split",
                        "樣本內結束日必須早於樣本外開始日，不能重疊。",
                    ),
                ),
            )
        normalized = _normalize_prices(price_data)
        train_prices = _period_prices(normalized, config.train_period)
        test_prices = _period_prices(normalized, config.test_period)
        if len(train_prices) < 2 or len(test_prices) < config.minimum_test_rows:
            return OutOfSampleValidationResult(
                status="unavailable",
                in_sample=None,
                out_of_sample=None,
                warnings=(
                    ValidationWarning(
                        "insufficient_time_split_data",
                        "樣本內或樣本外資料筆數不足，無法形成可靠比較。",
                    ),
                ),
            )
        strategy_for_validation, strategy_warning = _strict_fundamental_strategy(
            strategy, fundamentals
        )
        if strategy_for_validation is None:
            assert strategy_warning is not None
            return OutOfSampleValidationResult(
                status="unavailable",
                in_sample=None,
                out_of_sample=None,
                warnings=(strategy_warning,),
            )
        train_run = self._run_period(
            strategy=strategy_for_validation,
            all_prices=normalized,
            period=config.train_period,
            fundamentals=fundamentals,
        )
        test_run = self._run_period(
            strategy=strategy_for_validation,
            all_prices=normalized,
            period=config.test_period,
            fundamentals=fundamentals,
        )
        warnings = (*train_run.warnings, *test_run.warnings)
        return OutOfSampleValidationResult(
            status="ready",
            in_sample=train_run,
            out_of_sample=test_run,
            warnings=warnings,
        )

    def run_walk_forward(
        self,
        *,
        strategy: StrategyBase,
        price_data: pd.DataFrame,
        config: WalkForwardConfig,
        fundamentals: pd.DataFrame | None = None,
    ) -> WalkForwardValidationResult:
        """Evaluate frozen parameters over non-overlapping chronological test folds."""

        normalized = _normalize_prices(price_data)
        dates = tuple(sorted(normalized["date"].drop_duplicates().tolist()))
        strategy_for_validation, strategy_warning = _strict_fundamental_strategy(
            strategy, fundamentals
        )
        if strategy_for_validation is None:
            assert strategy_warning is not None
            return WalkForwardValidationResult("unavailable", (), (strategy_warning,))
        folds: list[WalkForwardFold] = []
        test_start_index = config.train_bars
        while len(folds) < config.max_folds:
            test_end_index = test_start_index + config.test_bars - 1
            if test_end_index >= len(dates):
                break
            train_start_index = (
                0 if config.window_mode == "expanding" else test_start_index - config.train_bars
            )
            train_period = ValidationPeriod(dates[train_start_index], dates[test_start_index - 1])
            test_period = ValidationPeriod(dates[test_start_index], dates[test_end_index])
            train_run = self._run_period(
                strategy=strategy_for_validation,
                all_prices=normalized,
                period=train_period,
                fundamentals=fundamentals,
            )
            test_run = self._run_period(
                strategy=strategy_for_validation,
                all_prices=normalized,
                period=test_period,
                fundamentals=fundamentals,
            )
            folds.append(
                WalkForwardFold(
                    fold_number=len(folds) + 1,
                    train_period=train_period,
                    test_period=test_period,
                    train_rows=len(_period_prices(normalized, train_period)),
                    test_rows=len(_period_prices(normalized, test_period)),
                    frozen_parameters=_freeze_parameters(strategy_for_validation.parameters),
                    train_run=train_run,
                    test_run=test_run,
                )
            )
            test_start_index += config.step_bars
        if len(folds) < 2:
            return WalkForwardValidationResult(
                "unavailable",
                tuple(folds),
                (
                    ValidationWarning(
                        "insufficient_walk_forward_folds",
                        "至少需要兩個有效樣本外 fold 才能檢視策略跨期穩定性。",
                    ),
                ),
            )
        warnings = tuple(warning for fold in folds for warning in fold.test_run.warnings)
        return WalkForwardValidationResult("ready", tuple(folds), warnings)

    def run_parameter_sensitivity(
        self,
        *,
        strategy: StrategyBase,
        price_data: pd.DataFrame,
        config: ParameterSensitivityConfig,
        fundamentals: pd.DataFrame | None = None,
    ) -> ParameterSensitivityResult:
        """Run an explicit capped parameter grid without optimizing sizing or costs."""

        definition = get_strategy_definition(strategy.name)
        requested = tuple(sorted(str(key) for key in config.parameter_values))
        forbidden = sorted(set(requested) & set(definition.forbidden_sensitivity_parameters))
        unsupported = sorted(set(requested) - set(definition.sensitivity_parameters))
        if forbidden or unsupported:
            invalid = forbidden or unsupported
            raise ParameterSensitivityError(
                f"Parameter sensitivity is not allowed for: {', '.join(invalid)}"
            )
        if config.expected_combinations > config.max_combinations:
            raise ParameterSensitivityError(
                "Parameter sensitivity exceeds the configured maximum combination count."
            )
        normalized = _normalize_prices(price_data)
        period = ValidationPeriod(normalized["date"].min(), normalized["date"].max())
        strategy_for_validation, strategy_warning = _strict_fundamental_strategy(
            strategy, fundamentals
        )
        if strategy_for_validation is None:
            assert strategy_warning is not None
            return ParameterSensitivityResult("unavailable", (), (strategy_warning,))
        keys = tuple(sorted(config.parameter_values))
        values = tuple(tuple(config.parameter_values[key]) for key in keys)
        runs: list[ParameterSensitivityRun] = []
        for combination in product(*values):
            overrides = dict(zip(keys, combination))
            candidate = _clone_strategy(strategy_for_validation, overrides)
            run = self._run_period(
                strategy=candidate,
                all_prices=normalized,
                period=period,
                fundamentals=fundamentals,
            )
            runs.append(ParameterSensitivityRun(_freeze_parameters(candidate.parameters), run))
        series = tuple(
            (tuple((key, value) for key, value in run.parameters if key in keys), run.total_return)
            for run in runs
        )
        warnings: tuple[ValidationWarning, ...] = ()
        if detect_isolated_parameter_peak(series):
            warnings = (
                ValidationWarning(
                    "isolated_parameter_peak",
                    "單一參數組合明顯高於相鄰組合，結果可能對參數過度敏感。",
                ),
            )
        return ParameterSensitivityResult("ready", tuple(runs), warnings)

    def _run_period(
        self,
        *,
        strategy: StrategyBase,
        all_prices: pd.DataFrame,
        period: ValidationPeriod,
        fundamentals: pd.DataFrame | None,
    ) -> ValidationRun:
        context = all_prices.loc[all_prices["date"] <= period.end].copy(deep=True)
        visible_prices = _period_prices(all_prices, period)
        signals = strategy.generate_signals(context, fundamentals=fundamentals)
        signal_dates = pd.to_datetime(signals["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        scoped_signals = signals.loc[
            (signal_dates >= period.start) & (signal_dates <= period.end)
        ].copy(deep=True)
        result = self._engine_factory().run(visible_prices, scoped_signals)
        warnings: list[ValidationWarning] = []
        if not result.trades:
            warnings.append(
                ValidationWarning(
                    "zero_trades",
                    "此驗證期間沒有成交，不能據此判定策略有效或無效。",
                )
            )
        return ValidationRun(
            period=period,
            result=result,
            signal_count=len(scoped_signals),
            warmup_rows=max(len(context) - len(visible_prices), 0),
            warnings=tuple(warnings),
        )


def detect_isolated_parameter_peak(
    results: Sequence[tuple[object, float]],
    *,
    minimum_drop: float = 0.05,
) -> bool:
    """Detect a large one-dimensional peak with materially weaker neighbours.

    The rule is deliberately conservative: it only warns where the best point
    has two directly adjacent values of the same parameter and both degrade by
    at least ``minimum_drop``. It is a research warning, not an optimization
    verdict.
    """

    if len(results) < 3:
        return False
    normalized: list[tuple[float, float]] = []
    for parameters, value in results:
        pairs = _coerce_parameter_pairs(parameters)
        if len(pairs) != 1:
            return False
        parameter_value = pairs[0][1]
        if not isinstance(parameter_value, (int, float, str)):
            return False
        try:
            numeric_parameter = float(parameter_value)
            numeric_value = float(value)
        except (TypeError, ValueError):
            return False
        normalized.append((numeric_parameter, numeric_value))
    normalized.sort(key=lambda item: item[0])
    best_index = max(range(len(normalized)), key=lambda index: normalized[index][1])
    if best_index == 0 or best_index == len(normalized) - 1:
        return False
    best_value = normalized[best_index][1]
    left_value = normalized[best_index - 1][1]
    right_value = normalized[best_index + 1][1]
    return best_value - max(left_value, right_value) >= minimum_drop


def _normalize_prices(price_data: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "symbol", "open", "close"}
    missing = sorted(required - set(price_data.columns))
    if missing:
        raise ValueError(f"price_data missing required columns: {', '.join(missing)}")
    frame = price_data.copy(deep=True)
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.isna().any():
        raise ValueError("price_data contains invalid dates.")
    frame["date"] = dates.dt.strftime("%Y-%m-%d")
    return frame.sort_values(["date", "symbol"], kind="mergesort").reset_index(drop=True)


def _period_prices(frame: pd.DataFrame, period: ValidationPeriod) -> pd.DataFrame:
    return frame.loc[(frame["date"] >= period.start) & (frame["date"] <= period.end)].copy(
        deep=True
    )


def _normalize_date(value: str) -> str:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("ValidationPeriod date must be valid.")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(None)
    return timestamp.normalize().date().isoformat()


def _strict_fundamental_strategy(
    strategy: StrategyBase,
    fundamentals: pd.DataFrame | None,
) -> tuple[StrategyBase | None, ValidationWarning | None]:
    if not isinstance(strategy, FundamentalGrowthStrategy):
        return strategy, None
    if fundamentals is None or fundamentals.empty:
        return None, ValidationWarning(
            "fundamentals_unavailable",
            "基本面策略健檢需要具 available_date 的基本面資料。",
        )
    if "available_date" not in fundamentals.columns:
        return None, ValidationWarning(
            "fundamental_available_date_missing",
            "嚴格基本面健檢缺少可用 available_date，因此沒有使用基本面資料。",
        )
    availability = pd.to_datetime(fundamentals["available_date"], errors="coerce")
    if availability.isna().all():
        return None, ValidationWarning(
            "fundamental_available_date_missing",
            "嚴格基本面健檢缺少可用 available_date，因此沒有使用基本面資料。",
        )
    parameters = dict(strategy.parameters)
    parameters["point_in_time_mode"] = FundamentalPointInTimeMode.STRICT.value
    return _clone_strategy(strategy, parameters), None


def _clone_strategy(strategy: StrategyBase, overrides: Mapping[str, object]) -> StrategyBase:
    parameters = dict(strategy.parameters)
    parameters.update(dict(overrides))
    return get_strategy_definition(strategy.name).create(parameters)


def _freeze_parameters(parameters: Mapping[str, object]) -> tuple[tuple[str, object], ...]:
    return tuple(sorted((str(key), _freeze_parameter(value)) for key, value in parameters.items()))


def _freeze_parameter(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze_parameter(item)) for key, item in value.items()))
    if isinstance(value, Sequence) and not isinstance(value, str):
        return tuple(_freeze_parameter(item) for item in value)
    return str(value)


def _coerce_parameter_pairs(value: object) -> tuple[tuple[str, object], ...]:
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        return ((value[0], value[1]),)
    if isinstance(value, Sequence) and not isinstance(value, str):
        pairs: list[tuple[str, object]] = []
        for item in value:
            if isinstance(item, tuple) and len(item) == 2:
                pairs.append((str(item[0]), item[1]))
        return tuple(pairs)
    return ()
