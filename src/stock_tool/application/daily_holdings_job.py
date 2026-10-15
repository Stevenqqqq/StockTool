"""One non-blocking daily runner per runtime; never call Streamlit in workers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from threading import Lock, Thread
from typing import Callable

from stock_tool.application.daily_holdings import due_key, positions_fingerprint
from stock_tool.portfolio_management import load_portfolio
from stock_tool.runtime_paths import RuntimePaths


@dataclass
class DailyJob:
    running: bool = False
    error: str | None = None


_LOCK = Lock()
_JOBS: dict[str, DailyJob] = {}


def job_for(paths: RuntimePaths) -> DailyJob:
    with _LOCK:
        return _JOBS.setdefault(str(paths.root.resolve()), DailyJob())


def attempt_path(paths: RuntimePaths) -> Path:
    return paths.data_dir / "daily_holdings_attempt.json"


def refresh_needed(paths: RuntimePaths, now: datetime) -> bool:
    positions = load_portfolio(paths.portfolio_file)
    if positions.empty:
        return False
    current = positions_fingerprint(positions)
    key = due_key(list(positions.market.astype(str)), now)
    try:
        attempt = json.loads(attempt_path(paths).read_text(encoding="utf-8"))
        age = (now - datetime.fromisoformat(attempt["at"])).total_seconds()
        if age < 0:
            return True
        if attempt["positions"] != current:
            return True
        # One retry per hour on provider failure; never one per rerender.
        if age < 3600:
            return False
        return (
            attempt["due_key"] != key
            or age >= 86400
            or attempt["status"] not in {"success", "skipped_no_new_data"}
        )
    except (OSError, ValueError, TypeError, KeyError):
        return True


def start_refresh(
    paths: RuntimePaths,
    *,
    force: bool = False,
    run: Callable[[], object] | None = None,
    now: datetime | None = None,
) -> DailyJob:
    now = now or datetime.now(UTC)
    job = job_for(paths)
    with _LOCK:
        if job.running or (not force and not refresh_needed(paths, now)):
            return job
        positions = load_portfolio(paths.portfolio_file)
        if positions.empty:
            return job
        job.running, job.error = True, None
    inputs = positions_fingerprint(positions)
    key = due_key(list(positions.market.astype(str)), now)

    def work() -> None:
        from stock_tool.application.daily_research_runner import DailyResearchRunner
        from stock_tool.application.daily_research_scheduler import _atomic_json_write

        status = "failed"
        try:
            outcome = run() if run else DailyResearchRunner(paths).run(trigger="manual")
            status = str(getattr(outcome, "status", "failed"))
            if status in {"failed", "partial"}:
                job.error = "部分來源未完成；各持股保留自己的有效結果，稍後會再檢查。"
        except Exception:
            job.error = "本次更新未完成；前次結果保留，請查看各自資料日期。"
        finally:
            try:
                _atomic_json_write(
                    attempt_path(paths),
                    {
                        "at": now.isoformat(),
                        "positions": inputs,
                        "due_key": key,
                        "status": status,
                    },
                )
            except OSError:
                job.error = "更新紀錄無法保存；前次研究仍保留。"
            with _LOCK:
                job.running = False

    Thread(target=work, name="stocktool-daily-holdings", daemon=True).start()
    return job
