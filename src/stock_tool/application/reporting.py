"""Application boundary for deterministic, reproducible report packages."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any, Mapping

import pandas as pd

from stock_tool import __version__
from stock_tool.backtest.metrics import BenchmarkComparison, calculate_benchmark_comparison
from stock_tool.reports.models import (
    BenchmarkMetadata,
    ReportData,
    ReportPackage,
    ReproducibilityManifest,
    _canonical_manifest_value,
    _safe_manifest_mapping,
)


@dataclass(frozen=True, slots=True)
class ReplayVerification:
    """Structured deterministic replay outcome without modifying runtime data."""

    matches: bool
    mismatches: tuple[str, ...]
    expected_manifest_hash: str
    actual_manifest_hash: str


@dataclass(frozen=True, slots=True)
class ReportingService:
    """Build one immutable report package shared by every report exporter."""

    stocktool_version: str = __version__
    manifest_schema_version: int = 1

    def build_package(
        self,
        report_data: ReportData,
        *,
        benchmark_data: pd.DataFrame | None = None,
        benchmark_metadata: BenchmarkMetadata | None = None,
        provider_metadata: Mapping[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> ReportPackage:
        """Create a read-only report package without mutating caller inputs."""

        benchmark = benchmark_data.copy(deep=True) if benchmark_data is not None else None
        price_data = (
            report_data.price_data.copy(deep=True) if report_data.price_data is not None else None
        )
        technical = (
            report_data.technical_indicators.copy(deep=True)
            if report_data.technical_indicators is not None
            else None
        )
        fundamentals = (
            report_data.fundamental_scores.copy(deep=True)
            if report_data.fundamental_scores is not None
            else None
        )
        equity_curve = report_data.resolved_equity_curve()
        trade_log = report_data.resolved_trade_log()
        risk_alerts = report_data.resolved_risk_alerts()
        corporate_action_audit = report_data.resolved_corporate_action_audit()
        daily_reconciliation = report_data.resolved_daily_reconciliation()
        backtest_metrics = report_data.resolved_backtest_metrics()
        total_return = (
            report_data.backtest_result.metrics.total_return
            if report_data.backtest_result is not None
            else None
        )
        resolved_metadata = benchmark_metadata or report_data.benchmark_metadata
        comparison = _comparison_for_report(
            equity_curve,
            benchmark,
            total_return,
            strategy_return_basis=(
                report_data.backtest_result.return_basis
                if report_data.backtest_result is not None
                else None
            ),
            benchmark_return_basis=(
                (
                    resolved_metadata.return_basis
                    if resolved_metadata is not None and resolved_metadata.return_basis is not None
                    else (
                        report_data.backtest_result.return_basis
                        if report_data.backtest_result is not None
                        else None
                    )
                )
            ),
            benchmark_price_policy=(
                (
                    resolved_metadata.price_policy
                    if resolved_metadata is not None and resolved_metadata.price_policy is not None
                    else (
                        report_data.backtest_result.price_policy
                        if report_data.backtest_result is not None
                        else None
                    )
                )
            ),
            benchmark_source=(
                resolved_metadata.provider if resolved_metadata is not None else None
            ),
        )
        resolved_provider = provider_metadata or report_data.provider_metadata
        payload = self._manifest_payload(
            report_data,
            price_data=price_data,
            fundamentals=fundamentals,
            benchmark_data=benchmark,
            benchmark_metadata=resolved_metadata,
            provider_metadata=resolved_provider,
            comparison=comparison,
            trade_log=trade_log,
            equity_curve=equity_curve,
            risk_alerts=risk_alerts,
            corporate_action_audit=corporate_action_audit,
            daily_reconciliation=daily_reconciliation,
            backtest_metrics=backtest_metrics,
        )
        manifest = ReproducibilityManifest(payload=payload, generated_at=generated_at)
        data = replace(
            report_data,
            price_data=price_data,
            technical_indicators=technical,
            fundamental_scores=fundamentals,
            benchmark_data=benchmark,
            benchmark_metadata=resolved_metadata,
            benchmark_comparison=comparison,
            provider_metadata=_safe_manifest_mapping(resolved_provider or {}),
            reproducibility_manifest=manifest,
        )
        return ReportPackage(data=data, manifest=manifest)

    def _manifest_payload(
        self,
        report_data: ReportData,
        *,
        price_data: pd.DataFrame | None,
        fundamentals: pd.DataFrame | None,
        benchmark_data: pd.DataFrame | None,
        benchmark_metadata: BenchmarkMetadata | None,
        provider_metadata: Mapping[str, Any] | None,
        comparison: BenchmarkComparison,
        trade_log: pd.DataFrame,
        equity_curve: pd.DataFrame,
        risk_alerts: pd.DataFrame,
        corporate_action_audit: pd.DataFrame,
        daily_reconciliation: pd.DataFrame,
        backtest_metrics: pd.DataFrame,
    ) -> dict[str, Any]:
        metrics = (
            report_data.backtest_result.metrics if report_data.backtest_result is not None else None
        )
        parameters = (
            dict(report_data.parameters or {})
            if isinstance(report_data.parameters, Mapping)
            else {}
        )
        warnings = tuple((provider_metadata or {}).get("warnings", ()))
        missing = [comparison.missing_reason] if comparison.missing_reason else []
        output_summary = {
            "total_return": metrics.total_return if metrics is not None else None,
            "max_drawdown": metrics.max_drawdown if metrics is not None else None,
            "benchmark_total_return": comparison.total_return,
            "benchmark_max_drawdown": comparison.max_drawdown,
            "benchmark_excess_return": comparison.excess_return,
        }
        return {
            "manifest_schema_version": self.manifest_schema_version,
            "stocktool_version": self.stocktool_version,
            "report_type": "research_backtest",
            "symbol": report_data.symbol,
            "market": report_data.market or "UNKNOWN",
            "analysis_date": report_data.resolved_analysis_date(),
            "analysis_start_date": _frame_date(price_data, first=True),
            "analysis_end_date": _frame_date(price_data, first=False),
            "interval": parameters.get("interval", "1d"),
            "price_input_hash": canonical_dataframe_hash(price_data),
            "technical_input_hash": canonical_dataframe_hash(report_data.technical_indicators),
            "fundamental_input_hash": canonical_dataframe_hash(fundamentals),
            "benchmark_input_hash": canonical_dataframe_hash(benchmark_data),
            "research_input_hash": canonical_object_hash(
                {
                    "technical_summary": report_data.technical_summary,
                    "fundamental_summary": report_data.fundamental_summary,
                    "risk_summary": report_data.risk_summary,
                }
            ),
            "strategy": parameters.get("strategy"),
            "strategy_parameters": parameters.get("strategy_parameters", {}),
            "initial_cash": parameters.get("initial_cash"),
            "commission": parameters.get("commission_rate"),
            "tax": parameters.get("tax_rate"),
            "slippage": parameters.get("slippage_rate"),
            "execution_price_model": parameters.get("execution_price_col"),
            "stop_loss": parameters.get("stop_loss_pct"),
            "take_profit": parameters.get("take_profit_pct"),
            "trailing_stop": parameters.get("trailing_stop_pct"),
            "risk_configuration": parameters.get("risk_config", {}),
            "provider_metadata": _safe_manifest_mapping(provider_metadata or {}),
            "provider_attempts": _safe_manifest_mapping(
                {"attempts": (provider_metadata or {}).get("attempts", ())}
            )["attempts"],
            "data_quality_warnings": _canonical_manifest_value(warnings),
            "missing_data_reasons": missing,
            "calculation_version": "backtest_metrics_v1",
            "scoring_version": "stock_scoring_30_30_20_20",
            "output_hashes": {
                "trade_log": canonical_dataframe_hash(trade_log),
                "equity_curve": canonical_dataframe_hash(equity_curve),
                "risk_alerts": canonical_dataframe_hash(risk_alerts),
                "corporate_action_audit": canonical_dataframe_hash(corporate_action_audit),
                "daily_reconciliation": canonical_dataframe_hash(daily_reconciliation),
                "backtest_metrics": canonical_dataframe_hash(backtest_metrics),
            },
            "output_summary": output_summary,
            "output_summary_hash": canonical_object_hash(output_summary),
            "benchmark_metadata": benchmark_metadata.to_dict() if benchmark_metadata else None,
            "benchmark_alignment": {
                "available": comparison.available,
                "aligned_start_date": comparison.aligned_start_date,
                "aligned_end_date": comparison.aligned_end_date,
                "observations": comparison.observations,
                "missing_reason": comparison.missing_reason,
                "return_basis": comparison.return_basis,
                "price_policy": comparison.price_policy,
                "source": comparison.source,
            },
        }


def verify_report_replay(
    package: ReportPackage,
    report_data: ReportData,
    *,
    service: ReportingService,
) -> ReplayVerification:
    """Rebuild a package from supplied inputs and return structured mismatches."""

    replayed = service.build_package(
        report_data,
        benchmark_data=package.data.benchmark_data,
        benchmark_metadata=package.data.benchmark_metadata,
        provider_metadata=package.data.provider_metadata,
    )
    expected = package.manifest.payload
    actual = replayed.manifest.payload
    mismatches = tuple(
        key for key in sorted(set(expected) | set(actual)) if expected.get(key) != actual.get(key)
    )
    return ReplayVerification(
        matches=not mismatches,
        mismatches=mismatches,
        expected_manifest_hash=package.manifest.manifest_hash,
        actual_manifest_hash=replayed.manifest.manifest_hash,
    )


def canonical_dataframe_hash(frame: pd.DataFrame | None) -> str | None:
    """Hash a frame independent of input column and row order."""

    if frame is None:
        return None
    records = []
    original_columns = sorted(frame.columns, key=str)
    columns = [str(column) for column in original_columns]
    for _, row in frame.loc[:, original_columns].iterrows():
        records.append(
            {
                column: _canonical_dataframe_value(column, row[original_column])
                for column, original_column in zip(columns, original_columns)
            }
        )
    records.sort(key=lambda record: _canonical_json(record))
    return canonical_object_hash({"columns": columns, "rows": records})


def canonical_object_hash(value: Any) -> str:
    """Return a stable SHA-256 for canonical JSON-compatible values."""

    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest().upper()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_manifest_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _frame_date(frame: pd.DataFrame | None, *, first: bool) -> str | None:
    if frame is None or frame.empty or "date" not in frame.columns:
        return None
    dates = _normalize_trade_dates(frame["date"])
    if dates.isna().any():
        return None
    dates = dates.sort_values()
    if dates.empty:
        return None
    value = dates.iloc[0] if first else dates.iloc[-1]
    return value.date().isoformat()


def _normalize_trade_dates(values: pd.Series) -> pd.Series:
    """Normalize naive and timezone-aware trading dates to UTC-naive dates."""

    normalized = pd.to_datetime(values, errors="coerce", utc=True)
    return normalized.dt.tz_localize(None).dt.normalize()


def _canonical_dataframe_value(column: Any, value: Any) -> Any:
    """Canonicalize dates before applying the shared manifest value policy."""

    column_name = str(column).lower()
    if "date" in column_name or "日期" in str(column):
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
        if not pd.isna(parsed):
            return parsed.date().isoformat()
    return _canonical_manifest_value(value)


def _comparison_for_report(
    equity_curve: pd.DataFrame,
    benchmark_data: pd.DataFrame | None,
    total_return: float | None,
    *,
    strategy_return_basis: str | None,
    benchmark_return_basis: str | None,
    benchmark_price_policy: str | None,
    benchmark_source: str | None,
) -> BenchmarkComparison:
    if total_return is None:
        return BenchmarkComparison(
            False, None, None, None, None, None, 0, "strategy_backtest_unavailable"
        )
    return calculate_benchmark_comparison(
        equity_curve,
        benchmark_data,
        strategy_total_return=total_return,
        strategy_return_basis=strategy_return_basis,
        benchmark_return_basis=benchmark_return_basis,
        benchmark_price_policy=benchmark_price_policy,
        benchmark_source=benchmark_source,
    )
