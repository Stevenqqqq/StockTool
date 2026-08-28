"""Fail-closed authority for the stable Windows StockTool entry point."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

AUTHORITY_FILENAME = "current-version.json"
PAYLOAD_FILENAME = "StockToolPayload.exe"
_VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


class AuthorityError(RuntimeError):
    """Raised when a stable entry cannot safely select an installed payload."""


@dataclass(frozen=True, slots=True)
class CurrentPayload:
    """One validated payload selected by the production authority file."""

    version: str
    executable: Path


def authority_path(program_root: Path) -> Path:
    """Return the one authority location used by the installed product."""

    return Path(program_root) / AUTHORITY_FILENAME


def payload_relative_path(version: str) -> Path:
    """Return the only permitted relative payload path for a version."""

    if not _VERSION_RE.fullmatch(version):
        raise AuthorityError("Authority version is invalid.")
    return Path("versions") / version / PAYLOAD_FILENAME


def resolve_current_payload(
    program_root: Path,
    *,
    run_version: Callable[[Sequence[str]], str] | None = None,
) -> CurrentPayload:
    """Resolve and verify the authority target without searching for executables."""

    root = Path(program_root).resolve()
    authority = authority_path(root)
    try:
        raw = json.loads(authority.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorityError("Current-version authority is missing or invalid.") from exc
    if not isinstance(raw, dict) or set(raw) != {"version", "payload"}:
        raise AuthorityError("Current-version authority has an unsupported schema.")
    version = raw.get("version")
    payload = raw.get("payload")
    if not isinstance(version, str) or not isinstance(payload, str):
        raise AuthorityError("Current-version authority has invalid values.")
    expected = payload_relative_path(version)
    supplied = Path(payload)
    if supplied.is_absolute() or supplied != expected:
        raise AuthorityError("Current-version authority points outside the version layout.")
    target = (root / supplied).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise AuthorityError("Current-version authority escapes the program root.") from exc
    if target.is_symlink() or not target.is_file() or target.name != PAYLOAD_FILENAME:
        raise AuthorityError("Current-version payload is unavailable.")
    observed = (run_version or _run_payload_version)((str(target), "--version"))
    if observed.strip() != version:
        raise AuthorityError("Current-version payload does not match the authority version.")
    return CurrentPayload(version=version, executable=target)


def activate_version(
    program_root: Path,
    version: str,
    *,
    run_version: Callable[[Sequence[str]], str] | None = None,
) -> CurrentPayload:
    """Verify a copied version then atomically make it the current payload."""

    root = Path(program_root).resolve()
    candidate = payload_relative_path(version)
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise AuthorityError("Activation target escapes the program root.") from exc
    if target.is_symlink() or not target.is_file():
        raise AuthorityError("Activation payload is unavailable.")
    observed = (run_version or _run_payload_version)((str(target), "--version"))
    if observed.strip() != version:
        raise AuthorityError("Activation payload version does not match the requested version.")
    _atomic_write_authority(root, version=version, payload=candidate.as_posix())
    return CurrentPayload(version=version, executable=target)


def _atomic_write_authority(program_root: Path, *, version: str, payload: str) -> None:
    """Write the minimal authority via temp file and replace, never partial JSON."""

    destination = authority_path(program_root)
    temporary = destination.with_name(destination.name + ".tmp")
    encoded = json.dumps({"version": version, "payload": payload}, sort_keys=True) + "\n"
    try:
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, destination)
    except OSError as exc:
        raise AuthorityError("Unable to atomically update current-version authority.") from exc
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _run_payload_version(command: Sequence[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
    if completed.returncode != 0:
        raise AuthorityError("Current-version payload failed its version verification.")
    return completed.stdout
