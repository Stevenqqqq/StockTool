from __future__ import annotations


from pathlib import Path
from datetime import datetime
import inspect
from types import SimpleNamespace

import pandas as pd
from streamlit.testing.v1 import AppTest

import stock_tool.dashboard.app as dashboard_app
from stock_tool.application.daily_brief import (
    ActionRequired,
    DailyAction,
    DailyBrief,
    DailyBriefItem,
    PortfolioPulse,
    ResearchContinuation,
    WatchlistPulse,
)
from stock_tool.application.daily_brief import DailyRefreshRecord, DailyRefreshResult
from stock_tool.application.daily_research_loop import DailyResearchLoopService
from stock_tool.application.macro_snapshot import MacroSignal, MacroSnapshot
from stock_tool.application.prediction_lab import PredictionLabSummary
from stock_tool.application.results import DataHydrationRequest
from stock_tool.data.contracts import (
    DataSourceMetadata,
    DataSourceType,
    provider_result_from_price_frame,
)
from stock_tool.data.policies import ProviderHealthTracker
from stock_tool.domain.models import Symbol
from stock_tool.dashboard.pages import home as home_page
from stock_tool.dashboard.pages.home import HomeContext
from stock_tool.dashboard.state import DashboardStatus
from stock_tool.dashboard.state import SearchRequest


def test_home_important_revisions_excludes_unchanged_refetch(tmp_path) -> None:
    # Provenance-only refetches must not create visible revision cards.
    from stock_tool.application.macro_snapshot import (
        MacroObservationPoint,
        MacroRevisionLedgerStore,
    )

    path = tmp_path / "revision-ledger.json"
    store = MacroRevisionLedgerStore(path)
    first = MacroObservationPoint("CPI", "2026-07-01", 1.0, "a" * 64, "2026-08-10T00:00:00+00:00")
    same = MacroObservationPoint("CPI", "2026-07-01", 1.0, "b" * 64, "2026-08-11T00:00:00+00:00")
    store.update((first,))
    store.update((same,))
    assert store.important_revisions() == ()


def _app_path() -> Path:
    return Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "app.py"


def test_first_use_daily_home_has_search_examples_and_no_raw_table(tmp_path, monkeypatch) -> None:
    """First use should offer a concrete start without rendering empty portfolio tables."""

    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_file(str(_app_path())).run(timeout=20)

    assert not app.exception
    assert any("今天先看這些" in block.value for block in app.markdown)
    assert any(heading.value == "每日研究收件匣" for heading in app.subheader)
    assert {button.label for button in app.button}.issuperset(
        {"研究 2330", "研究 6488", "研究 AAPL"}
    )
    assert not app.dataframe


def test_daily_home_prediction_lab_cards_keep_status_and_limitations_visible(monkeypatch) -> None:
    """The visual lab card exposes useful counts without implying a forecast."""

    monkeypatch.setattr(home_page, "render_global_search", lambda *_args, **_kwargs: None)
    summary = PredictionLabSummary(
        status="ready",
        message="今日樣本已登錄",
        registered_today=2,
        bucket_counts={"top": 1, "middle": 1, "bottom": 1},
        outcome_counts={
            "5": {"pending": 1, "eligible": 0, "evaluated": 1, "unavailable": 0},
            "20": {"pending": 0, "eligible": 1, "evaluated": 0, "unavailable": 0},
        },
        prediction_count=6,
        outcome_count=1,
        last_trading_date="2026-08-21",
        warnings=("仍有樣本等待到期。",),
        limitations=("資料僅供研究驗證。",),
    )
    context = HomeContext(
        status=DashboardStatus.READY,
        active_symbol=None,
        recent_searches=(),
        watchlist_count=1,
        portfolio_count=1,
        source_label="fixture",
        updated_at="2026-08-21",
        prediction_lab=summary,
    )
    recorder = _HomeRecorder()

    assert home_page.render_home(recorder, context) is None
    assert any("今天先看這些" in message for message in recorder.messages)
    assert any("預測評估實驗室（實驗）" in message for message in recorder.messages)
    assert any("今日登錄" in message and ">2<" in message for message in recorder.messages)
    assert any("等待到期" in message and ">1<" in message for message in recorder.messages)
    assert "仍有樣本等待到期。" in recorder.messages
    assert "資料僅供研究驗證。" in recorder.messages


