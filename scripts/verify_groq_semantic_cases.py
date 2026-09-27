"""One explicit Free-account reviewer call over public evidence and labelled bad claims."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("public_payload", type=Path)
    parser.add_argument("--free-account-confirmed", action="store_true")
    parser.add_argument("--counterexample", action="store_true")
    parser.add_argument(
        "--case-group",
        choices=("all", "identity-units", "inference", "counter-date"),
        default="all",
    )
    args = parser.parse_args()
    if not args.free_account_confirmed:
        return 2
    from stock_tool.research.groq_transport import GroqTransport, DEFAULT_MODEL
    from stock_tool.research.local_credentials import load_groq_key
    from stock_tool.research.semantic_review import (
        AXES,
        REVIEW_VERSION,
        assess_review,
        review_input,
    )
    from stock_tool.research.work_session import canonical, digest
    from stock_tool.research.citation_preflight import preflight_public_citations

    public = json.loads(args.public_payload.read_text(encoding="utf-8"))
    rows = public["evidence"]
    cases = [
        ("supported", "公司提供資產與財富管理服務。", 0, "company_fact", None),
        ("wrong_company", "美光提供資產與財富管理服務。", 0, "company_fact", None),
        ("wrong_unit", "公司這項業務營收為8000萬美元。", 2, "company_fact", None),
        ("wrong_scope", "所有銀行都提供全球資產保管與支付服務。", 1, "industry_context", None),
        ("missing_data", "公司沒有信用風險。", 1, "company_fact", None),
        ("unsupported_causality", "若客戶成長，公司獲利可能翻倍。", 2, "conditional_risk", None),
        (
            "false_counter",
            "然而公司也提供消費者銀行服務，所以前述資產管理業務不存在。",
            2,
            "counter_evidence",
            "c1",
        ),
        ("unknown_date", "這是今天最新確認的公司技術人員現況。", 3, "company_fact", None),
    ]
    supported_ids = {1}
    if args.case_group == "identity-units":
        cases = cases[:4]
    elif args.case_group == "inference":
        cases = [cases[0], *cases[4:6]]
    elif args.case_group == "counter-date":
        cases = [cases[0], *cases[6:]]
    if args.counterexample:
        cases = [
            (
                "unsupported_exclusive_premise",
                "公司只經營資產與財富管理，沒有其他銀行業務。",
                0,
                "company_fact",
                None,
            ),
            (
                "genuine_counterexample",
                "公司也提供消費者與社區銀行服務，因此不是只經營資產與財富管理。",
                2,
                "counter_evidence",
                "c1",
            ),
            (
                "invalid_reverse_inference",
                "公司提供資產管理，因此沒有消費者銀行業務。",
                0,
                "company_fact",
                None,
            ),
        ]
        supported_ids = {2}
    claims = [
        {
            "id": f"c{i}",
            "text": text,
            "kind": kind,
            "counter_to": counter,
            "citations": [
                {"evidence_id": rows[index]["evidence_id"], "quote": rows[index]["text"]}
            ],
        }
        for i, (_, text, index, kind, counter) in enumerate(cases, 1)
    ]
    raw = canonical({"identity": public["identity"], "claims": claims})
    assert preflight_public_citations(raw, public).status == "unverified"
    out = (
        ROOT
        / "docs/product/research-workflow-evidence"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-groq-adversarial")
    )
    out.mkdir()
    (out / "public-review-input.json").write_text(review_input(public, raw), encoding="utf-8")
    try:
        response = GroqTransport(load_groq_key(), DEFAULT_MODEL, True).review(
            canonical(public).encode(), raw
        )
    except Exception as exc:
        summary = {
            "passed": False,
            "status": "provider_failed",
            "error_type": type(exc).__name__,
            "category": getattr(exc, "category", None),
            "http_status": getattr(exc, "status_code", None),
            "provider_code": getattr(exc, "provider_code", None),
            "model": DEFAULT_MODEL,
            "real_holdings_accessed": False,
        }
        (out / "summary.json").write_text(canonical(summary), encoding="utf-8")
        print(canonical(summary))
        return 1
    receipt = {
        "version": REVIEW_VERSION,
        "input_fingerprint": digest(json.loads(review_input(public, raw))),
        "raw_response": response.content,
        "finish_reason": response.finish_reason,
    }
    (out / "receipt.json").write_text(canonical(receipt), encoding="utf-8")
    decision = assess_review(public, raw, receipt)
    assessments = {a["claim_id"]: a for a in json.loads(response.content)["assessments"]}
    results = [
        {
            "case": case[0],
            "expected_supported": i in supported_ids,
            "observed_supported": all(
                assessments[f"c{i}"].get(axis) is True
                for axis in AXES
                if axis != "real_counterargument" or case[3] == "counter_evidence"
            ),
        }
        for i, case in enumerate(cases, 1)
    ]
    passed = decision.status == "invalid" and all(
        r["expected_supported"] == r["observed_supported"] for r in results
    )
    summary = {
        "passed": passed,
        "whole_answer_status": decision.status,
        "cases": results,
        "synthetic_claims_on_public_evidence": True,
        "real_holdings_accessed": False,
        "model": DEFAULT_MODEL,
        "generated_at": response.generated_at,
    }
    (out / "summary.json").write_text(canonical(summary), encoding="utf-8")
    print(canonical(summary))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
