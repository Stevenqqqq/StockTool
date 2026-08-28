from __future__ import annotations

import pandas as pd

from stock_tool import concepts
from stock_tool.concepts import (
    concept_market_summary,
    lookup_concept_stocks_online,
    normalize_concept_stocks,
)


def test_online_concept_lookup_combines_taiwan_openapi_and_us_yfinance(monkeypatch) -> None:
    def fake_download_json(url: str, *, timeout_seconds: int) -> list[dict[str, object]]:
        if url == concepts.TWSE_COMPANY_URL:
            return [
                {"公司代號": "2330", "公司簡稱": "台積電", "產業別": "24", "英文簡稱": "TSMC"},
                {"公司代號": "2603", "公司簡稱": "長榮", "產業別": "15", "英文簡稱": "Evergreen"},
            ]
        if url == concepts.TPEX_COMPANY_URL:
            return [
                {
                    "SecuritiesCompanyCode": "6488",
                    "CompanyAbbreviation": "環球晶",
                    "SecuritiesIndustryCode": "24",
                }
            ]
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(concepts, "_download_json", fake_download_json)
    monkeypatch.setattr(
        concepts,
        "_screen_yfinance_us",
        lambda field, value, *, max_results: [
            {
                "symbol": "NVDA",
                "name": "NVIDIA Corporation",
                "market": "US",
                "exchange": "NASDAQ",
                "industry": "Semiconductors",
                "concept": "Semiconductors",
                "keywords": "Technology;Semiconductors",
                "source": "yfinance screen",
                "note": "test row",
                "match_score": 80,
                "match_reason": "yfinance 產業結果相符",
            }
        ]
        if value == "Semiconductors"
        else [],
    )
    monkeypatch.setattr(concepts, "_search_yfinance_us", lambda query, *, max_results: [])

    result = lookup_concept_stocks_online("半導體", markets=("TWSE", "TPEX", "US"))

    assert set(result.matches["symbol"]) == {"2330", "6488", "NVDA"}
    assert set(result.matches["market"]) == {"TWSE", "TPEX", "US"}
    assert "台股官方 OpenAPI" not in " ".join(result.warnings)
    assert any("TWSE/TPEx OpenAPI" in attempt for attempt in result.attempts)
    assert any("yfinance" in attempt for attempt in result.attempts)
    assert "TWSE OpenAPI" in result.matches.loc[result.matches["symbol"] == "2330", "source"].iloc[0]


def test_online_concept_lookup_does_not_use_local_fallback_unless_enabled(monkeypatch) -> None:
    monkeypatch.setattr(concepts, "_download_json", lambda url, *, timeout_seconds: [])
    monkeypatch.setattr(concepts, "_screen_yfinance_us", lambda field, value, *, max_results: [])
    monkeypatch.setattr(concepts, "_search_yfinance_us", lambda query, *, max_results: [])

    result = lookup_concept_stocks_online(
        "半導體",
        markets=("TWSE", "US"),
        include_local_fallback=False,
    )

    assert result.matches.empty
    assert any("沒有找到可用的線上結果" in warning for warning in result.warnings)
    assert not any("本機備援清單" in attempt for attempt in result.attempts)


def test_popular_taiwan_concept_uses_topic_profile_and_official_company_data(monkeypatch) -> None:
    def fake_download_json(url: str, *, timeout_seconds: int) -> list[dict[str, object]]:
        if url == concepts.TWSE_COMPANY_URL:
            return [
                {"公司代號": "2301", "公司簡稱": "光寶科", "產業別": "28", "英文簡稱": "LITEON"},
                {"公司代號": "2308", "公司簡稱": "台達電", "產業別": "28", "英文簡稱": "DELTA"},
                {"公司代號": "2330", "公司簡稱": "台積電", "產業別": "24", "英文簡稱": "TSMC"},
            ]
        if url == concepts.TPEX_COMPANY_URL:
            return []
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(concepts, "_download_json", fake_download_json)
    monkeypatch.setattr(concepts, "_screen_yfinance_us", lambda field, value, *, max_results: [])
    monkeypatch.setattr(concepts, "_search_yfinance_us", lambda query, *, max_results: [])

    result = lookup_concept_stocks_online("電源", markets=("TWSE", "TPEX"))

    assert set(result.matches["symbol"]) == {"2301", "2308"}
    assert result.matches["match_reason"].eq("內建概念題材對照 + 官方公司資料確認").all()
    assert result.matches["source"].str.contains("內建概念題材對照").all()


