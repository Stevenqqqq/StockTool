from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from stock_tool.release_archive import (
    archive_forbidden_entries,
    create_source_archive,
    required_build_inputs,
    verify_source_archive,
)

PROJECT_ROOT = Path(__file__).parents[1]


def test_source_archive_contains_every_required_exe_build_input(tmp_path: Path) -> None:
    archive_path = tmp_path / "stocktool-source.zip"

    result = create_source_archive(root=PROJECT_ROOT, archive_path=archive_path)

    with ZipFile(archive_path) as archive:
        entries = {entry.filename for entry in archive.infolist() if not entry.is_dir()}

    assert ".streamlit/config.toml" in entries
    assert set(required_build_inputs(PROJECT_ROOT)).issubset(entries)
    assert result.entry_count == len(entries)
    assert not archive_forbidden_entries(entries)
    assert "requirements/stocktool-runtime-constraints.txt" in entries


def test_source_archive_expands_to_complete_rebuild_inputs(tmp_path: Path) -> None:
    archive_path = tmp_path / "stocktool-source.zip"
    extracted_root = tmp_path / "expanded"
    create_source_archive(root=PROJECT_ROOT, archive_path=archive_path)

    verification = verify_source_archive(
        archive_path=archive_path,
        extracted_root=extracted_root,
    )

    assert verification.missing_required_inputs == ()
    assert verification.forbidden_entries == ()
    assert verification.content_mismatches == ()
    assert verification.duplicate_entries == ()
    assert (extracted_root / ".streamlit" / "config.toml").exists()


def test_source_archive_rejects_duplicate_zip_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "duplicate.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("duplicate.txt", "first")
        archive.writestr("duplicate.txt", "second")

    with pytest.raises(ValueError, match="duplicate entries"):
        verify_source_archive(archive_path=archive_path, extracted_root=tmp_path / "expanded")


def test_source_archive_omits_generated_installer_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "installer" / "artifacts").mkdir(parents=True)
    (root / "installer" / "StockTool.iss").write_text("[Setup]\n", encoding="utf-8")
    (root / "installer" / "artifacts" / "generated.exe").write_bytes(b"generated")
    archive_path = tmp_path / "stocktool-source.zip"

    create_source_archive(root=root, archive_path=archive_path)

    with ZipFile(archive_path) as archive:
        entries = set(archive.namelist())
    assert "installer/StockTool.iss" in entries
    assert "installer/artifacts/generated.exe" not in entries


def test_streamlit_archive_allowlist_excludes_secrets_and_private_settings(tmp_path: Path) -> None:
    root = tmp_path / "fake-project"
    streamlit = root / ".streamlit"
    streamlit.mkdir(parents=True)
    (streamlit / "config.toml").write_text("[theme]\nbase = 'dark'\n", encoding="utf-8")
    secret_value = "sprint4122-private-token"
    for filename in ("secrets.toml", "secrets.dev.toml", "credentials.toml", "private.toml"):
        (streamlit / filename).write_text(f"token = '{secret_value}'\n", encoding="utf-8")
    archive_path = tmp_path / "stocktool-source.zip"

    create_source_archive(root=root, archive_path=archive_path)

    with ZipFile(archive_path) as archive:
        entries = {entry.filename for entry in archive.infolist() if not entry.is_dir()}
        archive_text = "\n".join(
            archive.read(entry).decode("utf-8", errors="ignore") for entry in entries
        )
    sidecar_text = archive_path.with_suffix(".zip.sha256").read_text(encoding="ascii")

    assert ".streamlit/config.toml" in entries
    assert not any(
        entry.startswith(".streamlit/") and entry != ".streamlit/config.toml" for entry in entries
    )
    assert secret_value not in archive_text
    assert secret_value not in sidecar_text
    assert all("secret" not in item.lower() for item in required_build_inputs(root))
    assert ".streamlit/config.toml" in required_build_inputs(root)
    assert ".streamlit/secrets.toml" in archive_forbidden_entries((".streamlit/secrets.toml",))
    assert ".streamlit/secrets.dev.toml" in archive_forbidden_entries(
        (".streamlit/secrets.dev.toml",)
    )


def test_build_metadata_packages_only_streamlit_config() -> None:
    spec = (PROJECT_ROOT / "StockTool.spec").read_text(encoding="utf-8")

    assert "('.streamlit\\\\config.toml', '.streamlit')" in spec
    assert "('.streamlit\\\\', '.streamlit')" not in spec
