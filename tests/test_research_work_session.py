from dataclasses import replace
from datetime import UTC, datetime
import json

import pandas as pd
import pytest

from stock_tool.application.holding_analysis import build_holding_analysis
from stock_tool.application.research_snapshot import (
    ResearchWorkspaceService,
    ResearchSourceMetadata,
)
from stock_tool.company_documents import CompanyDocument
from stock_tool.company_dossier import build_dossier
from stock_tool.company_research import build_company_research_profile
from stock_tool.domain.models import Market, Symbol
from stock_tool.research.public_selection import PUBLIC_QUESTIONS, select_public_evidence
from stock_tool.research.work_session import (
    CombinedSnapshot,
    ResearchWorkSession,
    WorkSessionError,
    WorkSessionStore,
    canonical,
    combine_snapshots,
    digest,
)

NOW = datetime(2026, 9, 13, 10, tzinfo=UTC)


def snapshots(symbol="3006", market="TWSE", kind="股票"):
    identity = {"symbol": symbol, "market": market, "instrument_type": kind}
    holding = build_holding_analysis(
        {
            **identity,
            "currency": "TWD",
            "quantity": 19,
            "average_cost": 31,
            "note": "CANARY_NOTE_DO_NOT_SEND",
        },
        prices=pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "market": market,
                    "date": "2026-09-11",
                    "close": 36,
                    "provider": "fixture",
                    "fetched_at": NOW.isoformat(),
                }
            ]
        ),
        fx_quote=None,
        profile=identity,
        weight=0.7341,
        now=NOW,
    )
    document = CompanyDocument(
        "https://example.com/products",
        "Memory products",
        "We design DDR4 memory products. DDR4 is in mass production. "
        + "Full original document preserved. " * 60,
        "2026-09-01",
        "2026-09-12T03:00:00+00:00",
    )
    if symbol == "JPM":
        document = replace(
            document,
            title="Banking services",
            text="We provide consumer and community banking services. "
            "Commercial and investment banking and asset and wealth management are our businesses. "
            "Our business faces adverse effects from credit loss and interest rate volatility.",
        )
    dossier = build_dossier(
        symbol, market, "https://example.com", (document,), checked_at=NOW.isoformat()
    )
    profile = build_company_research_profile(symbol, market=market, allow_remote_fetch=False)
    profile = replace(
        profile,
        company_name=symbol + " fixture",
        fact_fields=("company_name",),
        instrument_type=kind,
        dossier=dossier if kind == "股票" else None,
    )
    company = ResearchWorkspaceService().build(
        symbol=Symbol(symbol, Market(market)),
        company_profile=profile,
        price_data=None,
        indicators=None,
        fundamental_results=None,
        stock_score=None,
        scenario_reference=None,
        source_metadata=ResearchSourceMetadata.empty(symbol=symbol, market=market),
    )
    return holding, company


def work():
    h, c = snapshots()
    return ResearchWorkSession(
        combine_snapshots(h, c), "我的成本 CANARY_PRIVATE_900", NOW.isoformat()
    )


def test_full_local_evidence_and_separate_times_roundtrip(tmp_path):
    h, c = snapshots()
    combined = combine_snapshots(h, c)
    assert combined.holding_fingerprint == h.fingerprint
    assert (
        combined.company["profile"]["dossier"]["documents"][0]["text"]
        == c.company_profile.dossier.documents[0].text
    )
    assert len(combined.company["profile"]["dossier"]["documents"][0]["text"]) > 700
    assert (
        next(d["as_of"] for d in combined.holding["data"] if d["label"] == "收盤價") == "2026-09-11"
    )
    assert combined.company["profile"]["dossier"]["documents"][0]["published_at"] == "2026-09-01"
    assert "data_as_of" not in combined.to_dict()
    session = ResearchWorkSession(combined, "公司怎麼賺錢", NOW.isoformat())
    store = WorkSessionStore(tmp_path / "new")
    key = store.save(session)
    reopened = WorkSessionStore(store.directory).load(key)
    assert reopened.to_dict() == session.to_dict()
    mutable = reopened.snapshot.company
    mutable["profile"]["dossier"]["documents"].clear()
    assert reopened.snapshot.company["profile"]["dossier"]["documents"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "JPM"),
        ("market", "US"),
        ("instrument_type", "ETF"),
        ("instrument_type", "未確認"),
    ],
)
def test_identity_conflicts_rejected(field, value):
    h, c = snapshots()
    with pytest.raises(WorkSessionError):
        combine_snapshots(replace(h, **{field: value}), c)


