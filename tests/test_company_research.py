from __future__ import annotations

from time import monotonic

import stock_tool.company_research as company_research
from stock_tool.company_research import build_company_research_profile


def _profile_text(profile: object) -> str:
    fields = (
        "main_business",
        "technical_features",
        "linked_industries",
        "current_applications",
        "future_applications",
        "bottlenecks",
        "additional_checks",
    )
    return " ".join(item for field in fields for item in getattr(profile, field))


def test_company_profile_returns_promptly_when_optional_provider_blocks(monkeypatch) -> None:
    def blocking_info() -> dict[str, object]:
        import time

        time.sleep(1.0)
        return {"longName": "Late provider"}

    class BlockingTicker:
        get_info = staticmethod(blocking_info)

    monkeypatch.setattr(company_research.yf, "Ticker", lambda _symbol: BlockingTicker())

    started = monotonic()
    profile = build_company_research_profile("2330", market="TWSE", fetch_timeout_seconds=0.02)

    assert monotonic() - started < 0.4
    assert any("逾時" in item for item in profile.limitations)


def test_company_profile_can_explicitly_skip_optional_remote_fetch() -> None:
    profile = build_company_research_profile("2330", market="TWSE", allow_remote_fetch=False)

    assert any("略過公司基本資料" in item for item in profile.limitations)


def test_globalwafers_uses_silicon_wafer_context_not_storage_templates() -> None:
    profile = build_company_research_profile(
        "6488",
        market="TPEX",
        info={
            "symbol": "6488.TWO",
            "longName": "GlobalWafers Co., Ltd.",
            "sector": "Technology",
            "industry": "Semiconductors",
            "longBusinessSummary": "GlobalWafers makes silicon wafers used by semiconductor, data storage, NAND flash, SSD, and DRAM customers.",
        },
    )

    text = _profile_text(profile)
    assert "Semiconductor silicon wafers" in profile.linked_industries
    assert "矽晶圓" in text
    assert not any(token in text for token in ("NAND", "SSD", "DRAM"))


def test_specific_company_identity_beats_broad_storage_word() -> None:
    profile = build_company_research_profile(
        "2330",
        market="TWSE",
        info={
            "symbol": "2330.TW",
            "longName": "Taiwan Semiconductor Manufacturing Company Limited",
            "sector": "Technology",
            "industry": "Semiconductors",
            "longBusinessSummary": "A semiconductor foundry whose customers build storage and compute products.",
        },
    )

    assert profile.company_name == "台積電"
    assert not any(token in _profile_text(profile) for token in ("NAND", "SSD", "DRAM"))


def test_consumer_company_with_generic_storage_text_is_not_given_memory_products() -> None:
    profile = build_company_research_profile(
        "AAPL",
        market="US",
        info={
            "symbol": "AAPL",
            "longName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "longBusinessSummary": "Apple provides consumer electronics and cloud storage services.",
        },
    )

    assert not any(token in _profile_text(profile) for token in ("NAND", "SSD", "DRAM"))


def test_company_research_profile_infers_semiconductor_context_from_info() -> None:
    profile = build_company_research_profile(
        "TSM",
        market="US",
        info={
            "symbol": "TSM",
            "longName": "Taiwan Semiconductor Manufacturing Company Limited",
            "sector": "Technology",
            "industry": "Semiconductors",
            "website": "https://www.tsmc.com",
            "longBusinessSummary": "The company manufactures semiconductor wafers and integrated circuits.",
        },
    )

    assert profile.company_name == "Taiwan Semiconductor Manufacturing Company Limited"
    assert profile.industry == "半導體"
    assert any("半導體" in item for item in profile.main_business)
    assert any("製程" in item or "先進封裝" in item for item in profile.technical_features)
    assert any("AI" in item or "高效能" in item for item in profile.future_applications)
    assert profile.is_available


