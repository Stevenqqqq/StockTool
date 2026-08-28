"""Verified metadata for unsigned internal-test installer artifacts.

The manifest intentionally contains only public artifact metadata.  Validation
is artifact-bound: metadata is never trusted unless it is compared with the
installer file that will actually be used.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stock_tool import __version__

UPDATE_MANIFEST_SCHEMA_VERSION = 2
INTERNAL_TEST_CHANNEL = "internal-test"
PRODUCT_NAME = "StockTool"
INTERNAL_TEST_PUBLISHER = "StockTool Internal Test"
_NUMERIC_IDENTIFIER = r"(?:0|[1-9]\d*)"
_NON_NUMERIC_IDENTIFIER = r"(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
_PRE_RELEASE_IDENTIFIER = rf"(?:{_NUMERIC_IDENTIFIER}|{_NON_NUMERIC_IDENTIFIER})"
_BUILD_IDENTIFIER = r"[0-9A-Za-z-]+"
_SEMVER_PATTERN = re.compile(
    rf"^(?P<major>{_NUMERIC_IDENTIFIER})\.(?P<minor>{_NUMERIC_IDENTIFIER})\.(?P<patch>{_NUMERIC_IDENTIFIER})"
    rf"(?:-(?P<prerelease>{_PRE_RELEASE_IDENTIFIER}(?:\.{_PRE_RELEASE_IDENTIFIER})*))?"
    rf"(?:\+(?P<build>{_BUILD_IDENTIFIER}(?:\.{_BUILD_IDENTIFIER})*))?$"
)
_ROLLBACK_FIELDS = frozenset({"artifact_filename", "version", "size_bytes", "sha256"})
_STAGING_FIELDS = frozenset({"layout", "stable_entry", "payload"})
_STAGING_ARTIFACT_FIELDS = frozenset({"relative_path", "size_bytes", "sha256"})


@dataclass(frozen=True, slots=True)
class SemanticVersion:
    """Strict SemVer 2.0.0 value with precedence comparison."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    def is_lower_than(self, other: SemanticVersion) -> bool:
        """Return SemVer precedence ordering, ignoring build metadata."""

        core = (self.major, self.minor, self.patch)
        other_core = (other.major, other.minor, other.patch)
        if core != other_core:
            return core < other_core
        if not self.prerelease or not other.prerelease:
            return bool(self.prerelease) and not other.prerelease
        for left, right in zip(self.prerelease, other.prerelease, strict=False):
            if left == right:
                continue
            if left.isdigit() and right.isdigit():
                return int(left) < int(right)
            if left.isdigit() != right.isdigit():
                return left.isdigit()
            return left < right
        return len(self.prerelease) < len(other.prerelease)


def parse_semver(value: object) -> SemanticVersion:
    """Parse a strict SemVer 2.0.0 value or fail closed."""

    if not isinstance(value, str):
        raise ValueError("Version is invalid.")
    match = _SEMVER_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("Version is invalid.")
    prerelease = tuple(match.group("prerelease").split(".")) if match.group("prerelease") else ()
    return SemanticVersion(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        prerelease=prerelease,
    )


def sha256_file(path: Path) -> str:
    """Return the uppercase SHA-256 of a verified regular release artifact."""

    artifact = _regular_executable(path, label="Installer artifact")
    digest = hashlib.sha256()
    with artifact.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def build_update_manifest(
    artifact_path: Path,
    *,
    created_at_utc: datetime | None = None,
    rollback_artifact_path: Path | None = None,
    rollback_version: str | None = None,
    staging_directory: Path | None = None,
) -> dict[str, object]:
    """Create metadata for one unsigned, non-promotable internal artifact."""

    artifact = _artifact_metadata(artifact_path, label="Installer artifact")
    if (rollback_artifact_path is None) != (rollback_version is None):
        raise ValueError("Rollback artifact and version must be provided together.")
    rollback: dict[str, object]
    if rollback_artifact_path is None:
        rollback = {field: None for field in _ROLLBACK_FIELDS}
    else:
        if not _is_rollback_version(rollback_version):
            raise ValueError("Rollback version is invalid.")
        _assert_distinct_rollback_artifact(artifact_path, rollback_artifact_path)
        rollback = {
            **_artifact_metadata(rollback_artifact_path, label="Rollback installer artifact"),
            "version": rollback_version,
        }
    timestamp = (created_at_utc or datetime.now(UTC)).astimezone(UTC)
    payload: dict[str, object] = {
        "schema_version": 2 if staging_directory is not None else 1,
        "product": PRODUCT_NAME,
        "version": __version__,
        "channel": INTERNAL_TEST_CHANNEL,
        "publisher": INTERNAL_TEST_PUBLISHER,
        **artifact,
        "created_at_utc": timestamp.isoformat(),
        "user_data_compatibility": {
            "runtime_layout": "localappdata-stocktool-v1",
            "migration": "none",
        },
        "rollback": rollback,
    }
    if staging_directory is not None:
        payload["staging"] = _staging_metadata(staging_directory)
    return payload


