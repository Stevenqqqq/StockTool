from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stock_tool.data import auto_fetch
from stock_tool.data.auto_fetch import (
    DataFetchError,
    default_date_range,
    fetch_prices,
    normalize_stooq_symbol,
    normalize_yfinance_symbol,
    standardize_yfinance_frame,
    yfinance_symbol_candidates,
)
from stock_tool.data.cache import load_cached_prices, save_cached_prices


YFINANCE_FRAME = pd.DataFrame(
    {
        "Date": ["2024-01-02", "2024-01-03"],
        "Open": [100.0, 104.0],
        "High": [105.0, 106.0],
        "Low": [99.0, 103.0],
        "Close": [104.0, 105.0],
        "Adj Close": [103.5, 104.5],
        "Volume": [1000, 1200],
    }
)


def test_normalize_yfinance_symbol_for_twse_tpex_and_us() -> None:
    assert normalize_yfinance_symbol("2330", market="TWSE") == "2330.TW"
    assert normalize_yfinance_symbol("6488", market="TPEX") == "6488.TWO"
    assert normalize_yfinance_symbol("AAPL", market="US") == "AAPL"
    assert normalize_yfinance_symbol("2330.TW", market="TWSE") == "2330.TW"
    assert normalize_yfinance_symbol("6488.TWO", market="TPEX") == "6488.TWO"


def test_yfinance_symbol_candidates_retry_other_taiwan_suffix() -> None:
    assert yfinance_symbol_candidates("3105", market="TWSE") == ("3105.TW", "3105.TWO")
    assert yfinance_symbol_candidates("3105", market="TPEX") == ("3105.TWO", "3105.TW")
    assert yfinance_symbol_candidates("3105.TW", market="TWSE") == ("3105.TW", "3105.TWO")
    assert yfinance_symbol_candidates("AAPL", market="US") == ("AAPL",)


def test_default_date_range_uses_last_two_years() -> None:
    start, end = default_date_range(None, None, today=date(2026, 6, 21))

    assert start == "2024-06-21"
    assert end == "2026-06-21"


def test_standardize_yfinance_frame_converts_columns_to_standard_schema() -> None:
    result = standardize_yfinance_frame(
        YFINANCE_FRAME,
        user_symbol="2330",
        query_symbol="2330.TW",
        market="TWSE",
        start="2024-01-02",
        end="2024-01-03",
    )

    assert list(result.columns) == [
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjusted_close",
    ]
    assert result["symbol"].tolist() == ["2330", "2330"]
    assert result["adjusted_close"].tolist() == [103.5, 104.5]


def test_standardize_yfinance_frame_sets_adjusted_close_to_close_when_missing() -> None:
    raw = YFINANCE_FRAME.drop(columns=["Adj Close"])

    result = standardize_yfinance_frame(
        raw,
        user_symbol="AAPL",
        query_symbol="AAPL",
        market="US",
        start="2024-01-02",
        end="2024-01-03",
    )

    assert result["adjusted_close"].tolist() == result["close"].tolist()


def test_standardize_yfinance_frame_handles_multiindex_columns() -> None:
    raw = YFINANCE_FRAME.set_index("Date")
    raw.columns = pd.MultiIndex.from_tuples([(column, "2330.TW") for column in raw.columns])

    result = standardize_yfinance_frame(
        raw,
        user_symbol="2330",
        query_symbol="2330.TW",
        market="TWSE",
        start="2024-01-02",
        end="2024-01-03",
    )

    assert result["close"].tolist() == [104.0, 105.0]


def test_fetch_prices_downloads_from_yfinance_and_caches(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auto_fetch,
        "_download_yfinance_history",
        lambda **kwargs: YFINANCE_FRAME,
    )

    result = fetch_prices(
        "2330",
        market="TWSE",
        start="2024-01-02",
        end="2024-01-03",
        cache_dir=tmp_path,
    )

    assert not result.from_cache
    assert result.source == "yfinance"
    assert result.provider_symbol == "2330.TW"
    assert result.cache_file is not None
    assert result.cache_file.exists()