@pytest.mark.parametrize("field,value", [("symbol", None), ("market", []), ("instrument_type", {})])
def test_malformed_identity_is_a_controlled_rejection(field, value):
    from stock_tool.research.work_session import ResearchIdentity

    identity = {"market": "TWSE", "symbol": "3006", "instrument_type": "股票"}
    identity[field] = value
    with pytest.raises(WorkSessionError):
        ResearchIdentity(**identity)


@pytest.mark.parametrize(
    "field,value",
    [
        ("price_source", {}),
        ("price_source", {"market": "US"}),
        ("price", {"latest_close": "wrong"}),
        ("status", []),
    ],
)
def test_malformed_company_payload_refused_before_render(field, value):
    combined = combine_snapshots(*snapshots())
    company = combined.company
    company[field] = value
    with pytest.raises(WorkSessionError):
        replace(combined, company_json=canonical(company))


def test_etf_never_enters_company_model():
    h, c = snapshots("00935", kind="ETF")
    combined = combine_snapshots(h, c)
    assert not combined.company["explanations"]
    with pytest.raises(WorkSessionError):
        select_public_evidence(combined, PUBLIC_QUESTIONS[0])
    bad_profile = replace(c.company_profile, dossier=snapshots()[1].company_profile.dossier)
    with pytest.raises(WorkSessionError):
        combine_snapshots(h, replace(c, company_profile=bad_profile))


def test_private_canaries_never_enter_outbound_payload():
    session = work()
    h = session.snapshot.holding
    h["observations"].append("CANARY_WEIGHT_0.7341 other holding JPM CANARY_OTHER")
    h["data"].append(
        dict(
            label="CANARY_ACCOUNT",
            value="CANARY_QUANTITY_COST_PNL",
            source="C:\\secret\\CANARY_PATH",
            as_of="不適用",
            fetched_at="不適用",
            status="可用",
            reason="CANARY_NOTE",
        )
    )
    combined = CombinedSnapshot(
        session.snapshot.identity, canonical(h), session.snapshot.company_json, NOW.isoformat()
    )
    selection = select_public_evidence(combined, PUBLIC_QUESTIONS[0])
    assert selection.payload["evidence"]
    assert "CANARY" not in selection.payload_json
    assert "JPM" not in selection.payload_json
    assert set(selection.payload) == {"identity", "question", "evidence"}
    for item in selection.payload["evidence"]:
        assert set(item) == {"evidence_id", "text", "url", "content_date", "retrieved_at"}
    with pytest.raises(WorkSessionError):
        select_public_evidence(combined, session.question)


def test_selection_manifest_can_reproduce_exact_selected_excerpts():
    selection = select_public_evidence(work().snapshot, PUBLIC_QUESTIONS[0], max_records=1)
    assert selection.manifest["request_fingerprint"] == digest(selection.payload)
    for selected, outbound in zip(
        selection.manifest["selected"], selection.payload["evidence"], strict=True
    ):
        assert selected["excerpt"] == outbound["text"]
        assert selected["excerpt_fingerprint"] == digest(outbound["text"])
    assert selection.manifest["omitted"]
    assert "未完整" in selection.manifest["coverage_label"]


