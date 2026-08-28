"""Build only unsigned, per-user internal-test installers for Sprint 18 Phase A."""

from __future__ import annotations

import os
import hashlib
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from stock_tool import __version__
from stock_tool.release_assets import validate_payload_release_assets
from stock_tool.release_manifest import write_update_manifest
from stock_tool.version_resource import windows_version_tuple

_INNO_CANDIDATES = (
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
)
_FORBIDDEN_STAGE_PARTS = frozenset(
    {
        "cache",
        "logs",
        "reports",
        "backups",
        "ledger",
        "research_library",
        "daily_research",
        "documents",
    }
)
_PRIVATE_NAME_MARKERS = (
    "portfolio",
    "watchlist",
    "settings",
    "credential",
    "credentials",
    "secret",
    "token",
    "private",
)
_PRIVATE_CERTIFICATE_SUFFIXES = frozenset({".pem", ".key", ".pfx", ".p12"})
_ALLOWED_TOP_LEVEL_NAMES = frozenset(
    {"StockTool.exe", "Payload", "versions", "current-version.json"}
)
_PUBLIC_THIRD_PARTY_NAME_ALLOWLIST = frozenset(
    {
        "Payload/_internal/certifi/cacert.pem",
        "Payload/_internal/api-ms-win-crt-private-l1-1-0.dll",
        "Payload/_internal/pyarrow/include/arrow/vendored/datetime/tz_private.h",
        "Payload/_internal/streamlit/runtime/credentials.py",
        "Payload/_internal/streamlit/runtime/secrets.py",
    }
)


@dataclass(frozen=True, slots=True)
class InstallerBuildResult:
    """Public paths for one unsigned internal-test installer candidate."""

    installer_path: Path
    manifest_path: Path


@dataclass(frozen=True, slots=True)
class SigningPrerequisites:
    """Read-only discovery result; this module never signs an artifact."""

    signtool_path: Path | None
    certificate_configured: bool

    @property
    def ready(self) -> bool:
        return self.signtool_path is not None and self.certificate_configured


def find_inno_setup_compiler() -> Path | None:
    """Find a locally installed Inno Setup compiler without downloading anything."""

    configured = os.environ.get("ISCC", "").strip()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    per_user = (
        [Path(local_app_data) / "Programs" / "Inno Setup 6" / "ISCC.exe"] if local_app_data else []
    )
    candidates = ([Path(configured)] if configured else []) + [*_INNO_CANDIDATES, *per_user]
    on_path = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if on_path:
        candidates.append(Path(on_path))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def detect_signing_prerequisites() -> SigningPrerequisites:
    """Inspect signing prerequisites without reading certificate contents or signing."""

    configured = os.environ.get("STOCK_TOOL_SIGNING_CERTIFICATE", "").strip()
    signtool = shutil.which("signtool.exe") or shutil.which("signtool")
    return SigningPrerequisites(
        signtool_path=Path(signtool) if signtool else None,
        certificate_configured=bool(configured),
    )


def validate_installer_staging(
    staging_directory: Path,
    *,
    output_directory: Path | None = None,
) -> None:
    """Reject private, linked, or escaping content before Inno Setup can consume it."""

    stage = Path(staging_directory)
    if not stage.is_dir() or _is_reparse_point(stage):
        raise ValueError("Installer staging root must be a real directory, not a reparse point.")
    root = stage.resolve()
    if output_directory is not None:
        _validate_output_directory(root, Path(output_directory).resolve())
    for item in _staging_items(stage):
        if _is_reparse_point(item):
            raise ValueError(f"Installer staging cannot contain linked or reparse content: {item}")
        try:
            resolved = item.resolve()
            relative = item.relative_to(stage)
        except ValueError as exc:
            raise ValueError(f"Installer staging contains an unsafe path: {item}") from exc
        if not resolved.is_relative_to(root):
            raise ValueError(f"Installer staging content escapes its root: {relative}")
        _validate_staging_relative_path(relative)
    _validate_versioned_payload_copy(stage)


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _staging_items(root: Path) -> tuple[Path, ...]:
    """Enumerate without following a directory link before it can be rejected."""

    items: list[Path] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        items.extend(current_path / name for name in directories)
        items.extend(current_path / name for name in files)
    return tuple(sorted(items, key=lambda candidate: candidate.as_posix()))


def _validate_output_directory(staging_root: Path, output_root: Path) -> None:
    if (
        output_root == staging_root
        or output_root.is_relative_to(staging_root)
        or staging_root.is_relative_to(output_root)
    ):
        raise ValueError("Installer output directory must not contain or be contained by staging.")


def _validate_staging_relative_path(relative: Path) -> None:
    if relative.parts[0] not in _ALLOWED_TOP_LEVEL_NAMES:
        raise ValueError(f"Installer staging contains an unexpected top-level item: {relative}")
    if relative.parts[0] == "versions":
        _validate_versioned_relative_path(relative)
        return
    if (
        len(relative.parts) > 2
        and relative.parts[0] == "Payload"
        and relative.parts[1] == "data"
        and relative.parts[:3] != ("Payload", "data", "sample")
    ):
        raise ValueError(f"Installer staging contains an unexpected data item: {relative}")
    _reject_private_staging_path(relative)


