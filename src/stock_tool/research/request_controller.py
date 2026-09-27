"""Session-local request lifecycle independent of Streamlit and network setup."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Callable

from stock_tool.research.ai_attempt import record_attempt
from stock_tool.research.public_request import (
    PreparedPublicRequest,
    PublicRequestJob,
    PublicResponse,
    RequestOutcome,
)
from stock_tool.research.work_session import CombinedSnapshot, WorkSessionError


class ResearchRequestController:
    def __init__(self) -> None:
        self.job: PublicRequestJob | None = None
        self.attempt_json = "null"
        self.provider = ""
        self.model = ""

    def discard(self) -> None:
        if self.job:
            self.job.poll("")
        self.job = None
        self.attempt_json = "null"

    def synchronize(self, snapshot: CombinedSnapshot) -> None:
        if self.job and self.job.prepared.snapshot_fingerprint != snapshot.fingerprint:
            self.discard()

    def start(
        self,
        snapshot: CombinedSnapshot,
        request: PreparedPublicRequest,
        transport: Callable[[bytes], PublicResponse],
        *,
        provider: str,
        model: str,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.synchronize(snapshot)
        if self.job and self.job.poll(snapshot.fingerprint).status == "pending":
            raise WorkSessionError("AI 請求仍在處理，未重複傳送。")
        if not provider or not model or len(provider) > 120 or len(model) > 120:
            raise WorkSessionError("供應商與模型尚未確認。")
        self.job = PublicRequestJob(snapshot, request, transport, timeout_seconds=timeout_seconds)
        self.provider, self.model = provider, model
        self.attempt_json = "null"

    def poll(self, snapshot: CombinedSnapshot) -> str:
        self.synchronize(snapshot)
        if self.job is None:
            return "idle"
        outcome = self.job.poll(snapshot.fingerprint)
        if outcome.status == "pending":
            return "pending"
        if self.attempt_json == "null":
            try:
                self.attempt_json = record_attempt(
                    snapshot,
                    self.job.prepared,
                    outcome,
                    provider=self.provider,
                    model=self.model,
                    started_at=self.job.started_at,
                    completed_at=datetime.now(UTC).isoformat(),
                )
            except (ValueError, TypeError, KeyError, OverflowError):
                # Untrusted response metadata must never break local UI/save.
                self.attempt_json = record_attempt(
                    snapshot,
                    self.job.prepared,
                    RequestOutcome("invalid", "模型回應或時間格式無效。"),
                    provider=self.provider,
                    model=self.model,
                    started_at=self.job.started_at,
                    completed_at=datetime.now(UTC).isoformat(),
                )
                return "invalid"
        return str(json.loads(self.attempt_json)["status"])
