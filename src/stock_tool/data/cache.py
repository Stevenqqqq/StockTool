"""Atomic price-cache helpers with explicit age and corruption states."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import pandas as pd

from stock_tool.data.loader import REQUIRED_COLUMNS, STANDARD_COLUMNS
from stock_tool.runtime_paths import default_runtime_paths

# ``None`` deliberately delays creation of the user runtime directory until a
# caller actually reads or writes cache data.
DEFAULT_CACHE_DIR: Path | None = None


class CacheState(StrEnum):
    """Explicit cache validity states used by fallback policy and evidence UI."""

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"
    CORRUPT = "corrupt"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class CacheMetadata:
    """Non-sensitive metadata stored next to one cache CSV."""

    provider: str
    symbol: str
    market: str | None
    start_date: str | None
    end_date: str | None
    interval: str
    fetched_at: str
    last_data_date: str | None

    def to_dict(self) -> dict[str, str | None]:
        """Return JSON-compatible cache metadata."""

        return {
            "provider": self.provider,
            "symbol": self.symbol,
            "market": self.market,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "interval": self.interval,
            "fetched_at": self.fetched_at,
            "last_data_date": self.last_data_date,
        }


@dataclass(frozen=True, slots=True)
class CacheReadResult:
    """One cache inspection without silently treating bad data as usable."""

    state: CacheState
    path: Path
    data: pd.DataFrame | None = None
    metadata: CacheMetadata | None = None
    age_seconds: float | None = None
    warning: str | None = None


def cache_key(
    *,
    source: str,
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    interval: str = "d",
) -> str:
    """Build a stable cache key for one downloaded price dataset."""

    parts = [
        _safe_part(source),
        _safe_part(symbol),
        _safe_part(interval),
        _safe_part(start or "all"),
        _safe_part(end or "latest"),
    ]
    return "_".join(parts)


def resolve_cache_dir(cache_dir: str | Path | None = None) -> Path:
    """Resolve cache storage only at the point it is required."""

    return Path(cache_dir) if cache_dir is not None else default_runtime_paths().cache_dir


def cache_path(
    *,
    source: str,
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    interval: str = "d",
    cache_dir: str | Path | None = DEFAULT_CACHE_DIR,
) -> Path:
    """Return the CSV cache path for the given dataset identity."""

    return resolve_cache_dir(cache_dir) / (
        f"{cache_key(source=source, symbol=symbol, start=start, end=end, interval=interval)}.csv"
    )


def cache_metadata_path(path: Path) -> Path:
    """Return the sidecar metadata path for one cache file."""

    return path.with_suffix(f"{path.suffix}.metadata.json")


def inspect_cached_prices(
    *,
    source: str,
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    interval: str = "d",
    cache_dir: str | Path | None = DEFAULT_CACHE_DIR,
    fresh_ttl_seconds: float = 3_600.0,
    stale_ttl_seconds: float = 86_400.0,
    now: datetime | None = None,
) -> CacheReadResult:
    """Inspect cache data and metadata without accepting corrupt data.

    A legacy CSV without a metadata sidecar is intentionally marked stale.  It
    may be used only as an explicitly labelled stale-if-error fallback.
    """

    path = cache_path(
        source=source,
        symbol=symbol,
        start=start,
        end=end,
        interval=interval,
        cache_dir=cache_dir,
    )
    if not path.exists():
        return CacheReadResult(CacheState.MISSING, path)
    try:
        frame = pd.read_csv(path, dtype={"symbol": str})
        if any(column not in frame.columns for column in REQUIRED_COLUMNS):
            return CacheReadResult(
                CacheState.CORRUPT,
                path,
                warning="快取缺少必要 OHLCV 欄位，未使用該檔案。",
            )
        frame = frame.loc[:, [column for column in STANDARD_COLUMNS if column in frame.columns]]
        for column in STANDARD_COLUMNS:
            if column not in frame.columns:
                frame[column] = None
        metadata = _read_metadata(cache_metadata_path(path))
    except (OSError, UnicodeError, ValueError, pd.errors.ParserError, json.JSONDecodeError):
        return CacheReadResult(
            CacheState.CORRUPT,
            path,
            warning="快取檔案無法安全讀取，未使用該檔案。",
        )

    if metadata is None:
        return CacheReadResult(
            CacheState.STALE,
            path,
            data=frame.loc[:, list(STANDARD_COLUMNS)].copy(deep=True),
            warning="快取缺少取得時間資訊，只能作為過期備援資料。",
        )
    try:
        fetched_at = datetime.fromisoformat(metadata.fetched_at.replace("Z", "+00:00"))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        age_seconds = max(((now or datetime.now(UTC)) - fetched_at).total_seconds(), 0.0)
    except ValueError:
        return CacheReadResult(
            CacheState.CORRUPT,
            path,
            warning="快取取得時間格式無效，未使用該檔案。",
        )
    state = (
        CacheState.FRESH
        if age_seconds <= fresh_ttl_seconds
        else CacheState.STALE if age_seconds <= stale_ttl_seconds else CacheState.EXPIRED
    )
    return CacheReadResult(
        state,
        path,
        data=frame.loc[:, list(STANDARD_COLUMNS)].copy(deep=True),
        metadata=metadata,
        age_seconds=age_seconds,
    )


def load_cached_prices(
    *,
    source: str,
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    interval: str = "d",
    cache_dir: str | Path | None = DEFAULT_CACHE_DIR,
) -> pd.DataFrame | None:
    """Backward-compatible cache load returning data only when readable."""

    result = inspect_cached_prices(
        source=source,
        symbol=symbol,
        start=start,
        end=end,
        interval=interval,
        cache_dir=cache_dir,
    )
    return result.data.copy(deep=True) if result.data is not None else None


def save_cached_prices(
    frame: pd.DataFrame,
    *,
    source: str,
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    interval: str = "d",
    cache_dir: str | Path | None = DEFAULT_CACHE_DIR,
    market: str | None = None,
    fetched_at: datetime | None = None,
) -> Path:
    """Atomically persist standardized price data and cache metadata."""

    path = cache_path(
        source=source,
        symbol=symbol,
        start=start,
        end=end,
        interval=interval,
        cache_dir=cache_dir,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    output = frame.copy(deep=True)
    for column in STANDARD_COLUMNS:
        if column not in output.columns:
            output[column] = None
    output = output.loc[:, list(STANDARD_COLUMNS)]
    last_data_date = _last_data_date(output)
    metadata = CacheMetadata(
        provider=str(source).strip().lower(),
        symbol=str(symbol).strip().upper(),
        market=str(market).strip().upper() if market else None,
        start_date=start,
        end_date=end,
        interval=interval,
        fetched_at=(fetched_at or datetime.now(UTC)).isoformat(),
        last_data_date=last_data_date,
    )
    _atomic_write_csv(path, output)
    _atomic_write_text(
        cache_metadata_path(path), json.dumps(metadata.to_dict(), ensure_ascii=False)
    )
    return path


def _read_metadata(path: Path) -> CacheMetadata | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cache metadata must be an object")
    required = ("provider", "symbol", "interval", "fetched_at")
    if any(not payload.get(field) for field in required):
        raise ValueError("cache metadata is incomplete")
    return CacheMetadata(
        provider=str(payload["provider"]),
        symbol=str(payload["symbol"]),
        market=_optional_string(payload.get("market")),
        start_date=_optional_string(payload.get("start_date")),
        end_date=_optional_string(payload.get("end_date")),
        interval=str(payload["interval"]),
        fetched_at=str(payload["fetched_at"]),
        last_data_date=_optional_string(payload.get("last_data_date")),
    )


def _atomic_write_csv(path: Path, frame: pd.DataFrame) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8-sig", newline="", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        frame.to_csv(handle, index=False)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_text(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _last_data_date(frame: pd.DataFrame) -> str | None:
    if "date" not in frame.columns or frame.empty:
        return None
    values = pd.to_datetime(frame["date"], errors="coerce").dropna()
    return values.max().date().isoformat() if not values.empty else None


def _optional_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _safe_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip().lower())
    return cleaned.strip("_") or "unknown"
