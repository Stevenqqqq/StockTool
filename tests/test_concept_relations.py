"""Sprint 9 canonical concept-relation regression tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from stock_tool.company_research import build_company_research_profile
from stock_tool.concept_repository import ConceptRepository, confidence_label, seed_bundled_dataset
from stock_tool.data.repositories import ResearchRepository
from stock_tool.serenity_agent import run_serenity_agent


@pytest.fixture
def concept_repository(tmp_path: Path) -> ConceptRepository:
    repository = ResearchRepository(tmp_path / "research.sqlite")
    repository.initialize()
    return ConceptRepository(repository)


def test_imported_fixtures_are_market_qualified_and_precision_first(
    concept_repository: ConceptRepository,
) -> None:
    result = concept_repository.import_dataset(Path("tests/fixtures/concepts"))

    assert result.imported_relations >= 20
    packaging = concept_repository.relations_for("advanced_packaging")
    assert any(
        item.identity.symbol == "2330" and item.identity.market == "TWSE" for item in packaging
    )
    assert not any(
        item.identity.symbol in {"NVDA", "AMD"} and item.relation_type == "core_manufacturing"
        for item in packaging
    )
    assert all(item.confidence < 0.75 or (item.evidence and item.source_url) for item in packaging)


def test_relation_identity_does_not_collide_between_markets(
    concept_repository: ConceptRepository,
) -> None:
    concept_repository.import_dataset(Path("tests/fixtures/concepts"))

    twse = concept_repository.relations_for("hbm", symbol="2330", market="TWSE")
    us = concept_repository.relations_for("hbm", symbol="2330", market="US")

    assert len(twse) == 1
    assert len(us) == 1
    assert twse[0].identity.market == "TWSE"
    assert us[0].identity.market == "US"


def test_manual_seed_and_unverified_or_stale_relations_are_honestly_labeled(
    concept_repository: ConceptRepository,
) -> None:
    concept_repository.import_dataset(Path("tests/fixtures/concepts"))
    robot = concept_repository.relations_for("humanoid_robot")

    manual = next(item for item in robot if item.identity.symbol == "MANUAL")
    stale = next(item for item in robot if item.identity.symbol == "STALE")
    assert manual.is_manual_seed is True
    assert manual.confidence < 0.75
    assert manual.verified_at is None
    assert stale.is_stale is True
    assert confidence_label(manual.confidence) == "低"


def test_canonical_relation_types_and_missing_source_rule(
    concept_repository: ConceptRepository,
) -> None:
    concept_repository.import_dataset(Path("tests/fixtures/concepts"))
    relations = concept_repository.relations_for("cowos")

    assert {item.relation_type for item in relations} == {
        "core_manufacturing",
        "equipment_materials",
        "design_platform",
        "downstream_demand",
        "indirect_beneficiary",
    }
    missing_source = next(item for item in relations if item.identity.symbol == "NOSOURCE")
    assert missing_source.source_url is None
    assert missing_source.confidence < 0.75


def test_dataset_import_is_idempotent_and_uses_utf8_chinese_labels(
    concept_repository: ConceptRepository,
) -> None:
    fixture_root = Path("tests/fixtures/concepts")
    first = concept_repository.import_dataset(fixture_root)
    second = concept_repository.import_dataset(fixture_root)

    assert first.imported_relations == second.imported_relations
    assert concept_repository.concept("hbm").display_name == "高頻寬記憶體"


def test_each_fixture_topic_has_all_roles_and_explicit_quality_edges(
    concept_repository: ConceptRepository,
) -> None:
    concept_repository.import_dataset(Path("tests/fixtures/concepts"))

    for concept_key in ("hbm", "advanced_packaging", "cowos", "humanoid_robot"):
        relations = concept_repository.relations_for(concept_key)
        assert {item.relation_type for item in relations} == {
            "core_manufacturing",
            "equipment_materials",
            "design_platform",
            "downstream_demand",
            "indirect_beneficiary",
        }
        assert any(item.is_manual_seed for item in relations)
        assert any(item.is_stale for item in relations)


def test_company_research_and_serenity_consume_the_same_canonical_relation(
    concept_repository: ConceptRepository,
) -> None:
    concept_repository.import_dataset(Path("tests/fixtures/concepts"))
    relations = concept_repository.relations_for("hbm", symbol="MU", market="US")
    profile = build_company_research_profile(
        "MU",
        market="US",
        info={"symbol": "MU", "longName": "Micron", "industry": "Semiconductors"},
        concept_relations=relations,
    )
    result = run_serenity_agent(
        symbol="MU",
        market="US",
        price_data=pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=2),
                "symbol": ["MU", "MU"],
                "close": [100.0, 101.0],
            }
        ),
        company_profile=profile,
        concept_relations=relations,
    )

    assert "hbm" in profile.linked_industries
    assert any("hbm" in item.lower() for item in result.chokepoint_map)


def test_serenity_does_not_use_same_symbol_relation_from_another_market(
    concept_repository: ConceptRepository,
) -> None:
    concept_repository.import_dataset(Path("tests/fixtures/concepts"))
    cross_market = concept_repository.relations_for("hbm", symbol="2330", market="US")
    result = run_serenity_agent(
        symbol="2330",
        market="TWSE",
        price_data=pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=2),
                "symbol": ["2330", "2330"],
                "close": [100.0, 101.0],
            }
        ),
        concept_relations=cross_market,
    )

    assert not any("不同市場測試資料" in item for item in result.chokepoint_map)


def test_bundled_dataset_is_seeded_once_and_remains_manual_seed(
    concept_repository: ConceptRepository,
) -> None:
    first = seed_bundled_dataset(concept_repository)
    second = seed_bundled_dataset(concept_repository)

    assert first is not None
    assert first.dataset_version == "sprint9-sample-v1"
    assert second is None
    relation = concept_repository.relations_for("hbm", symbol="MU", market="US")[0]
    assert relation.is_manual_seed is True
    assert relation.confidence < 0.75
