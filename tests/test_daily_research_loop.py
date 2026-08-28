from __future__ import annotations

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

import stock_tool.dashboard.app as dashboard_app
from stock_tool.application.daily_brief import (
    ActionRequired,
    DailyBrief,
    DailyBriefItem,
    PortfolioPulse,
    WatchlistPulse,
)
from stock_tool.application.daily_research_loop import (
    DailyResearchLoopService,
    DailyResearchSnapshotLoad,
    DailyResearchSnapshotStore,
    DailyResearchSource,
)
from stock_tool.domain import Market, Symbol
from stock_tool.dashboard.pages import home as home_page
from stock_tool.runtime_paths import RuntimePaths


def _brief(
    *,
    attention: tuple[DailyBriefItem, ...] = (),
    actions: tuple[ActionRequired, ...] = (),
    price_coverage: float | None = 1.0,
    max_position_weight: float | None = 0.62,
    risk_alert_count: int = 1,
) -> DailyBrief:
    return DailyBrief(
        data_as_of_date="2026-07-17",
        attention_items=attention,
        portfolio=PortfolioPulse(
            position_count=2,
            priced_position_count=2,
            price_coverage=price_coverage,
            max_position_weight=max_position_weight,
            risk_alert_count=risk_alert_count,
            priority_issue=None,
        ),
        watchlist=WatchlistPulse(
            item_count=0,
            largest_move=None,
            stale_count=0,
            unresearched_count=0,
        ),
        continuations=(),
        action_required=actions,
        first_use=False,
    )


def _source(symbol: Symbol) -> dict[str, DailyResearchSource]:
    return {
        symbol.canonical: DailyResearchSource(
            provider="yfinance",
            source_type="online",
            provider_symbol=symbol.code,
            last_data_date="2026-07-17",
            checked_at="2026-07-17T08:30:00+00:00",
        )
    }


def test_first_successful_update_creates_baseline_without_fake_change() -> None:
    symbol = Symbol.parse("2330", market=Market.TWSE)
    brief = _brief(
        attention=(
            DailyBriefItem(
                code="price_move",
                severity="warning",
                title="價格波動需要研究",
                detail="單日變動高於檢查門檻。",
                evidence="收盤價 100，日變動 7%。",
                as_of_date="2026-07-17",
                action="open_research",
                symbol=symbol,
                field="price_change",
            ),
        )
    )

    result = DailyResearchLoopService().complete_success(
        brief=brief,
        previous_snapshot=None,
        successful_at="2026-07-17T08:30:00+00:00",
        sources=_source(symbol),
    )

    assert result.status == "baseline_created"
    assert result.priority_events == ()
    assert result.snapshot is not None


def test_identical_successful_updates_have_no_false_positive() -> None:
    symbol = Symbol.parse("2330", market=Market.TWSE)
    brief = _brief()
    service = DailyResearchLoopService()
    baseline = service.complete_success(
        brief=brief,
        previous_snapshot=None,
        successful_at="2026-07-17T08:30:00+00:00",
        sources=_source(symbol),
    ).snapshot

    assert baseline is not None
    result = service.complete_success(
        brief=brief,
        previous_snapshot=baseline,
        successful_at="2026-07-17T09:30:00+00:00",
        sources=_source(symbol),
    )

    assert result.status == "no_change"
    assert result.priority_events == ()


def test_changed_canonical_risk_metric_keeps_previous_value_and_snapshot_time() -> None:
    """A changed event must compare the prior value instead of looking newly absent."""

    service = DailyResearchLoopService()
    baseline = service.complete_success(
        brief=_brief(risk_alert_count=1),
        previous_snapshot=None,
        successful_at="2026-07-18T08:00:00+00:00",
    ).snapshot
    assert baseline is not None

    result = service.complete_success(
        brief=_brief(risk_alert_count=2),
        previous_snapshot=baseline,
        successful_at="2026-07-18T09:00:00+00:00",
    )

    event = next(
        item for item in result.priority_events if item.code == "portfolio_risk_alert_count"
    )
    assert event.category == "changed"
    assert event.current_value == "2"
    assert event.baseline_value == "1"
    assert event.baseline_as_of == "2026-07-18T08:00:00+00:00"


