from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from stock_tool.research.assistant import AIResearchAssistant, ResearchAssistantCache
from stock_tool.research.evidence import ClaimKind, EvidenceBundle, EvidenceRecord
from stock_tool.research.library import ResearchLibrary, ResearchLibraryRestoreError


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        symbol="MU",
        market="US",
        snapshot_fingerprint="snapshot-1",
        evidence=(
            EvidenceRecord(
                evidence_id="price",
                kind=ClaimKind.FACT,
                label="??",
                text="????? 100?",
                source="fixture",
                provider="fixture",
                symbol="MU",
                market="US",
            ),
        ),
    )


def test_backup_restore_is_verified_and_tamper_leaves_current_library(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    bundle = _bundle()
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "cache")).generate(bundle)
    saved = library.save(bundle=bundle, note=note, title="??")
    backup = library.create_backup(tmp_path / "backups" / "library.zip")
    original_hash = library.library_hash()
    library.delete(saved.library_entry_id)
    library.restore(backup.archive_path)
    assert library.library_hash() == original_hash

    tampered = tmp_path / "tampered.zip"
    with ZipFile(backup.archive_path) as source, ZipFile(tampered, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr("../escape.txt", b"x")
    before = library.library_hash()
    with pytest.raises(ResearchLibraryRestoreError):
        library.restore(tampered)
    assert library.library_hash() == before


def test_manifest_hash_tampering_leaves_existing_library_unchanged(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    bundle = _bundle()
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "cache")).generate(bundle)
    library.save(bundle=bundle, note=note, title="研究")
    backup = library.create_backup(tmp_path / "backups" / "library.zip")
    tampered = tmp_path / "tampered-content.zip"
    with ZipFile(backup.archive_path) as source, ZipFile(tampered, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename.startswith("entries/"):
                content = content.replace(b"snapshot-1", b"snapshot-9")
            target.writestr(info, content)
    before = library.library_hash()
    with pytest.raises(ResearchLibraryRestoreError):
        library.restore(tampered)
    assert library.library_hash() == before


def test_empty_library_backup_restores_without_touching_other_runtime_files(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    backup = library.create_backup(tmp_path / "backups" / "empty.zip")
    assert backup.entry_count == 0
    library.restore(backup.archive_path)
    assert library.list_entries() == ()


def test_empty_nonexistent_library_has_a_stable_hash(tmp_path: Path) -> None:
    assert ResearchLibrary(tmp_path / "missing-library").library_hash()


@pytest.mark.parametrize("manifest_update", ({"file_count": 999}, {"unexpected": "metadata"}))
def test_invalid_manifest_metadata_leaves_existing_library_unchanged(
    tmp_path: Path, manifest_update: dict[str, object]
) -> None:
    library = ResearchLibrary(tmp_path / "library")
    bundle = _bundle()
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "cache")).generate(bundle)
    library.save(bundle=bundle, note=note, title="Saved research")
    backup = library.create_backup(tmp_path / "backups" / "library.zip")
    invalid = tmp_path / "invalid-manifest.zip"
    with ZipFile(backup.archive_path) as source, ZipFile(invalid, "w") as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == "RESEARCH_LIBRARY_MANIFEST.json":
                manifest = json.loads(payload.decode("utf-8"))
                manifest.update(manifest_update)
                payload = json.dumps(manifest).encode("utf-8")
            target.writestr(info, payload)
    before = library.library_hash()

    with pytest.raises(ResearchLibraryRestoreError):
        library.restore(invalid)

    assert library.library_hash() == before


def test_duplicate_zip_entry_leaves_existing_library_unchanged(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    bundle = _bundle()
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "cache")).generate(bundle)
    library.save(bundle=bundle, note=note, title="Saved research")
    backup = library.create_backup(tmp_path / "backups" / "library.zip")
    duplicate = tmp_path / "duplicate-entry.zip"
    with ZipFile(backup.archive_path) as source, ZipFile(duplicate, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        entry_name = next(name for name in source.namelist() if name.startswith("entries/"))
        target.writestr(entry_name, source.read(entry_name))
    before = library.library_hash()

    with pytest.raises(ResearchLibraryRestoreError):
        library.restore(duplicate)

    assert library.library_hash() == before


def test_directory_zip_member_leaves_existing_library_unchanged(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    bundle = _bundle()
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "cache")).generate(bundle)
    library.save(bundle=bundle, note=note, title="Saved research")
    backup = library.create_backup(tmp_path / "backups" / "library.zip")
    invalid = tmp_path / "directory-entry.zip"
    with ZipFile(backup.archive_path) as source, ZipFile(invalid, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr("entries/", b"")
    before = library.library_hash()

    with pytest.raises(ResearchLibraryRestoreError):
        library.restore(invalid)

    assert library.library_hash() == before


def test_backup_rejects_unsupported_json_without_creating_an_archive(tmp_path: Path) -> None:
    library = ResearchLibrary(tmp_path / "library")
    bundle = _bundle()
    note = AIResearchAssistant(cache=ResearchAssistantCache(tmp_path / "cache")).generate(bundle)
    library.save(bundle=bundle, note=note, title="Saved research")
    (library.directory / "unexpected.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported files"):
        library.create_backup(tmp_path / "backups" / "library.zip")
