"""Deterministic macro-evidence snapshots for the Daily Decision Center.

The module deliberately keeps the provider boundary small.  Rendering code only
loads validated local snapshots; network access is performed by
``MacroSnapshotApplicationService.refresh`` after an explicit user action.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol

MACRO_SCHEMA_VERSION = 2
MACRO_STATUSES = frozenset({"ready", "partial", "stale", "unavailable"})
MACRO_SIGNAL_STATUSES = frozenset(
    {"rising", "falling", "unchanged", "insufficient_data", "stale", "unavailable", "revised"}
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
FRED_DATE_HEADERS = ("observation_date", "DATE")
FRED_SERIES: dict[str, tuple[str, str, str]] = {
    "CPI": ("CPIAUCSL", "消費者物價指數", "index"),
    "CORE_CPI": ("CPILFESL", "核心消費者物價指數", "index"),
    "UNEMPLOYMENT_RATE": ("UNRATE", "失業率", "percent"),
    "NONFARM_PAYROLLS": ("PAYEMS", "非農就業人數", "thousand_persons"),
    "FEDERAL_FUNDS_RATE": ("FEDFUNDS", "聯邦基金利率", "percent"),
    "TREASURY_10Y_2Y_SPREAD": ("T10Y2Y", "10 年減 2 年公債利差", "percent_points"),
}


class MacroSnapshotError(ValueError):
    """Raised when an external or persisted macro snapshot is not trustworthy."""


class FredPayloadError(MacroSnapshotError):
    """Raised when a FRED response is reachable but violates its CSV contract."""


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MacroSnapshotError(f"{name} must be non-empty text")
    return value.strip()


def _strict_schema(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != MACRO_SCHEMA_VERSION:
        raise MacroSnapshotError(f"{name} schema is unsupported")
    return value


def _parse_datetime(value: object, name: str, *, allow_future: bool = False) -> datetime:
    text = _strict_text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MacroSnapshotError(f"{name} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MacroSnapshotError(f"{name} must include timezone")
    if not allow_future and parsed.astimezone(timezone.utc) > datetime.now(timezone.utc):
        raise MacroSnapshotError(f"{name} is in the future")
    return parsed.astimezone(timezone.utc)


def _parse_date(value: object, name: str, *, allow_future: bool = False) -> str:
    text = _strict_text(value, name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise MacroSnapshotError(f"{name} is not a date") from exc
    if not allow_future and parsed > datetime.now(timezone.utc).date():
        raise MacroSnapshotError(f"{name} is in the future")
    return parsed.isoformat()


def _strict_hash(value: object, name: str) -> str:
    text = _strict_text(value, name).lower()
    if SHA256_RE.fullmatch(text) is None:
        raise MacroSnapshotError(f"{name} must be a SHA-256")
    return text


@dataclass(frozen=True, slots=True)
class MacroEvidenceReference:
    """One verifiable provider payload reference."""

    reference_id: str
    provider: str
    series_id: str
    source_url: str
    observed_date: str
    fetched_at: str
    payload_sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> "MacroEvidenceReference":
        if not isinstance(payload, Mapping):
            raise MacroSnapshotError("macro reference must be an object")
        source_url = _strict_text(payload.get("source_url"), "reference.source_url")
        if urllib.parse.urlparse(source_url).scheme not in {"http", "https"}:
            raise MacroSnapshotError("reference source URL is invalid")
        return cls(
            reference_id=_strict_text(payload.get("reference_id"), "reference.reference_id"),
            provider=_strict_text(payload.get("provider"), "reference.provider"),
            series_id=_strict_text(payload.get("series_id"), "reference.series_id"),
            source_url=source_url,
            observed_date=_parse_date(payload.get("observed_date"), "reference.observed_date"),
            fetched_at=_parse_datetime(
                payload.get("fetched_at"), "reference.fetched_at"
            ).isoformat(),
            payload_sha256=_strict_hash(payload.get("payload_sha256"), "reference.payload_sha256"),
        )


@dataclass(frozen=True, slots=True)
class MacroObservation:
    """A single official series observation."""

    series_id: str
    observation_period: str
    value: float
    unit: str
    source: str
    source_url: str
    fetched_at: str
    observed_date: str
    release_date: str | None
    freshness_status: str
    snapshot_fingerprint: str
    schema_version: int
    reference_id: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> "MacroObservation":
        if not isinstance(payload, Mapping):
            raise MacroSnapshotError("macro observation must be an object")
        raw_value = payload.get("value")
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise MacroSnapshotError("macro observation value is invalid")
        value = float(raw_value)
        if not math.isfinite(value):
            raise MacroSnapshotError("macro observation value is not finite")
        source_url = _strict_text(payload.get("source_url"), "observation.source_url")
        if urllib.parse.urlparse(source_url).scheme not in {"http", "https"}:
            raise MacroSnapshotError("observation source URL is invalid")
        release_date = payload.get("release_date")
        return cls(
            series_id=_strict_text(payload.get("series_id"), "observation.series_id"),
            observation_period=_parse_date(
                payload.get("observation_period"), "observation.observation_period"
            ),
            value=value,
            unit=_strict_text(payload.get("unit"), "observation.unit"),
            source=_strict_text(payload.get("source"), "observation.source"),
            source_url=source_url,
            fetched_at=_parse_datetime(
                payload.get("fetched_at"), "observation.fetched_at"
            ).isoformat(),
            observed_date=_parse_date(payload.get("observed_date"), "observation.observed_date"),
            release_date=(
                _parse_date(release_date, "observation.release_date")
                if release_date is not None
                else None
            ),
            freshness_status=_strict_text(
                payload.get("freshness_status"), "observation.freshness_status"
            ),
            snapshot_fingerprint=_strict_hash(
                payload.get("snapshot_fingerprint"), "observation.snapshot_fingerprint"
            ),
            schema_version=_strict_schema(payload.get("schema_version"), "observation"),
            reference_id=_strict_text(payload.get("reference_id"), "observation.reference_id"),
        )


@dataclass(frozen=True, slots=True)
class MacroSnapshot:
    """Validated immutable macro snapshot."""

    schema_version: int
    status: str
    generated_at: str
    as_of_date: str | None
    source: str
    observations: tuple[MacroObservation, ...]
    references: tuple[MacroEvidenceReference, ...]
    warnings: tuple[str, ...]
    snapshot_fingerprint: str
    record_sha256: str

    def semantic_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "as_of_date": self.as_of_date,
            "source": self.source,
            "observations": [
                {
                    **observation.to_dict(),
                    "snapshot_fingerprint": "",
                    "fetched_at": "",
                }
                for observation in self.observations
            ],
            "references": [
                {**reference.to_dict(), "fetched_at": ""} for reference in self.references
            ],
            "warnings": list(self.warnings),
        }

    def record_dict(self) -> dict[str, object]:
        """Return every authoritative field except the self-referential hash.

        ``snapshot_fingerprint`` is the stable semantic identity used by change
        detection.  ``record_sha256`` protects the exact persisted record,
        including generated/fetched timestamps and warnings.
        """

        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "generated_at": self.generated_at,
            "as_of_date": self.as_of_date,
            "source": self.source,
            "observations": [item.to_dict() for item in self.observations],
            "references": [item.to_dict() for item in self.references],
            "warnings": list(self.warnings),
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "record_sha256": "",
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "generated_at": self.generated_at,
            "as_of_date": self.as_of_date,
            "source": self.source,
            "observations": [item.to_dict() for item in self.observations],
            "references": [item.to_dict() for item in self.references],
            "warnings": list(self.warnings),
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "record_sha256": self.record_sha256,
        }

    def validate(self) -> "MacroSnapshot":
        _strict_schema(self.schema_version, "snapshot")
        if self.status not in MACRO_STATUSES:
            raise MacroSnapshotError("macro snapshot status is invalid")
        _parse_datetime(self.generated_at, "snapshot.generated_at")
        if self.as_of_date is not None:
            _parse_date(self.as_of_date, "snapshot.as_of_date")
        _strict_hash(self.snapshot_fingerprint, "snapshot.snapshot_fingerprint")
        expected = _sha256(self.semantic_dict())
        if expected != self.snapshot_fingerprint:
            raise MacroSnapshotError("macro snapshot fingerprint mismatch")
        _strict_hash(self.record_sha256, "snapshot.record_sha256")
        references: dict[str, MacroEvidenceReference] = {}
        for reference in self.references:
            if reference.reference_id in references:
                raise MacroSnapshotError("duplicate macro reference id")
            references[reference.reference_id] = MacroEvidenceReference.from_dict(
                reference.to_dict()
            )
            if reference.series_id not in {item[0] for item in FRED_SERIES.values()}:
                raise MacroSnapshotError("unknown macro reference series")
        seen_series: set[tuple[str, str]] = set()
        used_refs: set[str] = set()
        for observation in self.observations:
            MacroObservation.from_dict(observation.to_dict())
            if observation.series_id not in FRED_SERIES:
                raise MacroSnapshotError("unknown macro observation series")
            expected_unit = FRED_SERIES[observation.series_id][2]
            if observation.unit != expected_unit:
                raise MacroSnapshotError("macro observation unit mismatch")
            key = (observation.series_id, observation.observation_period)
            if key in seen_series:
                raise MacroSnapshotError("duplicate macro observation")
            seen_series.add(key)
            if observation.snapshot_fingerprint != self.snapshot_fingerprint:
                raise MacroSnapshotError("observation snapshot fingerprint mismatch")
            if observation.reference_id not in references:
                raise MacroSnapshotError("unresolved macro reference")
            reference = references[observation.reference_id]
            expected_fred_id = FRED_SERIES[observation.series_id][0]
            if reference.series_id != expected_fred_id:
                raise MacroSnapshotError("macro observation/reference identity mismatch")
            if observation.observed_date != reference.observed_date:
                raise MacroSnapshotError("macro observation/reference date mismatch")
            if observation.source_url != reference.source_url:
                raise MacroSnapshotError("macro observation/reference URL mismatch")
            used_refs.add(observation.reference_id)
        if used_refs != set(references):
            raise MacroSnapshotError("unused macro reference")
        count = len(self.observations)
        if self.status == "ready":
            if count != len(FRED_SERIES) or {item.series_id for item in self.observations} != set(
                FRED_SERIES
            ):
                raise MacroSnapshotError("ready macro snapshot must contain all series")
            if any(item.freshness_status != "fresh" for item in self.observations):
                raise MacroSnapshotError("ready macro observations must be fresh")
        elif self.status == "partial":
            if count == 0 or count >= len(FRED_SERIES):
                raise MacroSnapshotError("partial macro snapshot must contain 1-5 series")
            if any(item.freshness_status != "fresh" for item in self.observations):
                raise MacroSnapshotError("partial macro observations must be fresh")
        elif self.status == "unavailable":
            if self.observations or self.references:
                raise MacroSnapshotError("unavailable macro snapshot must be empty")
        elif self.status == "stale":
            if not self.observations or not self.references:
                raise MacroSnapshotError("stale macro snapshot must retain verified data")
            if any(item.freshness_status != "stale" for item in self.observations):
                raise MacroSnapshotError("stale macro observations must be stale")
        if self.observations:
            expected_as_of = max(item.observed_date for item in self.observations)
            if self.as_of_date != expected_as_of:
                raise MacroSnapshotError("macro snapshot as-of date mismatch")
        elif self.as_of_date is not None:
            raise MacroSnapshotError("empty macro snapshot cannot have an as-of date")
        if _sha256(self.record_dict()) != self.record_sha256:
            raise MacroSnapshotError("macro snapshot record hash mismatch")
        return self

    @classmethod
    def from_dict(cls, payload: object) -> "MacroSnapshot":
        if not isinstance(payload, Mapping):
            raise MacroSnapshotError("macro snapshot must be an object")
        raw_obs = payload.get("observations", [])
        raw_refs = payload.get("references", [])
        raw_warnings = payload.get("warnings", [])
        if (
            not isinstance(raw_obs, list)
            or not isinstance(raw_refs, list)
            or not isinstance(raw_warnings, list)
        ):
            raise MacroSnapshotError("macro snapshot lists are invalid")
        snapshot = cls(
            schema_version=_strict_schema(payload.get("schema_version"), "snapshot"),
            status=_strict_text(payload.get("status"), "snapshot.status"),
            generated_at=_parse_datetime(
                payload.get("generated_at"), "snapshot.generated_at"
            ).isoformat(),
            as_of_date=(
                _parse_date(payload.get("as_of_date"), "snapshot.as_of_date")
                if payload.get("as_of_date") is not None
                else None
            ),
            source=_strict_text(payload.get("source"), "snapshot.source"),
            observations=tuple(MacroObservation.from_dict(item) for item in raw_obs),
            references=tuple(MacroEvidenceReference.from_dict(item) for item in raw_refs),
            warnings=tuple(_strict_text(item, "snapshot.warning") for item in raw_warnings),
            snapshot_fingerprint=_strict_hash(
                payload.get("snapshot_fingerprint"), "snapshot.snapshot_fingerprint"
            ),
            record_sha256=_strict_hash(payload.get("record_sha256"), "snapshot.record_sha256"),
        )
        return snapshot.validate()

    @classmethod
    def create(
        cls,
        *,
        status: str,
        source: str,
        observations: Sequence[MacroObservation],
        references: Sequence[MacroEvidenceReference],
        warnings: Sequence[str] = (),
        generated_at: datetime | None = None,
        as_of_date: str | None = None,
    ) -> "MacroSnapshot":
        generated = (
            (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        )
        provisional = cls(
            schema_version=MACRO_SCHEMA_VERSION,
            status=status,
            generated_at=generated,
            as_of_date=as_of_date,
            source=source,
            observations=tuple(observations),
            references=tuple(references),
            warnings=tuple(warnings),
            snapshot_fingerprint="0" * 64,
            record_sha256="0" * 64,
        )
        fingerprint = _sha256(provisional.semantic_dict())
        finalized = replace(
            provisional,
            snapshot_fingerprint=fingerprint,
            observations=tuple(
                replace(item, snapshot_fingerprint=fingerprint, schema_version=MACRO_SCHEMA_VERSION)
                for item in provisional.observations
            ),
        )
        finalized = replace(finalized, record_sha256=_sha256(finalized.record_dict()))
        return finalized.validate()


@dataclass(frozen=True, slots=True)
class MacroSignal:
    """A deterministic, non-advisory interpretation of one macro series."""

    signal_id: str
    series_id: str
    title: str
    status: str
    current_value: float | None
    previous_value: float | None
    delta: float | None
    unit: str | None
    rule_version: str
    reference_ids: tuple[str, ...]
    next_condition: str
    threshold_distance: float | None
    freshness: str
    limitations: tuple[str, ...]
    observation_period: str | None = None
    observed_date: str | None = None
    release_date: str | None = None
    fetched_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reference_ids"] = list(self.reference_ids)
        payload["limitations"] = list(self.limitations)
        return payload


class MacroProvider(Protocol):
    def fetch(self) -> "MacroProviderResult": ...


@dataclass(frozen=True, slots=True)
class MacroProviderResult:
    observations: tuple[MacroObservation, ...]
    references: tuple[MacroEvidenceReference, ...]
    warnings: tuple[str, ...] = ()
    source: str = "FRED official"
    observation_history: tuple["MacroObservationPoint", ...] = ()


@dataclass(frozen=True, slots=True)
class MacroObservationPoint:
    """One provider observation retained for revision detection."""

    series_id: str
    observation_period: str
    value: float
    payload_sha256: str
    fetched_at: str

    def validate(self) -> "MacroObservationPoint":
        if self.series_id not in FRED_SERIES:
            raise MacroSnapshotError("unknown macro revision series")
        _parse_date(self.observation_period, "revision.observation_period")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise MacroSnapshotError("revision value is invalid")
        if not math.isfinite(float(self.value)):
            raise MacroSnapshotError("revision value is non-finite")
        _strict_hash(self.payload_sha256, "revision.payload_sha256")
        _parse_datetime(self.fetched_at, "revision.fetched_at")
        return self

    def to_dict(self) -> dict[str, object]:
        return {
            "series_id": self.series_id,
            "observation_period": self.observation_period,
            "value": float(self.value),
            "payload_sha256": self.payload_sha256,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "MacroObservationPoint":
        if not isinstance(payload, Mapping):
            raise MacroSnapshotError("revision point must be an object")
        value = payload.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MacroSnapshotError("revision value is invalid")
        point = cls(
            series_id=_strict_text(payload.get("series_id"), "revision.series_id"),
            observation_period=_parse_date(
                payload.get("observation_period"), "revision.observation_period"
            ),
            value=float(value),
            payload_sha256=_strict_hash(payload.get("payload_sha256"), "revision.payload_sha256"),
            fetched_at=_parse_datetime(
                payload.get("fetched_at"), "revision.fetched_at"
            ).isoformat(),
        )
        return point.validate()


@dataclass(frozen=True, slots=True)
class MacroRevisionEntry:
    """Bounded history for one series/period identity."""

    series_id: str
    observation_period: str
    first_seen_value: float
    first_seen_payload_sha256: str
    first_seen_fetched_at: str
    observations: tuple[MacroObservationPoint, ...]

    @property
    def latest(self) -> MacroObservationPoint:
        return self.observations[-1]

    @property
    def revised(self) -> bool:
        return len(self.observations) > 1

    def validate(self) -> "MacroRevisionEntry":
        if not self.observations:
            raise MacroSnapshotError("revision entry is empty")
        key = (self.series_id, self.observation_period)
        if (
            self.latest.series_id != self.series_id
            or self.latest.observation_period != self.observation_period
        ):
            raise MacroSnapshotError("revision entry identity mismatch")
        for point in self.observations:
            point.validate()
            if (point.series_id, point.observation_period) != key:
                raise MacroSnapshotError("revision point identity mismatch")
        if self.first_seen_value != self.observations[0].value:
            raise MacroSnapshotError("revision first-seen value mismatch")
        if self.first_seen_payload_sha256 != self.observations[0].payload_sha256:
            raise MacroSnapshotError("revision first-seen payload mismatch")
        if self.first_seen_fetched_at != self.observations[0].fetched_at:
            raise MacroSnapshotError("revision first-seen timestamp mismatch")
        previous_value: float | None = None
        for index, point in enumerate(self.observations):
            # A revision is an economic-value transition.  Provenance may
            # change between fetches, but repeating the same value must never
            # create a second revision record.
            if index and point.value == previous_value:
                raise MacroSnapshotError("duplicate unchanged revision point")
            previous_value = point.value
        return self

    def to_dict(self) -> dict[str, object]:
        return {
            "series_id": self.series_id,
            "observation_period": self.observation_period,
            "first_seen_value": self.first_seen_value,
            "first_seen_payload_sha256": self.first_seen_payload_sha256,
            "first_seen_fetched_at": self.first_seen_fetched_at,
            "observations": [item.to_dict() for item in self.observations],
        }

    @classmethod
    def from_dict(cls, payload: object) -> "MacroRevisionEntry":
        if not isinstance(payload, Mapping):
            raise MacroSnapshotError("revision entry must be an object")
        raw = payload.get("observations")
        if not isinstance(raw, list):
            raise MacroSnapshotError("revision observations are invalid")
        first = payload.get("first_seen_value")
        if isinstance(first, bool) or not isinstance(first, (int, float)):
            raise MacroSnapshotError("revision first-seen value is invalid")
        entry = cls(
            series_id=_strict_text(payload.get("series_id"), "revision.series_id"),
            observation_period=_parse_date(
                payload.get("observation_period"), "revision.observation_period"
            ),
            first_seen_value=float(first),
            first_seen_payload_sha256=_strict_hash(
                payload.get("first_seen_payload_sha256"), "revision.first_seen_payload_sha256"
            ),
            first_seen_fetched_at=_parse_datetime(
                payload.get("first_seen_fetched_at"), "revision.first_seen_fetched_at"
            ).isoformat(),
            observations=tuple(MacroObservationPoint.from_dict(item) for item in raw),
        )
        return entry.validate()


class MacroRevisionLedgerStore:
    """Atomic, bounded and replayable observation revision ledger."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, *, max_entries: int = 512) -> None:
        if max_entries <= 0:
            raise ValueError("revision ledger limit must be positive")
        self.path = Path(path)
        self.max_entries = max_entries

    @staticmethod
    def _write_atomic(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink(missing_ok=True)

    @classmethod
    def _payload(cls, entries: Sequence[MacroRevisionEntry]) -> dict[str, object]:
        return {
            "schema_version": cls.SCHEMA_VERSION,
            "entries": [entry.to_dict() for entry in entries],
        }

    def load(self) -> tuple[MacroRevisionEntry, ...]:
        if not self.path.is_file():
            return ()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MacroSnapshotError("macro revision ledger is corrupt") from exc
        if not isinstance(payload, Mapping):
            raise MacroSnapshotError("macro revision ledger is invalid")
        schema = payload.get("schema_version")
        if isinstance(schema, bool) or schema != self.SCHEMA_VERSION:
            raise MacroSnapshotError("macro revision ledger schema is unsupported")
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, list):
            raise MacroSnapshotError("macro revision ledger entries are invalid")
        entries = tuple(MacroRevisionEntry.from_dict(item) for item in raw_entries)
        if len({(item.series_id, item.observation_period) for item in entries}) != len(entries):
            raise MacroSnapshotError("duplicate macro revision identity")
        expected_hash = _sha256(self._payload(entries))
        if payload.get("ledger_sha256") != expected_hash:
            raise MacroSnapshotError("macro revision ledger hash mismatch")
        return entries

    def update(self, points: Sequence[MacroObservationPoint]) -> tuple[MacroRevisionEntry, ...]:
        current = {(entry.series_id, entry.observation_period): entry for entry in self.load()}
        changed = False
        for point in points:
            point.validate()
            key = (point.series_id, point.observation_period)
            entry = current.get(key)
            if entry is None:
                current[key] = MacroRevisionEntry(
                    series_id=point.series_id,
                    observation_period=point.observation_period,
                    first_seen_value=point.value,
                    first_seen_payload_sha256=point.payload_sha256,
                    first_seen_fetched_at=point.fetched_at,
                    observations=(point,),
                ).validate()
                changed = True
            elif entry.latest.value != point.value:
                current[key] = replace(entry, observations=(*entry.observations, point)).validate()
                changed = True
        entries = tuple(
            sorted(current.values(), key=lambda item: (item.series_id, item.observation_period))
        )
        if not changed:
            return entries
        if len(entries) > self.max_entries:
            entries = entries[-self.max_entries :]
        payload = self._payload(entries)
        payload["ledger_sha256"] = _sha256(self._payload(entries))
        self._write_atomic(self.path, _canonical(payload).encode("utf-8"))
        return entries

    def important_revisions(self) -> tuple[MacroRevisionEntry, ...]:
        return tuple(item for item in self.load() if item.revised)