def test_hbm_query_returns_labeled_supply_chain_without_broad_semiconductor_matches(monkeypatch) -> None:
    def fake_download_json(url: str, *, timeout_seconds: int) -> list[dict[str, object]]:
        if url == concepts.TWSE_COMPANY_URL:
            return [
                {"公司代號": "2330", "公司簡稱": "台積電", "產業別": "24", "英文簡稱": "TSMC"},
                {"公司代號": "3711", "公司簡稱": "日月光投控", "產業別": "24", "英文簡稱": "ASEH"},
                {"公司代號": "3037", "公司簡稱": "欣興", "產業別": "28", "英文簡稱": "UNIMICRON"},
                {"公司代號": "2408", "公司簡稱": "南亞科", "產業別": "24", "英文簡稱": "NANYA"},
            ]
        if url == concepts.TPEX_COMPANY_URL:
            return []
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(concepts, "_download_json", fake_download_json)
    monkeypatch.setattr(concepts, "_screen_yfinance_us", lambda field, value, *, max_results: [])
    monkeypatch.setattr(concepts, "_search_yfinance_us", lambda query, *, max_results: [])

    result = lookup_concept_stocks_online("HBM", markets=("TWSE", "TPEX"))

    assert set(result.matches["symbol"]) == {"2330", "3711", "3037"}
    assert "2408" not in set(result.matches["symbol"])
    assert result.matches["relation_type"].str.contains("供應鏈關聯").all()
    assert result.matches["note"].str.contains("非 HBM 記憶體製造商").all()


def test_hbm_supply_chain_query_returns_taiwan_related_candidates(monkeypatch) -> None:
    def fake_download_json(url: str, *, timeout_seconds: int) -> list[dict[str, object]]:
        if url == concepts.TWSE_COMPANY_URL:
            return [
                {"公司代號": "2330", "公司簡稱": "台積電", "產業別": "24", "英文簡稱": "TSMC"},
                {"公司代號": "3711", "公司簡稱": "日月光投控", "產業別": "24", "英文簡稱": "ASEH"},
                {"公司代號": "3037", "公司簡稱": "欣興", "產業別": "28", "英文簡稱": "UNIMICRON"},
                {"公司代號": "2408", "公司簡稱": "南亞科", "產業別": "24", "英文簡稱": "NANYA"},
            ]
        if url == concepts.TPEX_COMPANY_URL:
            return []
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(concepts, "_download_json", fake_download_json)
    monkeypatch.setattr(concepts, "_screen_yfinance_us", lambda field, value, *, max_results: [])
    monkeypatch.setattr(concepts, "_search_yfinance_us", lambda query, *, max_results: [])

    result = lookup_concept_stocks_online("HBM供應鏈", markets=("TWSE", "TPEX"))

    assert set(result.matches["symbol"]) == {"2330", "3711", "3037"}
    assert result.matches["match_reason"].eq("內建概念題材對照 + 官方公司資料確認").all()
    assert result.matches["relation_type"].str.contains("供應鏈關聯").all()
    assert result.matches["note"].str.contains("非 HBM 記憶體製造商").all()


