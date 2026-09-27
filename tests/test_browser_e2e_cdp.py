"""Real browser E2E verification using Chrome DevTools Protocol (CDP)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

import websockets

CDP_COMMAND_TIMEOUT_SECONDS = 10.0


def classify_browser_console_events(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split actionable app-origin warning/errors from browser extensions."""

    app_origin: list[dict[str, Any]] = []
    extensions: list[dict[str, Any]] = []
    for event in events:
        method = event.get("method")
        params = event.get("params") or {}
        level: str | None = None
        if method == "Runtime.exceptionThrown":
            level = "error"
        elif method == "Runtime.consoleAPICalled" and params.get("type") in {
            "error",
            "assert",
            "warning",
        }:
            level = "warning" if params.get("type") == "warning" else "error"
        elif method == "Log.entryAdded":
            entry_level = (params.get("entry") or {}).get("level")
            if entry_level in {"error", "warning"}:
                level = str(entry_level)
        if level is None:
            continue
        classified = {"level": level, "event": event}
        serialized = json.dumps(event, ensure_ascii=False).lower()
        if "chrome-extension://" in serialized or "edge-extension://" in serialized:
            extensions.append(classified)
        else:
            app_origin.append(classified)
    return app_origin, extensions


def test_console_classifier_keeps_extension_warnings_separate() -> None:
    app_warning = {
        "method": "Log.entryAdded",
        "params": {"entry": {"level": "warning", "url": "http://127.0.0.1:8501"}},
    }
    extension_warning = {
        "method": "Log.entryAdded",
        "params": {
            "entry": {"level": "warning", "url": "chrome-extension://example/background.js"}
        },
    }

    app, extensions = classify_browser_console_events([app_warning, extension_warning])

    assert app == [{"level": "warning", "event": app_warning}]
    assert extensions == [{"level": "warning", "event": extension_warning}]


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def listener_addresses(port: int) -> list[str]:
    """Return Windows TCP listener addresses for one evidence-only port."""

    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    suffix = f":{port}"
    addresses: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].upper() == "TCP" and parts[1].endswith(suffix):
            if parts[3].upper() == "LISTENING":
                addresses.append(parts[1])
    return addresses


def find_browser_exe() -> str:
    for p in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]:
        if os.path.exists(p):
            return p
    raise RuntimeError("No Chrome or Edge browser executable found on system.")