def test_only_first_seen_event_uses_absent_previous_baseline() -> None:
    """Only an identity absent from the successful snapshot may use the absent marker."""

    symbol = Symbol.parse("2330", market=Market.TWSE)
    service = DailyResearchLoopService()
    baseline = service.complete_success(
        brief=_brief(risk_alert_count=0),
        previous_snapshot=None,
        successful_at="2026-07-18T08:00:00+00:00",
        sources=_source(symbol),
    ).snapshot
    assert baseline is not None

    result = service.complete_success(
        brief=_brief(
            risk_alert_count=0,
            attention=(
                DailyBriefItem(
                    code="daily_move",
                    severity="attention",
                    title="2330 單日變動明顯",
                    detail="相較前一個可用交易日上漲。",
                    evidence="前一交易日收盤 100.00；最新收盤 110.00；變動 +10.00%。",
                    as_of_date="2026-07-18",
                    action="open_research",
                    symbol=symbol,
                    field="price_change",
                ),
            ),
        ),
        previous_snapshot=baseline,
        successful_at="2026-07-18T09:00:00+00:00",
        sources=_source(symbol),
    )

    event = next(item for item in result.priority_events if item.code == "daily_move")
    assert event.category == "new_change"
    assert event.baseline_value == "上次成功檢查未出現"


def test_resolved_event_is_a_real_change_with_previous_evidence() -> None:
    """A disappearing successful-baseline event must not be downgraded to no change."""

    symbol = Symbol.parse("2330", market=Market.TWSE)
    item = DailyBriefItem(
        code="risk_alert",
        severity="warning",
        title="持股集中度偏高",
        detail="最大單一持股比重超出研究門檻。",
        evidence="最大比重 62%。",
        as_of_date="2026-07-18",
        action="view_holdings",
        symbol=symbol,
        field="portfolio_concentration",
    )
    service = DailyResearchLoopService()
    baseline = service.complete_success(
        brief=_brief(attention=(item,), risk_alert_count=0),
        previous_snapshot=None,
        successful_at="2026-07-18T08:00:00+00:00",
        sources=_source(symbol),
    ).snapshot
    assert baseline is not None

    result = service.complete_success(
        brief=_brief(risk_alert_count=0),
        previous_snapshot=baseline,
        successful_at="2026-07-18T09:00:00+00:00",
        sources=_source(symbol),
    )

    event = next(item for item in result.priority_events if item.code == "risk_alert")
    assert result.status == "updated"
    assert event.category == "resolved"
    assert event.current_value == "已不再出現／已解除"
    assert event.baseline_value == "最大比重 62%。"
    assert event.baseline_as_of == "2026-07-18T08:00:00+00:00"


def test_priority_repair_is_not_rendered_again_in_repair_group() -> None:
    """A repair promoted into priority may have one card and one CTA only."""

    symbol = Symbol.parse("2330", market=Market.TWSE)
    service = DailyResearchLoopService()
    baseline = service.complete_success(
        brief=_brief(),
        previous_snapshot=None,
        successful_at="2026-07-18T08:00:00+00:00",
        sources=_source(symbol),
    ).snapshot
    assert baseline is not None

    result = service.complete_success(
        brief=_brief(
            actions=(
                ActionRequired(
                    field="fundamentals",
                    title="補齊基本面資料",
                    detail="尚無可用基本面。",
                    action="complete_data",
                    symbol=symbol,
                ),
            )
        ),
        previous_snapshot=baseline,
        successful_at="2026-07-18T09:00:00+00:00",
        sources=_source(symbol),
    )

    priority_keys = {item.display_key for item in result.priority_events}
    repair_keys = {item.display_key for item in result.repair_events}
    assert priority_keys.isdisjoint(repair_keys)


