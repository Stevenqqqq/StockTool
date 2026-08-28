from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from stock_tool.runtime_paths import (
    RuntimePaths,
    migrate_legacy_user_data,
    prepare_release_user_data_migration,
)


def _write_portfolio(path, *, symbol: str = "2330") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "symbol": symbol,
                "quantity": 10,
                "average_cost": 500,
                "market": "TWSE",
                "currency": "TWD",
                "note": "fixture",
            }
        ]
    ).to_csv(path, index=False, encoding="utf-8")


def test_runtime_paths_use_explicit_environment_override(monkeypatch, tmp_path) -> None:
    expected_root = tmp_path / "user-data"
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(expected_root))

    paths = RuntimePaths.from_environment()
    paths.ensure_directories()

    assert paths.root == expected_root
    assert paths.portfolio_file == expected_root / "data" / "portfolio.csv"
    assert paths.watchlist_file == expected_root / "data" / "watchlist.csv"
    assert paths.cache_dir.is_dir()
    assert paths.reports_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.backups_dir.is_dir()


def test_dashboard_runtime_paths_follow_environment_after_module_import(
    monkeypatch, tmp_path
) -> None:
    import stock_tool.dashboard.app as dashboard_app

    expected_root = tmp_path / "isolated-runtime"
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(expected_root))

    paths = dashboard_app._runtime_paths()

    assert paths.root == expected_root.resolve()


def test_legacy_migration_copies_and_validates_portfolio_without_deleting_source(tmp_path) -> None:
    legacy_root = tmp_path / "legacy-release"
    legacy_file = legacy_root / "data" / "portfolio.csv"
    _write_portfolio(legacy_file)
    paths = RuntimePaths(root=tmp_path / "runtime")

    result = migrate_legacy_user_data(paths, legacy_root=legacy_root)

    item = result.item("portfolio")
    assert item is not None
    assert item.status == "migrated"
    assert item.source_sha256 == item.target_sha256
    assert item.source_rows == item.target_rows == 1
    assert legacy_file.exists()
    assert paths.portfolio_file.exists()
    assert any(paths.backups_dir.glob("legacy-migration-*/*portfolio.csv"))


def test_legacy_migration_is_repeat_safe_and_does_not_overwrite_existing_target(tmp_path) -> None:
    legacy_root = tmp_path / "legacy-release"
    _write_portfolio(legacy_root / "data" / "portfolio.csv", symbol="2330")
    paths = RuntimePaths(root=tmp_path / "runtime")
    paths.ensure_directories()
    _write_portfolio(paths.portfolio_file, symbol="AAPL")
    before_hash = hashlib.sha256(paths.portfolio_file.read_bytes()).hexdigest()

    result = migrate_legacy_user_data(paths, legacy_root=legacy_root)

    item = result.item("portfolio")
    assert item is not None
    assert item.status == "skipped_existing"
    assert "not overwritten" in " ".join(result.warnings).lower()
    assert hashlib.sha256(paths.portfolio_file.read_bytes()).hexdigest() == before_hash


def test_malformed_legacy_portfolio_is_reported_without_copying(tmp_path) -> None:
    legacy_root = tmp_path / "legacy-release"
    malformed = legacy_root / "data" / "portfolio.csv"
    malformed.parent.mkdir(parents=True)
    malformed.write_text("symbol,quantity\n2330,not-a-number\n", encoding="utf-8")
    paths = RuntimePaths(root=tmp_path / "runtime")

    result = migrate_legacy_user_data(paths, legacy_root=legacy_root)

    item = result.item("portfolio")
    assert item is not None
    assert item.status == "skipped_invalid"
    assert not paths.portfolio_file.exists()
    assert "required" in " ".join(result.warnings).lower()


def test_build_script_keeps_runtime_user_data_outside_release_assets() -> None:
    build_script = (Path(__file__).resolve().parents[1] / "build_exe.bat").read_text(
        encoding="utf-8"
    )

    assert "data\\portfolio.csv" not in build_script
    assert "data\\watchlist.csv" not in build_script
    assert "data\\cache" not in build_script
    assert "Runtime user data is stored outside the release folder" in build_script


def test_release_migration_writes_manifest_and_preserves_existing_user_portfolio(tmp_path) -> None:
    legacy_root = tmp_path / "legacy-release"
    _write_portfolio(legacy_root / "data" / "portfolio.csv", symbol="LEGACY")
    paths = RuntimePaths(root=tmp_path / "runtime")
    paths.ensure_directories()
    _write_portfolio(paths.portfolio_file, symbol="CURRENT")
    before_hash = hashlib.sha256(paths.portfolio_file.read_bytes()).hexdigest()

    result = prepare_release_user_data_migration(legacy_root=legacy_root, paths=paths)

    assert result.manifest_path is not None
    assert result.manifest_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_root"] == str(legacy_root)
    portfolio_item = result.item("portfolio")
    assert portfolio_item is not None
    assert portfolio_item.status == "skipped_existing"
    assert hashlib.sha256(paths.portfolio_file.read_bytes()).hexdigest() == before_hash
    assert legacy_root.joinpath("data", "portfolio.csv").exists()


def test_release_migration_blocks_destructive_cleanup_when_legacy_data_is_invalid(tmp_path) -> None:
    legacy_root = tmp_path / "legacy-release"
    legacy_file = legacy_root / "data" / "portfolio.csv"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text("symbol,quantity\nBROKEN,nope\n", encoding="utf-8")
    paths = RuntimePaths(root=tmp_path / "runtime")

    with pytest.raises(RuntimeError, match="cleanup is blocked"):
        prepare_release_user_data_migration(legacy_root=legacy_root, paths=paths)

    assert legacy_file.exists()
    assert not paths.portfolio_file.exists()


def test_release_promotion_migrates_legacy_user_data_without_build_cleanup() -> None:
    project_root = Path(__file__).resolve().parents[1]
    build_script = (project_root / "build_exe.bat").read_text(encoding="utf-8")
    publish_script = (project_root / "publish_release.bat").read_text(encoding="utf-8")

    assert 'rmdir /s /q "%RELEASE_DIR%"' not in build_script
    assert "prepare_release_user_data_migration" in publish_script
    rollback_verification = "Verifying rollback backup assets and executable hash..."
    release_move = 'move "%RELEASE_DIR%" "%PROMOTION_HOLD%"'
    migration_index = publish_script.index("prepare_release_user_data_migration")
    assert (
        publish_script.index(rollback_verification)
        < migration_index
        < publish_script.index(release_move)
    )
    migration_block = publish_script[migration_index : publish_script.index(release_move)]
    assert "if errorlevel 1 (" in migration_block
    assert "exit /b 1" in migration_block
    assert "%PREVIOUS_DIR%" not in publish_script
