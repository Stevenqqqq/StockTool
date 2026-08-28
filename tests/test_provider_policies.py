from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from stock_tool.data import auto_fetch
from stock_tool.data.auto_fetch import DataFetchError, fetch_prices
from stock_tool.data.cache import CacheState, inspect_cached_prices, save_cached_prices


def _prices(symbol: str = "2330") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-03"],
            "symbol": [symbol, symbol],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000, 1100],
            "adjusted_close": [101.0, 102.0],
        }
    )


def test_cache_metadata_classifies_fresh_stale_expired_and_corrupt(tmp_path) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    save_cached_prices(
        _prices(),
        source="yfinance",
        symbol="2330.TW",
        start="2026-01-01",
        end="2026-01-03",
        interval="1d",
        cache_dir=tmp_path,
        market="TWSE",
        fetched_at=now,
    )
    kwargs = dict(
        source="yfinance",
        symbol="2330.TW",
        start="2026-01-01",
        end="2026-01-03",
        interval="1d",
        cache_dir=tmp_path,
    )
    assert inspect_cached_prices(**kwargs, now=now).state is CacheState.FRESH
    assert inspect_cached_prices(**kwargs, now=now + timedelta(hours=2)).state is CacheState.STALE
    assert inspect_cached_prices(**kwargs, now=now + timedelta(days=2)).state is CacheState.EXPIRED

    path = inspect_cached_prices(**kwargs).path
    path.write_text("not,a,price,file\n", encoding="utf-8")
    assert inspect_cached_prices(**kwargs).state is CacheState.CORRUPT


def test_force_refresh_tries_online_then_uses_stale_if_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_cached_prices(
        _prices(),
        source="yfinance",
        symbol="2330.TW",
        start="2026-01-01",
        end="2026-01-03",
        interval="1d",
        cache_dir=tmp_path,
        market="TWSE",
        fetched_at=datetime.now(UTC) - timedelta(hours=2),
    )
    monkeypatch.setattr(
        auto_fetch,
        "_fetch_yfinance",
        lambda **_: (_ for _ in ()).throw(TimeoutError("provider timeout")),
    )

    result = fetch_prices(
        "2330",
        market="TWSE",
        start="2026-01-01",
        end="2026-01-03",
        provider="cache",
        force_refresh=True,
        cache_dir=tmp_path,
        sleeper=lambda _: None,
        clock=lambda: 0.0,
    )

    assert result.source_type == "cache"
    assert result.cache_state == "stale"
    assert result.attempts[0].provider.startswith("yfinance")


def test_corrupt_cache_is_rejected_not_silently_used(tmp_path) -> None:
    path = tmp_path / "yfinance_2330.tw_1d_2026-01-01_2026-01-03.csv"
    path.write_text("date,symbol\n2026-01-02,2330\n", encoding="utf-8")
    with pytest.raises(DataFetchError) as raised:
        fetch_prices(
            "2330",
            market="TWSE",
            start="2026-01-01",
            end="2026-01-03",
            provider="cache",
            cache_dir=tmp_path,
        )
    assert "快取" in str(raised.value)


def test_successful_download_records_actual_online_provenance(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auto_fetch, "_fetch_yfinance", lambda **_: _prices())
    result = fetch_prices(
        "2330",
        market="TWSE",
        start="2026-01-01",
        end="2026-01-03",
        cache_dir=tmp_path,
    )
    assert result.source == "yfinance"
    assert result.source_type == "online"
    assert result.fetched_at is not None
    assert result.last_data_date == "2026-01-03"