def test_daily_home_prediction_lab_renders_verified_settlement_metrics(monkeypatch) -> None:
    monkeypatch.setattr(home_page, "render_global_search", lambda *_args, **_kwargs: None)
    summary = PredictionLabSummary(
        status="ready",
        message="樣本累積中",
        registered_today=2,
        bucket_counts={"top": 1, "middle": 1, "bottom": 0},
        outcome_counts={
            "5": {"pending": 0, "eligible": 0, "evaluated": 1, "unavailable": 0},
            "20": {"pending": 0, "eligible": 0, "evaluated": 1, "unavailable": 0},
        },
        prediction_count=2,
        outcome_count=2,
        last_trading_date="2026-08-21",
        evaluated_count=2,
        coverage_by_horizon={"5": 1.0, "20": 1.0},
        median_net_return=0.0123,
        median_net_excess_return=0.0045,
        top_bottom_spread=0.01,
        last_evaluated_at="2026-08-22T00:00:00+00:00",
    )
    context = HomeContext(
        status=DashboardStatus.READY,
        active_symbol=None,
        recent_searches=(),
        watchlist_count=0,
        portfolio_count=0,
        source_label="fixture",
        updated_at="2026-08-21",
        prediction_lab=summary,
    )
    recorder = _HomeRecorder()

    home_page.render_home(recorder, context)

    assert any("可信結算摘要" in message for message in recorder.messages)
    assert any("5 日覆蓋率" in message and "100%" in message for message in recorder.messages)
    assert any("中位淨報酬" in message and "+1.23%" in message for message in recorder.messages)
    assert not any("勝率" in message or "目標價" in message for message in recorder.messages)


def test_daily_home_prediction_lab_exposes_explicit_evaluation_action(monkeypatch) -> None:
    monkeypatch.setattr(home_page, "render_global_search", lambda *_args, **_kwargs: None)
    summary = PredictionLabSummary(
        status="ready",
        message="樣本累積中",
        registered_today=1,
        bucket_counts={"top": 1, "middle": 0, "bottom": 0},
        outcome_counts={"5": {"pending": 1}, "20": {"pending": 0}},
        prediction_count=1,
        outcome_count=0,
        last_trading_date="2026-08-21",
    )
    context = HomeContext(
        status=DashboardStatus.READY,
        active_symbol=None,
        recent_searches=(),
        watchlist_count=0,
        portfolio_count=0,
        source_label="fixture",
        updated_at="2026-08-21",
        prediction_lab=summary,
        prediction_lab_evaluation_available=True,
    )
    recorder = _HomeRecorder("home_evaluate_prediction_outcomes")

    action = home_page.render_home(recorder, context)

    assert action is not None
    assert action.kind == "prediction_outcome_evaluation"


def test_runtime_cached_outcome_provider_is_read_only_and_market_qualified() -> None:
    provider = dashboard_app._RuntimeCachedOutcomeProvider(
        (
            {
                "symbol": "2330",
                "market": "TWSE",
                "date": "2026-08-13",
                "close": 100.0,
                "provider": "fixture-cache",
            },
            {
                "symbol": "2330",
                "market": "TWSE",
                "date": "2026-08-20",
                "close": 105.0,
                "provider": "fixture-cache",
            },
        )
    )

    calendar = provider.calendar("TWSE")
    # The provider must use the bundled, hash-bound market calendar rather
    # than inferring trading days from whichever security rows are cached.
    assert calendar.market == "TWSE"
    assert calendar.source_hash and len(calendar.source_hash) == 64
    assert calendar.identity.startswith("calendar-")
    assert "2026-08-13" in calendar.dates
    assert "2026-08-20" in calendar.dates
    evidence = provider.price("TWSE:2330", "2026-08-20")
    assert evidence is not None and evidence.value == 105.0
    assert provider.price("TPEX:2330", "2026-08-20") is None
    # No benchmark row was supplied, so the strict provider fails closed.
    assert provider.benchmark("TWSE:TAIEX", "2026-08-20") is None


