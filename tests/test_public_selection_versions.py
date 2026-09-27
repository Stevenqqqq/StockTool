from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path

from stock_tool.company_documents import CompanyDocument
from stock_tool.company_dossier import CompanyDossier, CompanyFact
from stock_tool.research.ai_attempt import record_attempt
from stock_tool.research.public_request import PreparedPublicRequest, RequestOutcome
from stock_tool.research.public_selection import PUBLIC_QUESTIONS, select_public_evidence
from stock_tool.research.work_session import (
    ResearchWorkSession,
    WorkSessionStore,
    combine_snapshots,
)
from test_research_work_session import snapshots

NOW = datetime(2026, 9, 19, 10, tzinfo=UTC)
PUBLIC_DOCUMENT_TEXT = (
    "DDR4 memory products.\n"
    "We provide public memory services.\n"
    "Private contact account@example.com details.\n"
    "Additional public company risk is disclosed in filings."
)


def _adjacent_snapshot():
    holding, company = snapshots()
    document = CompanyDocument(
        "https://example.com/products",
        "Memory products",
        PUBLIC_DOCUMENT_TEXT,
        "2026-09-01",
        "2026-09-18T03:00:00+00:00",
    )
    facts = (
        CompanyFact(
            "產品與技術",
            "DDR4",
            "DDR4 memory products.",
            "官網列示／提及（量產狀態未確認）",
            "DDR4 memory products.",
            document.url,
            document.title,
            document.published_at,
            document.fetched_at,
        ),
        CompanyFact(
            "公司角色",
            "private neighbor",
            "Private contact account@example.com details.",
            "官網列示／提及（量產狀態未確認）",
            "Private contact account@example.com details.",
            document.url,
            document.title,
            document.published_at,
            document.fetched_at,
        ),
        CompanyFact(
            "公司揭露的風險",
            "public risk",
            "Additional public company risk is disclosed in filings.",
            "官網列示／提及（量產狀態未確認）",
            "Additional public company risk is disclosed in filings.",
            document.url,
            document.title,
            document.published_at,
            document.fetched_at,
        ),
    )
    dossier = CompanyDossier(
        symbol="3006",
        market="TWSE",
        website="https://example.com",
        industry_lens="記憶體",
        facts=facts,
        questions=("產品與風險",),
        gaps=(),
        documents=(document,),
        checked_at=NOW.isoformat(),
        state="fresh",
    )
    profile = replace(company.company_profile, dossier=dossier)
    return combine_snapshots(holding, replace(company, company_profile=profile))


def test_v2_keeps_adjacent_source_text_and_omits_private_neighbor() -> None:
    snapshot = _adjacent_snapshot()
    selection = select_public_evidence(snapshot, PUBLIC_QUESTIONS[0], selection_version=2)
    payload = selection.payload
    manifest = selection.manifest
    rows = {row["evidence_id"]: row for row in payload["evidence"]}
    selected = {row["evidence_id"]: row for row in manifest["selected"]}
    omitted = {row["evidence_id"]: row for row in manifest["omitted"]}

    assert set(rows) == {"company.fact.0", "company.fact.2"}
    assert "company.fact.1" in omitted
    assert "個人或敏感內容" in omitted["company.fact.1"]["reason"]
    assert "account@example.com" not in selection.payload_json
    assert rows["company.fact.0"]["text"] == (
        "DDR4 memory products.\nWe provide public memory services."
    )
    assert "Private contact" not in rows["company.fact.0"]["text"]

    for evidence_id, item in selected.items():
        start, end = item["start"], item["end"]
        assert PUBLIC_DOCUMENT_TEXT[start:end] == item["excerpt"]
        assert item["excerpt"] == rows[evidence_id]["text"]


def test_v1_request_replays_and_survives_work_session_backup_restore(tmp_path: Path) -> None:
    snapshot = _adjacent_snapshot()
    request = PreparedPublicRequest.prepare(snapshot, PUBLIC_QUESTIONS[0], selection_version=1)
    request.verify(snapshot)
    payload = json.loads(request.payload_json)
    assert json.loads(request.manifest_json)["selection_version"] == 1
    assert payload["evidence"][0]["text"] == "DDR4 memory products."
    assert "We provide public memory services." not in payload["evidence"][0]["text"]
    assert "account@example.com" not in request.payload_json

    timestamp = NOW.isoformat()
    attempt = record_attempt(
        snapshot,
        request,
        RequestOutcome("failed", "fixture failure", timestamp),
        provider="fixture",
        model="fixture",
        started_at=timestamp,
        completed_at=timestamp,
    )
    session = ResearchWorkSession(snapshot, "本機問題", timestamp, attempt)
    original = WorkSessionStore(tmp_path / "original")
    restored = WorkSessionStore(tmp_path / "restored")
    key = original.save(session)
    restored.restore_bytes(original.backup_bytes())

    reopened = restored.load(key)
    assert reopened == session
    saved_attempt = json.loads(reopened.ai_attempt_json)
    assert saved_attempt["selection"]["selection_version"] == 1
    assert saved_attempt["payload"]["evidence"][0]["text"] == "DDR4 memory products."
    request.verify(reopened.snapshot)
