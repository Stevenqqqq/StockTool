"""Sprint 9.1 regressions for launcher readiness and evidence integrity."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import launcher
from stock_tool.concept_repository import ConceptRepository
from stock_tool.data.repositories import (
    ConceptRelationRecord,
    ResearchRepository,
    RepositoryDataError,
)
from stock_tool.dashboard import app as dashboard_app
from stock_tool.research_reports import extract_pdf_pages, summarize_pdf_report


class _Response:
    status = 200

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _Opener:
    def __init__(self, body: bytes, seen: dict[str, Any]) -> None:
        self._body = body
        self._seen = seen

    def open(self, request: Any, timeout: int) -> _Response:
        self._seen["url"] = request.full_url
        self._seen["timeout"] = timeout
        return _Response(self._body)


def test_launcher_readiness_uses_health_path_bypasses_proxy_and_requires_ok(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def build_opener(*handlers: object) -> _Opener:
        seen["handlers"] = handlers
        return _Opener(b"ok\n", seen)

    monkeypatch.setattr(launcher.urllib.request, "build_opener", build_opener)

    assert launcher._health_check("http://localhost:8501/_stcore/health") is True
    assert seen["url"] == "http://localhost:8501/_stcore/health"
    handlers = seen["handlers"]
    assert isinstance(handlers, tuple)
    assert any(isinstance(handler, launcher.urllib.request.ProxyHandler) for handler in handlers)


def test_launcher_readiness_rejects_non_ok_body(monkeypatch) -> None:
    monkeypatch.setattr(
        launcher.urllib.request,
        "build_opener",
        lambda *_handlers: _Opener(b"dashboard html", {}),
    )

    assert launcher._health_check("http://localhost:8501/_stcore/health") is False


def test_launcher_opens_browser_only_after_health_and_browser_failure_keeps_server(
    monkeypatch, tmp_path: Path
) -> None:
    runtime = SimpleNamespace(root=tmp_path / "runtime", logs_dir=tmp_path / "logs")
    runtime.logs_dir.mkdir()
    events: list[str] = []

    class _Process:
        def poll(self) -> None:
            return None

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(launcher, "default_runtime_paths", lambda: runtime)
    monkeypatch.setattr(
        launcher,
        "migrate_legacy_user_data",
        lambda *_args, **_kwargs: SimpleNamespace(warnings=()),
    )
    monkeypatch.setattr(launcher, "_available_port", lambda _ports: 8501)
    monkeypatch.setattr(launcher, "_streamlit_app_path", lambda: Path("launcher.py"))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *_args, **_kwargs: _Process())

    def wait_for_server(url: str, _process: object) -> bool:
        events.append(url)
        return True

    def fail_browser(url: str) -> bool:
        events.append(url)
        return False

    monkeypatch.setattr(launcher, "_wait_for_server", wait_for_server)
    monkeypatch.setattr(launcher, "_open_browser", fail_browser)

    assert launcher.main() == 0
    assert events == [
        "http://127.0.0.1:8501/_stcore/health",
        "http://127.0.0.1:8501",
    ]


def test_canonical_concept_identity_requires_explicit_market_for_numeric_symbol() -> None:
    unresolved = SimpleNamespace(session_state=SimpleNamespace(price_data_source={}))
    twse = SimpleNamespace(
        session_state=SimpleNamespace(price_data_source={"market": "TWSE", "user_symbol": "2330"})
    )
    tpex = SimpleNamespace(
        session_state=SimpleNamespace(
            price_data_source={"market": "TPEX", "user_symbol": "6488.TWO"}
        )
    )
    us = SimpleNamespace(session_state=SimpleNamespace(price_data_source={}))

    assert dashboard_app._canonical_concept_identity(unresolved, "2330") is None
    twse_identity = dashboard_app._canonical_concept_identity(twse, "2330.TW")
    tpex_identity = dashboard_app._canonical_concept_identity(tpex, "6488.TWO")
    us_identity = dashboard_app._canonical_concept_identity(us, "MU")
    assert twse_identity is not None and twse_identity.market == "TWSE"
    assert tpex_identity is not None and tpex_identity.symbol == "6488"
    assert tpex_identity is not None and tpex_identity.market == "TPEX"
    assert us_identity is not None and us_identity.market == "US"


def test_canonical_relations_survive_sqlite_reopen_without_cross_market_collision(
    tmp_path: Path,
) -> None:
    database = tmp_path / "research.sqlite"
    first = ConceptRepository(ResearchRepository(database))
    first.initialize()
    first.import_dataset(Path("tests/fixtures/concepts"))

    reopened = ConceptRepository(ResearchRepository(database))
    reopened.initialize()
    assert (
        reopened.relations_for("hbm", symbol="2330.TW", market="TWSE")[0].identity.market == "TWSE"
    )
    assert reopened.relations_for("hbm", symbol="2330", market="US")[0].identity.market == "US"


def test_dashboard_uses_same_canonical_identity_for_twse_tpex_and_us_relations(
    monkeypatch, tmp_path: Path
) -> None:
    fixture_root = tmp_path / "concepts"
    fixture_root.mkdir()
    source = Path("tests/fixtures/concepts")
    concepts = json.loads((source / "concepts.json").read_text(encoding="utf-8"))
    relation_payload = json.loads((source / "relations.json").read_text(encoding="utf-8"))
    relation_payload["relations"].append(
        {
            "concept_key": "hbm",
            "symbol": "6488",
            "market": "TPEX",
            "relation_type": "equipment_materials",
            "evidence": "Controlled fixture relation.",
            "confidence": 0.8,
            "source_name": "fixture",
            "source_url": "https://example.test/6488-tpex",
            "verified_at": "2026-07-01",
        }
    )
    (fixture_root / "concepts.json").write_text(json.dumps(concepts), encoding="utf-8")
    (fixture_root / "relations.json").write_text(json.dumps(relation_payload), encoding="utf-8")
    database = tmp_path / "dashboard.sqlite"
    repository = ConceptRepository(ResearchRepository(database))
    repository.initialize()
    repository.import_dataset(fixture_root)
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", database)

    def dashboard_relations(symbol: str, market: str) -> tuple[ConceptRelationRecord, ...]:
        fake_st = SimpleNamespace(
            session_state=SimpleNamespace(
                price_data_source={"user_symbol": symbol, "market": market}
            )
        )
        return dashboard_app._canonical_concept_relations(fake_st, symbol)

    twse = dashboard_relations("2330.TW", "TWSE")
    tpex = dashboard_relations("6488.TWO", "TPEX")
    us = dashboard_relations("MU", "US")

    assert any(item.identity.market == "TWSE" and item.identity.symbol == "2330" for item in twse)
    assert any(item.identity.market == "TPEX" and item.identity.symbol == "6488" for item in tpex)
    assert any(item.identity.market == "US" and item.identity.symbol == "MU" for item in us)
    assert not any(item.identity.market == "US" for item in twse)


def test_dataset_import_rolls_back_when_any_relation_is_invalid(tmp_path: Path) -> None:
    source = Path("tests/fixtures/concepts")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    concepts = json.loads((source / "concepts.json").read_text(encoding="utf-8"))
    relations = json.loads((source / "relations.json").read_text(encoding="utf-8"))
    relations["relations"][-1]["market"] = "AUTO"
    (dataset / "concepts.json").write_text(json.dumps(concepts), encoding="utf-8")
    (dataset / "relations.json").write_text(json.dumps(relations), encoding="utf-8")
    repository = ConceptRepository(ResearchRepository(tmp_path / "research.sqlite"))
    repository.initialize()

    with pytest.raises(RepositoryDataError):
        repository.import_dataset(dataset)

    assert repository.concepts() == ()


def test_dataset_import_rejects_alias_collision_without_partial_writes(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "concepts.json").write_text(
        json.dumps(
            {
                "dataset_version": "test-v1",
                "concepts": [
                    {"concept_key": "first", "display_name": "First", "aliases": ["shared"]},
                    {"concept_key": "second", "display_name": "Second", "aliases": ["shared"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    (dataset / "relations.json").write_text(
        json.dumps({"dataset_version": "test-v1", "relations": []}), encoding="utf-8"
    )
    repository = ConceptRepository(ResearchRepository(tmp_path / "research.sqlite"))
    repository.initialize()

    with pytest.raises(RepositoryDataError, match="alias"):
        repository.import_dataset(dataset)

    assert repository.concepts() == ()


class _Page:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _Reader:
    def __init__(self, _source: object) -> None:
        self.pages = [
            _Page("Page one discusses baseline demand. " + "A" * 500),
            _Page("Page two identifies a supply risk and a catalyst. " + "B" * 500),
        ]


def test_pdf_points_use_bounded_sentence_quotes_with_precise_second_page_offsets(
    monkeypatch,
) -> None:
    monkeypatch.setattr("stock_tool.research_reports.PdfReader", _Reader)
    source = Path("tests/fixtures/reports/fixture.pdf")
    pages = extract_pdf_pages(source)
    summary = summarize_pdf_report(source, source_name="fixture.pdf")
    second = next(point for point in summary.points if point.citations[0].page_number == 2)
    citation = second.citations[0]
    page_text = pages[1].text

    assert len(citation.quote) <= 320
    assert page_text[citation.start_offset : citation.end_offset] == citation.quote
    assert second.text in citation.quote


def test_pdf_with_no_citable_sentence_reports_data_insufficiency(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_tool.research_reports.PdfReader",
        lambda _source: SimpleNamespace(pages=[_Page("x")]),
    )

    summary = summarize_pdf_report(
        Path("tests/fixtures/reports/fixture.pdf"), source_name="short.pdf"
    )

    assert summary.points == ()
    assert any("資料不足" in limitation for limitation in summary.data_limitations)