def test_daily_home_prediction_lab_empty_state_is_explicit(monkeypatch) -> None:
    """An unavailable lab is honest and does not render synthetic counts."""

    monkeypatch.setattr(home_page, "render_global_search", lambda *_args, **_kwargs: None)
    context = HomeContext(
        status=DashboardStatus.PARTIAL,
        active_symbol=None,
        recent_searches=(),
        watchlist_count=0,
        portfolio_count=0,
        source_label=None,
        updated_at=None,
        prediction_lab=PredictionLabSummary(
            status="unavailable",
            message="目前沒有可驗證樣本",
            registered_today=0,
            bucket_counts={},
            outcome_counts={},
            prediction_count=0,
            outcome_count=0,
            last_trading_date=None,
        ),
    )
    recorder = _HomeRecorder()

    assert home_page.render_home(recorder, context) is None
    assert any("尚無可驗證樣本" in message for message in recorder.messages)
    assert not any("累積樣本:" in message for message in recorder.messages)


def test_daily_home_run_reasons_are_short_traditional_chinese_guidance(monkeypatch) -> None:
    """Provider diagnostics stay in evidence while the home page stays actionable."""

    monkeypatch.setattr(home_page, "render_global_search", lambda *_args, **_kwargs: None)
    context = HomeContext(
        status=DashboardStatus.PARTIAL,
        active_symbol=None,
        recent_searches=(),
        watchlist_count=0,
        portfolio_count=0,
        source_label=None,
        updated_at=None,
        daily_research_run=SimpleNamespace(
            status="partial",
            completed_at="2026-08-24T10:00:00+00:00",
            stages=(
                SimpleNamespace(
                    name="market_refresh",
                    status="failure",
                    reason="TWSE official source unavailable; timeout=15s",
                ),
                SimpleNamespace(
                    name="notification",
                    status="unavailable",
                    reason="WindowsRuntime provider detail",
                ),
            ),
        ),
    )
    recorder = _HomeRecorder()

    home_page.render_home(recorder, context)

    assert any("部分市場資料暫時無法更新" in message for message in recorder.messages)
    assert any("研究成果已保留" in message for message in recorder.messages)
    assert not any("official source unavailable" in message for message in recorder.messages)
    assert not any("WindowsRuntime" in message for message in recorder.messages)


def test_home_first_screen_and_prediction_lab_do_not_use_fixed_metric_columns() -> None:
    overview_source = inspect.getsource(home_page._render_home_overview_header)
    lab_source = inspect.getsource(home_page._render_prediction_lab)

    assert "st.columns" not in overview_source
    assert "st.columns" not in lab_source
    assert "st.metric" not in overview_source
    assert "st.metric" not in lab_source


def test_home_primary_action_and_widget_keys_remain_stable(monkeypatch) -> None:
    search_calls: list[dict[str, object]] = []

    def record_search(_st, **kwargs: object):
        search_calls.append(kwargs)
        return None

    monkeypatch.setattr(home_page, "render_global_search", record_search)
    context = HomeContext(
        status=DashboardStatus.LOADING,
        active_symbol="2330",
        recent_searches=(),
        watchlist_count=2,
        portfolio_count=1,
        source_label="cache",
        updated_at="2026-08-21",
    )
    recorder = _HomeRecorder("home_refresh_today")

    action = home_page.render_home(recorder, context)

    assert action is not None and action.kind == "refresh"
    assert search_calls == [
        {
            "key_prefix": "home",
            "disabled": True,
            "default_symbol": "2330",
            "submit_label": "研究一家公司",
        }
    ]
    assert "更新今日資料" in recorder.button_labels


def test_home_one_click_research_action_is_explicit_and_primary(monkeypatch) -> None:
    monkeypatch.setattr(home_page, "render_global_search", lambda *_args, **_kwargs: None)
    context = HomeContext(
        status=DashboardStatus.READY,
        active_symbol=None,
        recent_searches=(),
        watchlist_count=1,
        portfolio_count=1,
        source_label="cache",
        updated_at="2026-08-23",
    )
    recorder = _HomeRecorder("home_run_daily_research")

    action = home_page.render_home(recorder, context)

    assert action is not None and action.kind == "daily_research_run"
    assert "執行今日研究" in recorder.button_labels


