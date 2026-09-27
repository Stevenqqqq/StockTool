import json

import pytest

from stock_tool.research.citation_preflight import preflight_citations
from stock_tool.research.citation_preflight import _numeric_values
from stock_tool.research.public_request import PreparedPublicRequest
from stock_tool.research.public_selection import PUBLIC_QUESTIONS
from stock_tool.research.work_session import canonical, combine_snapshots
from test_research_work_session import snapshots


def example():
    snapshot = combine_snapshots(*snapshots())
    request = PreparedPublicRequest.prepare(snapshot, PUBLIC_QUESTIONS[0])
    payload = json.loads(request.payload_json)
    evidence = payload["evidence"][0]
    answer = {
        "identity": payload["identity"],
        "claims": [
            {
                "id": "c1",
                "text": "公司列有 DDR4 產品。",
                "kind": "company_fact",
                "citations": [{"evidence_id": evidence["evidence_id"], "quote": evidence["text"]}],
                "counter_to": None,
            }
        ],
    }
    return snapshot, request, answer


def test_matching_citation_is_not_semantic_acceptance():
    snapshot, request, answer = example()
    assert preflight_citations(canonical(answer), snapshot, request).status == "unverified"


@pytest.mark.parametrize(
    "mutation", ["company", "missing_id", "quote", "number", "condition", "counter", "duplicate_id"]
)
def test_demonstrable_citation_errors_invalidate_whole_answer(mutation):
    snapshot, request, answer = example()
    claim = answer["claims"][0]
    if mutation == "company":
        answer["identity"]["symbol"] = "JPM"
    elif mutation == "missing_id":
        claim["citations"][0]["evidence_id"] = "company.fact.999"
    elif mutation == "quote":
        claim["citations"][0]["quote"] = "Invented text"
    elif mutation == "number":
        claim["text"] = "DDR4 營收占比 80%。"
    elif mutation == "condition":
        claim["kind"] = "conditional_risk"
        claim["text"] = "產品價格下跌已造成公司虧損。"
    elif mutation == "counter":
        claim["kind"] = "counter_evidence"
        claim["counter_to"] = "missing"
    else:
        answer["claims"].append(dict(claim))
    assert preflight_citations(canonical(answer), snapshot, request).status == "invalid"


@pytest.mark.parametrize(
    "text",
    [
        "公司毛利率很高。",
        "產業成長證明這家公司正在成長。",
        "缺少資料證明公司沒有風險。",
    ],
)
def test_semantically_unsupported_but_well_formed_claim_never_passes(text):
    snapshot, request, answer = example()
    answer["claims"][0]["text"] = text
    result = preflight_citations(canonical(answer), snapshot, request)
    assert result.status == "unverified"
    # These still require real semantic rejection, not a structural success claim.
    assert "語意驗證" in result.reasons[0]


def test_duplicate_json_keys_rejected():
    snapshot, request, answer = example()
    raw = canonical(answer)
    raw = raw.replace('"claims":', '"claims":[],"claims":', 1)
    assert preflight_citations(raw, snapshot, request).status == "invalid"


def test_exact_chinese_english_numeric_scaling_without_weakening_mismatch_check():
    assert _numeric_values("8000萬人") == _numeric_values("80 million people")
    assert _numeric_values("1.2億") == _numeric_values("120 million")
    assert _numeric_values("80%") != _numeric_values("80")
    assert _numeric_values("800萬人") != _numeric_values("80 million people")
    assert _numeric_values("DDR4") != _numeric_values("DDR5")
