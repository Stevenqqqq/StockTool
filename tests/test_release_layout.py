"""Release-boundary and version consistency tests for the v1.2 onedir workflow."""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

from stock_tool import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_package_init_is_the_canonical_v1_2_version_source() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert __version__ == "1.4.0"
    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "stock_tool.__version__"}
    assert version("stock-analysis-tool") == __version__


def test_build_script_stages_new_release_without_deleting_official_release() -> None:
    build = (PROJECT_ROOT / "build_exe.bat").read_text(encoding="utf-8").lower()
    clean = (PROJECT_ROOT / "clean_build.bat").read_text(encoding="utf-8").lower()

    assert 'set "staging_dir=release\\staging\\stocktool"' in build
    assert '--distpath "%staging_parent%\\payload-build"' in build
    assert "stablelauncher.spec" in build
    assert "stocktoolpayload" in build
    assert 'rmdir /s /q "%release_dir%"' not in build
    assert 'rmdir /s /q "release\\stocktool"' not in clean
    assert "release\\staging" in clean
    assert "StockTool.spec" in (PROJECT_ROOT / "build_exe.bat").read_text(encoding="utf-8")


def test_release_scripts_only_package_the_allowlisted_streamlit_config() -> None:
    build = (PROJECT_ROOT / "build_exe.bat").read_text(encoding="utf-8")
    spec = (PROJECT_ROOT / "StockTool.spec").read_text(encoding="utf-8")

    assert "StockTool.spec" in build
    assert "('.streamlit\\\\config.toml', '.streamlit')" in spec
    assert "('.streamlit\\\\', '.streamlit')" not in spec
    assert "publish_release.bat" in (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")


def test_promotion_script_uses_unique_rollback_and_non_destructive_hold() -> None:
    promotion = (PROJECT_ROOT / "publish_release.bat").read_text(encoding="utf-8").lower()

    assert (
        'set "rollback_dir=release\\rollback\\stocktool-pre-sprint12-release-%stamp%"' in promotion
    )
    assert 'if exist "%rollback_dir%" (' in promotion
    assert 'robocopy "%release_dir%" "%rollback_dir%" /e' in promotion
    assert (
        'set "promotion_hold=release\\promotion-hold\\stocktool-pre-sprint12-release-%stamp%"'
        in promotion
    )
    assert "goto :restore_previous_release" in promotion
    assert "call :run_post_promotion_smoke" in promotion
    assert "stock_tool_user_data_dir" in promotion
    assert 'set "previous_dir=release\\previous\\stocktool"' not in promotion


def test_dashboard_visible_version_uses_the_canonical_package_version() -> None:
    shell = (PROJECT_ROOT / "src" / "stock_tool" / "dashboard" / "shell.py").read_text(
        encoding="utf-8"
    )

    assert "from stock_tool import __version__" in shell
    assert 'caption(f"StockTool v{__version__}")' in shell
