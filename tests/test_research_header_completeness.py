from __future__ import annotations

import pandas as pd

from stock_tool.application.research_snapshot import (
    ResearchSourceMetadata,
    ResearchWorkspaceService,
)
from stock_tool.company_documents import CompanyDocument
from stock_tool.company_dossier import CompanyDossier, build_dossier
from stock_tool.company_research import CompanyResearchProfile
from stock_tool.dashboard.components.research_header import render_research_header
from stock_tool.domain.models import Market, Symbol
from stock_tool.stock_scoring import (
    FUNDAMENTAL_WEIGHT,
    RISK_WEIGHT,
    TECHNICAL_WEIGHT,
    VALUATION_WEIGHT,
    ScoreComponent,
    StockScoreResult,
)


class _Column:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events

    def markdown(self, value: str) -> None:
        self.events.append(("markdown", value))

    def metric(self, label: str, value: object) -> None:
        self.events.append(("metric", (label, value)))


class _FakeStreamlit(_Column):
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        super().__init__(self.events)

    def title(self, value: str) -> None:
        self.events.append(("title", value))

    def caption(self, value: str) -> None:
        self.events.append(("caption", value))

    def warning(self, value: str) -> None:
        self.events.append(("warning", value))

    def info(self, value: str) -> None:
        self.events.append(("info", value))

    def columns(self, count: int) -> list[_Column]:
        return [_Column(self.events) for _ in range(count)]


def _score() -> StockScoreResult:
    return StockScoreResult(
        symbol="MU",
        total_score=80.0,
        available_score=80.0,
        coverage=1.0,
        technical_score=24.0,
        fundamental_score=24.0,
        valuation_score=16.0,
        risk_score=16.0,
        rating_label="研究參考",
        summary=(),
        strengths=(),
        weaknesses=(),
        strategy_health=(),
        missing_data=(),
        risk_notes=(),
        components=(
            ScoreComponent("技術面", 24.0, TECHNICAL_WEIGHT),
            ScoreComponent("基本面", 24.0, FUNDAMENTAL_WEIGHT),
            ScoreComponent("估值面", 16.0, VALUATION_WEIGHT),
            ScoreComponent("風險面", 16.0, RISK_WEIGHT),
        ),
    )


def _profile(*, dossier=None) -> CompanyResearchProfile:
    return CompanyResearchProfile(
        symbol="MU",
        provider_symbol="MU",
        company_name="Micron Technology",
        sector="科技",
        industry="記憶體",
        website="https://www.micron.com",
        main_business=("記憶體產品。",),
        technical_features=("DRAM。",),
        linked_industries=("半導體",),
        current_applications=("資料中心。",),
        future_applications=(),
        bottlenecks=("價格循環。",),
        additional_checks=(),
        data_sources=("provider company data",),
        limitations=("公司資料可能不完整。",),
        fact_fields=("company_name", "sector", "industry"),
        dossier=dossier,
    )


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-25", "2026-09-26"]),
            "close": [100.0, 101.0],
        }
    )


def _source() -> ResearchSourceMetadata:
    return ResearchSourceMetadata(
        provider="fixture-provider",
        query_symbol="MU",
        market="US",
        source_type="online",
        fetched_at="2026-09-26T10:00:00+00:00",
        last_data_date="2026-09-26",
        row_count=2,
    )


def _snapshot(
    *,
    profile=None,
    price_data: pd.DataFrame | None = None,
    is_stale: bool = False,
    error_message: str | None = None,
):
    return ResearchWorkspaceService().build(
        symbol=Symbol("MU", Market.US),
        price_data=_prices() if price_data is None else price_data,
        indicators=None,
        fundamental_results=None,
        stock_score=_score(),
        company_profile=profile,
        scenario_reference=None,
        source_metadata=_source(),
        is_stale=is_stale,
        error_message=error_message,
    )


def _visible(fake: _FakeStreamlit) -> str:
    return "\n".join(str(value) for _, value in fake.events)


def _status(fake: _FakeStreamlit) -> str:
    return next(str(value) for kind, value in fake.events if kind == "caption" and "研究狀態" in str(value))


def _document() -> CompanyDocument:
    return CompanyDocument(
        url="https://www.micron.com/about",
        title="About Micron",
        text="Micron provides memory products for data center customers.",
        published_at="2026-09-01",
        fetched_at="2026-09-26T10:00:00+00:00",
    )


