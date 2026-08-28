from __future__ import annotations

import pandas as pd
import pandas.testing as pdt

from stock_tool.portfolio_refresh import PortfolioRefreshService


def _positions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["2330", "AAPL", "PRIVATE"],
            "market": ["TWSE", "US", "CUSTOM"],
            "currency": ["TWD", "USD", "USD"],
            "quantity": [1.5, 2.0, 1.0],
            "average_cost": [600.0, 100.0, 10.0],
            "note": ["keep", "keep", "keep"],
        }
    )


def test_refresh_continues_after_single_symbol_failure_and_never_mutates_positions() -> None:
    positions = _positions()
    original = positions.copy(deep=True)
    calls: list[tuple[str, str, bool]] = []

    def hydrate(symbol: str, market: str, force_refresh: bool) -> dict[str, object]:
        calls.append((symbol, market, force_refresh))
        if symbol == "AAPL":
            raise RuntimeError("provider unavailable token=secret-value")
        return {
            "price_rows": 120,
            "fundamental_rows": 1,
            "provider": "yfinance",
            "query_symbol": "2330.TW",
            "last_data_date": "2026-07-18",
            "fetched_at": "2026-07-18T00:00:00+00:00",
            "source_type": "online",
            "warnings": (),
        }

    result = PortfolioRefreshService().refresh(positions=positions, hydrate=hydrate)

    pdt.assert_frame_equal(positions, original)
    assert calls == [("2330", "TWSE", False), ("AAPL", "US", False)]
    by_identity = {(item.symbol, item.market): item for item in result.items}
    assert by_identity[("2330", "TWSE")].status == "success"
    assert by_identity[("AAPL", "US")].status == "failed"
    assert "secret-value" not in " ".join(by_identity[("AAPL", "US")].warnings)
    assert by_identity[("PRIVATE", "CUSTOM")].status == "manual_required"


def test_refresh_deduplicates_canonical_identity_and_passes_force_refresh() -> None:
    positions = pd.concat([_positions().iloc[:1], _positions().iloc[:1]], ignore_index=True)
    calls: list[tuple[str, str, bool]] = []

    def hydrate(symbol: str, market: str, force_refresh: bool) -> dict[str, object]:
        calls.append((symbol, market, force_refresh))
        return {"price_rows": 60, "fundamental_rows": 0, "warnings": ()}

    result = PortfolioRefreshService().refresh(
        positions=positions, hydrate=hydrate, force_refresh=True
    )

    assert calls == [("2330", "TWSE", True)]
    assert len(result.items) == 1
