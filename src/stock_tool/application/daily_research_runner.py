"""One application boundary for manual and scheduled Daily Research runs.

The existing :class:`HeadlessDailyResearchRunner` owns the established domain
orchestration.  This module adds the run-level contract used by both the Home
button and the scheduler without duplicating refresh, brief, change, or
Prediction Lab logic.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from stock_tool.application.daily_research_scheduler import (
    DailyResearchRefreshCallback,
    DailyResearchRunOutcome,
    HeadlessDailyResearchRunner,
    EXIT_FAILED,
    _market_snapshot_fingerprint,
    RUN_TRIGGER,
)
from stock_tool.application.prediction_lab import PredictionOutcomeProvider
from stock_tool.application.prediction_lab import BenchmarkRefreshResult
from stock_tool.application.market_monitor import MarketRefreshResult
from stock_tool.runtime_paths import RuntimePaths

RUN_MANIFEST_SCHEMA_VERSION = 3
LEGACY_RUN_MANIFEST_SCHEMA_VERSION = 2
_STAGES = (
    "target_refresh",
    "market_refresh",
    "brief",
    "change",
    "prediction_registration",
    "prediction_outcome_evaluation",
    "notification",
)
_LEGACY_STAGES = tuple(name for name in _STAGES if name != "prediction_outcome_evaluation")
_VALID_STAGE_STATUSES = frozenset({"success", "partial", "skipped", "unavailable", "failure"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class DailyResearchStage:
    """Auditable result for one bounded stage of a Daily Research run."""

    name: str
    status: str
    input_snapshot_hash: str | None = None
    output_fingerprint: str | None = None
    data_as_of: str | None = None
    output_reference: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.name not in _STAGES:
            raise ValueError("unknown daily research stage")
        if self.status not in _VALID_STAGE_STATUSES:
            raise ValueError("unknown daily research stage status")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DailyResearchRunManifest:
    """Schema-versioned, privacy-safe orchestration evidence."""

    run_id: str
    trigger: RUN_TRIGGER
    status: str
    exit_code: int
    started_at: str
    completed_at: str
    stages: tuple[DailyResearchStage, ...]
    input_snapshot_hash: str | None = None
    output_brief_fingerprint: str | None = None
    market_snapshot_hash: str | None = None
    market_status: str | None = None
    market_source_state: str | None = None
    market_data_as_of: str | None = None
    data_as_of: str | None = None
    deterministic_fallback_used: bool = True
    reason: str | None = None
    schema_version: int = RUN_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version not in {
            LEGACY_RUN_MANIFEST_SCHEMA_VERSION,
            RUN_MANIFEST_SCHEMA_VERSION,
        }:
            raise ValueError("unsupported daily research run manifest schema")
        if self.trigger not in {"manual", "scheduled"}:
            raise ValueError("invalid daily research trigger")
        if not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool):
            raise ValueError("invalid daily research exit code")
        if not isinstance(self.deterministic_fallback_used, bool):
            raise ValueError("deterministic_fallback_used must be boolean")
        names = tuple(stage.name for stage in self.stages)
        expected = (
            _LEGACY_STAGES if self.schema_version == LEGACY_RUN_MANIFEST_SCHEMA_VERSION else _STAGES
        )
        if names != expected:
            raise ValueError("daily research stages must be complete and ordered")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["stages"] = [stage.to_dict() for stage in self.stages]
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DailyResearchRunManifest":
        if not isinstance(payload, Mapping):
            raise ValueError("daily research run manifest must be an object")
        raw_stages = payload.get("stages")
        if not isinstance(raw_stages, list):
            raise ValueError("daily research run manifest stages are required")
        stages: list[DailyResearchStage] = []
        for raw in raw_stages:
            if not isinstance(raw, Mapping):
                raise ValueError("invalid daily research stage")
            stages.append(DailyResearchStage(**dict(raw)))
        allowed = {
            "run_id",
            "trigger",
            "status",
            "exit_code",
            "started_at",
            "completed_at",
            "stages",
            "input_snapshot_hash",
            "output_brief_fingerprint",
            "market_snapshot_hash",
            "market_status",
            "market_source_state",
            "market_data_as_of",
            "data_as_of",
            "deterministic_fallback_used",
            "reason",
            "schema_version",
        }
        if set(payload) != allowed:
            raise ValueError("daily research run manifest fields are not exact")
        schema_version = payload["schema_version"]
        if isinstance(schema_version, bool) or schema_version not in {
            LEGACY_RUN_MANIFEST_SCHEMA_VERSION,
            RUN_MANIFEST_SCHEMA_VERSION,
        }:
            raise ValueError("unsupported daily research run manifest schema")
        return cls(
            run_id=str(payload["run_id"]),
            trigger=payload["trigger"],  # type: ignore[arg-type]
            status=str(payload["status"]),
            exit_code=payload["exit_code"],  # type: ignore[arg-type]
            started_at=str(payload["started_at"]),
            completed_at=str(payload["completed_at"]),
            stages=tuple(stages),
            input_snapshot_hash=(
                str(payload["input_snapshot_hash"])
                if payload["input_snapshot_hash"] is not None
                else None
            ),
            output_brief_fingerprint=(
                str(payload["output_brief_fingerprint"])
                if payload["output_brief_fingerprint"] is not None
                else None
            ),
            market_snapshot_hash=(
                str(payload["market_snapshot_hash"])
                if payload["market_snapshot_hash"] is not None
                else None
            ),
            market_status=(
                str(payload["market_status"]) if payload["market_status"] is not None else None
            ),
            market_source_state=(
                str(payload["market_source_state"])
                if payload["market_source_state"] is not None
                else None
            ),
            market_data_as_of=(
                str(payload["market_data_as_of"])
                if payload["market_data_as_of"] is not None
                else None
            ),
            data_as_of=str(payload["data_as_of"]) if payload["data_as_of"] is not None else None,
            deterministic_fallback_used=payload["deterministic_fallback_used"],  # type: ignore[arg-type]
            reason=str(payload["reason"]) if payload["reason"] is not None else None,
            schema_version=schema_version,  # type: ignore[arg-type]
        )


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


def _stage_statuses(outcome: DailyResearchRunOutcome) -> tuple[DailyResearchStage, ...]:
    """Copy actual typed stage results; never infer success from overall status."""

    if not outcome.stages:
        return tuple(
            DailyResearchStage(
                name=name,
                status="unavailable",
                input_snapshot_hash=outcome.record.input_snapshot_hash,
                data_as_of=outcome.record.data_as_of,
                reason="核心流程未提供階段結果",
            )
            for name in _LEGACY_STAGES
        )
    names = tuple(item.name for item in outcome.stages)
    if names not in {_LEGACY_STAGES, _STAGES}:
        raise ValueError("core stage results are incomplete or out of order")
    return tuple(
        DailyResearchStage(
            name=item.name,
            status=item.status,
            input_snapshot_hash=item.input_snapshot_hash,
            output_fingerprint=item.output_fingerprint,
            data_as_of=item.data_as_of,
            output_reference=item.output_fingerprint,
            reason=item.reason,
        )
        for item in outcome.stages
    )


class DailyResearchRunner:
    """Shared application runner used by Home and headless scheduler entry points."""

    def __init__(
        self,
        paths: RuntimePaths,
        *,
        now_fn: Callable[[], datetime] = _utc_now,
        refresh_callback: DailyResearchRefreshCallback | None = None,
        market_refresh_callback: Callable[[], MarketRefreshResult] | None = None,
        benchmark_refresh_callback: Callable[[], BenchmarkRefreshResult] | None = None,
        on_success: Callable[..., object] | None = None,
        prediction_outcome_provider: PredictionOutcomeProvider | None = None,
        max_symbols: int = 20,
    ) -> None:
        self.paths = paths
        self.now_fn = now_fn
        self.refresh_callback = refresh_callback
        self.market_refresh_callback = market_refresh_callback
        self.benchmark_refresh_callback = benchmark_refresh_callback
        self.on_success = on_success
        self.prediction_outcome_provider = prediction_outcome_provider
        self.max_symbols = max_symbols

    @property
    def manifest_dir(self) -> Path:
        return self.paths.daily_research_run_manifests_dir

    def run(
        self, *, trigger: RUN_TRIGGER = "manual", dry_run: bool = False
    ) -> DailyResearchRunOutcome:
        core = HeadlessDailyResearchRunner(
            self.paths,
            now_fn=self.now_fn,
            refresh_callback=self.refresh_callback,
            market_refresh_callback=self.market_refresh_callback,
            benchmark_refresh_callback=self.benchmark_refresh_callback,
            on_success=self.on_success,
            prediction_outcome_provider=self.prediction_outcome_provider,
            max_symbols=self.max_symbols,
        )
        outcome = core.run(trigger=trigger, dry_run=dry_run)
        try:
            self._persist_manifest(outcome)
        except Exception:
            # The immutable core result and its six stage trace remain the
            # source of truth even when the derived manifest projection cannot
            # be published. Surface the persistence failure without replacing
            # the actual seven-stage statuses with an inferred tuple.
            failed_record = replace(
                outcome.record,
                status="failed",
                exit_code=EXIT_FAILED,
                reason="run manifest persistence failed",
            )
            return DailyResearchRunOutcome(
                "failed",
                EXIT_FAILED,
                "run manifest persistence failed",
                failed_record,
                stages=outcome.stages,
                market_result=outcome.market_result,
                market_snapshot_hash=outcome.market_snapshot_hash,
            )
        return outcome

    def _persist_manifest(self, outcome: DailyResearchRunOutcome) -> DailyResearchRunManifest:
        record = outcome.record
        manifest = DailyResearchRunManifest(
            run_id=record.run_id,
            trigger=record.trigger,
            status=record.status,
            exit_code=record.exit_code,
            started_at=record.started_at,
            completed_at=record.completed_at,
            stages=_stage_statuses(outcome),
            input_snapshot_hash=record.input_snapshot_hash,
            output_brief_fingerprint=record.output_brief_fingerprint,
            market_snapshot_hash=(
                outcome.market_snapshot_hash or _market_snapshot_fingerprint(outcome.market_result)
            ),
            market_status=(outcome.market_result.status if outcome.market_result else None),
            market_source_state=(
                outcome.market_result.source_state if outcome.market_result else None
            ),
            market_data_as_of=(
                outcome.market_result.snapshot.metadata.data_date
                if outcome.market_result and outcome.market_result.snapshot is not None
                else None
            ),
            data_as_of=record.data_as_of,
            deterministic_fallback_used=record.deterministic_fallback_used,
            reason=record.reason,
            schema_version=(
                RUN_MANIFEST_SCHEMA_VERSION
                if len(outcome.stages) == len(_STAGES)
                else LEGACY_RUN_MANIFEST_SCHEMA_VERSION
            ),
        )
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json_write(self.manifest_dir / f"{manifest.run_id}.json", manifest.to_dict())
        _atomic_json_write(self.manifest_dir / "latest.json", manifest.to_dict())
        return manifest

    def latest_manifest(self) -> DailyResearchRunManifest | None:
        path = self.manifest_dir / "latest.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return DailyResearchRunManifest.from_dict(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return None


__all__ = [
    "DailyResearchRunManifest",
    "DailyResearchRunner",
    "DailyResearchStage",
    "RUN_MANIFEST_SCHEMA_VERSION",
]
