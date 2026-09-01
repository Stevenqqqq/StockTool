"""Sprint 18.1 installer, manifest, and staging-boundary regression tests."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from stock_tool import __version__
from stock_tool.installer_build import (
    build_unsigned_internal_test_installer,
    detect_signing_prerequisites,
    validate_installer_staging,
)
from stock_tool.release_archive import required_build_inputs
from stock_tool.release_assets import copy_release_assets
from stock_tool.release_manifest import (
    INTERNAL_TEST_CHANNEL,
    INTERNAL_TEST_PUBLISHER,
    build_update_manifest,
    validate_update_manifest,
    write_update_manifest,
)
from stock_tool.version_resource import version_resource_text, windows_version_tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _artifact(tmp_path: Path, name: str = "StockTool-Setup-1.2.2-internal-test.exe") -> Path:
    artifact = tmp_path / name
    artifact.write_bytes(f"unsigned internal test installer: {name}".encode("utf-8"))
    return artifact


def _side_by_side_staging(tmp_path: Path) -> Path:
    staging = tmp_path / "staging" / "StockTool"
    copy_release_assets(PROJECT_ROOT, staging / "Payload")
    (staging / "StockTool.exe").parent.mkdir(parents=True, exist_ok=True)
    (staging / "StockTool.exe").write_bytes(b"fake stable entry")
    (staging / "Payload" / "StockToolPayload.exe").write_bytes(b"fake version payload")
    versioned = staging / "versions" / __version__
    versioned.mkdir(parents=True, exist_ok=True)
    for item in (staging / "Payload").iterdir():
        if item.is_dir():
            shutil.copytree(item, versioned / item.name)
        else:
            (versioned / item.name).write_bytes(item.read_bytes())
    return staging


def test_update_manifest_is_generated_from_artifact_hash_and_canonical_version(
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path)

    payload = build_update_manifest(artifact, created_at_utc=datetime(2026, 7, 28, tzinfo=UTC))

    assert payload["version"] == __version__
    assert payload["channel"] == INTERNAL_TEST_CHANNEL
    assert payload["publisher"] == INTERNAL_TEST_PUBLISHER
    assert payload["artifact_filename"] == artifact.name
    assert payload["size_bytes"] == artifact.stat().st_size
    assert payload["sha256"]
    assert str(payload["created_at_utc"]).endswith("+00:00")
    assert str(tmp_path) not in json.dumps(payload)
    assert validate_update_manifest(payload, artifact) == payload


@pytest.mark.parametrize(
    "field,value",
    (("channel", "production"), ("publisher", "Publisher TBD"), ("sha256", "F" * 64)),
)
def test_update_manifest_fails_closed_for_non_internal_or_tampered_metadata(
    tmp_path: Path, field: str, value: object
) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    payload = build_update_manifest(artifact)
    payload[field] = value

    with pytest.raises(ValueError):
        validate_update_manifest(payload, artifact)


def test_manifest_rejects_installer_changed_after_manifest_creation(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    payload = build_update_manifest(artifact)
    artifact.write_bytes(artifact.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="does not match"):
        validate_update_manifest(payload, artifact)


@pytest.mark.parametrize(
    "path_factory",
    (
        lambda directory: directory / "missing.exe",
        lambda directory: directory / "candidate.txt",
    ),
)
def test_manifest_rejects_missing_or_non_executable_installer(tmp_path: Path, path_factory) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    payload = build_update_manifest(artifact)
    supplied = path_factory(tmp_path)
    if supplied.suffix == ".txt":
        supplied.write_bytes(b"not executable")

    with pytest.raises(ValueError):
        validate_update_manifest(payload, supplied)


def test_manifest_rejects_name_mismatch_even_when_contents_match(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    payload = build_update_manifest(artifact)
    renamed = _artifact(tmp_path, "other.exe")

    with pytest.raises(ValueError, match="does not match"):
        validate_update_manifest(payload, renamed)


def test_manifest_rejects_symlink_instead_of_a_regular_installer(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    payload = build_update_manifest(artifact)
    linked = tmp_path / "linked.exe"
    try:
        os.symlink(artifact, linked)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")

    with pytest.raises(ValueError):
        validate_update_manifest(payload, linked)


@pytest.mark.parametrize(
    "bad_name",
    ("", " ", "..\\rollback.exe", "nested/rollback.exe", "C:\\rollback.exe", "rollback.msi"),
)
def test_rollback_metadata_rejects_unsafe_filename(tmp_path: Path, bad_name: str) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    rollback = _artifact(tmp_path, "rollback.exe")
    payload = build_update_manifest(
        artifact, rollback_artifact_path=rollback, rollback_version="1.2.1"
    )
    rollback_metadata = payload["rollback"]
    assert isinstance(rollback_metadata, dict)
    rollback_metadata["artifact_filename"] = bad_name

    with pytest.raises(ValueError):
        validate_update_manifest(payload, artifact, rollback_artifact_path=rollback)


@pytest.mark.parametrize(
    "version",
    (
        "",
        " ",
        "v1.2.1",
        "1",
        "1.2",
        "1.2.1/evil",
        "1.2.1..",
        "01.2.3",
        "1.2.2-..",
        "9.9.9",
        __version__,
    ),
)
def test_rollback_metadata_rejects_garbage_version(tmp_path: Path, version: str) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    rollback = _artifact(tmp_path, "rollback.exe")

    with pytest.raises(ValueError, match="Rollback version"):
        build_update_manifest(artifact, rollback_artifact_path=rollback, rollback_version=version)


def test_rollback_metadata_accepts_strict_lower_prerelease_version(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    rollback = _artifact(tmp_path, "rollback.exe")

    payload = build_update_manifest(
        artifact, rollback_artifact_path=rollback, rollback_version="1.2.2-rc.1"
    )

    assert payload["rollback"]


def test_rollback_artifact_rejects_same_resolved_path(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")

    with pytest.raises(ValueError, match="distinct artifact"):
        build_update_manifest(artifact, rollback_artifact_path=artifact, rollback_version="1.2.1")


def test_rollback_artifact_rejects_same_hash_under_another_filename(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    rollback = tmp_path / "rollback.exe"
    rollback.write_bytes(artifact.read_bytes())

    with pytest.raises(ValueError, match="different hash"):
        build_update_manifest(artifact, rollback_artifact_path=rollback, rollback_version="1.2.1")


@pytest.mark.parametrize("field", ("size_bytes", "sha256"))
def test_rollback_artifact_must_match_its_actual_installer(tmp_path: Path, field: str) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    rollback = _artifact(tmp_path, "rollback.exe")
    payload = build_update_manifest(
        artifact, rollback_artifact_path=rollback, rollback_version="1.2.1"
    )
    rollback_metadata = payload["rollback"]
    assert isinstance(rollback_metadata, dict)
    rollback_metadata[field] = 999 if field == "size_bytes" else "A" * 64

    with pytest.raises(ValueError):
        validate_update_manifest(payload, artifact, rollback_artifact_path=rollback)


def test_manifest_rejects_boolean_size_bytes(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    payload = build_update_manifest(artifact)
    payload["size_bytes"] = True

    with pytest.raises(ValueError):
        validate_update_manifest(payload, artifact)


def test_manifest_writer_emits_only_public_metadata(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path, "candidate.exe")
    destination = tmp_path / "update_manifest.json"

    written = write_update_manifest(artifact, destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == written
    assert "candidate" in destination.read_text(encoding="utf-8")
    assert str(tmp_path) not in destination.read_text(encoding="utf-8")


def test_schema_two_manifest_binds_stable_entry_and_payload_hashes(tmp_path: Path) -> None:
    staging = _side_by_side_staging(tmp_path)
    artifact = _artifact(tmp_path, "candidate.exe")
    payload = build_update_manifest(artifact, staging_directory=staging)

    assert payload["schema_version"] == 2
    assert validate_update_manifest(payload, artifact, staging_directory=staging) == payload
    (staging / "Payload" / "StockToolPayload.exe").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Staging payload"):
        validate_update_manifest(payload, artifact, staging_directory=staging)


def test_staging_rejects_version_payload_that_differs_from_payload(tmp_path: Path) -> None:
    staging = _side_by_side_staging(tmp_path)
    (staging / "versions" / __version__ / "StockToolPayload.exe").write_bytes(b"different")

    with pytest.raises(ValueError, match="does not match"):
        validate_installer_staging(staging)


def test_installer_source_is_fixed_per_user_and_does_not_delete_user_data() -> None:
    installer = (PROJECT_ROOT / "installer" / "StockTool.iss").read_text(encoding="utf-8")

    assert '#define MyAppId "{{7ABF2B4C-4D79-4E74-B66C-9AF7E9E06568}"' in installer
    assert "AppId={#MyAppId}" in installer
    assert "PrivilegesRequired=lowest" in installer
    assert "DefaultDirName={localappdata}\\Programs\\StockTool" in installer
    assert 'Source: "{#MyStageDir}\\StockTool.exe"; DestDir: "{app}"' in installer
    assert 'DestDir: "{app}\\versions\\{#MyAppVersion}"' in installer
    assert "--activate-version {#MyAppVersion}" in installer
    assert "MyFailAfterPayloadCopy" in installer
    assert 'WorkingDir: "{app}"' in installer
    assert "#ifndef MyDisableShellIntegration" in installer
    assert '#if MyDisableShellIntegration == "0"' in installer
    assert 'Type: filesandordirs; Name: "{app}\\versions"' in installer
    assert 'Type: files; Name: "{app}\\current-version.json"' in installer
    assert "%LOCALAPPDATA%\\StockTool" not in installer


def test_version_resource_installer_and_manifest_use_one_canonical_version() -> None:
    spec = (PROJECT_ROOT / "StockTool.spec").read_text(encoding="utf-8")
    build = (PROJECT_ROOT / "build_exe.bat").read_text(encoding="utf-8")
    installer_build = (PROJECT_ROOT / "src/stock_tool/installer_build.py").read_text(
        encoding="utf-8"
    )
    resource = version_resource_text()

    assert f"StringStruct('FileVersion', '{__version__}')" in resource
    assert f"StringStruct('ProductVersion', '{__version__}')" in resource
    assert "write_version_resource" in spec
    assert "stocktool-version-info.txt" in spec
    assert "StockTool.spec" in build
    assert "--name StockTool" not in build
    assert 'f"/DMyAppVersion={__version__}"' in installer_build
    assert windows_version_tuple() == "1, 4, 1, 0"


def test_manifest_template_declares_all_generated_fields() -> None:
    template = json.loads((PROJECT_ROOT / "installer" / "update_manifest.json").read_text("utf-8"))

    assert template["schema_version"] == 2
    assert set(template["required_fields"]) >= {
        "version",
        "artifact_filename",
        "size_bytes",
        "sha256",
        "created_at_utc",
        "user_data_compatibility",
        "rollback",
        "rollback.size_bytes",
        "rollback.sha256",
        "staging.stable_entry.sha256",
        "staging.payload.sha256",
    }


def test_source_archive_build_inputs_include_installer_foundation() -> None:
    inputs = required_build_inputs(PROJECT_ROOT)

    assert "build_installer.bat" in inputs
    assert "installer/StockTool.iss" in inputs
    assert "installer/update_manifest.json" in inputs
    assert "installer/version_info.txt" in inputs
    assert "scripts/verify_installer_lifecycle.ps1" in inputs
    assert "src/stock_tool/version_resource.py" in inputs


def test_lifecycle_harness_is_explicitly_opt_in_and_preserves_replay_evidence() -> None:
    harness = (PROJECT_ROOT / "scripts" / "verify_installer_lifecycle.ps1").read_text(
        encoding="utf-8"
    )

    assert "[switch]$AllowHostLifecycleTest" in harness
    assert "Refusing host lifecycle execution without -AllowHostLifecycleTest" in harness
    assert "lifecycle-result.json" in harness
    assert '"/LOG=$LogPath"' in harness
    assert "Fixed AppId already has an uninstall entry" in harness
    assert "Default StockTool install directory exists" in harness
    assert "post-copy-pre-switch-interruption" in harness
    assert "MyFailAfterPayloadCopy=1" in harness
    assert "expected_interruption_observed" in harness
    assert "STOCK_TOOL_USER_DATA_DIR" in harness
    assert "user_data_sentinel_exists" in harness
    assert "CandidateRootName" in harness


@pytest.mark.parametrize(
    "relative",
    (
        ".env",
        ".env.local",
        ".env.production",
        "data/portfolio.csv",
        "data/stock_tool.sqlite",
        "logs/install.log",
        "reports/private-report.txt",
        "config/private.toml",
        "documents/research.pdf",
        "settings.toml",
        "portfolio.xlsx",
        "watchlist.json",
        "api_token.pem",
        "signing_private.key",
        "credentials.csv",
        "unexpected.txt",
    ),
)
def test_installer_staging_rejects_private_or_runtime_content(
    tmp_path: Path, relative: str
) -> None:
    staging = tmp_path / "StockTool"
    private_item = staging / relative
    private_item.parent.mkdir(parents=True, exist_ok=True)
    private_item.write_text("private", encoding="utf-8")

    with pytest.raises(ValueError):
        validate_installer_staging(staging)


def test_installer_staging_allows_env_example(tmp_path: Path) -> None:
    staging = tmp_path / "StockTool"
    (staging / "Payload").mkdir(parents=True)
    (staging / "Payload" / ".env.example").write_text("API_KEY=", encoding="utf-8")

    validate_installer_staging(staging)


def test_installer_staging_allows_only_exact_public_third_party_private_names(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "StockTool"
    allowed = staging / "Payload/_internal/pyarrow/include/arrow/vendored/datetime/tz_private.h"
    allowed.parent.mkdir(parents=True)
    allowed.write_text("public header", encoding="utf-8")
    public_ca_bundle = staging / "Payload/_internal/certifi/cacert.pem"
    public_ca_bundle.parent.mkdir(parents=True)
    public_ca_bundle.write_text("public CA bundle", encoding="utf-8")
    windows_runtime = staging / "Payload/_internal/api-ms-win-crt-private-l1-1-0.dll"
    windows_runtime.write_bytes(b"public Windows runtime")

    validate_installer_staging(staging)

    denied = allowed.with_name("other_private.h")
    denied.write_text("not allowlisted", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_installer_staging(staging)


def test_installer_staging_rejects_non_allowlisted_certificate_container(tmp_path: Path) -> None:
    staging = tmp_path / "StockTool"
    unexpected_certificate = staging / "_internal/other/public.pem"
    unexpected_certificate.parent.mkdir(parents=True)
    unexpected_certificate.write_text("not allowlisted", encoding="utf-8")

    with pytest.raises(ValueError):
        validate_installer_staging(staging)


def test_installer_staging_rejects_output_directory_nested_inside_staging(tmp_path: Path) -> None:
    staging = tmp_path / "StockTool"
    staging.mkdir()

    with pytest.raises(ValueError, match="output directory"):
        validate_installer_staging(staging, output_directory=staging / "installer-output")


def test_installer_staging_rejects_output_directory_containing_staging(tmp_path: Path) -> None:
    staging = tmp_path / "parent" / "StockTool"
    staging.mkdir(parents=True)

    with pytest.raises(ValueError, match="output directory"):
        validate_installer_staging(staging, output_directory=tmp_path / "parent")


def test_installer_staging_rejects_symlink_and_path_escape(tmp_path: Path) -> None:
    staging = tmp_path / "StockTool"
    staging.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = staging / "escape.txt"
    try:
        os.symlink(outside, link)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")

    with pytest.raises(ValueError):
        validate_installer_staging(staging)


def test_signing_prerequisites_are_read_only_and_never_sign(monkeypatch) -> None:
    monkeypatch.setattr("stock_tool.installer_build.shutil.which", lambda _: None)
    monkeypatch.delenv("STOCK_TOOL_SIGNING_CERTIFICATE", raising=False)

    result = detect_signing_prerequisites()

    assert result.signtool_path is None
    assert not result.certificate_configured
    assert not result.ready


def test_unsigned_installer_build_uses_verified_staging_and_writes_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    staging = _side_by_side_staging(tmp_path)
    compiler = tmp_path / "ISCC.exe"
    compiler.write_bytes(b"fake compiler")
    output = tmp_path / "artifacts"
    observed: list[str] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == PROJECT_ROOT
        assert check is True
        observed.extend(command)
        output.mkdir(parents=True, exist_ok=True)
        (output / f"StockTool-Setup-{__version__}-internal-test.exe").write_bytes(b"fake installer")

    monkeypatch.setattr("stock_tool.installer_build.subprocess.run", fake_run)

    result = build_unsigned_internal_test_installer(
        project_root=PROJECT_ROOT,
        staging_directory=staging,
        output_directory=output,
        compiler=compiler,
    )

    assert f"/DMyAppVersion={__version__}" in observed
    assert any(item.startswith("/DMyStageDir=") for item in observed)
    assert "/DMyDisableShellIntegration=0" in observed
    assert result.installer_path.is_file()
    assert validate_update_manifest(
        json.loads(result.manifest_path.read_text("utf-8")),
        result.installer_path,
        staging_directory=staging,
    )


def test_installer_build_can_bind_a_genuine_rollback_and_disable_shell_integration(
    tmp_path: Path, monkeypatch
) -> None:
    staging = _side_by_side_staging(tmp_path)
    rollback = _artifact(tmp_path, "StockTool-Setup-1.2.1-internal-test.exe")
    compiler = tmp_path / "ISCC.exe"
    compiler.write_bytes(b"fake compiler")
    output = tmp_path / "artifacts"
    observed: list[str] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        observed.extend(command)
        output.mkdir(parents=True, exist_ok=True)
        (output / f"StockTool-Setup-{__version__}-internal-test.exe").write_bytes(
            b"fake current installer"
        )

    monkeypatch.setattr("stock_tool.installer_build.subprocess.run", fake_run)

    result = build_unsigned_internal_test_installer(
        project_root=PROJECT_ROOT,
        staging_directory=staging,
        output_directory=output,
        compiler=compiler,
        rollback_artifact_path=rollback,
        rollback_version="1.2.1",
        disable_shell_integration=True,
    )

    assert "/DMyDisableShellIntegration=1" in observed
    payload = json.loads(result.manifest_path.read_text("utf-8"))
    assert payload["rollback"]["version"] == "1.2.1"
    assert validate_update_manifest(
        payload,
        result.installer_path,
        rollback_artifact_path=rollback,
        staging_directory=staging,
    )
