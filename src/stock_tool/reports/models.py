"""Shared report data structures and conversion helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from stock_tool.backtest.engine import BacktestResult, TRAILING_STOP_DAILY_MODEL_NOTICE
from stock_tool.backtest.metrics import BenchmarkComparison, PerformanceMetrics
from stock_tool.backtest.orders import Trade
from stock_tool.data.contracts import sanitize_provider_text
from stock_tool.risk import RiskAlert

DISCLAIMER = "歷史績效不代表未來報酬。本報表僅供研究、學習與風險分析，不構成個人化投資建議。"
INSUFFICIENT_DATA = "資料不足"
SURVIVORSHIP_BIAS_WARNING = (
    "此回測可能受到存活者偏誤影響，因為沒有提供歷史當下成分股名單或下市證券資料。"
)
PARAMETER_LABELS = {
    "symbol": "股票代號",
    "strategy": "策略",
    "strategy_parameters": "策略參數",
    "initial_cash": "初始資金",
    "commission_rate": "手續費率",
    "tax_rate": "交易稅率",
    "slippage_rate": "滑價率",
    "execution_price_col": "成交價格欄位",
    "max_position_pct": "最大單一持股比例",
    "trailing_stop_pct": "移動停利比例",
    "trailing_take_profit_pct": "移動停利比例",
}
DISPLAY_COLUMN_LABELS = {
    "date": "日期",
    "symbol": "股票代號",
    "name": "名稱",
    "market": "市場代碼",
    "market_label": "市場",
    "exchange": "交易所",
    "industry": "產業",
    "industry_code": "產業代碼",
    "concept": "概念",
    "relation_type": "關聯類型",
    "price_reaction_stage": "股價反應階段",
    "stage_note": "階段說明",
    "keywords": "關鍵字",
    "source": "資料來源",
    "note": "備註",
    "match_score": "匹配分數",
    "match_reason": "匹配原因",
    "open": "開盤價",
    "high": "最高價",
    "low": "最低價",
    "close": "收盤價",
    "volume": "成交量",
    "adjusted_close": "調整後收盤價",
    "total_score": "總分",
    "available_score": "可用資料分數",
    "coverage": "資料覆蓋率",
    "growth_score": "成長性分數",
    "profitability_score": "獲利能力分數",
    "financial_safety_score": "財務安全分數",
    "valuation_score": "估值分數",
    "cashflow_score": "現金流分數",
    "strengths": "優勢",
    "weaknesses": "弱項",
    "missing_data": "缺漏資料",
    "risk_notes": "風險提示",
    "source_name": "來源檔名",
    "title": "標題",
    "report_date": "報告日期",
    "extracted_characters": "抽取字數",
    "key_points": "研究重點",
    "technology_points": "技術特點",
    "catalysts": "可能催化",
    "bottlenecks": "瓶頸 / 需要驗證",
    "message": "訊息",
    "severity": "嚴重程度",
    "code": "代碼",
    "order_id": "訂單編號",
    "side": "買賣方向",
    "quantity": "股數",
    "signal_date": "訊號日期",
    "execution_date": "成交日期",
    "execution_price": "成交價格",
    "gross_amount": "交易金額",
    "commission": "手續費",
    "tax": "交易稅",
    "slippage": "滑價成本",
    "net_cash_flow": "淨現金流",
    "realized_pnl": "已實現損益",
    "holding_days": "持有天數",
    "reason": "原因",
    "status": "狀態",
    "rejection_reason": "拒絕原因",
    "cash": "現金",
    "market_value": "持股市值",
    "total_equity": "總資產",
    "cash_ratio": "現金比例",
    "exposure": "曝險比例",
    "positions_count": "持股檔數",
    "drawdown": "回撤",
    "event_id": "事件識別碼",
    "action_type": "公司行動類型",
    "event_date": "事件生效日",
    "available_date": "可得日期",
    "payable_date": "實際入帳日",
    "price_policy": "價格政策",
    "return_basis": "報酬基準",
    "quantity_before": "調整前股數",
    "quantity_after": "調整後股數",
    "average_cost_before": "調整前平均成本",
    "average_cost_after": "調整後平均成本",
    "gross_cash_delta": "稅前現金變動",
    "net_cash_delta": "稅後現金變動",
    "holdings_market_value": "持股市值",
    "reconciled_equity": "對帳總資產",
    "difference": "對帳差異",
    "parameter": "參數",
    "value": "數值",
}
DISPLAY_VALUE_LABELS = {
    "buy": "買進",
    "sell": "賣出",
    "pending": "待處理",
    "filled": "已成交",
    "rejected": "已拒絕",
    "cancelled": "已取消",
    "signal": "策略訊號",
    "stop_loss": "停損",
    "take_profit": "停利",
    "trailing_stop": "移動停利",
    "info": "提示",
    "warning": "警告",
    "critical": "嚴重",
    "error": "錯誤",
}


@dataclass(frozen=True, slots=True)
class BenchmarkMetadata:
    """Safe provenance for a benchmark input used in one report package."""

    symbol: str
    market: str
    provider: str | None
    provider_symbol: str | None
    source_type: str
    start_date: str | None
    end_date: str | None
    interval: str
    row_count: int
    fetched_at: str | None = None
    updated_at: str | None = None
    warnings: tuple[str, ...] = ()
    return_basis: str | None = None
    price_policy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return sanitized, serializable benchmark provenance."""

        return {
            "symbol": self.symbol,
            "market": self.market,
            "provider": _safe_manifest_text(self.provider),
            "provider_symbol": _safe_manifest_text(self.provider_symbol),
            "source_type": self.source_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "interval": self.interval,
            "row_count": self.row_count,
            "fetched_at": self.fetched_at,
            "updated_at": self.updated_at,
            "warnings": [_safe_manifest_text(item) for item in self.warnings],
            "return_basis": self.return_basis,
            "price_policy": self.price_policy,
        }