@pytest.mark.parametrize(
    "change", ["hash", "identity", "version", "missing_dependency", "truncated", "duplicate"]
)
def test_persisted_corruption_is_rejected(tmp_path, change):
    store = WorkSessionStore(tmp_path / "new")
    key = store.save(work())
    path = store.directory / f"{key}.json"
    value = json.loads(path.read_bytes())
    if change == "hash":
        value["question"] = "tamper"
    elif change == "identity":
        value["snapshot"]["identity"]["symbol"] = "JPM"
    elif change == "version":
        value["version"] = 99
    elif change == "missing_dependency":
        del value["snapshot"]["company"]["profile"]["dossier"]["documents"]
    if change == "truncated":
        path.write_bytes(b'{"format":')
    elif change == "duplicate":
        path.write_text('{"version":1,"version":1}', encoding="utf-8")
    else:
        path.write_text(canonical(value), encoding="utf-8")
    with pytest.raises(WorkSessionError):
        store.load(key)


def test_backup_restore_reboot_and_reject_before_writes(tmp_path):
    store = WorkSessionStore(tmp_path / "sessions")
    key = store.save(work())
    backup = store.backup_bytes()
    restored = WorkSessionStore(tmp_path / "restored")
    restored.restore_bytes(backup)
    assert WorkSessionStore(restored.directory).load(key).to_dict() == store.load(key).to_dict()
    bad = json.loads(backup)
    bad["payload"]["sessions"][key]["snapshot"]["holding"]["symbol"] = "JPM"
    bad["fingerprint"] = digest(bad["payload"])
    target = WorkSessionStore(tmp_path / "rejected")
    with pytest.raises(WorkSessionError):
        target.restore_bytes(canonical(bad).encode())
    assert not target.directory.exists()
    assert restored.backup_bytes() == backup


def test_existing_session_cannot_be_overwritten_and_paths_rejected(tmp_path):
    store = WorkSessionStore(tmp_path)
    key = store.save(work())
    original = (tmp_path / f"{key}.json").read_bytes()
    assert store.save(store.load(key)) == key
    assert (tmp_path / f"{key}.json").read_bytes() == original
    for malicious in ("../secret", "C:/private", "x" * 64):
        with pytest.raises(WorkSessionError):
            store.load(malicious)


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_library_and_new_sessions_backup_restore_coexist(tmp_path, version):
    from stock_tool.research.assistant import AIResearchAssistant, ResearchAssistantCache
    from stock_tool.research.library import ResearchLibrary, _content_hash

    old = ResearchLibrary(tmp_path / "research_library")
    bundle = snapshots()[0].evidence_bundle()
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "ai_cache")).generate(bundle)
    entry = old.save(bundle=bundle, note=note, title="unchanged legacy")
    path = old.entry_path(entry.library_entry_id)
    if version == 1:
        raw = entry.to_dict()
        raw["schema_version"] = 1
        raw["content_hash"] = _content_hash(entry.note, entry.bundle)
        raw.pop("document_references")
        path.write_text(canonical(raw), encoding="utf-8")
    before = path.read_bytes()
    store = WorkSessionStore(tmp_path / "research_work_sessions")
    key = store.save(work())
    saved_backup = store.backup_bytes()
    library_backup = old.create_backup(tmp_path / "legacy.zip")
    restored_old = ResearchLibrary(tmp_path / "new_runtime" / "research_library")
    restored_old.restore(library_backup.archive_path)
    restored_new = WorkSessionStore(tmp_path / "new_runtime" / "research_work_sessions")
    restored_new.restore_bytes(saved_backup)
    assert (
        ResearchLibrary(restored_old.directory).get(entry.library_entry_id).schema_version
        == version
    )
    assert WorkSessionStore(restored_new.directory).load(key).fingerprint == key
    assert restored_old.entry_path(entry.library_entry_id).read_bytes() == before
    assert path.read_bytes() == before
    # Corruption is refused independently; a valid new session cannot mask it.
    restored_old.entry_path(entry.library_entry_id).write_bytes(b'{"corrupt":')
    assert ResearchLibrary(restored_old.directory).get(entry.library_entry_id) is None
    assert restored_new.load(key).fingerprint == key


