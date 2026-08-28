from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pandas.testing as pdt

from stock_tool.application.portfolio import PortfolioLedgerService
from stock_tool.portfolio.ledger import (
    LedgerEntryType,
    import_legacy_opening_positions,
    replay_ledger,
)


def test_legacy_import_creates_opening_positions_without_historical_cash_flow() -> None:
    legacy = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL"],
            "market": ["TWSE", "US"],
            "currency": ["TWD", "USD"],
            "quantity": [2, 1.5],
            "average_cost": [600, 100],
            "note": ["legacy", "legacy"],
        }
    )
    original = legacy.copy(deep=True)

    result = import_legacy_opening_positions(legacy)
    snapshot = replay_ledger(result.entries)

    pdt.assert_frame_equal(legacy, original)
    assert [entry.entry_type for entry in result.entries] == [
        LedgerEntryType.OPENING_POSITION,
        LedgerEntryType.OPENING_POSITION,
    ]
    assert snapshot.cash_balance("TWD") == Decimal("0")
    assert snapshot.cash_balance("USD") == Decimal("0")
    assert snapshot.realized_pnl("TWD") is None
    assert snapshot.realized_pnl("USD") is None


def test_legacy_import_is_idempotent_and_flags_incomplete_rows() -> None:
    legacy = pd.DataFrame(
        {
            "symbol": ["2330", "ABC", "XYZ", "DEF"],
            "market": ["TW", "UNKNOWN", "TPEX", "US"],
            "currency": ["TWD", "USD", "", "USD"],
            "quantity": [2, 1, 1, 1],
            "average_cost": [600, 0, 10, ""],
            "note": ["", "", "", ""],
        }
    )

    first = import_legacy_opening_positions(legacy)
    second = import_legacy_opening_positions(legacy)

    assert first.entries == second.entries
    assert first.entries[0].entry_id == "legacy-opening:TWSE:2330"
    assert len(first.entries) == 1
    assert {item.field for item in first.missing_data} == {
        "portfolio.currency",
        "portfolio.market",
        "portfolio.average_cost",
    }


def test_application_service_replays_legacy_import_without_touching_csv(tmp_path) -> None:
    path = tmp_path / "portfolio.csv"
    path.write_text(
        "symbol,market,currency,quantity,average_cost,note\n2330,TWSE,TWD,2,600,keep\n",
        encoding="utf-8",
    )
    before = path.read_bytes()

    outcome = PortfolioLedgerService().import_and_replay_legacy_csv(path)

    assert outcome.snapshot.position_count == 1
    assert path.read_bytes() == before
