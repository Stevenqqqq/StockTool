"""Streamlit dashboard for local stock research workflows."""

# ruff: noqa: E402

from __future__ import annotations

import os
import sys
import tempfile
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO, Mapping, Sequence, cast

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stock_tool.backtest import BacktestEngine, BacktestResult
from stock_tool.application.daily_brief import (
    DailyBrief,
    DailyBriefService,
    DailyRefreshRecord,
    DailyRefreshResult,
    DailyRefreshService,
    ResearchContinuation,
)
from stock_tool.application.daily_research_loop import (
    DailyResearchLoopResult,
    DailyResearchLoopService,
    DailyResearchSnapshotStore,
    DailyResearchSource,
)
from stock_tool.application.daily_research_brief import (
    DailyResearchBrief,
    DailyResearchBriefApplicationService,
    DailyResearchBriefStore,
)
from stock_tool.application.daily_research_changes import (
    DailyResearchChangeApplicationService,
    DailyResearchChangeStore,
)
from stock_tool.application.macro_snapshot import (
    MacroRevisionLedgerStore,
    MacroRuleRegistry,
    MacroSnapshot,
    MacroSnapshotApplicationService,
    MacroSnapshotStore,
    build_macro_links,
)
from stock_tool.application.market_monitor import (
    MarketMonitorApplicationService,
    load_local_classifications,
)
from stock_tool.application.data_hydration import DataHydrationService
from stock_tool.application.research_snapshot import (
    ResearchSourceMetadata,
    ResearchWorkspaceService,
)
from stock_tool.research.assistant import (
    AIResearchAssistant,
    DailyResearchAssistantBrief,
    DailyResearchAssistantService,
    ResearchAssistantCache,
)
from stock_tool.application.results import DataHydrationRequest
from stock_tool.application.reporting import ReportingService
from stock_tool.application.portfolio import PortfolioLedgerService
from stock_tool.application.settings_workspace import (
    SettingsWorkspaceApplicationService,
    SettingsWorkspaceSnapshot,
)
from stock_tool.application.daily_research_scheduler import DailyScheduleApplicationService
from stock_tool.application.daily_research_runner import DailyResearchRunner
from stock_tool.application.daily_research_inbox import (
    DailyResearchInboxService,
    DailyResearchNotificationService,
)
from stock_tool.application.prediction_lab import (
    BenchmarkRefreshService,
    PredictionLabApplicationService,
    PredictionOutcomeEvaluator,
    PredictionOutcomeEvaluationResult,
    PredictionLabStore,
    PredictionLabSummary,
    RuntimeCachedOutcomeProvider,
    build_runtime_cached_outcome_provider,
    economic_input_fingerprint,
)
from stock_tool.application.portfolio_risk import PortfolioRiskResult, PortfolioRiskService
from stock_tool.company_research import CompanyResearchProfile, build_company_research_profile
from stock_tool.concepts import (
    concept_market_summary,
    lookup_concept_stocks_online,
)
from stock_tool.data.auto_fetch import (
    DataFetchError,
    Market as ProviderMarket,
    ProviderChoice,
    default_date_range,
    fetch_prices,
    fetch_prices_result,
    normalize_yfinance_symbol,
    yfinance_symbol_candidates,
)
from stock_tool.data.cleaner import DataValidationError, PriceDataWarning, clean_price_data
from stock_tool.data.contracts import sanitize_provider_text
from stock_tool.data.policies import ProviderHealthTracker
from stock_tool.data.loader import COLUMN_ALIASES, REQUIRED_COLUMNS, STANDARD_COLUMNS
from stock_tool.data.storage import PersistedPriceProvenance, SQLitePriceStorage
from stock_tool.data.repositories import ResearchIdentity, ResearchRepository, RepositoryDataError
from stock_tool.concept_repository import ConceptRepository, seed_bundled_dataset
from stock_tool.dashboard.pages.discovery import render_discovery
from stock_tool.domain.models import Market, Symbol
from stock_tool.entry_reference import EntryReference, estimate_entry_reference
from stock_tool.fundamentals import (
    FUNDAMENTAL_COLUMNS,
    FundamentalFetchError,
    fetch_yfinance_fundamentals,
    load_fundamentals_csv,
    score_fundamentals,
)
from stock_tool.indicators import (
    add_atr,
    add_bias,
    add_bollinger_bands,
    add_ema,
    add_macd,
    add_rolling_return,
    add_rolling_volatility,
    add_rsi,
    add_sma,
    add_stochastic_oscillator,
    add_volume_moving_average,
)
from stock_tool.reports import (
    ReportData,
    TRAILING_STOP_DAILY_MODEL_NOTICE,
    generate_excel_report,
    localize_display_frame,
)
from stock_tool.research_reports import (
    REPORT_DISCLAIMER,
    ResearchReportSummary,
    build_public_report_search_links,
    research_report_summaries_to_frame,
    summarize_pdf_report,
)
from stock_tool.risk import RiskConfig, RiskManager
from stock_tool.serenity_agent import (
    SerenityAgentResult,
    run_serenity_agent,
    serenity_factors_frame,
)
from stock_tool.screener import ScreenerCriteria, screen_stocks
from stock_tool.stock_scoring import score_components_frame, score_stock
from stock_tool.strategies import (
    FundamentalGrowthStrategy,
    create_strategy,
    strategy_display_labels,
)
from stock_tool.dashboard.pages.strategy import render_strategy_health
from stock_tool.portfolio_management import (
    add_portfolio_position,
    load_portfolio,
    normalize_portfolio,
    portfolio_summary,
    remove_portfolio_position,
    save_portfolio,
)
from stock_tool.portfolio_health import PortfolioHealthService
from stock_tool.portfolio_analytics import (
    build_portfolio_data_gaps,
    build_portfolio_risk_inputs,
)
from stock_tool.portfolio_research import build_portfolio_research_brief
from stock_tool.portfolio_stress import PortfolioStressService, StressScenario, StressScenarioType
from stock_tool.portfolio_valuation import (
    Currency,
    FxQuote,
    PortfolioValuationConfig,
    PortfolioValuationService,
)
from stock_tool.portfolio_fx import (
    DEFAULT_FX_CACHE_TTL_SECONDS,
    FxResolution,
    JsonFxQuoteCache,
    UsdTwdFxResolutionService,
    YFinanceUsdTwdProvider,
    fx_provider_from_resolution,
    is_fx_retrieval_fresh,
)
from stock_tool.portfolio_refresh import PortfolioRefreshResult, PortfolioRefreshService
from stock_tool.runtime_paths import RuntimePaths, default_runtime_paths
from stock_tool.dashboard.shell import (
    DashboardShellDependencies,
    render_dashboard_shell,
    render_legacy_dashboard,
    synchronize_existing_session_status,
)
from stock_tool.dashboard.backtest_ui import (
    BacktestCostPreset,
    BacktestFormValues,
    BacktestRunBinding,
    BacktestSummary,
    BacktestValidationResult,
    BACKTEST_RESEARCH_NOTICE,
    build_backtest_run_binding,
    build_backtest_summary,
    cost_assumptions,
    percent_to_rate,
    no_trade_explanation,
    rate_to_percent,
    resolve_backtest_result_display,
    resolve_cost_preset,
    strategy_guidance,
    validate_backtest_form,
)
from stock_tool.dashboard.portfolio_guidance import (
    PORTFOLIO_RISK_INDEPENDENCE_NOTICE,
    portfolio_missing_data_guidance,
)
from stock_tool.dashboard.state import initialize_dashboard_state
from stock_tool.dashboard.styles import apply_dashboard_styles
from stock_tool.watchlist import (
    add_watchlist_symbol,
    build_effective_watchlist,
    load_watchlist,
    remove_watchlist_symbol,
    save_watchlist,
)

APP_TITLE = "股票分析與回測儀表板"
RISK_NOTICE = "本工具僅供研究、學習與風險分析。歷史績效不代表未來報酬，且不構成個人化投資建議。"
INSUFFICIENT_DATA = "資料不足"
TRAILING_STOP_NOTICE = TRAILING_STOP_DAILY_MODEL_NOTICE
APP_ROOT = Path.cwd()
PACKAGE_ROOT = SRC_ROOT.parent
DATA_ROOT = APP_ROOT / "data" if (APP_ROOT / "data").exists() else PACKAGE_ROOT / "data"
SAMPLE_PRICE_FILE = DATA_ROOT / "sample" / "sample_tw_prices_for_indicators.csv"
SAMPLE_FUNDAMENTAL_FILE = DATA_ROOT / "sample" / "sample_fundamentals.csv"
CONCEPT_STOCK_FILE = DATA_ROOT / "sample" / "concept_stocks.csv"
CANONICAL_MARKETS = frozenset({Market.TWSE.value, Market.TPEX.value, Market.US.value})
BACKTEST_STRATEGY_LABELS = strategy_display_labels()


def _runtime_paths() -> RuntimePaths:
    """Resolve mutable paths at use time so isolation overrides are honored."""

    return default_runtime_paths()