def test_home_partial_and_error_states_stay_visible(monkeypatch) -> None:
    monkeypatch.setattr(home_page, "render_global_search", lambda *_args, **_kwargs: None)
    for status, expected in (
        (DashboardStatus.PARTIAL, "部分資料可用"),
        (DashboardStatus.ERROR, "資料更新未完成"),
    ):
        recorder = _HomeRecorder()
        context = HomeContext(
            status=status,
            active_symbol=None,
            recent_searches=(),
            watchlist_count=0,
            portfolio_count=0,
            source_label=None,
            updated_at=None,
        )

        home_page.render_home(recorder, context)

        assert any(expected in message for message in recorder.messages)


def test_daily_evidence_brief_has_explicit_action_and_isolated_persistence(
    tmp_path, monkeypatch
) -> None:
    """The Home action is explicit and writes only the isolated runtime sidecar."""

    runtime = tmp_path / "runtime"
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    app = AppTest.from_file(str(_app_path())).run(timeout=20)
    assert not app.exception
    app.button(key="home_generate_daily_evidence_brief").click().run(timeout=30)
    assert not app.exception
    assert (runtime / "data" / "daily_research" / "latest_evidence_chain_brief.json").is_file()
    assert (runtime / "data" / "daily_research" / "latest_evidence_chain_brief.html").is_file()


def test_returning_daily_home_uses_cards_not_raw_frames(tmp_path, monkeypatch) -> None:
    """Existing portfolio/watchlist data should produce the returning-user home sections."""

    runtime = tmp_path / "runtime"
    data_dir = runtime / "data"
    data_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "symbol": ["2330"],
            "market": ["TWSE"],
            "quantity": [1.0],
            "average_cost": [500.0],
            "currency": ["TWD"],
            "note": [""],
        }
    ).to_csv(data_dir / "portfolio.csv", index=False, encoding="utf-8")
    pd.DataFrame({"symbol": ["AAPL"], "market": ["US"], "note": [""]}).to_csv(
        data_dir / "watchlist.csv", index=False, encoding="utf-8"
    )
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))

    app = AppTest.from_file(str(_app_path())).run(timeout=20)

    assert not app.exception
    headings = {heading.value for heading in app.subheader}
    assert {"今日關注", "持倉快照", "自選股動態", "繼續研究", "待處理事項"}.issubset(headings)
    assert not app.dataframe


def test_daily_refresh_uses_explicit_identities_without_mutating_user_frames() -> None:
    """Batch selection must be market-qualified and must not write portfolio/watchlist inputs."""

    portfolio = pd.DataFrame(
        {"symbol": ["2330", "2330"], "market": ["TWSE", "TWSE"], "quantity": [1, 1]}
    )
    watchlist = pd.DataFrame(
        {"symbol": ["2330", "AAPL"], "market": ["TWSE", "US"], "note": ["", ""]}
    )
    before_portfolio = portfolio.copy(deep=True)
    before_watchlist = watchlist.copy(deep=True)

    identities = dashboard_app._daily_refresh_identities(portfolio, watchlist)

    assert [(item.code, item.market.value) for item in identities] == [
        ("2330", "TWSE"),
        ("AAPL", "US"),
    ]
    pd.testing.assert_frame_equal(portfolio, before_portfolio)
    pd.testing.assert_frame_equal(watchlist, before_watchlist)


def test_daily_refresh_uses_portfolio_as_effective_watchlist_when_manual_file_is_empty() -> None:
    portfolio = pd.DataFrame(
        {
            "symbol": ["2330", "6488", "AAPL", "MU", "UNKNOWN"],
            "market": ["TWSE", "TPEX", "US", "US", "UNKNOWN"],
            "quantity": [1, 1, 1, 1, 1],
        }
    )
    manual_watchlist = pd.DataFrame(columns=["symbol", "market", "note"])

    identities = dashboard_app._daily_refresh_identities(portfolio, manual_watchlist)

    assert [(item.code, item.market.value) for item in identities] == [
        ("6488", "TPEX"),
        ("2330", "TWSE"),
        ("AAPL", "US"),
        ("MU", "US"),
    ]