def test_canonical_price_coverage_change_uses_structured_values() -> None:
    """Portfolio coverage is compared from DailyBrief fields, never parsed from UI text."""

    service = DailyResearchLoopService()
    baseline = service.complete_success(
        brief=_brief(price_coverage=0.5, risk_alert_count=0),
        previous_snapshot=None,
        successful_at="2026-07-18T08:00:00+00:00",
    ).snapshot
    assert baseline is not None

    result = service.complete_success(
        brief=_brief(price_coverage=1.0, risk_alert_count=0),
        previous_snapshot=baseline,
        successful_at="2026-07-18T09:00:00+00:00",
    )

    event = next(item for item in result.priority_events if item.code == "portfolio_price_coverage")
    assert event.category == "changed"
    assert event.baseline_value == "50.0%"
    assert event.current_value == "100.0%"


def test_legacy_snapshot_without_baseline_as_of_remains_readable() -> None:
    """Existing Sprint 10.3 sidecars remain a safe comparison baseline."""

    snapshot = (
        DailyResearchLoopService()
        .complete_success(
            brief=_brief(),
            previous_snapshot=None,
            successful_at="2026-07-18T08:00:00+00:00",
        )
        .snapshot
    )
    assert snapshot is not None
    payload = snapshot.to_dict()
    for event in payload["events"]:
        assert isinstance(event, dict)
        event.pop("baseline_as_of", None)

    restored = type(snapshot).from_dict(payload)

    assert restored.successful_at == snapshot.successful_at
    assert all(event.baseline_as_of is None for event in restored.events)


def test_market_qualified_identities_do_not_collide() -> None:
    twse = Symbol.parse("MU", market=Market.TWSE)
    us = Symbol.parse("MU", market=Market.US)
    service = DailyResearchLoopService()
    baseline = service.complete_success(
        brief=_brief(),
        previous_snapshot=None,
        successful_at="2026-07-17T08:30:00+00:00",
        sources={**_source(twse), **_source(us)},
    ).snapshot
    assert baseline is not None

    result = service.complete_success(
        brief=_brief(
            attention=(
                DailyBriefItem(
                    code="price_move",
                    severity="warning",
                    title="美股 MU 價格波動",
                    detail="需要研究。",
                    evidence="收盤價 100。",
                    as_of_date="2026-07-17",
                    action="open_research",
                    symbol=us,
                    field="price_change",
                ),
                DailyBriefItem(
                    code="price_move",
                    severity="warning",
                    title="台股 MU 價格波動",
                    detail="需要研究。",
                    evidence="收盤價 50。",
                    as_of_date="2026-07-17",
                    action="open_research",
                    symbol=twse,
                    field="price_change",
                ),
            )
        ),
        previous_snapshot=baseline,
        successful_at="2026-07-17T09:30:00+00:00",
        sources={**_source(twse), **_source(us)},
    )

    assert [event.identity for event in result.priority_events] == ["TWSE:MU", "US:MU"]


def test_new_risk_and_data_repair_events_are_classified_and_ranked() -> None:
    symbol = Symbol.parse("2330", market=Market.TWSE)
    service = DailyResearchLoopService()
    baseline = service.complete_success(
        brief=_brief(),
        previous_snapshot=None,
        successful_at="2026-07-17T08:30:00+00:00",
        sources=_source(symbol),
    ).snapshot
    assert baseline is not None

    result = service.complete_success(
        brief=_brief(
            attention=(
                DailyBriefItem(
                    code="risk_alert",
                    severity="critical",
                    title="持股集中度偏高",
                    detail="最大單一持股比重超出研究門檻。",
                    evidence="最大比重 62%。",
                    as_of_date="2026-07-17",
                    action="view_holdings",
                    field="portfolio_concentration",
                ),
            ),
            actions=(
                ActionRequired(
                    field="price_data",
                    title="補齊價格資料",
                    detail="2330 缺少可用價格。",
                    action="update_data",
                    symbol=symbol,
                ),
            ),
        ),
        previous_snapshot=baseline,
        successful_at="2026-07-17T09:30:00+00:00",
        sources=_source(symbol),
    )

    assert [event.category for event in result.priority_events] == ["new_change", "data_repair"]
    assert result.priority_events[0].action == "view_holdings"
    assert result.priority_events[1].action == "update_data"


