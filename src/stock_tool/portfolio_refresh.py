"""Bounded user-triggered portfolio hydration orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import pandas as pd

from stock_tool.data.contracts import sanitize_provider_text
from stock_tool.domain.models import Market
from stock_tool.portfolio_management import normalize_portfolio


@dataclass(frozen=True, slots=True)
class PortfolioRefreshItem:
    """One market-qualified holding refresh outcome."""

    symbol: str
    market: str
    status: str
    price_rows: int = 0
    fundamental_rows: int = 0
    provider: str | None = None
    query_symbol: str | None = None
    source_type: str | None = None
    last_data_date: str | None = None
    fetched_at: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PortfolioRefreshResult:
    """Immutable, non-accounting result of a one-click refresh request."""

    items: tuple[PortfolioRefreshItem, ...]


class PortfolioRefreshService:
    """Refresh canonical holdings independently while preserving user portfolio data."""

    def refresh(
        self,
        *,
        positions: pd.DataFrame,
        hydrate: Callable[[str, str, bool], Mapping[str, Any]],
        force_refresh: bool = False,
    ) -> PortfolioRefreshResult:
        """Run user-triggered hydration once for each canonical standard-market holding."""

        normalized = normalize_portfolio(positions)
        seen: set[tuple[str, str]] = set()
        items: list[PortfolioRefreshItem] = []
        for row in normalized.itertuples(index=False):
            symbol = str(row.symbol).strip().upper()
            market = str(row.market).strip().upper()
            identity = (symbol, market)
            if identity in seen:
                continue
            seen.add(identity)
            if market not in {Market.TWSE.value, Market.TPEX.value, Market.US.value}:
                items.append(
                    PortfolioRefreshItem(
                        symbol=symbol,
                        market=market,
                        status="manual_required",
                        warnings=(
                            "Holding has no confirmed standard market identity; automatic retrieval was not attempted.",
                        ),
                    )
                )
                continue
            try:
                outcome = hydrate(symbol, market, force_refresh)
            except Exception as exc:
                items.append(
                    PortfolioRefreshItem(
                        symbol=symbol,
                        market=market,
                        status="failed",
                        warnings=(sanitize_provider_text(str(exc)),),
                    )
                )
                continue
            price_rows = int(outcome.get("price_rows") or 0)
            fundamental_rows = int(outcome.get("fundamental_rows") or 0)
            items.append(
                PortfolioRefreshItem(
                    symbol=symbol,
                    market=market,
                    status="success" if price_rows > 0 else "partial",
                    price_rows=price_rows,
                    fundamental_rows=fundamental_rows,
                    provider=_optional_text(outcome.get("provider")),
                    query_symbol=_optional_text(outcome.get("query_symbol")),
                    source_type=_optional_text(outcome.get("source_type")),
                    last_data_date=_optional_text(outcome.get("last_data_date")),
                    fetched_at=_optional_text(outcome.get("fetched_at")),
                    warnings=tuple(
                        sanitize_provider_text(str(item)) for item in outcome.get("warnings", ())
                    ),
                )
            )
        return PortfolioRefreshResult(tuple(items))


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