class FredMacroProvider:
    """Small official FRED CSV provider; no API key is required."""

    def __init__(
        self, *, timeout_seconds: float = 8.0, opener: Any = urllib.request.urlopen
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.opener = opener

    @staticmethod
    def _parse_csv_rows(payload: bytes, *, series_id: str) -> tuple[tuple[str, float], ...]:
        """Parse all official fredgraph rows using an explicit header contract."""

        try:
            text = payload.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            fieldnames = reader.fieldnames or []
        except (UnicodeDecodeError, csv.Error) as exc:
            raise FredPayloadError(f"{series_id} CSV header is invalid") from exc
        date_column = next((name for name in FRED_DATE_HEADERS if name in fieldnames), None)
        if date_column is None:
            raise FredPayloadError(f"{series_id} CSV is missing observation_date")
        if series_id not in fieldnames:
            raise FredPayloadError(f"{series_id} CSV is missing series column")
        observations: list[tuple[str, float]] = []
        seen_periods: set[str] = set()
        for row in reader:
            raw_date = row.get(date_column)
            raw_value = row.get(series_id)
            if raw_date in (None, "") and raw_value in (None, "", "."):
                continue
            if raw_date in (None, ""):
                raise FredPayloadError(f"{series_id} observation date is missing")
            if raw_value in (None, "", "."):
                continue
            try:
                period = _parse_date(raw_date, f"{series_id}.{date_column}")
                value = float(str(raw_value).replace(",", "").strip())
            except (TypeError, ValueError, MacroSnapshotError) as exc:
                raise FredPayloadError(f"{series_id} observation is invalid") from exc
            if not math.isfinite(value):
                raise FredPayloadError(f"{series_id} observation is non-finite")
            if period in seen_periods:
                raise FredPayloadError(f"{series_id} has duplicate observation period")
            seen_periods.add(period)
            observations.append((period, value))
        if not observations:
            raise FredPayloadError(f"{series_id} CSV has no valid observation")
        return tuple(sorted(observations, key=lambda item: item[0]))

    @staticmethod
    def _parse_csv_payload(payload: bytes, *, series_id: str) -> tuple[str, float]:
        """Parse one official fredgraph CSV and return its latest observation."""

        return FredMacroProvider._parse_csv_rows(payload, series_id=series_id)[-1]

    def fetch(self) -> MacroProviderResult:
        observations: list[MacroObservation] = []
        references: list[MacroEvidenceReference] = []
        observation_history: list[MacroObservationPoint] = []
        warnings: list[str] = []
        fetched_at = datetime.now(timezone.utc).isoformat()
        for key, (series_id, _title, unit) in FRED_SERIES.items():
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            try:
                with self.opener(url, timeout=self.timeout_seconds) as response:
                    payload = response.read()
                rows = self._parse_csv_rows(payload, series_id=series_id)
                period, value = rows[-1]
                payload_hash = _sha256_bytes(payload)
                reference_id = f"macro-{series_id.lower()}-{period}"
                references.append(
                    MacroEvidenceReference(
                        reference_id=reference_id,
                        provider="FRED",
                        series_id=series_id,
                        source_url=url,
                        observed_date=period,
                        fetched_at=fetched_at,
                        payload_sha256=payload_hash,
                    )
                )
                observations.append(
                    MacroObservation(
                        series_id=key,
                        observation_period=period,
                        value=value,
                        unit=unit,
                        source="FRED official",
                        source_url=url,
                        fetched_at=fetched_at,
                        observed_date=period,
                        release_date=None,
                        freshness_status="fresh",
                        snapshot_fingerprint="0" * 64,
                        schema_version=MACRO_SCHEMA_VERSION,
                        reference_id=reference_id,
                    )
                )
                observation_history.extend(
                    MacroObservationPoint(
                        series_id=key,
                        observation_period=row_period,
                        value=row_value,
                        payload_sha256=payload_hash,
                        fetched_at=fetched_at,
                    ).validate()
                    for row_period, row_value in rows
                )
            except FredPayloadError:
                # A reachable but malformed official payload is a contract
                # violation, not an endpoint outage.  Preserve the distinction
                # so callers cannot silently manufacture an unavailable state.
                raise
            except Exception as exc:  # provider failures become explicit partial state
                warnings.append(f"{key} unavailable ({type(exc).__name__})")
        return MacroProviderResult(
            tuple(observations),
            tuple(references),
            tuple(warnings),
            observation_history=tuple(observation_history),
        )


class MacroSnapshotStore:
    """Atomic authoritative latest JSON plus immutable content-addressed history."""

    def __init__(
        self,
        latest_path: str | Path,
        history_dir: str | Path,
        revision_ledger_path: str | Path | None = None,
    ) -> None:
        self.latest_path = Path(latest_path)
        self.history_dir = Path(history_dir)
        self.revision_ledger_path = (
            Path(revision_ledger_path)
            if revision_ledger_path
            else self.history_dir.parent / "revision-ledger.json"
        )
        self.last_warning: str | None = None

    @staticmethod
    def _write_atomic(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink(missing_ok=True)

    def save(self, snapshot: MacroSnapshot) -> None:
        snapshot.validate()
        payload = _canonical(snapshot.to_dict()).encode("utf-8")
        self.history_dir.mkdir(parents=True, exist_ok=True)
        history_path = self.history_dir / f"snapshot-{snapshot.record_sha256}.json"
        descriptor: int | None = None
        own_created = False
        history_published = False
        try:
            try:
                descriptor = os.open(history_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if history_path.read_bytes() != payload:
                    raise MacroSnapshotError("macro history fingerprint collision")
            else:
                own_created = True
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("macro history write made no progress")
                    view = view[written:]
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = None
                history_published = True
            # The immutable history record is authoritative.  A failed latest
            # projection must not remove that record or the previous latest.
            self._write_atomic(self.latest_path, payload)
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            if own_created and not history_published:
                history_path.unlink(missing_ok=True)
            raise

    def load_latest(self) -> MacroSnapshot | None:
        self.last_warning = None
        if not self.latest_path.is_file():
            return None
        try:
            return MacroSnapshot.from_dict(json.loads(self.latest_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.last_warning = f"總經快照無法驗證（{type(exc).__name__}）"
            raise MacroSnapshotError("latest macro snapshot is invalid") from exc

    def history(self) -> tuple[MacroSnapshot, ...]:
        if not self.history_dir.is_dir():
            return ()
        snapshots: list[MacroSnapshot] = []
        for path in sorted(self.history_dir.iterdir()):
            if (
                not path.is_file()
                or path.suffix.lower() != ".json"
                or not path.name.startswith("snapshot-")
            ):
                raise MacroSnapshotError("unexpected macro history file")
            try:
                snapshot = MacroSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise MacroSnapshotError("macro history is corrupt") from exc
            if path.name != f"snapshot-{snapshot.record_sha256}.json":
                raise MacroSnapshotError("macro history identity mismatch")
            snapshots.append(snapshot)
        return tuple(sorted(snapshots, key=lambda item: (item.generated_at, item.record_sha256)))

    def first_seen(self, series_id: str, observation_period: str) -> MacroObservation | None:
        for snapshot in self.history():
            for observation in snapshot.observations:
                if (
                    observation.series_id == series_id
                    and observation.observation_period == observation_period
                ):
                    return observation
        return None


class MacroRuleRegistry:
    """Versioned, deterministic rules; no forecast or investment recommendation."""

    VERSION = "macro-rules-v1"

    def evaluate(
        self, snapshot: MacroSnapshot, previous: MacroSnapshot | None = None
    ) -> tuple[MacroSignal, ...]:
        snapshot.validate()
        previous_map = {item.series_id: item for item in previous.observations} if previous else {}
        signals: list[MacroSignal] = []
        for key, (_fred_id, title, _unit) in FRED_SERIES.items():
            current = next((item for item in snapshot.observations if item.series_id == key), None)
            previous_observation = previous_map.get(key)
            refs = (current.reference_id,) if current else ()
            limitations: list[str] = []
            status = "insufficient_data"
            delta: float | None = None
            if snapshot.status == "unavailable":
                status = "unavailable"
            elif snapshot.status == "stale":
                status = "stale"
                limitations.append("目前沿用最後一份已驗證快照")
            elif current is None:
                status = "insufficient_data"
            elif previous_observation is None:
                status = "insufficient_data"
            elif (
                current.observation_period == previous_observation.observation_period
                and current.value != previous_observation.value
            ):
                status = "revised"
            else:
                delta = current.value - previous_observation.value
                status = "rising" if delta > 0 else "falling" if delta < 0 else "unchanged"
            signals.append(
                MacroSignal(
                    signal_id=f"{key.lower()}-{snapshot.snapshot_fingerprint[:12]}",
                    series_id=key,
                    title=title,
                    status=status,
                    current_value=current.value if current else None,
                    previous_value=previous_observation.value if previous_observation else None,
                    delta=delta,
                    unit=current.unit if current else None,
                    rule_version=self.VERSION,
                    reference_ids=refs,
                    next_condition="下一期官方資料發布後重新確認",
                    threshold_distance=None,
                    freshness=current.freshness_status if current else snapshot.status,
                    limitations=tuple(limitations),
                    observation_period=current.observation_period if current else None,
                    observed_date=current.observed_date if current else None,
                    release_date=current.release_date if current else None,
                    fetched_at=current.fetched_at if current else None,
                )
            )
        return tuple(signals)


class MacroSnapshotApplicationService:
    """Explicit refresh/load orchestration for macro evidence."""

    def __init__(
        self,
        store: MacroSnapshotStore,
        *,
        provider: MacroProvider | None = None,
        revision_ledger: MacroRevisionLedgerStore | None = None,
    ) -> None:
        self.store = store
        self.provider = provider or FredMacroProvider()
        self.revision_ledger = revision_ledger or MacroRevisionLedgerStore(
            store.revision_ledger_path
        )

    def load(self) -> MacroSnapshot | None:
        # Corrupt latest state is not a baseline.  Surface it so callers can
        # show a safe warning instead of fabricating a first observation.
        return self.store.load_latest()

    def refresh(self, *, provider: MacroProvider | None = None) -> MacroSnapshot:
        selected = provider or self.provider
        # An existing history directory is part of the trust boundary.  Do not
        # turn a corrupt immutable record into a new baseline.
        if self.store.history_dir.exists():
            self.store.history()
        previous = self.load()
        try:
            result = selected.fetch()
        except FredPayloadError:
            raise
        except Exception as exc:
            if previous is not None and previous.observations:
                stale_observations = tuple(
                    replace(item, freshness_status="stale") for item in previous.observations
                )
                snapshot = MacroSnapshot.create(
                    status="stale",
                    source=previous.source,
                    observations=stale_observations,
                    references=previous.references,
                    warnings=tuple(
                        (*previous.warnings, f"更新失敗，沿用最後快照（{type(exc).__name__}）")
                    ),
                    as_of_date=previous.as_of_date,
                )
                self.store.save(snapshot)
                return snapshot
            snapshot = MacroSnapshot.create(
                status="unavailable",
                source="FRED official",
                observations=(),
                references=(),
                warnings=(f"目前無可驗證的官方總經資料（{type(exc).__name__}）",),
            )
            self.store.save(snapshot)
            return snapshot
        if not result.observations:
            if result.references:
                raise MacroSnapshotError("empty macro provider result cannot contain references")
            if previous is not None and previous.observations:
                stale_observations = tuple(
                    replace(item, freshness_status="stale") for item in previous.observations
                )
                snapshot = MacroSnapshot.create(
                    status="stale",
                    source=previous.source,
                    observations=stale_observations,
                    references=previous.references,
                    warnings=tuple(
                        (
                            *previous.warnings,
                            *result.warnings,
                            "本次官方資料沒有有效 observations，沿用最後驗證快照",
                        )
                    ),
                    as_of_date=previous.as_of_date,
                )
            else:
                snapshot = MacroSnapshot.create(
                    status="unavailable",
                    source=result.source,
                    observations=(),
                    references=(),
                    warnings=result.warnings or ("目前沒有可驗證的官方總經資料",),
                )
            self.store.save(snapshot)
            return snapshot
        status = "ready" if len(result.observations) == len(FRED_SERIES) else "partial"
        as_of = max((item.observed_date for item in result.observations), default=None)
        snapshot = MacroSnapshot.create(
            status=status,
            source=result.source,
            observations=result.observations,
            references=result.references,
            warnings=result.warnings,
            as_of_date=as_of,
        )
        points = tuple(result.observation_history)
        if not points:
            points = tuple(
                MacroObservationPoint(
                    series_id=observation.series_id,
                    observation_period=observation.observation_period,
                    value=observation.value,
                    payload_sha256=next(
                        reference.payload_sha256
                        for reference in result.references
                        if reference.reference_id == observation.reference_id
                    ),
                    fetched_at=observation.fetched_at,
                )
                for observation in result.observations
            )
        # The revision ledger is authoritative for period-level change history;
        # save it before publishing the latest snapshot so a failed ledger write
        # cannot claim a successful refresh.
        self.revision_ledger.update(points)
        # Persistence failures are not provider failures: surface them so the
        # caller can preserve and report the last successful state.
        self.store.save(snapshot)
        return snapshot


def build_macro_links(
    snapshot: MacroSnapshot,
    *,
    portfolio: Any = None,
    watchlist: Any = None,
    classifications: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[dict[str, object], ...]:
    """Link macro context only when a market-qualified classification is verified."""

    snapshot.validate()
    identities: set[str] = set()
    for frame in (portfolio, watchlist):
        if (
            frame is None
            or getattr(frame, "empty", True)
            or not {"symbol", "market"}.issubset(frame.columns)
        ):
            continue
        for row in frame.loc[:, ["symbol", "market"]].itertuples(index=False):
            try:
                from stock_tool.domain.models import Symbol

                identities.add(Symbol.parse(str(row.symbol), market=str(row.market)).canonical)
            except (TypeError, ValueError):
                continue
    result: list[dict[str, object]] = []
    classifications = classifications or {}
    for identity in sorted(identities):
        classification = classifications.get(identity)
        raw_reference_ids = classification.get("reference_ids", ()) if classification else ()
        reference_ids = (
            tuple(item for item in raw_reference_ids if isinstance(item, str) and item.strip())
            if isinstance(raw_reference_ids, (list, tuple))
            else ()
        )
        limitations = (
            "尚無可驗證總經關聯",
            "分類僅代表本機已驗證產業資訊，不等同於總經暴露規則",
        )
        result.append(
            {
                "identity": identity,
                "sector": classification.get("sector") if classification else None,
                "industry": classification.get("industry") if classification else None,
                "status": "verified" if classification else "unavailable",
                "message": "已驗證市場／分類關聯" if classification else "尚無可驗證對應",
                "rule_version": "macro-exposure-v1",
                "reference_ids": list(reference_ids),
                "limitations": list(limitations),
                "macro_relation_status": "unavailable",
                "macro_relation_message": "尚無可驗證總經關聯",
            }
        )
    return tuple(result)
