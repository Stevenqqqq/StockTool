"""Create and verify privacy-safe, reproducible source archives for releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

MANIFEST_NAME = "SOURCE_ARCHIVE_MANIFEST.json"
ROOT_FILES = (
    "AGENTS.md",
    ".env.example",
    ".gitignore",
    "README.md",
    "pyproject.toml",
    "build_exe.bat",
    "build_installer.bat",
    "quality_gate.bat",
    "clean_build.bat",
    "publish_release.bat",
    "launcher.py",
    "stable_launcher.py",
    "run_from_source.bat",
    "StockTool.spec",
    "StableLauncher.spec",
    "CHANGELOG.md",
    "\u555f\u52d5\u80a1\u7968\u5de5\u5177.bat",
    "\u4f7f\u7528\u6559\u5b78_\u7c21\u6613\u7248.txt",
    "PROJECT_WHITEPAPER.md",
    "PRODUCT_VISION.md",
    "PRODUCT_EXECUTION_PLAN.md",
)
TREE_ROOTS = (
    "src",
    "tests",
    "examples",
    "docs",
    "data/sample",
    "installer",
    "scripts",
    "requirements",
)
BUILD_INPUT_ROOTS = ("src", "data/sample", "installer", "scripts", "requirements")
STREAMLIT_CONFIG = ".streamlit/config.toml"
FORBIDDEN_TOP_LEVEL = frozenset({"release", "build", "dist", ".venv", ".git", "reports", "logs"})
FORBIDDEN_PARTS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
FORBIDDEN_FILENAMES = frozenset({".env", "portfolio.csv", "watchlist.csv", ".coverage"})


@dataclass(frozen=True, slots=True)
class SourceArchiveResult:
    """Metadata for a newly created source archive."""

    archive_path: Path
    sha256: str
    entry_count: int
    manifest_path: str


@dataclass(frozen=True, slots=True)
class SourceArchiveVerification:
    """Result of extracting and validating a source archive."""

    missing_required_inputs: tuple[str, ...]
    forbidden_entries: tuple[str, ...]
    content_mismatches: tuple[str, ...]
    duplicate_entries: tuple[str, ...]


def required_build_inputs(root: Path) -> tuple[str, ...]:
    """Return every local source/configuration input needed by ``build_exe.bat``."""

    root = root.resolve()
    required = {item.replace("\\", "/") for item in ROOT_FILES if (root / item).is_file()}
    if (root / STREAMLIT_CONFIG).is_file():
        required.add(STREAMLIT_CONFIG)
    for tree_root in BUILD_INPUT_ROOTS:
        required.update(_relative_files(root, root / tree_root))
    return tuple(sorted(required))


def create_source_archive(*, root: Path, archive_path: Path) -> SourceArchiveResult:
    """Build an allowlisted source ZIP with a file-hash manifest and sidecar."""

    root = root.resolve()
    archive_path = archive_path.resolve()
    files = _archive_files(root)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        archive_path.unlink()

    manifest_files: dict[str, str] = {}
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in files:
            relative = file_path.relative_to(root).as_posix()
            archive.write(file_path, relative)
            manifest_files[relative] = _sha256_file(file_path)
        archive.writestr(
            MANIFEST_NAME,
            json.dumps(
                {
                    "schema_version": 1,
                    "required_build_inputs": list(required_build_inputs(root)),
                    "files": manifest_files,
                },
                indent=2,
                sort_keys=True,
            ),
        )

    sha256 = _sha256_file(archive_path)
    sidecar = archive_path.with_suffix(archive_path.suffix + ".sha256")
    sidecar.write_text(f"{sha256}  {archive_path.name}\n", encoding="ascii")
    return SourceArchiveResult(
        archive_path=archive_path,
        sha256=sha256,
        entry_count=len(manifest_files) + 1,
        manifest_path=MANIFEST_NAME,
    )


def verify_source_archive(
    *,
    archive_path: Path,
    extracted_root: Path,
) -> SourceArchiveVerification:
    """Extract a source archive and verify all required rebuild inputs and hashes."""

    archive_path = archive_path.resolve()
    extracted_root = extracted_root.resolve()
    if extracted_root.exists():
        shutil.rmtree(extracted_root)
    extracted_root.mkdir(parents=True, exist_ok=True)

    with ZipFile(archive_path) as archive:
        entries = tuple(item.filename for item in archive.infolist() if not item.is_dir())
        duplicate_entries = tuple(sorted({entry for entry in entries if entries.count(entry) > 1}))
        if duplicate_entries:
            raise ValueError(
                f"Source archive has duplicate entries: {', '.join(duplicate_entries)}"
            )
        forbidden = archive_forbidden_entries(entries)
        for entry in entries:
            _safe_extract(archive, entry, extracted_root)

    manifest_file = extracted_root / MANIFEST_NAME
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    required = tuple(str(item) for item in payload["required_build_inputs"])
    files = {str(path): str(value) for path, value in payload["files"].items()}
    missing = tuple(item for item in required if not (extracted_root / item).is_file())
    mismatches = tuple(
        item
        for item, expected_hash in files.items()
        if not (extracted_root / item).is_file()
        or _sha256_file(extracted_root / item) != expected_hash
    )
    return SourceArchiveVerification(
        missing_required_inputs=missing,
        forbidden_entries=forbidden,
        content_mismatches=mismatches,
        duplicate_entries=(),
    )


def archive_forbidden_entries(entries: set[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Return forbidden runtime, environment, bytecode, and private ZIP entries."""

    forbidden: list[str] = []
    for entry in entries:
        path = PurePosixPath(entry)
        parts = path.parts
        if not parts:
            continue
        is_forbidden = (
            parts[0] in FORBIDDEN_TOP_LEVEL
            or any(part in FORBIDDEN_PARTS for part in parts)
            or path.name in FORBIDDEN_FILENAMES
            or path.suffix in {".pyc", ".pyo"}
            or (len(parts) >= 2 and parts[0] == "data" and parts[1] == "cache")
            or (parts[0] == ".streamlit" and path.as_posix() != STREAMLIT_CONFIG)
        )
        if is_forbidden:
            forbidden.append(entry)
    return tuple(sorted(forbidden))


