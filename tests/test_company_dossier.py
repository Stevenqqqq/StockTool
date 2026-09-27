from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from stock_tool.company_documents import CompanyDocument, parse_company_html, public_url
from stock_tool.company_dossier import build_dossier, collect_dossier
from stock_tool.company_research import build_company_research_profile


def document(text, url="https://example.com/products", title="產品介紹", links=()):
    return CompanyDocument(url, title, text, "", datetime.now(UTC).isoformat(), links)


def test_specs_are_company_evidence_not_inferred_production():
    doc = document(
        "本公司提供DDR4記憶體，容量4Gb及8Gb，最高3200Mbps。\nLPDDR4x產品預計明年量產。\nHBM3尚未量產。"
    )
    result = build_dossier("3006", "TWSE", "https://example.com", (doc,), industry="記憶體")
    assert any("DDR4" in f.subject and "3200Mbps" in f.subject for f in result.facts)
    assert any("LPDDR4x" in f.subject for f in result.facts)
    assert all(
        "非已實現" in f.stage for f in result.facts if "預計" in f.excerpt or "尚未" in f.excerpt
    )
    assert all(f.url == doc.url and f.excerpt in doc.text for f in result.facts)
    assert all(not f.published_at for f in result.facts)


@pytest.mark.parametrize(
    "industry,text,lens",
    [
        ("銀行", "本行收入包括放款利息與手續費，信用風險主要來自客戶違約。", "金融與租賃"),
        ("航運", "本公司提供貨櫃運輸服務，運量下滑影響營收。", "運輸與航運"),
        (
            "software",
            "We provide subscription software services. Revenue grew 10 percent.",
            "軟體與服務",
        ),
    ],
)
def test_industry_lenses_do_not_invent_company_products(industry, text, lens):
    result = build_dossier("ABC", "US", "https://example.com", (document(text),), industry=industry)
    assert result.industry_lens == lens
    assert result.facts
    assert all("DDR" not in f.excerpt for f in result.facts)
    assert any(f.section == "營運與收入" for f in result.facts)


def test_parser_ignores_navigation_and_unrelated_article_dates():
    doc = parse_company_html(
        "https://example.com",
        '<nav>HBM3 mass production</nav><main><p>We provide DDR4 memory.</p></main><aside><time datetime="2026-01-01">Related article</time></aside>',
        "2026-09-10",
    )
    assert doc.text == "We provide DDR4 memory."
    assert doc.published_at == ""


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://other.com",
        "https://example.com.evil.org",
        "https://user:pass@example.com",
        "https://example.com:444",
        "https://127.0.0.1",
    ],
)
def test_reader_rejects_untrusted_destinations(url):
    with pytest.raises(ValueError):
        public_url(url, "https://example.com")


def test_cache_isolated_by_identity_and_failed_refresh_is_stale(tmp_path):
    calls = []

    def loader(url, **kwargs):
        calls.append(url)
        return document("本公司提供DDR4記憶體，產品容量為4Gb。", url=url)

    first = collect_dossier(
        "3006", "TWSE", "https://example.com", industry="記憶體", cache_dir=tmp_path, loader=loader
    )
    cached = collect_dossier(
        "3006", "TWSE", "https://example.com", industry="記憶體", cache_dir=tmp_path, loader=loader
    )
    assert cached.state == "cached" and len(calls) == 1

    def broken(*args, **kwargs):
        raise TimeoutError("官網逾時")

    old = collect_dossier(
        "3006",
        "TWSE",
        "https://example.com",
        industry="記憶體",
        cache_dir=tmp_path,
        force=True,
        loader=broken,
    )
    assert old.state == "stale" and old.documents == first.documents
    other = collect_dossier(
        "MU", "US", "https://example.com", industry="記憶體", cache_dir=tmp_path, loader=broken
    )
    assert not other.facts
    assert old.fingerprint != first.fingerprint


