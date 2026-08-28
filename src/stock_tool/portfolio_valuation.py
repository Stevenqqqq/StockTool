"""Currency-aware, provider-independent valuation for manual portfolios."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Callable, Protocol, Sequence

import pandas as pd

from stock_tool.domain.models import Market, MissingData, MissingDataState
from stock_tool.portfolio_management import normalize_portfolio


class Currency(str, Enum):
    """Currencies supported by the Sprint 3.2 valuation boundary."""

    TWD = "TWD"
    USD = "USD"

    @classmethod
    def parse(cls, value: Currency | str) -> Currency:
        """Parse a supported ISO currency code."""

        if isinstance(value, cls):
            return value
        return cls(str(value).strip().upper())


@dataclass(frozen=True, slots=True)
class FxQuote:
    """One explicit FX conversion quote from source to base currency."""

    from_currency: Currency
    to_currency: Currency
    rate: float | None
    source: str
    fetched_at: str
    effective_at: str
    stale: bool = False
    unknown: bool = False
    provider_symbol: str | None = None
    cache_state: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_currency", Currency.parse(self.from_currency))
        object.__setattr__(self, "to_currency", Currency.parse(self.to_currency))
        if not self.unknown and (
            self.rate is None or not math.isfinite(float(self.rate)) or self.rate <= 0
        ):
            raise ValueError("FX rate must be a finite value greater than zero.")
        if not str(self.source).strip():
            raise ValueError("FX quote source is required.")
        _parse_timestamp(self.fetched_at)
        _parse_timestamp(self.effective_at)

    @property
    def currency_pair(self) -> str:
        """Return the explicit source/base currency pair."""

        return f"{self.from_currency.value}/{self.to_currency.value}"

    @classmethod
    def manual(
        cls,
        from_currency: Currency | str,
        to_currency: Currency | str,
        rate: float,
        effective_at: str,
    ) -> FxQuote:
        """Build a clearly labeled manual quote for offline fallback use."""

        return cls(
            from_currency=Currency.parse(from_currency),
            to_currency=Currency.parse(to_currency),
            rate=float(rate),
            source="manual",
            fetched_at=effective_at,
            effective_at=effective_at,
        )


class FxRateProvider(Protocol):
    """Replaceable boundary for source-to-base FX conversion quotes."""

    def get_quote(self, from_currency: Currency, to_currency: Currency) -> FxQuote | None:
        """Return a quote for the requested pair, or ``None`` when unavailable."""


@dataclass(frozen=True, slots=True)
class StaticFxRateProvider:
    """Deterministic quote provider for tests, fixtures, and manual fallback."""

    quotes: tuple[FxQuote, ...]

    def __init__(self, quotes: Sequence[FxQuote]) -> None:
        object.__setattr__(self, "quotes", tuple(quotes))

    def get_quote(self, from_currency: Currency, to_currency: Currency) -> FxQuote | None:
        """Return the fixture quote matching one ordered currency pair."""

        return next(
            (
                quote
                for quote in self.quotes
                if quote.from_currency is from_currency and quote.to_currency is to_currency
            ),
            None,
        )


@dataclass(frozen=True, slots=True)
class CachedFxRateProvider:
    """Use a primary FX source and fall back to a bounded, explicit cache."""

    primary: FxRateProvider | None
    cache: FxRateProvider | None
    max_age_seconds: int = 86_400
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def __post_init__(self) -> None:
        if self.max_age_seconds < 0:
            raise ValueError("max_age_seconds must not be negative.")

    def get_quote(self, from_currency: Currency, to_currency: Currency) -> FxQuote | None:
        """Return a non-stale primary quote, otherwise a non-expired cache quote."""

        primary_quote = (
            self.primary.get_quote(from_currency, to_currency) if self.primary is not None else None
        )
        if primary_quote is not None and not primary_quote.unknown and not primary_quote.stale:
            return primary_quote
        cached_quote = (
            self.cache.get_quote(from_currency, to_currency) if self.cache is not None else None
        )
        if (
            cached_quote is None
            or cached_quote.unknown
            or _quote_age_seconds(cached_quote, self.now()) > self.max_age_seconds
        ):
            return None
        return replace(cached_quote, source=f"cache:{cached_quote.source}")


@dataclass(frozen=True, slots=True)
class PortfolioValuationConfig:
    """Explicit valuation configuration with TWD as the default reporting currency."""

    base_currency: Currency = Currency.TWD

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_currency", Currency.parse(self.base_currency))


@dataclass(frozen=True, slots=True)
class PortfolioValuationResult:
    """Native and base-currency valuation without mixing unavailable currencies."""

    positions: pd.DataFrame
    base_currency: Currency
    base_cost_basis: float | None
    base_market_value: float | None
    base_unrealized_pnl: float | None
    native_totals: dict[str, float]
    warnings: tuple[str, ...]
    missing_data: tuple[MissingData, ...]


class PortfolioValuationService:
    """Build position and total valuations using only explicit identity and FX data."""

    def __init__(
        self,
        fx_provider: FxRateProvider | None = None,
        config: PortfolioValuationConfig | None = None,
    ) -> None:
        self._fx_provider = fx_provider
        self._config = config or PortfolioValuationConfig()

    def value(
        self, *, positions: pd.DataFrame, prices: pd.DataFrame | None
    ) -> PortfolioValuationResult:
        """Value positions without mutating caller-owned price or portfolio frames."""

        normalized = normalize_portfolio(positions)
        output = normalized.copy(deep=True)
        lookup = _latest_price_lookup(prices)
        rows: list[dict[str, object]] = []
        warnings: list[str] = []
        missing: list[MissingData] = []
        all_convertible = True

        for _, position in output.iterrows():
            symbol = str(position["symbol"])
            try:
                market = Market.parse(position["market"])
                currency = _position_currency(position, market)
            except ValueError:
                all_convertible = False
                missing.append(
                    MissingData(
                        field="portfolio.identity",
                        state=MissingDataState.UNKNOWN,
                        reason=f"Position {symbol} has no canonical market or currency identity.",
                    )
                )
                rows.append(_unvalued_identity_row(position, symbol))
                continue
            latest_price = lookup.get((symbol, market.value))
            quantity = float(position["quantity"])
            average_cost = float(position["average_cost"])
            native_cost = quantity * average_cost
            native_value = quantity * latest_price if latest_price is not None else None
            native_pnl = native_value - native_cost if native_value is not None else None
            fx_rate, fx_source, fx_stale = self._fx_for(currency)
            if latest_price is None:
                all_convertible = False
                missing.append(
                    MissingData(
                        field="latest_price",
                        state=MissingDataState.MISSING,
                        reason=f"No market-qualified close price is available for {market.value}:{symbol}.",
                    )
                )
            if fx_rate is None:
                all_convertible = False
                missing.append(
                    MissingData(
                        field="fx_rate_to_base",
                        state=MissingDataState.MISSING,
                        reason=f"No {currency.value}/{self._config.base_currency.value} FX quote is available.",
                    )
                )
            if fx_stale:
                warnings.append(
                    f"FX quote for {currency.value}/{self._config.base_currency.value} is stale."
                )
            rows.append(
                {
                    "symbol": symbol,
                    "market": market.value,
                    "quantity": quantity,
                    "average_cost": average_cost,
                    "native_currency": currency.value,
                    "latest_price": latest_price,
                    "native_cost_basis": native_cost,
                    "native_market_value": native_value,
                    "native_unrealized_pnl": native_pnl,
                    "fx_rate_to_base": fx_rate,
                    "fx_source": fx_source,
                    "fx_stale": fx_stale,
                    "base_cost_basis": native_cost * fx_rate if fx_rate is not None else None,
                    "base_market_value": (
                        native_value * fx_rate
                        if native_value is not None and fx_rate is not None
                        else None
                    ),
                    "base_unrealized_pnl": (
                        native_pnl * fx_rate
                        if native_pnl is not None and fx_rate is not None
                        else None
                    ),
                    "weight": None,
                    "note": str(position.get("note", "")),
                }
            )

        frame = pd.DataFrame(rows)
        native_totals = _native_totals(frame)
        base_cost = _sum_if_complete(frame, "base_cost_basis", all_convertible)
        base_value = _sum_if_complete(frame, "base_market_value", all_convertible)
        base_pnl = _sum_if_complete(frame, "base_unrealized_pnl", all_convertible)
        if base_value is not None and base_value > 0:
            frame["weight"] = (
                pd.to_numeric(frame["base_market_value"], errors="coerce") / base_value
            )
        elif not frame.empty:
            warnings.append(
                "Consolidated weights are unavailable until all prices and FX quotes are present."
            )
        return PortfolioValuationResult(
            positions=frame.copy(deep=True),
            base_currency=self._config.base_currency,
            base_cost_basis=base_cost,
            base_market_value=base_value,
            base_unrealized_pnl=base_pnl,
            native_totals=native_totals,
            warnings=tuple(dict.fromkeys(warnings)),
            missing_data=tuple(missing),
        )

    def _fx_for(self, currency: Currency) -> tuple[float | None, str | None, bool]:
        if currency is self._config.base_currency:
            return 1.0, "identity", False
        if self._fx_provider is None:
            return None, None, False
        quote = self._fx_provider.get_quote(currency, self._config.base_currency)
        if quote is None or quote.unknown:
            return None, None, False
        return quote.rate, quote.source, quote.stale


def _position_currency(position: pd.Series, market: Market) -> Currency:
    raw_currency = str(position.get("currency", "")).strip().upper()
    if raw_currency:
        return Currency.parse(raw_currency)
    defaults = {Market.TWSE: Currency.TWD, Market.TPEX: Currency.TWD, Market.US: Currency.USD}
    try:
        return defaults[market]
    except KeyError as exc:
        raise ValueError(f"{market.value} positions require an explicit currency.") from exc


def _latest_price_lookup(prices: pd.DataFrame | None) -> dict[tuple[str, str], float]:
    if prices is None or prices.empty or not {"symbol", "market", "close"}.issubset(prices.columns):
        return {}
    output = prices.copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    output["market"] = output["market"].map(_valuation_market_or_empty)
    output = output.loc[
        output["market"].isin({Market.TWSE.value, Market.TPEX.value, Market.US.value})
    ]
    output["close"] = pd.to_numeric(output["close"], errors="coerce")
    if "date" in output.columns:
        output = output.sort_values(["symbol", "market", "date"])
    latest = output.groupby(["symbol", "market"], as_index=False, sort=False).tail(1)
    return {
        (str(row["symbol"]), str(row["market"])): float(row["close"])
        for _, row in latest.iterrows()
        if pd.notna(row["close"])
    }


def _sum_if_complete(frame: pd.DataFrame, column: str, complete: bool) -> float | None:
    if frame.empty:
        return 0.0
    values = pd.to_numeric(frame[column], errors="coerce")
    if not complete or values.isna().any():
        return None
    return float(values.sum())


def _native_totals(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {}
    values = pd.to_numeric(frame["native_market_value"], errors="coerce")
    output: dict[str, float] = {}
    for currency, group in frame.assign(_value=values).groupby("native_currency", sort=True):
        if group["_value"].notna().all():
            output[str(currency)] = float(group["_value"].sum())
    return output


def _unvalued_identity_row(position: pd.Series, symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "market": str(position.get("market", "UNKNOWN")),
        "quantity": float(position.get("quantity", 0.0)),
        "average_cost": float(position.get("average_cost", 0.0)),
        "native_currency": str(position.get("currency", "UNKNOWN")),
        "latest_price": None,
        "native_cost_basis": None,
        "native_market_value": None,
        "native_unrealized_pnl": None,
        "fx_rate_to_base": None,
        "fx_source": None,
        "fx_stale": False,
        "base_cost_basis": None,
        "base_market_value": None,
        "base_unrealized_pnl": None,
        "weight": None,
        "note": str(position.get("note", "")),
    }


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _quote_age_seconds(quote: FxQuote, now: datetime) -> float:
    """Return cache age from retrieval time, normalizing naive fixture timestamps."""

    fetched = _parse_timestamp(quote.fetched_at)
    if fetched.tzinfo is None and now.tzinfo is not None:
        fetched = fetched.replace(tzinfo=now.tzinfo)
    if now.tzinfo is None and fetched.tzinfo is not None:
        now = now.replace(tzinfo=fetched.tzinfo)
    return max(0.0, (now - fetched).total_seconds())


def _valuation_market_or_empty(value: object) -> str:
    try:
        market = Market.parse(str(value))
    except ValueError:
        return ""
    return market.value if market in {Market.TWSE, Market.TPEX, Market.US} else ""