def test_daily_refresh_partial_failure_keeps_success_and_uses_safe_message() -> None:
    """The shell service result retains successful symbols when an independent update fails."""

    twse = Symbol.parse("2330", market="TWSE")
    us = Symbol.parse("AAPL", market="US")

    def hydrate(symbol: Symbol) -> DailyRefreshRecord:
        if symbol == us:
            raise RuntimeError("token=private-value")
        return DailyRefreshRecord(symbol=symbol, status="success", provider="fixture")

    result = dashboard_app.DailyRefreshService().refresh(symbols=(twse, us), hydrate=hydrate)

    assert isinstance(result, DailyRefreshResult)
    assert result.success_count == 1
    assert result.failure_count == 1
    assert "private-value" not in (result.records[1].reason or "")


def test_daily_hydration_provider_uses_existing_contract_and_health_tracker(monkeypatch) -> None:
    """The explicit daily refresh adapter must retain the established provider boundary."""

    request = DataHydrationRequest(
        symbol=Symbol.parse("2330", market="TWSE"),
        start_date="2024-01-01",
        end_date="2024-01-03",
        interval="1d",
    )
    calls: dict[str, object] = {}

    def fake_fetch(symbol: str, **kwargs: object):
        calls["symbol"] = symbol
        calls.update(kwargs)
        return provider_result_from_price_frame(
            pd.DataFrame(
                {
                    "date": ["2024-01-02"],
                    "symbol": ["2330"],
                    "open": [100.0],
                    "high": [101.0],
                    "low": [99.0],
                    "close": [100.0],
                    "volume": [1000.0],
                    "adjusted_close": [100.0],
                }
            ),
            metadata=DataSourceMetadata(
                provider="fixture-provider",
                source_type=DataSourceType.CACHE,
                requested_symbol=request.symbol,
                resolved_symbol=request.symbol,
                provider_symbol="2330.TW",
                request_start=request.start_date,
                request_end=request.end_date,
                interval="1d",
                cache_path="fixture-cache.csv",
                last_data_date="2024-01-02",
                cache_state="hit",
            ),
        )

    tracker = ProviderHealthTracker()
    monkeypatch.setattr(dashboard_app, "fetch_prices_result", fake_fetch)

    result = dashboard_app._DailyHydrationProvider(request, tracker).load_price_result()

    assert result.metadata.source_type is DataSourceType.CACHE
    assert result.metadata.provider_symbol == "2330.TW"
    assert calls["symbol"] == "2330"
    assert calls["health_tracker"] is tracker
    assert calls["contracts_enabled"] is True


def test_daily_home_dynamic_text_does_not_use_unsafe_html() -> None:
    """Home card text must stay on Streamlit's safe rendering path."""

    source = (
        Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "pages" / "home.py"
    ).read_text(encoding="utf-8")

    assert "unsafe_allow_html" not in source


class _HomeRecorder:
    """Minimal Streamlit double for deterministic card-action tests."""

    def __init__(self, clicked_key: str | None = None) -> None:
        self.clicked_key = clicked_key
        self.messages: list[str] = []
        self.button_labels: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def container(self, **_: object):
        return self

    def columns(self, values: int | tuple[int, ...]):
        count = values if isinstance(values, int) else len(values)
        return [self] * count

    def title(self, value: str) -> None:
        self.messages.append(value)

    def subheader(self, value: str) -> None:
        self.messages.append(value)

    def caption(self, value: str) -> None:
        self.messages.append(value)

    def write(self, value: str) -> None:
        self.messages.append(value)

    def markdown(self, value: str, **_: object) -> None:
        self.messages.append(value)

    def info(self, value: str) -> None:
        self.messages.append(value)

    def success(self, value: str) -> None:
        self.messages.append(value)

    def warning(self, value: str) -> None:
        self.messages.append(value)

    def metric(self, label: str, value: str) -> None:
        self.messages.append(f"{label}:{value}")

    def button(self, _label: str, *, key: str, **_: object) -> bool:
        self.button_labels.append(_label)
        return key == self.clicked_key