def test_partial_refresh_preserves_previous_successful_snapshot() -> None:
    symbol = Symbol.parse("2330", market=Market.TWSE)
    service = DailyResearchLoopService()
    baseline = service.complete_success(
        brief=_brief(),
        previous_snapshot=None,
        successful_at="2026-07-17T08:30:00+00:00",
        sources=_source(symbol),
    ).snapshot
    assert baseline is not None

    result = service.complete_partial(
        previous_snapshot=baseline,
        checked_at="2026-07-17T09:30:00+00:00",
        reason="1 個資料來源更新失敗。",
    )

    assert result.status == "partial"
    assert result.snapshot == baseline
    assert result.priority_events == ()
    assert "上次成功" in result.message


def test_corrupted_snapshot_safely_falls_back(tmp_path: Path) -> None:
    store = DailyResearchSnapshotStore(tmp_path / "daily_research" / "last_successful.json")
    store.path.parent.mkdir(parents=True)
    store.path.write_text("not-json", encoding="utf-8")

    loaded = store.load()

    assert loaded.snapshot is None
    assert "無法讀取" in loaded.warning


def test_first_use_without_snapshot_and_partial_failure_stay_explicit() -> None:
    service = DailyResearchLoopService()

    restored = service.restore(DailyResearchSnapshotLoad(snapshot=None))
    partial = service.complete_partial(
        previous_snapshot=None,
        checked_at="2026-07-17T08:30:00+00:00",
        reason="更新失敗。",
    )

    assert restored.status == "unavailable"
    assert "手動更新" in restored.message
    assert partial.status == "unavailable"
    assert "檢查時間" in (partial.warning or "")


def test_snapshot_serialization_round_trip_keeps_safe_derived_provenance() -> None:
    symbol = Symbol.parse("2330", market=Market.TWSE)
    snapshot = (
        DailyResearchLoopService()
        .complete_success(
            brief=_brief(
                attention=(
                    DailyBriefItem(
                        code="daily_move",
                        severity="attention",
                        title="2330 單日變動明顯",
                        detail="價格變動。",
                        evidence="變動 +6%。",
                        as_of_date="2026-07-17",
                        action="open_research",
                        symbol=symbol,
                        field="price_change",
                    ),
                )
            ),
            previous_snapshot=None,
            successful_at="2026-07-17T08:30:00+00:00",
            sources=_source(symbol),
        )
        .snapshot
    )
    assert snapshot is not None

    restored = type(snapshot).from_dict(snapshot.to_dict())

    assert restored == snapshot
    assert next(item for item in restored.events if item.code == "daily_move").source.label == (
        "yfinance / online"
    )


def test_event_without_provider_metadata_uses_explicit_local_derived_source() -> None:
    result = DailyResearchLoopService().complete_success(
        brief=_brief(
            attention=(
                DailyBriefItem(
                    code="risk_alert",
                    severity="warning",
                    title="持股風險提醒",
                    detail="已有風險提醒。",
                    evidence="風險提醒 1 項。",
                    as_of_date="2026-07-17",
                    action="view_holdings",
                    field="risk_alerts",
                ),
            )
        ),
        previous_snapshot=None,
        successful_at="2026-07-17T08:30:00+00:00",
        sources={},
    )

    assert result.snapshot is not None
    assert result.snapshot.events[0].source.label == "本機投資組合／研究狀態"


def test_snapshot_survives_restart_and_compares_after_reopen(tmp_path: Path) -> None:
    symbol = Symbol.parse("2330", market=Market.TWSE)
    service = DailyResearchLoopService()
    store = DailyResearchSnapshotStore(tmp_path / "daily_research" / "last_successful.json")
    baseline = service.complete_success(
        brief=_brief(),
        previous_snapshot=None,
        successful_at="2026-07-17T08:30:00+00:00",
        sources=_source(symbol),
    ).snapshot
    assert baseline is not None
    store.save(baseline)

    restored = service.restore(store.load())
    updated = service.complete_success(
        brief=_brief(
            attention=(
                DailyBriefItem(
                    code="daily_move",
                    severity="attention",
                    title="2330 單日變動明顯",
                    detail="相較前一個可用交易日上漲。",
                    evidence="前一交易日收盤 100；最新收盤 110；變動 +10%。",
                    as_of_date="2026-07-17",
                    action="open_research",
                    symbol=symbol,
                    field="price_change",
                ),
            )
        ),
        previous_snapshot=restored.snapshot,
        successful_at="2026-07-17T09:30:00+00:00",
        sources=_source(symbol),
    )

    assert restored.status == "previous_success"
    assert updated.status == "updated"
    assert updated.priority_events[0].identity == "TWSE:2330"


