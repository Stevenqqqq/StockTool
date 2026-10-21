"""First-screen findings reuse existing evidence without inventing conclusions."""

from dataclasses import replace

import pandas as pd
import pytest

from stock_tool.application.breakout_observation import observe_breakout
from stock_tool.company_dossier import CompanyFact
from stock_tool.dashboard.components.research_header import render_research_header
from test_breakout_observation import snapshot
from test_research_header_completeness import _FakeStreamlit, _dossier, _profile


def visible(s):
    fake = _FakeStreamlit()
    render_research_header(fake, s)
    cut = next(i for i, e in enumerate(fake.events) if e[0] == "expander")
    return fake, "\n".join(str(v) for _, v in fake.events[:cut])


@pytest.mark.parametrize("code", ["3006", "6669", "6933"])
@pytest.mark.parametrize("volume", [100, 150, 200])
def test_focus_reuses_existing_pattern_conditions_and_keeps_inputs(code, volume):
    s = snapshot(code, volume=volume)
    before = s.price_history.copy(deep=True)
    expected = observe_breakout(s)
    fake, text = visible(s)
    for heading in ("目前觀察", "支持與反向證據", "優先待查"):
        assert heading in text
    assert expected.status in text
    for condition in expected.conditions:
        assert condition in text
    columns = [str(v) for kind, v in fake.events if kind == "markdown"]
    positive = next(t for t in columns if t.startswith("**已符合的條件**"))
    negative = next(t for t in columns if t.startswith("**尚未符合的條件**"))
    assert ("量能 達標" in positive) == (volume > 150)
    assert ("量能 未達標" in negative) == (volume <= 150)
    assert "2025-02-25" in text  # Actual final completed date from this fixture.
    assert s.source_metadata.fetched_at in text
    pd.testing.assert_frame_equal(before, s.price_history)


@pytest.mark.parametrize("source_field", ["provider", "source_type", "row_provider"])
def test_synthetic_prices_never_look_like_real_quotes(source_field):
    s = snapshot()
    source = replace(s.source_metadata, provider="yfinance", source_type="online")
    frame = s.price_history.copy()
    if source_field == "row_provider":
        frame["provider"] = "synthetic"
    else:
        source = replace(
            source, **{source_field: "synthetic" if source_field == "provider" else "sample"}
        )
    s = replace(s, source_metadata=source, price_history=frame)
    _, text = visible(s)
    assert "模擬資料／Synthetic" in text
    assert "模擬收盤價（測試資料）" in text
    assert "最新可用收盤價" not in text


@pytest.mark.parametrize("gap", ["high", "provider", "price"])
def test_pattern_gap_is_unavailable_not_negative_evidence(gap):
    s = snapshot()
    if gap == "high":
        s = replace(s, price_history=s.price_history.drop(columns="high"))
    elif gap == "provider":
        s = replace(s, source_metadata=replace(s.source_metadata, provider=None))
    else:
        s = replace(s, price=None, price_history=None)
    _, text = visible(s)
    assert "尚無可判讀證據" in text
    assert "缺資料也不是反向證據" in text
    assert "量能 達標" not in text
    if gap != "price":
        assert "106.00" in text


def test_company_evidence_dates_risk_and_question_are_not_price_dates():
    s = snapshot()
    facts = (
        CompanyFact(
            "產品與技術",
            "DDR4",
            "DDR4",
            "產品列示",
            "DDR4 DRAM",
            "https://example.org/product",
            "產品",
            "",
            "2026-01-02",
        ),
        CompanyFact(
            "公司揭露的風險",
            "庫存",
            "庫存增加可能影響營運。",
            "原文",
            "庫存",
            "https://example.org/risk",
            "風險",
            "2026-01-01",
            "2026-01-02",
        ),
    )
    dossier = replace(
        _dossier(gaps=("財報缺漏不可隱藏。",), state="stale"),
        symbol="3006",
        market="TWSE",
        facts=facts,
        questions=("DDR4 收入占比是否已公布？",),
    )
    profile = replace(_profile(dossier=dossier), symbol="3006")
    fake, text = visible(replace(s, company_profile=profile))
    assert "DDR4" in text and "日期未知" in text
    assert "發布：2026-01-01" in text
    assert "庫存增加可能影響營運。" in text
    assert "DDR4 收入占比是否已公布？" in text
    assert "財報缺漏不可隱藏" in text and "資料可能過期" in text
    assert ("link", ("核對這項風險來源", "https://example.org/risk")) in fake.events
    _, mismatched = visible(
        replace(s, company_profile=replace(profile, dossier=replace(dossier, market="TPEX")))
    )
    assert "DDR4 收入占比是否已公布？" not in mismatched
    assert "公司風險原文" not in mismatched


def test_yahoo_limits_stay_visible_and_future_rows_do_not_change_focus():
    s = snapshot()
    s = replace(s, source_metadata=replace(s.source_metadata, provider="yfinance"))
    _, before = visible(s)
    tail = s.price_history.tail(1).assign(date=pd.Timestamp("2025-04-30"), close=9999)
    _, after = visible(replace(s, price_history=pd.concat([s.price_history, tail])))
    assert after == before
    assert "可能落後交易所" in before
    assert "量能口徑未必等同交易所總成交量" in before
    assert "Adj Close" in before