def test_append_restore_never_overwrites_or_partially_accepts_invalid_backup(tmp_path):
    store = WorkSessionStore(tmp_path / "work")
    key = store.save(work())
    before = (store.directory / f"{key}.json").read_bytes()
    backup = store.backup_bytes()
    store.restore_bytes(backup, append_only=True)
    assert (store.directory / f"{key}.json").read_bytes() == before
    broken = json.loads(backup)
    broken["payload"]["sessions"][key]["version"] = 999
    broken["fingerprint"] = digest(broken["payload"])
    with pytest.raises(WorkSessionError):
        store.restore_bytes(canonical(broken).encode(), append_only=True)
    assert store.backup_bytes() == backup


def test_generic_ai_jobs_commentary_is_not_company_specific_risk():
    doc = CompanyDocument(
        "https://example.com/ir/report",
        "Annual report",
        "Artificial intelligence may transform employment amid recession and credit risk.\n"
        "Our business faces adverse effects from interest rate volatility and credit loss.",
        "2026-09-01",
        NOW.isoformat(),
    )
    dossier = build_dossier("JPM", "US", "https://example.com", (doc,))
    risks = [f.excerpt for f in dossier.facts if f.section == "公司揭露的風險"]
    assert len(risks) == 1
    assert "Our business" in risks[0]


def test_bank_plain_and_word_keeps_same_business_explanation():
    from stock_tool.company_explanation import explain_company

    _, company = snapshots("JPM", "US")
    text = " ".join(item.text for item in explain_company(company.company_profile.dossier))
    assert "消費與社區銀行" in text
    assert "存放款利差" in text


def test_real_renderers_switch_save_return_and_restart(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    runtime = tmp_path / "stocktool-workflow-app-test"
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    monkeypatch.setenv("STOCK_TOOL_AI_API_KEY", "")
    script = Path(__file__).resolve().parents[1] / "scripts/research_workflow_review_app.py"
    app = AppTest.from_file(str(script)).run(timeout=20)
    assert not app.exception
    app.selectbox(key="portfolio_workspace_research_identity").select("3006 / TWSE").run()
    question = next(item for item in app.text_area if item.label == "我的研究問題（只保存在本機）")
    question.set_value("CANARY_UI_3006 private question")
    next(item for item in app.button if item.label == "保存這次持股與公司研究").click().run()
    assert not app.exception
    store = WorkSessionStore(runtime / "data" / "research_work_sessions")
    (key,) = store.keys()
    assert store.load(key).question == "CANARY_UI_3006 private question"
    app.button(key="portfolio_workspace_return_research").click().run()
    assert app.text_input(key="research_global_symbol").value == "3006"
    # AppTest retains removed widgets after an explicit rerun; use a fresh
    # research tree for subsequent form interactions. Browser covers the route.
    app = AppTest.from_file(str(script))
    app.session_state["review_page"] = "公司研究"
    app.session_state["review_company"] = ("3006", "TWSE")
    app.run(timeout=20)
    # Simulate the already validated router's completed company switch.
    app.session_state["review_company"] = ("JPM", "US")
    app.run()
    assert app.text_input(key="research_global_symbol").value == "JPM"
    assert app.selectbox(key="research_global_market").value == "美股 US"
    app.button(key="research_to_holdings").click().run()
    assert app.selectbox(key="portfolio_workspace_research_identity").value == "JPM / US"
    assert not app.exception
    # A new Streamlit session reads the persisted research without live providers.
    restarted = AppTest.from_file(str(script)).run(timeout=20)
    next(item for item in restarted.button if item.label == "前往研究庫").click().run()
    assert not restarted.exception
    assert any("CANARY_UI_3006" in str(item.value) for item in restarted.text)
    assert store.load(key).snapshot.identity.symbol == "3006"