def test_missing_score_is_not_converted_to_a_negative_change() -> None:
    symbol = Symbol.parse("AAPL", market=Market.US)
    service = DailyResearchLoopService()
    brief = _brief(
        actions=(
            ActionRequired(
                field="composite_score",
                title="綜合評分資料不足",
                detail="尚未完成可用的綜合評分。",
                action="complete_data",
                symbol=symbol,
            ),
        )
    )
    baseline = service.complete_success(
        brief=brief,
        previous_snapshot=None,
        successful_at="2026-07-17T08:30:00+00:00",
        sources=_source(symbol),
    ).snapshot
    assert baseline is not None

    result = service.complete_success(
        brief=brief,
        previous_snapshot=baseline,
        successful_at="2026-07-17T09:30:00+00:00",
        sources=_source(symbol),
    )

    assert result.status == "no_change"
    assert result.priority_events == ()
    assert all("0" not in item.current_value for item in result.repair_events)


def test_dashboard_loop_uses_isolated_snapshot_and_preserves_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    symbol = Symbol.parse("2330", market=Market.TWSE)
    fake_st = type("FakeStreamlit", (), {"session_state": {}})()
    monkeypatch.setattr(dashboard_app, "default_runtime_paths", lambda: runtime_paths)
    monkeypatch.setattr(dashboard_app, "_build_daily_brief", lambda _st: _brief())
    monkeypatch.setattr(dashboard_app, "_daily_research_sources", lambda _st: _source(symbol))
    result = dashboard_app._complete_daily_research_loop(
        fake_st,
        dashboard_app.DailyRefreshResult(
            requested_count=1,
            limited_count=1,
            records=(dashboard_app.DailyRefreshRecord(symbol=symbol, status="success"),),
        ),
    )

    fake_st_after_restart = type("FakeStreamlit", (), {"session_state": {}})()
    restored = dashboard_app._build_daily_research_loop(fake_st_after_restart)

    assert result.status == "baseline_created"
    assert restored.status == "previous_success"
    assert restored.last_successful_at == "2026-07-17T08:30:00+00:00"
    assert runtime_paths.daily_research_snapshot_file.exists()


def test_daily_research_sources_keep_market_and_freshness_metadata(monkeypatch) -> None:
    fake_st = type("FakeStreamlit", (), {"session_state": {}})()
    prices = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL"],
            "market": ["TWSE", "US"],
            "date": ["2026-07-17", "2026-07-16"],
            "close": [100.0, 200.0],
            "provider": ["yfinance", "cache"],
            "provider_symbol": ["2330.TW", "AAPL"],
            "source_type": ["online", "cache"],
            "last_data_date": ["2026-07-17", "2026-07-16"],
            "checked_at": ["2026-07-17T08:30:00+00:00", "2026-07-17T07:30:00+00:00"],
        }
    )
    monkeypatch.setattr(dashboard_app, "_portfolio_price_context", lambda _st: prices)

    sources = dashboard_app._daily_research_sources(fake_st)

    assert sources["TWSE:2330"].provider == "yfinance"
    assert sources["US:AAPL"].source_type == "cache"
    assert sources["US:AAPL"].last_data_date == "2026-07-16"
    assert sources["TWSE:2330"].checked_at == "2026-07-17T08:30:00+00:00"


