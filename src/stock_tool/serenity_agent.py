"""Local Serenity-style chokepoint research agent.

The agent converts the installed Serenity chokepoint-investing framework into a
deterministic, testable local research layer. It does not call an external LLM,
does not place orders, and does not produce buy/sell instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Sequence

import pandas as pd

from stock_tool.company_research import CompanyResearchProfile
from stock_tool.data.repositories import ConceptRelationRecord
from stock_tool.research_reports import ResearchReportSummary

EvidenceLevel = Literal["低", "中", "高"]

FORBIDDEN_PHRASES = ("保證獲利", "必漲", "穩賺", "歐印", "一定買進", "一定賣出")
DISCLAIMER = (
    "Serenity 小 Agent 只做供應鏈瓶頸研究整理，不提供個人化投資建議；"
    "也不提供買賣建議。社群或第三方摘要只能作為線索，仍需用公司公告、年報、法說與財報交叉驗證。"
)

CHOKEPOINT_KEYWORDS = {
    "瓶頸": ("瓶頸", "稀缺", "供給受限", "供應鏈", "不可替代", "替代品", "寡占", "壟斷"),
    "製造門檻": ("良率", "認證", "量產", "產能", "製程", "設備", "材料", "交期"),
    "先進封裝": ("先進封裝", "封裝", "CoWoS", "chiplet", "TGV", "玻璃基板", "載板", "ABF"),
    "光通訊": ("CPO", "LPO", "LRO", "光通訊", "矽光子", "laser", "雷射", "InP", "SOI"),
    "記憶體": ("HBM", "DRAM", "NAND", "記憶體", "頻寬", "SSD"),
    "電源": ("SiC", "GaN", "800V", "電源", "功率", "電源管理", "PMIC"),
    "機器人": ("人形機器人", "減速器", "伺服", "馬達", "感測", "工業自動化"),
}
ARCHITECTURE_KEYWORDS = {
    "AI 資料中心": ("AI 伺服器", "資料中心", "hyperscaler", "GPU", "ASIC", "HPC"),
    "高速互連": ("800G", "1.6T", "3.2T", "CPO", "LPO", "LRO", "光引擎", "光纖"),
    "AI 記憶體": ("HBM", "高頻寬記憶體", "AI memory", "記憶體頻寬"),
    "電力架構": ("800V DC", "SiC", "GaN", "高功率", "資料中心電力"),
    "自動化": ("人形機器人", "機器人", "自動化", "減速器", "伺服控制"),
}
PRIMARY_EVIDENCE_TERMS = (
    "年報",
    "法說",
    "財報",
    "公司公告",
    "annual report",
    "10-k",
    "20-f",
    "earnings call",
    "transcript",
)
VALIDATION_TERMS = ("客戶", "訂單", "合約", "設計導入", "認證", "量產", "出貨", "營收")


@dataclass(frozen=True)
class SerenityFactor:
    """One scored research factor in the local Serenity agent output."""

    name: str
    score: float
    evidence_level: EvidenceLevel
    explanation: str
    gaps: tuple[str, ...] = ()


@dataclass(frozen=True)
class SerenityAgentResult:
    """Structured Serenity-style research summary for one stock."""

    symbol: str
    research_match_score: float
    confidence_label: str
    thesis: str
    factors: tuple[SerenityFactor, ...]
    chokepoint_map: tuple[str, ...]
    catalysts: tuple[str, ...]
    invalidation_tests: tuple[str, ...]
    risks: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    next_questions: tuple[str, ...]
    disclaimer: str = DISCLAIMER


def run_serenity_agent(
    *,
    symbol: str,
    market: str | None = None,
    price_data: pd.DataFrame,
    technical_indicators: pd.DataFrame | None = None,
    company_profile: CompanyResearchProfile | None = None,
    research_reports: Sequence[ResearchReportSummary] | None = None,
    stock_score_result: Any | None = None,
    concept_relations: Sequence[ConceptRelationRecord] = (),
) -> SerenityAgentResult:
    """Run a deterministic chokepoint research check for one stock.

    The output is a research checklist and thesis quality assessment. It uses
    only currently loaded local data, company profile text, and user-provided
    report summaries. Missing filings, customer confirmations, dilution data, or
    market-share evidence are explicitly listed instead of being inferred.
    """

    symbol_text = str(symbol).strip().upper()
    reports = tuple(research_reports or ())
    relation_text = " ".join(
        f"{relation.concept_key} {relation.relation_type} {relation.evidence}"
        for relation in concept_relations
        if relation.identity.symbol == str(symbol).strip().upper()
        and (market is None or relation.identity.market == str(market).strip().upper())
        and relation.evidence
    )
    text_blob = _build_text_blob(company_profile, reports) + " " + relation_text
    symbol_prices = _filter_symbol(price_data, symbol_text)
    symbol_indicators = _filter_symbol(
        technical_indicators if technical_indicators is not None else price_data,
        symbol_text,
    )

    chokepoint_score, chokepoint_notes, chokepoint_gaps = _score_keyword_groups(
        text_blob,
        CHOKEPOINT_KEYWORDS,
        missing_note="尚未看到明確供應鏈瓶頸、材料、良率、認證或產能描述。",
    )
    architecture_score, architecture_notes, architecture_gaps = _score_keyword_groups(
        text_blob,
        ARCHITECTURE_KEYWORDS,
        missing_note="尚未看到明確架構遷移線索，例如 AI 資料中心、CPO、HBM、800V 或機器人供應鏈。",
    )
    evidence_factor = _score_evidence(text_blob, company_profile, reports)
    catalyst_factor = _score_catalysts(text_blob, symbol_indicators)
    financial_factor = _score_financial_translation(stock_score_result)
    risk_factor = _score_risk_and_reflexivity(symbol_prices, symbol_indicators, stock_score_result)

    factors = (
        SerenityFactor(
            "供應鏈瓶頸強度",
            chokepoint_score,
            _evidence_label(chokepoint_score),
            "；".join(chokepoint_notes),
            chokepoint_gaps,
        ),
        SerenityFactor(
            "架構遷移關聯",
            architecture_score,
            _evidence_label(architecture_score),
            "；".join(architecture_notes),
            architecture_gaps,
        ),
        evidence_factor,
        catalyst_factor,
        financial_factor,
        risk_factor,
    )
    score = round(sum(factor.score for factor in factors) / len(factors), 2)
    confidence = _confidence_label(score, factors)
    gaps = _dedupe(item for factor in factors for item in factor.gaps)

    thesis = _build_thesis(symbol_text, company_profile, chokepoint_notes, architecture_notes, gaps)
    return SerenityAgentResult(
        symbol=symbol_text,
        research_match_score=score,
        confidence_label=confidence,
        thesis=_sanitize(thesis),
        factors=tuple(_sanitize_factor(factor) for factor in factors),
        chokepoint_map=_sanitize_items(_build_chokepoint_map(chokepoint_notes, company_profile)),
        catalysts=_sanitize_items(_build_catalysts(catalyst_factor, reports)),
        invalidation_tests=_sanitize_items(_build_invalidation_tests(company_profile)),
        risks=_sanitize_items(_build_risks(risk_factor, financial_factor)),
        evidence_gaps=_sanitize_items(
            gaps or ("目前缺少足夠一手證據，請補公司公告、年報、法說或產業報告。",)
        ),
        next_questions=_sanitize_items(_build_next_questions(company_profile, gaps)),
    )


def serenity_factors_frame(result: SerenityAgentResult) -> pd.DataFrame:
    """Convert Serenity factors into a dashboard-friendly DataFrame."""

    return pd.DataFrame(
        [
            {
                "factor": factor.name,
                "score": round(factor.score, 2),
                "evidence_level": factor.evidence_level,
                "explanation": factor.explanation,
                "gaps": "；".join(factor.gaps),
            }
            for factor in result.factors
        ]
    )


def _build_text_blob(
    profile: CompanyResearchProfile | None,
    reports: Sequence[ResearchReportSummary],
) -> str:
    parts: list[str] = []
    if profile is not None:
        parts.extend(
            [
                profile.company_name,
                profile.sector,
                profile.industry,
                *profile.main_business,
                *profile.technical_features,
                *profile.linked_industries,
                *profile.current_applications,
                *profile.future_applications,
                *profile.bottlenecks,
                *profile.additional_checks,
                *profile.data_sources,
                *profile.limitations,
            ]
        )
    for report in reports:
        parts.extend(
            [
                report.title,
                report.source_name,
                *report.key_points,
                *report.business_points,
                *report.technology_points,
                *report.industry_links,
                *report.catalysts,
                *report.bottlenecks,
                *report.valuation_notes,
                *report.risk_notes,
                *report.data_limitations,
            ]
        )
    return " ".join(str(part) for part in parts if str(part).strip())


def _score_keyword_groups(
    text: str,
    groups: dict[str, tuple[str, ...]],
    *,
    missing_note: str,
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    lower = text.lower()
    matched: list[str] = []
    for group, keywords in groups.items():
        if any(keyword.lower() in lower for keyword in keywords):
            matched.append(group)
    if not matched:
        return 20.0, ("未偵測到明確匹配題材。",), (missing_note,)
    score = min(35.0 + len(matched) * 12.0, 90.0)
    if len(matched) == 1:
        score -= 8.0
    notes = tuple(f"偵測到「{item}」相關線索" for item in matched[:5])
    gaps: list[str] = []
    if len(matched) < 2:
        gaps.append("題材線索偏單一，需要確認公司實際產品層級與營收占比。")
    if not any(term.lower() in lower for term in VALIDATION_TERMS):
        gaps.append("缺少客戶、訂單、認證、量產或營收轉換證據。")
    return round(score, 2), notes, tuple(gaps)


def _score_evidence(
    text: str,
    profile: CompanyResearchProfile | None,
    reports: Sequence[ResearchReportSummary],
) -> SerenityFactor:
    lower = text.lower()
    score = 20.0
    notes: list[str] = []
    gaps: list[str] = []

    if profile is not None and profile.is_available:
        score += 15.0
        notes.append("已有公司業務與產業脈絡資料。")
    else:
        gaps.append("公司業務資料不足，需要先取得公司基本資料。")

    if reports:
        extracted = sum(max(report.extracted_characters, 0) for report in reports)
        score += 10.0 if extracted < 2_000 else 20.0
        notes.append(f"已納入 {len(reports)} 份研究報告摘要。")
    else:
        gaps.append("尚未匯入研究報告或公司文件摘要。")

    if any(term in lower for term in PRIMARY_EVIDENCE_TERMS):
        score += 15.0
        notes.append("文字中出現年報、法說、財報或類似一手文件線索。")
    else:
        gaps.append("尚未明確看到年報、法說、財報或公司公告等一手證據。")

    if any(term.lower() in lower for term in VALIDATION_TERMS):
        score += 10.0
        notes.append("文字中有客戶、訂單、認證、量產或出貨線索。")
    else:
        gaps.append("缺少客戶驗證、設計導入、量產或訂單證據。")

    score = min(score, 90.0)
    return SerenityFactor(
        "證據品質",
        round(score, 2),
        _evidence_label(score),
        "；".join(notes) if notes else "證據仍不足。",
        tuple(gaps),
    )


def _score_catalysts(text: str, indicators: pd.DataFrame) -> SerenityFactor:
    lower = text.lower()
    catalyst_terms = (
        "催化",
        "量產",
        "認證",
        "出貨",
        "訂單",
        "法說",
        "財報",
        "新品",
        "擴產",
        "客戶",
    )
    matched = [term for term in catalyst_terms if term in lower]
    score = min(25.0 + len(matched) * 8.0, 78.0)
    notes: list[str] = []
    gaps: list[str] = []
    if matched:
        notes.append("已看到可能催化線索：" + "、".join(matched[:5]))
    else:
        gaps.append("缺少明確時間表，例如量產、認證、客戶導入、法說或財報事件。")

    latest = _latest_row(indicators)
    if latest is not None:
        close = _number(latest.get("close"))
        sma20 = _number(latest.get("sma_20"))
        sma60 = _number(latest.get("sma_60"))
        return20 = _number(latest.get("return_20"))
        if close is not None and sma20 is not None and close >= sma20:
            score += 6.0
            notes.append("股價位於 20 日均線上方，市場關注度可能已提高。")
        if close is not None and sma60 is not None and close >= sma60:
            score += 6.0
            notes.append("股價位於 60 日均線上方，可作為價格反應觀察。")
        if return20 is not None and return20 > 0.15:
            notes.append("近 20 日漲幅偏大，需要注意題材擁擠與追價風險。")
    else:
        gaps.append("缺少技術資料，無法觀察股價反應階段。")

    score = min(score, 90.0)
    return SerenityFactor(
        "催化與股價反應",
        round(score, 2),
        _evidence_label(score),
        "；".join(notes) if notes else "尚未看到明確催化。",
        tuple(gaps),
    )


def _score_financial_translation(stock_score_result: Any | None) -> SerenityFactor:
    if stock_score_result is None:
        return SerenityFactor(
            "財務轉換品質",
            25.0,
            "低",
            "尚未接上綜合評分結果。",
            ("缺少基本面、估值面、現金流與財務安全分數。",),
        )

    coverage = float(getattr(stock_score_result, "coverage", 0.0) or 0.0)
    available = _number(getattr(stock_score_result, "available_score", None))
    total = _number(getattr(stock_score_result, "total_score", None))
    missing = tuple(getattr(stock_score_result, "missing_data", ()) or ())
    base = total if total is not None else available
    score = 25.0 if base is None else min(max(float(base) * 0.75, 20.0), 80.0)
    if coverage >= 1.0:
        score += 10.0
    elif coverage >= 0.5:
        score += 4.0

    notes = [f"目前可用資料覆蓋率為 {coverage * 100:.2f}%。"]
    if base is not None:
        notes.append(f"綜合評分可用分數為 {base:.2f}/100，僅作財務轉換參考。")
    gaps = []
    if missing:
        gaps.append("缺少資料：" + "、".join(str(item) for item in missing))
    if "fundamental_scores" in missing or "valuation_score" in missing:
        gaps.append("缺少基本面或估值資料時，不應把題材直接轉成財務結論。")

    return SerenityFactor(
        "財務轉換品質",
        round(min(score, 90.0), 2),
        _evidence_label(score),
        "；".join(notes),
        tuple(gaps),
    )


def _score_risk_and_reflexivity(
    prices: pd.DataFrame,
    indicators: pd.DataFrame,
    stock_score_result: Any | None,
) -> SerenityFactor:
    latest = _latest_row(indicators if not indicators.empty else prices)
    notes: list[str] = []
    gaps: list[str] = []
    score = 60.0

    if latest is not None:
        vol20 = _number(latest.get("volatility_20"))
        return20 = _number(latest.get("return_20"))
        atr = _number(latest.get("atr_14"))
        close = _number(latest.get("close"))
        if vol20 is not None:
            if vol20 > 0.05:
                score -= 18.0
                notes.append(f"20 日波動率約 {vol20 * 100:.2f}%，題材波動偏高。")
            else:
                score += 6.0
                notes.append(f"20 日波動率約 {vol20 * 100:.2f}%，未見極端波動。")
        else:
            gaps.append("缺少 20 日波動率。")
        if return20 is not None and return20 > 0.25:
            score -= 12.0
            notes.append("近 20 日漲幅偏大，需檢查是否已進入擁擠交易。")
        if atr is not None and close and close > 0:
            atr_pct = atr / close
            if atr_pct > 0.07:
                score -= 8.0
                notes.append(f"ATR/收盤價約 {atr_pct * 100:.2f}%，價格跳動風險偏高。")
    else:
        gaps.append("缺少價格資料，無法估計波動、回撤與題材擁擠。")

    risk_score = (
        _number(getattr(stock_score_result, "risk_score", None)) if stock_score_result else None
    )
    if risk_score is not None:
        score += (risk_score - 10.0) * 1.5
        notes.append(f"既有風險面分數為 {risk_score:.2f}/20。")
    else:
        gaps.append("缺少既有風險面分數。")

    gaps.append("目前未自動檢查股本膨脹、ATM、可轉債、認股權證、放空比例與流動性。")
    score = min(max(score, 15.0), 88.0)
    return SerenityFactor(
        "風險與反身性",
        round(score, 2),
        _evidence_label(score),
        "；".join(notes) if notes else "風險資料不足。",
        tuple(gaps),
    )


def _build_thesis(
    symbol: str,
    profile: CompanyResearchProfile | None,
    chokepoint_notes: Sequence[str],
    architecture_notes: Sequence[str],
    gaps: Sequence[str],
) -> str:
    name = profile.company_name if profile and profile.company_name else symbol
    industry = profile.industry if profile and profile.industry else "資料不足產業"
    if chokepoint_notes and "未偵測" not in chokepoint_notes[0]:
        layer = "、".join(
            note.replace("偵測到「", "").replace("」相關線索", "") for note in chokepoint_notes[:3]
        )
        driver = "、".join(
            note.replace("偵測到「", "").replace("」相關線索", "")
            for note in architecture_notes[:3]
        )
        driver = driver if driver and "未偵測" not in driver else "下游需求"
        return (
            f"{name}（{symbol}）在「{industry}」脈絡下，可能值得用 {layer} 的供應鏈瓶頸角度檢查；"
            f"目前看到的架構遷移線索是 {driver}。這只是研究假設，仍需補齊一手證據與財務轉換。"
        )
    return (
        f"{name}（{symbol}）目前尚未形成明確供應鏈瓶頸假設；"
        f"優先補資料：{gaps[0] if gaps else '公司一手文件、客戶驗證與財務轉換資料'}。"
    )


def _build_chokepoint_map(
    chokepoint_notes: Sequence[str],
    profile: CompanyResearchProfile | None,
) -> tuple[str, ...]:
    rows = [
        "下游需求：先確認 AI、資料中心、車用、機器人、電力或其他實際需求是否拉動該公司產品。",
        "候選層級：區分材料、基板、製程、封裝、測試、模組、系統整合，不要把整個題材混成同一層。",
    ]
    if profile is not None and profile.technical_features:
        rows.append("公司技術線索：" + "；".join(profile.technical_features[:3]))
    if chokepoint_notes and "未偵測" not in chokepoint_notes[0]:
        rows.append("目前匹配層級：" + "；".join(chokepoint_notes[:4]))
    rows.append("需驗證：市場占有率、替代品、客戶認證週期、產能與良率是否真的構成瓶頸。")
    return tuple(rows)


def _build_catalysts(
    catalyst_factor: SerenityFactor,
    reports: Sequence[ResearchReportSummary],
) -> tuple[str, ...]:
    rows = [catalyst_factor.explanation]
    for report in reports[-2:]:
        rows.extend(report.catalysts[:2])
    rows.append("建議追蹤：下一次財報 / 法說、客戶量產時程、產能擴充、產業展會與公司公告。")
    return _dedupe(rows)


def _build_invalidation_tests(profile: CompanyResearchProfile | None) -> tuple[str, ...]:
    tests = [
        "若替代供應商快速通過認證，瓶頸假設需要下修。",
        "若量產、出貨或客戶導入持續延後，需要重新評估題材時程。",
        "若毛利率、現金流或股本稀釋惡化，代表供應鏈價值未必能轉成股東價值。",
        "若股價只因社群熱度上漲、但一手資料沒有改善，不能把價格反應當作基本面驗證。",
    ]
    if profile is not None and profile.bottlenecks:
        tests.append("公司既有瓶頸：" + "；".join(profile.bottlenecks[:2]))
    return tuple(tests)


def _build_risks(risk_factor: SerenityFactor, financial_factor: SerenityFactor) -> tuple[str, ...]:
    rows = [
        "題材研究可能有 survivorship bias 與熱門題材選樣偏誤。",
        "缺少完整歷史 universe、下市資料與股本變化時，回測或評分可能偏樂觀。",
        "供應鏈瓶頸不等於公司一定能取得高毛利或高現金流。",
        risk_factor.explanation,
        financial_factor.explanation,
    ]
    return tuple(item for item in rows if item)


def _build_next_questions(
    profile: CompanyResearchProfile | None,
    gaps: Sequence[str],
) -> tuple[str, ...]:
    questions = [
        "公司在供應鏈中的精確層級是什麼：材料、設備、封裝、測試、模組，還是系統？",
        "有沒有一手文件證明客戶認證、量產、訂單、營收或毛利率改善？",
        "競爭者與替代方案是誰，替換成本與時程有多高？",
        "股本稀釋、現金流、債務、存貨與客戶集中是否會抵消題材價值？",
    ]
    if profile is not None and profile.additional_checks:
        questions.extend(profile.additional_checks[:3])
    questions.extend(gaps[:3])
    return _dedupe(questions)


def _filter_symbol(frame: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    output = frame.copy(deep=True)
    if "symbol" in output.columns:
        normalized = output["symbol"].astype(str).str.upper()
        output = output.loc[normalized == symbol]
    if "date" in output.columns:
        output = output.sort_values("date")
    return output


def _latest_row(frame: pd.DataFrame) -> pd.Series | None:
    if frame.empty:
        return None
    output = frame.copy(deep=True)
    if "date" in output.columns:
        output = output.sort_values("date")
    return output.iloc[-1]


def _number(value: Any) -> float | None:
    if value is None or value == "unknown" or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _evidence_label(score: float) -> EvidenceLevel:
    if score >= 72:
        return "高"
    if score >= 45:
        return "中"
    return "低"


def _confidence_label(score: float, factors: Sequence[SerenityFactor]) -> str:
    if any(factor.score < 35 for factor in factors):
        return "探索型，需要補證據"
    if score >= 72:
        return "中高，仍需一手文件驗證"
    if score >= 52:
        return "中，適合列入研究清單"
    return "低，資料或瓶頸假設不足"


def _sanitize_factor(factor: SerenityFactor) -> SerenityFactor:
    return SerenityFactor(
        name=_sanitize(factor.name),
        score=factor.score,
        evidence_level=factor.evidence_level,
        explanation=_sanitize(factor.explanation),
        gaps=_sanitize_items(factor.gaps),
    )


def _sanitize_items(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(_sanitize(item) for item in items if str(item).strip())


def _sanitize(text: str) -> str:
    output = str(text)
    for phrase in FORBIDDEN_PHRASES:
        output = output.replace(phrase, "不適合使用的投資誤導語句")
    return output


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return tuple(output)
