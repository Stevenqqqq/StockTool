"""Explicit outbound allowlist. Never accepts a portfolio or free-form prompt.

The local question is deliberately not an input to this serializer. The user
chooses a public research question after seeing the transmission preview.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import re
from typing import Any
from urllib.parse import urlsplit

from stock_tool.company_documents import public_url
from stock_tool.research.work_session import CombinedSnapshot, WorkSessionError, canonical, digest

PUBLIC_QUESTIONS = (
    "這家公司提供哪些產品或服務，如何賺錢？",
    "目前證據支持哪些公司風險，哪些條件仍未確認？",
    "哪些證據支持或反駁目前的公司業務判斷？",
)
_PRIVATE = re.compile(
    r"(?<![A-Z0-9])[A-Z]:[\\/]|\\\\|file:|localhost|127\.0\.0\.1|"
    r"[\w.+-]+@[\w.-]+\.[A-Z]{2,}|(?:api[_ -]?key|token|password|帳戶|帳號|我的持股|"
    r"平均成本|未實現損益|我的權重|my portfolio|my holdings|my account)",
    re.I,
)


@dataclass(frozen=True)
class PublicSelection:
    """Local manifest includes omitted evidence; outbound data contains only selected fields."""

    payload_json: str
    manifest_json: str

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    @property
    def manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest_json)

    @property
    def fingerprint(self) -> str:
        return digest(self.payload)


def select_public_evidence(
    snapshot: CombinedSnapshot,
    public_question: str,
    *,
    max_characters: int = 16000,
    max_records: int = 20,
    selection_version: int = 2,
) -> PublicSelection:
    """Build from empty data, with no arbitrary questions or context passthrough."""
    if public_question not in PUBLIC_QUESTIONS:
        raise WorkSessionError("外部問題須改寫為公開公司問題；原始研究問題只留在本機。")
    if snapshot.identity.instrument_type != "股票":
        raise WorkSessionError("ETF 不進入公司 AI 模型。")
    if not (1 <= max_records <= 40 and 500 <= max_characters <= 32000):
        raise WorkSessionError("AI 證據選取上限無效。")
    if type(selection_version) is not int or selection_version not in (1, 2):
        raise WorkSessionError("不支援的證據選取版本。")
    company = snapshot.company
    dossier = company["profile"].get("dossier")
    rows: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    size = 0
    offsets: dict[str, tuple[int, int]] = {}
    facts = dossier["facts"] if dossier else []
    for index, fact in enumerate(facts):
        evidence_id = f"company.fact.{index}"
        reason = ""
        url = fact["url"]
        excerpt = fact["excerpt"]
        start = 0
        if selection_version == 2:
            document = next(doc for doc in dossier["documents"] if doc["url"] == url)
            original = document["text"]
            start = original.index(excerpt)
            end = start + len(excerpt)
            # Keep a service heading and its adjacent explanatory sentence together.
            # Only contiguous verbatim source text: no generated glue or guessed facts.
            tail = original[end:]
            adjacent = re.match(
                r"\n((?:Providing|Helping|Offering|We provide|提供|協助)[^\n]{15,900})", tail
            )
            if len(excerpt) <= 100 and adjacent:
                excerpt += adjacent.group(0)
        offsets[evidence_id] = (start, start + len(excerpt))
        try:
            parsed = urlsplit(public_url(url, dossier["website"]))
            # Never send query strings, fragments or potentially private URLs.
            if parsed.query or urlsplit(url).fragment or _PRIVATE.search(url):
                raise ValueError("private url")
        except (ValueError, TypeError):
            reason = "來源網址不符合公開傳送規則"
        if _PRIVATE.search(excerpt):
            reason = "原文疑似包含個人或敏感內容"
        try:
            for value in (fact["published_at"], fact["fetched_at"]):
                if value:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            reason = "來源日期格式無法確認"
        if dossier["state"] != "fresh" or company["status"] in {"stale", "error"}:
            reason = "公司證據尚未確認有效"
        # Entire excerpts are selected or omitted; no silent text truncation.
        row = {
            "evidence_id": evidence_id,
            "text": excerpt,
            "url": url,
            "content_date": fact["published_at"] or None,
            "retrieved_at": fact["fetched_at"] or None,
        }
        length = len(canonical(row))
        if len(rows) >= max_records or size + length > max_characters:
            reason = "本次模型輸入上限，未送出此項證據"
        if reason:
            omitted.append({"evidence_id": evidence_id, "reason": reason})
            continue
        rows.append(row)
        size += length
    payload = {"identity": asdict(snapshot.identity), "question": public_question, "evidence": rows}
    manifest = {
        "selection_version": selection_version,
        "company_fingerprint": snapshot.company_fingerprint,
        "request_fingerprint": digest(payload),
        "public_question": public_question,
        "selected": [
            {
                "evidence_id": row["evidence_id"],
                "excerpt": row["text"],
                "excerpt_fingerprint": digest(row["text"]),
                "start": offsets[row["evidence_id"]][0],
                "end": offsets[row["evidence_id"]][1],
            }
            for row in rows
        ],
        "omitted": omitted,
        "total_company_facts": len(facts),
        "coverage_label": "僅選取的公司原文；未完整審閱本機文件",
    }
    return PublicSelection(canonical(payload), canonical(manifest))