def test_hbm_query_sorts_direct_maker_before_supply_chain(monkeypatch) -> None:
    def fake_download_json(url: str, *, timeout_seconds: int) -> list[dict[str, object]]:
        if url == concepts.TWSE_COMPANY_URL:
            return [{"公司代號": "2330", "公司簡稱": "台積電", "產業別": "24", "英文簡稱": "TSMC"}]
        if url == concepts.TPEX_COMPANY_URL:
            return []
        raise AssertionError(f"unexpected url: {url}")

    def fake_search_yfinance_us(query: str, *, max_results: int) -> list[dict[str, object]]:
        if query == "MU":
            return [
                {
                    "symbol": "MU",
                    "name": "Micron Technology, Inc.",
                    "market": "US",
                    "exchange": "NASDAQ",
                    "industry": "Semiconductors",
                    "concept": "Semiconductors",
                    "keywords": "Memory;HBM",
                    "source": "yfinance search:MU",
                    "note": "online",
                    "match_score": 70,
                    "match_reason": "yfinance 產業/搜尋結果相符",
                }
            ]
        return []

    monkeypatch.setattr(concepts, "_download_json", fake_download_json)
    monkeypatch.setattr(concepts, "_screen_yfinance_us", lambda field, value, *, max_results: [])
    monkeypatch.setattr(concepts, "_search_yfinance_us", fake_search_yfinance_us)

    result = lookup_concept_stocks_online("HBM", markets=("TWSE", "TPEX", "US"))

    assert result.matches.iloc[0]["symbol"] == "MU"
    assert result.matches.iloc[0]["relation_type"] == "直接製造商"
    assert "2330" in set(result.matches["symbol"])
    assert result.matches.loc[result.matches["symbol"] == "2330", "relation_type"].iloc[0].startswith("供應鏈關聯")


def test_exact_long_alias_is_preferred_over_broad_short_alias(monkeypatch) -> None:
    def fake_download_json(url: str, *, timeout_seconds: int) -> list[dict[str, object]]:
        if url == concepts.TWSE_COMPANY_URL:
            return [
                {"公司代號": "2382", "公司簡稱": "廣達", "產業別": "25", "英文簡稱": "QUANTA"},
                {"公司代號": "3231", "公司簡稱": "緯創", "產業別": "25", "英文簡稱": "WISTRON"},
                {"公司代號": "2330", "公司簡稱": "台積電", "產業別": "24", "英文簡稱": "TSMC"},
            ]
        if url == concepts.TPEX_COMPANY_URL:
            return []
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(concepts, "_download_json", fake_download_json)
    monkeypatch.setattr(concepts, "_screen_yfinance_us", lambda field, value, *, max_results: [])
    monkeypatch.setattr(concepts, "_search_yfinance_us", lambda query, *, max_results: [])

    result = lookup_concept_stocks_online("AI伺服器", markets=("TWSE", "TPEX"))

    assert {"2382", "3231"} <= set(result.matches["symbol"])
    assert result.matches["concept"].eq("ai伺服器").all()


def test_advanced_packaging_aliases_use_topic_profiles(monkeypatch) -> None:
    def fake_download_json(url: str, *, timeout_seconds: int) -> list[dict[str, object]]:
        if url == concepts.TWSE_COMPANY_URL:
            return [
                {"公司代號": "2330", "公司簡稱": "台積電", "產業別": "24", "英文簡稱": "TSMC"},
                {"公司代號": "3711", "公司簡稱": "日月光投控", "產業別": "24", "英文簡稱": "ASEH"},
                {"公司代號": "3037", "公司簡稱": "欣興", "產業別": "28", "英文簡稱": "UNIMICRON"},
                {"公司代號": "2409", "公司簡稱": "友達", "產業別": "26", "英文簡稱": "AUO"},
                {"公司代號": "3481", "公司簡稱": "群創", "產業別": "26", "英文簡稱": "INNOLUX"},
            ]
        if url == concepts.TPEX_COMPANY_URL:
            return []
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(concepts, "_download_json", fake_download_json)
    monkeypatch.setattr(concepts, "_screen_yfinance_us", lambda field, value, *, max_results: [])
    monkeypatch.setattr(concepts, "_search_yfinance_us", lambda query, *, max_results: [])

    cowos = lookup_concept_stocks_online("cowos", markets=("TWSE", "TPEX"))
    copos = lookup_concept_stocks_online("copos", markets=("TWSE", "TPEX"))
    tgv = lookup_concept_stocks_online("tgv", markets=("TWSE", "TPEX"))

    assert {"2330", "3711", "3037"} <= set(cowos.matches["symbol"])
    assert {"2330", "2409", "3481"} <= set(copos.matches["symbol"])
    assert {"2330", "2409", "3481"} <= set(tgv.matches["symbol"])
    assert cowos.matches["match_reason"].str.contains("內建概念題材對照").any()
    assert copos.matches["match_reason"].str.contains("內建概念題材對照").any()
    assert tgv.matches["match_reason"].str.contains("內建概念題材對照").any()


