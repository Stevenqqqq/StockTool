"""Completed-bar boundary regressions; no network or production data."""

from datetime import datetime
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from stock_tool.application.completed_daily_prices import completed_daily_prices


@pytest.mark.parametrize(
    "market,stamp,expected",
    [
        ("TWSE", "2026-10-14T02:20:00Z", 1),
        ("TPEX", "2026-10-14T10:29:59Z", 1),
        ("TWSE", "2026-10-14T10:30:00Z", 2),
        ("TWSE", "2026-10-14T18:30:00+08:00", 2),
        ("US", "2026-10-14T17:00:00+08:00", 1),
        ("US", "2026-10-15T05:59:59+08:00", 1),
        ("US", "2026-10-15T06:00:00+08:00", 2),
        ("UNKNOWN", "2026-10-15T12:00:00Z", 0),
        ("TWSE", None, 0),
        ("TWSE", "2026-10-14T20:00:00", 0),
        ("TWSE", "invalid", 0),
        ("TWSE", "2026-10-17T20:00:00Z", 0),
    ],
)
def test_completed_inputs(market, stamp, expected):
    raw = pd.DataFrame(
        {"date": ["2026-10-13", "2026-10-14"], "close": [242.0, 999.0], "volume": [1000, 1]}
    )
    before = raw.copy(deep=True)
    usable, notices = completed_daily_prices(
        raw,
        market=market,
        fetched_at=stamp,
        now=datetime.fromisoformat("2026-10-16T00:00:00+00:00"),
    )
    assert len(usable) == expected
    assert bool(notices) == (expected != 2)
    assert_frame_equal(raw, before)


def test_cached_intraday_never_becomes_completed_and_row_provenance_wins():
    raw = pd.DataFrame(
        {"date": ["2026-10-14", "2026-10-13"], "fetched_at": ["2026-10-14T02:20:00Z", None]}
    )
    usable, notices = completed_daily_prices(
        raw,
        market="TWSE",
        fetched_at="2026-10-15T12:00:00Z",
        now=datetime.fromisoformat("2026-10-16T00:00:00+00:00"),
    )
    assert usable.empty and notices


def test_aware_bar_dates_and_us_winter_timezone():
    raw = pd.DataFrame({"date": ["2026-01-15T05:00:00Z"]})
    now = datetime.fromisoformat("2026-01-17T00:00:00+00:00")
    assert completed_daily_prices(
        raw, market="US", fetched_at="2026-01-16T06:59:00+08:00", now=now
    )[0].empty
    assert (
        len(
            completed_daily_prices(
                raw, market="US", fetched_at="2026-01-16T07:00:00+08:00", now=now
            )[0]
        )
        == 1
    )


def test_invalid_dates_and_naive_clock_fail_closed():
    raw = pd.DataFrame({"date": [None, "invalid", "2026-10-17"]})
    assert completed_daily_prices(
        raw,
        market="TWSE",
        fetched_at="2026-10-15T12:00:00Z",
        now=datetime.fromisoformat("2026-10-16T00:00:00+00:00"),
    )[0].empty
    assert completed_daily_prices(
        pd.DataFrame({"date": ["2026-10-13"]}),
        market="TWSE",
        fetched_at="2026-10-15T12:00:00Z",
        now=datetime(2026, 10, 16),
    )[0].empty


def test_workspace_all_outputs_share_completed_history_and_company_survives(monkeypatch):
    import stock_tool.dashboard.app as app
    import stock_tool.application.completed_daily_prices as boundary

    original_boundary = boundary.completed_daily_prices
    monkeypatch.setattr(
        boundary,
        "completed_daily_prices",
        lambda *args, **kwargs: original_boundary(
            *args, **kwargs, now=datetime.fromisoformat("2026-10-16T00:00:00+00:00")
        ),
    )
    from test_dashboard import _FakeStreamlit
    from test_research_header_completeness import _profile
    from stock_tool.dashboard.components.price_volume_observation import observation_summary
    from stock_tool.dashboard.components.research_header import render_research_header
    from test_research_workspace import _FakeStreamlit as Display

    dates = pd.bdate_range(end="2026-10-14", periods=81)
    raw = pd.DataFrame(
        {
            "date": dates,
            "symbol": "3006",
            "market": "TWSE",
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1000.0,
            "fetched_at": "2026-10-14T02:20:00Z",
        }
    )
    raw.loc[80, ["close", "high", "volume"]] = [999.0, 1000.0, 1.0]
    st = _FakeStreamlit()
    st.session_state.update(
        price_data=raw,
        technical_indicators=app.compute_technical_indicators(raw),
        fundamental_scores=None,
        backtest_result=None,
        price_data_source={"fetched_at": "2026-10-14T02:20:00Z"},
        dashboard_status="ready",
    )
    profile = _profile()
    monkeypatch.setattr(app, "_get_company_research_profile", lambda *args: profile)
    before = raw.copy(deep=True)
    snapshot = app._build_research_snapshot(st, symbol="3006", market="TWSE")
    assert snapshot.price.latest_close == 101.0
    assert snapshot.price.last_data_date[:10] == "2026-10-13"
    assert len(snapshot.price_history) == 80
    expected_prices = raw.iloc[:-1].assign(date=pd.to_datetime(raw.iloc[:-1].date.dt.date.tolist()))
    assert_frame_equal(snapshot.indicators, app.compute_technical_indicators(expected_prices))
    baseline = app.score_stock(
        symbol="3006",
        price_data=raw.iloc[:-1],
        technical_indicators=app.compute_technical_indicators(raw.iloc[:-1]),
    )
    assert snapshot.available_score == baseline.available_score
    assert snapshot.scenario_reference.as_of_date[:10] == "2026-10-13"
    assert "1.00" in observation_summary(snapshot)[1]
    assert snapshot.company_profile is profile
    display = Display()
    render_research_header(display, snapshot)
    assert "收盤研究：已排除 1 筆" in str(display.events)
    assert_frame_equal(raw, before)
    st.session_state.price_data = raw.assign(fetched_at="2026-10-14T10:30:00Z")
    after_close = app._build_research_snapshot(st, symbol="3006", market="TWSE")
    assert after_close.price.latest_close == 999.0
    assert after_close.price.last_data_date[:10] == "2026-10-14"
    assert after_close.scenario_reference.as_of_date[:10] == "2026-10-14"
    assert len(after_close.price_history) == 81
    st.session_state.price_data = raw.assign(fetched_at=None)
    unavailable = app._build_research_snapshot(st, symbol="3006", market="TWSE")
    assert unavailable.price is None
    assert unavailable.available_score is None
    assert unavailable.company_profile is profile


