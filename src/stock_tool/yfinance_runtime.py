"""Bind provider databases before any Yahoo request, without global-cache fallback."""

from pathlib import Path
from threading import Lock

import yfinance as yf

from stock_tool.runtime_paths import RuntimePaths

_lock = Lock()
_configured: Path | None = None


def configure_yfinance_cache() -> Path:
    """A running process owns one runtime; switching it requires a restart."""
    global _configured
    target = RuntimePaths.from_environment().cache_dir / "yfinance"
    with _lock:
        if _configured == target:
            return target
        if _configured is not None:
            raise RuntimeError("資料目錄已變更，請重新啟動後再取得市場資料。")
        target.mkdir(parents=True, exist_ok=True)
        # yfinance's public API configures timezone, cookie and ISIN databases.
        # Set it before constructing a Ticker or initiating download/search.
        yf.set_tz_cache_location(str(target))
        _configured = target
    return target
