from types import SimpleNamespace

from stock_tool.company_documents import CompanyDocument
from stock_tool.company_dossier import build_dossier
from stock_tool.company_explanation import explain_company
from stock_tool.dashboard.pages.library import _render_saved_entry


def dossier(text, symbol="3006"):
    doc = CompanyDocument(
        "https://example.com/ir/annual-report",
        "Annual report",
        text,
        "",
        "2026-09-10T01:00:00+00:00",
    )
    return build_dossier(symbol, "TWSE", "https://example.com", (doc,))


def test_memory_explanation_distinguishes_products_from_unknown_revenue():
    value = dossier(
        "本公司從事專業 IC 設計，提供多種晶片產品與服務。\n本公司DDR4容量4Gb及8Gb，已進入量產。"
    )
    items = explain_company(value)
    text = " ".join(item.text for item in items)
    assert "DDR4" in text and "平均售價" in text and "庫存" in text
    assert "目前不能確認" in text and "待驗證風險" in text
    assert items[0].evidence_indices
    assert all(i < len(value.facts) for item in items for i in item.evidence_indices)


def test_bank_explanation_and_classification_reject_publicity_and_opinion():
    value = dossier(
        "Consumer & Community Banking\nCommercial & Investment Bank\nAsset & Wealth Management\n"
        "JPMorganChase becomes the Worldwide Olympic Partner in Asset and Wealth Management.\n"
        "The CCAR stress test produces results far worse, in our strongly held opinion, than actual results."
    )
    assert not any("Olympic" in f.excerpt or "CCAR" in f.excerpt for f in value.facts)
    text = " ".join(item.text for item in explain_company(value))
    assert "存放款利差" in text and "信用成本" in text
    assert "DDR" not in text


def test_unknown_company_is_not_given_memory_business_claims():
    text = " ".join(i.text for i in explain_company(dossier("尚無足夠內容可以核對。")))
    assert "不能只靠產業標籤" in text
    assert "DDR4" not in text


def test_saved_source_links_are_exact_urls_not_interpolated_markdown():
    url = "https://example.com/report?year=2025&lang=en"
    citation = SimpleNamespace(
        evidence_id="company.document.0", source=url, provider="公司官網", excerpt="原文", url=url
    )
    claim = SimpleNamespace(
        kind=SimpleNamespace(value="fact"),
        section="company",
        text="原文",
        citation_ids=(citation.evidence_id,),
    )
    note = SimpleNamespace(
        mode="local_rules",
        confidence_label="有限",
        coverage=1,
        claims=(claim,),
        citations=(citation,),
        missing_data=(),
        warnings=(),
    )
    entry = SimpleNamespace(
        symbol="3006",
        market="TWSE",
        version=1,
        created_at="2026-09-10",
        data_as_of="2026-09-10",
        note=note,
        sources=(url,),
        document_reference_integrity="verified",
    )

    class View:
        def __init__(self):
            self.links = []
            self.captions = []

        def link_button(self, label, href):
            self.links.append(href)

        def caption(self, text):
            self.captions.append(text)

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    view = View()
    _render_saved_entry(view, entry)
    assert view.links == [url]
    assert all(url not in text for text in view.captions)
