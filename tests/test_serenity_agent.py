from __future__ import annotations

import pandas as pd

from stock_tool.company_research import CompanyResearchProfile
from stock_tool.research_reports import ResearchReportSummary
from stock_tool.serenity_agent import FORBIDDEN_PHRASES, run_serenity_agent, serenity_factors_frame
from stock_tool.stock_scoring import score_stock


def _prices(symbol: str = "MU") -> pd.DataFrame:
    rows = []
    for index in range(80):
        close = 90.0 + index * 0.5
        rows.append(
            {
                "date": f"2026-03-{(index % 28) + 1:02d}",
                "symbol": symbol,
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 1000 + index,
                "adjusted_close": close,
                "sma_20": close - 2,
                "sma_60": close - 5,
                "rsi_14": 56.0,
                "macd_dif": 2.0,
                "macd_dea": 1.0,
                "return_20": 0.12,
                "volatility_20": 0.018,
                "atr_14": 2.2,
            }
        )
    return pd.DataFrame(rows)


def _profile(symbol: str = "MU", *, focused: bool = True) -> CompanyResearchProfile:
    if focused:
        return CompanyResearchProfile(
            symbol=symbol,
            provider_symbol=symbol,
            company_name="Micron Technology",
            sector="科技",
            industry="記憶體",
            website="",
            main_business=("DRAM、NAND 與資料中心記憶體產品。",),
            technical_features=("HBM、高頻寬記憶體、先進封裝與良率是主要觀察點。",),
            linked_industries=("AI 記憶體", "資料中心"),
            current_applications=("AI 伺服器與資料中心。",),
            future_applications=("AI memory bandwidth 需求可能推升 HBM 供應鏈重要性。",),
            bottlenecks=("HBM 產能、良率、客戶認證與量產節奏需要驗證。",),
            additional_checks=("查證 HBM 營收占比與主要客戶。",),
            data_sources=("test",),
            limitations=("研究索引，不代表營收保證。",),
        )
    return CompanyResearchProfile(
        symbol=symbol,
        provider_symbol=symbol,
        company_name="Generic Company",
        sector="資料不足",
        industry="資料不足",
        website="",
        main_business=(),
        technical_features=(),
        linked_industries=(),
        current_applications=(),
        future_applications=(),
        bottlenecks=(),
        additional_checks=(),
        data_sources=(),
        limitations=("資料不足。",),
    )


def _report(symbol: str = "MU") -> ResearchReportSummary:
    return ResearchReportSummary(
        symbol=symbol,
        source_name="mu_hbm_report.pdf",
        title="Micron HBM and AI memory report",
        report_date="2026-06-01",
        extracted_characters=3200,
        key_points=("年報與法說提到資料中心 AI 記憶體需求。",),
        business_points=("公司供應 DRAM、NAND 與 HBM。",),
        technology_points=("HBM 需要先進封裝、良率爬坡與客戶認證。",),
        industry_links=("AI 伺服器與資料中心。",),
        catalysts=("量產、出貨、客戶認證與下一次財報是觀察時點。",),
        bottlenecks=("HBM 產能、良率與先進封裝供給是瓶頸。",),
        valuation_notes=("需要確認財務轉換。",),
        risk_notes=("價格循環、庫存與資本支出是風險。",),
        data_limitations=("摘要需回到原始報告確認。",),
    )


def test_serenity_agent_scores_chokepoint_profile_above_empty_profile() -> None:
    prices = _prices()
    stock_score = score_stock(symbol="MU", price_data=prices, technical_indicators=prices)

    focused = run_serenity_agent(
        symbol="MU",
        price_data=prices,
        technical_indicators=prices,
        company_profile=_profile(focused=True),
        stock_score_result=stock_score,
    )
    empty = run_serenity_agent(
        symbol="MU",
        price_data=prices,
        technical_indicators=prices,
        company_profile=_profile(focused=False),
        stock_score_result=stock_score,
    )

    assert focused.research_match_score > empty.research_match_score
    assert any("HBM" in item or "記憶體" in item for item in focused.chokepoint_map)


def test_serenity_agent_marks_missing_evidence_without_faking_certainty() -> None:
    result = run_serenity_agent(
        symbol="MU",
        price_data=_prices(),
        company_profile=_profile(focused=True),
    )

    assert result.evidence_gaps
    assert "一手證據" in " ".join(result.evidence_gaps)
    assert "買賣建議" in result.disclaimer


def test_serenity_agent_uses_report_summary_as_evidence() -> None:
    prices = _prices()
    without_report = run_serenity_agent(
        symbol="MU",
        price_data=prices,
        technical_indicators=prices,
        company_profile=_profile(focused=True),
    )
    with_report = run_serenity_agent(
        symbol="MU",
        price_data=prices,
        technical_indicators=prices,
        company_profile=_profile(focused=True),
        research_reports=(_report(),),
    )
    evidence_without = next(factor for factor in without_report.factors if factor.name == "證據品質")
    evidence_with = next(factor for factor in with_report.factors if factor.name == "證據品質")

    assert evidence_with.score > evidence_without.score


def test_serenity_agent_output_has_no_forbidden_language() -> None:
    result = run_serenity_agent(
        symbol="MU",
        price_data=_prices(),
        company_profile=_profile(focused=True),
        research_reports=(_report(),),
    )
    frame = serenity_factors_frame(result)
    text = " ".join(
        [
            result.thesis,
            result.disclaimer,
            " ".join(result.risks),
            " ".join(result.next_questions),
            frame.to_string(),
        ]
    )

    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in text
    assert set(frame.columns) == {"factor", "score", "evidence_level", "explanation", "gaps"}
