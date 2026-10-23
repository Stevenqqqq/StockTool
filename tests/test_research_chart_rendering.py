import copy
import json

import pandas as pd
import pytest
from streamlit.elements.vega_charts import _marshall_chart_data
from streamlit.proto.VegaLiteChart_pb2 import VegaLiteChart

from stock_tool.dashboard.components.research_chart import (
    build_research_chart,
    research_chart_spec,
    research_chart_panels,
    render_research_chart,
)
from test_research_workspace import _FakeStreamlit


def frame(base=100):
    data = pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=600)})
    data["close"] = [base + i / 10 for i in range(len(data))]
    for field, offset in [("open", -1), ("high", 2), ("low", -2)]:
        data[field] = data.close + offset
    data["volume"] = 1000
    return data


def test_candles_volume_and_sma_survive_actual_streamlit_marshalling():
    data = frame()
    indicators = data[["date"]].copy()
    indicators["sma_20"] = data.close.rolling(20).mean()
    indicators["sma_60"] = data.close.rolling(60).mean()
    model = build_research_chart(data, indicators=indicators, period="1Y")
    spec = research_chart_spec(model)
    original = copy.deepcopy(spec)
    proto = VegaLiteChart()
    _marshall_chart_data(proto, spec)
    assert spec == original
    assert not proto.data.data and not proto.datasets
    assert len(spec["vconcat"]) == 2
    assert len(spec["vconcat"][0]["layer"]) == 4
    assert spec["vconcat"][1]["mark"]["type"] == "bar"
    assert spec["vconcat"][0]["data"]["values"][-1]["close"] == data.close.iloc[-1]
    json.dumps(spec, allow_nan=False)
    import altair as alt

    alt.VConcatChart.from_dict(spec, validate=True)


def test_rendered_panels_fit_width_keep_atomic_data_and_share_date_domain():
    import altair as alt

    data = frame()
    data.loc[0:10, "volume"] = float("nan")
    model = build_research_chart(data, indicators=None, period="MAX")
    panels = research_chart_panels(model)
    assert len(panels) == 2
    domains = []
    for panel in panels:
        original = copy.deepcopy(panel)
        proto = VegaLiteChart()
        _marshall_chart_data(proto, panel)
        assert panel == original
        assert not proto.data.data and not proto.datasets
        assert panel["autosize"] == {"type": "fit-x", "contains": "padding"}
        alt.LayerChart.from_dict(panel, validate=True)
        domains.append(panel["layer"][0]["encoding"]["x"]["scale"]["domain"])
    assert domains[0] == domains[1]
    fake = _FakeStreamlit()
    render_research_chart(fake, model)
    assert len([event for event in fake.events if event[0] == "vega"]) == 2


@pytest.mark.parametrize("period", ["6M", "1Y", "3Y", "MAX"])
def test_period_and_symbol_switch_are_fresh_nonmutating_snapshots(period):
    old, new = frame(100), frame(1000)
    before = new.copy(deep=True)
    research_chart_spec(build_research_chart(old, indicators=None, period="MAX"))
    model = build_research_chart(new, indicators=None, period=period)
    spec = research_chart_spec(model)
    rows = spec["vconcat"][0]["data"]["values"]
    assert len(rows) == len(model.data)
    assert all(r["close"] >= 1000 for r in rows)
    assert rows[-1]["date"].startswith(str(new.date.max().date()))
    pd.testing.assert_frame_equal(new, before)


def test_close_only_missing_volume_and_disabled_overlays_are_honest():
    data = frame()[["date", "close"]]
    indicators = data[["date"]].assign(sma_20=1, sma_60=2)
    model = build_research_chart(
        data, indicators=indicators, period="MAX", show_sma20=False, show_sma60=False
    )
    spec = research_chart_spec(model)
    assert len(spec["vconcat"]) == 1
    assert len(spec["vconcat"][0]["layer"]) == 1
    assert spec["vconcat"][0]["layer"][0]["mark"]["type"] == "line"
    assert len(model.limitations) == 2
    assert not any("sma_" in k for k in spec["vconcat"][0]["data"]["values"][0])


def test_nan_inf_and_partial_candles_do_not_create_fake_ohlc():
    data = frame()
    data.loc[0, "open"] = float("inf")
    indicators = data[["date"]].assign(sma_20=float("nan"), sma_60=float("inf"))
    model = build_research_chart(data, indicators=indicators, period="MAX")
    spec = research_chart_spec(model)
    assert spec["vconcat"][0]["data"]["values"][0]["open"] is None
    assert len(spec["vconcat"][0]["layer"]) == 3  # close fallback + valid candles
    json.dumps(spec, allow_nan=False)
    data["open"] = float("nan")
    spec = research_chart_spec(build_research_chart(data, indicators=None, period="MAX"))
    assert spec["vconcat"][0]["layer"][0]["mark"]["type"] == "line"


def test_unavailable_and_server_failure_keep_honest_table_fallback():
    empty = frame().assign(
        close=float("nan"), open=float("nan"), high=float("nan"), low=float("nan")
    )
    fake = _FakeStreamlit()
    render_research_chart(fake, build_research_chart(empty, indicators=None, period="MAX"))
    assert not any(kind == "vega" for kind, _ in fake.events)
    assert any(kind == "info" for kind, _ in fake.events)

    def fail(**kwargs):
        raise RuntimeError("synthetic transport failure")

    fake.vega_lite_chart = fail
    render_research_chart(fake, build_research_chart(frame(), indicators=None, period="MAX"))
    assert any(kind == "warning" for kind, _ in fake.events)
    assert any(kind == "dataframe" for kind, _ in fake.events)


def test_compact_chart_omits_volume_panel_but_retains_price():
    spec = research_chart_spec(
        build_research_chart(frame(), indicators=None, period="MAX"), compact=True
    )
    assert len(spec["vconcat"]) == 1
    assert spec["vconcat"][0]["height"] == 200