def test_manual_refresh_persists_only_all_successful_results_and_keeps_user_frames(
    tmp_path: Path, monkeypatch
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    symbol = Symbol.parse("2330", market=Market.TWSE)
    portfolio = pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"], "quantity": [1.0]})
    watchlist = pd.DataFrame({"symbol": ["AAPL"], "market": ["US"], "note": [""]})
    before_portfolio = portfolio.copy(deep=True)
    before_watchlist = watchlist.copy(deep=True)
    fake_st = type("FakeStreamlit", (), {"session_state": {}})()
    monkeypatch.setattr(dashboard_app, "default_runtime_paths", lambda: runtime_paths)
    monkeypatch.setattr(dashboard_app, "_get_portfolio", lambda _st: portfolio)
    monkeypatch.setattr(dashboard_app, "_get_watchlist", lambda _st: watchlist)
    monkeypatch.setattr(dashboard_app, "_build_daily_brief", lambda _st: _brief())
    monkeypatch.setattr(dashboard_app, "_daily_research_sources", lambda _st: _source(symbol))

    class _SuccessfulRefresh:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def refresh(self, **_kwargs: object) -> dashboard_app.DailyRefreshResult:
            return dashboard_app.DailyRefreshResult(
                requested_count=1,
                limited_count=1,
                records=(dashboard_app.DailyRefreshRecord(symbol=symbol, status="success"),),
            )

    monkeypatch.setattr(dashboard_app, "DailyRefreshService", _SuccessfulRefresh)
    dashboard_app._refresh_daily_data(fake_st)
    snapshot_path = runtime_paths.daily_research_snapshot_file
    baseline_bytes = snapshot_path.read_bytes()

    class _PartialRefresh:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def refresh(self, **_kwargs: object) -> dashboard_app.DailyRefreshResult:
            return dashboard_app.DailyRefreshResult(
                requested_count=1,
                limited_count=1,
                records=(dashboard_app.DailyRefreshRecord(symbol=symbol, status="partial"),),
            )

    monkeypatch.setattr(dashboard_app, "DailyRefreshService", _PartialRefresh)
    dashboard_app._refresh_daily_data(fake_st)

    assert fake_st.session_state["dashboard_daily_research_loop"].status == "partial"
    assert snapshot_path.read_bytes() == baseline_bytes
    pd.testing.assert_frame_equal(portfolio, before_portfolio)
    pd.testing.assert_frame_equal(watchlist, before_watchlist)


def test_daily_research_loop_home_is_visible_after_isolated_app_restart(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = tmp_path / "runtime"
    paths = RuntimePaths(runtime).ensure_directories()
    pd.DataFrame(
        {
            "symbol": ["2330"],
            "market": ["TWSE"],
            "quantity": [1.0],
            "average_cost": [500.0],
            "currency": ["TWD"],
            "note": [""],
        }
    ).to_csv(paths.portfolio_file, index=False, encoding="utf-8")
    symbol = Symbol.parse("2330", market=Market.TWSE)
    snapshot = (
        DailyResearchLoopService()
        .complete_success(
            brief=_brief(),
            previous_snapshot=None,
            successful_at="2026-07-17T08:30:00+00:00",
            sources=_source(symbol),
        )
        .snapshot
    )
    assert snapshot is not None
    DailyResearchSnapshotStore(paths.daily_research_snapshot_file).save(snapshot)
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    app_path = Path(__file__).parents[1] / "src" / "stock_tool" / "dashboard" / "app.py"

    app = AppTest.from_file(str(app_path)).run(timeout=20)

    assert not app.exception
    assert any(item.value == "每日研究更新" for item in app.subheader)
    assert any("上次成功檢查" in item.value for item in app.caption)


def test_deterministic_five_session_replay_orders_only_top_three_changes() -> None:
    """The required five-session replay stays deterministic without fabricated updates."""

    twse = Symbol.parse("2330", market=Market.TWSE)
    tpex = Symbol.parse("6488", market=Market.TPEX)
    us = Symbol.parse("AAPL", market=Market.US)
    service = DailyResearchLoopService()

    # 1. First successful update creates only a comparison baseline.
    first = service.complete_success(
        brief=_brief(),
        previous_snapshot=None,
        successful_at="2026-07-17T08:00:00+00:00",
        sources={**_source(twse), **_source(tpex), **_source(us)},
    )
    assert first.status == "baseline_created"
    assert first.snapshot is not None

    # 2. Identical evidence produces no false event.
    second = service.complete_success(
        brief=_brief(),
        previous_snapshot=first.snapshot,
        successful_at="2026-07-17T09:00:00+00:00",
        sources={**_source(twse), **_source(tpex), **_source(us)},
    )
    assert second.status == "no_change"
    assert second.snapshot is not None

    # 3. More than three new signals are sorted by deterministic policy.
    third = service.complete_success(
        brief=_brief(
            attention=(
                DailyBriefItem(
                    code="risk_alert",
                    severity="warning",
                    title="AAPL 持股風險提醒",
                    detail="風險提醒增加。",
                    evidence="風險提醒 2 項。",
                    as_of_date="2026-07-17",
                    action="view_holdings",
                    symbol=us,
                    field="risk_alerts",
                ),
                DailyBriefItem(
                    code="daily_move",
                    severity="attention",
                    title="2330 單日變動明顯",
                    detail="價格變動。",
                    evidence="變動 +8%。",
                    as_of_date="2026-07-17",
                    action="open_research",
                    symbol=twse,
                    field="price_change",
                ),
                DailyBriefItem(
                    code="volume_move",
                    severity="attention",
                    title="6488 成交量變動明顯",
                    detail="成交量變動。",
                    evidence="量能為均量 2 倍。",
                    as_of_date="2026-07-17",
                    action="open_research",
                    symbol=tpex,
                    field="volume",
                ),
                DailyBriefItem(
                    code="stale_price",
                    severity="warning",
                    title="6488 價格資料可能過期",
                    detail="資料可能過期。",
                    evidence="最後資料日 2026-07-10。",
                    as_of_date="2026-07-10",
                    action="update_data",
                    symbol=tpex,
                    field="price_data",
                ),
            )
        ),
        previous_snapshot=second.snapshot,
        successful_at="2026-07-17T10:00:00+00:00",
        sources={**_source(twse), **_source(tpex), **_source(us)},
    )
    assert [event.code for event in third.priority_events] == [
        "risk_alert",
        "stale_price",
        "volume_move",
    ]
    assert third.snapshot is not None

    # 4. Partial provider work leaves the preceding successful state intact.
    fourth = service.complete_partial(
        previous_snapshot=third.snapshot,
        checked_at="2026-07-17T11:00:00+00:00",
        reason="1 個資料來源更新失敗。",
    )
    assert fourth.status == "partial"
    assert fourth.snapshot == third.snapshot

    # 5. A new process can restore the same comparison baseline.
    restored = service.restore(DailyResearchSnapshotLoad(snapshot=fourth.snapshot))
    assert restored.status == "previous_success"
    assert restored.last_successful_at == "2026-07-17T10:00:00+00:00"


def test_daily_research_event_cta_preserves_market_qualified_identity() -> None:
    symbol = Symbol.parse("6488", market=Market.TPEX)
    event = (
        DailyResearchLoopService()
        .complete_success(
            brief=_brief(
                attention=(
                    DailyBriefItem(
                        code="daily_move",
                        severity="attention",
                        title="6488 單日變動明顯",
                        detail="價格變動。",
                        evidence="變動 +6%。",
                        as_of_date="2026-07-17",
                        action="open_research",
                        symbol=symbol,
                        field="price_change",
                    ),
                )
            ),
            previous_snapshot=DailyResearchLoopService()
            .complete_success(
                brief=_brief(),
                previous_snapshot=None,
                successful_at="2026-07-17T08:00:00+00:00",
                sources=_source(symbol),
            )
            .snapshot,
            successful_at="2026-07-17T09:00:00+00:00",
            sources=_source(symbol),
        )
        .priority_events[0]
    )

    action = home_page._action_for_loop_event(event)

    assert action.kind == "search"
    assert action.preparation is not None
    assert action.preparation.request is not None
    assert action.preparation.request.market == "TPEX"
    assert action.preparation.request.symbol == "6488"