def test_company_research_profile_uses_topic_mapping_for_taiwan_symbol() -> None:
    profile = build_company_research_profile(
        "2383",
        market="TWSE",
        info={
            "symbol": "2383.TW",
            "longName": "Elite Material Co., Ltd.",
            "sector": "Technology",
            "industry": "Electronic Components",
            "longBusinessSummary": "The company provides copper clad laminate and PCB materials.",
        },
    )

    assert any("PCB" in item or "載板" in item for item in profile.linked_industries)
    assert any("線寬" in item or "訊號" in item for item in profile.technical_features)
    assert any("AI 伺服器" in item or "高速交換器" in item for item in profile.future_applications)


def test_company_research_profile_marks_missing_summary_as_limitation() -> None:
    profile = build_company_research_profile(
        "UNKNOWN",
        market="US",
        info={"symbol": "UNKNOWN", "longName": "Unknown Corp"},
    )

    assert profile.company_name == "Unknown Corp"
    assert any("未提供公司長描述" in item for item in profile.limitations)
    assert any("資料不足" in item for item in profile.main_business)


def test_company_research_profile_does_not_match_short_aliases_inside_words() -> None:
    profile = build_company_research_profile(
        "9999",
        market="TWSE",
        info={
            "symbol": "9999.TW",
            "longName": "Taiwan Device Components",
            "sector": "Technology",
            "industry": "Semiconductors",
            "longBusinessSummary": "The company makes semiconductor parts for consumer devices and servers.",
        },
    )

    assert not any(item == "AI" for item in profile.linked_industries)
    assert not any("電動車" in item for item in profile.linked_industries)
    assert not any("低軌衛星" in item for item in profile.linked_industries)


def test_company_research_profile_highlights_hbm_for_micron() -> None:
    profile = build_company_research_profile(
        "MU",
        market="US",
        info={
            "symbol": "MU",
            "longName": "Micron Technology, Inc.",
            "sector": "Technology",
            "industry": "Semiconductors",
            "longBusinessSummary": "Micron provides memory and storage products for data centers and clients.",
        },
    )

    assert any("HBM" in item or "AI 記憶體" in item for item in profile.linked_industries)
    assert any("HBM" in item and "頻寬" in item for item in profile.technical_features)
    assert any("HBM3E" in item or "HBM4" in item for item in profile.future_applications)
    assert any("產能" in item and "良率" in item for item in profile.bottlenecks)


def test_company_research_profile_uses_nand_storage_focus_for_sandisk() -> None:
    profile = build_company_research_profile(
        "SNDK",
        market="US",
        info={
            "symbol": "SNDK",
            "longName": "Sandisk Corporation",
            "sector": "Technology",
            "industry": "Computer Hardware",
            "longBusinessSummary": "Sandisk develops NAND flash storage, SSDs, memory cards, and USB flash drives.",
        },
    )

    assert any("NAND" in item or "SSD" in item for item in profile.linked_industries)
    assert any("3D NAND" in item or "控制器" in item for item in profile.technical_features)
    assert any(
        "資料中心 SSD" in item or "企業 SSD" in item
        for item in profile.current_applications + profile.future_applications
    )
    assert not any(item == "HBM / AI 記憶體" for item in profile.linked_industries)


def test_company_research_profile_identifies_robot_reducer_role() -> None:
    profile = build_company_research_profile(
        "2049",
        market="TWSE",
        info={
            "symbol": "2049.TW",
            "longName": "HIWIN Technologies Corp.",
            "sector": "Industrials",
            "industry": "Specialty Industrial Machinery",
            "longBusinessSummary": "The company provides linear motion, automation and robot reducer products.",
        },
    )

    assert any("減速器" in item for item in profile.linked_industries)
    assert any("低背隙" in item or "高扭矩" in item for item in profile.technical_features)
    assert any("人形機器人關節" in item for item in profile.future_applications)
    assert any("量產" in item or "客戶認證" in item for item in profile.bottlenecks)
