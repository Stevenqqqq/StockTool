from dataclasses import replace

import pandas as pd
import pytest

from stock_tool.application.breakout_observation import observe_breakout
from stock_tool.application.research_snapshot import (
    ResearchSourceMetadata,
    ResearchWorkspaceService,
)
from stock_tool.dashboard.components.breakout_observation import render_breakout_observation
from stock_tool.domain.models import Market, Symbol


def snapshot(code="3006", market="TWSE", *, volume=200.0, breakout=True):
    f = pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=40)})
    f["close"] = [100 + i * 0.1 for i in range(len(f))]
    f["open"] = f.close - 0.1
    f["high"] = f.close + 1
    f["low"] = f.open - 1
    f["volume"] = 100.0
    if breakout:
        f.loc[f.index[-1], ["open", "close", "high", "low"]] = [104, 106, 107, 103]
    f.loc[f.index[-1], "volume"] = volume
    f["symbol"], f["market"] = code, market
    return ResearchWorkspaceService().build(
        symbol=Symbol(code, Market.parse(market)),
        price_data=f,
        indicators=None,
        fundamental_results=None,
        stock_score=None,
        company_profile=None,
        scenario_reference=None,
        source_metadata=ResearchSourceMetadata(
            "synthetic", code, market, "local_file", "2025-04-01T00:00:00Z", None, len(f)
        ),
    )


@pytest.mark.parametrize("code", ["3006", "6669", "6933"])
def test_breakout_defaults_and_inputs_unchanged(code):
    s = snapshot(code)
    before = s.price_history.copy(deep=True)
    r = observe_breakout(s)
    assert r.status == "突破・確認條件齊備"
    assert r.reference == pytest.approx(104.8)
    assert r.distance == pytest.approx(106 / 104.8 - 1)
    assert r.volume_ratio == 2
    assert len(r.events) == 1
    pd.testing.assert_frame_equal(before, s.price_history)


@pytest.mark.parametrize("volume", [100, 150])
def test_volume_strict_threshold_excludes_today(volume):
    r = observe_breakout(snapshot(volume=volume))
    assert r.status == "價格突破・確認條件未齊"
    assert "量能 未達標" in r.conditions[0]


def test_no_breakout_and_future_never_change_history():
    s = snapshot(breakout=False)
    assert observe_breakout(s).status == "尚未突破"
    tail = s.price_history.tail(1).copy()
    tail["date"] += pd.Timedelta(days=30)
    tail["close"], tail["volume"] = 10000, 1e9
    assert observe_breakout(
        replace(s, price_history=pd.concat([s.price_history, tail]))
    ) == observe_breakout(s)


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
def test_missing_ohlcv_local_unavailable(field):
    s = snapshot()
    f = s.price_history.copy()
    f.loc[f.index[-5], field] = float("nan")
    assert observe_breakout(replace(s, price_history=f)).status == "資料不足"
    assert s.price is not None


def test_duplicate_identity_and_discontinuity():
    s = snapshot()
    for f in [
        pd.concat([s.price_history, s.price_history.tail(1)]),
        s.price_history.assign(market="US"),
        s.price_history.assign(open=s.price_history.open * 0.5),
    ]:
        assert observe_breakout(replace(s, price_history=f)).status == "資料不足"
    f = s.price_history.copy()
    f["stock_splits"] = 0
    f.loc[f.index[-10], "stock_splits"] = 2
    assert "公司行動" in observe_breakout(replace(s, price_history=f)).reason


@pytest.mark.parametrize("market,offset", [("TWSE", -8), ("TPEX", -8), ("US", 5)])
def test_utc_dates_match_exchange_local_and_do_not_mutate(market, offset):
    s = snapshot(market=market)
    f = s.price_history.copy()
    f["date"] = f.date.dt.tz_localize("UTC") + pd.Timedelta(hours=offset)
    before = f.copy(deep=True)
    assert observe_breakout(replace(s, price_history=f)) == observe_breakout(s)
    pd.testing.assert_frame_equal(f, before)


def test_intraday_cache_unknown_completion_and_missing_provider_fail_closed():
    s = snapshot()
    end = s.price.last_data_date
    for stamp in [None, f"{end}T02:20:00Z", "2099-01-01T00:00:00Z"]:
        source = replace(s.source_metadata, fetched_at=stamp)
        assert observe_breakout(replace(s, source_metadata=source)).status == "資料不足"
    f = s.price_history.copy()
    f["fetched_at"] = None
    assert observe_breakout(replace(s, price_history=f)).status == "資料不足"
    assert (
        observe_breakout(
            replace(s, source_metadata=replace(s.source_metadata, provider=None))
        ).status
        == "資料不足"
    )


def test_short_missing_columns_bad_dates_and_ohlc():
    s = snapshot()
    for f in [
        s.price_history.tail(24),
        s.price_history.drop(columns="high"),
        s.price_history.assign(date="bad"),
        s.price_history.assign(low=10000),
    ]:
        assert observe_breakout(replace(s, price_history=f)).status == "資料不足"


def test_visible_explanation_does_not_promise_strategy_results():
    class UI:
        def __init__(self):
            self.text = []

        def write(self, value):
            self.text.append(value)

        caption = subheader = write

    ui = UI()
    render_breakout_observation(ui, snapshot())
    text = " ".join(ui.text)
    assert "104.80" in text and "最近" in text
    assert "公司行動" in text and "正式 Scenario Research 仍未開放" in text
    assert "勝率" not in text
