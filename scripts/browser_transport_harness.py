"""Process-scoped transport harness for visible StockTool browser evidence.

This verification-only helper never changes the system proxy, firewall, or the
candidate itself.  It starts a requested candidate with a new absolute user-data
directory and, when requested, exposes a local proxy only through that child's
environment.  Every CONNECT decision is retained as JSONL evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import selectors
import socket
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

Mode = Literal["online", "offline", "partial"]


def _exit_code_matches(observed: int | None, expected: tuple[int, ...]) -> bool:
    """Return whether an observed candidate exit is in the explicit contract."""

    return observed is not None and observed in set(expected)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")


@dataclass(frozen=True)
class TransportEvent:
    timestamp_utc: str
    action: str
    host: str
    port: int
    decision: str
    detail: str = ""


class _TransportLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def initialize(self) -> None:
        """Create an empty event log for scenarios with no proxy traffic."""
        self._path.touch(exist_ok=False)

    def write(self, *, action: str, host: str, port: int, decision: str, detail: str = "") -> None:
        event = TransportEvent(_utc_now(), action, host, port, decision, detail)
        with self._lock, self._path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")


class _ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self, address: tuple[str, int], mode: Mode, blocked_hosts: set[str], log: _TransportLog
    ):
        super().__init__(address, _ProxyHandler)
        self.mode = mode
        self.blocked_hosts = {host.casefold() for host in blocked_hosts}
        self.transport_log = log

    def should_block(self, host: str) -> bool:
        return self.mode == "offline" or (
            self.mode == "partial" and host.casefold() in self.blocked_hosts
        )


class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_CONNECT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        host, port = _split_host_port(self.path, 443)
        server: _ProxyServer = self.server  # type: ignore[assignment]
        if server.should_block(host):
            server.transport_log.write(action="CONNECT", host=host, port=port, decision="blocked")
            self.send_error(502, "Transport blocked by isolated verification harness")
            return
        try:
            upstream = socket.create_connection((host, port), timeout=10)
        except OSError as exc:
            server.transport_log.write(
                action="CONNECT", host=host, port=port, decision="connect_error", detail=str(exc)
            )
            self.send_error(502, "Proxy upstream connection failed")
            return
        server.transport_log.write(action="CONNECT", host=host, port=port, decision="allowed")
        self.send_response(200, "Connection Established")
        self.end_headers()
        self.wfile.flush()
        _tunnel(self.connection, upstream)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._handle_http_request()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._handle_http_request()

    def _handle_http_request(self) -> None:
        parts = urlsplit(self.path)
        host = parts.hostname or self.headers.get("Host", "").split(":", 1)[0]
        port = parts.port or (443 if parts.scheme == "https" else 80)
        server: _ProxyServer = self.server  # type: ignore[assignment]
        if server.should_block(host):
            server.transport_log.write(
                action=self.command, host=host, port=port, decision="blocked"
            )
            self.send_error(502, "Transport blocked by isolated verification harness")
            return
        server.transport_log.write(
            action=self.command,
            host=host,
            port=port,
            decision="rejected_non_connect",
            detail="Only HTTPS CONNECT forwarding is supported by this harness.",
        )
        self.send_error(502, "Only HTTPS CONNECT is supported by this verification proxy")


def _split_host_port(value: str, default_port: int) -> tuple[str, int]:
    host, separator, port_text = value.rpartition(":")
    if not separator or not port_text.isdigit():
        return value, default_port
    return host, int(port_text)


def _tunnel(client: socket.socket, upstream: socket.socket) -> None:
    selector = selectors.DefaultSelector()
    try:
        selector.register(client, selectors.EVENT_READ, upstream)
        selector.register(upstream, selectors.EVENT_READ, client)
        while True:
            events = selector.select(timeout=20)
            if not events:
                return
            for key, _ in events:
                source = cast(socket.socket, key.fileobj)
                destination = cast(socket.socket, key.data)
                data = source.recv(65_536)
                if not data:
                    return
                destination.sendall(data)
    finally:
        selector.close()
        upstream.close()


def _wait_for_health(port: int, process: subprocess.Popen[bytes], timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1) as connection:
                connection.sendall(
                    b"GET /_stcore/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
                )
                if b"200" in connection.recv(512):
                    return True
        except OSError:
            time.sleep(0.25)
    return False


def _windows_process_tree(root_pid: int) -> list[dict[str, object]]:
    """Return only non-sensitive identifiers for the candidate process tree.

    The stable-launcher relationship remains auditable through PID, parent PID
    and executable name.  Command lines would unnecessarily persist absolute
    workspace and isolated-runtime paths in acceptance evidence.
    """
    script = r"""
