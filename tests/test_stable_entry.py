"""Production stable-entry authority and side-by-side activation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_tool.stable_entry import (
    AUTHORITY_FILENAME,
    AuthorityError,
    activate_version,
    authority_path,
    resolve_current_payload,
)


def _payload(root: Path, version: str) -> Path:
    target = root / "versions" / version / "StockToolPayload.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"payload")
    return target


def _version_runner(expected: str):
    def run(command: tuple[str, ...] | list[str]) -> str:
        assert command[-1] == "--version"
        return expected + "\n"

    return run


def test_activation_writes_only_the_production_authority_atomically(tmp_path: Path) -> None:
    _payload(tmp_path, "1.2.1")

    activated = activate_version(tmp_path, "1.2.1", run_version=_version_runner("1.2.1"))

    assert activated.version == "1.2.1"
    assert activated.executable == tmp_path / "versions" / "1.2.1" / "StockToolPayload.exe"
    assert json.loads(authority_path(tmp_path).read_text("utf-8")) == {
        "payload": "versions/1.2.1/StockToolPayload.exe",
        "version": "1.2.1",
    }
    assert not (tmp_path / f"{AUTHORITY_FILENAME}.tmp").exists()


@pytest.mark.parametrize(
    "payload",
    (
        {"version": "1.2.1", "payload": "../StockToolPayload.exe"},
        {"version": "1.2.1", "payload": "versions/1.2.2/StockToolPayload.exe"},
        {"version": "1.2.1", "payload": "versions/1.2.1/other.exe"},
        {"version": "01.2.1", "payload": "versions/01.2.1/StockToolPayload.exe"},
    ),
)
def test_authority_rejects_escape_or_noncanonical_payload_layout(
    tmp_path: Path, payload: dict[str, str]
) -> None:
    authority_path(tmp_path).write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AuthorityError):
        resolve_current_payload(tmp_path, run_version=_version_runner("1.2.1"))


def test_authority_rejects_missing_or_version_mismatched_payload(tmp_path: Path) -> None:
    authority_path(tmp_path).write_text(
        json.dumps({"version": "1.2.1", "payload": "versions/1.2.1/StockToolPayload.exe"}),
        encoding="utf-8",
    )

    with pytest.raises(AuthorityError, match="unavailable"):
        resolve_current_payload(tmp_path, run_version=_version_runner("1.2.1"))

    _payload(tmp_path, "1.2.1")
    with pytest.raises(AuthorityError, match="does not match"):
        resolve_current_payload(tmp_path, run_version=_version_runner("1.2.2"))


def test_interrupted_pre_switch_copy_does_not_change_current_authority(tmp_path: Path) -> None:
    _payload(tmp_path, "1.2.1")
    activate_version(tmp_path, "1.2.1", run_version=_version_runner("1.2.1"))
    _payload(tmp_path, "1.2.2")  # The post-copy interruption happens before activation.

    current = resolve_current_payload(tmp_path, run_version=_version_runner("1.2.1"))

    assert current.version == "1.2.1"
    assert (tmp_path / "versions" / "1.2.2" / "StockToolPayload.exe").is_file()


def test_activation_does_not_replace_current_authority_when_new_payload_fails_verification(
    tmp_path: Path,
) -> None:
    _payload(tmp_path, "1.2.1")
    activate_version(tmp_path, "1.2.1", run_version=_version_runner("1.2.1"))
    original = authority_path(tmp_path).read_bytes()
    _payload(tmp_path, "1.2.2")

    with pytest.raises(AuthorityError, match="does not match"):
        activate_version(tmp_path, "1.2.2", run_version=_version_runner("not-1.2.2"))

    assert authority_path(tmp_path).read_bytes() == original