def _validate_versioned_relative_path(relative: Path) -> None:
    """Validate the derived version copy with the same privacy policy as Payload."""

    if len(relative.parts) == 1:
        return
    if relative.parts[1] != __version__:
        raise ValueError(f"Installer staging contains an unexpected version payload: {relative}")
    payload_relative = Path("Payload", *relative.parts[2:])
    if len(payload_relative.parts) > 2 and payload_relative.parts[1] == "data":
        if payload_relative.parts[:3] != ("Payload", "data", "sample"):
            raise ValueError(f"Installer staging contains an unexpected data item: {relative}")
    _reject_private_staging_path(payload_relative)


def _validate_versioned_payload_copy(stage: Path) -> None:
    """Fail closed if a versioned payload is not an exact copy of Payload.

    The version directory is product state, not a second arbitrary staging input.
    Requiring byte-for-byte correspondence preserves the privacy boundary while
    allowing the stable launcher to be smoke-tested from the real layout.
    """

    version_root = stage / "versions"
    if not version_root.exists():
        return
    expected = stage / "Payload"
    actual = version_root / __version__
    if not expected.is_dir() or not actual.is_dir():
        raise ValueError("Installer staging versioned payload is incomplete.")
    expected_files = _regular_file_hashes(expected)
    actual_files = _regular_file_hashes(actual)
    if expected_files != actual_files:
        raise ValueError("Installer staging versioned payload does not match Payload.")


def _regular_file_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _staging_items(root):
        if not item.is_file():
            continue
        digest = hashlib.sha256()
        with item.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        result[item.relative_to(root).as_posix()] = digest.hexdigest().upper()
    return result


def _reject_private_staging_path(relative: Path) -> None:
    name = relative.name.lower()
    parts = {part.lower() for part in relative.parts}
    relative_name = relative.as_posix()
    if relative_name in _PUBLIC_THIRD_PARTY_NAME_ALLOWLIST:
        return
    if name != ".env.example" and (name == ".env" or name.startswith(".env.")):
        raise ValueError(f"Installer staging contains a private environment file: {relative}")
    if relative.suffix.lower() in _PRIVATE_CERTIFICATE_SUFFIXES:
        raise ValueError(f"Installer staging contains a private key or certificate: {relative}")
    if any(marker in name for marker in _PRIVATE_NAME_MARKERS):
        raise ValueError(f"Installer staging contains a private named item: {relative}")
    if name.endswith((".sqlite", ".db")):
        raise ValueError(f"Installer staging contains private runtime data: {relative}")
    if any(part in _FORBIDDEN_STAGE_PARTS for part in parts):
        raise ValueError(f"Installer staging contains a private runtime directory: {relative}")


def build_unsigned_internal_test_installer(
    *,
    project_root: Path,
    staging_directory: Path,
    output_directory: Path,
    compiler: Path | None = None,
    rollback_artifact_path: Path | None = None,
    rollback_version: str | None = None,
    disable_shell_integration: bool = False,
) -> InstallerBuildResult:
    """Compile a staging-only installer; production signing/promotion is unsupported."""

    root = Path(project_root).resolve()
    stage = Path(staging_directory)
    output = Path(output_directory).resolve()
    validate_installer_staging(stage, output_directory=output)
    stage = stage.resolve()
    payload = stage / "Payload"
    if not (stage / "StockTool.exe").is_file():
        raise ValueError("Installer staging is missing the stable StockTool.exe entry.")
    validate_payload_release_assets(payload)
    iscc = Path(compiler).resolve() if compiler else find_inno_setup_compiler()
    if iscc is None or not iscc.is_file():
        raise FileNotFoundError("Inno Setup 6 ISCC.exe is required for installer compilation.")
    source = root / "installer" / "StockTool.iss"
    if not source.is_file():
        raise FileNotFoundError("Installer source is missing.")
    numeric_version = windows_version_tuple(__version__).replace(", ", ".")
    subprocess.run(
        [
            str(iscc),
            f"/DMyAppVersion={__version__}",
            f"/DMyAppNumericVersion={numeric_version}",
            f"/DMyStageDir={stage}",
            f"/DMyOutputDir={output}",
            f"/DMyDisableShellIntegration={int(disable_shell_integration)}",
            str(source),
        ],
        cwd=root,
        check=True,
    )
    installer = output / f"StockTool-Setup-{__version__}-internal-test.exe"
    if not installer.is_file():
        raise RuntimeError("Inno Setup did not produce the expected internal-test installer.")
    manifest = output / "update_manifest.json"
    write_update_manifest(
        installer,
        manifest,
        rollback_artifact_path=rollback_artifact_path,
        rollback_version=rollback_version,
        staging_directory=stage,
    )
    return InstallerBuildResult(installer_path=installer, manifest_path=manifest)
