from copy import deepcopy
import json

import pytest

from stock_tool.research.semantic_review import AXES, assess_review, review_input
from stock_tool.research.work_session import canonical, digest
from test_citation_preflight import example


def reviewed_example():
    snapshot, request, answer = example()
    public = json.loads(request.payload_json)
    raw = canonical(answer)
    assessment = {
        "claim_id": "c1",
        **dict.fromkeys(AXES, True),
        "support_quotes": [answer["claims"][0]["citations"][0]["quote"]],
        "explanation": "原文直接列出此項產品。",
    }
    review = {"identity": public["identity"], "assessments": [assessment]}
    receipt = {
        "version": 1,
        "input_fingerprint": digest(json.loads(review_input(public, raw))),
        "raw_response": canonical(review),
        "finish_reason": "stop",
    }
    return snapshot, request, raw, review, receipt


def test_complete_review_is_explicitly_model_reviewed_not_proven():
    _, request, raw, _, receipt = reviewed_example()
    result = assess_review(json.loads(request.payload_json), raw, receipt)
    assert result.status == "model_reviewed"
    assert "不是人工驗證" in result.reasons[0]


@pytest.mark.parametrize("axis", AXES)
def test_any_failed_semantic_axis_invalidates_whole_result(axis):
    _, request, raw, review, receipt = reviewed_example()
    review["assessments"][0][axis] = False
    receipt["raw_response"] = canonical(review)
    assert assess_review(json.loads(request.payload_json), raw, receipt).status == "invalid"


@pytest.mark.parametrize(
    "case",
    [
        "other_company",
        "missing",
        "duplicate",
        "invented_quote",
        "no_quote",
        "string_bool",
        "truncated",
        "wrong_binding",
    ],
)
def test_malformed_or_unbound_review_fails_closed(case):
    _, request, raw, review, receipt = reviewed_example()
    if case == "other_company":
        review["identity"]["symbol"] = "JPM"
    elif case == "missing":
        review["assessments"] = []
    elif case == "duplicate":
        review["assessments"] *= 2
    elif case == "invented_quote":
        review["assessments"][0]["support_quotes"] = ["This company earns $100 billion."]
    elif case == "no_quote":
        review["assessments"][0]["support_quotes"] = []
    elif case == "string_bool":
        review["assessments"][0]["correct_entity"] = "true"
    elif case == "truncated":
        receipt["finish_reason"] = "length"
    else:
        receipt["input_fingerprint"] = "0" * 64
    receipt["raw_response"] = canonical(review)
    assert assess_review(json.loads(request.payload_json), raw, receipt).status == "invalid"


def test_review_receipt_replays_after_save_backup_restore_without_provider(tmp_path):
    from stock_tool.research.ai_attempt import record_attempt
    from stock_tool.research.public_request import RequestOutcome
    from stock_tool.research.work_session import ResearchWorkSession, WorkSessionStore

    snapshot, request, raw, _, receipt = reviewed_example()
    timestamp = "2026-09-14T01:00:00+00:00"
    outcome = RequestOutcome(
        "received_unverified", "", timestamp, raw, timestamp, canonical(receipt)
    )
    attempt = record_attempt(
        snapshot,
        request,
        outcome,
        provider="test",
        model="test",
        started_at=timestamp,
        completed_at=timestamp,
    )
    session = ResearchWorkSession(snapshot, "CANARY_PRIVATE", timestamp, attempt)
    original, restored = WorkSessionStore(tmp_path / "a"), WorkSessionStore(tmp_path / "b")
    key = original.save(session)
    restored.restore_bytes(original.backup_bytes())
    assert restored.load(key) == session
    assert json.loads(session.ai_attempt_json)["status"] == "model_reviewed"
    changed = deepcopy(session.to_dict())
    changed["ai_attempt"]["review"]["input_fingerprint"] = "0" * 64
    with pytest.raises(ValueError):
        ResearchWorkSession.from_dict(changed)


def test_counter_relation_is_only_required_for_counterclaims_and_v1_is_unchanged():
    _, request, raw, review, receipt = reviewed_example()
    public = json.loads(request.payload_json)
    review["assessments"][0]["real_counterargument"] = False
    receipt["raw_response"] = canonical(review)
    assert assess_review(public, raw, receipt).status == "invalid"  # historical v1
    receipt["version"] = 2
    assert assess_review(public, raw, receipt).status == "model_reviewed"
    answer = json.loads(raw)
    counter = deepcopy(answer["claims"][0])
    counter.update(id="c2", kind="counter_evidence", counter_to="c1", text="但公司也有 DDR4 產品。")
    answer["claims"].append(counter)
    assessment = deepcopy(review["assessments"][0])
    assessment["claim_id"] = "c2"
    review["assessments"].append(assessment)
    raw = canonical(answer)
    receipt.update(
        input_fingerprint=digest(json.loads(review_input(public, raw))),
        raw_response=canonical(review),
    )
    assert assess_review(public, raw, receipt).status == "invalid"