def _archive_files(root: Path) -> tuple[Path, ...]:
    files: set[Path] = set()
    for item in ROOT_FILES:
        candidate = root / item
        if candidate.is_file() and not _is_excluded(root, candidate):
            files.add(candidate)
    streamlit_config = root / STREAMLIT_CONFIG
    if streamlit_config.is_file():
        files.add(streamlit_config)
    for tree_root in TREE_ROOTS:
        candidate = root / tree_root
        if candidate.is_dir():
            files.update(
                file_path
                for file_path in candidate.rglob("*")
                if file_path.is_file() and not _is_excluded(root, file_path)
            )
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _relative_files(root: Path, directory: Path) -> tuple[str, ...]:
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            file_path.relative_to(root).as_posix()
            for file_path in directory.rglob("*")
            if file_path.is_file() and not _is_excluded(root, file_path)
        )
    )


def _is_excluded(root: Path, file_path: Path) -> bool:
    relative = file_path.relative_to(root)
    return (
        relative.parts[:2] == ("installer", "artifacts")
        or bool(archive_forbidden_entries((relative.as_posix(),)))
        or any(part.endswith(".egg-info") for part in relative.parts)
    )


def _safe_extract(archive: ZipFile, entry: str, target: Path) -> None:
    relative = PurePosixPath(entry)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe archive entry: {entry}")
    destination = target.joinpath(*relative.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(entry) as source, destination.open("wb") as output:
        shutil.copyfileobj(source, output)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    """Create a source archive from explicit command-line paths."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = create_source_archive(root=args.root, archive_path=args.output)
    print(result.archive_path)
    print(result.sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