def _stable_entry_for_schedule() -> Path:
    """Resolve the stable entry used by Task Scheduler without hard-coding a version."""

    override = os.environ.get("STOCK_TOOL_STABLE_ENTRY", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parents[2] / "StockTool.exe"
    return Path(__file__).resolve().parents[3] / "stable_launcher.py"


# These compatibility seams remain patchable for legacy module-level tests.  They
# are intentionally unset by default, so normal execution always resolves the
# current STOCK_TOOL_USER_DATA_DIR at call time.
DEFAULT_DATABASE: Path | None = None
AUTO_FUNDAMENTAL_FILE: Path | None = None
PORTFOLIO_FILE: Path | None = None
WATCHLIST_FILE: Path | None = None


def _runtime_database_path() -> Path:
    """Return the processed SQLite path for the current runtime environment."""

    return DEFAULT_DATABASE or (_runtime_paths().processed_dir / "stock_data.sqlite")


def _refresh_settings_workspace() -> SettingsWorkspaceSnapshot:
    """Explicitly re-read local diagnostics without performing network I/O."""

    paths = RuntimePaths.from_environment()
    return SettingsWorkspaceApplicationService(
        paths,
        database_path=paths.processed_dir / "stock_data.sqlite",
    ).refresh()


def _runtime_fundamentals_path() -> Path:
    """Return the auto-fundamentals path for the current runtime environment."""

    return AUTO_FUNDAMENTAL_FILE or (_runtime_paths().processed_dir / "fundamentals_auto.csv")


def _runtime_portfolio_path() -> Path:
    """Return the current runtime portfolio path, honoring legacy test overrides."""

    return PORTFOLIO_FILE or _runtime_paths().portfolio_file


def _runtime_watchlist_path() -> Path:
    """Return the current runtime watchlist path, honoring legacy test overrides."""

    return WATCHLIST_FILE or _runtime_paths().watchlist_file


def main() -> None:
    """Run the Streamlit dashboard."""

    st = _streamlit()
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    _init_state(st)
    apply_dashboard_styles(st)

    dependencies = DashboardShellDependencies(
        ensure_symbol_data=_ensure_symbol_data,
        render_legacy_page=_render_legacy_page,
        portfolio_path=_runtime_portfolio_path(),
        watchlist_path=_runtime_watchlist_path(),
        risk_notice=RISK_NOTICE,
        app_title=APP_TITLE,
        logger=logging.getLogger(__name__),
        build_research_snapshot=_build_research_snapshot,
        build_daily_brief=_build_daily_brief,
        build_daily_research_loop=_build_daily_research_loop,
        refresh_daily_data=_refresh_daily_data,
        run_daily_research=lambda: _run_daily_research(st),
        build_daily_research_run=lambda: DailyResearchRunner(
            _runtime_paths(), now_fn=lambda: datetime.now(timezone.utc)
        ).latest_manifest(),
        generate_daily_ai_research=_generate_daily_ai_research,
        build_daily_evidence_brief=_build_daily_evidence_brief,
        generate_daily_evidence_brief=_generate_daily_evidence_brief,
        concept_path=CONCEPT_STOCK_FILE,
        refresh_portfolio_data=_refresh_portfolio_analysis,
        build_portfolio_classifications=_portfolio_risk_classifications,
        refresh_settings_workspace=_refresh_settings_workspace,
        daily_schedule_service=DailyScheduleApplicationService(
            _runtime_paths(), stable_entry=_stable_entry_for_schedule()
        ),
        daily_research_inbox_service=DailyResearchInboxService(_runtime_paths()),
        daily_notification_service=DailyResearchNotificationService(_runtime_paths()),
        build_macro_snapshot=_build_macro_snapshot,
        build_macro_links=_build_macro_links,
        build_macro_revisions=_build_macro_revisions,
        refresh_macro_snapshot=_refresh_macro_snapshot,
        build_prediction_lab_summary=_build_prediction_lab_summary,
        evaluate_prediction_outcomes=_evaluate_prediction_outcomes,
    )
    if st.session_state.legacy_dashboard:
        render_legacy_dashboard(st, dependencies)
        return
    render_dashboard_shell(st, dependencies)


def _streamlit() -> Any:
    try:
        import streamlit as st
    except ImportError as exc:
        raise ImportError(
            "Streamlit 儀表板需要安裝 streamlit。請先安裝依賴後執行："
            "streamlit run src/stock_tool/dashboard/app.py"
        ) from exc
    return st


def _init_state(st: Any) -> None:
    defaults: dict[str, Any] = {
        "price_data": None,
        "technical_indicators": None,
        "fundamentals": None,
        "fundamental_scores": None,
        "backtest_result": None,
        "backtest_run_binding": None,
        "signals": None,
        "risk_alerts": tuple(),
        "last_parameters": {},
        "watchlist": None,
        "portfolio": None,
        "price_data_source": None,
        "active_symbol": None,
        "last_auto_hydration": None,
        "concept_lookup_result": None,
        "concept_update_log": None,
        "company_research_cache": {},
        "research_report_summaries": [],
        "portfolio_manual_usd_twd": 0.0,
        "portfolio_manual_fx_applied_at": None,
        "portfolio_fx_resolution": None,
        "portfolio_refresh_result": None,
        "portfolio_force_refresh": False,
        "research_snapshot": None,
        "provider_health_tracker": None,
        "dashboard_daily_research_loop": None,
        "dashboard_ai_research_brief": None,
        "dashboard_research_snapshots": {},
        "dashboard_daily_evidence_brief": None,
        "dashboard_daily_run_outcome": None,
        "dashboard_daily_run_manifest": None,
        "dashboard_macro_snapshot": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    initialize_dashboard_state(st.session_state)
    if st.session_state.provider_health_tracker is None:
        st.session_state.provider_health_tracker = ProviderHealthTracker()

    if st.session_state.price_data is None:
        imported_prices = _load_default_database_prices(_runtime_database_path())
        if imported_prices is not None:
            _set_price_data(
                st,
                imported_prices,
                source_type="SQLite 匯入資料",
                provider="sqlite",
                cache_file=None,
                start_date=str(imported_prices["date"].min()),
                end_date=str(imported_prices["date"].max()),
                warnings=tuple(imported_prices.attrs.get("price_identity_warnings") or ()),
            )
    if st.session_state.fundamentals is None:
        try:
            fundamentals = _load_all_fundamentals()
            if fundamentals is not None and not fundamentals.empty:
                _set_fundamentals_state(st, fundamentals)
        except Exception:
            pass
    synchronize_existing_session_status(st)


def _render_legacy_page(st: Any, page: str) -> None:
    """Route one retained page without duplicating its existing implementation."""

    routes = {
        "首頁儀表板": _page_home,
        "資料匯入": _page_import,
        "自動抓資料": _page_auto_fetch,
        "產業 / 概念股查詢": _page_concept_lookup,
        "自選股清單": _page_watchlist,
        "單檔股票分析": _page_single_stock,
        "技術指標": _page_indicators,
        "AI 分析與評分": _page_ai_analysis,
        "研究報告摘要": _page_research_reports,
        "股票篩選器": _page_screener,
        "基本面評分": _page_fundamentals,
        "策略回測": _page_backtest,
        "投資組合管理": _page_portfolio,
        "投資組合風險": _page_risk,
        "報表下載": _page_reports,
    }
    routes[page](st)


def _display_metric_cards(st: Any, metrics: list[tuple[str, Any]]) -> None:
    """Display a compact row of Streamlit metric cards."""

    columns = st.columns(len(metrics))
    for column, (label, value) in zip(columns, metrics):
        column.metric(label, value)


def _display_table(st: Any, frame: pd.DataFrame) -> None:
    """Display a DataFrame with consistent dashboard table settings."""

    st.dataframe(localize_display_frame(frame), use_container_width=True)


def _display_warnings(st: Any, messages: list[str], limit: int = 10) -> None:
    """Display a bounded list of warning messages."""

    for message in messages[:limit]:
        st.warning(message)


def _auto_hydration_panel(st: Any, *, key_prefix: str) -> None:
    """Render a one-box workflow that fetches missing price/fundamental data."""

    with st.expander("全自動查詢 / 補資料", expanded=False):
        st.caption(
            "輸入股票後會先查本機 SQLite；沒有股價會自動下載，能取得的基本面會以盡力補齊方式補上。"
        )
        col1, col2, col3 = st.columns([1.2, 1, 1])
        symbol = col1.text_input("股票代號", value="2330", key=f"{key_prefix}_auto_symbol")
        market_label = col2.selectbox(
            "市場",
            ["台股上市 TWSE", "台股上櫃 TPEx", "美股 US"],
            key=f"{key_prefix}_auto_market",
        )
        force_refresh = col3.checkbox("重新下載", value=False, key=f"{key_prefix}_auto_force")
        if st.button("自動查資料並更新分析", key=f"{key_prefix}_auto_button", type="primary"):
            try:
                result = _ensure_symbol_data(
                    st,
                    symbol=symbol,
                    market=_plain_market_code(market_label),
                    force_refresh=force_refresh,
                )
            except Exception as exc:
                st.error(f"自動查詢失敗：{exc}")
                return
            st.success(result["summary"])
            for warning in result["warnings"]:
                st.warning(warning)
            st.session_state.last_auto_hydration = result


def _page_home(st: Any) -> None:
    st.title("首頁儀表板")
    st.info(RISK_NOTICE)
    _auto_hydration_panel(st, key_prefix="home")
    prices = st.session_state.price_data
    fundamentals = st.session_state.fundamentals
    result = st.session_state.backtest_result

    _display_metric_cards(
        st,
        [
            ("股價資料列數", _row_count(prices)),
            ("股票數量", _symbol_count(prices)),
            ("基本面資料列數", _row_count(fundamentals)),
            ("最近回測交易數", _trade_count(result)),
        ],
    )

    if result is not None:
        st.subheader("最近回測績效")
        _display_metrics(st, result)
        _display_equity_and_drawdown(st, result.equity_curve)
    else:
        st.warning("尚未執行回測。請先到「資料匯入」與「策略回測」。")


def _page_import(st: Any) -> None:
    st.title("資料匯入")
    st.caption("支援標準 OHLCV CSV。缺值會提示，不會補假資料。")

    if st.button("載入內建範例股價資料"):
        _set_price_data(
            st,
            _load_sample_prices(),
            source_type="範例資料",
            provider="sample",
            cache_file=None,
        )
        st.success(f"已載入範例資料：{SAMPLE_PRICE_FILE}")

    price_upload = st.file_uploader("上傳股價 CSV", type=["csv"], key="price_upload")
    if price_upload is not None:
        try:
            price_data, warning_messages = load_price_upload(price_upload)
            _set_price_data(
                st,
                price_data,
                source_type="使用者上傳 CSV",
                provider="csv",
                cache_file=None,
            )
            st.success(f"已匯入 {len(price_data)} 筆股價資料")
            _display_warnings(st, warning_messages)
        except (ValueError, DataValidationError) as exc:
            st.error(f"股價資料匯入失敗：{exc}")

    st.divider()
    if st.button("載入內建範例基本面資料"):
        fundamentals, scores = _load_sample_fundamentals()
        st.session_state.fundamentals = fundamentals
        st.session_state.fundamental_scores = scores
        st.success(f"已載入範例資料：{SAMPLE_FUNDAMENTAL_FILE}")

    fundamental_upload = st.file_uploader("上傳基本面 CSV", type=["csv"], key="fundamental_upload")
    if fundamental_upload is not None:
        try:
            fundamentals = load_fundamentals_upload(fundamental_upload)
            st.session_state.fundamentals = fundamentals
            st.session_state.fundamental_scores = score_fundamentals(fundamentals)
            st.success(f"已匯入 {len(fundamentals)} 筆基本面資料")
        except ValueError as exc:
            st.error(f"基本面資料匯入失敗：{exc}")

    prices = st.session_state.price_data
    if prices is not None:
        st.subheader("股價資料預覽")
        _display_data_source(st)
        _display_table(st, prices.head(20))


def _page_auto_fetch(st: Any) -> None:
    st.title("自動抓資料")
    st.caption("使用 yfinance 優先抓取日線資料，失敗時依序嘗試 FinMind（需權杖）與 data/cache。")
    st.info("目前自動抓資料僅作研究便利功能；CSV 上傳仍保留為主要備援。")

    col1, col2, col3 = st.columns(3)
    symbol = col1.text_input(
        "股票代號",
        value="2330",
        help="台股上市可輸入 2330 或 2330.TW；上櫃可輸入 6488 或 6488.TWO；美股可輸入 AAPL。",
    )
    market_label = col2.selectbox("市場", ["台股上市 TWSE", "台股上櫃 TPEx", "美股 US"])
    provider_label = col3.selectbox(
        "資料來源",
        ["自動備援", "yfinance", "FinMind（需 FINMIND_TOKEN）", "快取", "CSV 上傳"],
    )
    market = _market_code(market_label)
    provider = _provider_code(provider_label)
    use_cache = provider != "csv"
    query_symbols = (
        yfinance_symbol_candidates(symbol, market=cast(ProviderMarket, market))
        if symbol.strip()
        else ()
    )
    query_symbol = " -> ".join(query_symbols)
    default_start, default_end = default_date_range(None, None)
    st.caption(
        f"使用者輸入代號：{symbol or '未輸入'}；實際查詢代號：{query_symbol or '未輸入'}；市場：{market}"
    )

    if provider == "csv":
        st.warning("請到「資料匯入」頁面上傳 CSV；CSV 會被標示為使用者上傳資料。")
        return

    col4, col5 = st.columns(2)
    start = col4.text_input("起始日 YYYY-MM-DD（空白則預設兩年前）", value=default_start)
    end = col5.text_input("結束日 YYYY-MM-DD（空白則預設今天）", value=default_end)
    force_refresh = st.checkbox("忽略既有快取並重新下載", value=False, disabled=provider == "cache")

    if st.button("抓取股價資料", type="primary"):
        try:
            result = fetch_prices(
                symbol,
                market=cast(ProviderMarket, market),
                start=start or None,
                end=end or None,
                provider=cast(ProviderChoice, provider),
                use_cache=use_cache,
                force_refresh=force_refresh,
                health_tracker=st.session_state.get("provider_health_tracker"),
            )
            qualified_result = _with_price_provenance(
                _qualify_price_frame(
                    result.data,
                    symbol=result.symbol,
                    market=_canonical_market_or_unknown(result.market),
                ),
                provider=result.source,
                provider_symbol=result.provider_symbol,
                source_type=result.source_type,
                last_data_date=result.last_data_date,
                checked_at=result.fetched_at,
            )
            saved_rows = 0
            try:
                saved_rows = _persist_price_data(qualified_result, _runtime_database_path())
            except Exception as exc:
                st.warning(f"股價資料已抓取，但寫入 SQLite 失敗：{exc}")
            _set_price_data(
                st,
                qualified_result,
                source_type=result.source_type,
                provider=result.source,
                user_symbol=result.symbol,
                query_symbol=result.provider_symbol,
                market=result.market,
                start_date=result.start_date,
                end_date=result.end_date,
                cache_file=result.cache_file,
                fetched_at=result.fetched_at,
                last_data_date=result.last_data_date,
                cache_state=result.cache_state,
                cache_age_seconds=result.cache_age_seconds,
                attempts=result.attempts,
                row_count=len(result.data),
            )
            st.success(f"已載入 {len(result.data)} 筆資料。")
            if saved_rows:
                st.caption(
                    f"已寫入 SQLite：{_runtime_database_path()}；寫入 {saved_rows} 筆，目前載入 {len(result.data)} 筆。"
                )
            _display_metric_cards(
                st,
                [
                    ("資料類型", result.source_type),
                    ("資料來源", result.source),
                    ("實際查詢代號", result.provider_symbol),
                    ("資料筆數", len(result.data)),
                ],
            )
            st.caption(f"實際日期區間：{result.start_date} 到 {result.end_date}")
            if result.cache_file is not None:
                st.caption(f"快取檔案：{result.cache_file}")
            _display_warnings(st, [sanitize_provider_text(item) for item in result.warnings])
            if result.attempts:
                st.subheader("資料來源嘗試紀錄")
                attempts_frame = pd.DataFrame(
                    [
                        {
                            "provider": sanitize_provider_text(attempt.provider),
                            "success": attempt.success,
                            "reason": sanitize_provider_text(attempt.reason),
                        }
                        for attempt in result.attempts
                    ]
                ).rename(columns={"provider": "資料來源", "success": "是否成功", "reason": "原因"})
                _display_table(st, attempts_frame)
            st.subheader("前 5 筆資料")
            _display_table(st, result.data.head(5))
        except DataFetchError as exc:
            st.error("自動抓資料失敗。已嘗試可用資料來源與備援機制，但沒有取得可用股價資料。")
            st.text(sanitize_provider_text(exc))
            st.info("你仍可到「資料匯入」頁面上傳 CSV 作為備用資料來源。")

    prices = st.session_state.price_data
    if prices is not None:
        st.subheader("目前載入股價資料")
        _display_data_source(st)
        _display_table(st, prices.tail(30))


def _page_concept_lookup(st: Any) -> None:
    _render_canonical_discovery(st)
    st.divider()
    st.title("產業 / 概念股查詢")
    st.caption(
        "輸入產業或概念後，系統會優先線上查詢 TWSE/TPEx 官方公開資料與 yfinance，"
        "再把選定股票送進既有自動抓價與基本面更新流程。"
    )
    st.warning("概念股清單只作研究索引，不代表完整名單，也不是買賣建議。")

    col1, col2 = st.columns([2, 3])
    query = col1.text_input(
        "產業或概念關鍵字",
        value="半導體",
        help=(
            "可輸入產業、概念、公司名或美股代號。例如：半導體、AI、AI伺服器、"
            "HBM（會分成直接製造商與供應鏈關聯）、封裝、矽電容、CoWoS、CoPoS、TGV、CPO、矽光子、TSM、NVDA。"
        ),
    )
    market_labels = col2.multiselect(
        "市場分類",
        ["台股上市 TWSE", "台股上櫃 TPEx", "美股 US"],
        default=["台股上市 TWSE", "台股上櫃 TPEx", "美股 US"],
    )

    col3, col4, col5 = st.columns([1, 1, 1])
    auto_update = col3.checkbox("查詢後自動更新股價與基本面", value=True)
    update_limit = col4.number_input(
        "自動更新檔數上限", min_value=1, max_value=30, value=10, step=1
    )
    force_refresh = col5.checkbox("重新下載", value=False)
    include_local_fallback = st.checkbox(
        "線上來源失敗時才使用本機備援清單",
        value=False,
        help="預設關閉。開啟後才會讀取 data/sample/concept_stocks.csv 作為備援，不會把它標成線上資料。",
    )

    if st.button("線上查詢並更新", type="primary"):
        try:
            result = lookup_concept_stocks_online(
                query,
                markets=_concept_market_codes(market_labels),
                max_results_per_source=25,
                include_local_fallback=include_local_fallback,
                local_path=CONCEPT_STOCK_FILE,
            )
            st.session_state.concept_lookup_result = result
            st.session_state.concept_update_log = None
            if result.matches.empty:
                st.warning("沒有找到可用結果。請換一個關鍵字，或確認網路連線後重試。")
            else:
                st.success(f"找到 {len(result.matches)} 筆候選股票。")
                if auto_update:
                    st.info("開始更新候選股票資料；免費資料源可能會有部分股票查不到。")
                    st.session_state.concept_update_log = _hydrate_concept_matches(
                        st,
                        result.matches,
                        limit=int(update_limit),
                        force_refresh=force_refresh,
                    )
        except Exception as exc:
            st.error(f"產業 / 概念股線上查詢失敗：{exc}")
            st.info("請確認網路連線，或稍後再試。CSV 匯入仍可作為備援資料來源。")

    result = st.session_state.concept_lookup_result
    if result is None:
        return

    st.subheader(f"查詢結果：{result.query}")
    if result.attempts:
        _display_table(st, pd.DataFrame({"資料來源嘗試": list(result.attempts)}))
    _display_warnings(st, list(result.warnings))

    matches = result.matches
    if matches.empty:
        return

    st.subheader("市場分類摘要")
    _display_table(st, concept_market_summary(matches))

    st.subheader("候選股票")
    visible_columns = [
        "symbol",
        "name",
        "market_label",
        "exchange",
        "industry",
        "concept",
        "relation_type",
        "price_reaction_stage",
        "stage_note",
        "source",
        "match_reason",
        "note",
    ]
    _display_table(
        st, matches.loc[:, [column for column in visible_columns if column in matches.columns]]
    )

    update_log = st.session_state.concept_update_log
    if update_log is not None and not update_log.empty:
        st.subheader("自動更新紀錄")
        _display_table(st, update_log)

    _display_concept_actions(st, matches, result.query)


def _render_canonical_discovery(st: Any) -> None:
    """Render the exact-evidence discovery surface within the existing Explore page."""

    try:
        render_discovery(st, ConceptRepository(ResearchRepository(_runtime_database_path())))
    except Exception:
        logging.getLogger(__name__).exception("Canonical discovery renderer failed")
        st.info("題材證據資料尚未載入；可使用下方既有查詢工具。")


def _page_watchlist(st: Any) -> None:
    st.title("自選股清單")
    st.caption("自選股會儲存在 data/watchlist.csv，可搭配自動抓資料逐檔研究。")
    watchlist = _get_watchlist(st)

    col1, col2, col3 = st.columns([1, 1, 2])
    symbol = col1.text_input("新增股票代號", value="2330", key="watchlist_symbol")
    market = col2.selectbox("市場", ["TW", "US", "AUTO", "CUSTOM"], key="watchlist_market")
    note = col3.text_input("備註", value="", key="watchlist_note")
    if st.button("加入 / 更新自選股"):
        watchlist = add_watchlist_symbol(watchlist, symbol=symbol, market=market, note=note)
        st.session_state.watchlist = watchlist
        save_watchlist(watchlist, _runtime_watchlist_path())
        st.success(f"已更新自選股：{symbol}")

    if not watchlist.empty:
        remove_symbol = st.selectbox("移除股票", watchlist["symbol"].tolist())
        if st.button("移除選取股票"):
            watchlist = remove_watchlist_symbol(watchlist, symbol=remove_symbol)
            st.session_state.watchlist = watchlist
            save_watchlist(watchlist, _runtime_watchlist_path())
            st.success(f"已移除：{remove_symbol}")

    if st.button("儲存自選股"):
        save_watchlist(watchlist, _runtime_watchlist_path())
        st.success(f"已儲存：{_runtime_watchlist_path()}")

    effective = build_effective_watchlist(watchlist, _get_portfolio(st))
    st.subheader("有效追蹤清單")
    st.caption("持股自動追蹤僅在本次分析使用，不會寫入手動自選股檔；移除持股後才會停止追蹤。")
    _display_table(st, effective)


def _page_single_stock(st: Any) -> None:
    st.title("單檔股票分析")
    prices = _require_prices(st)
    if prices is None:
        return
    symbol = _select_symbol(st, prices)
    stock_data = _filter_symbol(prices, symbol)
    st.subheader(f"{symbol} 資料概覽")
    _display_metric_cards(
        st,
        [
            ("資料筆數", len(stock_data)),
            ("起始日期", str(stock_data["date"].min())),
            ("結束日期", str(stock_data["date"].max())),
            ("最新收盤", _latest_value(stock_data, "close")),
        ],
    )
    _display_entry_reference(
        st,
        estimate_entry_reference(
            prices,
            st.session_state.technical_indicators,
            symbol=symbol,
        ),
    )
    _display_line_chart(st, stock_data, ["close"])
    _display_table(st, stock_data.tail(30))


def _page_indicators(st: Any) -> None:
    st.title("技術指標")
    prices = _require_prices(st)
    if prices is None:
        return
    symbol = _select_symbol(st, prices)
    if st.button("計算技術指標"):
        st.session_state.technical_indicators = compute_technical_indicators(prices)
        st.success("技術指標已計算")
    indicators = st.session_state.technical_indicators
    if indicators is None:
        st.warning("尚未計算技術指標。")
        return
    data = _filter_symbol(indicators, symbol)
    latest = data.tail(1)
    if latest.empty:
        st.warning(INSUFFICIENT_DATA)
        return
    st.subheader("最新指標摘要")
    indicator_cols = [
        "close",
        "sma_20",
        "sma_60",
        "ema_12",
        "ema_26",
        "rsi_14",
        "macd_dif",
        "macd_dea",
        "atr_14",
    ]
    _display_table(st, latest[[col for col in indicator_cols if col in latest.columns]])
    chart_cols = [col for col in ["close", "sma_20", "sma_60"] if col in data.columns]
    _display_line_chart(st, data, chart_cols)
    _display_table(st, data.tail(50))


def _page_ai_analysis(st: Any) -> None:
    st.title("AI 分析與綜合評分")
    st.caption(
        "本頁使用本機規則式摘要與可測試評分模型，不連外部 AI，不提供保證獲利或個人化投資建議。"
    )
    _auto_hydration_panel(st, key_prefix="ai")
    prices = _require_prices(st)
    if prices is None:
        return

    symbol = _select_symbol(st, prices)
    if st.session_state.technical_indicators is None:
        st.session_state.technical_indicators = compute_technical_indicators(prices)
        st.info("已依目前股價資料自動計算技術指標。")

    if st.session_state.fundamentals is not None and st.session_state.fundamental_scores is None:
        st.session_state.fundamental_scores = score_fundamentals(st.session_state.fundamentals)

    result = score_stock(
        symbol=symbol,
        price_data=prices,
        technical_indicators=st.session_state.technical_indicators,
        fundamental_scores=st.session_state.fundamental_scores,
        backtest_result=st.session_state.backtest_result,
    )
    _display_stock_research_header(st, symbol, prices, result)
    _display_entry_reference(
        st,
        estimate_entry_reference(
            prices,
            st.session_state.technical_indicators,
            symbol=symbol,
        ),
    )
    if result.available_score != "unknown":
        st.success(
            f"可用資料評分：{_score_value(result.available_score)} / 100；"
            f"資料覆蓋率：{_percent(result.coverage)}。"
        )
    if result.total_score == "unknown" and result.missing_data:
        st.info(
            "完整 0-100 總分需要技術面、基本面、估值面與風險面都具備資料；"
            f"目前缺少：{_format_missing_data(result.missing_data)}。"
        )

    st.subheader(f"{symbol} 綜合研究分數")
    _display_metric_cards(
        st,
        [
            (
                "研究分數",
                _score_value(
                    result.total_score
                    if result.total_score != "unknown"
                    else result.available_score
                ),
            ),
            ("全資料總分", _score_value(result.total_score)),
            ("資料覆蓋率", _percent(result.coverage)),
            ("摘要評級", result.rating_label),
        ],
    )

    component_frame = score_components_frame(result)
    factor_frame = _factor_health_frame(result)
    if not factor_frame.empty:
        st.subheader("AI 分析與策略健檢")
        st.bar_chart(factor_frame.set_index("factor")["score"])
        _display_table(
            st, factor_frame.rename(columns={"factor": "因子", "score": "分數", "note": "說明"})
        )
    chart_frame = _component_chart_frame(component_frame)
    if not chart_frame.empty:
        st.bar_chart(chart_frame.set_index("component")["score"])
    _display_table(
        st,
        component_frame.rename(
            columns={
                "component": "分項",
                "score": "分數",
                "weight": "權重",
                "coverage": "覆蓋權重",
                "reasons": "原因",
                "missing_data": "缺漏資料",
            }
        ),
    )

    if result.total_score == "unknown":
        st.warning("完整總分需要技術面、基本面、估值面與風險面資料都齊全；目前只顯示可用資料分數。")
    if "fundamental_scores" in result.missing_data or "valuation_score" in result.missing_data:
        st.info("若要計算完整股票評分，請先到「資料匯入」載入基本面 CSV。")

    company_profile = _get_company_research_profile(st, symbol)
    related_reports = _related_research_summaries(st, symbol)
    serenity_result = run_serenity_agent(
        symbol=symbol,
        market=_infer_market_for_symbol(st, symbol),
        price_data=prices,
        technical_indicators=st.session_state.technical_indicators,
        company_profile=company_profile,
        research_reports=related_reports,
        stock_score_result=result,
        concept_relations=_canonical_concept_relations(st, symbol),
    )
    summary_tab, business_tab, serenity_tab, report_tab, strategy_tab, reasons_tab, risk_tab = (
        st.tabs(
            [
                "AI 摘要",
                "公司業務脈絡",
                "Serenity 小 Agent",
                "研究報告",
                "策略健檢",
                "分數原因",
                "風險與限制",
            ]
        )
    )
    with summary_tab:
        st.markdown("#### 研究摘要")
        for item in result.summary:
            st.write(f"- {item}")
        st.markdown("#### 主要優勢")
        for item in result.strengths or ("目前沒有足夠資料列出優勢。",):
            st.write(f"- {item}")
        st.markdown("#### 需要檢查")
        for item in result.weaknesses or ("目前沒有足夠資料列出弱項。",):
            st.write(f"- {item}")

    with business_tab:
        _display_company_research_profile(st, company_profile)

    with serenity_tab:
        _display_serenity_agent(st, serenity_result)

    with report_tab:
        _display_related_research_reports(st, symbol)

    with strategy_tab:
        st.markdown("#### 策略健檢")
        for item in result.strategy_health:
            st.write(f"- {item}")
        if st.session_state.backtest_result is None:
            st.info("可先到「策略回測」執行回測，再回到本頁查看策略健檢。")

    with reasons_tab:
        st.markdown("#### 分項理由")
        for component in result.components:
            st.markdown(
                f"**{component.name}：{_score_value(component.score)} / {component.weight:g}**"
            )
            strengths, weaknesses = _component_reason_breakdown(component)
            left, right = st.columns(2)
            left.markdown("**優點**")
            for reason in strengths:
                left.write(f"- {reason}")
            right.markdown("**缺點 / 需要檢查**")
            for reason in weaknesses:
                right.write(f"- {reason}")

    with risk_tab:
        st.markdown("#### 風險揭露")
        for item in result.risk_notes:
            st.write(f"- {item}")
        if result.missing_data:
            st.markdown("#### 缺漏資料")
            for item in result.missing_data:
                st.write(f"- {item}")


def _page_research_reports(st: Any) -> None:
    st.title("研究報告摘要")
    st.caption(
        "匯入你已有權使用的 PDF 研究報告，系統會在本機抽取文字並產生保守摘要；"
        "不會自動下單，也不會把原報告評等轉成買賣建議。"
    )
    st.warning(REPORT_DISCLAIMER)

    with st.expander("公開報告搜尋入口", expanded=False):
        st.caption(
            "這裡只建立搜尋連結，不自動爬取付費券商報告。請確認來源、版權與日期後再匯入 PDF。"
        )
        col1, col2 = st.columns(2)
        search_symbol = col1.text_input("股票代號", value=str(st.session_state.active_symbol or ""))
        company_name = col2.text_input("公司名稱（選填）", value="")
        links = build_public_report_search_links(search_symbol, company_name)
        for label, url in links.items():
            st.markdown(f"- [{label}]({url})")

    st.subheader("匯入 PDF")
    col1, col2 = st.columns([1, 2])
    symbol = col1.text_input(
        "股票代號（用來和 AI 分析頁關聯）", value=str(st.session_state.active_symbol or "")
    )
    local_pdf_path = col2.text_input(
        "本機 PDF 路徑（選填）",
        value="",
        help="例如 D:\\Downloads\\矽力-KY 分析.pdf。若已上傳 PDF，這欄可留空。",
    )
    uploaded_pdf = st.file_uploader("上傳 PDF 研究報告", type=["pdf"])
    max_pages = st.slider("最多讀取頁數", min_value=5, max_value=80, value=40, step=5)

    if st.button("產生研究報告摘要", type="primary"):
        try:
            summary = _summarize_report_from_inputs(
                symbol=symbol,
                uploaded_pdf=uploaded_pdf,
                local_pdf_path=local_pdf_path,
                max_pages=int(max_pages),
            )
            st.session_state.research_report_summaries = [
                *st.session_state.research_report_summaries,
                summary,
            ]
            st.success("研究報告摘要已產生，並已加入本次 session。")
        except Exception as exc:
            st.error(f"無法產生研究報告摘要：{exc}")
            st.info("若 PDF 是掃描圖片，這個版本尚未做 OCR，請改用可選取文字的 PDF。")

    summaries = list(st.session_state.research_report_summaries)
    if not summaries:
        st.info("尚未匯入研究報告。")
        return

    st.subheader("已匯入報告")
    _display_table(st, research_report_summaries_to_frame(summaries))
    selected_index = st.selectbox(
        "選擇要查看的摘要",
        options=list(range(len(summaries))),
        format_func=lambda index: f"{summaries[index].symbol or '未指定'} - {summaries[index].title}",
    )
    _display_research_report_summary(st, summaries[int(selected_index)])

    csv_text = research_report_summaries_to_frame(summaries).to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "下載摘要 CSV",
        data=csv_text,
        file_name="research_report_summaries.csv",
        mime="text/csv",
    )


def _summarize_report_from_inputs(
    *,
    symbol: str,
    uploaded_pdf: Any,
    local_pdf_path: str,
    max_pages: int,
) -> ResearchReportSummary:
    """Summarize an uploaded PDF or a local PDF path."""

    symbol_text = str(symbol or "").strip()
    local_path_text = str(local_pdf_path or "").strip().strip('"')
    if uploaded_pdf is not None:
        uploaded_pdf.seek(0)
        return summarize_pdf_report(
            uploaded_pdf,
            symbol=symbol_text,
            source_name=getattr(uploaded_pdf, "name", "uploaded_report.pdf"),
            max_pages=max_pages,
        )
    if local_path_text:
        path = Path(local_path_text)
        if not path.exists():
            raise FileNotFoundError(f"找不到 PDF：{path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError("目前只支援 PDF 檔。")
        return summarize_pdf_report(
            path,
            symbol=symbol_text,
            source_name=path.name,
            max_pages=max_pages,
        )
    raise ValueError("請上傳 PDF，或填入本機 PDF 路徑。")


def _display_related_research_reports(st: Any, symbol: str) -> None:
    """Display report summaries related to a stock symbol in the AI page."""

    summaries = _related_research_summaries(st, symbol)
    if not summaries:
        st.info("尚未匯入這檔股票的研究報告。可到「研究報告摘要」頁上傳 PDF 或輸入本機 PDF 路徑。")
        return
    st.markdown("#### 已匯入研究報告摘要")
    _display_table(st, research_report_summaries_to_frame(summaries))
    _display_research_report_summary(st, summaries[-1])


def _related_research_summaries(st: Any, symbol: str) -> tuple[ResearchReportSummary, ...]:
    """Return report summaries matching the selected symbol."""

    symbol_text = str(symbol).strip().upper()
    return tuple(
        summary
        for summary in st.session_state.research_report_summaries
        if str(summary.symbol).strip().upper() == symbol_text
    )


def _display_serenity_agent(st: Any, result: SerenityAgentResult) -> None:
    """Render the local Serenity-style chokepoint research agent output."""

    st.markdown("#### Serenity 供應鏈瓶頸小 Agent")
    st.caption(
        "這是本機規則式研究 agent，將公司脈絡、技術指標、綜合評分與已匯入研究報告"
        "整理成供應鏈瓶頸檢查表。它不呼叫外部 AI，也不提供買賣建議。"
    )
    _display_metric_cards(
        st,
        [
            ("研究匹配度", _number(result.research_match_score)),
            ("信心標籤", result.confidence_label),
            ("股票代號", result.symbol),
            ("用途", "研究假設檢查"),
        ],
    )
    st.info(result.disclaimer)
    st.markdown("**核心假設**")
    st.write(result.thesis)

    factor_frame = serenity_factors_frame(result)
    if not factor_frame.empty:
        st.bar_chart(factor_frame.set_index("factor")["score"])
        _display_table(
            st,
            factor_frame.rename(
                columns={
                    "factor": "檢查因子",
                    "score": "分數",
                    "evidence_level": "證據等級",
                    "explanation": "說明",
                    "gaps": "缺口",
                }
            ),
        )

    left, right = st.columns(2)
    with left:
        _write_bullets(st, "瓶頸地圖", result.chokepoint_map)
        _write_bullets(st, "可能催化與觀察時點", result.catalysts)
        _write_bullets(st, "下一步查證問題", result.next_questions)
    with right:
        _write_bullets(st, "失效條件", result.invalidation_tests)
        _write_bullets(st, "主要風險", result.risks)
        _write_bullets(st, "證據缺口", result.evidence_gaps)


def _display_research_report_summary(st: Any, summary: ResearchReportSummary) -> None:
    """Render one research report summary."""

    _display_metric_cards(
        st,
        [
            ("股票代號", summary.symbol or "未指定"),
            ("報告日期", summary.report_date),
            ("抽取字數", f"{summary.extracted_characters:,}"),
            ("來源檔名", summary.source_name or "未指定"),
        ],
    )
    st.markdown(f"#### {summary.title}")
    _display_points_section(st, "研究重點", summary.key_points)
    _display_points_section(st, "主要業務", summary.business_points)
    _display_points_section(st, "技術特點", summary.technology_points)
    _display_points_section(st, "產業連結 / 應用場景", summary.industry_links)
    _display_points_section(st, "可能催化", summary.catalysts)
    _display_points_section(st, "瓶頸 / 需要驗證", summary.bottlenecks)
    _display_points_section(st, "估值觀察", summary.valuation_notes)
    _display_points_section(st, "風險", summary.risk_notes)
    if summary.points:
        with st.expander("頁碼與原文引用", expanded=False):
            for point in summary.points:
                for citation in point.citations:
                    st.markdown(
                        f"- 第 {citation.page_number} 頁，{citation.start_offset}–"
                        f"{citation.end_offset} 字元（{citation.source_name or '未指定來源'}）"
                    )
                    st.caption(citation.quote[:300])
    with st.expander("資料限制"):
        for item in summary.data_limitations:
            st.write(f"- {item}")
        st.write(f"- {summary.disclaimer}")


def _display_points_section(st: Any, title: str, points: Sequence[str]) -> None:
    """Display a small bullet section."""

    st.markdown(f"**{title}**")
    for point in points:
        st.write(f"- {point}")


def _page_screener(st: Any) -> None:
    st.title("股票篩選器")
    st.caption("使用目前已載入資料的最新技術指標列進行篩選；資料不足時會提示限制。")
    prices = _require_prices(st)
    if prices is None:
        return

    if st.session_state.technical_indicators is None:
        if st.button("先計算技術指標"):
            st.session_state.technical_indicators = compute_technical_indicators(prices)
            st.success("技術指標已計算")
        else:
            st.warning("請先計算技術指標，或按下方按鈕由篩選器代為計算。")
            return

    indicators = st.session_state.technical_indicators
    col1, col2, col3 = st.columns(3)
    min_volume = col1.number_input("最低成交量（0 表示不限制）", min_value=0.0, value=0.0)
    min_return_20d = col2.number_input("20 日報酬率下限", value=-1.0, step=0.01)
    max_volatility_20d = col3.number_input("20 日波動率上限", min_value=0.0, value=1.0, step=0.01)
    col4, col5 = st.columns(2)
    min_rsi = col4.number_input("RSI 下限", min_value=0.0, max_value=100.0, value=0.0)
    max_rsi = col5.number_input("RSI 上限", min_value=0.0, max_value=100.0, value=100.0)

    result = screen_stocks(
        indicators,
        ScreenerCriteria(
            min_volume=min_volume if min_volume > 0 else None,
            min_return_20d=min_return_20d,
            max_volatility_20d=max_volatility_20d,
            min_rsi=min_rsi,
            max_rsi=max_rsi,
        ),
    )
    _display_warnings(st, list(result.warnings))
    st.subheader(f"符合條件股票：{len(result.matches)}")
    summary_cols = [
        "symbol",
        "date",
        "close",
        "volume",
        "return_20",
        "volatility_20",
        "rsi_14",
        "sma_20",
        "sma_60",
    ]
    visible_cols = [column for column in summary_cols if column in result.matches.columns]
    _display_table(st, result.matches.loc[:, visible_cols] if visible_cols else result.matches)


def _page_fundamentals(st: Any) -> None:
    st.title("基本面評分")
    scores = st.session_state.fundamental_scores
    if scores is None:
        st.warning("尚未匯入或計算基本面資料。請先到「資料匯入」。")
        return
    _display_table(st, scores)
    symbols = sorted(scores["symbol"].astype(str).unique().tolist())
    selected = st.selectbox("股票代號", symbols)
    row = scores.loc[scores["symbol"].astype(str) == selected]
    if row.empty:
        st.warning(INSUFFICIENT_DATA)
        return
    row = row.iloc[0]
    _display_metric_cards(
        st,
        [
            ("總分", str(row.get("total_score", INSUFFICIENT_DATA))),
            ("成長性", str(row.get("growth_score", INSUFFICIENT_DATA))),
            ("獲利能力", str(row.get("profitability_score", INSUFFICIENT_DATA))),
        ],
    )
    st.markdown("**優勢**")
    st.write(row.get("strengths") or INSUFFICIENT_DATA)
    st.markdown("**弱項 / 限制**")
    st.write(row.get("weaknesses") or INSUFFICIENT_DATA)
    if row.get("missing_data"):
        st.warning(f"缺漏資料：{row.get('missing_data')}")
    st.info(str(row.get("risk_notes") or RISK_NOTICE))


def _page_backtest(st: Any) -> None:
    st.title("策略回測")
    st.info(BACKTEST_RESEARCH_NOTICE)
    st.caption("本頁所有成本與成交設定僅用於研究模擬，不代表實際交易條件。")
    prices = _require_prices(st)
    if prices is None:
        return

    st.subheader("1. 選擇標的與資料")
    symbol = _select_symbol(st, prices)
    stock_data = _filter_symbol(prices, symbol)
    market = _market_for_backtest_record(st, symbol) or "UNKNOWN"
    source_metadata = st.session_state.price_data_source or {}
    data_start = str(stock_data["date"].min()) if not stock_data.empty else None
    data_end = str(stock_data["date"].max()) if not stock_data.empty else None
    source_name = str(
        source_metadata.get("source_type") or source_metadata.get("provider") or "資料不足"
    )
    st.caption(
        f"股票代號：{symbol}；市場：{market}；資料期間：{data_start or '資料不足'} 至 "
        f"{data_end or '資料不足'}；資料筆數：{len(stock_data)}；資料來源：{source_name}。"
    )

    st.subheader("2. 選擇策略")
    strategy_key = st.selectbox(
        "策略",
        list(BACKTEST_STRATEGY_LABELS),
        format_func=lambda value: BACKTEST_STRATEGY_LABELS[value],
        key="backtest_strategy_key",
    )
    guidance = strategy_guidance(strategy_key)
    st.caption(guidance.observe)
    with st.expander("策略說明與限制"):
        st.write(f"研究買入訊號：{guidance.buy_signal}")
        st.write(f"研究賣出訊號：{guidance.sell_signal}")
        st.write(f"資料需求：{guidance.data_requirement}")
        for limitation in guidance.limitations:
            st.write(f"限制：{limitation}")

    st.subheader("3. 設定策略參數")
    allocation_pct = st.slider(
        "策略投入比例 (%)",
        min_value=5.0,
        max_value=95.0,
        value=40.0,
        step=5.0,
        help="此數值會直接作為既有策略的 target_percent，限制每次研究訊號的目標部位。",
    )
    strategy = _strategy_controls(
        st,
        strategy_key=strategy_key,
        target_percent=percent_to_rate(allocation_pct),
    )

    st.subheader("4. 資金與成本假設")
    currency = (
        "TWD"
        if market in {Market.TWSE.value, Market.TPEX.value}
        else "USD" if market == Market.US.value else "未確認"
    )
    initial_cash = st.number_input(
        f"初始資金（{currency}）",
        min_value=1_000.0,
        value=1_000_000.0,
        step=10_000.0,
    )
    max_position_pct = percent_to_rate(
        st.slider(
            "單一持股上限 (%)",
            min_value=5.0,
            max_value=95.0,
            value=50.0,
            step=5.0,
            help="此上限會傳給既有 BacktestEngine 與 Broker 的最大單一持股限制。",
        )
    )
    cost_preset, commission_rate, tax_rate, slippage_rate = _render_backtest_cost_controls(
        st, market
    )
    enable_trailing_stop = st.checkbox("啟用移動停利", value=False)
    trailing_stop_pct = None
    if enable_trailing_stop:
        trailing_stop_pct = percent_to_rate(
            st.slider("移動停利回落比例 (%)", min_value=1.0, max_value=50.0, value=10.0, step=1.0)
        )
    st.caption(
        "移動停利會在每日收盤後更新持有期間最高收盤價；若回落達設定比例，只產生研究賣出訊號，"
        "最早於下一根 K 棒成交。"
    )
    with st.expander("移動停利技術細節"):
        st.write(TRAILING_STOP_NOTICE)

    market_costs_confirmed = True
    if market not in CANONICAL_MARKETS:
        market_costs_confirmed = st.checkbox("我已確認此未知市場的幣別與交易成本假設", value=False)
    values = BacktestFormValues(
        symbol=symbol,
        market=market,
        strategy_key=strategy.name,
        strategy_parameters=dict(strategy.parameters),
        data_rows=len(stock_data),
        data_start=data_start,
        data_end=data_end,
        data_source=source_name,
        initial_cash=float(initial_cash),
        allocation_rate=percent_to_rate(allocation_pct),
        max_position_pct=max_position_pct,
        commission_rate=commission_rate,
        tax_rate=tax_rate,
        slippage_rate=slippage_rate,
        cost_preset=cost_preset,
        trailing_stop_pct=trailing_stop_pct,
        has_fundamentals=st.session_state.fundamentals is not None,
        market_costs_confirmed=market_costs_confirmed,
    )
    validation = validate_backtest_form(values)
    summary = build_backtest_summary(values)

    st.subheader("5. 執行前檢查")
    _display_backtest_preflight(st, summary, validation)
    for error in validation.errors:
        st.error(error)
    for warning in validation.warnings:
        st.warning(warning)
    for next_step in validation.next_steps:
        st.info(next_step)

    if st.button("使用以上設定執行回測", type="primary", disabled=not validation.can_execute):
        try:
            with st.spinner("正在以既有 T+1 成交規則執行研究回測…"):
                fundamentals = st.session_state.fundamentals
                if isinstance(strategy, FundamentalGrowthStrategy):
                    signals = strategy.generate_signals(stock_data, fundamentals=fundamentals)
                else:
                    signals = strategy.generate_signals(stock_data)
                engine = BacktestEngine(
                    initial_cash=float(initial_cash),
                    broker_config=summary.broker_config,
                    max_position_pct=max_position_pct,
                    trailing_stop_pct=trailing_stop_pct,
                )
                result = engine.run(stock_data, signals)
            binding = build_backtest_run_binding(values)
            st.session_state.backtest_result = result
            st.session_state.backtest_run_binding = binding
            st.session_state.signals = signals
            st.session_state.last_parameters = binding.to_parameters()
            st.success("回測完成。訊號於 T 日產生，最早於下一個交易日 T+1 成交。")
        except Exception as exc:  # Streamlit UI should surface recoverable errors.
            st.error(f"回測失敗：{exc}")

    result = st.session_state.backtest_result
    if result is not None:
        st.subheader("7. 結果解讀")
        stored_binding = st.session_state.get("backtest_run_binding")
        display_binding = stored_binding if isinstance(stored_binding, BacktestRunBinding) else None
        display = resolve_backtest_result_display(values, display_binding)
        if display.message:
            st.warning(display.message)
        if display.summary is not None:
            _display_backtest_interpretation(st, result, display.summary)
            _display_metrics(st, result)
            _display_equity_and_drawdown(st, result.equity_curve)
            st.subheader("交易紀錄")
            _display_table(st, _trades_frame(result))

    render_strategy_health(
        st,
        strategy=strategy,
        price_data=stock_data,
        fundamentals=st.session_state.fundamentals,
        engine_factory=lambda: BacktestEngine(
            initial_cash=float(initial_cash),
            broker_config=summary.broker_config,
            max_position_pct=max_position_pct,
            trailing_stop_pct=trailing_stop_pct,
        ),
    )


def _page_portfolio(st: Any) -> None:
    st.title("投資組合管理")
    st.caption("手動輸入持股，用於部位與未實現損益追蹤；本工具不會自動下單。")
    st.info(f"{PORTFOLIO_RISK_INDEPENDENCE_NOTICE}健康度使用目前持股、價格、匯率與研究資料。")
    portfolio = _get_portfolio(st)

    col1, col2, col3, col4 = st.columns(4)
    symbol = col1.text_input("股票代號", value="2330", key="portfolio_symbol")
    market = col2.selectbox(
        "市場",
        ["TWSE", "TPEX", "US", "AUTO", "CUSTOM"],
        key="portfolio_market",
        help="AUTO 與 CUSTOM 不會被默默猜成台股；CUSTOM 必須明確指定幣別。",
    )
    quantity = col3.number_input(
        "零股股數（股）",
        min_value=0,
        value=1,
        step=1,
        help="以股為單位。1 代表 1 股，1000 股才等於 1 張。",
    )
    average_cost = col4.number_input("平均成本（每股）", min_value=0.0, value=100.0, step=1.0)
    st.caption("投資組合持股以「股」為單位，支援零股；請不要輸入張數。")
    currency_choice = st.selectbox(
        "幣別",
        ["自動（標準市場）", "TWD", "USD"],
        key="portfolio_currency",
        help="CUSTOM 市場必須選擇 TWD 或 USD。",
    )
    currency = None if currency_choice == "自動（標準市場）" else currency_choice
    note = st.text_input("備註", value="", key="portfolio_note")

    if st.button("加入 / 更新持股"):
        try:
            portfolio = add_portfolio_position(
                portfolio,
                symbol=symbol,
                market=market,
                quantity=float(quantity),
                average_cost=average_cost,
                currency=currency,
                note=note,
            )
        except ValueError as exc:
            st.error(f"持股資料無法加入：{exc}")
        else:
            st.session_state.portfolio = portfolio
            save_portfolio(portfolio, _runtime_portfolio_path())
            st.success(f"已更新持股：{symbol} / {market}")

    if not portfolio.empty:
        remove_options = [
            f"{row.symbol} / {row.market}"
            for row in portfolio[["symbol", "market"]].itertuples(index=False)
        ]
        remove_selection = st.selectbox("移除持股", remove_options)
        if st.button("移除選取持股"):
            remove_symbol, remove_market = remove_selection.split(" / ", maxsplit=1)
            portfolio = remove_portfolio_position(
                portfolio,
                symbol=remove_symbol,
                market=remove_market,
            )
            st.session_state.portfolio = portfolio
            save_portfolio(portfolio, _runtime_portfolio_path())
            st.success(f"已移除：{remove_symbol} / {remove_market}")

    if st.button("儲存投資組合"):
        save_portfolio(portfolio, _runtime_portfolio_path())
        st.success(f"已儲存：{_runtime_portfolio_path()}")

    prices = _portfolio_price_context(st)
    st.subheader("持股摘要")
    with st.expander("進階設定／資料備援"):
        st.checkbox("強制忽略快取", key="portfolio_force_refresh")
        st.caption("手動匯率與資料來源診斷位於下方的投資組合分析區。")
    if st.button("更新並分析持股", type="primary", key="portfolio_update_and_analyze"):
        with st.spinner("正在更新股價、基本面、匯率並重新計算投資組合分析..."):
            result = _refresh_portfolio_analysis(
                st,
                portfolio,
                force_refresh=bool(st.session_state.get("portfolio_force_refresh")),
            )
        st.session_state.portfolio_refresh_result = result
        prices = _portfolio_price_context(st)
    _display_portfolio_refresh_result(st, st.session_state.get("portfolio_refresh_result"))
    if prices is None:
        st.warning("尚無可用的市場價格資料；請按「更新並分析持股」取得可用資料。")
    summary = portfolio_summary(portfolio, prices)
    _display_table(
        st,
        summary.rename(
            columns={
                "quantity": "零股股數（股）",
                "average_cost": "平均成本（每股）",
            }
        ),
    )
    _display_portfolio_intelligence(st, portfolio, prices)


def _portfolio_fx_cache() -> JsonFxQuoteCache:
    """Return the private runtime cache used only for the USD/TWD quote."""

    return JsonFxQuoteCache(_runtime_paths().cache_dir / "usd_twd_fx.json")


def _manual_usd_twd_rate(st: Any) -> float | None:
    """Return an explicit valid manual fallback rate, if the user supplied one."""

    try:
        rate = float(
            st.session_state.get("portfolio_manual_usd_twd")
            or st.session_state.get("portfolio_workspace_manual_fx")
            or 0.0
        )
    except (TypeError, ValueError):
        return None
    return rate if rate > 0 else None


def _stored_portfolio_fx_resolution(st: Any) -> FxResolution:
    """Reuse a fresh session quote or resolve an expired result through the fallback chain."""

    stored = st.session_state.get("portfolio_fx_resolution")
    if (
        isinstance(stored, FxResolution)
        and stored.quote is not None
        and is_fx_retrieval_fresh(
            stored.quote,
            max_age_seconds=DEFAULT_FX_CACHE_TTL_SECONDS,
        )
    ):
        return stored
    if isinstance(stored, FxResolution) and stored.quote is not None:
        refreshed = UsdTwdFxResolutionService(
            online=YFinanceUsdTwdProvider(),
            cache=_portfolio_fx_cache(),
        ).resolve(manual_rate=_manual_usd_twd_rate(st))
        st.session_state.portfolio_fx_resolution = refreshed
        return refreshed
    cache = _portfolio_fx_cache()
    cached = cache.get_quote(Currency.USD, Currency.TWD)
    warnings = (cache.last_warning,) if cache.last_warning else ()
    if cached is not None:
        return FxResolution(
            FxQuote(
                from_currency=cached.from_currency,
                to_currency=cached.to_currency,
                rate=cached.rate,
                source=f"cache:{cached.source}",
                fetched_at=cached.fetched_at,
                effective_at=cached.effective_at,
                stale=cached.stale,
                unknown=cached.unknown,
                provider_symbol=cached.provider_symbol,
                cache_state="cache",
            ),
            "cache",
            warnings,
        )
    manual = _manual_usd_twd_rate(st)
    if manual is not None:
        timestamp = str(
            st.session_state.get("portfolio_manual_fx_applied_at")
            or st.session_state.get("portfolio_workspace_manual_fx_applied_at")
            or pd.Timestamp.now(tz="UTC").isoformat()
        )
        return FxResolution(
            FxQuote.manual(Currency.USD, Currency.TWD, manual, timestamp),
            "manual",
            warnings,
        )
    return FxResolution(
        None,
        "unavailable",
        (*warnings, "USD/TWD 匯率資料不足，跨幣別總值無法可靠計算。"),
    )


def _refresh_portfolio_analysis(
    st: Any,
    portfolio: pd.DataFrame,
    *,
    force_refresh: bool,
) -> PortfolioRefreshResult:
    """Run one user-triggered, non-mutating portfolio data refresh workflow."""

    refresh = PortfolioRefreshService().refresh(
        positions=portfolio,
        force_refresh=force_refresh,
        hydrate=lambda symbol, market, force: _ensure_symbol_data(
            st,
            symbol=symbol,
            market=market,
            force_refresh=force,
        ),
    )
    fx_resolution = UsdTwdFxResolutionService(
        online=YFinanceUsdTwdProvider(),
        cache=_portfolio_fx_cache(),
    ).resolve(manual_rate=_manual_usd_twd_rate(st))
    st.session_state.portfolio_fx_resolution = fx_resolution
    return refresh


def _display_portfolio_refresh_result(st: Any, result: object) -> None:
    """Render one concise status row per requested position without new requests."""

    if not isinstance(result, PortfolioRefreshResult):
        return
    rows = [
        {
            "股票代號": item.symbol,
            "市場": item.market,
            "狀態": item.status,
            "股價筆數": item.price_rows,
            "基本面筆數": item.fundamental_rows,
            "資料來源": item.provider or "資料不足",
            "查詢代號": item.query_symbol or "資料不足",
            "最後資料日": item.last_data_date or "資料不足",
            "更新時間": item.fetched_at or "資料不足",
            "說明": "；".join(item.warnings),
        }
        for item in result.items
    ]
    if rows:
        st.subheader("最近更新狀態")
        _display_table(st, pd.DataFrame(rows))


def _display_portfolio_intelligence(
    st: Any,
    portfolio: pd.DataFrame,
    prices: pd.DataFrame | None = None,
) -> None:
    """Render the bounded Sprint 3.2 portfolio valuation and research panel."""

    st.subheader("投資組合健康度與本機規則式摘要")
    base_currency = st.selectbox("基準幣別", ["TWD", "USD"], key="portfolio_base_currency")
    with st.expander("進階設定／資料備援"):
        manual_usd_twd = st.number_input(
            "USD/TWD 手動匯率（僅在自動資料不可用時備援）",
            min_value=0.0,
            value=float(st.session_state.portfolio_manual_usd_twd),
            step=0.01,
            key="portfolio_manual_usd_twd_input",
        )
        if st.button("套用手動匯率", key="portfolio_apply_manual_fx"):
            st.session_state.portfolio_manual_usd_twd = float(manual_usd_twd)
            st.session_state.portfolio_manual_fx_applied_at = pd.Timestamp.now(tz="UTC").isoformat()
            st.session_state.portfolio_fx_resolution = None
            st.success("已保存明確標示的手動備援匯率；它不是即時線上匯率。")
        st.caption("Provider 診斷只在使用者按下「更新並分析持股」後更新。")

    fx_resolution = _stored_portfolio_fx_resolution(st)
    valuation = PortfolioValuationService(
        fx_provider=fx_provider_from_resolution(fx_resolution),
        config=PortfolioValuationConfig(base_currency=Currency.parse(base_currency)),
    ).value(positions=portfolio, prices=prices)
    qualified_prices = _market_qualified_current_prices(st)
    qualified_fundamentals = _market_qualified_frame(
        st.session_state.fundamentals,
        reference_prices=qualified_prices,
        resolve_unknown_from_prices=False,
    )
    qualified_indicators = _market_qualified_frame(
        st.session_state.technical_indicators,
        reference_prices=qualified_prices,
    )
    qualified_fundamental_scores = _market_qualified_frame(
        st.session_state.fundamental_scores,
        reference_prices=qualified_prices,
        resolve_unknown_from_prices=False,
    )
    composite_scores = _portfolio_composite_scores(
        portfolio=portfolio,
        prices=qualified_prices,
        indicators=qualified_indicators,
        fundamental_scores=qualified_fundamental_scores,
    )
    risk_inputs = build_portfolio_risk_inputs(
        _portfolio_price_context(st),
        valuation.positions,
    )
    health = PortfolioHealthService().assess(
        portfolio=portfolio,
        valuation=valuation,
        fundamentals=qualified_fundamentals,
        indicators=qualified_indicators,
        stock_scores=composite_scores,
        risk_inputs=risk_inputs,
    )
    portfolio_risk = PortfolioRiskService().assess(
        portfolio=portfolio,
        prices=qualified_prices,
        valuation=valuation,
        health=health,
        classifications=_portfolio_risk_classifications(st, portfolio),
        ledger_snapshot=_read_existing_ledger_snapshot(),
    )
    brief = build_portfolio_research_brief(health)
    source = getattr(st.session_state, "price_data_source", None) or {}
    source_name = str(source.get("source_type") or source.get("provider") or "未提供")
    updated_at = str(source.get("updated_at") or source.get("end_date") or "未知")
    st.caption(f"價格資料來源：{source_name}；最後資料日期：{updated_at}")
    _display_metric_cards(
        st,
        [
            ("基準幣別總市值", _currency_value(valuation.base_market_value, base_currency)),
            ("基準幣別未實現損益", _currency_value(valuation.base_unrealized_pnl, base_currency)),
            ("健康度", _score_value(health.overall_score)),
            ("資料涵蓋率", _percent(health.coverage.coverage_pct)),
        ],
    )
    _display_portfolio_risk_center(st, portfolio_risk)
    if fx_resolution.quote is not None:
        quote = fx_resolution.quote
        market_freshness = "市場資料過舊" if quote.stale else "市場資料可用"
        st.caption(
            "USD/TWD "
            f"{quote.rate:.4f}；來源：{quote.source}；查詢代號：{quote.provider_symbol or '資料不足'}；"
            f"市場資料日期：{quote.effective_at}；下載／快取時間：{quote.fetched_at}；"
            f"取得狀態：{fx_resolution.status}；{market_freshness}。"
        )
    for warning in dict.fromkeys(
        (*fx_resolution.warnings, *valuation.warnings, *health.warnings, *risk_inputs.warnings)
    ):
        st.warning(warning)
    if valuation.base_market_value is None:
        st.info("缺少市場別價格或匯率時，不會合併不同幣別的總市值或權重。")
    st.caption("本機規則式摘要不會將持股資料傳送到外部 AI，也不是買賣建議。")
    _display_table(
        st,
        valuation.positions.rename(
            columns={
                "native_currency": "原始幣別",
                "native_market_value": "原始市值",
                "fx_rate_to_base": "換算匯率",
                "base_market_value": "基準幣別市值",
                "weight": "基準幣別權重",
            }
        ),
    )
    component_rows = [
        {
            "構面": component.name,
            "分數": component.score,
            "權重": component.weight,
            "貢獻": component.contribution,
            "原因": " ".join(component.reasons),
            "警示": " ".join(component.warnings),
            "證據": "；".join(
                f"{item.get('metric', 'evidence')}={item.get('value', item.get('state', ''))}"
                for item in component.evidence
            ),
        }
        for component in health.components
    ]
    _display_table(st, pd.DataFrame(component_rows))
    gap_items = tuple(
        dict.fromkeys(
            (
                *valuation.missing_data,
                *health.missing_data,
                *risk_inputs.missing_data,
            )
        )
    )
    gap_table = build_portfolio_data_gaps(
        positions=valuation.positions,
        missing_data=gap_items,
        structured_gaps=risk_inputs.data_gaps,
    )
    if not gap_table.empty:
        st.subheader("缺少資料與修復方式")
        _display_table(st, gap_table)
        for guidance in portfolio_missing_data_guidance(gap_items):
            st.info(guidance.next_step)
            with st.expander(f"技術原因：{guidance.field}"):
                st.write(guidance.technical_reason)
    st.markdown("**本機規則式摘要**")
    st.write(brief.overall_summary)
    st.write("主要風險：" + "；".join(brief.top_risks))
    st.write("下一步檢查：" + "；".join(brief.next_checks))
    st.caption(brief.disclaimer)

    scenario_type = st.selectbox(
        "壓力測試情境",
        [item.value for item in StressScenarioType],
        key="portfolio_stress_scenario",
    )
    is_fx_scenario = scenario_type == StressScenarioType.USD_TWD_MOVE.value
    shock_pct = st.slider(
        "壓力幅度",
        -0.80 if is_fx_scenario else 0.0,
        0.80,
        0.10,
        0.01,
        key="portfolio_stress_pct",
    )
    selected_stress_market = None
    market_options = _stress_market_options(scenario_type)
    if market_options:
        selected_stress_market = st.selectbox(
            "指定市場",
            list(market_options),
            key="portfolio_stress_market",
        )
    if st.button("執行壓力測試", key="portfolio_run_stress"):
        scenario = StressScenario(
            name="dashboard-scenario",
            scenario_type=StressScenarioType(scenario_type),
            shock_pct=float(shock_pct),
            market=selected_stress_market,
        )
        stress = PortfolioStressService().run(valuation=valuation, scenario=scenario)
        st.info(
            f"情境後基準幣別市值：{_currency_value(stress.base_value_after, base_currency)}；"
            f"影響：{_currency_value(stress.base_impact, base_currency)}。"
        )
        st.caption(stress.disclaimer)


def _portfolio_risk_classifications(st: Any, portfolio: pd.DataFrame) -> pd.DataFrame:
    """Return only already-cached, evidence-backed company classifications.

    Portfolio Risk must not infer an industry from a ticker or trigger an
    additional network request.  A profile becomes usable only after an
    existing company-research flow has supplied explicit source metadata.
    """

    cache = st.session_state.get("company_research_cache", {})
    rows: list[dict[str, str]] = []
    for row in normalize_portfolio(portfolio).itertuples(index=False):
        symbol = str(row.symbol).strip().upper()
        market = str(row.market).strip().upper()
        profile = cache.get(f"{symbol}|{market}")
        if not isinstance(profile, CompanyResearchProfile) or not profile.is_available:
            continue
        source = ", ".join(item for item in profile.data_sources if str(item).strip())
        if not source:
            continue
        rows.append(
            {
                "symbol": symbol,
                "market": market,
                "sector": profile.sector,
                "industry": profile.industry,
                "source": source,
            }
        )
    return pd.DataFrame(rows, columns=["symbol", "market", "sector", "industry", "source"])


def _read_existing_ledger_snapshot() -> Any | None:
    """Replay an existing dedicated ledger only; never create one for a UI render."""

    paths = _runtime_paths()
    if not paths.ledger_database_file.is_file():
        return None
    try:
        return PortfolioLedgerService.from_runtime_paths(paths).replay_persisted()
    except (OSError, RuntimeError, ValueError):
        return None


def _display_portfolio_risk_center(st: Any, result: PortfolioRiskResult) -> None:
    """Render the bounded, evidence-first Portfolio Risk v2 summary."""

    st.subheader("投資組合風險中心")
    _display_metric_cards(
        st,
        [
            ("已實現損益", _currency_value(result.realized_pnl, result.base_currency)),
            ("最大單一持股", _percent(result.position_concentration)),
            ("前三大持股集中度", _percent(result.top_three_concentration)),
            ("資料涵蓋率", _percent(result.coverage_pct)),
        ],
    )
    st.caption(
        f"計算時間：{result.calculated_at}；市場資料截至：{result.data_as_of or '無法判斷'}。"
    )
    price_status = result.price_data_status
    if price_status.status in {"partial", "unknown", "stale"}:
        affected = list(price_status.missing_identities) + list(price_status.stale_identities)
        st.warning(
            "價格資料覆蓋或新鮮度不足："
            + ("、".join(affected) if affected else "無法判定受影響持股")
        )
    for exposure in (
        result.market_exposure,
        result.currency_exposure,
        result.sector_exposure,
        result.industry_exposure,
    ):
        label = {
            "market": "市場曝險",
            "native_currency": "幣別曝險",
            "sector": "產業別曝險",
            "industry": "次產業曝險",
        }.get(exposure.dimension, exposure.dimension)
        if exposure.status == "unknown":
            st.info(f"{label}：資料不足，未將不完整部位重新正規化為 100%。")
            for conflict in exposure.conflicts:
                _display_classification_conflict(st, label, conflict)
            continue
        entries = (
            "、".join(f"{item.identity} {_percent(item.weight)}" for item in exposure.items)
            or "無可分類部位"
        )
        suffix = (
            f"；未分類 {_percent(exposure.unclassified_weight)}"
            if exposure.unclassified_weight
            else ""
        )
        st.caption(f"{label}：{entries}{suffix}")
        for conflict in exposure.conflicts:
            _display_classification_conflict(st, label, conflict)
    st.info(
        "因缺少可驗證的因子敏感度資料，價值、成長、動能、beta、利率與波動度曝險目前顯示為資料不足。"
    )
    with st.expander("壓力測試（確定性假設，非預測）"):
        stress_rows = [
            {
                "情境": item.scenario.name,
                "衝擊": _percent(item.scenario.shock_pct),
                "壓力後價值": _currency_value(item.base_value_after, item.base_currency),
                "變動": _currency_value(item.base_impact, item.base_currency),
            }
            for item in result.stress_results
        ]
        _display_table(st, pd.DataFrame(stress_rows))
        evidence_rows = [item.to_dict() for item in result.evidence_stress_results]
        if evidence_rows:
            _display_table(st, pd.DataFrame(evidence_rows))
    if result.missing_data:
        st.caption("資料缺口：" + "；".join(item.field for item in result.missing_data[:5]))
    st.caption(result.disclaimer)


def _display_classification_conflict(st: Any, label: str, conflict: Mapping[str, object]) -> None:
    """Render source evidence for a conflict without selecting a silent winner."""

    sources = conflict.get("sources", ())
    source_text = (
        "、".join(str(source) for source in sources)
        if isinstance(sources, (list, tuple))
        else "無法判定"
    )
    st.warning(f"{label} 分類衝突：{conflict.get('identity', '無法判定')}；來源：{source_text}")


def _stress_market_options(scenario_type: str) -> tuple[str, ...]:
    """Return selectable markets only for a market-decline scenario."""

    if scenario_type != StressScenarioType.MARKET_DECLINE.value:
        return ()
    return (Market.TWSE.value, Market.TPEX.value, Market.US.value)


def _market_qualified_current_prices(st: Any) -> pd.DataFrame | None:
    """Return only session prices that already carry a reliable market identity."""

    prices = st.session_state.price_data
    if prices is None or prices.empty or "symbol" not in prices.columns:
        return None
    output = prices.copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    if "market" not in output.columns:
        # Older session data did not persist a market column. A source market is
        # only safe to apply when the frame itself contains one unambiguous symbol.
        symbols = tuple(symbol for symbol in output["symbol"].unique() if symbol)
        source_metadata = getattr(st.session_state, "price_data_source", None) or {}
        source_market = _canonical_market_or_unknown(source_metadata.get("market"))
        if len(symbols) != 1 or source_market not in CANONICAL_MARKETS:
            return None
        output["market"] = source_market
    else:
        output["market"] = output["market"].map(_canonical_market_or_unknown)
    output = output.loc[output["market"].isin(CANONICAL_MARKETS)].copy()
    return output.reset_index(drop=True) if not output.empty else None


def _market_qualified_frame(
    frame: pd.DataFrame | None,
    *,
    reference_prices: pd.DataFrame | None = None,
    resolve_unknown_from_prices: bool = True,
) -> pd.DataFrame | None:
    """Return a defensive frame with only explicit or reliably mapped identities."""

    if frame is None or frame.empty or "symbol" not in frame.columns:
        return None
    output = frame.copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    if "market" not in output.columns:
        output["market"] = "UNKNOWN"
    output["market"] = output["market"].map(_canonical_market_or_unknown)
    if resolve_unknown_from_prices and reference_prices is not None:
        identity_map = _unique_market_map(reference_prices)
        unknown = output["market"].eq("UNKNOWN")
        output.loc[unknown, "market"] = output.loc[unknown, "symbol"].map(
            lambda symbol: identity_map.get(symbol, "UNKNOWN")
        )
    output = output.loc[output["market"].isin(CANONICAL_MARKETS)].copy()
    return output.reset_index(drop=True) if not output.empty else None


def _portfolio_composite_scores(
    *,
    portfolio: pd.DataFrame,
    prices: pd.DataFrame | None,
    indicators: pd.DataFrame | None,
    fundamental_scores: pd.DataFrame | None,
) -> pd.DataFrame:
    """Reuse canonical stock scoring once for each market-qualified portfolio position."""

    positions = normalize_portfolio(portfolio)
    rows: list[dict[str, object]] = []
    for position in positions.itertuples(index=False):
        symbol = str(position.symbol).upper()
        market = _canonical_market_or_unknown(position.market)
        if market not in CANONICAL_MARKETS:
            continue
        price_slice = _filter_identity(prices, symbol=symbol, market=market)
        indicator_slice = _filter_identity(indicators, symbol=symbol, market=market)
        fundamental_slice = _filter_identity(fundamental_scores, symbol=symbol, market=market)
        if price_slice.empty:
            rows.append(
                {
                    "symbol": symbol,
                    "market": market,
                    "total_score": pd.NA,
                    "available_score": pd.NA,
                    "coverage": 0.0,
                    "status": "missing_price_data",
                    "missing_data": "price_data",
                }
            )
            continue
        result = score_stock(
            symbol=symbol,
            price_data=price_slice,
            technical_indicators=indicator_slice if not indicator_slice.empty else None,
            fundamental_scores=fundamental_slice if not fundamental_slice.empty else None,
        )
        rows.append(
            {
                "symbol": symbol,
                "market": market,
                "total_score": (
                    float(result.total_score) if result.total_score != "unknown" else pd.NA
                ),
                "available_score": (
                    float(result.available_score) if result.available_score != "unknown" else pd.NA
                ),
                "coverage": result.coverage,
                "status": "available" if result.total_score != "unknown" else "insufficient_data",
                "missing_data": ";".join(result.missing_data),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "symbol",
            "market",
            "total_score",
            "available_score",
            "coverage",
            "status",
            "missing_data",
        ],
    )


def _currency_value(value: float | None, currency: str) -> str:
    """Format a base-currency result without inventing unavailable values."""

    return "—" if value is None else f"{currency} {value:,.2f}"


def _page_risk(st: Any) -> None:
    st.title("投資組合風險")
    st.info(f"{PORTFOLIO_RISK_INDEPENDENCE_NOTICE}持股健康度與資料缺口請在「投資組合管理」查看。")
    result = st.session_state.backtest_result
    if result is None:
        st.warning("目前沒有回測結果可檢查策略資金曲線風險；這不影響投資組合健康度功能。")
        return

    col1, col2, col3, col4 = st.columns(4)
    max_position_pct = col1.slider("單一股票上限", 0.05, 0.95, 0.25, 0.05)
    min_cash_ratio = col2.slider("現金水位下限", 0.0, 0.50, 0.05, 0.01)
    max_drawdown_pct = col3.slider("最大回撤警示", 0.01, 0.80, 0.20, 0.01)
    max_volatility = col4.slider("年化波動率警示", 0.01, 2.00, 0.40, 0.01)
    max_positions = st.number_input("總持股數上限", min_value=1, value=10, step=1)
    max_consecutive_losses = st.number_input("連續虧損警示門檻", min_value=1, value=3, step=1)
    max_industry_pct = st.slider("產業集中度上限", 0.05, 0.95, 0.40, 0.05)

    config = RiskConfig(
        max_position_pct=max_position_pct,
        min_cash_ratio=min_cash_ratio,
        max_drawdown_pct=max_drawdown_pct,
        max_volatility=max_volatility,
        max_positions=int(max_positions),
        max_consecutive_losses=int(max_consecutive_losses),
        max_industry_pct=max_industry_pct,
    )
    returns = result.equity_curve["total_equity"].pct_change().dropna()
    alerts = RiskManager(config).check_portfolio_alerts(
        equity_curve=result.equity_curve,
        returns=returns,
        trades=result.trades,
        portfolio=result.portfolio,
    )
    st.session_state.risk_alerts = alerts
    if not alerts:
        st.success("目前沒有觸發設定中的風險警示。")
    else:
        st.warning("已觸發風險警示，請檢查風控設定與策略假設。")
        _display_table(st, pd.DataFrame([alert.__dict__ for alert in alerts]))


def _page_reports(st: Any) -> None:
    st.title("報表下載")
    result = st.session_state.backtest_result
    prices = st.session_state.price_data
    if prices is None:
        st.warning("請先匯入股價資料。")
        return
    symbol = _select_symbol(st, prices)
    if result is None:
        st.warning("尚未執行回測，報表會缺少回測績效與交易紀錄。")

    report_data = _build_report_data(st, symbol, prices, result)

    if st.button("產生 Excel 報表"):
        _display_excel_download(st, report_data, symbol)
        st.success("Excel 報表已產生。")


def _get_watchlist(st: Any) -> pd.DataFrame:
    """Load watchlist once per Streamlit session."""

    if st.session_state.watchlist is None:
        st.session_state.watchlist = load_watchlist(_runtime_watchlist_path())
    return st.session_state.watchlist


def _get_portfolio(st: Any) -> pd.DataFrame:
    """Load manual portfolio once per Streamlit session."""

    if st.session_state.portfolio is None:
        st.session_state.portfolio = load_portfolio(_runtime_portfolio_path())
    return st.session_state.portfolio


def _build_daily_brief(st: Any) -> DailyBrief:
    """Adapt existing local evidence into the UI-independent Daily Brief service."""

    portfolio = _get_portfolio(st)
    watchlist = build_effective_watchlist(_get_watchlist(st), portfolio)
    prices = _portfolio_price_context(st)
    valuation = _daily_portfolio_valuation(st, portfolio, prices)
    qualified_prices = _market_qualified_current_prices(st)
    fundamental_scores = _market_qualified_frame(
        st.session_state.fundamental_scores,
        reference_prices=qualified_prices,
        resolve_unknown_from_prices=False,
    )
    continuations = tuple(
        item
        for item in st.session_state.get("dashboard_research_continuations", [])
        if isinstance(item, ResearchContinuation)
    )
    source = st.session_state.price_data_source or {}
    # A provider check/fetch time is distinct from a market-data date. Do not
    # use the latter as a freshness reference after a restart.
    reference_at = source.get("checked_at") or source.get("fetched_at")
    return DailyBriefService().build(
        portfolio=portfolio,
        watchlist=watchlist,
        prices=prices,
        valuation=valuation,
        continuations=continuations,
        reference_at=str(reference_at) if reference_at else None,
        fundamental_scores=fundamental_scores,
        risk_alert_count=len(tuple(st.session_state.get("risk_alerts") or ())),
    )


def _daily_research_snapshot_store() -> DailyResearchSnapshotStore:
    """Resolve a process-isolated derived snapshot location without touching user inputs."""

    return DailyResearchSnapshotStore(default_runtime_paths().daily_research_snapshot_file)


def _build_daily_research_loop(st: Any) -> DailyResearchLoopResult:
    """Restore a prior successful Daily Brief for the homepage without any network request."""

    existing = st.session_state.get("dashboard_daily_research_loop")
    if isinstance(existing, DailyResearchLoopResult):
        return existing
    return DailyResearchLoopService().restore(_daily_research_snapshot_store().load())


def _run_daily_research(st: Any) -> Any:
    """Run the shared application flow once, then hydrate the UI from local outputs."""

    paths = _runtime_paths()
    notifications = DailyResearchNotificationService(paths)
    benchmark_service = BenchmarkRefreshService(
        _runtime_database_path(),
        cache_dir=paths.cache_dir,
        log_dir=paths.logs_dir,
    )

    def notify_success(
        record: Any,
        brief: DailyResearchBrief,
        *,
        change_summary: Any | None = None,
    ) -> object:
        evidence_mode = os.environ.get("STOCK_TOOL_EVIDENCE_MODE", "").strip()
        isolated_root = paths.root.resolve(strict=False)
        temp_root = Path(tempfile.gettempdir()).resolve()
        if evidence_mode == "sprint32.1.1" and temp_root in isolated_root.parents:
            # Explicit evidence-only notifier seam.  It is enabled only for a
            # fresh TEMP runtime and never changes normal notification policy.
            return SimpleNamespace(status="sent", reason=None)
        # The runner passes the change projection produced by this same run;
        # never reload a potentially different cached snapshot here.
        if change_summary is None:
            change_summary = DailyResearchChangeStore(
                paths.daily_research_change_file,
                paths.daily_research_change_history_dir,
            ).load()
        return notifications.notify_success(record, brief, change_summary=change_summary)

    runner = DailyResearchRunner(
        paths,
        now_fn=lambda: datetime.now(timezone.utc),
        on_success=notify_success,
        benchmark_refresh_callback=benchmark_service.refresh,
        prediction_outcome_provider=_build_runtime_cached_outcome_provider(),
        max_symbols=20,
    )
    outcome = runner.run(trigger="manual")
    manifest = runner.latest_manifest()
    st.session_state["dashboard_daily_run_outcome"] = outcome
    st.session_state["dashboard_daily_run_manifest"] = manifest
    # The runner writes only derived cache/brief data.  Hydrate the current UI
    # from those local bytes; this does not issue a second provider request.
    imported_prices = _load_default_database_prices(_runtime_database_path())
    if imported_prices is not None and not imported_prices.empty:
        _set_price_data(
            st,
            imported_prices,
            source_type="SQLite 匯入資料",
            provider="sqlite",
            cache_file=None,
            start_date=str(imported_prices["date"].min()),
            end_date=str(imported_prices["date"].max()),
            warnings=tuple(imported_prices.attrs.get("price_identity_warnings") or ()),
        )
    brief = _daily_evidence_brief_store().load()
    if brief is not None:
        st.session_state["dashboard_daily_evidence_brief"] = brief
    return outcome


def _build_prediction_lab_summary(_st: Any) -> PredictionLabSummary:
    """Load the immutable Prediction Lab projection without network activity."""

    return PredictionLabApplicationService(
        PredictionLabStore.from_runtime_paths(_runtime_paths()).ensure()
    ).summary(trading_date=datetime.now(timezone.utc).date().isoformat())


class _RuntimeCachedOutcomeProvider(RuntimeCachedOutcomeProvider):
    """Compatibility name for the shared strict runtime provider."""


def _build_runtime_cached_outcome_provider() -> RuntimeCachedOutcomeProvider | None:
    paths = _runtime_paths()
    provider = build_runtime_cached_outcome_provider(
        _runtime_database_path(),
        corporate_actions_path=paths.corporate_actions_file,
    )
    if provider is None:
        return None
    # Keep the shared provider (including its persisted CorporateAction
    # evidence) intact; wrapping only the rows would silently discard action
    # provenance at the dashboard boundary.
    return provider


def _evaluate_prediction_outcomes() -> PredictionOutcomeEvaluationResult:
    """Refresh official benchmark evidence, then settle due samples locally."""

    paths = _runtime_paths()
    service = BenchmarkRefreshService(
        _runtime_database_path(), cache_dir=paths.cache_dir, log_dir=paths.logs_dir
    )
    try:
        refreshed = service.refresh(markets=("TWSE", "TPEX", "US"))
    except Exception:
        refreshed = None
    provider = service.load_provider() if refreshed and refreshed.identities else None
    if provider is None:
        return PredictionOutcomeEvaluationResult(
            status="unavailable",
            outcomes=(),
            message="目前沒有足夠的本機價格與基準證據",
        )
    return PredictionOutcomeEvaluator(
        PredictionLabStore.from_runtime_paths(_runtime_paths()).ensure(),
        provider,
    ).evaluate_due()


def _daily_evidence_brief_store() -> DailyResearchBriefStore:
    """Resolve the latest evidence-chain brief inside the isolated runtime root."""

    paths = default_runtime_paths()
    return DailyResearchBriefStore(
        paths.daily_research_brief_file,
        paths.daily_research_brief_html_file,
        paths.daily_research_brief_history_dir,
    )


def _macro_snapshot_store() -> MacroSnapshotStore:
    """Resolve private macro snapshot storage for the current isolated runtime."""

    paths = default_runtime_paths()
    return MacroSnapshotStore(
        paths.macro_latest_file,
        paths.macro_history_dir,
        revision_ledger_path=paths.macro_revision_ledger_file,
    )


def _build_macro_snapshot(st: Any) -> tuple[MacroSnapshot | None, tuple[Any, ...]]:
    """Load macro evidence and deterministic signals without network access."""

    snapshot = st.session_state.get("dashboard_macro_snapshot")
    if not isinstance(snapshot, MacroSnapshot):
        try:
            snapshot = MacroSnapshotApplicationService(_macro_snapshot_store()).load()
        except Exception:
            st.warning("總經快照無法驗證，已安全停用；請重新取得官方資料。")
            return None, ()
        if snapshot is not None:
            st.session_state["dashboard_macro_snapshot"] = snapshot
    if snapshot is None:
        return None, ()
    previous = None
    try:
        history = _macro_snapshot_store().history()
        if len(history) >= 2:
            previous = history[-2]
    except Exception:
        st.warning("總經歷史快照無法驗證，已停用變化比較。")
        previous = None
    return snapshot, MacroRuleRegistry().evaluate(snapshot, previous)


def _build_macro_links(st: Any, snapshot: MacroSnapshot) -> tuple[dict[str, object], ...]:
    """Adapt existing portfolio/watchlist/classification evidence to macro links."""

    classifications = load_local_classifications(CONCEPT_STOCK_FILE)
    normalized_classifications: dict[str, dict[str, object]] = {
        f"{market}:{symbol}": {"industry": label}
        for (market, symbol), label in classifications.items()
    }
    return build_macro_links(
        snapshot,
        portfolio=_get_portfolio(st),
        watchlist=_get_watchlist(st),
        classifications=normalized_classifications,
    )


def _build_macro_revisions(st: Any) -> tuple[dict[str, object], ...]:
    """Read only important revision events from the bounded local ledger."""

    del st
    entries = MacroRevisionLedgerStore(
        _macro_snapshot_store().revision_ledger_path
    ).important_revisions()
    return tuple(
        {
            "series_id": entry.series_id,
            "observation_period": entry.observation_period,
            "first_seen_value": entry.first_seen_value,
            "latest_value": entry.latest.value,
            "revision_count": len(entry.observations) - 1,
        }
        for entry in entries
    )


def _refresh_macro_snapshot(st: Any) -> MacroSnapshot:
    """Perform one explicit official-provider refresh from the Home button."""

    snapshot = MacroSnapshotApplicationService(_macro_snapshot_store()).refresh()
    st.session_state["dashboard_macro_snapshot"] = snapshot
    return snapshot


def _build_daily_evidence_brief(st: Any) -> DailyResearchBrief | None:
    """Replay the last successful brief without fetching or mutating inputs."""

    existing = st.session_state.get("dashboard_daily_evidence_brief")
    if isinstance(existing, DailyResearchBrief):
        return existing
    brief = _daily_evidence_brief_store().load()
    if brief is not None:
        st.session_state["dashboard_daily_evidence_brief"] = brief
    return brief


def _generate_daily_evidence_brief(st: Any, force_regenerate: bool = False) -> DailyResearchBrief:
    """Generate a bounded evidence brief only after an explicit UI action."""

    portfolio = _get_portfolio(st)
    watchlist = build_effective_watchlist(_get_watchlist(st), portfolio)
    daily_brief = _build_daily_brief(st)
    restored_loop = _build_daily_research_loop(st)
    loop_result = restored_loop
    if daily_brief is not None:
        previous_snapshot = restored_loop.snapshot
        loop_result = DailyResearchLoopService().complete_success(
            brief=daily_brief,
            previous_snapshot=previous_snapshot,
            successful_at=datetime.now(timezone.utc).isoformat(),
            sources=_daily_research_sources(st),
        )
    market_paths = default_runtime_paths()
    market_result = MarketMonitorApplicationService(
        market_paths.market_snapshot_file,
        classifications=load_local_classifications(CONCEPT_STOCK_FILE),
    ).load_cached()
    macro_snapshot, _macro_signals = _build_macro_snapshot(st)
    macro_links = _build_macro_links(st, macro_snapshot) if macro_snapshot is not None else ()
    assistant_brief: DailyResearchAssistantBrief | None = None
    try:
        # This delegates to the existing assistant/provider boundary.  Any
        # provider failure is intentionally converted to deterministic rules.
        assistant_brief = _generate_daily_ai_research(st, force_regenerate)
    except Exception:  # pragma: no cover - defensive boundary for optional AI
        logging.getLogger(__name__).exception("Daily research assistant unavailable")
    previous_snapshot_id = (
        restored_loop.snapshot.successful_at if restored_loop.snapshot is not None else None
    )
    result = DailyResearchBriefApplicationService().generate(
        portfolio=portfolio,
        watchlist=watchlist,
        daily_brief=daily_brief,
        loop_result=loop_result,
        market_result=market_result,
        assistant_brief=assistant_brief,
        previous_snapshot_id=previous_snapshot_id,
        macro_snapshot=macro_snapshot,
        macro_links=macro_links,
    )
    # Saving happens only after the complete immutable result exists.  If the
    # write fails, the prior successful file remains untouched.
    brief_store = _daily_evidence_brief_store()
    previous: DailyResearchBrief | None = None
    change_history_error: ValueError | None = None
    try:
        history = brief_store.history()
        if history:
            previous = history[-1]
    except ValueError as exc:
        # Existing corrupt immutable history is a safety event, never a
        # legitimate first run.  Preserve the last valid projection instead
        # of fabricating a baseline from the new brief.
        change_history_error = exc
        st.session_state["dashboard_daily_change_warning"] = (
            "歷史簡報無法驗證；已保留上一份變化摘要，請檢查資料後再產生。"
        )
        logging.getLogger(__name__).warning(
            "daily research change history rejected in dashboard: %s", type(exc).__name__
        )
    brief_store.save(result)
    if change_history_error is None:
        try:
            change_store = DailyResearchChangeStore(
                default_runtime_paths().daily_research_change_file,
                default_runtime_paths().daily_research_change_history_dir,
            )
            change_store.save(DailyResearchChangeApplicationService().compare(result, previous))
        except Exception:
            logging.getLogger(__name__).exception("Daily research change summary unavailable")
    if market_result.snapshot is not None and market_result.status == "fresh":
        PredictionLabApplicationService(
            PredictionLabStore.from_runtime_paths(market_paths).ensure()
        ).register_from_market_snapshot(
            market_result.snapshot,
            trading_date=result.manifest.brief_date,
            input_hashes=(
                economic_input_fingerprint(
                    market_result.snapshot, trading_date=result.manifest.brief_date
                ),
            ),
        )
    st.session_state["dashboard_daily_evidence_brief"] = result
    return result


def _generate_daily_ai_research(
    st: Any, force_regenerate: bool = False
) -> DailyResearchAssistantBrief:
    """Generate bounded notes from existing snapshots without fetching or changing user inputs."""

    brief = _build_daily_brief(st)
    snapshots = dict(st.session_state.get("dashboard_research_snapshots") or {})
    current = st.session_state.get("research_snapshot")
    if current is not None and hasattr(current, "symbol"):
        snapshots.setdefault(current.symbol.canonical, current)
    candidates: list[tuple[str, str]] = []
    for attention_item in brief.attention_items:
        if attention_item.symbol is not None:
            candidates.append((attention_item.symbol.code, attention_item.symbol.market.value))
    for continuation in brief.continuations:
        candidates.append((continuation.symbol.code, continuation.symbol.market.value))
    if current is not None and hasattr(current, "symbol"):
        candidates.append((current.symbol.code, current.symbol.market.value))
    cache = ResearchAssistantCache(_runtime_paths().ai_research_dir)
    assistant = AIResearchAssistant.from_environment(cache=cache)
    return DailyResearchAssistantService(assistant).generate(
        candidates=candidates,
        snapshots=snapshots,
        daily_items=brief.attention_items,
        force_regenerate=force_regenerate,
    )


def _daily_research_sources(st: Any) -> dict[str, DailyResearchSource]:
    """Read persisted per-identity price provenance without inferring a market."""

    prices = _portfolio_price_context(st)
    if prices is None or prices.empty or not {"symbol", "market"}.issubset(prices.columns):
        return {}
    qualified = _market_qualified_frame(prices, resolve_unknown_from_prices=False)
    if qualified is None or qualified.empty:
        return {}
    sources: dict[str, DailyResearchSource] = {}
    for (code, market), group in qualified.groupby(["symbol", "market"], sort=True):
        try:
            symbol = Symbol.parse(str(code), market=str(market))
        except ValueError:
            continue
        checked_values = [
            value
            for value in (
                _single_frame_text(group, "checked_at"),
                _single_frame_text(group, "fetched_at"),
            )
            if value
        ]
        sources[symbol.canonical] = DailyResearchSource(
            provider=_single_frame_text(group, "provider"),
            source_type=_single_frame_text(group, "source_type"),
            provider_symbol=_single_frame_text(group, "provider_symbol"),
            last_data_date=(
                _single_frame_text(group, "last_data_date") or _latest_frame_date(group)
            ),
            checked_at=max(checked_values) if checked_values else None,
        )
    return sources


def _daily_research_successful_at(sources: dict[str, DailyResearchSource]) -> str:
    """Return an explicit successful check time, never passing it off as market-data time."""

    persisted = sorted(source.checked_at for source in sources.values() if source.checked_at)
    if persisted:
        return persisted[-1]
    return datetime.now(timezone.utc).isoformat()


def _complete_daily_research_loop(
    st: Any,
    result: DailyRefreshResult,
) -> DailyResearchLoopResult:
    """Persist a diff only after every requested refresh completed successfully."""

    store = _daily_research_snapshot_store()
    previous = store.load().snapshot
    service = DailyResearchLoopService()
    all_successful = result.requested_count > 0 and all(
        record.status == "success" for record in result.records
    )
    if not all_successful:
        failed_count = result.requested_count - result.success_count
        reason = (
            f"本次更新有 {failed_count} 檔未完成。"
            if failed_count > 0
            else "本次更新未取得足夠完整的資料，未建立新的比較基準。"
        )
        return service.complete_partial(
            previous_snapshot=previous,
            checked_at=datetime.now(timezone.utc).isoformat(),
            reason=reason,
        )

    sources = _daily_research_sources(st)
    completed = service.complete_success(
        brief=_build_daily_brief(st),
        previous_snapshot=previous,
        successful_at=_daily_research_successful_at(sources),
        sources=sources,
    )
    if completed.snapshot is None:
        return completed
    try:
        store.save(completed.snapshot)
    except OSError:
        return service.complete_partial(
            previous_snapshot=previous,
            checked_at=datetime.now(timezone.utc).isoformat(),
            reason="資料更新完成，但 Daily Brief 快照無法安全寫入。",
        )
    return completed


def _daily_portfolio_valuation(
    st: Any,
    portfolio: pd.DataFrame,
    prices: pd.DataFrame | None,
) -> Any:
    """Use the existing canonical valuation service without inventing missing FX quotes."""

    base_currency = Currency.parse(st.session_state.get("portfolio_base_currency", "TWD"))
    fx_resolution = _stored_portfolio_fx_resolution(st)
    return PortfolioValuationService(
        fx_provider=fx_provider_from_resolution(fx_resolution),
        config=PortfolioValuationConfig(base_currency=base_currency),
    ).value(positions=portfolio, prices=prices)


@dataclass(frozen=True, slots=True)
class _DailyHydrationProvider:
    """Request-bound adapter that delegates daily refreshes to the existing provider contract."""

    request: DataHydrationRequest
    health_tracker: ProviderHealthTracker | None

    def load_price_result(self) -> Any:
        """Load one canonical request through the existing fallback-aware fetch adapter."""

        return fetch_prices_result(
            self.request.symbol.code,
            market=cast(ProviderMarket, self.request.symbol.market.value),
            start=self.request.start_date,
            end=self.request.end_date,
            interval=self.request.interval or "1d",
            provider="auto",
            use_cache=True,
            force_refresh=True,
            cache_dir=_runtime_paths().cache_dir,
            log_dir=_runtime_paths().logs_dir,
            health_tracker=self.health_tracker,
            contracts_enabled=True,
        )


def _refresh_daily_data(st: Any) -> DailyRefreshResult:
    """Refresh up to twenty explicit portfolio/watchlist identities after a user action."""

    identities = _daily_refresh_identities(_get_portfolio(st), _get_watchlist(st))
    service = DailyRefreshService(max_symbols=20)
    result = service.refresh(
        symbols=identities, hydrate=lambda symbol: _hydrate_daily_symbol(st, symbol)
    )
    st.session_state["dashboard_daily_research_loop"] = _complete_daily_research_loop(st, result)
    return result


def _daily_refresh_identities(
    portfolio: pd.DataFrame, watchlist: pd.DataFrame
) -> tuple[Symbol, ...]:
    """Read only explicit market-qualified portfolio/watchlist identities in stable order."""

    values: list[Symbol] = []
    effective = build_effective_watchlist(watchlist, portfolio)
    for row in effective.loc[:, ["symbol", "market"]].itertuples(index=False):
        try:
            symbol = Symbol.parse(str(row.symbol), market=str(row.market))
        except ValueError:
            continue
        if symbol.market not in {Market.TWSE, Market.TPEX, Market.US}:
            continue
        values.append(symbol)
    unique: dict[str, Symbol] = {}
    for symbol in values:
        unique.setdefault(symbol.canonical, symbol)
    return tuple(unique.values())


def _hydrate_daily_symbol(st: Any, symbol: Symbol) -> DailyRefreshRecord:
    """Hydrate one identity and retain only validated session data and redacted lineage."""

    start_date, end_date = default_date_range(None, None)
    request = DataHydrationRequest(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        interval="1d",
    )
    snapshot = DataHydrationService(
        provider=_DailyHydrationProvider(
            request=request,
            health_tracker=st.session_state.get("provider_health_tracker"),
        ),
        storage=SQLitePriceStorage(_runtime_database_path()),
    ).hydrate(request)
    source = snapshot.metadata.source
    if not snapshot.has_usable_data or snapshot.data is None or snapshot.data.empty:
        return DailyRefreshRecord(
            symbol=symbol,
            status="failure",
            provider=source.provider,
            query_symbol=source.provider_symbol,
            source_type=source.source_type.value,
            reason="找不到可用價格資料；請確認代號、市場或稍後再試。",
            row_count=0,
        )

    qualified = _with_price_provenance(
        _qualify_price_frame(
            snapshot.data,
            symbol=symbol.code,
            market=symbol.market.value,
        ),
        provider=source.provider,
        provider_symbol=source.provider_symbol,
        source_type=source.source_type.value,
        last_data_date=source.last_data_date or snapshot.metadata.last_data_date,
        checked_at=source.fetched_at or snapshot.metadata.completed_at,
    )
    persistence_warning = None
    try:
        _persist_price_data(qualified, _runtime_database_path())
    except Exception:
        persistence_warning = "已取得價格資料，但市場別重啟資料寫入未完成；本次 session 仍可使用。"
    merged = _merge_price_frames([st.session_state.price_data, qualified])
    if merged is None:
        return DailyRefreshRecord(
            symbol=symbol,
            status="failure",
            reason="已取得資料但無法建立市場別價格身分；既有資料未被覆寫。",
        )
    _set_price_data(
        st,
        merged,
        source_type=source.source_type.value,
        provider=source.provider,
        cache_file=Path(source.cache_path) if source.cache_path else None,
        user_symbol=source.requested_symbol.code,
        query_symbol=source.provider_symbol,
        market=source.resolved_symbol.market.value,
        start_date=source.request_start,
        end_date=source.request_end,
        fetched_at=source.fetched_at or snapshot.metadata.completed_at,
        last_data_date=source.last_data_date or snapshot.metadata.last_data_date,
        cache_state=source.cache_state or ("hit" if snapshot.metadata.cache_hit else "miss"),
        cache_age_seconds=source.cache_age_seconds,
        attempts=snapshot.attempts,
        row_count=len(qualified),
    )
    return DailyRefreshRecord(
        symbol=symbol,
        status=(
            "partial" if snapshot.status.value == "partial" or persistence_warning else "success"
        ),
        provider=source.provider,
        query_symbol=source.provider_symbol,
        last_data_date=snapshot.metadata.last_data_date,
        source_type=source.source_type.value,
        reason=persistence_warning,
        row_count=len(qualified),
    )


def _portfolio_price_context(st: Any) -> pd.DataFrame | None:
    """Return the widest available local price context for portfolio valuation."""

    stored_prices = _load_default_database_prices(_runtime_database_path())
    if (
        stored_prices is not None
        and not stored_prices.empty
        and "market" not in stored_prices.columns
    ):
        # SQLite's legacy prices schema has no market column. Keep these rows visible
        # for legacy inspection, but never let valuation infer a market from them.
        stored_prices = stored_prices.copy(deep=True)
        stored_prices["market"] = "UNKNOWN"
    return _merge_price_frames([stored_prices, _market_qualified_current_prices(st)])


def _merge_price_frames(frames: Sequence[pd.DataFrame | None]) -> pd.DataFrame | None:
    """Merge prices only on full symbol/market/date identity without mutating inputs."""

    non_empty: list[pd.DataFrame] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        output = frame.copy(deep=True)
        if "symbol" in output.columns:
            output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
        if "market" not in output.columns:
            output["market"] = "UNKNOWN"
        output["market"] = output["market"].map(_canonical_market_or_unknown)
        non_empty.append(output)

    if not non_empty:
        return None

    combined = pd.concat(non_empty, ignore_index=True, sort=False)
    if {"symbol", "date"}.issubset(combined.columns):
        combined = combined.drop_duplicates(subset=["symbol", "market", "date"], keep="last")
        # Keep known identities ahead of legacy UNKNOWN rows for deterministic
        # current-session display. UNKNOWN remains a separate identity and is not
        # merged into any market-qualified record.
        combined["_market_sort"] = (~combined["market"].isin(CANONICAL_MARKETS)).astype(int)
        combined = combined.sort_values(["symbol", "_market_sort", "market", "date"])
        combined = combined.drop(columns="_market_sort")
    elif "symbol" in combined.columns:
        combined = combined.drop_duplicates(subset=["symbol", "market"], keep="last")
        combined["_market_sort"] = (~combined["market"].isin(CANONICAL_MARKETS)).astype(int)
        combined = combined.sort_values(["symbol", "_market_sort", "market"])
        combined = combined.drop(columns="_market_sort")
    return combined.reset_index(drop=True)


def _missing_portfolio_price_symbols(
    portfolio: pd.DataFrame,
    prices: pd.DataFrame | None,
) -> tuple[str, ...]:
    """Return portfolio symbols that do not have a usable latest close price."""

    positions = normalize_portfolio(portfolio)
    if positions.empty:
        return tuple()
    priced_identities = _identities_with_latest_prices(prices)
    legacy_symbols = (
        _symbols_with_latest_prices(prices)
        if prices is not None and "market" not in prices.columns
        else set()
    )
    symbol_counts = positions["symbol"].value_counts()
    missing = [
        symbol
        for symbol, market in positions[["symbol", "market"]].itertuples(index=False)
        if (
            (str(symbol).upper(), str(market).upper()) not in priced_identities
            and not (
                str(symbol).upper() in legacy_symbols
                and int(symbol_counts.get(str(symbol).upper(), 0)) == 1
            )
        )
    ]
    return tuple(dict.fromkeys(missing))


def _symbols_with_latest_prices(prices: pd.DataFrame | None) -> set[str]:
    """Return symbols whose latest row has a valid close price."""

    if (
        prices is None
        or prices.empty
        or "symbol" not in prices.columns
        or "close" not in prices.columns
    ):
        return set()

    output = prices.copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    output["close"] = pd.to_numeric(output["close"], errors="coerce")
    if "date" in output.columns:
        output = output.sort_values(["symbol", "date"])
    latest = output.groupby("symbol", as_index=False, sort=False).tail(1)
    return {
        str(row["symbol"])
        for _, row in latest.iterrows()
        if str(row.get("symbol", "")).strip() and pd.notna(row.get("close"))
    }


def _identities_with_latest_prices(prices: pd.DataFrame | None) -> set[tuple[str, str]]:
    """Return market-qualified identities with a usable latest close price."""

    if prices is None or prices.empty or not {"symbol", "market", "close"}.issubset(prices.columns):
        return set()

    output = prices.copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    output["market"] = output["market"].fillna("").astype(str).str.strip().str.upper()
    output["close"] = pd.to_numeric(output["close"], errors="coerce")
    output = output.loc[output["market"].isin({"TWSE", "TPEX", "US"})]
    if "date" in output.columns:
        output = output.sort_values(["symbol", "market", "date"])
    latest = output.groupby(["symbol", "market"], as_index=False, sort=False).tail(1)
    return {
        (str(row["symbol"]), str(row["market"]))
        for _, row in latest.iterrows()
        if str(row.get("symbol", "")).strip() and pd.notna(row.get("close"))
    }


def _portfolio_market_for_fetch(symbol: str, market: str) -> str:
    """Map manual portfolio market labels to the auto-fetch provider market."""

    market_key = str(market).strip().upper()
    symbol_key = str(symbol).strip().upper()
    if market_key in {"TW", "AUTO"}:
        return "AUTO"
    if market_key in {"TWSE", "TPEX", "US"}:
        return market_key
    if market_key == "CUSTOM":
        return "AUTO" if symbol_key.isdigit() else "US"
    return market_key or ("AUTO" if symbol_key.isdigit() else "US")


def _hydrate_portfolio_prices(
    st: Any,
    portfolio: pd.DataFrame,
    *,
    missing_symbols: Sequence[str],
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Try to fetch missing portfolio prices and return a user-facing update log."""

    positions = normalize_portfolio(portfolio)
    missing_set = {str(symbol).strip().upper() for symbol in missing_symbols}
    rows: list[dict[str, Any]] = []
    for _, position in positions.iterrows():
        symbol = str(position["symbol"]).strip().upper()
        if symbol not in missing_set:
            continue
        market = _portfolio_market_for_fetch(symbol, str(position.get("market", "")))
        try:
            update = _ensure_symbol_data(
                st,
                symbol=symbol,
                market=market,
                force_refresh=force_refresh,
            )
            rows.append(
                {
                    "股票代號": symbol,
                    "市場": market,
                    "狀態": "成功",
                    "股價筆數": update["price_rows"],
                    "基本面筆數": update["fundamental_rows"],
                    "說明": "；".join(update["warnings"]) or update["summary"],
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "股票代號": symbol,
                    "市場": market,
                    "狀態": "失敗",
                    "股價筆數": 0,
                    "基本面筆數": 0,
                    "說明": str(exc),
                }
            )
    return pd.DataFrame(rows)


def _get_company_research_profile(st: Any, symbol: str) -> CompanyResearchProfile:
    """Return cached company business context for the AI analysis page."""

    market = _infer_market_for_symbol(st, symbol)
    cache_key = f"{symbol}|{market}"
    cache = st.session_state.company_research_cache
    if cache_key not in cache:
        try:
            source = st.session_state.get("price_data_source") or {}
            offline_cache_fallback = str(
                source.get("source_type") or ""
            ).lower() == "cache" and any(
                not bool(getattr(attempt, "success", False))
                and not str(getattr(attempt, "provider", "")).startswith("cache")
                for attempt in source.get("attempts", ())
            )
            cache[cache_key] = build_company_research_profile(
                symbol,
                market=cast(ProviderMarket, market),
                concept_relations=_canonical_concept_relations(st, symbol),
                allow_remote_fetch=not offline_cache_fallback,
            )
        except Exception as exc:
            cache[cache_key] = build_company_research_profile(
                symbol,
                market=cast(ProviderMarket, market),
                info={
                    "longName": symbol,
                    "longBusinessSummary": "",
                    "sector": "",
                    "industry": "",
                    "symbol": symbol,
                },
                concept_relations=_canonical_concept_relations(st, symbol),
            )
            st.warning(f"公司業務脈絡自動查詢未完成：{exc}")
        st.session_state.company_research_cache = cache
    return cache[cache_key]


def _canonical_concept_relations(st: Any, symbol: str) -> tuple[Any, ...]:
    """Read explicit concept evidence for the current market-qualified symbol only."""

    identity = _canonical_concept_identity(st, symbol)
    if identity is None:
        st.info("概念關聯需要確認市場；數字代號請先透過資料來源或市場選擇建立明確身分。")
        return ()
    try:
        repository = ConceptRepository(ResearchRepository(_runtime_database_path()))
        repository.initialize()
        seed_bundled_dataset(repository)
        return tuple(
            relation
            for concept in repository.concepts()
            for relation in repository.relations_for(
                concept_key=concept.concept_key,
                symbol=identity.symbol,
                market=identity.market,
            )
        )
    except (RepositoryDataError, OSError, ValueError):
        return ()


def _canonical_concept_identity(st: Any, symbol: str) -> ResearchIdentity | None:
    """Resolve canonical evidence identity without guessing a numeric security's market."""

    raw_symbol = str(symbol or "").strip()
    if not raw_symbol:
        return None
    source = st.session_state.price_data_source or {}
    source_market = _canonical_market_or_unknown(source.get("market"))
    try:
        source_symbol = str(source.get("user_symbol") or source.get("query_symbol") or "").strip()
        suffix_identity = Symbol.parse(raw_symbol, market=Market.AUTO)
        if suffix_identity.market in {Market.TWSE, Market.TPEX}:
            if source_market in CANONICAL_MARKETS and source_symbol:
                source_identity = ResearchIdentity(source_symbol, source_market)
                if (
                    source_identity.symbol == suffix_identity.code
                    and source_identity.market != suffix_identity.market.value
                ):
                    return None
            return ResearchIdentity(suffix_identity.code, suffix_identity.market.value)
        if source_market in CANONICAL_MARKETS and source_symbol:
            source_identity = ResearchIdentity(source_symbol, source_market)
            requested_identity = ResearchIdentity(raw_symbol, source_market)
            if source_identity == requested_identity:
                return requested_identity
        if suffix_identity.code.isdigit():
            return None
        return ResearchIdentity(suffix_identity.code, Market.US.value)
    except (RepositoryDataError, ValueError):
        return None


def _infer_market_for_symbol(st: Any, symbol: str) -> str:
    """Infer market for yfinance company-profile lookup."""

    identity = _canonical_concept_identity(st, symbol)
    return identity.market if identity is not None else "AUTO"


def _display_company_research_profile(st: Any, profile: CompanyResearchProfile) -> None:
    """Render business, technology, application, and bottleneck notes."""

    st.markdown("#### 公司業務與產業脈絡")
    if not profile.is_available:
        st.warning("公司業務資料不足。請先用「全自動查詢 / 補資料」或確認股票代號與市場。")

    _display_metric_cards(
        st,
        [
            ("公司名稱", profile.company_name or profile.symbol),
            ("查詢代號", profile.provider_symbol or profile.symbol),
            ("產業", profile.industry),
            ("上層產業", profile.sector),
        ],
    )
    if profile.website:
        st.caption(f"公司網站：{profile.website}")

    st.info("以下為公開資料與本機規則式摘要，用於研究脈絡整理，不是營收占比或投資結論。")
    left, right = st.columns(2)
    with left:
        _write_bullets(st, "主要在做什麼", profile.main_business)
        _write_bullets(st, "技術特點", profile.technical_features)
        _write_bullets(st, "連結到什麼產業 / 題材", profile.linked_industries)
    with right:
        _write_bullets(st, "目前可能運用在哪", profile.current_applications)
        _write_bullets(st, "未來可能運用在哪", profile.future_applications)
        _write_bullets(st, "瓶頸與風險", profile.bottlenecks)

    _write_bullets(st, "建議補充查證", profile.additional_checks)
    with st.expander("資料來源與限制"):
        _write_bullets(st, "資料來源", profile.data_sources)
        _write_bullets(st, "限制", profile.limitations)


def _write_bullets(st: Any, title: str, items: Sequence[str]) -> None:
    """Render a titled bullet list with an explicit no-data fallback."""

    st.markdown(f"**{title}**")
    for item in items or ("資料不足，需補充公司年報、官網或法說資料。",):
        st.write(f"- {item}")


def _concept_market_codes(labels: Sequence[str]) -> tuple[str, ...]:
    """Convert concept lookup market labels to internal market codes."""

    codes: list[str] = []
    for label in labels:
        code = _plain_market_code(str(label))
        if code not in codes:
            codes.append(code)
    return tuple(codes or ["TWSE", "TPEX", "US"])


def _hydrate_concept_matches(
    st: Any,
    matches: pd.DataFrame,
    *,
    limit: int,
    force_refresh: bool,
) -> pd.DataFrame:
    """Fetch prices/fundamentals for concept matches through the existing auto pipeline."""

    rows: list[dict[str, Any]] = []
    for _, match in matches.head(limit).iterrows():
        symbol = str(match.get("symbol", "")).strip()
        market = str(match.get("market", "")).strip().upper()
        name = str(match.get("name", "")).strip()
        if not symbol or market not in {"TWSE", "TPEX", "US"}:
            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "market": market,
                    "status": "失敗",
                    "price_rows": 0,
                    "fundamental_rows": 0,
                    "reason": "缺少股票代號或市場代碼不支援。",
                }
            )
            continue

        try:
            update = _ensure_symbol_data(
                st,
                symbol=symbol,
                market=market,
                force_refresh=force_refresh,
            )
            warning_text = "；".join(update.get("warnings", ()))
            rows.append(
                {
                    "symbol": update["symbol"],
                    "name": name,
                    "market": market,
                    "status": "成功",
                    "price_rows": update["price_rows"],
                    "fundamental_rows": update["fundamental_rows"],
                    "reason": warning_text or update["summary"],
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "market": market,
                    "status": "失敗",
                    "price_rows": 0,
                    "fundamental_rows": 0,
                    "reason": str(exc),
                }
            )
    return pd.DataFrame(rows)


def _display_concept_actions(st: Any, matches: pd.DataFrame, query: str) -> None:
    """Show actions for adding one concept match to watchlist or immediate analysis."""

    if matches.empty:
        return
    st.subheader("單檔操作")
    options = [_concept_option_label(row) for _, row in matches.iterrows()]
    selected_label = st.selectbox("選擇股票", options)
    selected_index = options.index(selected_label)
    selected = matches.iloc[selected_index]
    selected_symbol = str(selected.get("symbol", "")).strip()
    selected_market = str(selected.get("market", "")).strip().upper()

    col1, col2 = st.columns(2)
    if col1.button("加入自選股"):
        watchlist = add_watchlist_symbol(
            _get_watchlist(st),
            symbol=selected_symbol,
            market=selected_market,
            note=f"概念查詢：{query}",
        )
        st.session_state.watchlist = watchlist
        save_watchlist(watchlist, _runtime_watchlist_path())
        st.success(f"已加入自選股：{selected_symbol}")

    if col2.button("立即更新並分析這檔"):
        try:
            update = _ensure_symbol_data(
                st,
                symbol=selected_symbol,
                market=selected_market,
                force_refresh=False,
            )
            st.success(update["summary"])
            _display_warnings(st, list(update.get("warnings", ())))
        except Exception as exc:
            st.error(f"{selected_symbol} 更新失敗：{exc}")


def _concept_option_label(row: pd.Series) -> str:
    """Return a stable label for a concept lookup row."""

    symbol = str(row.get("symbol", "")).strip()
    name = str(row.get("name", "")).strip()
    market = str(row.get("market_label", row.get("market", ""))).strip()
    return f"{symbol} {name} ({market})".strip()


def _ensure_symbol_data(
    st: Any,
    *,
    symbol: str,
    market: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Ensure one symbol has local prices and best-effort fundamentals."""

    display_symbol = _dashboard_symbol(symbol, market)
    if not display_symbol:
        raise ValueError("股票代號不可空白。")

    warnings: list[str] = []
    fetched_price_rows = 0
    fetched_fundamental_rows = 0
    resolved_query_symbol = normalize_yfinance_symbol(
        display_symbol, market=cast(ProviderMarket, market)
    )
    fetch_result = None

    session_prices = st.session_state.price_data
    if session_prices is None:
        session_prices = _load_default_database_prices(_runtime_database_path())
    requested_market = _canonical_market_or_unknown(market)
    existing_prices = _filter_symbol_market(session_prices, display_symbol, requested_market)
    needs_price_fetch = (
        force_refresh
        or existing_prices.empty
        or len(existing_prices) < 60
        or _price_frame_is_stale(existing_prices)
    )

    if needs_price_fetch:
        fetch_result = fetch_prices(
            display_symbol,
            market=cast(ProviderMarket, market),
            provider="auto",
            use_cache=True,
            force_refresh=force_refresh,
            health_tracker=st.session_state.get("provider_health_tracker"),
        )
        fetched_price_rows = len(fetch_result.data)
        resolved_query_symbol = fetch_result.provider_symbol
        warnings.extend(fetch_result.warnings)
        fetched_market = _canonical_market_or_unknown(fetch_result.market)
        fetched_prices = _with_price_provenance(
            _qualify_price_frame(
                fetch_result.data,
                symbol=display_symbol,
                market=fetched_market,
            ),
            provider=fetch_result.source,
            provider_symbol=fetch_result.provider_symbol,
            source_type=fetch_result.source_type,
            last_data_date=fetch_result.last_data_date,
            checked_at=fetch_result.fetched_at,
        )
        _persist_price_data(fetched_prices, _runtime_database_path())
        prices = _merge_price_frames([session_prices, fetched_prices])
        requested_market = fetched_market
    else:
        prices = session_prices
    if prices is None:
        raise ValueError(f"找不到 {display_symbol} 的本機股價資料。")

    _set_price_data(
        st,
        prices,
        source_type=(fetch_result.source_type if fetch_result is not None else "SQLite 匯入資料"),
        provider=fetch_result.source if fetch_result is not None else "sqlite",
        cache_file=fetch_result.cache_file if fetch_result is not None else None,
        user_symbol=display_symbol,
        query_symbol=(
            fetch_result.provider_symbol if fetch_result is not None else resolved_query_symbol
        ),
        market=requested_market if requested_market in CANONICAL_MARKETS else None,
        start_date=(
            fetch_result.start_date
            if fetch_result is not None
            else (str(prices["date"].min()) if "date" in prices.columns else None)
        ),
        end_date=(
            fetch_result.end_date
            if fetch_result is not None
            else (str(prices["date"].max()) if "date" in prices.columns else None)
        ),
        fetched_at=fetch_result.fetched_at if fetch_result is not None else None,
        last_data_date=fetch_result.last_data_date if fetch_result is not None else None,
        cache_state=fetch_result.cache_state if fetch_result is not None else None,
        cache_age_seconds=fetch_result.cache_age_seconds if fetch_result is not None else None,
        attempts=fetch_result.attempts if fetch_result is not None else (),
        row_count=len(fetch_result.data) if fetch_result is not None else len(prices),
    )

    fundamentals = st.session_state.fundamentals
    if fundamentals is None:
        fundamentals = _load_all_fundamentals()
        _set_fundamentals_state(st, fundamentals)

    offline_cache_fallback = bool(
        fetch_result is not None
        and fetch_result.from_cache
        and any(
            not attempt.success and not str(attempt.provider).startswith("cache")
            for attempt in fetch_result.attempts
        )
    )
    if offline_cache_fallback and (
        force_refresh
        or not _has_fundamental_row(
            st.session_state.fundamentals,
            display_symbol,
            requested_market,
        )
    ):
        warnings.append("價格已從本機快取回退；已略過基本面線上查詢，避免離線等待。")
    elif force_refresh or not _has_fundamental_row(
        st.session_state.fundamentals,
        display_symbol,
        requested_market,
    ):
        try:
            fundamental_result = fetch_yfinance_fundamentals(
                display_symbol, market=cast(ProviderMarket, market)
            )
            fetched_fundamental_rows = len(fundamental_result.data)
            _persist_auto_fundamentals(fundamental_result.data)
            fundamentals = _merge_fundamental_identity_frames(
                [
                    st.session_state.fundamentals,
                    _qualify_generic_frame(
                        fundamental_result.data,
                        symbol=display_symbol,
                        market=requested_market,
                    ),
                ]
            )
            _set_fundamentals_state(st, fundamentals)
            warnings.extend(fundamental_result.warnings)
        except FundamentalFetchError as exc:
            warnings.append(f"基本面自動抓取未完成：{exc}")

    st.session_state.active_symbol = display_symbol
    if st.session_state.price_data_source is not None:
        st.session_state.price_data_source["warnings"] = tuple(warnings)
    summary = (
        f"{display_symbol} 已更新；股價新增/刷新 {fetched_price_rows} 筆，"
        f"基本面新增/刷新 {fetched_fundamental_rows} 筆。"
    )
    return {
        "symbol": display_symbol,
        "market": market,
        "price_rows": fetched_price_rows,
        "fundamental_rows": fetched_fundamental_rows,
        "provider": (fetch_result.source if fetch_result is not None else "sqlite"),
        "query_symbol": (
            fetch_result.provider_symbol if fetch_result is not None else resolved_query_symbol
        ),
        "source_type": (fetch_result.source_type if fetch_result is not None else "sqlite"),
        "last_data_date": (fetch_result.last_data_date if fetch_result is not None else None),
        "fetched_at": fetch_result.fetched_at if fetch_result is not None else None,
        "warnings": warnings,
        "summary": summary,
    }


def _price_frame_is_stale(prices: pd.DataFrame, *, max_age_hours: int = 24) -> bool:
    """Return whether explicit provider check metadata is older than the refresh window.

    Legacy rows without per-identity check metadata remain usable and are not silently
    treated as fresh or forced into a network request.
    """

    if prices.empty or "checked_at" not in prices.columns:
        return False
    values = pd.to_datetime(prices["checked_at"], errors="coerce", utc=True).dropna()
    if values.empty:
        return False
    newest = values.max()
    age = pd.Timestamp.now(tz="UTC") - newest
    return age > pd.Timedelta(hours=max_age_hours)


def _build_research_snapshot(st: Any, *, symbol: str, market: str) -> Any:
    """Assemble one immutable workspace snapshot from existing session research results."""

    canonical_market = _canonical_market_or_unknown(market)
    if canonical_market not in CANONICAL_MARKETS:
        raise ValueError("Research Workspace requires an explicit canonical market.")
    display_symbol = _dashboard_symbol(symbol, canonical_market)
    canonical_symbol = Symbol(display_symbol, Market.parse(canonical_market))
    prices = _filter_symbol_market(st.session_state.price_data, display_symbol, canonical_market)
    indicators = _filter_identity(
        st.session_state.technical_indicators,
        symbol=display_symbol,
        market=canonical_market,
    )
    fundamentals = _filter_identity(
        st.session_state.fundamental_scores,
        symbol=display_symbol,
        market=canonical_market,
    )
    score = None
    scenario = None
    if not prices.empty:
        score = score_stock(
            symbol=display_symbol,
            price_data=prices,
            technical_indicators=indicators if not indicators.empty else None,
            fundamental_scores=fundamentals if not fundamentals.empty else None,
            backtest_result=_research_backtest_result(
                st,
                symbol=display_symbol,
                market=canonical_market,
            ),
        )
        scenario = estimate_entry_reference(
            prices,
            indicators if not indicators.empty else None,
            symbol=display_symbol,
        )
    source = st.session_state.price_data_source or {}
    source_metadata = ResearchSourceMetadata(
        provider=_optional_text(source.get("provider")),
        query_symbol=_optional_text(source.get("query_symbol")) or display_symbol,
        market=canonical_market,
        source_type=_research_source_type(source.get("source_type")),
        fetched_at=_optional_text(source.get("updated_at")),
        last_data_date=(
            str(prices["date"].max()) if not prices.empty and "date" in prices else None
        ),
        row_count=len(prices),
        warnings=tuple(source.get("warnings") or ()),
        limitations=("資料來源類型與最後資料日期依本次已載入資料顯示；不宣稱即時行情。",),
    )
    profile = _get_company_research_profile(st, display_symbol)
    return ResearchWorkspaceService().build(
        symbol=canonical_symbol,
        price_data=prices if not prices.empty else None,
        indicators=indicators if not indicators.empty else None,
        fundamental_results=fundamentals if not fundamentals.empty else None,
        stock_score=score,
        company_profile=profile,
        scenario_reference=scenario,
        source_metadata=source_metadata,
        is_stale=str(st.session_state.dashboard_status) == "stale",
    )


def _research_source_type(value: object) -> str:
    """Translate legacy source labels without overstating cache or sample provenance."""

    source = str(value or "").strip().lower()
    if "線上" in source or source == "online":
        return "online"
    if "快取" in source or source == "cache":
        return "cache"
    if "上傳" in source or source in {"upload", "user_upload"}:
        return "user_upload"
    if "sample" in source or "範例" in source:
        return "sample"
    if "sqlite" in source or "匯入" in source or source in {"local", "local_file"}:
        return "local_file"
    return "unknown"


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _set_price_data(
    st: Any,
    frame: pd.DataFrame,
    *,
    source_type: str,
    provider: str,
    cache_file: Path | None,
    user_symbol: str | None = None,
    query_symbol: str | None = None,
    market: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    fetched_at: str | None = None,
    last_data_date: str | None = None,
    cache_state: str | None = None,
    cache_age_seconds: float | None = None,
    attempts: Sequence[Any] = (),
    row_count: int | None = None,
    warnings: Sequence[str] = (),
) -> None:
    """Store price data and explicit source metadata in Streamlit state."""

    st.session_state.price_data = _normalize_price_identity_frame(frame)
    try:
        st.session_state.technical_indicators = compute_technical_indicators(
            st.session_state.price_data
        )
    except Exception:
        st.session_state.technical_indicators = None
    metadata = {
        "source_type": source_type,
        "provider": provider,
        "user_symbol": user_symbol,
        "query_symbol": query_symbol,
        "market": market,
        "start_date": start_date,
        "end_date": end_date,
        "cache_file": str(cache_file) if cache_file else None,
        "fetched_at": fetched_at,
        "last_data_date": last_data_date,
        "cache_state": cache_state,
        "cache_age_seconds": cache_age_seconds,
        "attempts": tuple(attempts),
        "row_count": row_count,
    }
    sanitized_warnings = tuple(sanitize_provider_text(item) for item in warnings)
    if sanitized_warnings:
        metadata["warnings"] = sanitized_warnings
    st.session_state.price_data_source = metadata


def _normalize_price_identity_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize available market values while preserving unknown legacy rows."""

    output = frame.copy(deep=True)
    if "symbol" in output.columns:
        output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    if "market" not in output.columns:
        output["market"] = "UNKNOWN"
    output["market"] = output["market"].map(_canonical_market_or_unknown)
    return output


def _qualify_price_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    market: str,
) -> pd.DataFrame:
    """Attach a market only to rows returned for the explicitly requested symbol."""

    output = _normalize_price_identity_frame(frame)
    if market not in CANONICAL_MARKETS or "symbol" not in output.columns:
        return output
    symbol_key = str(symbol).strip().upper()
    mask = output["symbol"].eq(symbol_key) & output["market"].eq("UNKNOWN")
    output.loc[mask, "market"] = market
    return output


def _with_price_provenance(
    frame: pd.DataFrame,
    *,
    provider: str | None,
    provider_symbol: str | None,
    source_type: str | None,
    last_data_date: str | None,
    checked_at: str | None,
) -> pd.DataFrame:
    """Attach explicit per-identity provenance without changing OHLCV values."""

    output = _normalize_price_identity_frame(frame)
    output["provider"] = provider
    output["provider_symbol"] = provider_symbol
    output["source_type"] = source_type
    output["last_data_date"] = last_data_date
    output["checked_at"] = checked_at
    output["fetched_at"] = checked_at
    return output


def _canonical_market_or_unknown(value: object) -> str:
    """Normalize a market label without inferring an unknown identity."""

    try:
        market = Market.parse(str(value))
    except ValueError:
        return "UNKNOWN"
    return market.value if market.value in CANONICAL_MARKETS else "UNKNOWN"


def _unique_market_map(prices: pd.DataFrame) -> dict[str, str]:
    """Map symbols to markets only when the known identity is unambiguous."""

    if prices.empty or not {"symbol", "market"}.issubset(prices.columns):
        return {}
    output = _normalize_price_identity_frame(prices)
    output = output.loc[output["market"].isin(CANONICAL_MARKETS)]
    markets_by_symbol = output.groupby("symbol", sort=False)["market"].agg(
        lambda values: tuple(sorted(set(values)))
    )
    return {
        str(symbol): markets[0]
        for symbol, markets in markets_by_symbol.items()
        if len(markets) == 1
    }


def _qualify_generic_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    market: str,
) -> pd.DataFrame:
    """Attach an explicitly fetched market to only its requested generic-data rows."""

    output = frame.copy(deep=True)
    if "symbol" not in output.columns:
        return output
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    if "market" not in output.columns:
        output["market"] = "UNKNOWN"
    output["market"] = output["market"].map(_canonical_market_or_unknown)
    if market in CANONICAL_MARKETS:
        mask = output["symbol"].eq(str(symbol).strip().upper()) & output["market"].eq("UNKNOWN")
        output.loc[mask, "market"] = market
    return output