def test_packaging_query_returns_curated_roles_with_symbol_notes(monkeypatch) -> None:
    def fake_download_json(url: str, *, timeout_seconds: int) -> list[dict[str, object]]:
        if url == concepts.TWSE_COMPANY_URL:
            return [
                {"公司代號": "2330", "公司簡稱": "台積電", "產業別": "24", "英文簡稱": "TSMC"},
                {"公司代號": "3711", "公司簡稱": "日月光投控", "產業別": "24", "英文簡稱": "ASEH"},
                {"公司代號": "3037", "公司簡稱": "欣興", "產業別": "28", "英文簡稱": "UNIMICRON"},
                {"公司代號": "2408", "公司簡稱": "南亞科", "產業別": "24", "英文簡稱": "NANYA"},
            ]
        if url == concepts.TPEX_COMPANY_URL:
            return []
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(concepts, "_download_json", fake_download_json)
    monkeypatch.setattr(concepts, "_screen_yfinance_us", lambda field, value, *, max_results: [])
    monkeypatch.setattr(concepts, "_search_yfinance_us", lambda query, *, max_results: [])

    result = lookup_concept_stocks_online("封裝", markets=("TWSE", "TPEX"))

    assert {"2330", "3711", "3037"} <= set(result.matches["symbol"])
    assert "2408" not in set(result.matches["symbol"])
    assert result.matches["concept"].eq("先進封裝").all()
    ase_note = result.matches.loc[result.matches["symbol"] == "3711", "note"].iloc[0]
    assert "日月光投控" in ase_note
    assert "先進封裝" in ase_note
    assert "最新產業報告確認" in ase_note


def test_packaging_query_labels_nvda_amd_as_demand_side_not_osat(monkeypatch) -> None:
    monkeypatch.setattr(concepts, "_download_json", lambda url, *, timeout_seconds: [])
    monkeypatch.setattr(concepts, "_screen_yfinance_us", lambda field, value, *, max_results: [])

    def fake_search_yfinance_us(query: str, *, max_results: int) -> list[dict[str, object]]:
        rows = {
            "NVDA": {
                "symbol": "NVDA",
                "name": "NVIDIA Corporation",
                "market": "US",
                "exchange": "NASDAQ",
                "industry": "Semiconductors",
                "concept": "Semiconductors",
                "keywords": "GPU;AI",
                "source": "yfinance search:NVDA",
                "note": "online",
                "match_score": 70,
                "match_reason": "yfinance 產業/搜尋結果相符",
            },
            "AMD": {
                "symbol": "AMD",
                "name": "Advanced Micro Devices, Inc.",
                "market": "US",
                "exchange": "NASDAQ",
                "industry": "Semiconductors",
                "concept": "Semiconductors",
                "keywords": "CPU;GPU",
                "source": "yfinance search:AMD",
                "note": "online",
                "match_score": 70,
                "match_reason": "yfinance 產業/搜尋結果相符",
            },
            "AMKR": {
                "symbol": "AMKR",
                "name": "Amkor Technology, Inc.",
                "market": "US",
                "exchange": "NASDAQ",
                "industry": "Semiconductor Equipment & Materials",
                "concept": "Semiconductor Equipment & Materials",
                "keywords": "OSAT;Packaging",
                "source": "yfinance search:AMKR",
                "note": "online",
                "match_score": 70,
                "match_reason": "yfinance 產業/搜尋結果相符",
            },
        }
        return [rows[query]] if query in rows else []

    monkeypatch.setattr(concepts, "_search_yfinance_us", fake_search_yfinance_us)

    result = lookup_concept_stocks_online("封裝", markets=("US",))

    nvda = result.matches.loc[result.matches["symbol"] == "NVDA"].iloc[0]
    amd = result.matches.loc[result.matches["symbol"] == "AMD"].iloc[0]
    amkr = result.matches.loc[result.matches["symbol"] == "AMKR"].iloc[0]

    assert "需求端" in nvda["relation_type"]
    assert "非封裝代工" in nvda["relation_type"]
    assert "不是封裝代工廠" in nvda["note"]
    assert "需求端" in amd["relation_type"]
    assert "非封裝代工" in amd["relation_type"]
    assert "不是封裝代工廠" in amd["note"]
    assert "OSAT" in amkr["relation_type"]