def test_cache_tampered_cross_domain_document_is_rejected(tmp_path):
    collect_dossier(
        "MU",
        "US",
        "https://example.com",
        industry="記憶體",
        cache_dir=tmp_path,
        loader=lambda url, **kw: document("本公司提供DDR4記憶體及相關產品。", url=url),
    )
    path = next(tmp_path.glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["documents"][0]["url"] = "https://other.com/fake"
    path.write_text(json.dumps(data), encoding="utf-8")

    def broken(*args, **kwargs):
        raise TimeoutError()

    result = collect_dossier(
        "MU", "US", "https://example.com", industry="記憶體", cache_dir=tmp_path, loader=broken
    )
    assert not result.facts


@pytest.mark.parametrize("returned,kind", [("OTHER", "EQUITY"), ("MU", "ETF"), ("MU", "")])
def test_identity_conflict_and_funds_do_not_fetch_company_docs(monkeypatch, returned, kind):
    def forbidden(*args, **kwargs):
        pytest.fail("unconfirmed company must not be fetched")

    monkeypatch.setattr("stock_tool.company_research.collect_dossier", forbidden)
    profile = build_company_research_profile(
        "MU",
        market="US",
        info={"symbol": returned, "quoteType": kind, "website": "https://example.com"},
        include_details=True,
    )
    assert profile.dossier is None


def test_crawl_budget_and_partial_failure_remain_visible_in_cache(tmp_path):
    home = document(
        "本公司提供完整產品服務及相關解決方案。",
        url="https://example.com",
        links=(("/products", "產品"),),
    )

    def loader(url, **kwargs):
        if url.endswith("products"):
            raise ValueError("官網回應 HTTP 403。")
        return home

    result = collect_dossier(
        "ABC", "US", home.url, industry="工業", cache_dir=tmp_path, loader=loader
    )
    assert any("403" in gap for gap in result.gaps)
    cached = collect_dossier(
        "ABC", "US", home.url, industry="工業", cache_dir=tmp_path, loader=loader
    )
    assert cached.gaps == result.gaps


@pytest.mark.parametrize(
    "text",
    [
        "Microsoft Purview provides risk and compliance solutions to help customers protect data.",
        "Revenues generated through the Olympic partnership will be redistributed to sports organisations.",
        "Contact sales to discuss subscriptions and pricing for your organization.",
        "正向工作環境與福利制度，讓員工在專業與生活中取得平衡、持續成長。",
    ],
)
def test_customer_marketing_and_partner_revenue_are_not_company_financial_risk(text):
    result = build_dossier("ABC", "US", "https://example.com", (document(text),))
    assert not any(
        f.section in {"營運與收入", "公司揭露的風險", "進度與變化"} for f in result.facts
    )


def test_future_publication_does_not_enter_company_analysis():
    from dataclasses import replace

    doc = replace(document("本公司DDR4產品已進入量產，容量為8Gb。"), published_at="2099-01-01")
    result = build_dossier("ABC", "US", "https://example.com", (doc,))
    assert not result.facts
    assert any("未來" in gap for gap in result.gaps)


def test_bank_role_and_risk_require_substantive_company_content():
    doc = document(
        "To combat the skills imbalance, we provide youth and adult apprenticeships in finance.\n"
        "In Section III of this letter, I describe how we are dealing with these risks.\n"
        "We satisfy regulators and continually improve risk, governance and controls.\n"
        "Our loans-to-liquid assets ratio declined, reflecting strengthened liquidity.\n"
        "ABC is a leading financial services firm with operations worldwide.\n"
        "We face credit losses and geopolitical uncertainty that may affect our results.",
        url="https://example.com/ir/annual-report",
    )
    result = build_dossier("ABC", "US", "https://example.com", (doc,))
    roles = [f.excerpt for f in result.facts if f.section == "公司角色"]
    risks = [f.excerpt for f in result.facts if f.section == "公司揭露的風險"]
    assert roles == ["ABC is a leading financial services firm with operations worldwide."]
    assert risks == [
        "We face credit losses and geopolitical uncertainty that may affect our results."
    ]


def test_company_component_shows_evidence_and_refreshes_only_company_cache():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string("""
import streamlit as st
from stock_tool.company_documents import CompanyDocument
from stock_tool.company_dossier import build_dossier
from stock_tool.dashboard.components.company_dossier import render_company_dossier
st.session_state.setdefault("portfolio", "preserved personal input")
doc = CompanyDocument("https://example.com/products", "產品介紹", "本公司提供DDR4記憶體，容量4Gb及8Gb，最高3200Mbps。", "", "2026-09-10T01:00:00+00:00")
render_company_dossier(st, build_dossier("3006", "TWSE", "https://example.com", (doc,), industry="記憶體"))
""").run()
    assert not app.exception
    assert "DDR4" in str(app.dataframe[0].value)
    assert any("3200Mbps" in element.value for element in app.text)
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state["company_details_force"] is True
    assert app.session_state["portfolio"] == "preserved personal input"