class CDPBrowser:
    def __init__(self, port: int, user_data_dir: Path):
        self.port = port
        self.user_data_dir = user_data_dir
        self.stderr_path = user_data_dir.parent / "browser_stderr.log"
        self._stderr_handle: Any = None
        self.proc: subprocess.Popen | None = None
        self.ws: Any = None
        self.msg_id = 0
        self.events: list[dict[str, Any]] = []

    def _stderr_tail(self, *, max_lines: int = 12, max_chars: int = 4000) -> str:
        """Return a bounded, path-redacted browser stderr tail for failures."""

        if self._stderr_handle is not None:
            self._stderr_handle.flush()
        try:
            text = self.stderr_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"<stderr unavailable: {type(exc).__name__}>"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        tail = "\n".join(lines[-max_lines:]).strip()
        for path in (self.user_data_dir, self.stderr_path, self.stderr_path.parent):
            tail = tail.replace(str(path), "<isolated_tmp>")
        if len(tail) > max_chars:
            tail = "..." + tail[-max_chars:]
        return tail or "<stderr empty>"

    def _startup_failure(self, last_error: BaseException | None) -> RuntimeError:
        exit_code = self.proc.poll() if self.proc is not None else None
        detail = str(last_error) if last_error is not None else "no response"
        return RuntimeError(
            "Failed to connect to browser CDP debugger "
            f"(exit_code={exit_code!r}; last_error={detail!r}; "
            f"stderr_tail={self._stderr_tail()})"
        )

    def _close_stderr(self) -> None:
        if self._stderr_handle is None:
            return
        self._stderr_handle.flush()
        self._stderr_handle.close()
        self._stderr_handle = None

    async def start(self):
        exe = find_browser_exe()
        self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self._stderr_handle = self.stderr_path.open("wb")
        try:
            self.proc = subprocess.Popen(
                [
                    exe,
                    "--headless=new",
                    f"--remote-debugging-port={self.port}",
                    f"--user-data-dir={self.user_data_dir}",
                    "--disable-gpu",
                    "--in-process-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--window-size=1280,900",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=self._stderr_handle,
            )
        except Exception:
            self._close_stderr()
            raise
        url = f"http://127.0.0.1:{self.port}/json/list"
        last_error: BaseException | None = None
        for _ in range(30):
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    targets = json.loads(response.read().decode())
                    page_targets = [
                        t
                        for t in targets
                        if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
                    ]
                    if page_targets:
                        page_ws_url = page_targets[0]["webSocketDebuggerUrl"]
                        self.ws = await websockets.connect(
                            page_ws_url,
                            max_size=50_000_000,
                            open_timeout=CDP_COMMAND_TIMEOUT_SECONDS,
                        )
                        await self.send("Page.enable")
                        await self.send("Runtime.enable")
                        await self.send("DOM.enable")
                        await self.send("Log.enable")
                        return
            except Exception as exc:
                last_error = exc
                if self.ws is not None:
                    raise
                if self.proc.poll() is not None:
                    raise self._startup_failure(last_error) from exc
                await asyncio.sleep(0.3)
        raise self._startup_failure(last_error)

    async def send(self, method: str, params: dict | None = None) -> dict:
        self.msg_id += 1
        payload = {"id": self.msg_id, "method": method, "params": params or {}}
        deadline = asyncio.get_running_loop().time() + CDP_COMMAND_TIMEOUT_SECONDS
        try:
            remaining = max(deadline - asyncio.get_running_loop().time(), 0.001)
            await asyncio.wait_for(self.ws.send(json.dumps(payload)), timeout=remaining)
            while True:
                remaining = max(deadline - asyncio.get_running_loop().time(), 0.001)
                raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
                data = json.loads(raw)
                if data.get("id") == payload["id"]:
                    return data
                self.events.append(data)
        except asyncio.TimeoutError as exc:
            exit_code = self.proc.poll() if self.proc is not None else None
            raise RuntimeError(
                f"CDP command timed out: method={method!r}; "
                f"exit_code={exit_code!r}; stderr_tail={self._stderr_tail()}"
            ) from exc

    async def evaluate(self, expression: str):
        res = await self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        )
        result = res.get("result", {}).get("result", {})
        return result.get("value")

    async def navigate(self, url: str):
        await self.send("Page.navigate", {"url": url})
        # Wait for network idle / page load
        for _ in range(50):
            await asyncio.sleep(0.2)
            ready = await self.evaluate("document.readyState")
            if ready == "complete":
                # Check if Streamlit main container is rendered
                has_main = await self.evaluate(
                    "Boolean(document.querySelector('[data-testid=\"stMain\"]'))"
                )
                if has_main:
                    break

    async def screenshot(self, output_path: Path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        res = await self.send("Page.captureScreenshot", {"format": "png"})
        b64 = res.get("result", {}).get("data", "")
        if b64:
            output_path.write_bytes(base64.b64decode(b64))

    async def close(self):
        if self.ws:
            await self.ws.close()
        if self.proc:
            subprocess.run(
                ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            try:
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
                self.proc.wait(timeout=3)
        self._close_stderr()


def test_real_browser_e2e_and_scroll_to_top(tmp_path: Path, monkeypatch):
    """Real browser E2E testing using CDP against active Streamlit server."""
    asyncio.run(_run_real_browser_e2e(tmp_path, monkeypatch))


async def _run_real_browser_e2e(tmp_path: Path, monkeypatch):
    port = find_free_port()
    cdp_port = find_free_port()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    browser_dir = tmp_path / "browser_profile"
    browser_dir.mkdir(parents=True, exist_ok=True)

    artifacts_dir = Path(os.environ.get("SPRINT34_ARTIFACTS_DIR", "artifacts/sprint34"))
    screenshots_dir = artifacts_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    server_stdout_path = artifacts_dir / "browser_server_stdout.log"
    server_stderr_path = artifacts_dir / "browser_server_stderr.log"

    env = dict(os.environ)
    env["STOCK_TOOL_USER_DATA_DIR"] = str(runtime_dir)
    env["PYTHONIOENCODING"] = "utf-8"

    # Start Streamlit server
    server_stdout = server_stdout_path.open("wb")
    server_stderr = server_stderr_path.open("wb")
    streamlit_proc = subprocess.Popen(
        [
            Path(".venv/Scripts/python.exe").resolve(),
            "-m",
            "streamlit",
            "run",
            "src/stock_tool/dashboard/app.py",
            f"--server.port={port}",
            "--server.address=127.0.0.1",
            "--server.headless=true",
            "--server.fileWatcherType=none",
            "--browser.gatherUsageStats=false",
        ],
        env=env,
        stdout=server_stdout,
        stderr=server_stderr,
    )

    browser = CDPBrowser(cdp_port, browser_dir)
    results: dict[str, Any] = {
        "workspaces": {},
        "scroll_to_top_test": {},
        "scale_tests": {},
        "keyboard_navigation": {},
    }

    try:
        # Wait for Streamlit server to be available
        url = f"http://127.0.0.1:{port}"
        for _ in range(40):
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    if resp.status == 200:
                        break
            except Exception:
                await asyncio.sleep(0.3)
        else:
            raise RuntimeError("Streamlit server failed to start.")

        listeners = listener_addresses(port)
        assert listeners, f"No Streamlit listener found for port {port}"
        assert all(
            address.startswith("127.0.0.1:") for address in listeners
        ), f"Streamlit listener escaped loopback: {listeners}"

        await browser.start()
        await browser.navigate(url)

        # Wait for Streamlit to render initial main content
        for _ in range(30):
            has_h1 = await browser.evaluate(
                "Boolean(document.querySelector('[data-testid=\"stMain\"] h1'))"
            )
            if has_h1:
                break
            await asyncio.sleep(0.4)

        # 1. Verify Home Workspace
        await browser.screenshot(screenshots_dir / "01_home.png")
        home_title = await browser.evaluate(
            "Array.from(document.querySelectorAll('[data-testid=\"stMain\"] h1')).map(h => h.innerText)"
        )
        results["workspaces"]["home"] = {
            "main_h1_count": len(home_title),
            "main_h1_titles": home_title,
            "screenshot": str(screenshots_dir / "01_home.png"),
        }
        assert len(home_title) == 1, f"Expected 1 H1 on Home page, got {home_title}"

        # Helper to click primary navigation radio by label text
        async def click_nav(name: str):
            js = f"""
            (() => {{
                const labels = Array.from(document.querySelectorAll('section[data-testid="stSidebar"] div[data-testid="stRadio"] label'));
                const target = labels.find(l => l.innerText.trim().includes("{name}"));
                if (target) {{
                    target.click();
                    const input = target.querySelector('input');
                    if (input) input.click();
                    return true;
                }}
                return false;
            }})()
            """
            clicked = await browser.evaluate(js)
            assert clicked, f"Failed to find sidebar navigation item for '{name}'"
            await asyncio.sleep(2)

        # 2. Explore Workspace
        await click_nav("探索")
        await browser.screenshot(screenshots_dir / "02_explore.png")
        explore_h1 = await browser.evaluate(
            "Array.from(document.querySelectorAll('[data-testid=\"stMain\"] h1')).map(h => h.innerText)"
        )
        results["workspaces"]["explore"] = {
            "main_h1_count": len(explore_h1),
            "main_h1_titles": explore_h1,
            "screenshot": str(screenshots_dir / "02_explore.png"),
        }
        assert len(explore_h1) == 1, f"Expected 1 H1 on Explore page, got {explore_h1}"

        # 3. Strategy Workspace
        await click_nav("策略")
        await browser.screenshot(screenshots_dir / "03_strategy.png")
        strategy_h1 = await browser.evaluate(
            "Array.from(document.querySelectorAll('[data-testid=\"stMain\"] h1')).map(h => h.innerText)"
        )
        results["workspaces"]["strategy"] = {
            "main_h1_count": len(strategy_h1),
            "main_h1_titles": strategy_h1,
            "screenshot": str(screenshots_dir / "03_strategy.png"),
        }
        assert len(strategy_h1) == 1, f"Expected 1 H1 on Strategy page, got {strategy_h1}"

        # 4. Holdings Workspace
        await click_nav("持倉")
        await browser.screenshot(screenshots_dir / "04_holdings.png")
        holdings_h1 = await browser.evaluate(
            "Array.from(document.querySelectorAll('[data-testid=\"stMain\"] h1')).map(h => h.innerText)"
        )
        results["workspaces"]["holdings"] = {
            "main_h1_count": len(holdings_h1),
            "main_h1_titles": holdings_h1,
            "screenshot": str(screenshots_dir / "04_holdings.png"),
        }
        assert len(holdings_h1) == 1, f"Expected 1 H1 on Holdings page, got {holdings_h1}"

        # 5. Library Workspace
        await click_nav("研究庫")
        await browser.screenshot(screenshots_dir / "05_library.png")
        library_h1 = await browser.evaluate(
            "Array.from(document.querySelectorAll('[data-testid=\"stMain\"] h1')).map(h => h.innerText)"
        )
        results["workspaces"]["library"] = {
            "main_h1_count": len(library_h1),
            "main_h1_titles": library_h1,
            "screenshot": str(screenshots_dir / "05_library.png"),
        }
        assert len(library_h1) == 1, f"Expected 1 H1 on Library page, got {library_h1}"

        # 6. Settings Workspace
        await click_nav("設定")
        await browser.screenshot(screenshots_dir / "06_settings.png")
        settings_h1 = await browser.evaluate(
            "Array.from(document.querySelectorAll('[data-testid=\"stMain\"] h1')).map(h => h.innerText)"
        )
        results["workspaces"]["settings"] = {
            "main_h1_count": len(settings_h1),
            "main_h1_titles": settings_h1,
            "screenshot": str(screenshots_dir / "06_settings.png"),
        }
        assert len(settings_h1) == 1, f"Expected 1 H1 on Settings page, got {settings_h1}"

        # --- TEST 1: Cross-Page Scroll to Top on Long Pages ---
        # Go back to Explore (long scrollable page)
        await click_nav("探索")
        # Scroll Explore page down
        scroll_down_js = """
        (() => {
            const main = document.querySelector('[data-testid="stMain"]');
            if (main) {
                main.scrollTop = 800;
                return main.scrollTop;
            }
            return 0;
        })()
        """
        await browser.evaluate(scroll_down_js)
        await asyncio.sleep(0.5)
        # Check actual scroll position before switch
        check_scroll_js = """
        (() => {
            const main = document.querySelector('[data-testid="stMain"]');
            return main ? main.scrollTop : 0;
        })()
        """
        actual_before_scroll = await browser.evaluate(check_scroll_js)

        # Now switch to Settings (also long scrollable page)
        await click_nav("設定")

        # Check scroll position after switch
        after_scroll = await browser.evaluate(check_scroll_js)
        after_title = await browser.evaluate(
            "document.querySelector('[data-testid=\"stMain\"] h1') ? document.querySelector('[data-testid=\"stMain\"] h1').innerText : ''"
        )
        results["scroll_to_top_test"] = {
            "from_page": "探索",
            "to_page": "設定",
            "active_title_after_switch": after_title,
            "before_switch_scrollTop": actual_before_scroll,
            "after_switch_scrollTop": after_scroll,
            "passed": after_scroll == 0 and after_title == "設定",
        }
        assert after_title == "設定", f"Expected active workspace '設定', got '{after_title}'"
        assert after_scroll == 0, f"Expected scrollTop 0 after page switch, got {after_scroll}"

        # --- TEST 2: Scaling (100% = 1280px, 125% = 1024px, 150% = 853px CSS Viewport) ---
        viewport_scales = [
            ("100%", 1280, 800, 1.0),
            ("125%", 1024, 640, 1.25),
            ("150%", 853, 533, 1.5),
        ]

        overflow_check_js = """
        ((viewportWidth) => {
            const main = document.querySelector('[data-testid="stMain"]');
            const docEl = document.documentElement;

            const clientWidth = main ? main.clientWidth : docEl.clientWidth;
            const scrollWidth = main ? main.scrollWidth : docEl.scrollWidth;
            const hasHorizontalScroll = scrollWidth > (clientWidth + 2);

            const elements = Array.from(document.querySelectorAll(
                'h1, h2, h3, [data-testid="stMetric"], [data-testid="stVerticalBlockBorderWrapper"], button, .st-ui-stat, .st-ui-state-panel, div[data-testid="stHorizontalBlock"]'
            ));
            const overflowingElements = [];
            for (const el of elements) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    if (rect.right > (viewportWidth + 3) || rect.left < -3) {
                        overflowingElements.push({
                            tag: el.tagName.toLowerCase(),
                            className: el.className ? String(el.className).slice(0, 50) : '',
                            text: (el.innerText || '').slice(0, 30).trim(),
                            left: Math.round(rect.left),
                            right: Math.round(rect.right),
                            viewportWidth: viewportWidth
                        });
                    }
                }
            }

            return {
                clientWidth: clientWidth,
                scrollWidth: scrollWidth,
                hasHorizontalScroll: hasHorizontalScroll,
                overflowingCount: overflowingElements.length,
                overflowingElements: overflowingElements.slice(0, 5)
            };
        })
        """

        for label, vp_w, vp_h, scale_factor in viewport_scales:
            await browser.send(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": vp_w,
                    "height": vp_h,
                    "deviceScaleFactor": scale_factor,
                    "mobile": False,
                },
            )
            await asyncio.sleep(0.5)
            screenshot_path = screenshots_dir / f"scale_{label.replace('%', '')}.png"
            await browser.screenshot(screenshot_path)

            scale_data = await browser.evaluate(f"({overflow_check_js})({vp_w})")
            is_valid = not scale_data["hasHorizontalScroll"] and scale_data["overflowingCount"] == 0
            results["scale_tests"][label] = {
                "css_viewport_width": vp_w,
                "css_viewport_height": vp_h,
                "scale_factor": scale_factor,
                "screenshot": str(screenshot_path),
                "clientWidth": scale_data["clientWidth"],
                "scrollWidth": scale_data["scrollWidth"],
                "has_horizontal_overflow": scale_data["hasHorizontalScroll"],
                "overflowing_elements_count": scale_data["overflowingCount"],
                "overflowing_elements": scale_data["overflowingElements"],
                "status": "passed" if is_valid else "failed",
            }
            assert not scale_data[
                "hasHorizontalScroll"
            ], f"Horizontal scroll detected at {label} ({vp_w}px): scrollWidth={scale_data['scrollWidth']} > clientWidth={scale_data['clientWidth']}"
            assert (
                scale_data["overflowingCount"] == 0
            ), f"Elements overflowing viewport at {label} ({vp_w}px): {scale_data['overflowingElements']}"

        # Reset device metrics override to standard 1280x800 and fresh navigate to start pure keyboard test
        await browser.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 1280,
                "height": 800,
                "deviceScaleFactor": 1.0,
                "mobile": False,
            },
        )
        await browser.navigate(url)
        for _ in range(40):
            has_radio = await browser.evaluate(
                'Boolean(document.querySelector(\'section[data-testid="stSidebar"] div[data-testid="stRadio"]\'))'
            )
            if has_radio:
                break
            await asyncio.sleep(0.3)

        # --- TEST 3: Pure Keyboard Navigation ---
        async def press_key(key: str, modifiers: int = 0):
            key_codes = {
                "Tab": (9, "\t", "Tab"),
                "Enter": (13, "\r", "Enter"),
                "Space": (32, " ", "Space"),
                "ArrowDown": (40, "", "ArrowDown"),
                "ArrowUp": (38, "", "ArrowUp"),
            }
            vk, text, code = key_codes.get(key, (0, "", key))
            event_key = " " if key == "Space" else key
            if modifiers:
                await browser.send(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "modifiers": modifiers,
                        "windowsVirtualKeyCode": vk,
                        "nativeVirtualKeyCode": vk,
                        "key": event_key,
                        "code": code,
                    },
                )
                await browser.send(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "modifiers": modifiers,
                        "windowsVirtualKeyCode": vk,
                        "nativeVirtualKeyCode": vk,
                        "key": event_key,
                        "code": code,
                    },
                )
            else:
                await browser.send(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "windowsVirtualKeyCode": vk,
                        "nativeVirtualKeyCode": vk,
                        "text": text,
                        "unmodifiedText": text,
                        "key": event_key,
                        "code": code,
                    },
                )
                await browser.send(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "windowsVirtualKeyCode": vk,
                        "nativeVirtualKeyCode": vk,
                        "key": event_key,
                        "code": code,
                    },
                )
            await asyncio.sleep(0.3)

        get_active_el_js = """
        (() => {
            const el = document.activeElement;
            const h1 = document.querySelector('[data-testid="stMain"] h1');
            const h1_title = h1 ? h1.innerText.trim() : '';

            if (!el || el === document.body) {
                return {
                    is_valid_stocktool: false,
                    ignore_reason: 'body_or_null',
                    in_sidebar: false,
                    tag: 'body',
                    text: '',
                    active_element_rect: { x: 0, y: 0, width: 0, height: 0 },
                    owner_label: null,
                    h1_title: h1_title
                };
            }

            const rect = el.getBoundingClientRect();
            const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').slice(0, 50).trim();

            // Identify owner label for inputs
            let owner_label = null;
            const label_el = el.closest('label') || (el.id ? document.querySelector(`label[for="${el.id}"]`) : null);
            if (label_el) {
                const l_rect = label_el.getBoundingClientRect();
                owner_label = {
                    text: (label_el.innerText || '').trim(),
                    rect: {
                        x: Math.round(l_rect.x),
                        y: Math.round(l_rect.y),
                        width: Math.round(l_rect.width),
                        height: Math.round(l_rect.height)
                    },
                    is_visible: l_rect.width > 0 && l_rect.height > 0,
                    checked: Boolean(el.checked)
                };
            }

            const is_deploy = (text && text.includes('Deploy')) || (el.getAttribute('aria-label') === 'Deploy');
            const is_menu = (el.getAttribute('aria-label') === 'Main menu') || (text && text.includes('Main menu'));
            const is_header_chrome = Boolean(el.closest('header')) && !el.closest('section[data-testid="stSidebar"]');
            const is_iframe = el.tagName === 'IFRAME';
            const is_heading_permalink = el.tagName === 'A' && (
                text === 'Link to heading' ||
                el.getAttribute('aria-label') === 'Link to heading'
            );
            const role = (el.getAttribute('role') || '').toLowerCase();
            const is_interactive = ['INPUT', 'BUTTON', 'SELECT', 'TEXTAREA', 'A', 'SUMMARY'].includes(el.tagName) ||
                ['button', 'checkbox', 'combobox', 'link', 'menuitem', 'option', 'radio', 'switch', 'tab'].includes(role);
            const style = window.getComputedStyle(el);
            const is_visible = style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0 && (
                (rect.width > 0 && rect.height > 0) || (owner_label && owner_label.is_visible)
            );
            const is_zero_size_without_visible_label = (rect.width === 0 && rect.height === 0) && (!owner_label || !owner_label.is_visible);

            let is_valid = true;
            let ignore_reason = null;
            if (is_deploy) { is_valid = false; ignore_reason = 'deploy_button'; }
            else if (is_menu) { is_valid = false; ignore_reason = 'main_menu'; }
            else if (is_header_chrome) { is_valid = false; ignore_reason = 'header_chrome'; }
            else if (is_iframe) { is_valid = false; ignore_reason = 'iframe'; }
            else if (is_heading_permalink) { is_valid = false; ignore_reason = 'heading_permalink'; }
            else if (!is_interactive) { is_valid = false; ignore_reason = 'not_interactive'; }
            else if (is_zero_size_without_visible_label) { is_valid = false; ignore_reason = 'zero_size_element'; }
            else if (!is_visible) { is_valid = false; ignore_reason = 'not_visible'; }

            const in_sidebar = Boolean(el.closest('section[data-testid="stSidebar"]'));

            return {
                is_valid_stocktool: is_valid,
                ignore_reason: ignore_reason,
                in_sidebar: in_sidebar,
                tag: el.tagName.toLowerCase(),
                input_type: el.getAttribute('type'),
                role: role,
                text: text,
                active_element_rect: {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height)
                },
                owner_label: owner_label,
                is_visible: is_visible,
                h1_title: h1_title
            };
        })()
        """

        keyboard_steps = []

        # 1. Tab into sidebar navigation radio group
        info = None
        for i in range(12):
            await press_key("Tab")
            info = await browser.evaluate(get_active_el_js)
            tab_step = {
                "step": f"tab_from_fresh_{i+1}",
                "key": "Tab",
                "action": "advance_from_fresh_page",
                "h1_title": info.get("h1_title"),
                "active_element": {
                    "tag": info.get("tag"),
                    "text": info.get("text"),
                    "rect": info.get("active_element_rect"),
                },
                "owner_label": info.get("owner_label"),
                "is_required_stocktool_step": True,
                "is_valid_stocktool_step": info.get("is_valid_stocktool", False),
            }
            keyboard_steps.append(tab_step)
            assert tab_step["is_valid_stocktool_step"], tab_step
            if (
                info.get("is_valid_stocktool")
                and info.get("in_sidebar")
                and info.get("owner_label")
            ):
                tab_step["action"] = "focus_sidebar_radio"
                break
        assert info is not None and keyboard_steps, "Tab did not reach StockTool sidebar navigation"

        # 2. ArrowDown to Explore workspace
        h1_before_explore = info.get("h1_title")
        await press_key("ArrowDown")
        await asyncio.sleep(2.0)
        info_explore = await browser.evaluate(get_active_el_js)
        keyboard_steps.append(
            {
                "step": "arrow_down_to_explore",
                "key": "ArrowDown",
                "action": "switch_workspace",
                "h1_before": h1_before_explore,
                "h1_after": info_explore.get("h1_title"),
                "active_element": {
                    "tag": info_explore.get("tag"),
                    "text": info_explore.get("text"),
                    "rect": info_explore.get("active_element_rect"),
                },
                "owner_label": info_explore.get("owner_label"),
                "is_required_stocktool_step": True,
                "is_valid_stocktool_step": info_explore.get("is_valid_stocktool", False),
            }
        )
        assert keyboard_steps[-1]["is_valid_stocktool_step"], keyboard_steps[-1]

        # 3. ArrowDown through the remaining workspaces to Settings. Record
        # every native key event instead of collapsing four events into one.
        previous_title = info_explore.get("h1_title")
        info_settings = info_explore
        for index in range(4):
            await press_key("ArrowDown")
            await asyncio.sleep(1.0)
            info_settings = await browser.evaluate(get_active_el_js)
            arrow_step = {
                "step": f"arrow_down_workspace_{index+2}",
                "key": "ArrowDown",
                "action": "switch_workspace",
                "h1_before": previous_title,
                "h1_after": info_settings.get("h1_title"),
                "active_element": {
                    "tag": info_settings.get("tag"),
                    "text": info_settings.get("text"),
                    "rect": info_settings.get("active_element_rect"),
                },
                "owner_label": info_settings.get("owner_label"),
                "is_required_stocktool_step": True,
                "is_valid_stocktool_step": info_settings.get("is_valid_stocktool", False),
            }
            keyboard_steps.append(arrow_step)
            assert arrow_step["is_valid_stocktool_step"], arrow_step
            previous_title = info_settings.get("h1_title")
        await asyncio.sleep(1.0)

        # 4. From the Settings radio selected by the real ArrowDown sequence,
        # dispatch exactly one native Shift+Tab. No click/focus workaround is
        # permitted in this pure-keyboard section.
        await press_key("Tab", modifiers=8)
        info_shift_tab = await browser.evaluate(get_active_el_js)
        keyboard_steps.append(
            {
                "step": "shift_tab_backward",
                "key": "Shift+Tab",
                "action": "backward_navigation",
                "active_element": {
                    "tag": info_shift_tab.get("tag"),
                    "text": info_shift_tab.get("text"),
                    "rect": info_shift_tab.get("active_element_rect"),
                },
                "owner_label": info_shift_tab.get("owner_label"),
                "is_visible": info_shift_tab.get("is_visible", False),
                "is_required_stocktool_step": True,
                "is_valid_stocktool_step": info_shift_tab.get("is_valid_stocktool", False),
            }
        )
        assert keyboard_steps[-1]["is_valid_stocktool_step"], keyboard_steps[-1]

        # 5. Tab into main content to focus safe StockTool action button (e.g. "重新檢查本機狀態")
        button_focused_step = None
        for i in range(40):
            await press_key("Tab")
            info = await browser.evaluate(get_active_el_js)
            tab_step = {
                "step": f"tab_after_shift_{i+1}",
                "key": "Tab",
                "action": "advance_to_safe_button",
                "active_element": {
                    "tag": info.get("tag"),
                    "text": info.get("text"),
                    "rect": info.get("active_element_rect"),
                },
                "owner_label": info.get("owner_label"),
                "is_required_stocktool_step": False,
                "is_valid_stocktool_step": info.get("is_valid_stocktool", False),
            }
            keyboard_steps.append(tab_step)
            if (
                info.get("is_valid_stocktool")
                and info.get("tag") == "button"
                and ("重新檢查" in info.get("text", "") or "檢查" in info.get("text", ""))
            ):
                tab_step["action"] = "focus_safe_button"
                tab_step["is_required_stocktool_step"] = True
                button_focused_step = tab_step
                break

        assert (
            button_focused_step is not None
        ), f"Failed to focus safe button in Settings workspace. Keyboard steps: {keyboard_steps}"

        # 6. Trigger the safe refresh action with Space and record an actual
        # before/after UI state change from the isolated Settings page.
        page_state_js = """
        (() => ({
            h1: document.querySelector('[data-testid="stMain"] h1')?.innerText || '',
            alerts: Array.from(document.querySelectorAll('[data-testid="stAlert"]'))
                .map((node) => node.innerText.trim()),
            main_text_length: (document.querySelector('[data-testid="stMain"]')?.innerText || '').length
        }))()
        """
        space_before = await browser.evaluate(page_state_js)
        await press_key("Space")
        await asyncio.sleep(2.0)
        space_after = await browser.evaluate(page_state_js)
        keyboard_steps.append(
            {
                "step": "space_trigger_safe_button",
                "key": "Space",
                "action": "trigger_button_with_space",
                "trigger_result": "success",
                "before_state": space_before,
                "after_state": space_after,
                "active_element": {
                    "tag": info.get("tag"),
                    "text": info.get("text"),
                    "rect": info.get("active_element_rect"),
                },
                "owner_label": info.get("owner_label"),
                "is_required_stocktool_step": True,
                "is_valid_stocktool_step": info.get("is_valid_stocktool", False),
            }
        )
        assert space_before != space_after, keyboard_steps[-1]
        await browser.screenshot(screenshots_dir / "keyboard_after_space.png")

        # 7. After the Streamlit rerun, reach the same safe action again using
        # Tab only and retain the existing Enter activation coverage.
        enter_focus = None
        for i in range(60):
            await press_key("Tab")
            candidate = await browser.evaluate(get_active_el_js)
            tab_step = {
                "step": f"tab_after_space_{i+1}",
                "key": "Tab",
                "action": "advance_to_enter_target",
                "active_element": {
                    "tag": candidate.get("tag"),
                    "text": candidate.get("text"),
                    "rect": candidate.get("active_element_rect"),
                },
                "owner_label": candidate.get("owner_label"),
                "is_required_stocktool_step": False,
                "is_valid_stocktool_step": candidate.get("is_valid_stocktool", False),
            }
            keyboard_steps.append(tab_step)
            if (
                candidate.get("is_valid_stocktool")
                and candidate.get("tag") == "button"
                and ("重新檢查" in candidate.get("text", "") or "檢查" in candidate.get("text", ""))
            ):
                enter_focus = candidate
                tab_step["action"] = "focus_safe_button_for_enter"
                tab_step["is_required_stocktool_step"] = True
                break
        assert enter_focus is not None, "Tab did not return to a safe Enter target"

        enter_before = await browser.evaluate(get_active_el_js)
        await press_key("Enter")
        await asyncio.sleep(2.0)
        enter_after_state = await browser.evaluate(page_state_js)
        keyboard_steps.append(
            {
                "step": "enter_trigger_safe_button",
                "key": "Enter",
                "action": "trigger_button_with_enter",
                "trigger_result": "success",
                "before_state": {
                    "text": enter_before.get("text"),
                    "h1_title": enter_before.get("h1_title"),
                },
                "after_state": enter_after_state,
                "active_element": {
                    "tag": enter_focus.get("tag"),
                    "text": enter_focus.get("text"),
                    "rect": enter_focus.get("active_element_rect"),
                },
                "owner_label": enter_focus.get("owner_label"),
                "is_required_stocktool_step": True,
                "is_valid_stocktool_step": enter_focus.get("is_valid_stocktool", False),
            }
        )

        required_stocktool_steps = [
            step for step in keyboard_steps if step.get("is_required_stocktool_step") is True
        ]
        valid_stocktool_steps = [
            step for step in required_stocktool_steps if step.get("is_valid_stocktool_step")
        ]
        assert all(
            step.get("is_valid_stocktool_step") is True for step in required_stocktool_steps
        ), f"Every required keyboard step must be a valid StockTool control: {keyboard_steps}"
        required_keys = {"Tab", "ArrowDown", "Enter", "Space", "Shift+Tab"}
        observed_keys = {str(s.get("key")) for s in keyboard_steps}
        assert required_keys <= observed_keys, (required_keys, observed_keys)
        assert (
            info_explore.get("h1_title") == "探索"
        ), f"Expected title '探索', got {info_explore.get('h1_title')}"
        assert (
            info_settings.get("h1_title") == "設定"
        ), f"Expected title '設定', got {info_settings.get('h1_title')}"

        results["keyboard_navigation"] = {
            "focus_element_supported": True,
            "workspaces_switched": ["探索", "設定"],
            "safe_button_triggered": button_focused_step["active_element"]["text"],
            "valid_steps_count": len(valid_stocktool_steps),
            "recorded_key_events_count": len(keyboard_steps),
            "all_required_steps_valid": True,
            "space_state_changed": space_before != space_after,
            "pure_keyboard_only_after_fresh_navigation": True,
            "steps": keyboard_steps,
            "status": "passed",
        }

        # Flush pending CDP events, then persist raw DOM/console evidence from
        # this exact live session.
        await asyncio.sleep(0.5)
        await browser.evaluate("true")
        app_origin_messages, extension_messages = classify_browser_console_events(browser.events)
        active_console_errors = [
            item for item in app_origin_messages if item.get("level") == "error"
        ]
        active_console_warnings = [
            item for item in app_origin_messages if item.get("level") == "warning"
        ]
        final_dom = await browser.evaluate("document.documentElement.outerHTML")
        (artifacts_dir / "browser_final.dom.html").write_text(str(final_dom), encoding="utf-8")
        (artifacts_dir / "browser_console.json").write_text(
            json.dumps(
                {
                    "active_console_error_count": len(active_console_errors),
                    "active_console_warning_count": len(active_console_warnings),
                    "errors": active_console_errors,
                    "warnings": active_console_warnings,
                    "app_origin_messages": app_origin_messages,
                    "extension_messages": extension_messages,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (artifacts_dir / "keyboard_navigation_trace.json").write_text(
            json.dumps(results["keyboard_navigation"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        assert app_origin_messages == [], app_origin_messages

        # Save verification results JSON
        (artifacts_dir / "browser_verification_results.json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("Real browser E2E verification and screenshots completed successfully.")

    finally:
        await browser.close()
        streamlit_proc.terminate()
        try:
            streamlit_proc.wait(timeout=3)
        except Exception:
            streamlit_proc.kill()
            streamlit_proc.wait(timeout=3)
        server_stdout.close()
        server_stderr.close()
        shutil.rmtree(browser_dir, ignore_errors=True)
        shutil.rmtree(runtime_dir, ignore_errors=True)

    server_output = (
        server_stdout_path.read_text(encoding="utf-8", errors="replace")
        + "\n"
        + server_stderr_path.read_text(encoding="utf-8", errors="replace")
    )
    banned_server_text = ("Network URL", "External URL", "0.0.0.0")
    assert not any(value in server_output for value in banned_server_text), server_output
    warning_markers = (
        "components.v1.html",
        "use_container_width",
        "DeprecationWarning",
        "UserWarning",
    )
    assert not any(value in server_output for value in warning_markers), server_output
    assert listener_addresses(port) == [], f"Streamlit listener {port} remained after cleanup"
    assert not runtime_dir.exists(), f"Temporary runtime was not removed: {runtime_dir}"
