"""Allowlisted public assets required in every Windows onedir release."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Callable, Sequence


class ReleaseAssetError(RuntimeError):
    """Raised when a build or promotion is missing a required public release asset."""


_PUBLIC_FILES = (
    "README.md",
    ".env.example",
    "使用教學_簡易版.txt",
    "啟動股票工具.bat",
)
_RELEASE_FILES = ("StockTool.exe", *_PUBLIC_FILES)
_PAYLOAD_RELEASE_FILES = ("StockToolPayload.exe", *_PUBLIC_FILES)
_SAMPLE_DIRECTORY = Path("data") / "sample"


def validate_release_source_assets(source_root: str | Path) -> None:
    """Fail before packaging when a required public source asset is absent."""

    root = Path(source_root)
    missing = [name for name in _PUBLIC_FILES if not (root / name).is_file()]
    if not (root / _SAMPLE_DIRECTORY).is_dir():
        missing.append(_SAMPLE_DIRECTORY.as_posix())
    _raise_for_missing(missing, context="build source")


def copy_release_assets(source_root: str | Path, release_root: str | Path) -> None:
    """Copy only allowlisted public files and bundled sample data into a staging release."""

    source = Path(source_root)
    destination = Path(release_root)
    validate_release_source_assets(source)
    destination.mkdir(parents=True, exist_ok=True)
    for filename in _PUBLIC_FILES:
        shutil.copy2(source / filename, destination / filename)
    shutil.copytree(source / _SAMPLE_DIRECTORY, destination / _SAMPLE_DIRECTORY, dirs_exist_ok=True)


def validate_release_assets(release_root: str | Path) -> None:
    """Fail a staging or promoted release that lacks a required public asset."""

    root = Path(release_root)
    missing = [name for name in _RELEASE_FILES if not (root / name).is_file()]
    sample = root / _SAMPLE_DIRECTORY
    if not sample.is_dir() or not any(sample.iterdir()):
        missing.append(_SAMPLE_DIRECTORY.as_posix())
    _raise_for_missing(missing, context="release")


def validate_payload_release_assets(release_root: str | Path) -> None:
    """Validate public assets bundled beside a versioned payload executable."""

    root = Path(release_root)
    missing = [name for name in _PAYLOAD_RELEASE_FILES if not (root / name).is_file()]
    sample = root / _SAMPLE_DIRECTORY
    if not sample.is_dir() or not any(sample.iterdir()):
        missing.append(_SAMPLE_DIRECTORY.as_posix())
    _raise_for_missing(missing, context="versioned payload")


def validate_release_distribution(
    release_root: str | Path,
    *,
    run_version: Callable[[Sequence[str]], str] | None = None,
) -> None:
    """Validate either a legacy onedir release or the stable-entry layout."""

    root = Path(release_root)
    side_by_side_markers = (root / "Payload", root / "versions", root / "current-version.json")
    if not any(marker.exists() for marker in side_by_side_markers):
        validate_release_assets(root)
        return

    missing: list[str] = []
    if not (root / "StockTool.exe").is_file():
        missing.append("StockTool.exe")
    if not (root / "Payload").is_dir():
        missing.append("Payload")
    if not (root / "versions").is_dir():
        missing.append("versions")
    if not (root / "current-version.json").is_file():
        missing.append("current-version.json")
    _raise_for_missing(missing, context="stable-entry release")

    # Imports stay local because installer_build itself uses this module.
    from stock_tool.installer_build import validate_installer_staging
    from stock_tool.stable_entry import resolve_current_payload

    validate_payload_release_assets(root / "Payload")
    validate_installer_staging(root)
    resolve_current_payload(root, run_version=run_version)


def _raise_for_missing(missing: list[str], *, context: str) -> None:
    if missing:
        raise ReleaseAssetError(
            f"Required {context} asset(s) missing: {', '.join(sorted(missing))}."
        )


def package_release_assets(destination: str | Path, *, payload: bool = False) -> None:
    """Copy and validate assets from this installed source tree without shell Unicode literals."""

    source_root = Path(__file__).resolve().parents[2]
    copy_release_assets(source_root, destination)
    (validate_payload_release_assets if payload else validate_release_assets)(destination)


def main() -> int:
    """Run the build-safe public asset step from ``build_exe.bat``."""

    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--copy-and-validate", type=Path)
    operation.add_argument("--copy-payload-and-validate", type=Path)
    operation.add_argument("--validate-source", action="store_true")
    args = parser.parse_args()
    source_root = Path(__file__).resolve().parents[2]
    if args.validate_source:
        validate_release_source_assets(source_root)
    else:
        package_release_assets(
            args.copy_and_validate or args.copy_payload_and_validate,
            payload=args.copy_payload_and_validate is not None,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
