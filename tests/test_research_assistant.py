from __future__ import annotations

from dataclasses import replace

import pandas as pd

from stock_tool.application.research_snapshot import (
    ResearchSourceMetadata,
    ResearchWorkspaceService,
)
from stock_tool.company_research import CompanyResearchProfile
from stock_tool.domain.models import Market, Symbol
from stock_tool.research.assistant import (
    AIResearchAssistant,
    ClaimKind,
    DailyResearchAssistantService,
    ResearchAssistantCache,
    build_evidence_bundle,
)
from stock_tool.stock_scoring import (
    FUNDAMENTAL_WEIGHT,
    RISK_WEIGHT,
    TECHNICAL_WEIGHT,
    VALUATION_WEIGHT,
    ScoreComponent,
    StockScoreResult,
)


def _snapshot():
    prices = pd.DataFrame(
        {
            "symbol": ["MU", "MU"],
            "market": ["US", "US"],
            "date": ["2026-07-24", "2026-07-27"],
            "close": [90.0, 100.0],
            "volume": [1000.0, 1200.0],
        }
    )
    score = StockScoreResult(
        symbol="MU",
        total_score=72.0,
        available_score=72.0,
        coverage=0.9,
        technical_score=24.0,
        fundamental_score=20.0,
        valuation_score=14.0,
        risk_score=14.0,
        rating_label="研究參考",
        summary=("確定性評分。",),
        strengths=("價格資料可用。",),
        weaknesses=(),
        strategy_health=(),
        missing_data=(),
        risk_notes=("資料不代表未來。",),
        components=(
            ScoreComponent("技術面", 24.0, TECHNICAL_WEIGHT),
            ScoreComponent("基本面", 20.0, FUNDAMENTAL_WEIGHT),
            ScoreComponent("估值面", 14.0, VALUATION_WEIGHT),
            ScoreComponent("風險面", 14.0, RISK_WEIGHT),
        ),
    )
    profile = CompanyResearchProfile(
        symbol="MU",
        provider_symbol="MU",
        company_name="Micron Technology",
        sector="Technology",
        industry="Semiconductors",
        website="",
        main_business=("記憶體產品。",),
        technical_features=("HBM。",),
        linked_industries=("AI 記憶體",),
        current_applications=("資料中心",),
        future_applications=(),
        bottlenecks=("記憶體循環。",),
        additional_checks=(),
        data_sources=("fixture profile",),
        limitations=(),
        fact_fields=("company_name", "sector", "industry"),
    )
    return ResearchWorkspaceService().build(
        symbol=Symbol("MU", Market.US),
        price_data=prices,
        indicators=prices,
        fundamental_results=pd.DataFrame({"symbol": ["MU"], "market": ["US"]}),
        stock_score=score,
        company_profile=profile,
        scenario_reference=None,
        source_metadata=ResearchSourceMetadata(
            provider="fixture-provider",
            query_symbol="MU",
            market="US",
            source_type="online",
            fetched_at="2026-07-27T08:00:00+00:00",
            last_data_date="2026-07-27",
            row_count=2,
        ),
    )


def test_evidence_bundle_is_market_qualified_and_does_not_mutate_snapshot() -> None:
    snapshot = _snapshot()
    before = snapshot.price_history.copy(deep=True)

    bundle = build_evidence_bundle(snapshot)

    assert bundle.symbol == "MU"
    assert bundle.market == "US"
    assert bundle.evidence
    assert all(item.symbol == "MU" and item.market == "US" for item in bundle.evidence)
    pd.testing.assert_frame_equal(snapshot.price_history, before)


def test_new_evidence_changes_fingerprint_but_deterministic_metrics_remain_read_only() -> None:
    snapshot = _snapshot()

    first = build_evidence_bundle(snapshot)
    second = build_evidence_bundle(replace(snapshot, warnings=("來源延遲",)))

    assert first.fingerprint != second.fingerprint
    assert snapshot.composite_score == 72.0
    assert any(item.kind is ClaimKind.CALCULATION for item in first.evidence)


def test_evidence_bundle_marks_missing_and_warning_without_promoting_them_to_facts() -> None:
    snapshot = replace(_snapshot(), warnings=("來源資料有衝突",), missing_data=())

    bundle = build_evidence_bundle(snapshot)

    kinds = {item.kind for item in bundle.evidence}
    assert ClaimKind.WARNING in kinds
    assert all(item.kind is not ClaimKind.FACT or item.source for item in bundle.evidence)


def test_warning_evidence_lowers_confidence_and_remains_visible(tmp_path) -> None:
    snapshot = replace(_snapshot(), warnings=("資料來源衝突，請確認。",))
    result = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path)).generate(
        build_evidence_bundle(snapshot)
    )

    assert result.confidence_label == "low"
    assert any(claim.kind is ClaimKind.WARNING for claim in result.claims)


def test_daily_service_limits_candidates_and_keeps_market_qualified_identity(tmp_path) -> None:
    snapshot = _snapshot()
    service = DailyResearchAssistantService(
        AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "ai-research"))
    )

    result = service.generate(
        candidates=(("MU", "US"), ("MU", "TWSE"), ("AAPL", "US"), ("2330", "TWSE")),
        snapshots={"US:MU": snapshot},
    )

    assert len(result.notes) == 1
    assert result.notes[0].symbol == "MU"
    assert result.notes[0].market == "US"
    assert result.unavailable_identities == ("TWSE:MU", "US:AAPL")


def test_daily_service_does_not_write_candidates_to_watchlist_or_snapshot_inputs(tmp_path) -> None:
    snapshot = _snapshot()
    snapshots = {"US:MU": snapshot}
    before = snapshot.price_history.copy(deep=True)
    service = DailyResearchAssistantService(
        AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "ai-research"))
    )

    service.generate(candidates=(("MU", "US"),), snapshots=snapshots)

    assert set(snapshots) == {"US:MU"}
    pd.testing.assert_frame_equal(snapshot.price_history, before)
