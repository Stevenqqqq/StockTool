from dataclasses import replace

import pandas as pd
import pytest

from stock_tool.dashboard.components.price_volume_observation import (
    observation_history,
    observation_summary,
    render_price_volume_observation,
)
from stock_tool.dashboard.pages import research
from test_research_workspace import _ready_snapshot, _FakeStreamlit
from test_research_header_completeness import _profile, _dossier


def snapshot():
    s = _ready_snapshot()
    data = s.price_history.copy()
    data["volume"] = 100.0
    data.loc[data.index[-1], "volume"] = 200.0
    indicators = data[["date"]].copy()
    indicators["sma_20"] = 150.0
    indicators["sma_60"] = 140.0
    return replace(s, price_history=data, indicators=indicators)


def test_known_date_volume_excludes_today_and_future_and_does_not_mutate():
    s = snapshot()
    before = s.price_history.copy(deep=True)
    assert "2.00 倍" in observation_summary(s)[1]
    assert "高於 SMA20（150.00）" in observation_summary(s)[0]
    extra = s.price_history.iloc[-1:].copy()
    extra["date"] += pd.Timedelta(days=1)
    extra["volume"] = 1e12
    later = replace(s, price_history=pd.concat([s.price_history, extra]))
    assert observation_summary(later) == observation_summary(s)
    pd.testing.assert_frame_equal(observation_history(later), observation_history(s))
    pd.testing.assert_frame_equal(s.price_history, before)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), -1, "bad"])
def test_invalid_volume_in_window_is_not_skipped(bad):
    s = snapshot()
    data = s.price_history.astype({"volume": object})
    data.loc[data.index[-5], "volume"] = bad
    assert "unavailable" in observation_summary(replace(s, price_history=data))[1]


def test_zero_denominator_short_history_missing_today_and_duplicate():
    s = snapshot()
    for data in [
        s.price_history.tail(20),
        s.price_history.iloc[:-1],
        s.price_history.assign(volume=0),
        pd.concat([s.price_history, s.price_history.tail(1)]),
        s.price_history.drop(columns="volume"),
    ]:
        assert "unavailable" in observation_summary(replace(s, price_history=data))[1]
    data = s.price_history.copy()
    data.loc[data.index[-1], "volume"] = 0
    assert "0.00 倍" in observation_summary(replace(s, price_history=data))[1]


def test_invalid_date_and_missing_quote_are_unavailable():
    s = snapshot()
    for quote in [None, replace(s.price, last_data_date="bad")]:
        t, v, r = observation_summary(replace(s, price=quote))
        assert "unavailable" in t and "unavailable" in v and "unavailable" in r


def test_stale_or_missing_indicators_are_not_forward_filled():
    s = snapshot()
    for indicators in [
        None,
        s.indicators.iloc[:-1],
        pd.concat([s.indicators, s.indicators.tail(1)]),
    ]:
        assert "unavailable" in observation_summary(replace(s, indicators=indicators))[0]
    assert (
        "SMA60 資料不足"
        in observation_summary(replace(s, indicators=s.indicators.drop(columns="sma_60")))[0]
    )


def test_existing_scenario_is_preserved_with_date_and_limitations():
    s = snapshot()
    ref = replace(s.scenario_reference, as_of_date=s.price.last_data_date)
    text = observation_summary(replace(s, scenario_reference=ref))[2]
    assert f"{ref.range_low:,.2f}" in text and ref.method in text
    future = replace(ref, as_of_date="2099-01-01")
    assert "unavailable" in observation_summary(replace(s, scenario_reference=future))[2]
    old = replace(ref, as_of_date="2020-01-01")
    assert "早於觀測日" in observation_summary(replace(s, scenario_reference=old))[2]
    fake = _FakeStreamlit()
    render_price_volume_observation(fake, replace(s, scenario_reference=ref))
    visible = str(fake.events)
    assert all(v in visible for v in (*ref.assumptions, *ref.limitations))


@pytest.mark.parametrize("with_dossier", [False, True])
def test_overview_always_renders_price_and_volume_before_company(
    monkeypatch, tmp_path, with_dossier
):
    from stock_tool.research.library import ResearchLibrary

    s = snapshot()
    if with_dossier:
        s = replace(s, company_profile=_profile(dossier=_dossier()))
    fake = _FakeStreamlit()
    fake.button = lambda *a, **k: False
    monkeypatch.setattr(research, "render_global_search", lambda *a, **k: None)
    research.render_research_workspace(
        fake, s, library=ResearchLibrary(tmp_path / "library"), ai_cache_directory=tmp_path / "ai"
    )
    chart_events = [i for i, e in enumerate(fake.events) if e[0] == "vega"]
    company = fake.events.index(("subheader", "公司介紹"))
    assert len(chart_events) == 4 and chart_events[1] < company


@pytest.mark.parametrize("period", ["6M", "1Y", "3Y", "MAX"])
def test_period_changes_do_not_change_observation(monkeypatch, period):
    s = snapshot()
    fake = _FakeStreamlit()
    monkeypatch.setattr(fake, "selectbox", lambda *a, **k: period)
    render_price_volume_observation(fake, s)
    assert "2.00 倍" in str(fake.events)
    assert len([e for e in fake.events if e[0] == "vega"]) == 2
