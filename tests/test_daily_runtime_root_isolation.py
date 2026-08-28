from __future__ import annotations

from pathlib import Path

from stock_tool.runtime_paths import RuntimePaths


def test_daily_scheduler_paths_are_isolated_from_process_cwd(tmp_path: Path, monkeypatch) -> None:
    """Headless evidence must never fall back to repository-root projections."""

    workspace = Path(__file__).resolve().parents[1]
    isolated = (tmp_path / "runtime").resolve()
    paths = RuntimePaths(isolated).ensure_directories()
    monkeypatch.chdir(workspace)

    assert paths.daily_schedule_latest_run_file.is_relative_to(isolated)
    assert paths.daily_schedule_runs_dir.is_relative_to(isolated)
    assert paths.daily_research_run_manifests_dir.is_relative_to(isolated)
    assert not (workspace / "history.json").exists()
    assert not (workspace / "latest-scheduled-run.json").exists()
    assert not (workspace / "latest.json").exists()
