"""Nonblocking public-evidence requests; responses are never implicitly valid.

This layer does not discover credentials or enable a provider. Its transport
receives only the reviewed public JSON bytes. Private snapshot bindings stay
on the UI side. A semantic validator must accept a response before publication.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import Callable

from stock_tool.research.public_selection import select_public_evidence
from stock_tool.research.work_session import CombinedSnapshot, WorkSessionError, canonical, digest

MAX_RESPONSE_BYTES = 96_000


@dataclass(frozen=True)
class PreparedPublicRequest:
    snapshot_fingerprint: str
    payload_json: str
    manifest_json: str

    @classmethod
    def prepare(
        cls, snapshot: CombinedSnapshot, public_question: str, *, selection_version: int = 2
    ) -> PreparedPublicRequest:
        # Revalidate rather than accepting a caller-supplied PublicSelection.
        checked = CombinedSnapshot.from_dict(snapshot.to_dict())
        selected = select_public_evidence(
            checked, public_question, selection_version=selection_version
        )
        if not selected.payload["evidence"]:
            raise WorkSessionError("沒有可傳送的公開公司證據，未建立 AI 請求。")
        return cls(checked.fingerprint, selected.payload_json, selected.manifest_json)

    def verify(self, snapshot: CombinedSnapshot) -> None:
        import json

        try:
            public_question = json.loads(self.payload_json)["question"]
            version = json.loads(self.manifest_json)["selection_version"]
            expected = self.prepare(snapshot, public_question, selection_version=version)
        except (ValueError, TypeError, KeyError) as exc:
            raise WorkSessionError("AI 傳送預覽已失效，請重新確認。") from exc
        if self != expected:
            raise WorkSessionError("AI 請求與目前證據不符，未傳送。")

    @property
    def request_fingerprint(self) -> str:
        import json

        return digest(json.loads(self.payload_json))


@dataclass(frozen=True)
class PublicResponse:
    content: str
    finish_reason: str
    generated_at: str | None = None
    review_json: str | None = None


@dataclass(frozen=True)
class RequestOutcome:
    # received_unverified is not a publishable or valid conclusion.
    status: str
    message: str
    completed_at: str | None = None
    raw_response: str | None = None
    generated_at: str | None = None
    review_json: str | None = None


class PublicRequestJob:
    """One explicit request; no automatic retries, no private-error logging.

    Polling never waits. Late responses are discarded after timeout or identity
    change. Transports must also impose their own network timeout; Python cannot
    forcibly stop a stalled provider thread.
    """

    def __init__(
        self,
        snapshot: CombinedSnapshot,
        prepared: PreparedPublicRequest,
        transport: Callable[[bytes], PublicResponse],
        *,
        timeout_seconds: float = 12.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not 0 < timeout_seconds <= 120:
            raise WorkSessionError("AI 等待時間設定無效。")
        prepared.verify(snapshot)
        self.prepared = prepared
        self.started_at = datetime.now(UTC).isoformat()
        self._clock = clock
        self._deadline = clock() + timeout_seconds
        self._terminal: RequestOutcome | None = None
        self._queue: Queue[tuple[float, RequestOutcome]] = Queue(maxsize=1)
        # The worker closure holds bytes, never the snapshot or original question.
        payload = prepared.payload_json.encode("utf-8")
        queue = self._queue

        def run() -> None:
            try:
                response = transport(payload)
                completed = datetime.now(UTC).isoformat()
                if not isinstance(response, PublicResponse) or not isinstance(
                    response.content, str
                ):
                    outcome = RequestOutcome("invalid", "模型回應格式無效。", completed)
                elif response.finish_reason != "stop":
                    outcome = RequestOutcome(
                        "invalid", "模型回應未完整完成，不能作為結論。", completed
                    )
                elif len(response.content.encode("utf-8")) > MAX_RESPONSE_BYTES:
                    outcome = RequestOutcome(
                        "invalid", "模型回應超過上限，不能作為結論。", completed
                    )
                else:
                    outcome = RequestOutcome(
                        "received_unverified",
                        "已收到回應，尚未通過引用語意驗證。",
                        completed,
                        response.content,
                        response.generated_at,
                        response.review_json,
                    )
            except Exception:
                # Provider errors may contain keys, URLs or echoed prompts.
                outcome = RequestOutcome(
                    "failed", "外部 AI 請求失敗；本機分析仍可用。", datetime.now(UTC).isoformat()
                )
            queue.put((clock(), outcome))

        Thread(target=run, name="stock-tool-public-research", daemon=True).start()

    def poll(self, current_snapshot_fingerprint: str) -> RequestOutcome:
        if current_snapshot_fingerprint != self.prepared.snapshot_fingerprint:
            self._terminal = RequestOutcome(
                "superseded", "證據或標的已變更，舊回應不套用到目前研究。"
            )
        if self._terminal is not None:
            return self._terminal
        try:
            completed_time, outcome = self._queue.get_nowait()
        except Empty:
            if self._clock() >= self._deadline:
                self._terminal = RequestOutcome(
                    "timed_out", "外部 AI 逾時；本機分析、切換與保存仍可用。"
                )
                return self._terminal
            return RequestOutcome("pending", "AI 處理中；可繼續本機研究。")
        if completed_time >= self._deadline:
            self._terminal = RequestOutcome("timed_out", "外部 AI 逾時，已忽略晚到的回應。")
        else:
            self._terminal = outcome
        return self._terminal

    def local_receipt(self) -> str:
        """Exact request selection, separate from complete local evidence.

        Does not include raw model output or claim semantic acceptance. Caller
        must bind a separately validated result before saving an AI session.
        """
        import json

        return canonical(
            {
                "version": 1,
                "snapshot_fingerprint": self.prepared.snapshot_fingerprint,
                "request_fingerprint": self.prepared.request_fingerprint,
                "started_at": self.started_at,
                "payload": json.loads(self.prepared.payload_json),
                "selection": json.loads(self.prepared.manifest_json),
            }
        )
