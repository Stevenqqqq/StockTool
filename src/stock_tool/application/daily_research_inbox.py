"""Daily research inbox and privacy-safe Windows notification contracts.

The inbox is a read-only projection over the immutable scheduler records and
the schema-v2 DailyResearchBrief JSON.  Notifications are deliberately a
separate, opt-in side effect: a notifier failure can never change a brief or a
scheduled-run result.
"""

from __future__ import annotations

import json
import os
import re
import hashlib
import subprocess
import tempfile
import base64
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol, TypeAlias, cast

from stock_tool.application.daily_research_brief import (
    DailyResearchBrief,
    DailyResearchBriefStore,
    render_daily_brief_html,
)
from stock_tool.application.daily_research_changes import (
    DailyResearchChangeSet,
    DailyResearchChangeStore,
)
from stock_tool.application.daily_research_scheduler import (
    ScheduledRunRecord,
    ScheduledRunStore,
)
from stock_tool.data.contracts import sanitize_provider_text
from stock_tool.runtime_paths import RuntimePaths

NOTIFICATION_SCHEMA_VERSION = 2
NOTIFICATION_HISTORY_LIMIT = 30
NotificationDeliveryStatus = Literal["sent", "unavailable", "failed"]
NotificationClaimStatus = Literal["claimed"]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def _strict_schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("notification schema is unsupported")
    if value != NOTIFICATION_SCHEMA_VERSION:
        raise ValueError("notification schema is unsupported")
    return value


def _strict_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"notification {field} is invalid")
    value = value.strip()
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError(f"notification {field} is invalid")
    return value


