"""Sprint 18.1 checks for installer/runtime user-data separation."""

from __future__ import annotations

from pathlib import Path

from stock_tool.runtime_paths import RuntimePaths

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_per_user_installer_path_is_distinct_from_runtime_user_data(
    monkeypatch, tmp_path: Path
) -> None:
    override = tmp_path / "isolated-user-data"
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(override))
    paths = RuntimePaths.from_environment()
    installer = (PROJECT_ROOT / "installer" / "StockTool.iss").read_text(encoding="utf-8")

    assert paths.root == override.resolve()
    assert "DefaultDirName={localappdata}\\Programs\\StockTool" in installer
    assert str(paths.root) not in installer
    assert "{localappdata}\\StockTool" not in installer


def test_installer_build_script_targets_only_sprint18_2_2_staging_and_artifacts() -> None:
    script = (PROJECT_ROOT / "build_installer.bat").read_text(encoding="utf-8").lower()

    assert "release\\staging-sprint18.2.2\\stocktool" in script
    assert "artifacts\\sprint18.2.2\\installer" in script
    assert "publish_release.bat" not in script
    assert "release\\stocktool" not in script
