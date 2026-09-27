from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pytest import CaptureFixture

from stock_tool.cli import main


def test_cli_version_uses_the_package_canonical_version(capsys: CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "1.4.3"


def test_python_module_cli_help_runs() -> None:
    env = os.environ.copy()
    src_path = str(Path.cwd() / "src")
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "-m", "stock_tool", "--help"],
        capture_output=True,
        env=env,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0
    assert "import-data" in result.stdout
    assert "backtest" in result.stdout


def test_cli_import_data_writes_sqlite_database(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    database_path = tmp_path / "prices.sqlite"

    exit_code = main(
        [
            "import-data",
            "--file",
            "data/sample/sample_tw_prices.csv",
            "--database",
            str(database_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert database_path.exists()
    assert "saved_rows=8" in captured.out


def test_cli_analyze_sample_symbol(capsys: CaptureFixture[str]) -> None:
    exit_code = main(["analyze", "--symbol", "2330"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "symbol=2330" in captured.out
    assert "close=" in captured.out


def test_cli_backtest_uses_next_bar_engine(capsys: CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "backtest",
            "--symbol",
            "2330",
            "--strategy",
            "macd_trend",
            "--initial-cash",
            "1000000",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "strategy=macd_trend" in captured.out
    assert "benchmark_total_return=" in captured.out