def test_silicon_capacitor_query_includes_price_reaction_stage(monkeypatch) -> None:
    def fake_download_json(url: str, *, timeout_seconds: int) -> list[dict[str, object]]:
        if url == concepts.TWSE_COMPANY_URL:
            return [
                {"公司代號": "6531", "公司簡稱": "愛普*", "產業別": "24", "英文簡稱": "APMEMORY"},
                {"公司代號": "6770", "公司簡稱": "力積電", "產業別": "24", "英文簡稱": "PSMC"},
                {"公司代號": "2344", "公司簡稱": "華邦電", "產業別": "24", "英文簡稱": "WINBOND"},
                {"公司代號": "2330", "公司簡稱": "台積電", "產業別": "24", "英文簡稱": "TSMC"},
                {"公司代號": "2408", "公司簡稱": "南亞科", "產業別": "24", "英文簡稱": "NANYA"},
            ]
        if url == concepts.TPEX_COMPANY_URL:
            return []
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(concepts, "_download_json", fake_download_json)
    monkeypatch.setattr(concepts, "_screen_yfinance_us", lambda field, value, *, max_results: [])
    monkeypatch.setattr(concepts, "_search_yfinance_us", lambda query, *, max_results: [])

    result = lookup_concept_stocks_online("矽電容", markets=("TWSE", "TPEX"))

    assert {"6531", "6770", "2344", "2330"} <= set(result.matches["symbol"])
    assert "2408" not in set(result.matches["symbol"])
    assert result.matches["price_reaction_stage"].eq("初期觀察").all()
    assert result.matches["stage_note"].str.contains("早期反應階段").all()
    ap_note = result.matches.loc[result.matches["symbol"] == "6531", "note"].iloc[0]
    assert "矽電容" in ap_note
    assert "營收占比" in ap_note


def test_normalize_concept_stocks_preserves_online_metadata_when_requested() -> None:
    raw = pd.DataFrame(
        [
            {
                "symbol": "NVDA",
                "name": "NVIDIA",
                "market": "US",
                "exchange": "NASDAQ",
                "industry": "Semiconductors",
                "concept": "AI",
                "keywords": "GPU",
                "source": "yfinance",
                "note": "online",
                "match_score": 90,
                "match_reason": "線上結果相符",
            }
        ]
    )

    result = normalize_concept_stocks(raw, preserve_extra=True)

    assert result.loc[0, "market_label"] == "美股"
    assert result.loc[0, "match_score"] == 90
    assert result.loc[0, "match_reason"] == "線上結果相符"


def test_concept_market_summary_counts_unique_symbols() -> None:
    matches = pd.DataFrame(
        {
            "symbol": ["2330", "2454", "NVDA"],
            "market_label": ["台股上市", "台股上市", "美股"],
        }
    )

    summary = concept_market_summary(matches)

    assert dict(zip(summary["市場"], summary["檔數"])) == {"台股上市": 2, "美股": 1}


def test_yfinance_search_includes_otc_equity_matches() -> None:
    quote = {
        "symbol": "TSVNF",
        "quoteType": "EQUITY",
        "exchange": "PNK",
        "shortname": "TEAM17 GROUP PLC",
        "industry": "Electronic Gaming & Multimedia",
        "sector": "Communication Services",
    }

    assert concepts._is_us_equity(quote)
    row = concepts._quote_to_concept_row(quote, source="yfinance search:tsv")

    assert row["symbol"] == "TSVNF"
    assert row["market"] == "US"
    assert "OTC" in row["note"]