def _item(action: DailyAction = "open_research") -> DailyBriefItem:
    return DailyBriefItem(
        code="daily_move",
        severity="attention",
        title="2330 單日變動明顯",
        detail="相較前一個可用交易日上漲。",
        evidence="前一交易日收盤 100.00；最新收盤 110.00；變動 +10.00%。",
        as_of_date="2024-01-10",
        action=action,
        symbol=Symbol.parse("2330", market="TWSE"),
    )


def test_daily_home_cards_return_explicit_actions_without_raw_html(monkeypatch) -> None:
    """Card clicks route to research, holdings, and settings through typed actions."""

    monkeypatch.setattr(home_page, "render_global_search", lambda *_args, **_kwargs: None)
    continuation = ResearchContinuation(
        symbol=Symbol.parse("AAPL", market="US"),
        researched_at="2024-01-10T00:00:00+00:00",
        data_as_of_date="2024-01-10",
        coverage=0.8,
    )
    brief = DailyBrief(
        data_as_of_date="2024-01-10",
        attention_items=(_item(),),
        portfolio=PortfolioPulse(1, 1, 1.0, 1.0, 1, _item(), None),
        watchlist=WatchlistPulse(1, _item(), 0, 0, None),
        continuations=(continuation,),
        action_required=(
            ActionRequired(
                field="portfolio_valuation",
                title="持倉估值資料不足",
                detail="缺少匯率。",
                action="view_holdings",
            ),
            ActionRequired(
                field="portfolio_fx",
                title="需要設定",
                detail="缺少資料。",
                action="complete_data",
            ),
        ),
        first_use=False,
    )
    context = HomeContext(
        status=DashboardStatus.READY,
        active_symbol=None,
        recent_searches=(),
        watchlist_count=1,
        portfolio_count=1,
        source_label="fixture",
        updated_at="2024-01-10",
        daily_brief=brief,
    )

    attention = home_page.render_home(_HomeRecorder("home_attention_0_daily_move"), context)
    assert attention is not None and attention.kind == "search"
    holdings = home_page._render_action_required(
        _HomeRecorder("home_required_0_portfolio_valuation"), brief.action_required
    )
    assert holdings is not None and holdings.workspace == "holdings"
    settings = home_page._render_action_required(
        _HomeRecorder("home_required_1_portfolio_fx"), brief.action_required
    )
    assert settings is not None and settings.workspace == "settings"
    continuation_action = home_page._render_continuations(
        _HomeRecorder("home_continue_0"), brief.continuations
    )
    assert continuation_action is not None and continuation_action.preparation is not None


def test_daily_loop_suppresses_duplicate_risk_card_and_holdings_cta(monkeypatch) -> None:
    """One represented risk identity has one Daily Loop card and one next-step CTA."""

    monkeypatch.setattr(home_page, "render_global_search", lambda *_args, **_kwargs: None)
    risk_item = DailyBriefItem(
        code="risk_alert",
        severity="warning",
        title="持倉風險警示",
        detail="目前有集中度風險。",
        evidence="風險警示數 1。",
        as_of_date="2026-07-18",
        action="view_holdings",
        field="risk_alerts",
    )
    current = DailyBrief(
        data_as_of_date="2026-07-18",
        attention_items=(risk_item,),
        portfolio=PortfolioPulse(1, 1, 1.0, 0.8, 1, risk_item, None),
        watchlist=WatchlistPulse(0, None, 0, 0, None),
        continuations=(),
        action_required=(
            ActionRequired(
                field="risk_alerts",
                title="持倉風險警示",
                detail="目前有集中度風險。",
                action="view_holdings",
            ),
        ),
        first_use=False,
    )
    baseline = DailyBrief(
        data_as_of_date="2026-07-17",
        attention_items=(),
        portfolio=PortfolioPulse(1, 1, 1.0, 0.8, 0, None, None),
        watchlist=WatchlistPulse(0, None, 0, 0, None),
        continuations=(),
        action_required=(),
        first_use=False,
    )
    service = DailyResearchLoopService()
    previous = service.complete_success(
        brief=baseline,
        previous_snapshot=None,
        successful_at="2026-07-18T08:00:00+00:00",
    ).snapshot
    assert previous is not None
    loop = service.complete_success(
        brief=current,
        previous_snapshot=previous,
        successful_at="2026-07-18T09:00:00+00:00",
    )
    context = HomeContext(
        status=DashboardStatus.READY,
        active_symbol=None,
        recent_searches=(),
        watchlist_count=0,
        portfolio_count=1,
        source_label="fixture",
        updated_at="2026-07-18",
        daily_brief=current,
        daily_research_loop=loop,
    )
    recorder = _HomeRecorder()

    assert home_page.render_home(recorder, context) is None
    assert recorder.button_labels.count("查看持倉") == 1
    assert sum("持倉風險警示" in message for message in recorder.messages) == 1