def test_fetch_prices_retries_tpex_when_twse_suffix_is_empty(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_download(**kwargs: object) -> pd.DataFrame:
        if kwargs["query_symbol"] == "3105.TW":
            return pd.DataFrame()
        if kwargs["query_symbol"] == "3105.TWO":
            return YFINANCE_FRAME
        raise AssertionError(f"unexpected query symbol: {kwargs['query_symbol']}")

    monkeypatch.setattr(auto_fetch, "_download_yfinance_history", fake_download)

    result = fetch_prices(
        "3105",
        market="TWSE",
        start="2024-01-02",
        end="2024-01-03",
        cache_dir=tmp_path,
    )

    assert result.provider_symbol == "3105.TWO"
    assert result.source == "yfinance"
    assert len(result.data) == 2
    assert result.cache_file is not None
    assert "3105.two" in result.cache_file.name
    assert any("自動改用 3105.TWO" in warning for warning in result.warnings)
    assert [attempt.provider for attempt in result.attempts] == [
        "yfinance:3105.TW",
        "yfinance:3105.TWO",
    ]


def test_fetch_prices_uses_cache_when_yfinance_returns_empty(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached_frame = pd.DataFrame(
        {
            "date": ["2024-01-02"],
            "symbol": ["2330"],
            "open": [100.0],
            "high": [105.0],
            "low": [99.0],
            "close": [104.0],
            "volume": [1000],
            "adjusted_close": [104.0],
        }
    )
    save_cached_prices(
        cached_frame,
        source="yfinance",
        symbol="2330.TW",
        start="2024-01-02",
        end="2024-01-03",
        interval="1d",
        cache_dir=tmp_path,
    )
    monkeypatch.setattr(
        auto_fetch,
        "_download_yfinance_history",
        lambda **kwargs: pd.DataFrame(),
    )

    result = fetch_prices(
        "2330",
        market="TWSE",
        start="2024-01-02",
        end="2024-01-03",
        cache_dir=tmp_path,
        force_refresh=True,
    )

    assert result.from_cache
    assert result.source == "yfinance"
    assert result.data["close"].iloc[0] == 104.0


def test_fetch_prices_uses_alternate_taiwan_suffix_cache(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached_frame = pd.DataFrame(
        {
            "date": ["2024-01-02"],
            "symbol": ["3105"],
            "open": [100.0],
            "high": [105.0],
            "low": [99.0],
            "close": [104.0],
            "volume": [1000],
            "adjusted_close": [104.0],
        }
    )
    save_cached_prices(
        cached_frame,
        source="yfinance",
        symbol="3105.TWO",
        start="2024-01-02",
        end="2024-01-03",
        interval="1d",
        cache_dir=tmp_path,
    )
    monkeypatch.setattr(
        auto_fetch,
        "_download_yfinance_history",
        lambda **kwargs: pd.DataFrame(),
    )

    result = fetch_prices(
        "3105",
        market="TWSE",
        start="2024-01-02",
        end="2024-01-03",
        cache_dir=tmp_path,
    )

    assert result.from_cache
    assert result.provider_symbol == "3105.TWO"
    assert result.data["close"].iloc[0] == 104.0


def test_fetch_prices_network_failure_is_reported_without_crashing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_download(**kwargs: object) -> pd.DataFrame:
        raise OSError("network unavailable")

    monkeypatch.setattr(auto_fetch, "_download_yfinance_history", fail_download)

    with pytest.raises(DataFetchError) as exc_info:
        fetch_prices(
            "2330",
            market="TWSE",
            start="2024-01-02",
            end="2024-01-03",
            cache_dir=tmp_path,
            log_dir=tmp_path / "logs",
        )

    assert "yfinance" in str(exc_info.value)
    assert "建議" in str(exc_info.value)
    assert (tmp_path / "logs" / "error.log").exists()


def test_cache_roundtrip_preserves_standard_columns(tmp_path) -> None:
    frame = pd.DataFrame({"date": ["2024-01-02"], "symbol": ["AAPL"], "close": [10.0]})
    path = save_cached_prices(frame, source="yfinance", symbol="AAPL", cache_dir=tmp_path)
    loaded = load_cached_prices(source="yfinance", symbol="AAPL", cache_dir=tmp_path)

    assert path.exists()
    assert loaded is not None
    assert list(loaded.columns) == [
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjusted_close",
    ]


def test_backward_compatible_stooq_symbol_conversion() -> None:
    assert normalize_stooq_symbol("2330", market="TWSE") == "2330.tw"
