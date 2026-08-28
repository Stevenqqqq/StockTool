"""Fail-closed verifier for a hash-bound artifact directory index.

The index is intentionally a projection of a directory, never a trust source
for files that are absent from the directory.  All paths, sizes and SHA-256
values are checked against raw bytes on disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SELF_EXCLUSIONS = ("artifact-hash-index.json", "artifact-hash-index.sha256")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _read_utf8_json(path: Path) -> Any:
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("index has a BOM")
    if b"\r" in raw:
        raise ValueError("index must use LF-only UTF-8")
    return json.loads(raw.decode("utf-8"))


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("entry path is missing")
    path = Path(value)
    if (
        path.is_absolute()
        or "\\" in value
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"entry path is not canonical: {value!r}")
    if value in SELF_EXCLUSIONS:
        raise ValueError("index self-reference is forbidden")
    return value


def _require_size(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("entry size must be a non-negative integer")
    return value


def _require_hash(value: object) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError("entry SHA-256 must be exactly 64 hexadecimal characters")
    return value.upper()


def verify_artifact_hash_index(index_path: str | Path) -> dict[str, Any]:
    """Verify one directory index and return a machine-readable result."""

    index = Path(index_path).resolve()
    root = index.parent
    errors: list[str] = []
    missing: list[str] = []
    extra: list[str] = []
    mismatches: list[str] = []
    try:
        if not index.is_file() or index.name != SELF_EXCLUSIONS[0]:
            raise ValueError("index file is unavailable or has an invalid name")
        payload = _read_utf8_json(index)
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("index schema_version must be 1")
        if payload.get("self_reference_exclusions") != list(SELF_EXCLUSIONS):
            raise ValueError("self-reference exclusions are invalid")
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise ValueError("entries must be a list")
        entry_count = payload.get("entry_count")
        if isinstance(entry_count, bool) or not isinstance(entry_count, int):
            raise ValueError("entry_count must be an integer")
        if entry_count != len(entries):
            raise ValueError("entry_count does not equal the entries length")

        expected: dict[str, tuple[int, str]] = {}
        for raw_entry in entries:
            if not isinstance(raw_entry, dict) or set(raw_entry) != {
                "path",
                "size_bytes",
                "sha256",
            }:
                raise ValueError("entry schema is invalid")
            relative = _safe_relative(raw_entry["path"])
            if relative in expected:
                raise ValueError(f"duplicate entry: {relative}")
            expected[relative] = (
                _require_size(raw_entry["size_bytes"]),
                _require_hash(raw_entry["sha256"]),
            )

        actual: dict[str, Path] = {}
        for candidate in root.rglob("*"):
            if candidate.is_symlink():
                relative = candidate.relative_to(root).as_posix()
                raise ValueError(f"symlink artifact is forbidden: {relative}")
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(root).as_posix()
            if relative in SELF_EXCLUSIONS:
                continue
            actual[relative] = candidate
        if set(expected) != set(actual):
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            raise ValueError(f"index file set mismatch; missing={missing}; extra={extra}")
        for relative, candidate in actual.items():
            expected_size, expected_hash = expected[relative]
            if candidate.stat().st_size != expected_size:
                mismatches.append(relative)
                raise ValueError(f"size mismatch: {relative}")
            if _sha256(candidate) != expected_hash:
                mismatches.append(relative)
                raise ValueError(f"SHA-256 mismatch: {relative}")

        sidecar = root / SELF_EXCLUSIONS[1]
        if not sidecar.is_file():
            raise ValueError("index sidecar is missing")
        sidecar_raw = sidecar.read_bytes()
        if sidecar_raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
            raise ValueError("index sidecar has a BOM")
        sidecar_text = sidecar_raw.decode("utf-8")
        if "\r" in sidecar_text:
            raise ValueError("index sidecar must use LF-only UTF-8")
        if sidecar_text != f"{_sha256(index)}\n":
            raise ValueError("index sidecar does not match index bytes")
    except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return {
        "schema_version": 1,
        "index_path": index.name,
        "entry_count": (
            payload.get("entry_count")
            if "payload" in locals() and isinstance(payload, dict)
            else None
        ),
        "actual_entry_count": (
            len(payload.get("entries", []))
            if "payload" in locals()
            and isinstance(payload, dict)
            and isinstance(payload.get("entries"), list)
            else None
        ),
        "missing": missing,
        "extra": extra,
        "mismatches": mismatches,
        "errors": errors,
        "passed": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path)
    args = parser.parse_args()
    result = verify_artifact_hash_index(args.index)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
