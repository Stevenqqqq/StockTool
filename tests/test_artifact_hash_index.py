from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.verify_artifact_hash_index import verify_artifact_hash_index


def _write_index(root: Path) -> Path:
    payload = root / "payload.txt"
    payload.write_bytes(b"payload\n")
    index = root / "artifact-hash-index.json"
    entries = [
        {
            "path": "payload.txt",
            "size_bytes": payload.stat().st_size,
            "sha256": hashlib.sha256(payload.read_bytes()).hexdigest().upper(),
        }
    ]
    index.write_bytes(
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "index_kind": "test",
                    "self_reference_exclusions": [
                        "artifact-hash-index.json",
                        "artifact-hash-index.sha256",
                    ],
                    "entry_count": len(entries),
                    "entries": entries,
                },
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
    )
    (root / "artifact-hash-index.sha256").write_bytes(
        (hashlib.sha256(index.read_bytes()).hexdigest().upper() + "\n").encode("ascii")
    )
    return index


def test_artifact_index_accepts_exact_entries_and_count(tmp_path: Path) -> None:
    result = verify_artifact_hash_index(_write_index(tmp_path))
    assert result["passed"] is True
    assert result["entry_count"] == result["actual_entry_count"] == 1


@pytest.mark.parametrize("mutation", ["count", "missing", "extra", "hash", "size", "sidecar"])
def test_artifact_index_fails_closed_for_integrity_mutations(tmp_path: Path, mutation: str) -> None:
    index = _write_index(tmp_path)
    payload = tmp_path / "artifact-hash-index.json"
    raw = json.loads(payload.read_text(encoding="utf-8"))
    if mutation == "count":
        raw["entry_count"] = 0
        payload.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    elif mutation == "missing":
        (tmp_path / "payload.txt").unlink()
    elif mutation == "extra":
        (tmp_path / "extra.txt").write_bytes(b"extra")
    elif mutation == "hash":
        raw["entries"][0]["sha256"] = "A" * 63
        payload.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        (tmp_path / "artifact-hash-index.sha256").write_bytes(
            (hashlib.sha256(payload.read_bytes()).hexdigest().upper() + "\n").encode("ascii")
        )
    elif mutation == "size":
        raw["entries"][0]["size_bytes"] = True
        payload.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    elif mutation == "sidecar":
        (tmp_path / "artifact-hash-index.sha256").write_text("0" * 64 + "\n", encoding="ascii")
    result = verify_artifact_hash_index(index)
    assert result["passed"] is False


def test_artifact_index_rejects_duplicate_entry_and_path_escape(tmp_path: Path) -> None:
    index = _write_index(tmp_path)
    raw = json.loads(index.read_text(encoding="utf-8"))
    raw["entries"].append(dict(raw["entries"][0]))
    raw["entry_count"] = 2
    index.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    (tmp_path / "artifact-hash-index.sha256").write_bytes(
        (hashlib.sha256(index.read_bytes()).hexdigest().upper() + "\n").encode("ascii")
    )
    assert verify_artifact_hash_index(index)["passed"] is False


def test_hash_index_builder_accepts_explicit_root_and_output(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "payload.txt").write_bytes(b"payload\n")
    output = root / "artifact-hash-index.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_artifact_hash_index.py",
            "--root",
            str(root),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert verify_artifact_hash_index(output)["passed"] is True
