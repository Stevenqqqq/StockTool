from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from stock_tool.portfolio_fx import (
    JsonFxQuoteCache,
    UsdTwdFxResolutionService,
    YFinanceUsdTwdProvider,
)
from stock_tool.portfolio_valuation import (
    Currency,
    FxQuote,
    PortfolioValuationConfig,
    PortfolioValuationService,
)


def _history(close: float = 32.5) -> pd.DataFrame:
    return pd.DataFrame({"Close": [close]}, index=pd.DatetimeIndex(["2026-07-18"], name="Date"))


def _history_on(date: str, close: float = 32.5) -> pd.DataFrame:
    return pd.DataFrame({"Close": [close]}, index=pd.DatetimeIndex([date], name="Date"))


def test_yfinance_usd_twd_provider_builds_valid_quote_and_inverts_for_usd_base() -> None:
    provider = YFinanceUsdTwdProvider(
        history_loader=lambda _symbol: _history(),
        now=lambda: datetime(2026, 7, 18, tzinfo=UTC),
    )

    usd_to_twd = provider.get_quote(Currency.USD, Currency.TWD)
    twd_to_usd = provider.get_quote(Currency.TWD, Currency.USD)

    assert usd_to_twd is not None
    assert usd_to_twd.rate == 32.5
    assert usd_to_twd.source == "yfinance"
    assert usd_to_twd.provider_symbol == "TWD=X"
    assert twd_to_usd is not None
    assert twd_to_usd.rate == pytest.approx(1.0 / 32.5)


@pytest.mark.parametrize("close", [0.0, -1.0, float("nan")])
def test_yfinance_usd_twd_provider_rejects_invalid_rates(close: float) -> None:
    provider = YFinanceUsdTwdProvider(history_loader=lambda _symbol: _history(close))

    assert provider.get_quote(Currency.USD, Currency.TWD) is None


def test_fx_resolution_prefers_online_then_valid_cache_then_manual(tmp_path: Path) -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    cache = JsonFxQuoteCache(tmp_path / "fx_usd_twd.json", now=lambda: now)
    cached = FxQuote(
        Currency.USD,
        Currency.TWD,
        31.0,
        "fixture-cache",
        now.isoformat(),
        now.isoformat(),
    )
    cache.save(cached)
    online = YFinanceUsdTwdProvider(history_loader=lambda _symbol: _history(32.0), now=lambda: now)

    online_result = UsdTwdFxResolutionService(online=online, cache=cache, now=lambda: now).resolve()
    assert online_result.status == "online"
    assert online_result.quote is not None and online_result.quote.rate == 32.0

    offline = YFinanceUsdTwdProvider(history_loader=lambda _symbol: pd.DataFrame(), now=lambda: now)
    cached_result = UsdTwdFxResolutionService(
        online=offline, cache=cache, now=lambda: now
    ).resolve()
    assert cached_result.status == "cache"
    assert cached_result.quote is not None and cached_result.quote.rate == 32.0
    assert cached_result.quote.source == "cache:yfinance"

    missing_cache = JsonFxQuoteCache(tmp_path / "missing.json", now=lambda: now)
    manual_result = UsdTwdFxResolutionService(
        online=offline, cache=missing_cache, now=lambda: now
    ).resolve(manual_rate=30.5)
    assert manual_result.status == "manual"
    assert manual_result.quote is not None and manual_result.quote.rate == 30.5


