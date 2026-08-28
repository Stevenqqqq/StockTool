"""Local deterministic portfolio brief with no external AI or trading advice."""

from __future__ import annotations

from dataclasses import dataclass

from stock_tool.domain.models import MissingData
from stock_tool.portfolio_health import PortfolioHealthResult


@dataclass(frozen=True, slots=True)
class PortfolioResearchBrief:
    """User-readable summary derived solely from a health-result snapshot."""

    overall_summary: str
    strengths: tuple[str, ...]
    top_risks: tuple[str, ...]
    concentration_findings: tuple[str, ...]
    currency_findings: tuple[str, ...]
    data_quality_findings: tuple[str, ...]
    counterarguments: tuple[str, ...]
    next_checks: tuple[str, ...]
    missing_data: tuple[MissingData, ...]
    evidence: tuple[dict[str, object], ...]
    disclaimer: str


def build_portfolio_research_brief(result: PortfolioHealthResult) -> PortfolioResearchBrief:
    """Create a Traditional-Chinese local rules brief without network calls."""

    component_map = {component.name: component for component in result.components}
    strengths = tuple(
        reason
        for component in result.components
        if component.score is not None and component.score >= 70
        for reason in component.reasons
    ) or ("目前沒有足夠資料可確認明確正面因素。",)
    risks = tuple(alert.message for alert in result.alerts if alert.severity == "warning") or (
        "未偵測到可量化的重大風險警示；這不代表風險不存在。",
    )
    concentration = component_map.get("diversification")
    concentration_findings = concentration.reasons if concentration else ("集中度資料不足。",)
    currency_findings = tuple(
        warning for warning in result.warnings if "FX" in warning or "currency" in warning.lower()
    ) or ("匯率資訊依本次估值資料判讀；未使用外部 AI 或即時匯率推論。",)
    data_findings = (
        f"資料涵蓋率：{result.coverage.coverage_pct:.1%}。",
        *(f"缺少：{item.field}（{item.state.value}）。" for item in result.coverage.missing_data),
        *(
            f"研究結果缺少：{item.field}（{item.state.value}）。"
            for item in result.missing_data
            if item not in result.coverage.missing_data
        ),
    )
    if result.overall_score is None:
        summary = "持股研究資料不足，未提供整體健康度分數。"
    else:
        summary = f"持股健康度為 {result.overall_score:.2f}/100，資料涵蓋率為 {result.coverage.coverage_pct:.1%}。"
    counterarguments = (
        "健康度分數僅整理已提供的價格、匯率與研究資料，無法涵蓋所有公司、產業與市場風險。",
        "未實現損益不會直接改變健康度分數，避免將短期價格變動誤解為研究品質。",
    )
    next_checks = (
        "確認缺少的價格、匯率、基本面與技術指標資料來源及更新時間。",
        "針對集中度或匯率曝險較高的部位，檢視個別研究證據與風險情境。",
    )
    return PortfolioResearchBrief(
        overall_summary=summary,
        strengths=strengths,
        top_risks=risks,
        concentration_findings=concentration_findings,
        currency_findings=currency_findings,
        data_quality_findings=tuple(data_findings),
        counterarguments=counterarguments,
        next_checks=next_checks,
        missing_data=result.missing_data,
        evidence=result.evidence,
        disclaimer="本功能為本機規則式研究摘要，不會將持股資料傳送到外部 AI；內容不是投資建議。",
    )
