from dataclasses import replace

import pytest

from stock_tool.dashboard.components.price_volume_observation import observation_summary
from stock_tool.dashboard.components.risk_summary import render_risk_summary
from stock_tool.dashboard.pages.research import render_research_workspace
from test_research_workspace import _FakeStreamlit, _ready_snapshot


@pytest.mark.parametrize(
    "reference_date,observed",
    [
        (None, "2025-06-30"),
        ("bad", "2025-06-30"),
        ("2025-07-01", "2025-06-30"),
        ("2025-06-30", None),
        (None, None),
    ],
)
def test_all_entry_points_reject_unusable_dates(reference_date, observed, monkeypatch, tmp_path):
    s = _ready_snapshot()
    s = replace(
        s,
        price=replace(s.price, last_data_date=observed),
        scenario_reference=replace(s.scenario_reference, as_of_date=reference_date),
    )
    assert "unavailable" in observation_summary(s)[2]
    fake = _FakeStreamlit()
    render_risk_summary(fake, s)
    assert not any(kind == "metric" for kind, value in fake.events)
    assert any("unavailable" in str(value) for kind, value in fake.events)
    fake = _FakeStreamlit()
    from stock_tool.dashboard.pages import research
    from stock_tool.research.library import ResearchLibrary

    fake.button = lambda *a, **k: False
    monkeypatch.setattr(research, "render_global_search", lambda *a, **k: None)
    render_research_workspace(
        fake, s, library=ResearchLibrary(tmp_path / "library"), ai_cache_directory=tmp_path / "ai"
    )
    scenario_labels = {"區間", "突破觀察值", "風險參考值"}
    assert not any(kind == "metric" and value[0] in scenario_labels for kind, value in fake.events)


@pytest.mark.parametrize("reference_date,historical", [("2025-06-30", False), ("2025-06-29", True)])
def test_same_day_and_historical_ranges_keep_values_and_label(reference_date, historical):
    s = _ready_snapshot()
    s = replace(
        s,
        price=replace(s.price, last_data_date="2025-06-30"),
        scenario_reference=replace(s.scenario_reference, as_of_date=reference_date),
    )
    before = s.scenario_reference
    text = observation_summary(s)[2]
    assert ("歷史參考" in text) is historical
    fake = _FakeStreamlit()
    render_risk_summary(fake, s)
    assert len([1 for kind, value in fake.events if kind == "metric"]) == 3
    assert any("歷史參考" in str(value) for kind, value in fake.events) is historical
    assert s.scenario_reference == before