def test_fx_resolution_rejects_expired_or_corrupt_cache_without_inventing_rate(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    cache_path = tmp_path / "fx_usd_twd.json"
    cache = JsonFxQuoteCache(cache_path, max_age_seconds=60, now=lambda: now)
    cache.save(
        FxQuote(
            Currency.USD,
            Currency.TWD,
            31.0,
            "fixture",
            (now - timedelta(hours=1)).isoformat(),
            (now - timedelta(hours=1)).isoformat(),
        )
    )
    offline = YFinanceUsdTwdProvider(history_loader=lambda _symbol: pd.DataFrame(), now=lambda: now)

    expired = UsdTwdFxResolutionService(online=offline, cache=cache, now=lambda: now).resolve()
    assert expired.status == "unavailable"
    assert expired.quote is None
    assert any("expired" in warning.lower() for warning in expired.warnings)

    cache_path.write_text("not-json", encoding="utf-8")
    corrupt = UsdTwdFxResolutionService(online=offline, cache=cache, now=lambda: now).resolve()
    assert corrupt.status == "unavailable"
    assert corrupt.quote is None
    assert any("corrupt" in warning.lower() for warning in corrupt.warnings)


def test_fx_market_date_and_retrieval_time_have_separate_weekend_semantics(tmp_path: Path) -> None:
    friday = datetime(2026, 7, 17, tzinfo=UTC)
    saturday = friday + timedelta(days=1)
    provider = YFinanceUsdTwdProvider(
        history_loader=lambda _symbol: _history_on("2026-07-17", 32.1),
        now=lambda: saturday,
        max_market_data_age_seconds=7 * 86_400,
    )
    quote = provider.get_quote(Currency.USD, Currency.TWD)

    assert quote is not None
    assert quote.effective_at.startswith("2026-07-17")
    assert quote.fetched_at == saturday.isoformat()
    assert not quote.stale

    cache = JsonFxQuoteCache(tmp_path / "fx.json", max_age_seconds=86_400, now=lambda: saturday)
    cache.save(quote)
    offline = YFinanceUsdTwdProvider(
        history_loader=lambda _symbol: pd.DataFrame(), now=lambda: saturday
    )
    cached = UsdTwdFxResolutionService(online=offline, cache=cache, now=lambda: saturday).resolve()

    assert cached.status == "cache"
    assert cached.quote is not None
    assert cached.quote.effective_at.startswith("2026-07-17")


def test_fx_cache_ttl_uses_fetched_at_not_market_effective_date(tmp_path: Path) -> None:
    friday = datetime(2026, 7, 17, tzinfo=UTC)
    saturday = friday + timedelta(days=1)
    cache = JsonFxQuoteCache(tmp_path / "fx.json", max_age_seconds=86_400, now=lambda: saturday)
    cache.save(
        FxQuote(
            Currency.USD,
            Currency.TWD,
            32.0,
            "fixture",
            saturday.isoformat(),
            friday.isoformat(),
        )
    )

    assert cache.get_quote(Currency.USD, Currency.TWD) is not None

    expired_cache = JsonFxQuoteCache(
        tmp_path / "fx.json", max_age_seconds=86_400, now=lambda: saturday + timedelta(days=2)
    )
    assert expired_cache.get_quote(Currency.USD, Currency.TWD) is None
    assert (
        expired_cache.last_warning is not None and "expired" in expired_cache.last_warning.lower()
    )


def test_obviously_old_online_market_data_is_not_marked_as_current(tmp_path: Path) -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    provider = YFinanceUsdTwdProvider(
        history_loader=lambda _symbol: _history_on("2026-06-01", 32.0),
        now=lambda: now,
        max_market_data_age_seconds=7 * 86_400,
    )

    quote = provider.get_quote(Currency.USD, Currency.TWD)

    assert quote is not None
    assert quote.stale
    assert provider.last_warning is not None and "market data" in provider.last_warning.lower()

    result = UsdTwdFxResolutionService(
        online=provider,
        cache=JsonFxQuoteCache(tmp_path / "missing-fx-cache.json", now=lambda: now),
        now=lambda: now,
    ).resolve()
    assert result.status == "unavailable"
    assert result.quote is None


def test_automatic_quote_values_mixed_currency_portfolio_in_usd_base() -> None:
    quote = FxQuote(
        Currency.TWD,
        Currency.USD,
        1.0 / 32.0,
        "fixture",
        "2026-07-18T00:00:00+00:00",
        "2026-07-18T00:00:00+00:00",
    )
    positions = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL"],
            "market": ["TWSE", "US"],
            "currency": ["TWD", "USD"],
            "quantity": [1.0, 1.0],
            "average_cost": [640.0, 100.0],
            "note": ["", ""],
        }
    )
    prices = pd.DataFrame(
        {
            "date": ["2026-07-18", "2026-07-18"],
            "symbol": ["2330", "AAPL"],
            "market": ["TWSE", "US"],
            "close": [640.0, 100.0],
        }
    )
    result = PortfolioValuationService(
        fx_provider=type("Provider", (), {"get_quote": lambda *_: quote})(),
        config=PortfolioValuationConfig(base_currency=Currency.USD),
    ).value(positions=positions, prices=prices)

    assert result.base_market_value == pytest.approx(120.0)
    assert result.positions["weight"].sum() == pytest.approx(1.0)
