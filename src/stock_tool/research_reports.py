"""Research report PDF extraction and conservative local summaries."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO, Iterable
from urllib.parse import quote_plus

import pandas as pd
from pypdf import PdfReader

REPORT_DISCLAIMER = (
    "研究報告摘要僅供研究、學習與風險分析；原始報告可能受版權保護，"
    "請回到原文確認數字與上下文。本摘要不構成個人化投資建議。"
)

FORBIDDEN_PHRASES = ("保證獲利", "必漲", "穩賺", "歐印", "一定買進", "一定賣出")
RATING_REPLACEMENTS = {
    "強力買進": "偏正向評等",
    "買進": "偏正向評等",
    "強力賣出": "偏負向評等",
    "賣出": "偏負向評等",
}


@dataclass(frozen=True)
class ResearchReportSummary:
    """Compact summary generated from a user-provided research report."""

    symbol: str
    source_name: str
    title: str
    report_date: str
    extracted_characters: int
    key_points: tuple[str, ...]
    business_points: tuple[str, ...]
    technology_points: tuple[str, ...]
    industry_links: tuple[str, ...]
    catalysts: tuple[str, ...]
    bottlenecks: tuple[str, ...]
    valuation_notes: tuple[str, ...]
    risk_notes: tuple[str, ...]
    data_limitations: tuple[str, ...]
    disclaimer: str = REPORT_DISCLAIMER
    points: tuple["ReportPoint", ...] = ()


@dataclass(frozen=True)
class ExtractedPage:
    """One page of extracted PDF text with a one-based page number."""

    page_number: int
    text: str
    character_count: int


@dataclass(frozen=True)
class ReportCitation:
    """A bounded quote within one extracted PDF page."""

    page_number: int
    quote: str
    start_offset: int
    end_offset: int
    source_name: str


@dataclass(frozen=True)
class ReportPoint:
    """One conservative report point with a page-aware supporting citation."""

    text: str
    citations: tuple[ReportCitation, ...]


def extract_pdf_pages(
    source: str | Path | BinaryIO,
    *,
    max_pages: int = 40,
    max_characters: int = 80_000,
) -> tuple[ExtractedPage, ...]:
    """Extract bounded, page-aware PDF text without OCR or persistent raw storage."""

    if max_pages < 1 or max_characters < 1:
        return ()
    reader = PdfReader(source)
    remaining = max_characters
    pages: list[ExtractedPage] = []
    for page_index in range(min(len(reader.pages), max_pages)):
        text = _normalize_report_text(reader.pages[page_index].extract_text() or "")
        if not text:
            continue
        bounded = text[:remaining]
        pages.append(ExtractedPage(page_index + 1, bounded, len(bounded)))
        remaining -= len(bounded)
        if remaining <= 0:
            break
    return tuple(pages)


def extract_pdf_text(
    source: str | Path | BinaryIO,
    *,
    max_pages: int = 40,
    max_characters: int = 80_000,
) -> str:
    """Extract normalized text from a PDF file or file-like object.

    The function only reads the first ``max_pages`` pages and truncates to
    ``max_characters`` so very large reports do not freeze the local dashboard.
    It does not OCR scanned image-only PDFs.
    """

    return _normalize_report_text(
        "\n".join(
            page.text
            for page in extract_pdf_pages(
                source, max_pages=max_pages, max_characters=max_characters
            )
        )
    )[:max_characters]


def summarize_research_report(
    text: str,
    *,
    symbol: str = "",
    source_name: str = "",
) -> ResearchReportSummary:
    """Generate a conservative local summary from extracted report text."""

    normalized = _normalize_report_text(text)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    title = _infer_title(lines, source_name)
    report_date = _infer_report_date(normalized)
    sentences = _split_sentences(normalized)

    key_points = _collect_points(
        sentences,
        ("重點", "摘要", "結論", "展望", "成長", "營收", "獲利", "毛利", "EPS"),
        "研究重點",
        limit=5,
    )
    business_points = _collect_points(
        sentences,
        ("公司", "產品", "業務", "營收", "客戶", "市場", "電源管理", "PMIC", "IC"),
        "主要業務",
        limit=4,
    )
    technology_points = _collect_points(
        sentences,
        (
            "技術",
            "製程",
            "封裝",
            "功率",
            "效率",
            "車用",
            "AI",
            "伺服器",
            "電源管理",
            "PMIC",
            "GaN",
            "SiC",
        ),
        "技術特點",
        limit=4,
    )
    industry_links = _collect_points(
        sentences,
        ("產業", "AI", "伺服器", "車用", "工控", "消費", "資料中心", "電動車", "供應鏈"),
        "產業連結",
        limit=4,
    )
    catalysts = _collect_points(
        sentences,
        ("催化", "動能", "成長", "新品", "量產", "導入", "回補", "復甦", "展望"),
        "可能催化",
        limit=4,
    )
    bottlenecks = _collect_points(
        sentences,
        ("瓶頸", "風險", "競爭", "降價", "毛利率", "庫存", "匯率", "需求疲弱", "良率"),
        "瓶頸",
        limit=4,
    )
    valuation_notes = _collect_points(
        sentences,
        ("本益比", "PE", "P/E", "PER", "估值", "目標價", "評等", "EPS", "股價淨值"),
        "估值觀察",
        limit=3,
    )
    risk_notes = _collect_points(
        sentences,
        ("風險", "不確定", "下修", "衰退", "客戶集中", "地緣", "景氣", "利率", "存貨"),
        "風險",
        limit=4,
    )

    limitations = [
        "此功能採本機規則式摘要，未呼叫外部 AI；若原文是掃描圖片或表格型 PDF，抽字可能不完整。",
        "摘要會壓縮原文內容，細節、數字與評等請回到原始 PDF 核對。",
    ]
    if len(normalized) < 500:
        limitations.append("可抽取文字偏少，這份 PDF 可能是掃描圖檔或加密格式。")

    return ResearchReportSummary(
        symbol=str(symbol).strip(),
        source_name=str(source_name).strip(),
        title=title,
        report_date=report_date,
        extracted_characters=len(normalized),
        key_points=key_points or ("資料不足：無法可靠擷取研究重點。",),
        business_points=business_points or ("資料不足：無法可靠擷取主要業務段落。",),
        technology_points=technology_points or ("資料不足：無法可靠擷取技術特點段落。",),
        industry_links=industry_links or ("資料不足：無法可靠擷取產業連結段落。",),
        catalysts=catalysts or ("資料不足：無法可靠擷取催化因素。",),
        bottlenecks=bottlenecks or ("資料不足：無法可靠擷取瓶頸。",),
        valuation_notes=valuation_notes or ("資料不足：無法可靠擷取估值段落。",),
        risk_notes=risk_notes or ("資料不足：無法可靠擷取風險段落。",),
        data_limitations=tuple(limitations),
    )


def summarize_pdf_report(
    source: str | Path | BinaryIO,
    *,
    symbol: str = "",
    source_name: str = "",
    max_pages: int = 40,
    max_characters: int = 80_000,
) -> ResearchReportSummary:
    """Extract text from a PDF and return a local research summary."""

    inferred_source = source_name or (Path(source).name if isinstance(source, str | Path) else "")
    pages = extract_pdf_pages(source, max_pages=max_pages, max_characters=max_characters)
    summary = summarize_research_report(
        "\n".join(page.text for page in pages), symbol=symbol, source_name=inferred_source
    )
    if not pages:
        return replace(
            summary,
            data_limitations=(*summary.data_limitations, "PDF 未擷取到可用文字；目前未支援 OCR。"),
        )
    points = _page_points(pages, inferred_source)
    if not points:
        return replace(
            summary,
            points=(),
            data_limitations=(
                *summary.data_limitations,
                "資料不足：PDF 未提供可直接引用的研究句子。",
            ),
        )
    return replace(summary, points=points)


def _page_points(pages: tuple[ExtractedPage, ...], source_name: str) -> tuple[ReportPoint, ...]:
    """Create bounded points whose text is directly quoted from one PDF page."""

    points: list[ReportPoint] = []
    for page in pages:
        sentence = _first_citable_sentence(page.text)
        if sentence is None:
            continue
        quote, start_offset = sentence
        points.append(
            ReportPoint(
                text=_clean_point(quote),
                citations=(
                    ReportCitation(
                        page_number=page.page_number,
                        quote=quote,
                        start_offset=start_offset,
                        end_offset=start_offset + len(quote),
                        source_name=source_name,
                    ),
                ),
            )
        )
    return tuple(points)


def _first_citable_sentence(page_text: str, *, limit: int = 320) -> tuple[str, int] | None:
    """Return a bounded, sentence-level quote and its exact offset in ``page_text``."""

    for match in re.finditer(r"[^\n。！？.!?]*[。！？.!?]", page_text):
        raw = match.group(0)
        quote = raw.strip()
        if not 12 <= len(quote) <= limit:
            continue
        start_offset = match.start() + len(raw) - len(raw.lstrip())
        return quote, start_offset
    return None


def research_report_summaries_to_frame(summaries: Iterable[ResearchReportSummary]) -> pd.DataFrame:
    """Convert report summaries into a dashboard-friendly table."""

    rows = []
    for summary in summaries:
        rows.append(
            {
                "symbol": summary.symbol,
                "source_name": summary.source_name,
                "title": summary.title,
                "report_date": summary.report_date,
                "extracted_characters": summary.extracted_characters,
                "key_points": "；".join(summary.key_points),
                "technology_points": "；".join(summary.technology_points),
                "catalysts": "；".join(summary.catalysts),
                "bottlenecks": "；".join(summary.bottlenecks),
                "risk_notes": "；".join(summary.risk_notes),
            }
        )
    return pd.DataFrame(rows)


def build_public_report_search_links(symbol: str, company_name: str = "") -> dict[str, str]:
    """Build conservative public-search links without scraping third-party reports."""

    query_base = " ".join(item for item in (symbol.strip(), company_name.strip()) if item)
    if not query_base:
        query_base = "股票 研究報告"
    return {
        "Google PDF 搜尋": f"https://www.google.com/search?q={quote_plus(query_base + ' 研究報告 PDF')}",
        "Google 投資人關係搜尋": f"https://www.google.com/search?q={quote_plus(query_base + ' investor relations presentation')}",
        "公開資訊觀測站": "https://mops.twse.com.tw/mops/web/index",
    }


def _normalize_report_text(text: str) -> str:
    text = str(text or "").replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _infer_title(lines: list[str], source_name: str) -> str:
    for line in lines[:15]:
        clean = _clean_point(line)
        if 6 <= len(clean) <= 80 and not re.fullmatch(r"\d+", clean):
            return clean
    if source_name:
        return Path(source_name).stem
    return "未能辨識報告標題"


def _infer_report_date(text: str) -> str:
    patterns = (
        r"20\d{2}[/-]\d{1,2}[/-]\d{1,2}",
        r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日",
        r"20\d{2}\s*年\s*\d{1,2}\s*月",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return re.sub(r"\s+", "", match.group(0))
    return "未辨識"


def _split_sentences(text: str) -> list[str]:
    rough = re.split(r"(?<=[。！？!?；;])|\n+", text)
    sentences = []
    for item in rough:
        clean = _clean_point(item)
        if 12 <= len(clean) <= 260:
            sentences.append(clean)
    return sentences


def _collect_points(
    sentences: list[str],
    keywords: tuple[str, ...],
    label: str,
    *,
    limit: int,
) -> tuple[str, ...]:
    ranked: list[tuple[int, int, str]] = []
    normalized_keywords = tuple(keyword.lower() for keyword in keywords)
    for index, sentence in enumerate(sentences):
        lower = sentence.lower()
        score = sum(1 for keyword in normalized_keywords if keyword and keyword in lower)
        if score:
            ranked.append((score, -index, sentence))
    ranked.sort(reverse=True)

    points: list[str] = []
    seen: set[str] = set()
    for _, _, sentence in ranked:
        point = _sanitize_point(f"{label}：{_shorten(sentence)}")
        if point in seen:
            continue
        seen.add(point)
        points.append(point)
        if len(points) >= limit:
            break
    return tuple(points)


def _clean_point(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip(" -•\t")
    return text.strip()


def _shorten(text: str, limit: int = 140) -> str:
    clean = _clean_point(text)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _sanitize_point(text: str) -> str:
    output = str(text)
    for phrase in FORBIDDEN_PHRASES:
        output = output.replace(phrase, "不當保證語句")
    for phrase, replacement in RATING_REPLACEMENTS.items():
        output = output.replace(phrase, replacement)
    return output