def validate_update_manifest(
    payload: object,
    artifact_path: Path,
    *,
    rollback_artifact_path: Path | None = None,
    staging_directory: Path | None = None,
) -> dict[str, Any]:
    """Fail closed unless a manifest exactly matches its supplied installer files."""

    validated = _validate_manifest_metadata(payload)
    _verify_artifact_matches(
        validated,
        artifact_path,
        label="Installer artifact",
    )
    if validated["schema_version"] == 2:
        if staging_directory is None:
            raise ValueError("Manifest staging directory is required for verification.")
        if _staging_metadata(staging_directory) != validated["staging"]:
            raise ValueError("Staging payload does not match manifest metadata.")
    elif staging_directory is not None:
        raise ValueError("Legacy manifest does not bind staging metadata.")
    rollback = validated["rollback"]
    if rollback["artifact_filename"] is None:
        if rollback_artifact_path is not None:
            raise ValueError("Manifest declares no rollback artifact.")
    else:
        if rollback_artifact_path is None:
            raise ValueError("Rollback installer path is required for verification.")
        _verify_artifact_matches(
            rollback, rollback_artifact_path, label="Rollback installer artifact"
        )
        _assert_distinct_rollback_artifact(artifact_path, rollback_artifact_path)
    return validated


def write_update_manifest(
    artifact_path: Path,
    destination: Path,
    *,
    rollback_artifact_path: Path | None = None,
    rollback_version: str | None = None,
    staging_directory: Path | None = None,
) -> dict[str, Any]:
    """Write a manifest that has been verified against its actual artifact files."""

    payload = build_update_manifest(
        artifact_path,
        rollback_artifact_path=rollback_artifact_path,
        rollback_version=rollback_version,
        staging_directory=staging_directory,
    )
    validated = validate_update_manifest(
        payload,
        artifact_path,
        rollback_artifact_path=rollback_artifact_path,
        staging_directory=staging_directory,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(validated, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return validated


def _validate_manifest_metadata(payload: object) -> dict[str, Any]:
    required = {
        "schema_version",
        "product",
        "version",
        "channel",
        "publisher",
        "artifact_filename",
        "size_bytes",
        "sha256",
        "created_at_utc",
        "user_data_compatibility",
        "rollback",
    }
    if not isinstance(payload, dict) or payload.get("schema_version") not in {1, 2}:
        raise ValueError("Update manifest has an unsupported schema.")
    if payload["schema_version"] == 2:
        required.add("staging")
    if set(payload) != required:
        raise ValueError("Update manifest has an unsupported schema.")
    if (
        payload["product"] != PRODUCT_NAME
        or payload["version"] != __version__
        or payload["channel"] != INTERNAL_TEST_CHANNEL
        or payload["publisher"] != INTERNAL_TEST_PUBLISHER
        or not _is_artifact_metadata(payload)
    ):
        raise ValueError("Update manifest metadata is invalid.")
    try:
        timestamp = datetime.fromisoformat(str(payload["created_at_utc"]))
    except ValueError as exc:
        raise ValueError("Update manifest timestamp is invalid.") from exc
    compatibility = payload["user_data_compatibility"]
    rollback = payload["rollback"]
    if (
        timestamp.tzinfo is None
        or timestamp.utcoffset() != UTC.utcoffset(timestamp)
        or compatibility != {"runtime_layout": "localappdata-stocktool-v1", "migration": "none"}
        or not isinstance(rollback, dict)
        or set(rollback) != _ROLLBACK_FIELDS
    ):
        raise ValueError("Update manifest compatibility metadata is invalid.")
    if payload["schema_version"] == 2 and not _is_staging_metadata(payload["staging"]):
        raise ValueError("Update manifest staging metadata is invalid.")
    has_rollback = rollback["artifact_filename"] is not None
    if has_rollback:
        if (
            not _is_artifact_metadata(rollback)
            or not _is_rollback_version(rollback["version"])
            or rollback["artifact_filename"] == payload["artifact_filename"]
        ):
            raise ValueError("Rollback metadata is invalid.")
    elif any(rollback[field] is not None for field in _ROLLBACK_FIELDS):
        raise ValueError("Rollback metadata is incomplete.")
    return payload


def _staging_metadata(staging_directory: Path) -> dict[str, object]:
    stage = Path(staging_directory)
    stable = stage / "StockTool.exe"
    payload = stage / "Payload" / "StockToolPayload.exe"
    return {
        "layout": "side-by-side-v1",
        "stable_entry": _staging_artifact_metadata(stage, stable),
        "payload": _staging_artifact_metadata(stage, payload),
    }


def _staging_artifact_metadata(stage: Path, artifact: Path) -> dict[str, object]:
    resolved_stage = stage.resolve()
    resolved_artifact = _regular_executable(artifact, label="Staging artifact")
    if not resolved_artifact.is_relative_to(resolved_stage):
        raise ValueError("Staging artifact escapes its root.")
    return {
        "relative_path": resolved_artifact.relative_to(resolved_stage).as_posix(),
        "size_bytes": resolved_artifact.stat().st_size,
        "sha256": sha256_file(resolved_artifact),
    }


def _is_staging_metadata(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _STAGING_FIELDS:
        return False
    if value.get("layout") != "side-by-side-v1":
        return False
    expected = {
        "stable_entry": "StockTool.exe",
        "payload": "Payload/StockToolPayload.exe",
    }
    for name, relative_path in expected.items():
        item = value.get(name)
        if (
            not isinstance(item, dict)
            or set(item) != _STAGING_ARTIFACT_FIELDS
            or item.get("relative_path") != relative_path
            or type(item.get("size_bytes")) is not int
            or item["size_bytes"] <= 0
            or not _is_sha256(item.get("sha256"))
        ):
            return False
    return True


def _artifact_metadata(path: Path, *, label: str) -> dict[str, object]:
    artifact = _regular_executable(path, label=label)
    return {
        "artifact_filename": artifact.name,
        "size_bytes": artifact.stat().st_size,
        "sha256": sha256_file(artifact),
    }


def _verify_artifact_matches(metadata: dict[str, Any], path: Path, *, label: str) -> None:
    actual = _artifact_metadata(path, label=label)
    expected = {field: metadata[field] for field in actual}
    if actual != expected:
        raise ValueError(f"{label} does not match manifest metadata.")


def _regular_executable(path: Path, *, label: str) -> Path:
    artifact = Path(path)
    if artifact.is_symlink() or not artifact.is_file() or artifact.suffix.lower() != ".exe":
        raise ValueError(f"{label} must be an existing regular .exe file.")
    return artifact.resolve()


def _is_artifact_metadata(metadata: object) -> bool:
    return (
        isinstance(metadata, dict)
        and isinstance(metadata.get("artifact_filename"), str)
        and _is_safe_executable_filename(metadata["artifact_filename"])
        and type(metadata.get("size_bytes")) is int
        and metadata["size_bytes"] > 0
        and _is_sha256(metadata.get("sha256"))
    )


def _is_safe_executable_filename(value: str) -> bool:
    return bool(value.strip()) and value == Path(value).name and value.lower().endswith(".exe")


def _is_rollback_version(value: object) -> bool:
    try:
        candidate = parse_semver(value)
        canonical = parse_semver(__version__)
    except ValueError:
        return False
    return candidate.is_lower_than(canonical)


def _assert_distinct_rollback_artifact(artifact_path: Path, rollback_artifact_path: Path) -> None:
    artifact = _regular_executable(artifact_path, label="Installer artifact")
    rollback = _regular_executable(rollback_artifact_path, label="Rollback installer artifact")
    if (
        artifact == rollback
        or artifact.name == rollback.name
        or sha256_file(artifact) == sha256_file(rollback)
    ):
        raise ValueError("Rollback installer must be a distinct artifact with a different hash.")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789ABCDEF" for character in value)
    )
