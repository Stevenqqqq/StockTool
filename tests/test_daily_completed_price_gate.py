"""Completed-close regressions for home, daily research and holding valuation."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_tool.application import daily_research_scheduler as scheduler
from stock_tool.application import completed_daily_prices as boundary
from stock_tool.application.holding_analysis import build_holding_analysis, validated_holding_prices
from stock_tool.application.daily_holdings import (
    holding_close_is_completed,
    publish_holdings,
    fingerprint,
    report_path,
)
from stock_tool.dashboard import app
from stock_tool.data.storage import PersistedPriceProvenance, SQLitePriceStorage
from stock_tool.domain.models import Symbol
from stock_tool.portfolio_valuation import PortfolioValuationService
from stock_tool.runtime_paths import RuntimePaths

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(boundary, "datetime", Clock)


def prices(market="TWSE", symbol="3006", fetched="2026-10-23T02:00:00Z"):
    return pd.DataFrame(
        dict(
            symbol=symbol,
            market=market,
            date=day,
            close=close,
            open=close,
            high=close,
            low=close,
            volume=1000,
            adjusted_close=close,
            fetched_at=fetched,
            checked_at="2026-10-23T12:00:00Z",
            provider="synthetic",
            source_type="synthetic",
            last_data_date="2026-10-23",
        )
        for day, close in (("2026-10-22", 100.0), ("2026-10-23", 999.0))
    )


def position():
    return dict(symbol="3006", market="TWSE", quantity=2, average_cost=80, currency="TWD")


def context(monkeypatch, raw):
    monkeypatch.setattr(app, "_load_default_database_prices", lambda _path: raw)
    monkeypatch.setattr(app, "_market_qualified_current_prices", lambda _st: None)
    monkeypatch.setattr(app, "_runtime_database_path", lambda: None)
    return SimpleNamespace(session_state={})


@pytest.mark.parametrize("market,symbol", [("TWSE", "3006"), ("TPEX", "6488"), ("US", "MU")])
def test_home_context_and_daily_sources_use_only_completed_dates(monkeypatch, market, symbol):
    raw = prices(market, symbol)
    before = raw.copy(deep=True)
    st = context(monkeypatch, raw)
    usable = app._portfolio_price_context(st)
    assert usable.close.tolist() == [100.0]
    source = app._daily_research_sources(st)[f"{market}:{symbol}"]
    assert source.last_data_date == "2026-10-22"
    assert source.checked_at == "2026-10-23T12:00:00Z"
    pd.testing.assert_frame_equal(raw, before)


@pytest.mark.parametrize("fetched", [None, "2026-10-23T02:00:00", "2099-01-01T00:00:00Z"])
def test_check_time_cannot_replace_unknown_or_invalid_acquisition(monkeypatch, fetched):
    raw = prices(fetched=fetched)
    st = context(monkeypatch, raw)
    usable = app._portfolio_price_context(st)
    assert usable is None or usable.empty
    assert app._daily_research_sources(st) == {}
    snapshot = build_holding_analysis(position(), prices=raw, fx_quote=None, now=NOW)
    assert not any(item.label == "原幣市值" for item in snapshot.data)


def test_fresh_holding_and_canonical_valuation_share_completed_copy():
    raw = prices()
    before = raw.copy(deep=True)
    snapshot = build_holding_analysis(position(), prices=raw, fx_quote=None, now=NOW)
    close = next(item for item in snapshot.data if item.label == "收盤價")
    assert close.value == "TWD 100.00"
    assert close.as_of == "2026-10-22"
    assert any("未收盤" in gap for gap in snapshot.gaps)
    usable = validated_holding_prices(pd.DataFrame([position()]), raw, {}, now=NOW)
    assert usable.close.tolist() == [100.0]
    value = PortfolioValuationService().value(positions=pd.DataFrame([position()]), prices=usable)
    assert value.positions.native_market_value.iloc[0] == 200.0
    pd.testing.assert_frame_equal(raw, before)


def test_cached_intraday_is_not_promoted_on_later_restart():
    raw = prices().tail(1)
    for clock in (NOW, datetime(2026, 10, 25, 12, tzinfo=UTC)):
        snapshot = build_holding_analysis(position(), prices=raw, fx_quote=None, now=clock)
        assert not any(item.label == "原幣市值" for item in snapshot.data)
        assert validated_holding_prices(pd.DataFrame([position()]), raw, {}, now=clock).empty


def test_headless_loader_retains_raw_sqlite_but_filters_daily_inputs(tmp_path):
    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    storage = SQLitePriceStorage(paths.processed_dir / "stock_data.sqlite")
    raw = prices()
    storage.save_market_qualified_price_data(
        raw.to_dict("records"),
        provenance=PersistedPriceProvenance(
            symbol=Symbol.parse("3006", market="TWSE"),
            provider="synthetic",
            provider_symbol="3006.TW",
            source_type="synthetic",
            last_data_date="2026-10-23",
            checked_at="2026-10-23T12:00:00Z",
            fetched_at="2026-10-23T02:00:00Z",
        ),
    )
    before = storage.database_path.read_bytes(), storage.price_identity_sidecar_path.read_bytes()
    usable, checked = scheduler._load_price_context(paths)
    assert usable.close.tolist() == [100.0]
    assert checked == {"TWSE:3006": "2026-10-23T12:00:00+00:00"}
    assert before == (
        storage.database_path.read_bytes(),
        storage.price_identity_sidecar_path.read_bytes(),
    )


@pytest.mark.parametrize("only_intraday", [False, True])
def test_actual_home_brief_never_calls_intraday_a_close(monkeypatch, only_intraday):
    from test_dashboard import _FakeStreamlit

    raw = prices()
    if only_intraday:
        raw = raw.tail(1)
    context(monkeypatch, raw)
    st = _FakeStreamlit()
    st.session_state.fundamental_scores = None
    st.session_state.price_data_source = {"checked_at": NOW.isoformat()}
    monkeypatch.setattr(app, "_get_portfolio", lambda _st: pd.DataFrame([position()]))
    monkeypatch.setattr(
        app, "_get_watchlist", lambda _st: pd.DataFrame(columns=["symbol", "market"])
    )
    brief = app._build_daily_brief(st)
    assert brief.data_as_of_date == (None if only_intraday else "2026-10-22")
    assert brief.portfolio.priced_position_count == (0 if only_intraday else 1)
    assert not any(item.code == "daily_move" for item in brief.attention_items)


def test_multi_market_gate_does_not_infer_identity_or_mutate_raw():
    raw = pd.concat(
        [prices(market=market) for market in ("TWSE", "TPEX", "US", "UNKNOWN")],
        ignore_index=True,
    )
    before = raw.copy(deep=True)
    usable = boundary.completed_market_prices(raw, now=NOW)
    assert usable.market.tolist() == ["TWSE", "TPEX", "US"]
    assert usable.close.tolist() == [100.0] * 3
    assert boundary.completed_market_prices(raw.drop(columns="market"), now=NOW).empty
    pd.testing.assert_frame_equal(raw, before)


def test_late_acquisition_accepts_close_but_rereading_intraday_does_not():
    intraday = prices()
    late = prices(fetched="2026-10-23T10:30:00Z")
    assert boundary.completed_market_prices(intraday, now=NOW).close.tolist() == [100.0]
    assert boundary.completed_market_prices(late, now=NOW).close.tolist() == [100.0, 999.0]


def test_intraday_session_cannot_overwrite_completed_persisted_close(monkeypatch):
    stored = prices(fetched="2026-10-23T11:00:00Z")
    stored.loc[stored.date == "2026-10-23", "close"] = 120.0
    st = context(monkeypatch, stored)
    monkeypatch.setattr(app, "_market_qualified_current_prices", lambda _st: prices())
    usable = app._portfolio_price_context(st)
    assert usable.close.tolist() == [100.0, 120.0]


def test_headless_loop_saves_bar_date_not_later_check_date(monkeypatch, tmp_path):
    from test_daily_research_scheduler import (
        _prepare_stage_fault_runner,
        _stage_fault_market_result,
    )

    paths = _prepare_stage_fault_runner(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scheduler,
        "_load_price_context",
        lambda _paths, **_kw: (prices().head(1), {"TWSE:3006": NOW.isoformat()}),
    )
    captured = {}

    def complete(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(snapshot=object())

    monkeypatch.setattr(scheduler.DailyResearchLoopService, "complete_success", complete)
    outcome = scheduler.HeadlessDailyResearchRunner(
        paths,
        now_fn=lambda: NOW,
        market_refresh_callback=_stage_fault_market_result,
    ).run(trigger="manual")
    assert next(stage for stage in outcome.stages if stage.name == "brief").status == "success"
    assert captured["sources"]["TWSE:3006"].last_data_date == "2026-10-22"
    assert captured["sources"]["TWSE:3006"].checked_at == NOW.isoformat()


def test_pre_fix_saved_intraday_close_is_not_reused_as_baseline(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from stock_tool.application.daily_holdings_job import DailyJob

    paths = RuntimePaths(tmp_path / "runtime").ensure_directories()
    positions = pd.DataFrame([position()])
    valid = publish_holdings(paths, positions, prices(), now=NOW, fx_quote=None, failed=set())
    row = valid["holdings"]["TWSE:3006"]
    assert holding_close_is_completed(row, now=NOW)
    for datum in row["data"]:
        if datum["label"] == "收盤價":
            datum.update(as_of="2026-10-23", value="TWD 999.00")
    assert not holding_close_is_completed(row, now=NOW)
    # This is a structurally valid old report, not a corrupt-file test.
    valid["fingerprint"] = fingerprint(valid)
    report_path(paths).write_text(json.dumps(valid, ensure_ascii=False), encoding="utf-8")
    original = report_path(paths).read_bytes()
    assert not holding_close_is_completed(row, now=NOW)
    positions.to_csv(paths.portfolio_file, index=False)
    app._persist_price_data(prices(), paths.processed_dir / "stock_data.sqlite")
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(paths.root))
    monkeypatch.setattr(
        "stock_tool.dashboard.components.daily_holdings.start_refresh",
        lambda *_a, **_k: DailyJob(),
    )
    ui = AppTest.from_file(str(Path(app.__file__).resolve())).run(timeout=30)
    assert not ui.exception
    assert any("未確認完成的日線" in item.value for item in ui.warning)
    assert not any("TWD 999.00" in item.value for item in ui.markdown)
    assert report_path(paths).read_bytes() == original
    result = publish_holdings(paths, positions, prices(), now=NOW, fx_quote=None, failed=set())
    assert result["holdings"]["TWSE:3006"]["status"] == "首次基準"
    assert result["holdings"]["TWSE:3006"]["previous_events"] == []
