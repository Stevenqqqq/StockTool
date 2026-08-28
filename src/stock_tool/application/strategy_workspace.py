"""Application orchestration for the native research-only Strategy workspace.

This module deliberately delegates signal generation, execution, costs, and
validation to the existing strategy registry, BacktestEngine, and validation
service.  It only coordinates user-visible state and a deterministic manifest;
it never writes user data or chooses a best-performing strategy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping

import pandas as pd

from stock_tool import __version__
from stock_tool.backtest import BacktestEngine, BacktestResult
from stock_tool.backtest.validation import (
    OutOfSampleConfig,
    OutOfSampleValidationResult,
    ParameterSensitivityConfig,
    ParameterSensitivityResult,
    StrategyValidationService,
    ValidationPeriod,
    WalkForwardConfig,
    WalkForwardValidationResult,
)
from stock_tool.dashboard.backtest_ui import (
    BacktestCostPreset,
    BacktestFormValues,
    BacktestValidationResult,
    build_backtest_broker_config,
    validate_backtest_form,
)
from stock_tool.dashboard.pages.strategy import build_strategy_health_preflight
from stock_tool.domain.models import Market
from stock_tool.strategies.base import StrategyBase
from stock_tool.strategies.registry import StrategyDefinition, get_strategy_definition


@dataclass(frozen=True, slots=True)
class StrategyDataSnapshot:
    """Auditable data state used by one strategy workspace run."""

    symbol: str
    market: str
    source: str | None
    start: str | None
    end: str | None
    rows: int
    status: str
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StrategyRunManifest:
    """Stable, privacy-safe manifest for comparing strategy runs."""

    core: Mapping[str, object]
    digest: str

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "core": dict(self.core), "digest": self.digest}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


@dataclass(frozen=True, slots=True)
class StrategyWorkspaceRun:
    """Standard result plus explicit health state."""

    status: str
    result: BacktestResult | None
    manifest: StrategyRunManifest
    validation: BacktestValidationResult
    health_status: str
    health_message: str | None = None
    health: "StrategyHealthRun | None" = None


@dataclass(frozen=True, slots=True)
class StrategyHealthRun:
    """Separate health evidence; standard backtest remains available on failure."""

    status: str
    out_of_sample: OutOfSampleValidationResult | None
    walk_forward: WalkForwardValidationResult | None
    sensitivity: ParameterSensitivityResult | None
    message: str | None = None


class StrategyWorkspaceApplicationService:
    """Coordinate one isolated, deterministic strategy research workflow."""

    def __init__(self, *, engine_factory: Any = BacktestEngine) -> None:
        self._engine_factory = engine_factory

    def definition(self, strategy_key: str) -> StrategyDefinition:
        return get_strategy_definition(strategy_key)

    def inspect_data(
        self,
        *,
        price_data: pd.DataFrame | None,
        symbol: str,
        market: str,
        source: Mapping[str, object] | None,
        definition: StrategyDefinition,
    ) -> StrategyDataSnapshot:
        """Classify loaded data without fetching or mutating it."""

        source_name = _safe_source(source)
        if price_data is None or price_data.empty:
            return StrategyDataSnapshot(
                symbol=str(symbol).strip().upper(),
                market=_market_value(market),
                source=source_name,
                start=None,
                end=None,
                rows=0,
                status="missing",
                missing_fields=tuple(definition.required_price_fields),
            )
        frame = price_data.copy(deep=False)
        required = set(definition.required_price_fields)
        missing_values = set(required - set(frame.columns))
        market_values = (
            frame["market"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique()
            if "market" in frame.columns
            else []
        )
        if market in {"UNKNOWN", "CONFLICT"} or len(market_values) != 1:
            missing_values.add("market")
        missing = tuple(sorted(missing_values))
        dates = (
            pd.to_datetime(frame.get("date"), errors="coerce")
            if "date" in frame
            else pd.Series(dtype="datetime64[ns]")
        )
        valid_dates = dates.dropna()
        start = valid_dates.min().strftime("%Y-%m-%d") if not valid_dates.empty else None
        end = valid_dates.max().strftime("%Y-%m-%d") if not valid_dates.empty else None
        if missing or not start or not end:
            status = "partial"
        else:
            status = "fresh" if _source_is_fresh(source) else "stale"
        return StrategyDataSnapshot(
            symbol=str(symbol).strip().upper(),
            market=_market_value(market),
            source=source_name,
            start=start,
            end=end,
            rows=int(len(frame)),
            status=status,
            missing_fields=missing,
        )

    def preflight(
        self,
        *,
        values: BacktestFormValues,
        price_data: pd.DataFrame | None,
        definition: StrategyDefinition,
    ) -> tuple[BacktestValidationResult, object]:
        """Return existing form validation plus the bounded health plan."""

        validation = validate_backtest_form(values)
        if price_data is None or price_data.empty:
            return validation, build_strategy_health_preflight(
                price_data=pd.DataFrame(), definition=definition
            )
        return validation, build_strategy_health_preflight(
            price_data=price_data, definition=definition
        )

    def build_manifest(
        self,
        *,
        values: BacktestFormValues,
        data: StrategyDataSnapshot,
        strategy: StrategyBase,
        status: str,
        warnings: tuple[str, ...] = (),
        missing_data: tuple[str, ...] = (),
        health_status: str = "not_run",
    ) -> StrategyRunManifest:
        """Build a canonical manifest with no runtime or private-path fields."""

        parameters = _canonical(strategy.parameters)
        core: dict[str, object] = {
            "schema_version": 1,
            "symbol": data.symbol,
            "market": data.market,
            "strategy": {"key": strategy.name, "parameters": parameters},
            "data": {
                "source": data.source,
                "start": data.start,
                "end": data.end,
                "rows": data.rows,
                "status": data.status,
                "missing_fields": list(data.missing_fields),
            },
            "costs": {
                "initial_cash": float(values.initial_cash),
                "allocation": float(values.allocation_rate),
                "position_limit": float(values.max_position_pct),
                "commission": float(values.commission_rate),
                "tax": float(values.tax_rate),
                "slippage": float(values.slippage_rate),
                "trailing_stop": values.trailing_stop_pct,
                "preset": BacktestCostPreset(values.cost_preset).value,
            },
            "execution": {
                "model": "T+1",
                "price_column": "open",
                "corporate_action_policy": "existing_engine_policy",
                "version": "backtest-contract-v1",
            },
            "application_version": __version__,
            "status": status,
            "health_status": health_status,
            "warnings": list(warnings),
            "missing_data": list(missing_data),
        }
        encoded = _canonical_json(core)
        return StrategyRunManifest(core=core, digest=sha256(encoded.encode("utf-8")).hexdigest())

    def run_standard(
        self,
        *,
        values: BacktestFormValues,
        strategy: StrategyBase,
        price_data: pd.DataFrame,
        fundamentals: pd.DataFrame | None,
        data: StrategyDataSnapshot,
    ) -> StrategyWorkspaceRun:
        """Execute only after the shared validation has passed."""

        validation = validate_backtest_form(values)
        # The workspace has one allocation control.  Refuse a caller that
        # constructed a strategy with a different target percentage rather
        # than silently allowing UI, engine, and manifest to diverge.
        strategy_target = strategy.parameters.get("target_percent")
        try:
            allocation_matches = strategy_target is not None and float(strategy_target) == float(
                values.allocation_rate
            )
        except (TypeError, ValueError):
            allocation_matches = False
        if not allocation_matches:
            validation = BacktestValidationResult(
                errors=(*validation.errors, "策略投入比例與回測設定不一致，已停止執行。"),
                warnings=validation.warnings,
                next_steps=validation.next_steps,
            )
        if not validation.can_execute or data.status in {"missing", "partial"}:
            manifest = self.build_manifest(
                values=values,
                data=data,
                strategy=strategy,
                status="blocked",
                warnings=validation.warnings,
                missing_data=data.missing_fields,
            )
            return StrategyWorkspaceRun("blocked", None, manifest, validation, "blocked")
        try:
            signals = strategy.generate_signals(price_data, fundamentals=fundamentals)
            engine = self._engine_factory(
                initial_cash=float(values.initial_cash),
                broker_config=build_backtest_broker_config(values),
                max_position_pct=float(values.max_position_pct),
                trailing_stop_pct=values.trailing_stop_pct,
            )
            result = engine.run(price_data, signals)
        except Exception:
            manifest = self.build_manifest(
                values=values,
                data=data,
                strategy=strategy,
                status="error",
                warnings=validation.warnings,
                missing_data=data.missing_fields,
            )
            return StrategyWorkspaceRun(
                "error",
                None,
                manifest,
                validation,
                "not_run",
                "策略執行失敗，請檢查資料與參數後重試。",
            )
        warnings = tuple(str(item) for item in result.warnings)
        manifest = self.build_manifest(
            values=values,
            data=data,
            strategy=strategy,
            status="standard_complete",
            warnings=warnings,
            health_status="not_run",
        )
        return StrategyWorkspaceRun("standard_complete", result, manifest, validation, "not_run")

    def run_health(
        self,
        *,
        strategy: StrategyBase,
        price_data: pd.DataFrame,
        fundamentals: pd.DataFrame | None,
        health_plan: object,
        values: BacktestFormValues,
    ) -> StrategyHealthRun:
        """Run bounded OOS, walk-forward, and sensitivity without optimization."""

        if not getattr(health_plan, "can_run", False):
            return StrategyHealthRun(
                "blocked", None, None, None, "資料不足，無法形成獨立樣本外期間。"
            )
        train_period = getattr(health_plan, "train_period")
        test_period = getattr(health_plan, "test_period")
        walk = getattr(health_plan, "walk_forward")
        sensitivity = getattr(health_plan, "sensitivity")
        assert isinstance(train_period, ValidationPeriod)
        assert isinstance(test_period, ValidationPeriod)
        assert isinstance(walk, WalkForwardConfig)
        assert isinstance(sensitivity, ParameterSensitivityConfig)
        service = StrategyValidationService(
            engine_factory=lambda: self._engine_factory(
                initial_cash=float(values.initial_cash),
                broker_config=build_backtest_broker_config(values),
                max_position_pct=float(values.max_position_pct),
                trailing_stop_pct=values.trailing_stop_pct,
            )
        )
        try:
            oos = service.run_out_of_sample(
                strategy=strategy,
                price_data=price_data,
                fundamentals=fundamentals,
                config=OutOfSampleConfig(train_period, test_period),
            )
            walk_result = service.run_walk_forward(
                strategy=strategy,
                price_data=price_data,
                fundamentals=fundamentals,
                config=walk,
            )
            sensitivity_result = service.run_parameter_sensitivity(
                strategy=strategy,
                price_data=price_data,
                fundamentals=fundamentals,
                config=sensitivity,
            )
        except Exception:
            return StrategyHealthRun(
                "error", None, None, None, "健檢執行失敗，標準回測結果仍保留。"
            )
        statuses = (oos.status, walk_result.status, sensitivity_result.status)
        status = "complete" if all(item == "ready" for item in statuses) else "partial"
        return StrategyHealthRun(status, oos, walk_result, sensitivity_result)

    @staticmethod
    def result_is_current(
        current: StrategyRunManifest, previous: StrategyRunManifest | None
    ) -> bool:
        if previous is None:
            return False
        ignored = {"status", "health_status", "warnings"}
        current_core = {key: value for key, value in current.core.items() if key not in ignored}
        previous_core = {key: value for key, value in previous.core.items() if key not in ignored}
        return _canonical_json(current_core) == _canonical_json(previous_core)


def _canonical(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _canonical_json(value: object) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_source(source: Mapping[str, object] | None) -> str | None:
    if not source:
        return None
    for key in ("source_type", "provider", "source"):
        value = source.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()[:120]
    return None


def _source_is_fresh(source: Mapping[str, object] | None) -> bool:
    if not source:
        return False
    value = source.get("end_date") or source.get("updated_at")
    if not value:
        return False
    try:
        parsed = pd.Timestamp(value)
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize("UTC")
        age = datetime.now(timezone.utc) - parsed.to_pydatetime().astimezone(timezone.utc)
        return 0 <= age.total_seconds() <= 7 * 24 * 60 * 60
    except (TypeError, ValueError):
        return False


def _market_value(market: str) -> str:
    if str(market).strip().upper() == "CONFLICT":
        return "CONFLICT"
    try:
        return Market.parse(market).value
    except ValueError:
        return "UNKNOWN"