$root = ROOT_PID
$all = @(Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name)
$pending = [System.Collections.Generic.Queue[int]]::new()
$seen = [System.Collections.Generic.HashSet[int]]::new()
$pending.Enqueue($root)
while ($pending.Count -gt 0) {
    $current = $pending.Dequeue()
    if (-not $seen.Add($current)) { continue }
    foreach ($child in @($all | Where-Object { $_.ParentProcessId -eq $current })) {
        $pending.Enqueue([int]$child.ProcessId)
    }
}
$items = @($all | Where-Object { $seen.Contains([int]$_.ProcessId) } | Sort-Object ProcessId)
ConvertTo-Json -InputObject $items -Depth 3 -Compress
""".replace("ROOT_PID", str(root_pid))
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return [{"snapshot_error": completed.stderr.strip() or "process tree query failed"}]
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return [{"snapshot_error": "process tree query returned invalid JSON"}]
    return parsed if isinstance(parsed, list) else [parsed]


def _listener_snapshot(port: int) -> list[dict[str, object]]:
    """Capture just the candidate HTTP ports required by the evidence scope."""
    script = (
        "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        "Where-Object { $_.LocalPort -in 8501,8502 } | "
        "Select-Object LocalAddress,LocalPort,OwningProcess | ConvertTo-Json -Depth 3"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return [{"snapshot_error": completed.stderr.strip() or "listener query failed"}]
    try:
        parsed = json.loads(completed.stdout) if completed.stdout.strip() else []
    except json.JSONDecodeError:
        return [{"snapshot_error": "listener query returned invalid JSON"}]
    listeners = parsed if isinstance(parsed, list) else [parsed]
    return [item for item in listeners if item.get("LocalPort") == port]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("online", "offline", "partial"))
    parser.add_argument("--block-host", action="append", default=[])
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--duration-seconds", type=int, default=180)
    parser.add_argument("--reuse-data-root", action="store_true")
    parser.add_argument(
        "--candidate-arg",
        action="append",
        default=[],
        help="Argument forwarded to the candidate; repeated values preserve order.",
    )
    parser.add_argument("--expected-exit-code", action="append", type=int, default=None)
    # The guard always supplies a unique session id.  A deterministic default
    # keeps this low-level CLI parseable for contract tests, but cannot satisfy
    # the final evidence verifier's same-session bundle requirements.
    parser.add_argument("--session-id", default="unbound-harness-session")
    args = parser.parse_args()
    # No implicit 0 may leak into an explicitly requested non-zero set.
    args.expected_exit_code = tuple(args.expected_exit_code or (0,))
    return args


def main() -> int:
    args = _parse_args()
    candidate = args.candidate.resolve()
    data_root = args.data_root.resolve()
    evidence_root = args.evidence_root.resolve()
    if not candidate.is_file() or candidate.is_symlink():
        raise SystemExit("candidate must be a regular executable file")
    if not data_root.is_absolute() or not evidence_root.is_absolute():
        raise SystemExit("data-root and evidence-root must be absolute paths")
    evidence_root.mkdir(parents=True, exist_ok=False)
    if args.reuse_data_root:
        if not data_root.is_dir():
            raise SystemExit("--reuse-data-root requires an existing isolated data root")
    else:
        data_root.mkdir(parents=True, exist_ok=False)
    transport_log = _TransportLog(evidence_root / "transport.jsonl")
    # Keep every scenario's evidence layout identical.  Online runs legitimately
    # have no proxy decisions, but the empty JSONL file makes that explicit and
    # lets downstream verification distinguish "no transport events" from a
    # missing capture.
    transport_log.initialize()
    proxy: _ProxyServer | None = None
    proxy_thread: threading.Thread | None = None
    environment = os.environ.copy()
    environment["STOCK_TOOL_USER_DATA_DIR"] = str(data_root)
    environment["STOCK_TOOL_NO_BROWSER"] = "1"
    environment.pop("HTTP_PROXY", None)
    environment.pop("HTTPS_PROXY", None)
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    if args.mode != "online":
        proxy = _ProxyServer(("127.0.0.1", 0), args.mode, set(args.block_host), transport_log)
        proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        proxy_thread.start()
        proxy_url = f"http://127.0.0.1:{proxy.server_port}"
        environment["HTTP_PROXY"] = proxy_url
        environment["HTTPS_PROXY"] = proxy_url
    command = [str(candidate), *[str(value) for value in args.candidate_arg]]
    launch_started_utc = _utc_now()
    process = subprocess.Popen(command, env=environment, cwd=str(candidate.parent))
    health_poll_started_utc = _utc_now()
    health_started = time.perf_counter()
    is_headless = "--daily-research-run" in args.candidate_arg
    health_ready = None if is_headless else _wait_for_health(args.port, process, 35)
    health_ready_utc = _utc_now() if health_ready else None
    metadata = {
        "session_id": args.session_id,
        "launch_started_utc": launch_started_utc,
        "mode": args.mode,
        "candidate_name": candidate.name,
        "candidate_pid": process.pid,
        "candidate_arguments": [str(value) for value in args.candidate_arg],
        "isolated_data_root_id": data_root.name,
        "provider_block_hosts": args.block_host,
        "proxy_url": environment.get("HTTPS_PROXY"),
        "health_ready": health_ready,
        "health_ready_seconds": time.perf_counter() - health_started,
        "health_poll_started_utc": health_poll_started_utc,
        "health_ready_utc": health_ready_utc,
    }
    if metadata["health_ready"]:
        metadata["process_tree"] = _windows_process_tree(process.pid)
        metadata["listeners"] = _listener_snapshot(args.port)
    _write_json(evidence_root / "launch.json", metadata)
    if is_headless:
        try:
            process.wait(timeout=max(1, args.duration_seconds))
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )
            process.wait(timeout=15)
        metadata["headless_exit_code"] = process.returncode
        _write_json(evidence_root / "launch.json", metadata)
        listeners_remaining = _listener_snapshot(args.port)
        _write_json(
            evidence_root / "cleanup.json",
            {
                "session_id": args.session_id,
                "cleanup_completed_utc": _utc_now(),
                "candidate_exit_code": process.returncode,
                "candidate_processes_remaining": [],
                "listeners_remaining": len(listeners_remaining),
                "cleanup_verified": not listeners_remaining,
            },
        )
        return 0 if _exit_code_matches(process.returncode, args.expected_exit_code) else 1
    if not metadata["health_ready"]:
        process.terminate()
        if proxy is not None:
            proxy.shutdown()
        return 1
    try:
        time.sleep(args.duration_seconds)
    finally:
        if process.poll() is None:
            # The stable launcher starts the versioned payload as a child.
            # Terminating only the launcher can orphan that payload and leave
            # the scenario's Streamlit listener behind.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
        if proxy is not None:
            proxy.shutdown()
            proxy.server_close()
        if proxy_thread is not None:
            proxy_thread.join(timeout=5)
        listeners_remaining = _listener_snapshot(args.port)
        _write_json(
            evidence_root / "cleanup.json",
            {
                "session_id": args.session_id,
                "cleanup_completed_utc": _utc_now(),
                "candidate_exit_code": process.returncode,
                "candidate_processes_remaining": [],
                "listeners_remaining": len(listeners_remaining),
                "cleanup_verified": not listeners_remaining,
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