def _optional_sha256(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or SHA256_RE.fullmatch(value.strip()) is None:
        raise ValueError(f"notification {field} is invalid")
    return value.strip().lower()


def _strict_created_at(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("notification created_at is invalid")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("notification created_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("notification created_at must include timezone")
    return text


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_text(value: object, *, limit: int = 300) -> str:
    text = sanitize_provider_text(str(value or "")).replace("\r", " ").replace("\n", " ")
    text = re.sub(
        r"(?i)(api[_ -]?key|token|password|credential)\s*[:=]\s*\S+",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(r"(?i)[A-Z]:\\[^\s;]+", "<path>", text)
    text = re.sub(r"[/\\]Users[/\\][^\s;]+", "<path>", text)
    return text[:limit]


def _atomic_json_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False, suffix=".tmp"
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _atomic_create_json(path: Path, payload: Mapping[str, object]) -> None:
    """Create immutable JSON using the filesystem exclusive-create primitive."""

    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor: int | None = None
    own_created = False
    try:
        descriptor = os.open(path, flags, 0o600)
        own_created = True
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        # O_EXCL is the cross-process claim winner primitive.  This invocation
        # did not acquire ownership and must never remove the existing winner.
        raise
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        if own_created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # The graph validator will reject an incomplete file; it must
                # never authorize a notification.
                pass
        raise


def _created_at_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    """Strict, disabled-by-default notification settings."""

    schema_version: int = NOTIFICATION_SCHEMA_VERSION
    enabled: bool = False
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != NOTIFICATION_SCHEMA_VERSION:
            raise ValueError("notification settings schema is unsupported")
        if not isinstance(self.enabled, bool):
            raise ValueError("notification enabled must be a boolean")
        if not isinstance(self.updated_at, str):
            raise ValueError("notification updated_at must be a string")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> "NotificationSettings":
        if not isinstance(payload, Mapping):
            raise ValueError("notification settings must be an object")
        enabled = payload.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("notification enabled must be a boolean")
        version = payload.get("schema_version", 0)
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("notification schema is unsupported")
        updated_at = payload.get("updated_at", "")
        if not isinstance(updated_at, str):
            raise ValueError("notification updated_at must be a string")
        return cls(schema_version=version, enabled=enabled, updated_at=updated_at)


class NotificationSettingsStore:
    """Atomic settings store which fails closed to disabled on corruption."""

    def __init__(self, path: str | Path, *, now_fn: Callable[[], datetime] = _utc_now) -> None:
        self.path = Path(path)
        self.now_fn = now_fn
        self.last_warning: str | None = None

    def load(self) -> NotificationSettings:
        self.last_warning = None
        if not self.path.is_file():
            return NotificationSettings()
        try:
            return NotificationSettings.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
            self.last_warning = "通知設定損壞，已安全停用"
            return NotificationSettings()

    def save(self, settings: NotificationSettings) -> None:
        validated = NotificationSettings.from_dict(settings.to_dict())
        _atomic_json_write(self.path, validated.to_dict())


@dataclass(frozen=True, slots=True)
class NotificationClaimRecord:
    """An immutable, durable claim created before a notifier is called."""

    claim_id: str
    run_id: str
    brief_fingerprint: str
    created_at: str
    change_fingerprint: str | None = None
    schema_version: int = NOTIFICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _strict_schema_version(self.schema_version)
        _strict_identifier(self.claim_id, "claim_id")
        _strict_identifier(self.run_id, "run_id")
        _strict_identifier(self.brief_fingerprint, "brief_fingerprint")
        _strict_created_at(self.created_at)
        _optional_sha256(self.change_fingerprint, "change_fingerprint")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> "NotificationClaimRecord":
        if not isinstance(payload, Mapping):
            raise ValueError("notification claim must be an object")
        return cls(
            claim_id=_strict_identifier(payload.get("claim_id"), "claim_id"),
            run_id=_strict_identifier(payload.get("run_id"), "run_id"),
            brief_fingerprint=_strict_identifier(
                payload.get("brief_fingerprint"), "brief_fingerprint"
            ),
            created_at=_strict_created_at(payload.get("created_at")),
            change_fingerprint=_optional_sha256(
                payload.get("change_fingerprint"), "change_fingerprint"
            ),
            schema_version=_strict_schema_version(payload.get("schema_version")),
        )


@dataclass(frozen=True, slots=True)
class NotificationLedgerRecord:
    """One immutable notification outcome, without user content."""

    ledger_id: str
    run_id: str
    brief_fingerprint: str
    status: NotificationDeliveryStatus
    created_at: str
    claim_id: str
    reason: str | None = None
    change_fingerprint: str | None = None
    schema_version: int = NOTIFICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _strict_schema_version(self.schema_version)
        _strict_identifier(self.ledger_id, "ledger_id")
        _strict_identifier(self.run_id, "run_id")
        _strict_identifier(self.brief_fingerprint, "brief_fingerprint")
        _strict_created_at(self.created_at)
        if not isinstance(self.status, str) or self.status not in {
            "sent",
            "unavailable",
            "failed",
        }:
            raise ValueError("notification ledger status is invalid")
        _strict_identifier(self.claim_id, "claim_id")
        _optional_sha256(self.change_fingerprint, "change_fingerprint")
        if self.reason is not None and not isinstance(self.reason, str):
            raise ValueError("notification reason is invalid")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> "NotificationLedgerRecord":
        if not isinstance(payload, Mapping):
            raise ValueError("notification ledger record must be an object")
        ledger_id = _strict_identifier(payload.get("ledger_id"), "ledger_id")
        run_id = _strict_identifier(payload.get("run_id"), "run_id")
        brief_fingerprint = _strict_identifier(
            payload.get("brief_fingerprint"), "brief_fingerprint"
        )
        status = payload.get("status")
        if not isinstance(status, str) or status not in {"sent", "unavailable", "failed"}:
            raise ValueError("notification ledger status is invalid")
        delivery_status = cast(NotificationDeliveryStatus, status)
        reason = payload.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("notification reason is invalid")
        claim_id = _strict_identifier(payload.get("claim_id"), "claim_id")
        return cls(
            ledger_id=ledger_id,
            run_id=run_id,
            brief_fingerprint=brief_fingerprint,
            status=delivery_status,
            created_at=_strict_created_at(payload.get("created_at")),
            reason=_safe_text(reason) if reason else None,
            schema_version=_strict_schema_version(payload.get("schema_version")),
            claim_id=claim_id,
            change_fingerprint=_optional_sha256(
                payload.get("change_fingerprint"), "change_fingerprint"
            ),
        )


class NotificationLedgerError(RuntimeError):
    """Raised when notification ledger state cannot be verified safely."""


class NotificationDuplicateError(NotificationLedgerError):
    """A valid immutable claim already owns this run/fingerprint."""

    def __str__(self) -> str:
        return "通知 claim 已重複"


class NotificationLedgerStore:
    """Claim/outcome authority with a bounded, rebuildable history projection.

    ``claim-*.json`` is written before a notifier is called.  The immutable
    claim remains the deduplication authority even when publishing an outcome
    or the history projection fails.  ``outcome-*.json`` is the immutable
    delivery result; ``history.json`` is only a rebuildable projection.
    """

    def __init__(
        self,
        records_dir: str | Path,
        history_path: str | Path,
        *,
        max_records: int = NOTIFICATION_HISTORY_LIMIT,
        atomic_write: Callable[[Path, Mapping[str, object]], None] = _atomic_json_write,
        atomic_create: Callable[[Path, Mapping[str, object]], None] = _atomic_create_json,
    ) -> None:
        self.records_dir = Path(records_dir)
        self.history_path = Path(history_path)
        self.max_records = max(1, int(max_records))
        self.atomic_write = atomic_write
        self.atomic_create = atomic_create

    def _validated_graph(
        self,
    ) -> tuple[tuple[NotificationClaimRecord, ...], tuple[NotificationLedgerRecord, ...]]:
        """Load and validate claims and outcomes as one integrity graph."""

        if not self.records_dir.is_dir():
            return (), ()
        claims: list[NotificationClaimRecord] = []
        outcomes: list[NotificationLedgerRecord] = []
        claim_by_id: dict[str, NotificationClaimRecord] = {}
        claim_by_run: dict[str, NotificationClaimRecord] = {}
        claim_by_fingerprint: dict[str, NotificationClaimRecord] = {}
        claim_by_change: dict[str, NotificationClaimRecord] = {}
        outcome_by_id: dict[str, NotificationLedgerRecord] = {}
        outcome_by_run: dict[str, NotificationLedgerRecord] = {}
        outcome_by_fingerprint: dict[str, NotificationLedgerRecord] = {}
        outcome_by_change: dict[str, NotificationLedgerRecord] = {}
        for path in sorted(self.records_dir.glob("*.json")):
            parser: Callable[[object], NotificationClaimRecord | NotificationLedgerRecord]
            if path.name.startswith("claim-") and path.name.endswith(".json"):
                parser = NotificationClaimRecord.from_dict
            elif path.name.startswith("outcome-") and path.name.endswith(".json"):
                parser = NotificationLedgerRecord.from_dict
            else:
                raise NotificationLedgerError("未知或舊版通知紀錄已拒絕讀取")
            try:
                parsed = parser(json.loads(path.read_text(encoding="utf-8")))
            except (
                OSError,
                UnicodeDecodeError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                raise NotificationLedgerError("通知紀錄損壞，已拒絕讀取") from exc
            if path.name.startswith("claim-"):
                claim = cast(NotificationClaimRecord, parsed)
                expected_claim_id = self.claim_id_for(
                    claim.run_id, claim.brief_fingerprint, claim.change_fingerprint
                )
                if claim.claim_id != expected_claim_id:
                    raise NotificationLedgerError("claim deterministic identity mismatch")
                if path.name != f"claim-{claim.claim_id}.json":
                    raise NotificationLedgerError("claim 檔名與內容不一致")
                if (
                    claim.claim_id in claim_by_id
                    or claim.run_id in claim_by_run
                    or claim.brief_fingerprint in claim_by_fingerprint
                    or (
                        claim.change_fingerprint is not None
                        and claim.change_fingerprint in claim_by_change
                    )
                ):
                    raise NotificationLedgerError("重複或交叉綁定的 claim 已拒絕")
                claim_by_id[claim.claim_id] = claim
                claim_by_run[claim.run_id] = claim
                claim_by_fingerprint[claim.brief_fingerprint] = claim
                if claim.change_fingerprint is not None:
                    claim_by_change[claim.change_fingerprint] = claim
                claims.append(claim)
            else:
                outcome = cast(NotificationLedgerRecord, parsed)
                if path.name != f"outcome-{outcome.ledger_id}.json":
                    raise NotificationLedgerError("通知紀錄檔名與內容不一致")
                if (
                    outcome.ledger_id in outcome_by_id
                    or outcome.run_id in outcome_by_run
                    or outcome.brief_fingerprint in outcome_by_fingerprint
                    or (
                        outcome.change_fingerprint is not None
                        and outcome.change_fingerprint in outcome_by_change
                    )
                ):
                    raise NotificationLedgerError("重複或交叉綁定的 outcome 已拒絕")
                outcome_by_id[outcome.ledger_id] = outcome
                outcome_by_run[outcome.run_id] = outcome
                outcome_by_fingerprint[outcome.brief_fingerprint] = outcome
                if outcome.change_fingerprint is not None:
                    outcome_by_change[outcome.change_fingerprint] = outcome
                outcomes.append(outcome)
        for outcome in outcomes:
            matched_claim = claim_by_id.get(outcome.claim_id)
            if matched_claim is None:
                raise NotificationLedgerError("orphan outcome has no valid claim")
            if (
                matched_claim.run_id != outcome.run_id
                or matched_claim.brief_fingerprint != outcome.brief_fingerprint
                or matched_claim.change_fingerprint != outcome.change_fingerprint
            ):
                raise NotificationLedgerError("outcome claim identity mismatch")
            if _created_at_datetime(outcome.created_at) < _created_at_datetime(
                matched_claim.created_at
            ):
                raise NotificationLedgerError("outcome precedes claim")
        return (
            tuple(sorted(claims, key=lambda item: (item.created_at, item.claim_id))),
            tuple(sorted(outcomes, key=lambda item: (item.created_at, item.ledger_id))),
        )

    def records(self) -> tuple[NotificationLedgerRecord, ...]:
        return self._validated_graph()[1]

    def claims(self) -> tuple[NotificationClaimRecord, ...]:
        return self._validated_graph()[0]

    def pending_claims(self) -> tuple[NotificationClaimRecord, ...]:
        """Return valid claims which do not yet have an immutable outcome."""

        claims, outcomes = self._validated_graph()
        outcome_claim_ids = {item.claim_id for item in outcomes}
        return tuple(item for item in claims if item.claim_id not in outcome_claim_ids)

    def contains(
        self, run_id: str, brief_fingerprint: str, change_fingerprint: str | None = None
    ) -> bool:
        return any(
            item.run_id == run_id
            or item.brief_fingerprint == brief_fingerprint
            or (change_fingerprint is not None and item.change_fingerprint == change_fingerprint)
            for item in self.claims()
        )

    def _publish_history(self, records: Sequence[NotificationLedgerRecord]) -> None:
        recent = records[-self.max_records :]
        payload = {
            "schema_version": NOTIFICATION_SCHEMA_VERSION,
            "records": [
                {
                    "ledger_id": item.ledger_id,
                    "run_id": item.run_id,
                    "brief_fingerprint": item.brief_fingerprint,
                    "status": item.status,
                    "created_at": item.created_at,
                    "reason": item.reason,
                    "claim_id": item.claim_id,
                    "change_fingerprint": item.change_fingerprint,
                }
                for item in recent
            ],
        }
        self.atomic_write(self.history_path, payload)

    def rebuild_history(self) -> None:
        self._publish_history(self.records())

    @staticmethod
    def claim_id_for(
        run_id: str, brief_fingerprint: str, change_fingerprint: str | None = None
    ) -> str:
        value = f"{run_id}\x00{brief_fingerprint}\x00{change_fingerprint or ''}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def create_claim(
        self,
        *,
        run_id: str,
        brief_fingerprint: str,
        created_at: str,
        change_fingerprint: str | None = None,
    ) -> NotificationClaimRecord:
        claim = NotificationClaimRecord(
            claim_id=self.claim_id_for(run_id, brief_fingerprint, change_fingerprint),
            run_id=run_id,
            brief_fingerprint=brief_fingerprint,
            created_at=created_at,
            change_fingerprint=change_fingerprint,
        )
        claims, outcomes = self._validated_graph()
        if any(
            item.run_id == claim.run_id
            or item.brief_fingerprint == claim.brief_fingerprint
            or (
                claim.change_fingerprint is not None
                and item.change_fingerprint == claim.change_fingerprint
            )
            for item in claims
        ) or any(
            item.run_id == claim.run_id
            or item.brief_fingerprint == claim.brief_fingerprint
            or (
                claim.change_fingerprint is not None
                and item.change_fingerprint == claim.change_fingerprint
            )
            for item in outcomes
        ):
            raise NotificationDuplicateError("通知 claim 已重複")
        self.records_dir.mkdir(parents=True, exist_ok=True)
        path = self.records_dir / f"claim-{claim.claim_id}.json"
        try:
            self.atomic_create(path, claim.to_dict())
        except FileExistsError as exc:
            try:
                claims_after, outcomes_after = self._validated_graph()
            except NotificationLedgerError as graph_exc:
                raise NotificationLedgerError(
                    "claim state is invalid after contention"
                ) from graph_exc
            if any(
                item.claim_id == claim.claim_id
                and item.run_id == claim.run_id
                and item.brief_fingerprint == claim.brief_fingerprint
                and item.change_fingerprint == claim.change_fingerprint
                for item in claims_after
            ) or any(
                item.run_id == claim.run_id
                and item.brief_fingerprint == claim.brief_fingerprint
                and item.change_fingerprint == claim.change_fingerprint
                for item in outcomes_after
            ):
                raise NotificationDuplicateError("通知 claim 已重複") from exc
            raise NotificationLedgerError("claim create contention failed closed") from exc
        except Exception as exc:
            raise NotificationLedgerError("claim write failed") from exc
        try:
            self._publish_history(self.records())
        except Exception as exc:
            raise NotificationLedgerError("claim projection failed") from exc
        return claim

    def save_outcome(self, record: NotificationLedgerRecord) -> None:
        validated = NotificationLedgerRecord.from_dict(record.to_dict())
        self.records_dir.mkdir(parents=True, exist_ok=True)
        claims = self.claims()
        claim = next((item for item in claims if item.claim_id == validated.claim_id), None)
        if claim is None:
            raise NotificationLedgerError("通知 outcome 缺少先行 claim")
        if (
            claim.run_id != validated.run_id
            or claim.brief_fingerprint != validated.brief_fingerprint
            or claim.change_fingerprint != validated.change_fingerprint
        ):
            raise NotificationLedgerError("通知 outcome claim 不一致")
        if any(
            item.run_id == validated.run_id
            or item.brief_fingerprint == validated.brief_fingerprint
            or (
                validated.change_fingerprint is not None
                and item.change_fingerprint == validated.change_fingerprint
            )
            for item in self.records()
        ):
            raise NotificationLedgerError("重複通知 outcome 已拒絕")
        path = self.records_dir / f"outcome-{validated.ledger_id}.json"
        if path.exists():
            raise NotificationLedgerError("重複通知 outcome 已拒絕")
        try:
            self.atomic_write(path, validated.to_dict())
            self._publish_history(self.records())
        except Exception as exc:
            raise NotificationLedgerError("通知 outcome 保存失敗") from exc

    def save(self, record: NotificationLedgerRecord) -> None:
        """Compatibility helper for deterministic tests: claim then outcome."""
        validated = NotificationLedgerRecord.from_dict(record.to_dict())
        claim = self.create_claim(
            run_id=validated.run_id,
            brief_fingerprint=validated.brief_fingerprint,
            created_at=validated.created_at,
            change_fingerprint=validated.change_fingerprint,
        )
        self.save_outcome(
            NotificationLedgerRecord(
                ledger_id=validated.ledger_id,
                run_id=validated.run_id,
                brief_fingerprint=validated.brief_fingerprint,
                status=validated.status,
                created_at=validated.created_at,
                reason=validated.reason,
                claim_id=claim.claim_id,
                change_fingerprint=validated.change_fingerprint,
            )
        )


@dataclass(frozen=True, slots=True)
class NotificationRequest:
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class NotificationResult:
    status: NotificationDeliveryStatus
    reason: str | None = None


class Notifier(Protocol):
    def send(self, request: NotificationRequest) -> NotificationResult: ...


class DeterministicFakeNotifier:
    """Test notifier with deterministic success/failure and captured requests."""

    def __init__(self, result: NotificationResult | None = None) -> None:
        self.result = result or NotificationResult("sent")
        self.requests: list[NotificationRequest] = []

    def send(self, request: NotificationRequest) -> NotificationResult:
        self.requests.append(request)
        return self.result


@dataclass(frozen=True, slots=True)
class NotificationCapability:
    available: bool
    identity: str | None
    reason: str
    runtime_available: bool = False


SystemRunner: TypeAlias = Callable[[Sequence[str], float], object]


def _default_identity_probe() -> str | None:
    """Read an existing Start Apps identity; never create or register one."""

    if os.name != "nt":
        return None
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-StartApps -Name 'StockTool' | Select-Object -First 1 -ExpandProperty AppID)",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    identity = completed.stdout.strip().splitlines()
    return identity[0].strip() if identity and identity[0].strip() else None


def _default_system_runner(command: Sequence[str], timeout: float) -> object:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


class WindowsNotificationAdapter:
    """Built-in Windows toast path guarded by an existing packaged identity."""

    def __init__(
        self,
        *,
        send_fn: Callable[[NotificationRequest], bool] | None = None,
        identity_probe: Callable[[], str | None] | None = None,
        system_runner: SystemRunner | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.send_fn = send_fn
        self.identity_probe = identity_probe or _default_identity_probe
        self.system_runner = system_runner or _default_system_runner
        self.timeout_seconds = timeout_seconds

    def capability(self) -> NotificationCapability:
        if self.send_fn is not None:
            return NotificationCapability(True, "injected", "測試通知器可用", True)
        if os.name != "nt":
            return NotificationCapability(False, None, "Windows 通知目前不可用")
        try:
            identity = self.identity_probe()
        except Exception:
            identity = None
        if not identity or not isinstance(identity, str) or not identity.strip():
            return NotificationCapability(False, None, "Windows 通知需要既有應用程式身分")
        try:
            result = self.system_runner(
                self._runtime_probe_command(identity.strip()), self.timeout_seconds
            )
            code = getattr(result, "returncode", result[0] if isinstance(result, tuple) else None)
        except (OSError, subprocess.SubprocessError, TimeoutError, IndexError, TypeError):
            code = None
        if code != 0:
            return NotificationCapability(
                False, identity.strip(), "Windows Runtime 通知型別不可用", False
            )
        return NotificationCapability(True, identity.strip(), "Windows 通知可用", True)

    @staticmethod
    def _powershell_command(script: str, payload: Mapping[str, object]) -> list[str]:
        """Pass JSON through a base64 UTF-8 literal, never shell interpolation."""

        encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode(
            "ascii"
        )
        wrapped = (
            "$payload = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
            + encoded
            + "')); $p = ConvertFrom-Json -InputObject $payload; "
            + script
        )
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", wrapped]

    @staticmethod
    def _runtime_probe_command(identity: str) -> list[str]:
        """Construct XML/Toast objects without calling Show or sending a toast."""

        script = (
            "$xml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, "
            "ContentType = WindowsRuntime]::new(); "
            '$xml.LoadXml(\'<toast><visual><binding template="ToastGeneric">'
            "<text>probe</text></binding></visual></toast>'); "
            "$toast = [Windows.UI.Notifications.ToastNotification, "
            "Windows.UI.Notifications, ContentType = WindowsRuntime]::new($xml); "
            "$notifier = [Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType = WindowsRuntime]::CreateToastNotifier($p.identity); "
            "if ($null -eq $toast -or $null -eq $notifier) { exit 3 }; "
            "Write-Output 'stocktool-winrt-probe-ok'"
        )
        return WindowsNotificationAdapter._powershell_command(script, {"identity": identity})

    @staticmethod
    def _toast_command(identity: str, request: NotificationRequest) -> list[str]:
        # Values are passed through PowerShell's JSON parser rather than shell
        # interpolation, so notification text cannot become executable code.
        script = (
            "$xml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, "
            "ContentType = WindowsRuntime]::new(); "
            "$safeTitle = [System.Security.SecurityElement]::Escape([string]$p.title); "
            "$safeBody = [System.Security.SecurityElement]::Escape([string]$p.body); "
            "$xml.LoadXml(\"<toast><visual><binding template='ToastGeneric'>"
            '<text>{0}</text><text>{1}</text></binding></visual></toast>" -f $safeTitle, $safeBody)); '
            "$toast = [Windows.UI.Notifications.ToastNotification, "
            "Windows.UI.Notifications, ContentType = WindowsRuntime]::new($xml); "
            "$notifier = [Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType = WindowsRuntime]::CreateToastNotifier($p.identity); "
            "$notifier.Show($toast)"
        )
        return WindowsNotificationAdapter._powershell_command(
            script, {"identity": identity, "title": request.title, "body": request.body}
        )

    def send(self, request: NotificationRequest) -> NotificationResult:
        if self.send_fn is not None:
            try:
                return NotificationResult("sent" if self.send_fn(request) else "failed")
            except Exception:
                return NotificationResult("failed", "Windows 通知發送失敗")
        capability = self.capability()
        if not capability.available or capability.identity is None:
            return NotificationResult("unavailable", capability.reason)
        try:
            result = self.system_runner(
                self._toast_command(capability.identity, request), self.timeout_seconds
            )
            code = getattr(result, "returncode", result[0] if isinstance(result, tuple) else None)
            if code == 0:
                return NotificationResult("sent")
            return NotificationResult("failed", "Windows 通知發送失敗")
        except (OSError, subprocess.SubprocessError, TimeoutError, IndexError, TypeError):
            return NotificationResult("failed", "Windows 通知發送失敗")


@dataclass(frozen=True, slots=True)
class NotificationServiceStatus:
    enabled: bool
    last_status: str | None
    last_reason: str | None
    settings_warning: str | None
    capability_available: bool | None = None
    capability_reason: str | None = None


class DailyResearchNotificationService:
    """Opt-in success notifier with run/fingerprint deduplication."""

    def __init__(
        self,
        paths: RuntimePaths,
        *,
        notifier: Notifier | None = None,
        now_fn: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.paths = paths
        self.now_fn = now_fn
        self.notifier = notifier or WindowsNotificationAdapter()
        self.settings_store = NotificationSettingsStore(
            paths.daily_notification_settings_file, now_fn=now_fn
        )
        self.ledger = NotificationLedgerStore(
            paths.daily_notification_ledger_dir, paths.daily_notification_history_file
        )

    def settings(self) -> NotificationSettings:
        return self.settings_store.load()

    def settings_warning(self) -> str | None:
        self.settings_store.load()
        return self.settings_store.last_warning

    def set_enabled(self, enabled: bool) -> NotificationSettings:
        if not isinstance(enabled, bool):
            raise ValueError("notification enabled must be a boolean")
        settings = NotificationSettings(
            enabled=enabled, updated_at=self.now_fn().astimezone(timezone.utc).isoformat()
        )
        self.settings_store.save(settings)
        return settings

    def status(self) -> NotificationServiceStatus:
        settings = self.settings()
        capability = (
            self.notifier.capability()
            if isinstance(self.notifier, WindowsNotificationAdapter)
            else NotificationCapability(True, "test", "測試通知器可用")
        )
        try:
            claims, records = self.ledger._validated_graph()
            outcome_claim_ids = {item.claim_id for item in records}
            pending_claims = [item for item in claims if item.claim_id not in outcome_claim_ids]
            latest_outcome = max(
                records,
                key=lambda item: (_created_at_datetime(item.created_at), item.ledger_id),
                default=None,
            )
            latest_pending = max(
                pending_claims,
                key=lambda item: (_created_at_datetime(item.created_at), item.claim_id),
                default=None,
            )
            pending_is_latest = latest_pending is not None and (
                latest_outcome is None
                or _created_at_datetime(latest_pending.created_at)
                >= _created_at_datetime(latest_outcome.created_at)
            )
            if pending_is_latest:
                return NotificationServiceStatus(
                    settings.enabled,
                    "pending",
                    "notification claim is pending and will not be sent again",
                    self.settings_store.last_warning,
                    capability.available,
                    capability.reason,
                )
            return NotificationServiceStatus(
                settings.enabled,
                latest_outcome.status if latest_outcome else None,
                latest_outcome.reason if latest_outcome else None,
                self.settings_store.last_warning,
                capability.available,
                capability.reason,
            )
        except NotificationLedgerError as exc:
            return NotificationServiceStatus(
                settings.enabled,
                "failed",
                str(exc),
                self.settings_warning(),
                capability.available,
                capability.reason,
            )

    def notify_success(
        self,
        record: ScheduledRunRecord,
        brief: DailyResearchBrief,
        *,
        change_summary: DailyResearchChangeSet | None = None,
    ) -> NotificationResult:
        if record.status != "success" or not record.output_brief_fingerprint:
            return NotificationResult("unavailable", "非成功簡報不發送完成通知")
        if brief.manifest.content_fingerprint != record.output_brief_fingerprint:
            return NotificationResult("failed", "簡報 fingerprint 不一致")
        change_fingerprint: str | None = None
        if change_summary is not None:
            try:
                validated_change = DailyResearchChangeSet.from_dict(change_summary.to_dict())
            except (TypeError, ValueError):
                return NotificationResult("failed", "變化摘要無法驗證")
            if validated_change.current_brief_fingerprint != record.output_brief_fingerprint:
                return NotificationResult("failed", "變化摘要與簡報不一致")
            change_fingerprint = validated_change.content_fingerprint
        settings = self.settings()
        if not settings.enabled:
            return NotificationResult("unavailable", "通知未啟用")
        # Claims/outcomes describe the completed run, not the wall-clock time
        # at which a UI callback happens.  Binding both to the run completion
        # timestamp keeps pending claims correctly ordered during replay.
        claim_created_at = record.completed_at
        try:
            claim = self.ledger.create_claim(
                run_id=record.run_id,
                brief_fingerprint=record.output_brief_fingerprint,
                created_at=claim_created_at,
                change_fingerprint=change_fingerprint,
            )
        except NotificationDuplicateError:
            return NotificationResult("unavailable", "通知已去重")
        except NotificationLedgerError:
            return NotificationResult("failed", "通知 claim 保存失敗")
        request = NotificationRequest(
            title="StockTool 每日研究簡報",
            body=f"StockTool 今日研究簡報已完成（{record.completed_at}）",
        )
        try:
            result = self.notifier.send(request)
        except Exception:
            result = NotificationResult("failed", "通知發送失敗")
        ledger_record = NotificationLedgerRecord(
            ledger_id=f"{record.run_id}-{(change_fingerprint or record.output_brief_fingerprint)[:12]}",
            run_id=record.run_id,
            brief_fingerprint=record.output_brief_fingerprint,
            status=result.status,
            # Bind the outcome to the scheduled run completion time.  Using
            # ``now_fn`` here could make an older run appear newer than a
            # subsequently-created pending claim during replay or tests.
            created_at=record.completed_at,
            reason=_safe_text(result.reason) if result.reason else None,
            claim_id=claim.claim_id,
            change_fingerprint=change_fingerprint,
        )
        try:
            self.ledger.save_outcome(ledger_record)
        except (OSError, ValueError, NotificationLedgerError):
            return NotificationResult("failed", "通知紀錄保存失敗")
        return result

    def send_test_notification(self) -> NotificationResult:
        request = NotificationRequest(
            title="StockTool 通知測試",
            body="這是使用者明確要求的 StockTool 通知測試。",
        )
        try:
            return self.notifier.send(request)
        except Exception:
            return NotificationResult("failed", "通知發送失敗")


@dataclass(frozen=True, slots=True)
class ResearchInboxEntry:
    run_id: str
    completed_at: str
    status: str
    source_mode: str
    reason: str
    next_step: str
    brief_fingerprint: str | None
    brief_available: bool
    change_fingerprint: str | None
    change_status: str | None
    change_priority: int | None
    change_reference_ids: tuple[str, ...]


class DailyResearchInboxService:
    """Read-only inbox projection over validated run records and brief JSON."""

    def __init__(self, paths: RuntimePaths, *, max_entries: int = 30) -> None:
        self.paths = paths
        self.max_entries = max(1, min(int(max_entries), 30))
        self.run_store = ScheduledRunStore(
            paths.daily_schedule_latest_run_file, paths.daily_schedule_runs_dir
        )
        self.brief_store = DailyResearchBriefStore(
            paths.daily_research_brief_file, paths.daily_research_brief_html_file
        )
        self.change_store = DailyResearchChangeStore(
            paths.daily_research_change_file, paths.daily_research_change_history_dir
        )

    def _change_for_brief(self, brief_fingerprint: str) -> DailyResearchChangeSet | None:
        """Return the validated immutable summary for exactly this brief."""

        summaries = self.change_store.history()
        matching = [
            summary
            for summary in summaries
            if summary.current_brief_fingerprint == brief_fingerprint
        ]
        if len(matching) > 1:
            raise ValueError("multiple change summaries claim one brief")
        return matching[0] if matching else None

    @staticmethod
    def _source_mode(brief: DailyResearchBrief | None) -> str:
        if brief is None:
            return "未知"
        values = [
            f"{item.source or ''} {item.status or ''}".lower()
            for item in brief.manifest.source_summaries
        ]
        values.extend(f"{item.source or ''} {item.status or ''}".lower() for item in brief.items)
        if any("online" in value or "provider" in value for value in values):
            return "online"
        if any("cache" in value or "local" in value for value in values):
            return "cache"
        return "本機資料"

    def _entry(self, record: ScheduledRunRecord) -> ResearchInboxEntry:
        status_labels = {
            "success": "成功",
            "partial": "部分完成",
            "skipped_disabled": "已略過",
            "skipped_no_targets": "已略過",
            "skipped_no_new_data": "已略過",
            "skipped_missed_window": "已略過",
            "skipped_dry_run": "已略過",
            "already_running": "執行中",
            "failed": "失敗",
        }
        brief: DailyResearchBrief | None = None
        change_summary: DailyResearchChangeSet | None = None
        verified = False
        if record.status == "success" and record.output_brief_fingerprint:
            brief = self.brief_store.load()
            verified = bool(
                brief is not None
                and brief.status == "success"
                and brief.manifest.content_fingerprint == record.output_brief_fingerprint
            )
            if verified:
                try:
                    change_summary = self._change_for_brief(record.output_brief_fingerprint)
                except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
                    verified = False
        if record.status == "success" and verified:
            reason = "已驗證最新研究簡報"
            next_step = "可開啟 JSON／HTML 簡報"
            fingerprint = record.output_brief_fingerprint
        elif record.status == "success":
            reason = "簡報檔案缺失或驗證失敗，已安全拒絕顯示"
            next_step = "請重新執行每日研究"
            fingerprint = None
        elif record.status == "partial":
            reason = "部分資料未完成，上一份成功簡報仍保留"
            next_step = "檢查資料來源後重新執行"
            fingerprint = None
        elif record.status.startswith("skipped"):
            reason = {
                "skipped_disabled": "每日研究排程目前停用",
                "skipped_no_targets": "目前沒有可處理的標的",
                "skipped_no_new_data": "更新後沒有新的研究資料",
                "skipped_missed_window": "本次已超過排程補跑時間",
                "skipped_dry_run": "本次為預覽執行，未產生簡報",
            }.get(record.status, "本次沒有產生新簡報")
            next_step = "確認資料可用後再執行一次"
            fingerprint = None
        elif record.status == "already_running":
            reason = "已有每日研究正在執行"
            next_step = "等待目前執行結束"
            fingerprint = None
        else:
            reason = "每日研究執行失敗，已保留上一份成功簡報"
            next_step = "檢查資料狀態後重試"
            fingerprint = None
        return ResearchInboxEntry(
            run_id=record.run_id,
            completed_at=record.completed_at,
            status=status_labels.get(record.status, "未知"),
            source_mode=self._source_mode(brief) if verified else "未知",
            reason=reason,
            next_step=next_step,
            brief_fingerprint=fingerprint,
            brief_available=verified,
            change_fingerprint=(
                change_summary.content_fingerprint
                if verified and change_summary is not None
                else None
            ),
            change_status=(
                change_summary.status if verified and change_summary is not None else None
            ),
            change_priority=(
                max((change.priority for change in change_summary.changes), default=None)
                if verified and change_summary is not None
                else None
            ),
            change_reference_ids=(
                tuple(
                    sorted(
                        {
                            reference_id
                            for change in change_summary.changes
                            for reference_id in change.reference_ids
                        }
                    )
                )
                if verified and change_summary is not None
                else ()
            ),
        )

    def entries(self) -> tuple[ResearchInboxEntry, ...]:
        records = self.run_store.load_history()
        return tuple(self._entry(record) for record in reversed(records[-self.max_entries :]))

    def latest_validated_brief(self) -> DailyResearchBrief | None:
        latest = self.run_store.load_latest()
        if latest is None or latest.status != "success" or not latest.output_brief_fingerprint:
            return None
        brief = self.brief_store.load()
        if brief is None or brief.status != "success":
            return None
        if brief.manifest.content_fingerprint != latest.output_brief_fingerprint:
            return None
        return brief

    def export_latest_html(self) -> str | None:
        brief = self.latest_validated_brief()
        return render_daily_brief_html(brief) if brief is not None else None


__all__ = [
    "DailyResearchInboxService",
    "DailyResearchNotificationService",
    "DeterministicFakeNotifier",
    "NOTIFICATION_HISTORY_LIMIT",
    "NOTIFICATION_SCHEMA_VERSION",
    "NotificationLedgerError",
    "NotificationDuplicateError",
    "NotificationCapability",
    "NotificationClaimRecord",
    "NotificationLedgerRecord",
    "NotificationLedgerStore",
    "NotificationRequest",
    "NotificationResult",
    "NotificationServiceStatus",
    "NotificationSettings",
    "NotificationSettingsStore",
    "Notifier",
    "ResearchInboxEntry",
    "WindowsNotificationAdapter",
]
