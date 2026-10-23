"""Bind provider databases before any Yahoo request, without global-cache fallback."""

from pathlib import Path
from threading import Lock
import hashlib
import os
import sys

import certifi

import yfinance as yf

from stock_tool.runtime_paths import RuntimePaths

_lock = Lock()
_configured: Path | None = None


def _configure_ca_bundle(target: Path) -> None:
    """Keep TLS verification on when Windows libcurl cannot open a Unicode CA path."""
    if sys.platform != "win32" or any(
        os.environ.get(key) for key in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE")
    ):
        return
    source = Path(certifi.where())
    if str(source).isascii():
        return
    data = source.read_bytes()
    destination = target / f"ca-{hashlib.sha256(data).hexdigest()}.pem"
    if not str(destination).isascii():
        raise RuntimeError(
            "TLS 憑證路徑含非 ASCII 字元；請使用 ASCII 隔離資料路徑，不能停用憑證驗證。"
        )
    if not destination.exists() or destination.read_bytes() != data:
        destination.write_bytes(data)
    # A byte-identical public trust bundle, not an added CA or verify=False.
    os.environ["REQUESTS_CA_BUNDLE"] = str(destination)


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
        _configure_ca_bundle(target)
        # yfinance's public API configures timezone, cookie and ISIN databases.
        # Set it before constructing a Ticker or initiating download/search.
        yf.set_tz_cache_location(str(target))
        _configured = target
    return target
