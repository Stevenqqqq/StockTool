"""Reject demonstrably broken citations before semantic review.

Passing this structural check is deliberately *not* semantic acceptance. An
existing ID, a matching quote and matching numbers do not establish entailment.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
import re
from typing import Any

from stock_tool.research.public_request import PreparedPublicRequest
from stock_tool.research.work_session import CombinedSnapshot

_NUMBER = re.compile(
    r"(?<!\d)(\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(trillion|billion|million|thousand|兆|億|亿|萬|万|千|百)?\s*(%)?",
    re.I,
)
_SCALE = {
    "trillion": 10**12,
    "兆": 10**12,
    "billion": 10**9,
    "億": 10**8,
    "亿": 10**8,
    "million": 10**6,
    "萬": 10**4,
    "万": 10**4,
    "thousand": 1000,
    "千": 1000,
    "百": 100,
}


def _numeric_values(text: str) -> set[tuple[Decimal, bool]]:
    # Exact decimal scaling only. Currency, entity and period remain semantic checks.
    return {
        (
            Decimal(match[1].replace(",", "")) * _SCALE.get((match[2] or "").lower(), 1),
            bool(match[3]),
        )
        for match in _NUMBER.finditer(text)
    }


@dataclass(frozen=True)
class CitationPreflight:
    status: str
    reasons: tuple[str, ...]


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def preflight_citations(
    raw: str, snapshot: CombinedSnapshot, request: PreparedPublicRequest
) -> CitationPreflight:
    """All-or-nothing schema/quote checks; never returns a valid conclusion."""
    try:
        request.verify(snapshot)
    except (ValueError, TypeError, KeyError):
        return CitationPreflight("invalid", ("AI 請求與目前證據不符。",))
    return preflight_public_citations(raw, json.loads(request.payload_json))


def preflight_public_citations(raw: str, payload: dict[str, Any]) -> CitationPreflight:
    """Worker-side checks against the exact allowlisted public payload."""
    try:
        if len(raw.encode("utf-8")) > 96_000:
            raise ValueError("size")
        value = json.loads(raw, object_pairs_hook=_object)
        if not isinstance(value, dict) or set(value) != {"identity", "claims"}:
            raise ValueError("schema")
        if value["identity"] != payload["identity"]:
            return CitationPreflight("invalid", ("模型回應的市場、代號或類型不符。",))
        claims = value["claims"]
        if not isinstance(claims, list) or not 1 <= len(claims) <= 20:
            raise ValueError("claims")
        evidence = {row["evidence_id"]: row for row in payload["evidence"]}
        seen: dict[str, dict[str, Any]] = {}
        reasons: list[str] = []
        for claim in claims:
            if not isinstance(claim, dict) or set(claim) != {
                "id",
                "text",
                "kind",
                "citations",
                "counter_to",
            }:
                raise ValueError("claim schema")
            if (
                not isinstance(claim["id"], str)
                or not re.fullmatch(r"c[1-9][0-9]?", claim["id"])
                or claim["id"] in seen
                or not isinstance(claim["text"], str)
                or not 1 <= len(claim["text"]) <= 2000
                or claim["kind"]
                not in ("company_fact", "industry_context", "conditional_risk", "counter_evidence")
                or (claim["counter_to"] is not None and not isinstance(claim["counter_to"], str))
            ):
                raise ValueError("claim fields")
            seen[claim["id"]] = claim
            citations = claim["citations"]
            if not isinstance(citations, list) or not 1 <= len(citations) <= 8:
                raise ValueError("citations")
            quoted: list[str] = []
            for citation in citations:
                if not isinstance(citation, dict) or set(citation) != {"evidence_id", "quote"}:
                    raise ValueError("citation fields")
                identifier = citation["evidence_id"]
                if not isinstance(identifier, str) or identifier not in evidence:
                    reasons.append("引用不在本次實際送出的證據內。")
                    continue
                # Full selected excerpt; no model-created quote or omitted qualifier.
                if citation["quote"] != evidence[identifier]["text"]:
                    reasons.append("引用原文與送出摘錄不符。")
                    continue
                quoted.append(citation["quote"])
            source_text = " ".join(quoted)
            # Only rejects absent numeric literals. Matching literals still need
            # semantic review of units, dates, entity and applicable period.
            if not _numeric_values(claim["text"]).issubset(_numeric_values(source_text)):
                reasons.append("主張數字與引用原文不符，不能作為有依據的結論。")
            if claim["kind"] == "conditional_risk" and not re.search(
                r"若|如果|可能|尚待|仍待", claim["text"]
            ):
                reasons.append("條件風險缺少條件或不確定語氣。")
            if claim["kind"] != "counter_evidence" and claim["counter_to"] is not None:
                reasons.append("反證關係格式不符。")
        for claim in claims:
            if claim["kind"] == "counter_evidence":
                target = seen.get(claim["counter_to"])
                if target is None or target is claim or target["kind"] == "counter_evidence":
                    reasons.append("反面證據沒有指向可核對的原主張。")
                elif claim["citations"] == target["citations"] and claim["text"] == target["text"]:
                    reasons.append("重複原主張不能當成反面證據。")
        if reasons:
            return CitationPreflight("invalid", tuple(dict.fromkeys(reasons)))
        return CitationPreflight(
            "unverified",
            (
                "引用結構與原文相符，但公司歸屬、單位、日期、因果及反駁關係仍須語意驗證；不能當成已驗證結論。",
            ),
        )
    except (ValueError, TypeError, KeyError, RecursionError):
        return CitationPreflight("invalid", ("模型輸出或引用格式無效。",))