def test_daily_home_legacy_and_first_use_fallbacks_remain_actionable(monkeypatch) -> None:
    """Fallback states retain safe counts and examples without creating empty data grids."""

    monkeypatch.setattr(home_page, "render_global_search", lambda *_args, **_kwargs: None)
    legacy = HomeContext(
        status=DashboardStatus.READY,
        active_symbol="2330",
        recent_searches=(),
        watchlist_count=1,
        portfolio_count=2,
        source_label="local_file",
        updated_at="2024-01-10",
        summary_warnings=("資料來源已更新。",),
        daily_brief=None,
    )
    recorder = _HomeRecorder()
    assert home_page.render_home(recorder, legacy) is None
    assert "研究摘要" in recorder.messages
    assert "持股筆數:2" in recorder.messages

    first_use = HomeContext(
        status=DashboardStatus.FIRST_USE,
        active_symbol=None,
        recent_searches=(SearchRequest(symbol="2330", market="TWSE"),),
        watchlist_count=0,
        portfolio_count=0,
        source_label=None,
        updated_at=None,
        daily_brief=DailyBrief(
            data_as_of_date=None,
            attention_items=(),
            portfolio=PortfolioPulse(0, 0, None, None, 0, None, "尚未建立持股。"),
            watchlist=WatchlistPulse(0, None, 0, 0, "尚未建立自選股。"),
            continuations=(),
            action_required=(),
            first_use=True,
        ),
    )
    recorder = _HomeRecorder()
    assert home_page.render_home(recorder, first_use) is None
    assert "從第一份研究開始" in recorder.messages


def test_daily_home_renders_macro_context_and_explicit_refresh_action(monkeypatch) -> None:
    monkeypatch.setattr(home_page, "render_global_search", lambda *_args, **_kwargs: None)
    snapshot = MacroSnapshot.create(
        status="unavailable",
        source="FRED official",
        observations=(),
        references=(),
        warnings=("目前無可驗證的官方總經資料",),
        generated_at=datetime.fromisoformat("2026-08-10T10:00:00+00:00"),
    )
    context = HomeContext(
        status=DashboardStatus.FIRST_USE,
        active_symbol=None,
        recent_searches=(),
        watchlist_count=0,
        portfolio_count=0,
        source_label=None,
        updated_at=None,
        daily_brief=None,
        macro_snapshot=snapshot,
        macro_signals=(
            MacroSignal(
                signal_id="cpi-1",
                series_id="CPI",
                title="消費者物價指數",
                status="unavailable",
                current_value=None,
                previous_value=None,
                delta=None,
                unit=None,
                rule_version="macro-rules-v1",
                reference_ids=(),
                next_condition="下一期官方資料發布後重新確認",
                threshold_distance=None,
                freshness="unavailable",
                limitations=("目前無可驗證資料",),
                observation_period="2026-07-01",
                observed_date="2026-07-01",
                fetched_at="2026-08-10T10:00:00+00:00",
            ),
        ),
        macro_links=(
            {
                "identity": "TWSE:2330",
                "sector": "半導體",
                "rule_version": "macro-exposure-v1",
                "macro_relation_message": "尚無可驗證總經關聯",
            },
        ),
    )
    recorder = _HomeRecorder("home_refresh_macro")
    action = home_page.render_home(recorder, context)
    assert action is not None and action.kind == "macro_refresh"
    assert "今日總經背景" in recorder.messages
    assert "更新總經資料" in recorder.button_labels
    assert any("資料期間：2026-07-01" in message for message in recorder.messages)
    assert any("尚無可驗證總經關聯" in message for message in recorder.messages)
