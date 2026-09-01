from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from stock_tool.release_assets import (
    ReleaseAssetError,
    copy_release_assets,
    validate_release_assets,
    validate_release_distribution,
    validate_payload_release_assets,
    validate_release_source_assets,
)


def _create_release_sources(root: Path) -> None:
    for filename in ("README.md", ".env.example", "使用教學_簡易版.txt", "啟動股票工具.bat"):
        (root / filename).write_text("fixture", encoding="utf-8")
    sample = root / "data" / "sample"
    sample.mkdir(parents=True)
    (sample / "sample_tw_prices.csv").write_text("date,symbol,close\n2024-01-02,2330,595\n")
    (sample / "sample_fundamentals.csv").write_text("symbol,revenue\n2330,1\n")


def test_release_asset_allowlist_copies_required_user_assets_and_rejects_missing_ones(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "release" / "StockTool"
    source.mkdir(parents=True)
    _create_release_sources(source)
    destination.mkdir(parents=True)
    (destination / "StockTool.exe").write_bytes(b"fixture-exe")

    validate_release_source_assets(source)
    copy_release_assets(source, destination)
    validate_release_assets(destination)

    assert (destination / "README.md").is_file()
    assert (destination / ".env.example").is_file()
    assert (destination / "使用教學_簡易版.txt").is_file()
    assert (destination / "啟動股票工具.bat").is_file()
    assert (destination / "data" / "sample" / "sample_tw_prices.csv").is_file()
    assert (destination / "data" / "sample" / "sample_fundamentals.csv").is_file()

    (destination / "README.md").unlink()
    with pytest.raises(ReleaseAssetError, match="README.md"):
        validate_release_assets(destination)


def test_release_asset_source_validation_fails_before_build_when_a_required_asset_is_missing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _create_release_sources(source)
    (source / ".env.example").unlink()

    with pytest.raises(ReleaseAssetError, match=".env.example"):
        validate_release_source_assets(source)


def test_versioned_payload_assets_require_payload_executable_and_keep_only_public_assets(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    payload = tmp_path / "stage" / "Payload"
    source.mkdir(parents=True)
    _create_release_sources(source)
    payload.mkdir(parents=True)
    (payload / "StockToolPayload.exe").write_bytes(b"payload")

    copy_release_assets(source, payload)
    validate_payload_release_assets(payload)

    (payload / "StockToolPayload.exe").unlink()
    with pytest.raises(ReleaseAssetError, match="StockToolPayload.exe"):
        validate_payload_release_assets(payload)


def test_release_distribution_accepts_and_binds_the_stable_entry_layout(tmp_path: Path) -> None:
    source = tmp_path / "source"
    stage = tmp_path / "stage" / "StockTool"
    payload = stage / "Payload"
    source.mkdir(parents=True)
    payload.mkdir(parents=True)
    _create_release_sources(source)
    (stage / "StockTool.exe").write_bytes(b"stable")
    (payload / "StockToolPayload.exe").write_bytes(b"payload")
    copy_release_assets(source, payload)
    shutil.copytree(payload, stage / "versions" / "1.4.1")
    (stage / "current-version.json").write_text(
        json.dumps(
            {
                "version": "1.4.1",
                "payload": "versions/1.4.1/StockToolPayload.exe",
            }
        ),
        encoding="utf-8",
    )

    validate_release_distribution(stage, run_version=lambda _command: "1.4.1")

    (stage / "versions" / "1.4.1" / "README.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match Payload"):
        validate_release_distribution(stage, run_version=lambda _command: "1.4.1")


def test_release_distribution_accepts_the_legacy_onedir_layout(tmp_path: Path) -> None:
    source = tmp_path / "source"
    release = tmp_path / "release" / "StockTool"
    source.mkdir(parents=True)
    release.mkdir(parents=True)
    _create_release_sources(source)
    (release / "StockTool.exe").write_bytes(b"legacy")
    copy_release_assets(source, release)

    validate_release_distribution(release)


def test_release_distribution_rejects_an_incomplete_stable_entry_layout(tmp_path: Path) -> None:
    release = tmp_path / "StockTool"
    (release / "Payload").mkdir(parents=True)

    with pytest.raises(ReleaseAssetError, match="StockTool.exe.*current-version.json"):
        validate_release_distribution(release)

    shutil.rmtree(release / "Payload")
    (release / "StockTool.exe").write_bytes(b"stable")
    (release / "versions").mkdir()
    (release / "current-version.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ReleaseAssetError, match="Payload"):
        validate_release_distribution(release)


def test_build_and_promotion_scripts_call_the_release_asset_allowlist() -> None:
    project_root = Path(__file__).parents[1]
    build_script = (project_root / "build_exe.bat").read_text(encoding="utf-8")
    promotion_script = (project_root / "publish_release.bat").read_text(encoding="utf-8")

    assert "stock_tool.release_assets --validate-source" in build_script
    assert "stock_tool.release_assets --copy-payload-and-validate" in build_script
    assert "validate_release_distribution" in promotion_script
