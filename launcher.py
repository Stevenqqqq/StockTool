"""Windows launcher for the Streamlit stock analysis dashboard."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

from stock_tool.runtime_paths import RuntimePaths, default_runtime_paths, migrate_legacy_user_data

# Daily Research is a headless-only path. Keep compatibility names for tests
# and injected runners, but defer the heavy scheduler/inbox imports until the
# explicit ``--daily-research-run`` command is selected.
HeadlessDailyResearchRunner: Any = None
DailyResearchRunner: Any = None
DailyResearchNotificationService: Any = None

STREAMLIT_CHILD_FLAG = "--stocktool-streamlit-cli"
VERSION_FLAG = "--version"
DEFAULT_PORTS = (8501, 8502)
# Keep probing, binding, health checks, and browser navigation on the same
# IPv4 loopback address.  ``localhost`` can resolve to IPv6 on Windows while
# Streamlit is listening only on IPv4, which makes readiness nondeterministic.
SERVER_HOST = "127.0.0.1"
HEALTH_PATH = "/_stcore/health"


def main() -> int:
    """Start the bundled Streamlit dashboard and open the local browser."""

    _write_startup_timing("payload_python_started")

    if len(sys.argv) > 1 and sys.argv[1] == "--daily-research-run":
        return _run_daily_research_cli(sys.argv[2:])
    if len(sys.argv) == 2 and sys.argv[1] == VERSION_FLAG:
        from stock_tool import __version__

        print(__version__)
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == STREAMLIT_CHILD_FLAG:
        return _run_streamlit_cli(sys.argv[2:])

    base_dir = _base_dir()
    runtime_paths = default_runtime_paths()
    migration = migrate_legacy_user_data(runtime_paths, legacy_root=base_dir)
    logs_dir = runtime_paths.logs_dir

    app_path = _streamlit_app_path()
    if not app_path.exists():
        message = f"錯誤：找不到 Streamlit 應用程式：{app_path}"
        error_log = _write_launcher_error(logs_dir, message)
        print(message, file=sys.stderr)
        print(f"錯誤紀錄：{error_log}", file=sys.stderr)
        return 1

    port = _available_port(DEFAULT_PORTS)
    if port is None:
        ports = ", ".join(str(item) for item in DEFAULT_PORTS)
        message = f"錯誤：以下連接埠無法使用：{ports}。" "請關閉占用中的服務後重新啟動 StockTool。"
        error_log = _write_launcher_error(logs_dir, message)
        print(message, file=sys.stderr)
        print(f"錯誤紀錄：{error_log}", file=sys.stderr)
        return 1
    if port != DEFAULT_PORTS[0]:
        print(f"警告：連接埠 {DEFAULT_PORTS[0]} 已被占用，改用連接埠 {port}。")

    command = _streamlit_command(app_path=app_path, port=port)
    stdout_log, stderr_log = _log_paths(logs_dir)
    print("正在啟動股票分析工具 Streamlit 介面...")
    print(f"應用程式：{app_path}")
    print(f"網址：http://{SERVER_HOST}:{port}")
    print(f"執行紀錄：{stdout_log}")
    print(f"錯誤紀錄：{stderr_log}")
    print("若要停止服務，請在此視窗按 Ctrl+C。")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    env["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    env["STOCK_TOOL_USER_DATA_DIR"] = str(runtime_paths.root)
    for warning in migration.warnings:
        print(f"User data migration warning: {warning}", file=sys.stderr)

    stdout_handle = None
    stderr_handle = None
    try:
        stdout_handle = stdout_log.open("a", encoding="utf-8")
        stderr_handle = stderr_log.open("a", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=base_dir,
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
        _write_startup_timing("streamlit_process_spawned")
    except OSError as exc:
        if stdout_handle is not None:
            stdout_handle.close()
        if stderr_handle is not None:
            stderr_handle.close()
        message = f"錯誤：無法啟動 Streamlit：{exc}"
        error_log = _write_launcher_error(logs_dir, message)
        print(message, file=sys.stderr)
        print(f"錯誤紀錄：{error_log}", file=sys.stderr)
        return 1

    url = f"http://{SERVER_HOST}:{port}"
    if _wait_for_server(_health_url(port), process):
        _write_startup_timing("payload_health_observed")
        if _browser_launch_disabled():
            print("Browser launch disabled by STOCK_TOOL_NO_BROWSER for an isolated test run.")
        elif not _open_browser(url):
            print(f"警告：瀏覽器沒有自動開啟，請手動開啟：{url}")
    else:
        message = f"錯誤：Streamlit 未能在指定時間內啟動：{url}"
        error_log = _write_launcher_error(logs_dir, message)
        print(message, file=sys.stderr)
        print(f"錯誤紀錄：{error_log}", file=sys.stderr)
        if process.poll() is not None:
            print(f"Streamlit 程序已結束，代碼：{process.returncode}。", file=sys.stderr)
            return int(process.returncode or 1)

    try:
        return int(process.wait())
    except KeyboardInterrupt:
        print("正在停止股票分析工具...")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        return 0
    finally:
        stdout_handle.close()
        stderr_handle.close()


def _run_daily_research_cli(arguments: list[str]) -> int:
    """Run one headless daily brief without starting Streamlit or a browser."""

    global DailyResearchNotificationService, HeadlessDailyResearchRunner, DailyResearchRunner
    if DailyResearchNotificationService is None:
        from stock_tool.application.daily_research_inbox import (
            DailyResearchNotificationService as _DailyResearchNotificationService,
        )

        DailyResearchNotificationService = _DailyResearchNotificationService
    injected_legacy_runner = HeadlessDailyResearchRunner is not None
    if not injected_legacy_runner and DailyResearchRunner is None:
        from stock_tool.application.daily_research_runner import (
            DailyResearchRunner as _DailyResearchRunner,
        )

        DailyResearchRunner = _DailyResearchRunner

    trigger: Literal["scheduled", "manual"] = "manual"
    dry_run = False
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value == "--dry-run":
            dry_run = True
        elif value == "--trigger" and index + 1 < len(arguments):
            trigger = cast(Literal["scheduled", "manual"], arguments[index + 1])
            index += 1
        else:
            print("StockTool daily research arguments are invalid.", file=sys.stderr)
            return 40
        index += 1
    if trigger not in {"scheduled", "manual"}:
        print("StockTool daily research trigger is invalid.", file=sys.stderr)
        return 40
    try:
        paths = RuntimePaths.from_environment().ensure_directories()
        from stock_tool.application.prediction_lab import (
            BenchmarkRefreshService,
            build_runtime_cached_outcome_provider,
        )

        outcome_provider = build_runtime_cached_outcome_provider(
            paths.processed_dir / "stock_data.sqlite"
        )
        # The packaged/headless entry point must use the same explicit
        # benchmark refresh boundary as the dashboard and scheduler.  The
        # callback is only invoked by the runner after the user/scheduler has
        # explicitly started a run; constructing it here performs no I/O.
        benchmark_service = BenchmarkRefreshService(
            paths.processed_dir / "stock_data.sqlite",
            cache_dir=paths.cache_dir,
            log_dir=paths.logs_dir,
        )
        notifications = DailyResearchNotificationService(paths)
        evidence_mode = os.environ.get("STOCK_TOOL_EVIDENCE_MODE", "").strip()
        temp_root = Path(os.environ.get("TEMP", "")).resolve()
        isolated_root = paths.root.resolve(strict=False)
        evidence_notifier = None
        if (
            evidence_mode == "sprint32.1.1"
            and temp_root.is_dir()
            and temp_root in isolated_root.parents
        ):
            # This seam is deliberately limited to an explicit evidence mode and
            # a temporary isolated runtime.  Production CLI runs retain the
            # opt-in notification setting and Windows capability contract.
            def _evidence_notifier(*_args: object, **_kwargs: object) -> object:
                return SimpleNamespace(status="sent", reason=None)

            evidence_notifier = _evidence_notifier
        if injected_legacy_runner:
            runner = HeadlessDailyResearchRunner(paths)
            if hasattr(runner, "on_success"):
                runner.on_success = evidence_notifier or notifications.notify_success
            # Keep the legacy launcher branch on the same production outcome
            # provider as the shared application runner.  The assignment is
            # deliberately explicit so injected test doubles remain compatible
            # while the packaged seventh-stage evaluator receives real evidence.
            if hasattr(runner, "prediction_outcome_provider"):
                runner.prediction_outcome_provider = outcome_provider
            if hasattr(runner, "benchmark_refresh_callback"):
                runner.benchmark_refresh_callback = benchmark_service.refresh
        else:
            runner = DailyResearchRunner(
                paths,
                on_success=evidence_notifier or notifications.notify_success,
                benchmark_refresh_callback=benchmark_service.refresh,
                prediction_outcome_provider=outcome_provider,
            )
        outcome = runner.run(trigger=trigger, dry_run=dry_run)
    except Exception:
        print("StockTool daily research run failed safely.", file=sys.stderr)
        return 40
    print(
        f"daily-research status={outcome.status} exit_code={outcome.exit_code} "
        f"run_id={outcome.record.run_id}"
    )
    return outcome.exit_code


def _run_streamlit_cli(args: list[str]) -> int:
    """Run Streamlit CLI inside the frozen executable child process."""

    if len(args) != 2:
        print("錯誤：內部 Streamlit 啟動參數無效。", file=sys.stderr)
        return 1

    app_path = Path(args[0])
    port = args[1]
    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.address",
        SERVER_HOST,
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
        "--global.developmentMode",
        "false",
    ]

    try:
        from streamlit.web import cli as streamlit_cli
    except ImportError as exc:
        print(f"錯誤：打包內的 Streamlit 無法使用：{exc}", file=sys.stderr)
        return 1

    try:
        streamlit_cli.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _streamlit_command(*, app_path: Path, port: int) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, STREAMLIT_CHILD_FLAG, str(app_path), str(port)]
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.address",
        SERVER_HOST,
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
        "--global.developmentMode",
        "false",
    ]


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return _base_dir()


def _streamlit_app_path() -> Path:
    if getattr(sys, "frozen", False):
        return _resource_dir() / "stock_tool" / "dashboard" / "app.py"
    return _base_dir() / "src" / "stock_tool" / "dashboard" / "app.py"


def _available_port(ports: tuple[int, ...]) -> int | None:
    for port in ports:
        if _is_port_available(port):
            return port
    return None


def _log_paths(logs_dir: Path) -> tuple[Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return (
        logs_dir / f"streamlit_{timestamp}.log",
        logs_dir / f"streamlit_{timestamp}_error.log",
    )


def _write_launcher_error(logs_dir: Path, message: str) -> Path:
    """Write a concise launcher failure record outside the release directory."""

    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    error_log = logs_dir / f"launcher_{timestamp}_error.log"
    error_log.write_text(f"{message}\n", encoding="utf-8")
    return error_log


def _write_startup_timing(stage: str) -> None:
    """Append an opt-in, isolated cold-start timing marker."""

    target = os.environ.get("STOCK_TOOL_STARTUP_TIMING_FILE", "").strip()
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"stage": stage, "timestamp_utc": datetime.now(timezone.utc).isoformat()}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.bind((SERVER_HOST, port))
        except OSError:
            return False
        return True


def _wait_for_server(url: str, process: subprocess.Popen[bytes], timeout_seconds: int = 45) -> bool:
    """Wait for the private health endpoint, never merely the Streamlit homepage."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if _health_check(url):
            return True
        time.sleep(1)
    return False


def _health_url(port: int) -> str:
    """Return the fixed readiness endpoint for a local Streamlit instance."""

    return f"http://{SERVER_HOST}:{port}{HEALTH_PATH}"


def _health_check(url: str) -> bool:
    """Return true only for the local health endpoint's exact 200/``ok`` response.

    A dedicated opener with an empty proxy map prevents a machine-level HTTP proxy
    from turning the local readiness probe into a proxy request.
    """

    request = urllib.request.Request(url, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=2) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
            return response.status == 200 and body == "ok"
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _open_browser(url: str) -> bool:
    """Open the local dashboard URL with a Windows-friendly fallback."""

    if os.name == "nt":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        except OSError:
            pass

    try:
        return bool(webbrowser.open(url, new=2))
    except webbrowser.Error:
        return False


def _browser_launch_disabled() -> bool:
    """Return true only for the explicit isolated-lifecycle test opt-in."""

    return os.environ.get("STOCK_TOOL_NO_BROWSER", "").strip() == "1"


if __name__ == "__main__":
    raise SystemExit(main())
