"""Explicit, zero-cost-account probe using public documents and synthetic holdings.

Never reads the user's portfolio. Saves only public payloads, model receipts and
isolated synthetic sessions. Requires --free-account-confirmed; no retries.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--free-account-confirmed", action="store_true")
    args = parser.parse_args()
    if not args.free_account_confirmed:
        print("No request sent: explicit Free-account confirmation required.")
        return 2

    from stock_tool.company_documents import fetch_company_document
    from stock_tool.company_dossier import build_dossier
    from stock_tool.research.groq_transport import LocalGroqTransport, DEFAULT_MODEL
    from stock_tool.research.public_request import PreparedPublicRequest, RequestOutcome
    from stock_tool.research.public_selection import PUBLIC_QUESTIONS
    from stock_tool.research.ai_attempt import record_attempt
    from stock_tool.research.work_session import (
        ResearchWorkSession,
        WorkSessionStore,
        canonical,
        combine_snapshots,
    )
    from test_research_work_session import snapshots

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "docs/product/research-workflow-evidence" / (stamp + "-groq-live")
    out.mkdir(exist_ok=False)
    started = datetime.now(UTC).isoformat()
    summary = {
        "started_at": started,
        "model": DEFAULT_MODEL,
        "account_free_user_confirmed": True,
        "real_holdings_accessed": False,
    }
    try:
        document = fetch_company_document(
            "https://www.jpmorganchase.com/about", origin="https://www.jpmorganchase.com"
        )
        (out / "public-document.json").write_text(canonical(asdict(document)), encoding="utf-8")
        holding, company = snapshots("JPM", "US")
        dossier = build_dossier(
            "JPM", "US", "https://www.jpmorganchase.com", (document,), checked_at=started
        )
        company = replace(
            company,
            company_profile=replace(
                company.company_profile, company_name="JPMorgan Chase & Co.", dossier=dossier
            ),
        )
        snapshot = combine_snapshots(holding, company)
        request = PreparedPublicRequest.prepare(snapshot, PUBLIC_QUESTIONS[0])
        assert "CANARY" not in request.payload_json
        (out / "public-payload.json").write_text(request.payload_json, encoding="utf-8")
        response = LocalGroqTransport(True)(request.payload_json.encode("utf-8"))
        completed = datetime.now(UTC).isoformat()
        outcome = RequestOutcome(
            "received_unverified",
            "",
            completed,
            response.content,
            response.generated_at,
            response.review_json,
        )
        if response.finish_reason != "stop":
            outcome = RequestOutcome("invalid", "truncated", completed)
        attempt = record_attempt(
            snapshot,
            request,
            outcome,
            provider="Groq",
            model=DEFAULT_MODEL,
            started_at=started,
            completed_at=completed,
        )
        # Receipt contains the exact public selection; never includes private question.
        assert "CANARY" not in attempt
        (out / "attempt.json").write_text(attempt, encoding="utf-8")
        runtime = Path(tempfile.mkdtemp(prefix="stocktool-workflow-groq-"))
        store, restored = WorkSessionStore(runtime / "original"), WorkSessionStore(
            runtime / "restored"
        )
        session = ResearchWorkSession(snapshot, "CANARY_PRIVATE_LOCAL_ONLY", completed, attempt)
        key = store.save(session)
        restored.restore_bytes(store.backup_bytes())
        assert restored.load(key) == session
        summary.update(
            status=json.loads(attempt)["status"],
            finish_reason=response.finish_reason,
            selected_evidence=len(json.loads(request.payload_json)["evidence"]),
            saved_restore_equal=True,
            runtime=str(runtime),
            completed_at=completed,
        )
        print(canonical({k: v for k, v in summary.items() if k != "runtime"}))
        return 0
    except Exception as exc:
        summary.update(status="probe_failed", error_type=type(exc).__name__)
        summary.update(
            error_category=getattr(exc, "category", None),
            http_status=getattr(exc, "status_code", None),
        )
        print(canonical(summary))
        return 1
    finally:
        (out / "summary.json").write_text(canonical(summary), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
