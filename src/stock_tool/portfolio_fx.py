"""USD/TWD quote retrieval and private runtime cache for portfolio valuation."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import math
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

import pandas as pd
import yfinance as yf

from stock_tool.data.contracts import sanitize_provider_text
from stock_tool.portfolio_valuation import (
    CachedFxRateProvider,
    Currency,
    FxQuote,
    FxRateProvider,
)

FX_CACHE_SCHEMA_VERSION = 1
USD_TWD_QUERY_SYMBOL = "TWD=X"
DEFAULT_FX_CACHE_TTL_SECONDS = 86_400
# Without an exchange calendar, seven days tolerates normal weekends and short market
# holidays while still surfacing an obviously outdated market observation.
DEFAULT_FX_MARKET_DATA_MAX_AGE_SECONDS = 7 * 86_400


@dataclass(frozen=True, slots=True)
class FxResolution:
    """One explicit USD/TWD resolution with its fallback state."""

    quote: FxQuote | None
    status: str
    warnings: tuple[str, ...] = ()


class YFinanceUsdTwdProvider:
    """Fetch one USD/TWD quote from yfinance without inventing a fallback rate."""

    provider_name = "yfinance"
    query_symbol = USD_TWD_QUERY_SYMBOL

    def __init__(
        self,
        *,
        history_loader: Callable[[str], pd.DataFrame] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_market_data_age_seconds: int = DEFAULT_FX_MARKET_DATA_MAX_AGE_SECONDS,
    ) -> None:
        if max_market_data_age_seconds < 0:
            raise ValueError("max_market_data_age_seconds must not be negative.")
        self._history_loader = history_loader or _load_yfinance_history
        self._now = now
        self._max_market_data_age_seconds = max_market_data_age_seconds
        self.last_warning: str | None = None

    def get_quote(self, from_currency: Currency, to_currency: Currency) -> FxQuote | None:
        """Return USD/TWD or its reciprocal for the requested supported direction."""

        self.last_warning = None
        if {from_currency, to_currency} != {Currency.USD, Currency.TWD}:
            return None
        try:
            history = self._history_loader(self.query_symbol)
            quote = _quote_from_history(
                history,
                source=self.provider_name,
                provider_symbol=self.query_symbol,
                fetched_at=self._now(),
                max_market_data_age_seconds=self._max_market_data_age_seconds,
            )
        except Exception as exc:  # Provider errors are converted to a safe unavailable result.
            self.last_warning = sanitize_provider_text(f"USD/TWD provider failed: {exc}")
            return None
        if quote is None:
            self.last_warning = "USD/TWD provider returned no finite positive close."
            return None
        if quote.stale:
            self.last_warning = (
                "USD/TWD provider returned market data older than the configured "
                "market-data freshness policy; it was not treated as current."
            )
        return _quote_for_pair(quote, from_currency, to_currency)


class JsonFxQuoteCache:
    """Atomic, schema-versioned private cache for a single USD/TWD quote."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_age_seconds: int = DEFAULT_FX_CACHE_TTL_SECONDS,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must not be negative.")
        self.path = Path(path)
        self.max_age_seconds = max_age_seconds
        self._now = now
        self.last_warning: str | None = None

    def get_quote(self, from_currency: Currency, to_currency: Currency) -> FxQuote | None:
        """Load only a valid, non-expired quote and convert direction explicitly."""

        self.last_warning = None
        if {from_currency, to_currency} != {Currency.USD, Currency.TWD}:
            return None
        quote = self._load_usd_twd()
        return _quote_for_pair(quote, from_currency, to_currency) if quote is not None else None

    def save(self, quote: FxQuote) -> None:
        """Atomically persist a USD/TWD quote outside the packaged application."""

        normalized = _quote_for_pair(quote, Currency.USD, Currency.TWD)
        if normalized is None:
            raise ValueError("Only USD/TWD quotes can be cached.")
        payload = {
            "schema_version": FX_CACHE_SCHEMA_VERSION,
            "quote": {
                "from_currency": normalized.from_currency.value,
                "to_currency": normalized.to_currency.value,
                "rate": normalized.rate,
                "source": normalized.source,
                "provider_symbol": normalized.provider_symbol,
                "fetched_at": normalized.fetched_at,
                "effective_at": normalized.effective_at,
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
        try:
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _load_usd_twd(self) -> FxQuote | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != FX_CACHE_SCHEMA_VERSION:
                raise ValueError("unsupported cache schema version")
            raw = payload["quote"]
            quote = FxQuote(
                from_currency=Currency.parse(raw["from_currency"]),
                to_currency=Currency.parse(raw["to_currency"]),
                rate=float(raw["rate"]),
                source=str(raw["source"]),
                provider_symbol=_optional_text(raw.get("provider_symbol")),
                fetched_at=str(raw["fetched_at"]),
                effective_at=str(raw["effective_at"]),
                cache_state="cache",
            )
            usd_twd = _quote_for_pair(quote, Currency.USD, Currency.TWD)
            if usd_twd is None:
                raise ValueError("cache does not contain USD/TWD")
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_warning = sanitize_provider_text(
                f"USD/TWD cache is corrupt and was ignored: {exc}"
            )
            return None
        age = _retrieval_age_seconds(usd_twd, self._now())
        if age > self.max_age_seconds:
            self.last_warning = "USD/TWD cache is expired and was not used as current data."
            return None
        market_stale = is_fx_market_data_stale(usd_twd, now=self._now())
        if market_stale:
            self.last_warning = (
                "USD/TWD cache was retrieved within its TTL, but its market-data date "
                "is older than the configured freshness policy."
            )
        return replace(usd_twd, cache_state="cache", stale=market_stale)


class UsdTwdFxResolutionService:
    """Resolve USD/TWD in online, cache, manual, then unavailable order."""

    def __init__(
        self,
        *,
        online: FxRateProvider,
        cache: JsonFxQuoteCache,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._online = online
        self._cache = cache
        self._now = now

    def resolve(self, *, manual_rate: float | None = None) -> FxResolution:
        """Return a verified quote, never using ``1.0`` as a missing-rate substitute."""

        warnings: list[str] = []
        provider = CachedFxRateProvider(
            primary=self._online,
            cache=self._cache,
            max_age_seconds=self._cache.max_age_seconds,
            now=self._now,
        )
        resolved = provider.get_quote(Currency.USD, Currency.TWD)
        provider_warning = getattr(self._online, "last_warning", None)
        if provider_warning:
            warnings.append(sanitize_provider_text(provider_warning))
        if self._cache.last_warning:
            warnings.append(sanitize_provider_text(self._cache.last_warning))
        if (
            resolved is not None
            and _valid_quote(resolved)
            and not str(resolved.source).startswith("cache:")
        ):
            try:
                self._cache.save(resolved)
            except OSError as exc:
                warnings.append(sanitize_provider_text(f"USD/TWD cache write failed: {exc}"))
            return FxResolution(resolved, "online", tuple(dict.fromkeys(warnings)))
        if resolved is not None and _valid_quote(resolved):
            return FxResolution(resolved, "cache", tuple(dict.fromkeys(warnings)))

        if manual_rate is not None and math.isfinite(float(manual_rate)) and float(manual_rate) > 0:
            timestamp = self._now().isoformat()
            return FxResolution(
                FxQuote.manual(Currency.USD, Currency.TWD, float(manual_rate), timestamp),
                "manual",
                tuple(dict.fromkeys(warnings)),
            )
        if manual_rate is not None:
            warnings.append("Manual USD/TWD rate is not a finite positive value and was ignored.")
        warnings.append(
            "USD/TWD rate is unavailable; consolidated cross-currency values were not calculated."
        )
        return FxResolution(None, "unavailable", tuple(dict.fromkeys(warnings)))


def fx_provider_from_resolution(
    resolution: FxResolution,
) -> FxRateProvider | None:
    """Expose one resolved quote through the existing valuation provider boundary."""

    return _ResolvedFxProvider(resolution.quote) if resolution.quote is not None else None


@dataclass(frozen=True, slots=True)
class _ResolvedFxProvider:
    quote: FxQuote

    def get_quote(self, from_currency: Currency, to_currency: Currency) -> FxQuote | None:
        return _quote_for_pair(self.quote, from_currency, to_currency)


def _load_yfinance_history(symbol: str) -> pd.DataFrame:
    return yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=False)


def _quote_from_history(
    history: pd.DataFrame,
    *,
    source: str,
    provider_symbol: str,
    fetched_at: datetime,
    max_market_data_age_seconds: int = DEFAULT_FX_MARKET_DATA_MAX_AGE_SECONDS,
) -> FxQuote | None:
    if history is None or history.empty:
        return None
    frame = history.copy(deep=True)
    close_column = _close_column(frame)
    if close_column is None:
        return None
    closes = pd.to_numeric(frame[close_column], errors="coerce").dropna()
    closes = closes.loc[closes.map(lambda value: math.isfinite(float(value)) and float(value) > 0)]
    if closes.empty:
        return None
    latest = closes.iloc[-1]
    effective = pd.Timestamp(closes.index[-1])
    if effective.tzinfo is None:
        effective = effective.tz_localize(UTC)
    else:
        effective = effective.tz_convert(UTC)
    quote = FxQuote(
        from_currency=Currency.USD,
        to_currency=Currency.TWD,
        rate=float(latest),
        source=source,
        provider_symbol=provider_symbol,
        fetched_at=fetched_at.astimezone(UTC).isoformat(),
        effective_at=effective.isoformat(),
        cache_state="online",
    )
    return replace(
        quote,
        stale=is_fx_market_data_stale(
            quote,
            now=fetched_at,
            max_age_seconds=max_market_data_age_seconds,
        ),
    )


def _close_column(frame: pd.DataFrame) -> object | None:
    for column in frame.columns:
        values = column if isinstance(column, tuple) else (column,)
        if any(str(value).strip().lower() == "close" for value in values):
            return column
    return None


def _quote_for_pair(
    quote: FxQuote | None,
    from_currency: Currency,
    to_currency: Currency,
) -> FxQuote | None:
    if quote is None or quote.unknown or quote.rate is None:
        return None
    if quote.from_currency is from_currency and quote.to_currency is to_currency:
        return quote
    if quote.from_currency is to_currency and quote.to_currency is from_currency:
        return replace(
            quote,
            from_currency=from_currency,
            to_currency=to_currency,
            rate=1.0 / float(quote.rate),
        )
    return None


def is_fx_retrieval_fresh(
    quote: FxQuote,
    *,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_FX_CACHE_TTL_SECONDS,
) -> bool:
    """Return whether the quote retrieval time is within the cache TTL."""

    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must not be negative.")
    return _retrieval_age_seconds(quote, now or datetime.now(UTC)) <= max_age_seconds


def is_fx_market_data_stale(
    quote: FxQuote,
    *,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_FX_MARKET_DATA_MAX_AGE_SECONDS,
) -> bool:
    """Return whether the market observation is older than the configured policy."""

    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must not be negative.")
    return _timestamp_age_seconds(quote.effective_at, now or datetime.now(UTC)) > max_age_seconds


def _retrieval_age_seconds(quote: FxQuote, now: datetime) -> float:
    return _timestamp_age_seconds(quote.fetched_at, now)


def _timestamp_age_seconds(value: str, now: datetime) -> float:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return max(0.0, (now - timestamp).total_seconds())


def _valid_quote(quote: FxQuote | None) -> bool:
    return (
        quote is not None
        and not quote.unknown
        and quote.rate is not None
        and math.isfinite(quote.rate)
        and quote.rate > 0
    )


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