@pytest.mark.parametrize(
    "market,last_utc,acquired",
    [
        ("TWSE", "2026-10-12T16:00:00Z", "2026-10-13T12:00:00Z"),
        ("US", "2026-10-14T00:00:00Z", "2026-10-14T00:30:00Z"),
    ],
)
def test_aware_date_end_to_end_and_saved_evidence(
    market, last_utc, acquired, monkeypatch, tmp_path
):
    import stock_tool.dashboard.app as app
    import stock_tool.application.completed_daily_prices as boundary
    from test_dashboard import _FakeStreamlit
    from stock_tool.dashboard.components.research_chart import build_research_chart
    from stock_tool.dashboard.components.price_volume_observation import observation_summary
    from stock_tool.research.evidence import build_evidence_bundle
    from stock_tool.research.assistant import AIResearchAssistant, ResearchAssistantCache
    from stock_tool.research.library import ResearchLibrary
    from stock_tool.application.research_library import ResearchLibraryApplicationService

    original_boundary = boundary.completed_daily_prices
    monkeypatch.setattr(
        boundary,
        "completed_daily_prices",
        lambda *a, **kw: original_boundary(
            *a, **kw, now=datetime.fromisoformat("2026-10-16T00:00:00+00:00")
        ),
    )
    symbol = "3006" if market == "TWSE" else "MU"
    dates = pd.date_range(end=last_utc, periods=81, freq="D")
    raw = pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "market": market,
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1000.0,
            "fetched_at": acquired,
        }
    )
    before = raw.copy(deep=True)
    st = _FakeStreamlit()
    st.session_state.update(
        price_data=raw,
        technical_indicators=None,
        fundamental_scores=None,
        backtest_result=None,
        price_data_source={"fetched_at": acquired},
        dashboard_status="ready",
    )
    monkeypatch.setattr(app, "_get_company_research_profile", lambda *a: None)
    snap = app._build_research_snapshot(st, symbol=symbol, market=market)
    assert snap.price.last_data_date == "2026-10-13"
    assert snap.price.latest_close == 101.0
    assert snap.price_history.date.iloc[-1] == pd.Timestamp("2026-10-13")
    assert snap.indicators.date.iloc[-1] == pd.Timestamp("2026-10-13")
    assert snap.scenario_reference.as_of_date == "2026-10-13"
    assert "2026-10-13" in observation_summary(snap)[2]
    assert "1.00" in observation_summary(snap)[1]
    chart = build_research_chart(snap.price_history, indicators=snap.indicators, period="1Y")
    assert chart.last_data_date == "2026-10-13"
    assert chart.data.date.max() == pd.Timestamp("2026-10-13")
    assert snap.price_history.fetched_at.tolist() == raw.fetched_at.tolist()
    assert snap.source_metadata.fetched_at == acquired
    bundle = build_evidence_bundle(snap)
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "ai")).generate(bundle)
    library = ResearchLibrary(tmp_path / "library")
    entry = ResearchLibraryApplicationService(library).save_research(
        bundle=bundle, note=note, title="Synthetic aware dates"
    )
    loaded = ResearchLibrary(tmp_path / "library").get(entry.library_entry_id)
    assert loaded is not None
    assert loaded.bundle.evidence == bundle.evidence
    assert any(e.available_at == "2026-10-13" for e in loaded.bundle.evidence)
    assert_frame_equal(raw, before)
    # Same local bar acquired intraday is still rejected when read days later.
    intraday = "2026-10-13T02:20:00Z" if market == "TWSE" else "2026-10-13T18:00:00Z"
    st.session_state.price_data = raw.assign(fetched_at=intraday)
    cached_before = st.session_state.price_data.copy(deep=True)
    cached = app._build_research_snapshot(st, symbol=symbol, market=market)
    assert cached.price.last_data_date == "2026-10-12"
    assert cached.scenario_reference.as_of_date == "2026-10-12"
    assert len(cached.price_history) == 80
    assert_frame_equal(st.session_state.price_data, cached_before)
