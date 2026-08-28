"""Sprint 9 page-aware PDF evidence tests."""

from __future__ import annotations

from pathlib import Path

from stock_tool.research_reports import extract_pdf_pages, summarize_pdf_report

PDF_FIXTURE = Path("tests/fixtures/reports/fixture.pdf")


class _Page:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _Reader:
    def __init__(self, _source: object) -> None:
        self.pages = [_Page("第 1 頁 HBM 供應受限。"), _Page("第 2 頁 CoWoS 產能擴充。"), _Page("")]


def test_page_aware_extraction_uses_one_based_pages_and_limits(monkeypatch) -> None:
    monkeypatch.setattr("stock_tool.research_reports.PdfReader", _Reader)

    pages = extract_pdf_pages(PDF_FIXTURE, max_pages=2, max_characters=30)

    assert [page.page_number for page in pages] == [1, 2]
    assert pages[0].character_count == len(pages[0].text)
    assert sum(page.character_count for page in pages) <= 30


def test_summary_points_carry_real_page_citations(monkeypatch) -> None:
    monkeypatch.setattr("stock_tool.research_reports.PdfReader", _Reader)

    summary = summarize_pdf_report(
        PDF_FIXTURE, symbol="MU", source_name="fixture.pdf", max_characters=30
    )

    assert summary.points
    assert all(point.citations for point in summary.points)
    citation = summary.points[0].citations[0]
    assert citation.page_number >= 1
    assert citation.start_offset == 0
    assert citation.end_offset > citation.start_offset
    assert citation.end_offset == len(citation.quote)
    assert citation.quote in {"第 1 頁 HBM 供應受限。", "第 2 頁 CoWoS 產能擴充。"}


def test_scanned_pdf_without_text_is_marked_ocr_unsupported(monkeypatch) -> None:
    monkeypatch.setattr("stock_tool.research_reports.PdfReader", _Reader)
    monkeypatch.setattr(
        _Reader, "__init__", lambda self, _source: setattr(self, "pages", [_Page("")])
    )

    summary = summarize_pdf_report(PDF_FIXTURE, source_name="scanned.pdf")

    assert summary.points == ()
    assert any("OCR" in item for item in summary.data_limitations)
