from __future__ import annotations

from stock_tool.research_reports import (
    build_public_report_search_links,
    research_report_summaries_to_frame,
    summarize_research_report,
)


def test_summarize_research_report_extracts_key_sections_without_forbidden_language() -> None:
    text = """
    矽力-KY 研究報告
    2026年6月28日
    公司主要產品為電源管理 IC 與 PMIC，營收來自工控、車用、消費與資料中心市場。
    技術重點在高效率功率轉換、低功耗設計、車規可靠度與封裝散熱。
    AI 伺服器與電動車電源需求帶來成長動能，新品導入與庫存回補可能成為催化因素。
    主要瓶頸包含中國同業競爭、毛利率壓力、庫存調整與需求疲弱。
    估值需要觀察本益比、EPS 修正與目標價假設。
    風險包括景氣循環、客戶集中、匯率與地緣政治。
    不應出現保證獲利或必漲等說法。
    """

    result = summarize_research_report(text, symbol="6415", source_name="矽力-KY 分析.pdf")

    assert result.symbol == "6415"
    assert result.report_date == "2026年6月28日"
    assert any("電源管理" in item for item in result.business_points)
    assert any("高效率" in item or "封裝散熱" in item for item in result.technology_points)
    assert any("AI" in item or "電動車" in item for item in result.industry_links)
    assert any("毛利率" in item or "競爭" in item for item in result.bottlenecks)
    combined = " ".join(
        [
            *result.key_points,
            *result.business_points,
            *result.technology_points,
            *result.risk_notes,
        ]
    )
    assert "保證獲利" not in combined
    assert "必漲" not in combined


def test_research_report_summaries_to_frame_contains_dashboard_columns() -> None:
    summary = summarize_research_report(
        "公司主要產品為電源管理 IC。技術重點在高效率功率轉換。風險包括庫存調整。",
        symbol="6415",
        source_name="report.pdf",
    )

    frame = research_report_summaries_to_frame([summary])

    assert list(frame["symbol"]) == ["6415"]
    assert "technology_points" in frame.columns
    assert "risk_notes" in frame.columns


def test_public_report_search_links_are_non_scraping_links() -> None:
    links = build_public_report_search_links("6415", "矽力-KY")

    assert "Google PDF 搜尋" in links
    assert "公開資訊觀測站" in links
    assert links["Google PDF 搜尋"].startswith("https://www.google.com/search")
