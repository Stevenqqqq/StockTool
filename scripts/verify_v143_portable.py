"""Verify the candidate entry point in temporary data; does not run any installer."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    candidate = root / "release/v1.4.3-candidate"
    stage = candidate / "StockTool"
    evidence = root / "docs/product/v1.4.3-delivery-evidence"
    sandbox = Path(tempfile.mkdtemp(prefix="stocktool-v143-portable-"))
    runtime = sandbox / "runtime"
    shutil.copytree(candidate / "sandbox-input/fixtures", runtime)
    env = dict(os.environ)
    env.update(
        STOCK_TOOL_USER_DATA_DIR=str(runtime),
        LOCALAPPDATA=str(sandbox / "local"),
        APPDATA=str(sandbox / "roaming"),
        STOCK_TOOL_NO_BROWSER="1",
    )
    for name in list(env):
        if name.endswith("API_KEY") or name == "STOCK_TOOL_STARTUP_TIMING_FILE":
            env.pop(name)

    def hashes() -> dict[str, str]:
        return {
            str(p.relative_to(runtime)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in runtime.rglob("*")
            if p.is_file()
        }

    def ports_free() -> None:
        for port in (8501, 8502):
            with socket.socket() as check:
                assert check.connect_ex(("127.0.0.1", port)) != 0, f"Port occupied: {port}"

    baseline = hashes()
    result: dict = {"kind": "portable_only_not_installer", "runtime": str(runtime), "runs": []}
    for executable in (stage / "StockTool.exe", stage / "Payload/StockToolPayload.exe"):
        version = (
            subprocess.check_output(
                [str(executable), "--version"], env=env, cwd=sandbox, timeout=30
            )
            .decode()
            .strip()
        )
        assert version == "1.4.3", version
    for index in range(2):
        ports_free()
        start = time.monotonic()
        with (evidence / f"portable-launch-{index + 1}.log").open("wb") as log:
            process = subprocess.Popen(
                [str(stage / "StockTool.exe")],
                env=env,
                cwd=sandbox,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                healthy = False
                while time.monotonic() - start < 60:
                    assert process.poll() is None, "Entry point exited prematurely"
                    try:
                        with urllib.request.urlopen(
                            "http://127.0.0.1:8501/_stcore/health", timeout=2
                        ) as response:
                            healthy = response.status == 200 and response.read().strip() == b"ok"
                    except OSError:
                        pass
                    if healthy:
                        break
                    time.sleep(0.25)
                assert healthy, "No health response"
                expected = stage / "versions/1.4.3/StockToolPayload.exe"
                quoted = str(expected).replace("'", "''")
                check = subprocess.check_output(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-Command",
                        "@(Get-CimInstance Win32_Process -Filter \"Name = 'StockToolPayload.exe'\" | "
                        f"Where-Object {{ $_.ExecutablePath -eq '{quoted}' }}).Count",
                    ],
                    env=env,
                    timeout=15,
                )
                assert int(check.strip()) > 0, "Wrong payload process"
                result["runs"].append(
                    {"launch": index + 1, "health": "200/ok", "seconds": time.monotonic() - start}
                )
            finally:
                if process.poll() is None:
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        stdout=log,
                        stderr=log,
                        check=True,
                        timeout=15,
                    )
                process.wait(timeout=10)
                time.sleep(1)
        ports_free()
        current = hashes()
        assert all(current.get(k) == v for k, v in baseline.items()), "Protected fixture changed"
    result.update(status="passed", protected_files=len(baseline), protected_changes=0)
    (evidence / "portable-smoke.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