def _dossier(
    *,
    documents: tuple[CompanyDocument, ...] = (),
    gaps: tuple[str, ...] = (),
    state: str = "fresh",
) -> CompanyDossier:
    return CompanyDossier(
        symbol="MU",
        market="US",
        website="https://www.micron.com",
        industry_lens="記憶體",
        facts=(),
        questions=(),
        gaps=gaps,
        documents=documents,
        checked_at="2026-09-26T10:00:00+00:00",
        state=state,
    )


def test_full_score_does_not_hide_missing_company_profile() -> None:
    fake = _FakeStreamlit()
    snapshot = _snapshot()

    render_research_header(fake, snapshot)

    visible = _visible(fake)
    assert "評分項目覆蓋率（依權重）" in visible
    assert "100.00%" in visible
    assert "公司資料狀態：資料不足" in visible
    assert "沒有可驗證的公司介紹資料" in visible
    assert "完整研究分數" not in visible
    assert "資料覆蓋率" not in visible
    assert "部分可用：沒有可驗證的公司介紹資料" in _status(fake)
    assert not any(
        kind == "metric" and "評分項目覆蓋率（依權重）" in str(value)
        for kind, value in fake.events
    )
    assert any(
        kind == "markdown" and "評分項目覆蓋率（依權重）" in str(value)
        for kind, value in fake.events
    )


def test_basic_company_profile_is_distinguished_from_official_documents() -> None:
    fake = _FakeStreamlit()

    render_research_header(fake, _snapshot(profile=_profile()))

    visible = _visible(fake)
    assert "公司資料狀態：僅有基本資料" in visible
    assert "尚未取得可核對的官方公司文件" in visible
    assert "完整公司研究" in visible
    assert "部分可用：僅有基本公司資料" in _status(fake)
    assert "資料已就緒" not in _status(fake)


def test_no_official_documents_is_partial_even_when_model_score_is_complete() -> None:
    fake = _FakeStreamlit()

    render_research_header(fake, _snapshot(profile=_profile(dossier=_dossier())))

    assert "部分可用：尚未取得可核對的官方公司頁面" in _status(fake)


def test_dossier_gap_is_visible_in_page_status() -> None:
    fake = _FakeStreamlit()
    dossier = _dossier(documents=(_document(),), gaps=("財報期間尚未取得。",))

    render_research_header(fake, _snapshot(profile=_profile(dossier=dossier)))

    assert "部分可用：公司資料仍有缺口：財報期間尚未取得。" in _status(fake)


def test_stale_dossier_takes_precedence_over_normal_company_status() -> None:
    fake = _FakeStreamlit()
    dossier = _dossier(documents=(_document(),), state="stale")

    render_research_header(fake, _snapshot(profile=_profile(dossier=dossier)))

    assert "資料可能過期：公司官方資料更新未完成" in _status(fake)


def test_error_precedes_missing_price_and_missing_price_precedes_profile_status() -> None:
    error_fake = _FakeStreamlit()
    render_research_header(
        error_fake,
        _snapshot(price_data=pd.DataFrame(), error_message="行情來源失敗。"),
    )
    assert "錯誤：行情來源失敗。" in _status(error_fake)
    assert "資料不足：" not in _status(error_fake)

    missing_fake = _FakeStreamlit()
    render_research_header(missing_fake, _snapshot(price_data=pd.DataFrame()))
    assert "資料不足：沒有可用的價格資料" in _status(missing_fake)


def test_limited_documents_without_gaps_use_non_ready_but_researchable_status() -> None:
    fake = _FakeStreamlit()
    dossier = _dossier(documents=(_document(),))

    render_research_header(fake, _snapshot(profile=_profile(dossier=dossier)))

    status = _status(fake)
    assert "目前資料可供研究（範圍有限）" in status
    assert "資料已就緒" not in status
    assert "完整" not in status


def test_partial_dossier_shows_real_documents_gaps_and_missing_price() -> None:
    document = CompanyDocument(
        url="https://www.micron.com/about",
        title="About Micron",
        text="Micron provides memory products for data center customers.",
        published_at="2026-09-01",
        fetched_at="2026-09-26T10:00:00+00:00",
    )
    dossier = build_dossier(
        "MU",
        "US",
        "https://www.micron.com",
        (document,),
        industry="記憶體",
        failures=("財報期間尚未取得。",),
    )
    fake = _FakeStreamlit()

    render_research_header(fake, _snapshot(profile=_profile(dossier=dossier), price_data=pd.DataFrame()))

    visible = _visible(fake)
    assert "公司資料狀態：已取得 1 個官方頁面" in visible
    assert "仍缺或未完成：" in visible
    assert "財報期間尚未取得。" in visible
    assert "最新可用收盤價" in visible
    assert "最後資料日期" in visible
    assert visible.count("資料不足") >= 2