@dataclass(frozen=True, slots=True)
class ReproducibilityManifest:
    """Versioned deterministic report manifest with a content hash."""

    payload: Mapping[str, Any]
    generated_at: str | None = None

    def __post_init__(self) -> None:
        canonical_payload = _canonical_manifest_value(dict(self.payload))
        object.__setattr__(self, "payload", canonical_payload)

    @property
    def canonical_json(self) -> str:
        """Return stable JSON excluding runtime-only generation time."""

        return json.dumps(self.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def manifest_hash(self) -> str:
        """Return deterministic SHA-256 for the canonical manifest payload."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest().upper()

    def to_dict(self) -> dict[str, Any]:
        """Serialize manifest payload and optional non-deterministic timestamp."""

        return {
            "manifest": self.payload,
            "manifest_hash": self.manifest_hash,
            "generated_at": self.generated_at,
        }


@dataclass(frozen=True, slots=True)
class ReportPackage:
    """Immutable canonical input shared by Excel, HTML, and replay checks."""

    data: "ReportData"
    manifest: ReproducibilityManifest

    @property
    def benchmark(self) -> BenchmarkComparison:
        """Return the one canonical benchmark comparison in the package."""

        if self.data.benchmark_comparison is None:
            raise ValueError("ReportPackage is missing its canonical benchmark comparison.")
        return self.data.benchmark_comparison


def unpack_report_input(report_input: "ReportData | ReportPackage") -> "ReportData":
    """Keep legacy exporters compatible while accepting canonical packages."""

    return report_input.data if isinstance(report_input, ReportPackage) else report_input


@dataclass(frozen=True)
class ReportData:
    """Input bundle for Excel and HTML reports."""

    symbol: str
    analysis_date: str | None = None
    price_data: pd.DataFrame | None = None
    technical_indicators: pd.DataFrame | None = None
    fundamental_scores: pd.DataFrame | None = None
    backtest_result: BacktestResult | None = None
    trade_log: pd.DataFrame | None = None
    equity_curve: pd.DataFrame | None = None
    risk_alerts: Sequence[RiskAlert] | pd.DataFrame | None = None
    parameters: Mapping[str, Any] | pd.DataFrame | None = None
    technical_summary: str | None = None
    fundamental_summary: str | None = None
    risk_summary: str | None = None
    backtest_summary: str | None = None
    point_in_time_universe: str | None = None
    market: str | None = None
    benchmark_data: pd.DataFrame | None = None
    benchmark_metadata: BenchmarkMetadata | None = None
    benchmark_comparison: BenchmarkComparison | None = None
    provider_metadata: Mapping[str, Any] | None = None
    reproducibility_manifest: ReproducibilityManifest | None = None

    def resolved_analysis_date(self) -> str:
        """Return explicit analysis date or today's ISO date."""

        return self.analysis_date or date.today().isoformat()

    def resolved_trade_log(self) -> pd.DataFrame:
        """Return trade log from explicit data or a backtest result."""

        if self.trade_log is not None:
            return self.trade_log.copy(deep=True)
        if self.backtest_result is None:
            return empty_table("交易紀錄")
        return trades_to_frame(self.backtest_result.trades)

    def resolved_equity_curve(self) -> pd.DataFrame:
        """Return equity curve from explicit data or a backtest result."""

        if self.equity_curve is not None:
            return self.equity_curve.copy(deep=True)
        if self.backtest_result is None:
            return empty_table("資金曲線")
        return self.backtest_result.equity_curve.copy(deep=True)

    def resolved_corporate_action_audit(self) -> pd.DataFrame:
        """Return applied and unavailable corporate-action records when present."""

        if self.backtest_result is None or self.backtest_result.corporate_action_audit.empty:
            return empty_table("公司行動稽核")
        return self.backtest_result.corporate_action_audit.copy(deep=True)

    def resolved_daily_reconciliation(self) -> pd.DataFrame:
        """Return daily cash-plus-holdings reconciliation when a backtest exists."""

        if self.backtest_result is None or self.backtest_result.daily_reconciliation.empty:
            return empty_table("每日資產對帳")
        return self.backtest_result.daily_reconciliation.copy(deep=True)

    def resolved_backtest_metrics(self) -> pd.DataFrame:
        """Return backtest metric summary as a two-column table."""

        if self.backtest_result is None:
            return empty_table("回測結果")
        metrics = self.backtest_result.metrics
        comparison = self.benchmark_comparison
        if comparison is not None:
            metrics = replace(
                metrics,
                benchmark_total_return=comparison.total_return,
                benchmark_max_drawdown=comparison.max_drawdown,
                benchmark_excess_return=comparison.excess_return,
                benchmark_aligned_start_date=comparison.aligned_start_date,
                benchmark_aligned_end_date=comparison.aligned_end_date,
                benchmark_observations=comparison.observations,
                benchmark_missing_reason=comparison.missing_reason,
            )
        return metrics_to_frame(metrics)

    def resolved_risk_alerts(self) -> pd.DataFrame:
        """Return risk alerts as a table, including unresolved research-bias warnings."""

        base_alerts = risk_alerts_to_frame(self.risk_alerts)
        research_limit_alerts = (
            *self.survivorship_bias_alerts(),
            *self.trailing_stop_model_alerts(),
        )
        if not research_limit_alerts:
            return base_alerts

        research_limit_frame = risk_alerts_to_frame(research_limit_alerts)
        if _is_placeholder_risk_alerts(base_alerts):
            return research_limit_frame
        return pd.concat([base_alerts, research_limit_frame], ignore_index=True, sort=False)

    def survivorship_bias_alerts(self) -> tuple[RiskAlert, ...]:
        """Return survivorship-bias warnings when no historical universe is supplied."""

        if self.backtest_result is None or self.point_in_time_universe:
            return ()
        return (
            RiskAlert(
                code="survivorship_bias",
                severity="warning",
                message=SURVIVORSHIP_BIAS_WARNING,
                symbol=self.symbol,
            ),
        )

    def trailing_stop_model_alerts(self) -> tuple[RiskAlert, ...]:
        """Return a report disclosure when trailing stop is enabled."""

        if self.backtest_result is None or not _parameters_enable_trailing_stop(self.parameters):
            return ()
        return (
            RiskAlert(
                code="trailing_stop_daily_model",
                severity="info",
                message=TRAILING_STOP_DAILY_MODEL_NOTICE,
                symbol=self.symbol,
            ),
        )

    def resolved_parameters(self) -> pd.DataFrame:
        """Return report parameters as a table."""

        return parameters_to_frame(self.parameters)

    def resolved_benchmark_comparison(self) -> pd.DataFrame:
        """Return benchmark values or an explicit insufficient-data table."""

        comparison = self.benchmark_comparison
        if comparison is None or not comparison.available:
            reason = (
                comparison.missing_reason if comparison is not None else "benchmark_unavailable"
            )
            return pd.DataFrame(
                {
                    "項目": ["基準比較"],
                    "數值": [INSUFFICIENT_DATA],
                    "原因": [reason],
                }
            )
        return pd.DataFrame(
            [
                ("基準總報酬率", format_percent(comparison.total_return)),
                ("基準最大回撤", format_percent(comparison.max_drawdown)),
                ("策略超額報酬", format_percent(comparison.excess_return)),
                ("對齊起日", comparison.aligned_start_date),
                ("對齊迄日", comparison.aligned_end_date),
                ("有效觀測筆數", comparison.observations),
                ("報酬基準", comparison.return_basis or INSUFFICIENT_DATA),
                ("價格政策", comparison.price_policy or INSUFFICIENT_DATA),
                ("基準來源", comparison.source or INSUFFICIENT_DATA),
            ],
            columns=["項目", "數值"],
        )

    def resolved_data_sources(self) -> pd.DataFrame:
        """Return report-safe provider and benchmark provenance."""

        rows: list[dict[str, Any]] = []
        if self.provider_metadata:
            rows.append({"類型": "研究資料", **_safe_manifest_mapping(self.provider_metadata)})
        if self.benchmark_metadata is not None:
            rows.append({"類型": "基準資料", **self.benchmark_metadata.to_dict()})
        return pd.DataFrame(rows) if rows else empty_table("資料來源")

    def resolved_data_quality(self) -> pd.DataFrame:
        """Return warnings and structured missing-data reasons for reports."""

        rows: list[dict[str, str]] = []
        if self.benchmark_comparison and self.benchmark_comparison.missing_reason:
            rows.append({"類型": "benchmark", "內容": self.benchmark_comparison.missing_reason})
        if self.reproducibility_manifest:
            payload = self.reproducibility_manifest.payload
            for warning in payload.get("data_quality_warnings", []):
                rows.append({"類型": "warning", "內容": str(warning)})
            for reason in payload.get("missing_data_reasons", []):
                rows.append({"類型": "missing_data", "內容": str(reason)})
        return pd.DataFrame(rows) if rows else empty_table("資料品質")

    def resolved_manifest(self) -> pd.DataFrame:
        """Return a flattened manifest table without exposing raw inputs."""

        if self.reproducibility_manifest is None:
            return empty_table("可重現性 Manifest")
        rows = _flatten_manifest(self.reproducibility_manifest.payload)
        rows.append({"欄位": "manifest_hash", "數值": self.reproducibility_manifest.manifest_hash})
        rows.append(
            {
                "欄位": "generated_at",
                "數值": self.reproducibility_manifest.generated_at or INSUFFICIENT_DATA,
            }
        )
        return pd.DataFrame(rows)


def empty_table(label: str) -> pd.DataFrame:
    """Return a standard insufficient-data table."""

    return pd.DataFrame({"訊息": [f"{label}: {INSUFFICIENT_DATA}"]})


def ensure_table(data: pd.DataFrame | None, label: str) -> pd.DataFrame:
    """Return a defensive copy or an insufficient-data table."""

    if data is None or data.empty:
        return empty_table(label)
    return data.copy(deep=True)


def data_period(price_data: pd.DataFrame | None) -> str:
    """Return the date range covered by price data."""

    if price_data is None or price_data.empty or "date" not in price_data.columns:
        return INSUFFICIENT_DATA
    dates = pd.to_datetime(price_data["date"], errors="coerce").dropna()
    if dates.empty:
        return INSUFFICIENT_DATA
    return f"{dates.min().date().isoformat()} ~ {dates.max().date().isoformat()}"


def metrics_to_frame(metrics: PerformanceMetrics) -> pd.DataFrame:
    """Convert performance metrics into a formatted DataFrame."""

    rows = [
        ("總報酬率", format_percent(metrics.total_return)),
        ("年化報酬率", format_percent(metrics.cagr)),
        ("年化波動率", format_percent(metrics.annualized_volatility)),
        ("夏普比率", format_number(metrics.sharpe_ratio)),
        ("Sortino 比率", format_number(metrics.sortino_ratio)),
        ("最大回撤", format_percent(metrics.max_drawdown)),
        ("勝率", format_percent(metrics.win_rate)),
        ("盈虧比", format_number(metrics.profit_factor)),
        ("平均持有天數", format_number(metrics.average_holding_period)),
        ("交易次數", str(metrics.number_of_trades)),
        ("曝險比例", format_percent(metrics.exposure)),
        ("基準總報酬率", format_percent(metrics.benchmark_total_return)),
        ("基準最大回撤", format_percent(metrics.benchmark_max_drawdown)),
        ("基準超額報酬", format_percent(metrics.benchmark_excess_return)),
    ]
    return pd.DataFrame(rows, columns=["指標", "數值"])


def trades_to_frame(trades: Sequence[Trade]) -> pd.DataFrame:
    """Convert trade dataclasses into a DataFrame."""

    if not trades:
        return empty_table("交易紀錄")
    return localize_display_frame(pd.DataFrame([asdict(trade) for trade in trades]))


def risk_alerts_to_frame(alerts: Sequence[RiskAlert] | pd.DataFrame | None) -> pd.DataFrame:
    """Convert risk alerts into a DataFrame."""

    if alerts is None:
        return empty_table("風險提示")
    if isinstance(alerts, pd.DataFrame):
        return localize_display_frame(ensure_table(alerts, "風險提示"))
    if not alerts:
        return pd.DataFrame({"嚴重程度": ["提示"], "訊息": ["目前沒有風險警示"]})
    return localize_display_frame(pd.DataFrame([asdict(alert) for alert in alerts]))


def localize_display_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Return a copy with common user-facing columns and enum values translated."""

    if frame is None:
        return pd.DataFrame()
    display = frame.copy(deep=True)
    for column in ("side", "status", "reason", "severity"):
        if column in display.columns:
            display[column] = display[column].map(_localize_display_value).fillna(display[column])
    return display.rename(columns=DISPLAY_COLUMN_LABELS)


def _localize_display_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return DISPLAY_VALUE_LABELS.get(value.strip().lower(), value)


def _is_placeholder_risk_alerts(frame: pd.DataFrame) -> bool:
    """Return whether a risk-alert table only contains a no-data/no-alert placeholder."""

    if frame.empty:
        return True
    if len(frame) != 1:
        return False
    columns = set(frame.columns)
    if columns == {"message"}:
        return str(frame.iloc[0]["message"]).startswith("風險提示:")
    if columns == {"訊息"}:
        return str(frame.iloc[0]["訊息"]).startswith("風險提示:")
    if {"severity", "message"}.issubset(columns):
        return (
            str(frame.iloc[0]["severity"]) == "info"
            and str(frame.iloc[0]["message"]) == "目前沒有風險警示"
        )
    if {"嚴重程度", "訊息"}.issubset(columns):
        return (
            str(frame.iloc[0]["嚴重程度"]) == "提示"
            and str(frame.iloc[0]["訊息"]) == "目前沒有風險警示"
        )
    return False


def _parameters_enable_trailing_stop(parameters: Mapping[str, Any] | pd.DataFrame | None) -> bool:
    """Return whether report parameters indicate trailing stop was enabled."""

    trailing_keys = {"trailing_stop_pct", "trailing_take_profit_pct"}
    if parameters is None:
        return False
    if isinstance(parameters, Mapping):
        return any(_is_enabled_parameter(parameters.get(key)) for key in trailing_keys)
    if isinstance(parameters, pd.DataFrame) and {"parameter", "value"}.issubset(parameters.columns):
        rows = parameters.loc[parameters["parameter"].astype(str).isin(trailing_keys), "value"]
        return any(_is_enabled_parameter(value) for value in rows)
    return False


def _is_enabled_parameter(value: Any) -> bool:
    if value is None:
        return False
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "none", "null", "false", "0", "0.0"}:
            return False
        try:
            return float(normalized) > 0
        except ValueError:
            return True
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return bool(value)


def parameters_to_frame(parameters: Mapping[str, Any] | pd.DataFrame | None) -> pd.DataFrame:
    """Convert report parameters into a DataFrame."""

    if parameters is None:
        return empty_table("參數")
    if isinstance(parameters, pd.DataFrame):
        return ensure_table(parameters, "參數")
    if not parameters:
        return empty_table("參數")
    return pd.DataFrame(
        [
            {"參數": PARAMETER_LABELS.get(str(key), str(key)), "數值": _stringify(value)}
            for key, value in parameters.items()
        ]
    )


def format_percent(value: Any, decimals: int = 2) -> str:
    """Format a decimal value as a percentage."""

    if value is None or pd.isna(value):
        return INSUFFICIENT_DATA
    return f"{float(value) * 100:.{decimals}f}%"


def format_number(value: Any, decimals: int = 2) -> str:
    """Format numeric values with a fixed number of decimals."""

    if value is None or pd.isna(value):
        return INSUFFICIENT_DATA
    if value == float("inf"):
        return "∞"
    return f"{float(value):.{decimals}f}"


def format_value(value: Any) -> str:
    """Format arbitrary report cell values."""

    if value is None or pd.isna(value):
        return INSUFFICIENT_DATA
    if isinstance(value, float):
        return format_number(value)
    return str(value)


def _stringify(value: Any) -> str:
    if value is None:
        return INSUFFICIENT_DATA
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, Mapping):
        return "; ".join(f"{key}={val}" for key, val in value.items())
    return str(value)


def _safe_manifest_text(value: Any) -> str | None:
    """Apply provider redaction and exclude absolute filesystem paths."""

    if value is None:
        return None
    text = sanitize_provider_text(str(value))
    if re.search(r"(?i)(?:[a-z]:[\\/]|\\\\[^\\/]+[\\/])", text):
        return "[PATH_REDACTED]"
    return text


def _safe_manifest_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively sanitize safe metadata before report display or hashing."""

    return {str(key): _canonical_manifest_value(value) for key, value in mapping.items()}


def _canonical_manifest_value(value: Any) -> Any:
    """Convert report inputs into deterministic, secret-safe JSON values."""

    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): _canonical_manifest_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical_manifest_value(item) for item in value]
    if isinstance(value, set):
        values = [_canonical_manifest_value(item) for item in value]
        return sorted(
            values,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        )
    if isinstance(value, pd.Timestamp):
        timestamp = value.tz_convert("UTC") if value.tzinfo is not None else value
        return timestamp.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return "[PATH_REDACTED]"
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return format(float(value), ".15g")
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return _safe_manifest_text(value)


def _flatten_manifest(payload: Mapping[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    """Flatten canonical manifest data into a readable two-column table."""

    rows: list[dict[str, Any]] = []
    for key in sorted(payload):
        value = payload[key]
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            rows.extend(_flatten_manifest(value, name))
        else:
            rows.append({"欄位": name, "數值": _stringify(value)})
    return rows