def _merge_fundamental_identity_frames(
    frames: Sequence[pd.DataFrame | None],
) -> pd.DataFrame | None:
    """Merge fundamental snapshots only on the full canonical identity."""

    non_empty = [frame.copy(deep=True) for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return None
    combined = pd.concat(non_empty, ignore_index=True, sort=False)
    if "symbol" not in combined.columns:
        return combined
    combined = _qualify_generic_frame(combined, symbol="", market="UNKNOWN")
    if "fiscal_period" not in combined.columns:
        combined["fiscal_period"] = pd.NA
    keys = ["symbol", "market", "fiscal_period"]
    combined["_fundamental_input_order"] = range(len(combined))
    combined["_fundamental_identity_order"] = combined.groupby(["symbol", "market"], sort=False)[
        "_fundamental_input_order"
    ].transform("min")
    ordering_columns = ["_fundamental_identity_order", "fiscal_period"]
    ordering_columns.extend(
        column for column in ("as_of_date", "updated_at", "date") if column in combined.columns
    )
    ordering_columns.append("_fundamental_input_order")
    combined = combined.sort_values(ordering_columns, kind="stable")
    combined = combined.drop_duplicates(subset=keys, keep="last")
    return combined.drop(
        columns=["_fundamental_input_order", "_fundamental_identity_order"]
    ).reset_index(drop=True)


def _set_fundamentals_state(st: Any, fundamentals: pd.DataFrame | None) -> None:
    """Store fundamentals and derived scores without inventing market identity."""

    if fundamentals is None or fundamentals.empty:
        st.session_state.fundamentals = fundamentals
        st.session_state.fundamental_scores = None
        return
    normalized = _qualify_generic_frame(fundamentals, symbol="", market="UNKNOWN")
    # Legacy rows remain UNKNOWN. A canonical market can only be attached by a
    # provider result for that explicit request, never inferred from prices.
    st.session_state.fundamentals = normalized
    st.session_state.fundamental_scores = score_fundamentals(normalized)


def _display_data_source(st: Any) -> None:
    """Display current price data source metadata when available."""

    metadata = st.session_state.price_data_source
    if not metadata:
        return
    st.caption(_source_label(metadata))


def _source_label(metadata: dict[str, Any]) -> str:
    """Format price data source metadata without overstating online provenance."""

    source_type = metadata.get("source_type") or "未知"
    provider = metadata.get("provider") or "未知"
    query_symbol = metadata.get("query_symbol") or "-"
    market = metadata.get("market") or "-"
    start_date = metadata.get("start_date") or "-"
    end_date = metadata.get("end_date") or "-"
    cache_file = metadata.get("cache_file") or "-"
    return (
        f"目前資料來源：{source_type}；資料提供者：{provider}；實際查詢代號：{query_symbol}；"
        f"市場：{market}；日期區間：{start_date} 到 {end_date}；快取檔案：{cache_file}"
    )


def _market_code(label: str) -> str:
    mapping = {
        "台股上市 TWSE": "TWSE",
        "台股上櫃 TPEx": "TPEX",
        "美股 US": "US",
    }
    return mapping[label]


def _plain_market_code(label: str) -> str:
    mapping = {
        "台股上市 TWSE": "TWSE",
        "台股上櫃 TPEx": "TPEX",
        "美股 US": "US",
        "?啗銝? TWSE": "TWSE",
        "?啗銝? TPEx": "TPEX",
        "蝢 US": "US",
    }
    return mapping[label]


def _dashboard_symbol(symbol: str, market: str) -> str:
    value = str(symbol).strip().upper()
    if market in {"TWSE", "TPEX"} and value.endswith((".TW", ".TWO")):
        return value.rsplit(".", 1)[0]
    return value


def _market_for_backtest_record(st: Any, symbol: str) -> str | None:
    """Persist a market only when the existing dashboard identity is explicit."""

    market = _canonical_market_or_unknown(_infer_market_for_symbol(st, symbol))
    return market if market in CANONICAL_MARKETS else None


def _research_backtest_result(
    st: Any,
    *,
    symbol: str,
    market: str,
) -> BacktestResult | None:
    """Return a backtest only when its recorded canonical identity matches research."""

    result = st.session_state.get("backtest_result")
    parameters = st.session_state.get("last_parameters")
    if result is None or not isinstance(parameters, dict):
        return None

    recorded_symbol = str(parameters.get("symbol") or "").strip()
    recorded_market = _canonical_market_or_unknown(parameters.get("market"))
    target_market = _canonical_market_or_unknown(market)
    if not recorded_symbol or recorded_market not in CANONICAL_MARKETS:
        return None
    if target_market not in CANONICAL_MARKETS or recorded_market != target_market:
        return None

    normalized_recorded_symbol = _dashboard_symbol(recorded_symbol, recorded_market)
    normalized_target_symbol = _dashboard_symbol(symbol, target_market)
    if normalized_recorded_symbol != normalized_target_symbol:
        return None
    return result


def _provider_code(label: str) -> str:
    mapping = {
        "自動備援": "auto",
        "yfinance": "yfinance",
        "FinMind（需 FINMIND_TOKEN）": "finmind",
        "快取": "cache",
        "CSV 上傳": "csv",
    }
    return mapping[label]


def load_price_upload(uploaded_file: BinaryIO) -> tuple[pd.DataFrame, list[str]]:
    """Load, standardize, and clean an uploaded price CSV."""

    raw = pd.read_csv(uploaded_file, dtype={"symbol": str})
    standardized = standardize_price_columns(raw)
    warning_messages: list[str] = []
    import warnings

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", PriceDataWarning)
        cleaned = clean_price_data(standardized.to_dict("records"))
    warning_messages.extend(str(item.message) for item in captured)
    return pd.DataFrame(cleaned.records), warning_messages


def load_fundamentals_upload(uploaded_file: BinaryIO) -> pd.DataFrame:
    """Load an uploaded fundamental CSV through the project loader."""

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(uploaded_file.read())
        path = Path(tmp.name)
    return load_fundamentals_csv(path)


def _load_sample_prices() -> pd.DataFrame:
    """Load bundled sample price data for the dashboard import page."""

    return pd.read_csv(SAMPLE_PRICE_FILE, dtype={"symbol": str})


def _load_default_database_prices(database_path: Path | None = None) -> pd.DataFrame | None:
    """Load market-qualified sidecar rows plus safe UNKNOWN legacy SQLite rows."""

    database_path = database_path or _runtime_database_path()
    if not database_path.exists():
        return None
    storage = SQLitePriceStorage(database_path)
    qualified_context = storage.load_market_qualified_price_context()
    legacy_rows = storage.load_price_data()
    frames: list[pd.DataFrame] = []
    qualified = pd.DataFrame(qualified_context.records)
    if not qualified.empty:
        frames.append(qualified)
    legacy = pd.DataFrame(legacy_rows)
    if not legacy.empty:
        legacy = _normalize_price_identity_frame(legacy)
        if not qualified.empty and {"symbol", "date"}.issubset(qualified.columns):
            known_keys = set(
                zip(
                    qualified["symbol"].astype(str).str.upper(),
                    qualified["date"].astype(str),
                    strict=True,
                )
            )
            legacy = legacy.loc[
                [
                    (str(row.symbol).upper(), str(row.date)) not in known_keys
                    for row in legacy[["symbol", "date"]].itertuples(index=False)
                ]
            ].copy()
        if not legacy.empty:
            frames.append(legacy)
    if not frames:
        return None
    output = pd.concat(frames, ignore_index=True, sort=False)
    output.attrs["price_identity_warnings"] = qualified_context.warnings
    return output


def _persist_price_data(frame: pd.DataFrame, database_path: Path | None = None) -> int:
    """Persist prices, using a sidecar only for explicit market-qualified rows."""

    if frame.empty:
        return 0
    missing = [column for column in STANDARD_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Cannot persist price data with missing columns: {missing}")
    storage = SQLitePriceStorage(database_path or _runtime_database_path())
    normalized = _normalize_price_identity_frame(frame)
    saved_rows = 0
    known = normalized.loc[normalized["market"].isin(CANONICAL_MARKETS)].copy()
    for (symbol_code, market), group in known.groupby(["symbol", "market"], sort=True):
        identity = Symbol.parse(str(symbol_code), market=str(market))
        provenance = PersistedPriceProvenance(
            symbol=identity,
            provider=_single_frame_text(group, "provider"),
            provider_symbol=_single_frame_text(group, "provider_symbol"),
            source_type=_single_frame_text(group, "source_type"),
            last_data_date=_single_frame_text(group, "last_data_date") or _latest_frame_date(group),
            checked_at=(
                _single_frame_text(group, "checked_at") or _single_frame_text(group, "fetched_at")
            ),
            fetched_at=_single_frame_text(group, "fetched_at"),
        )
        records = group.loc[:, list(STANDARD_COLUMNS)].to_dict("records")
        saved_rows += storage.save_market_qualified_price_data(records, provenance=provenance)

    unknown = normalized.loc[~normalized["market"].isin(CANONICAL_MARKETS)]
    if not unknown.empty:
        saved_rows += storage.save_price_data(
            unknown.loc[:, list(STANDARD_COLUMNS)].to_dict("records")
        )
    return saved_rows


def _single_frame_text(frame: pd.DataFrame, column: str) -> str | None:
    """Return an explicit shared value only when an identity has one unambiguous value."""

    if column not in frame.columns:
        return None
    values = tuple(
        dict.fromkeys(
            str(value).strip()
            for value in frame[column].tolist()
            if value is not None and str(value).strip() and str(value).lower() != "nan"
        )
    )
    return values[0] if len(values) == 1 else None


def _latest_frame_date(frame: pd.DataFrame) -> str | None:
    """Return an actual latest OHLCV date without substituting a current timestamp."""

    if "date" not in frame.columns:
        return None
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    return dates.max().date().isoformat() if not dates.empty else None


def _load_sample_fundamentals() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load bundled sample fundamentals and derived scores."""

    fundamentals = load_fundamentals_csv(SAMPLE_FUNDAMENTAL_FILE)
    return fundamentals, score_fundamentals(fundamentals)


def _load_all_fundamentals() -> pd.DataFrame | None:
    """Load bundled and automatically fetched fundamentals into one frame."""

    frames: list[pd.DataFrame] = []
    if SAMPLE_FUNDAMENTAL_FILE.exists():
        frames.append(load_fundamentals_csv(SAMPLE_FUNDAMENTAL_FILE))
    auto_fundamental_file = _runtime_fundamentals_path()
    if auto_fundamental_file.exists():
        frames.append(load_fundamentals_csv(auto_fundamental_file))
    if not frames:
        return None
    return _merge_fundamentals(frames)


def _persist_auto_fundamentals(frame: pd.DataFrame) -> int:
    """Persist best-effort auto-fetched fundamental data for future sessions."""

    if frame.empty:
        return 0
    auto_fundamental_file = _runtime_fundamentals_path()
    auto_fundamental_file.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        load_fundamentals_csv(auto_fundamental_file) if auto_fundamental_file.exists() else None
    )
    combined = _merge_fundamentals([item for item in (existing, frame) if item is not None])
    combined.to_csv(auto_fundamental_file, index=False, encoding="utf-8-sig")
    return len(frame)


def _merge_fundamentals(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge fundamentals on symbol, market, and fiscal-period identity."""

    combined = _merge_fundamental_identity_frames(frames)
    return combined if combined is not None else pd.DataFrame(columns=list(FUNDAMENTAL_COLUMNS))


def _has_fundamental_row(
    frame: pd.DataFrame | None,
    symbol: str,
    market: str,
) -> bool:
    """Return whether a canonical fundamental identity is already available."""

    return not _filter_identity(frame, symbol=symbol, market=market).empty


def standardize_price_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize uploaded price DataFrame columns to the standard schema."""

    rename_map: dict[str, str] = {}
    for column in frame.columns:
        normalized = str(column).strip().lower().replace(" ", "_").replace("-", "_")
        mapped = COLUMN_ALIASES.get(normalized, normalized)
        if mapped in STANDARD_COLUMNS:
            rename_map[column] = mapped
    output = frame.rename(columns=rename_map).copy(deep=True)
    missing = [column for column in REQUIRED_COLUMNS if column not in output.columns]
    if missing:
        raise ValueError(f"缺少必要欄位：{', '.join(missing)}")
    for column in STANDARD_COLUMNS:
        if column not in output.columns:
            output[column] = None
    return output.loc[:, list(STANDARD_COLUMNS)]


def compute_technical_indicators(price_data: pd.DataFrame) -> pd.DataFrame:
    """Compute indicators per canonical identity without mixing price histories."""

    data = price_data.copy(deep=True)
    if {"symbol", "market"}.issubset(data.columns):
        data = _normalize_price_identity_frame(data)
        frames = [
            _compute_technical_indicator_group(group)
            for _, group in data.groupby(["symbol", "market"], sort=False, dropna=False)
        ]
        return pd.concat(frames, ignore_index=True, sort=False) if frames else data
    return _compute_technical_indicator_group(data)


def _compute_technical_indicator_group(price_data: pd.DataFrame) -> pd.DataFrame:
    """Apply existing indicator functions to one already-isolated price history."""

    data = price_data.copy(deep=True)
    if "date" in data.columns:
        data = data.sort_values("date", kind="stable").reset_index(drop=True)
    data = add_sma(data)
    data = add_ema(data)
    data = add_rsi(data)
    data = add_macd(data)
    data = add_bollinger_bands(data)
    data = add_atr(data)
    data = add_stochastic_oscillator(data)
    data = add_volume_moving_average(data)
    data = add_bias(data)
    data = add_rolling_return(data, periods=(5, 20, 60))
    data = add_rolling_volatility(data, periods=(5, 20, 60))
    return data


def compute_drawdown(equity_curve: pd.DataFrame) -> pd.Series:
    """Compute drawdown series from an equity curve without mutating input."""

    if equity_curve.empty or "total_equity" not in equity_curve.columns:
        return pd.Series(dtype=float)
    equity = equity_curve["total_equity"].astype(float)
    peak = equity.cummax()
    return (equity / peak.where(peak != 0)) - 1.0


def _render_backtest_cost_controls(
    st: Any,
    market: str,
) -> tuple[BacktestCostPreset, float, float, float]:
    """Render persistent cost inputs while keeping preset decisions explicit."""

    _prepare_backtest_cost_state(st, market)
    st.selectbox(
        "交易成本預設",
        [item.value for item in BacktestCostPreset],
        format_func=lambda value: cost_assumptions(BacktestCostPreset(value)).label,
        key="backtest_cost_preset",
        on_change=_apply_selected_backtest_cost_preset,
        args=(st,),
        help="市場預設只提供研究假設；自行調整成本後會保留為自訂設定。",
    )
    preset = BacktestCostPreset(st.session_state.backtest_cost_preset)
    if preset is BacktestCostPreset.CUSTOM:
        st.caption("自訂成本設定會在 Streamlit rerun 與市場切換後保留，直到你選擇其他預設。")
    with st.expander("進階交易成本與執行設定"):
        st.caption(cost_assumptions(preset).limitation)
        st.number_input(
            "手續費 (%)",
            min_value=0.0,
            step=0.0001,
            format="%.4f",
            key="backtest_commission_pct",
            on_change=_mark_backtest_costs_custom,
            args=(st,),
        )
        st.number_input(
            "賣出稅費 (%)",
            min_value=0.0,
            step=0.0001,
            format="%.4f",
            key="backtest_tax_pct",
            on_change=_mark_backtest_costs_custom,
            args=(st,),
        )
        st.number_input(
            "滑價 (%)",
            min_value=0.0,
            step=0.0001,
            format="%.4f",
            key="backtest_slippage_pct",
            on_change=_mark_backtest_costs_custom,
            args=(st,),
        )
        st.caption("成交模型：訊號在 T 日產生，最早使用下一根 K 棒開盤價成交。")
    return (
        BacktestCostPreset(st.session_state.backtest_cost_preset),
        percent_to_rate(float(st.session_state.backtest_commission_pct)),
        percent_to_rate(float(st.session_state.backtest_tax_pct)),
        percent_to_rate(float(st.session_state.backtest_slippage_pct)),
    )


def _prepare_backtest_cost_state(st: Any, market: str) -> None:
    """Apply a market preset only when the user has not retained custom rates."""

    state = st.session_state
    market_changed = state.get("backtest_cost_market") != market
    if "backtest_cost_preset" not in state:
        _set_backtest_cost_preset(st, resolve_cost_preset(market))
    elif market_changed and not bool(state.get("backtest_costs_user_edited", False)):
        _set_backtest_cost_preset(
            st,
            resolve_cost_preset(
                market, current_preset=BacktestCostPreset(state.backtest_cost_preset)
            ),
        )
    state["backtest_cost_market"] = market


def _apply_selected_backtest_cost_preset(st: Any) -> None:
    """Apply an intentionally chosen named preset before rendering its inputs."""

    preset = BacktestCostPreset(st.session_state.backtest_cost_preset)
    if preset is BacktestCostPreset.CUSTOM:
        st.session_state.backtest_costs_user_edited = True
        return
    _set_backtest_cost_preset(st, preset)


def _set_backtest_cost_preset(st: Any, preset: BacktestCostPreset) -> None:
    """Set one named preset in user-facing percentages without changing engine rules."""

    assumptions = cost_assumptions(preset)
    state = st.session_state
    state["backtest_cost_preset"] = preset.value
    state["backtest_commission_pct"] = rate_to_percent(assumptions.commission_rate)
    state["backtest_tax_pct"] = rate_to_percent(assumptions.tax_rate)
    state["backtest_slippage_pct"] = rate_to_percent(assumptions.slippage_rate)
    state["backtest_costs_user_edited"] = preset is BacktestCostPreset.CUSTOM


def _mark_backtest_costs_custom(st: Any) -> None:
    """Mark direct cost edits as custom so reruns never silently overwrite them."""

    st.session_state.backtest_cost_preset = BacktestCostPreset.CUSTOM.value
    st.session_state.backtest_costs_user_edited = True


def _display_backtest_preflight(
    st: Any,
    summary: BacktestSummary,
    validation: BacktestValidationResult,
) -> None:
    """Render an auditable preflight summary before the existing engine is invoked."""

    columns = st.columns(4)
    columns[0].metric("資料筆數", summary.data_rows)
    columns[1].metric("策略投入比例", f"{rate_to_percent(summary.allocation_rate):.2f}%")
    columns[2].metric("單一持股上限", f"{rate_to_percent(summary.max_position_pct):.2f}%")
    columns[3].metric("執行模型", summary.execution_model)
    st.caption(
        f"標的：{summary.symbol}/{summary.market}；幣別：{summary.currency or '未確認'}；"
        f"資料：{summary.data_range}；來源：{summary.data_source}；"
        f"手續費 {rate_to_percent(summary.broker_config.commission_rate):.4f}%；"
        f"賣出稅費 {rate_to_percent(summary.broker_config.tax_rate):.4f}%；"
        f"滑價 {rate_to_percent(summary.broker_config.slippage_rate):.4f}%；"
        f"移動停利：{summary.trailing_stop_status}。"
    )
    if validation.can_execute:
        st.success("設定可執行。請確認此研究假設符合你的檢驗目的。")


def _display_backtest_interpretation(
    st: Any,
    result: BacktestResult,
    summary: BacktestSummary,
) -> None:
    """Explain an existing backtest result without inventing an investment conclusion."""

    metrics = result.metrics
    _display_metric_cards(
        st,
        [
            ("總報酬率", _percent(metrics.total_return)),
            ("CAGR", _percent(metrics.cagr)),
            ("最大回撤", _percent(metrics.max_drawdown)),
            ("Sharpe Ratio", _number(metrics.sharpe_ratio)),
            ("交易次數", metrics.number_of_trades),
        ],
    )
    st.caption(
        f"資料期間：{summary.data_range}；策略：{BACKTEST_STRATEGY_LABELS.get(summary.strategy_key, summary.strategy_key)}；"
        f"成交：{summary.execution_model}；成本已套用手續費、賣出稅費與滑價。"
    )
    no_trade_message = no_trade_explanation(len(result.trades))
    if no_trade_message is not None:
        st.info(no_trade_message)
    st.caption("歷史回測結果不代表未來報酬；請檢查樣本外期間、成本假設與資料品質。")


def _strategy_controls(st: Any, *, strategy_key: str, target_percent: float) -> Any:
    """Render only existing strategy parameters and return the existing strategy class."""

    if strategy_key == "ma_cross":
        short = st.number_input("短均線", min_value=2, value=20, step=1)
        long = st.number_input("長均線", min_value=3, value=60, step=1)
        return create_strategy(
            strategy_key,
            {
                "short_window": int(short),
                "long_window": int(long),
                "target_percent": target_percent,
            },
        )
    if strategy_key == "breakout":
        lookback = st.number_input("突破回看天數", min_value=2, value=20, step=1)
        return create_strategy(
            strategy_key, {"lookback": int(lookback), "target_percent": target_percent}
        )
    if strategy_key == "rsi_reversal":
        oversold = st.slider("RSI 低檔門檻", 5.0, 50.0, 30.0, 1.0)
        overbought = st.slider("RSI 高檔門檻", 50.0, 95.0, 70.0, 1.0)
        return create_strategy(
            strategy_key,
            {"oversold": oversold, "overbought": overbought, "target_percent": target_percent},
        )
    if strategy_key == "macd_trend":
        return create_strategy(strategy_key, {"target_percent": target_percent})
    if strategy_key == "volume_price_breakout":
        lookback = st.number_input("價格突破回看天數", min_value=2, value=20, step=1)
        volume_window = st.number_input("成交量均線天數", min_value=2, value=20, step=1)
        multiplier = st.number_input("成交量倍數", min_value=0.1, value=1.5, step=0.1)
        return create_strategy(
            strategy_key,
            {
                "lookback": int(lookback),
                "volume_window": int(volume_window),
                "volume_multiplier": float(multiplier),
                "target_percent": target_percent,
            },
        )
    return create_strategy(strategy_key, {"target_percent": target_percent})


def _display_metrics(st: Any, result: BacktestResult) -> None:
    metrics = result.metrics
    _display_metric_cards(
        st,
        [
            ("總報酬率", _percent(metrics.total_return)),
            ("年化報酬率", _percent(metrics.cagr)),
            ("最大回撤", _percent(metrics.max_drawdown)),
            ("交易次數", metrics.number_of_trades),
        ],
    )
    detail = pd.DataFrame(
        [
            {"指標": "年化波動率", "數值": _percent(metrics.annualized_volatility)},
            {"指標": "夏普比率", "數值": _number(metrics.sharpe_ratio)},
            {"指標": "Sortino 比率", "數值": _number(metrics.sortino_ratio)},
            {"指標": "勝率", "數值": _percent(metrics.win_rate)},
            {"指標": "盈虧比", "數值": _number(metrics.profit_factor)},
            {"指標": "曝險比例", "數值": _percent(metrics.exposure)},
        ]
    )
    _display_table(st, detail)


def _display_equity_and_drawdown(st: Any, equity_curve: pd.DataFrame) -> None:
    if equity_curve.empty:
        st.warning(INSUFFICIENT_DATA)
        return
    left, right = st.columns(2)
    left.subheader("資金曲線")
    _display_line_chart(left, equity_curve, ["total_equity"])
    right.subheader("最大回撤")
    drawdown = compute_drawdown(equity_curve)
    drawdown_frame = pd.DataFrame({"date": equity_curve["date"], "drawdown": drawdown})
    _display_line_chart(right, drawdown_frame, ["drawdown"])


def _display_line_chart(container: Any, frame: pd.DataFrame, columns: Sequence[str]) -> None:
    """Display a date-indexed line chart when requested columns are available."""

    if frame.empty or "date" not in frame.columns:
        return
    available = [column for column in columns if column in frame.columns]
    if not available:
        return
    chart_data = frame.set_index("date")[available]
    if len(available) == 1:
        chart_data = chart_data[available[0]]
    container.line_chart(chart_data)


def _build_report_data(
    st: Any,
    symbol: str,
    prices: pd.DataFrame,
    result: BacktestResult | None,
) -> ReportData:
    """Build the report payload from current dashboard state."""

    indicators = st.session_state.technical_indicators
    return ReportData(
        symbol=symbol,
        market=_infer_market_for_symbol(st, symbol),
        price_data=_filter_symbol(prices, symbol),
        technical_indicators=_filter_symbol(indicators, symbol) if indicators is not None else None,
        fundamental_scores=st.session_state.fundamental_scores,
        backtest_result=result,
        risk_alerts=st.session_state.risk_alerts,
        parameters=st.session_state.last_parameters,
        provider_metadata=st.session_state.get("price_data_source"),
    )


def _display_excel_download(st: Any, report_data: ReportData, symbol: str) -> None:
    """Generate a temporary Excel report and expose a download button."""

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        output_path = Path(tmp.name)
    package = ReportingService().build_package(report_data)
    generate_excel_report(package, output_path)
    st.download_button(
        label="下載 Excel 報表",
        data=output_path.read_bytes(),
        file_name=f"{symbol}_stock_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _require_prices(st: Any) -> pd.DataFrame | None:
    prices = st.session_state.price_data
    if prices is None or prices.empty:
        st.warning("尚未匯入股價資料。請先到「資料匯入」。")
        return None
    return prices


def _select_symbol(st: Any, prices: pd.DataFrame) -> str:
    symbols = sorted(prices["symbol"].astype(str).unique().tolist())
    active_symbol = st.session_state.get("active_symbol")
    if active_symbol in symbols:
        symbols = [active_symbol, *[symbol for symbol in symbols if symbol != active_symbol]]
    return st.selectbox("股票代號", symbols)


def _filter_symbol(frame: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    if frame is None or frame.empty or "symbol" not in frame.columns:
        return pd.DataFrame()
    symbol_key = str(symbol).strip().upper()
    symbols = frame["symbol"].fillna("").astype(str).str.strip().str.upper()
    return frame.loc[symbols == symbol_key].copy(deep=True)


def _filter_symbol_market(
    frame: pd.DataFrame | None,
    symbol: str,
    market: str,
) -> pd.DataFrame:
    """Return one reliable price history for the full canonical identity."""

    if (
        frame is None
        or frame.empty
        or market not in CANONICAL_MARKETS
        or not {"symbol", "market"}.issubset(frame.columns)
    ):
        return pd.DataFrame()
    output = _normalize_price_identity_frame(frame)
    mask = output["symbol"].eq(str(symbol).strip().upper()) & output["market"].eq(market)
    return output.loc[mask].copy(deep=True)


def _filter_identity(
    frame: pd.DataFrame | None,
    *,
    symbol: str,
    market: str,
) -> pd.DataFrame:
    """Filter any market-qualified research frame without changing its input."""

    if (
        frame is None
        or frame.empty
        or market not in CANONICAL_MARKETS
        or not {"symbol", "market"}.issubset(frame.columns)
    ):
        return pd.DataFrame()
    output = frame.copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    output["market"] = output["market"].map(_canonical_market_or_unknown)
    return output.loc[
        output["symbol"].eq(str(symbol).strip().upper()) & output["market"].eq(market)
    ].copy(deep=True)


def _trades_frame(result: BacktestResult) -> pd.DataFrame:
    if not result.trades:
        return pd.DataFrame({"訊息": [INSUFFICIENT_DATA]})
    return pd.DataFrame([trade.__dict__ for trade in result.trades])


def _component_chart_frame(component_frame: pd.DataFrame) -> pd.DataFrame:
    """Return numeric component scores for bar chart rendering."""

    if component_frame.empty or "score" not in component_frame.columns:
        return pd.DataFrame()
    chart = component_frame.copy(deep=True)
    chart["score"] = pd.to_numeric(chart["score"], errors="coerce")
    return chart.dropna(subset=["score"])


def _display_stock_research_header(st: Any, symbol: str, prices: pd.DataFrame, result: Any) -> None:
    """Display a compact quote and research summary inspired by analyst dashboards."""

    snapshot = _stock_snapshot(symbol, prices)
    if not snapshot:
        return
    st.markdown(f"### {symbol} 研究總覽")
    _display_metric_cards(
        st,
        [
            ("最新收盤", snapshot["close"]),
            ("單日變動", snapshot["change"]),
            ("成交量", snapshot["volume"]),
            (
                "研究分數",
                _score_value(
                    result.total_score
                    if result.total_score != "unknown"
                    else result.available_score
                ),
            ),
        ],
    )
    st.caption(
        f"資料期間：{snapshot['start_date']} 至 {snapshot['end_date']}；"
        f"評分覆蓋率：{_percent(result.coverage)}。"
    )


def _stock_snapshot(symbol: str, prices: pd.DataFrame) -> dict[str, str]:
    """Return formatted latest quote information for one symbol."""

    data = _filter_symbol(prices, symbol)
    if data.empty:
        return {}
    data = data.sort_values("date").copy(deep=True)
    latest = data.iloc[-1]
    previous = data.iloc[-2] if len(data) >= 2 else None
    close = _to_float(latest.get("close"))
    previous_close = _to_float(previous.get("close")) if previous is not None else None
    if close is None:
        close_text = INSUFFICIENT_DATA
        change_text = INSUFFICIENT_DATA
    else:
        close_text = f"{close:,.2f}"
        if previous_close is None or previous_close == 0.0:
            change_text = INSUFFICIENT_DATA
        else:
            change = close - previous_close
            change_pct = change / previous_close
            change_text = f"{change:+,.2f} ({change_pct:+.2%})"
    volume = _to_float(latest.get("volume"))
    return {
        "close": close_text,
        "change": change_text,
        "volume": f"{volume:,.0f}" if volume is not None else INSUFFICIENT_DATA,
        "start_date": str(data["date"].min()),
        "end_date": str(data["date"].max()),
    }


def _display_entry_reference(st: Any, entry: EntryReference) -> None:
    """Display rule-based entry reference prices with risk disclosure."""

    st.subheader("情境參考區間（研究用，非投資建議）")
    if not entry.is_available:
        st.warning(
            "資料不足，無法產生情境參考區間；" f"缺少：{_format_missing_data(entry.missing_data)}。"
        )
        for note in entry.risk_notes:
            st.caption(note)
        return

    _display_metric_cards(
        st,
        [
            ("區間中樞參考", _number(entry.reference_price)),
            ("觀察區間", _entry_zone_text(entry)),
            ("突破觀察價", _number(entry.breakout_trigger)),
            ("停損參考", _number(entry.stop_loss_reference)),
        ],
    )
    st.caption(
        f"方法：{entry.method}；計算基準日：{entry.as_of_date or '資料最後一列'}。"
        "此價格只用已載入日線資料推估，實際交易需考慮隔日開盤、滑價、手續費與交易稅。"
    )
    with st.expander("情境參考區間計算說明"):
        for note in entry.notes:
            st.write(f"- {note}")
        st.markdown("#### 風險限制")
        for note in entry.risk_notes:
            st.write(f"- {note}")


def _entry_zone_text(entry: EntryReference) -> str:
    if entry.zone_low is None or entry.zone_high is None:
        return "—"
    return f"{_number(entry.zone_low)} ~ {_number(entry.zone_high)}"


def _factor_health_frame(result: Any) -> pd.DataFrame:
    """Build a five-factor health table for the AI analysis page."""

    component_scores = {component.name: component for component in result.components}
    technical = _component_ratio(component_scores, "技術面")
    fundamental = _component_ratio(component_scores, "基本面")
    valuation = _component_ratio(component_scores, "估值面")
    risk = _component_ratio(component_scores, "風險面")
    rows = [
        ("趨勢動能", technical, "由均線、MACD、RSI 與近期報酬率估算。"),
        ("基本體質", fundamental, "由成長性、獲利能力、財務安全與現金流估算。"),
        ("估值風險", valuation, "由 PE、PB、股利殖利率等估值欄位估算。"),
        ("波動風險", risk, "由回撤、波動率、ATR 與回測風險估算。"),
        ("資料完整度", result.coverage * 100.0, "分數越高代表可用資料越完整。"),
    ]
    return pd.DataFrame(
        [
            {"factor": factor, "score": round(score, 2), "note": note}
            for factor, score, note in rows
            if score is not None
        ]
    )


def _component_reason_breakdown(component: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split one score component's reasons into strengths and weaknesses."""

    strengths: list[str] = []
    weaknesses: list[str] = []
    if getattr(component, "missing_data", ()):
        weaknesses.append(f"缺少資料：{_format_missing_data(component.missing_data)}")

    ratio = _component_score_ratio(component)
    for reason in getattr(component, "reasons", ()):
        text = str(reason)
        if _looks_like_strength(text):
            strengths.append(text)
        elif _looks_like_weakness(text):
            weaknesses.append(text)
        elif ratio >= 0.65:
            strengths.append(text)
        else:
            weaknesses.append(text)

    if not strengths:
        strengths.append("目前沒有足夠資料列出明確優點。")
    if not weaknesses:
        weaknesses.append("目前沒有明確缺點，但仍需確認資料來源、期間與成本假設。")
    return tuple(strengths), tuple(weaknesses)


def _component_score_ratio(component: Any) -> float:
    score = getattr(component, "score", "unknown")
    weight = getattr(component, "weight", 0.0)
    if score == "unknown" or not weight:
        return 0.0
    try:
        return float(score) / float(weight)
    except (TypeError, ValueError):
        return 0.0


def _looks_like_strength(text: str) -> bool:
    positive_terms = (
        "高於",
        "偏正向",
        "相對有利",
        "健康",
        "為正",
        "較低",
        "可控",
        "較佳",
        "較健康",
        "未超過",
        "未呈現",
        "資料皆可計算",
    )
    return any(term in text for term in positive_terms)


def _looks_like_weakness(text: str) -> bool:
    negative_terms = (
        "低於",
        "偏弱",
        "需要",
        "尚未",
        "缺少",
        "資料不足",
        "偏高",
        "不佳",
        "無法",
        "未納入",
        "壓力",
        "極端",
        "失控",
        "弱項",
    )
    return any(term in text for term in negative_terms)


def _component_ratio(components: dict[str, Any], name: str) -> float:
    component = components.get(name)
    if component is None or component.score == "unknown" or not component.weight:
        return 0.0
    return float(component.score) / float(component.weight) * 100.0


def _row_count(frame: pd.DataFrame | None) -> str:
    return str(0 if frame is None else len(frame))


def _symbol_count(frame: pd.DataFrame | None) -> str:
    if frame is None or frame.empty or "symbol" not in frame.columns:
        return "0"
    return str(frame["symbol"].astype(str).nunique())


def _trade_count(result: BacktestResult | None) -> str:
    return str(0 if result is None else len(result.trades))


def _latest_value(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return INSUFFICIENT_DATA
    value = frame[column].iloc[-1]
    return _number(value)


def _score_value(value: Any) -> str:
    if value == "unknown" or value is None or pd.isna(value):
        return "—"
    return f"{float(value):.2f}"


def _format_missing_data(items: Sequence[str]) -> str:
    labels = {
        "technical_indicators": "技術指標",
        "fundamental_scores": "基本面評分",
        "valuation_score": "估值分數",
        "price_data": "股價資料",
        "at_least_20_price_rows": "至少 20 筆股價資料",
    }
    return "、".join(labels.get(str(item), str(item)) for item in items)


def _percent(value: Any) -> str:
    if value is None or pd.isna(value):
        return INSUFFICIENT_DATA
    return f"{float(value) * 100:.2f}%"


def _number(value: Any) -> str:
    if value is None or pd.isna(value):
        return INSUFFICIENT_DATA
    if value == float("inf"):
        return "∞"
    return f"{float(value):,.2f}"


def _to_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
