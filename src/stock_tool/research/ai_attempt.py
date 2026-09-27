"""Locally persisted, unverified AI attempts bound to exact public evidence."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from stock_tool.research.citation_preflight import preflight_citations
from stock_tool.research.semantic_review import assess_review
from stock_tool.research.public_request import PreparedPublicRequest, RequestOutcome
from stock_tool.research.work_session import (
    CombinedSnapshot,
    WorkSessionError,
    canonical,
)


def validate_attempt(value: Any, snapshot: CombinedSnapshot) -> None:
    """Recompute citation status on load; persisted labels cannot grant validity."""
    if not isinstance(value, dict):
        raise WorkSessionError("AI 紀錄格式無效。")
    version = value.get("version")
    fields = {
        "version",
        "provider",
        "model",
        "started_at",
        "completed_at",
        "snapshot_fingerprint",
        "payload",
        "selection",
        "status",
        "raw_response",
    }
    if version == 2:
        fields |= {"generated_at", "review"}
    if set(value) != fields:
        raise WorkSessionError("AI 紀錄格式無效。")
    if type(version) is not int or version not in (1, 2):
        raise WorkSessionError("不支援的 AI 紀錄版本。")
    for name in ("provider", "model"):
        if not isinstance(value[name], str) or not 1 <= len(value[name]) <= 120:
            raise WorkSessionError("AI 供應商或模型紀錄無效。")
    times = []
    for name in ("started_at", "completed_at"):
        try:
            parsed = datetime.fromisoformat(value[name])
            if parsed.tzinfo is None:
                raise ValueError("timezone")
            times.append(parsed)
        except (TypeError, ValueError) as exc:
            raise WorkSessionError("AI 時間紀錄無效。") from exc
    if times[1] < times[0]:
        raise WorkSessionError("AI 完成時間早於開始時間。")
    if version == 2 and value["generated_at"] is not None:
        try:
            generated = datetime.fromisoformat(value["generated_at"])
            # Provider timestamps have second precision; allow clock skew only.
            if generated.tzinfo is None or not (
                times[0].timestamp() - 120 <= generated.timestamp() <= times[1].timestamp() + 120
            ):
                raise ValueError("provider clock")
        except (TypeError, ValueError):
            raise WorkSessionError("AI 供應商產生時間無效。") from None
    request = PreparedPublicRequest(
        value["snapshot_fingerprint"],
        canonical(value["payload"]),
        canonical(value["selection"]),
    )
    request.verify(snapshot)
    raw = value["raw_response"]
    status = value["status"]
    if raw is None:
        if version == 2 and (value["review"] is not None or value["generated_at"] is not None):
            raise WorkSessionError("無原文卻存在模型核對紀錄。")
        if status not in ("failed", "timed_out", "superseded", "invalid"):
            raise WorkSessionError("AI 結果狀態與內容不符。")
    else:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 96_000:
            raise WorkSessionError("AI 原始回應無效或過大。")
        expected = (
            assess_review(value["payload"], raw, value["review"]).status
            if version == 2
            else preflight_citations(raw, snapshot, request).status
        )
        if status != expected:
            raise WorkSessionError("AI 驗證狀態不符；不能以保存標籤冒充有效結論。")


def record_attempt(
    snapshot: CombinedSnapshot,
    request: PreparedPublicRequest,
    outcome: RequestOutcome,
    *,
    provider: str,
    model: str,
    started_at: str,
    completed_at: str,
) -> str:
    if outcome.status == "pending":
        raise WorkSessionError("AI 尚未完成，請先保存本機研究。")
    raw = outcome.raw_response
    status = outcome.status
    review = json.loads(outcome.review_json) if outcome.review_json is not None else None
    modern = outcome.generated_at is not None or review is not None
    if raw is not None:
        status = (
            assess_review(json.loads(request.payload_json), raw, review).status
            if modern
            else preflight_citations(raw, snapshot, request).status
        )
    value = {
        "version": 2 if modern else 1,
        "provider": provider,
        "model": model,
        "started_at": started_at,
        "completed_at": outcome.completed_at or completed_at,
        "snapshot_fingerprint": request.snapshot_fingerprint,
        "payload": json.loads(request.payload_json),
        "selection": json.loads(request.manifest_json),
        "status": status,
        "raw_response": raw,
    }
    if modern:
        value.update(generated_at=outcome.generated_at, review=review)
    validate_attempt(value, snapshot)
    return canonical(value)
