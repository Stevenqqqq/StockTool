from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from stock_tool.domain.models import Market, Symbol
from stock_tool.portfolio.ledger import (
    LedgerEntry,
    LedgerEntryType,
    LedgerReplayError,
    replay_ledger,
)


def _entry(**overrides: object) -> LedgerEntry:
    payload: dict[str, object] = {
        "entry_id": "entry",
        "entry_type": LedgerEntryType.BUY,
        "effective_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
        "sequence": 1,
        "symbol": Symbol.parse("MU", market=Market.US),
        "quantity": Decimal("1"),
        "unit_price": Decimal("100"),
        "currency": "USD",
        "source": "fixture",
    }
    payload.update(overrides)
    return LedgerEntry(**payload)  # type: ignore[arg-type]


def test_unsupported_entry_and_missing_fx_evidence_fail_closed() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _entry(entry_type="unsupported")
    with pytest.raises(ValueError, match="FX conversion"):
        replay_ledger(
            [_entry(entry_type=LedgerEntryType.FX_CONVERSION, native_cash_delta=Decimal("-1"))]
        )


def test_opening_position_missing_currency_or_cost_becomes_evidence_not_fake_cash() -> None:
    missing_currency = _entry(
        entry_id="opening-1",
        entry_type=LedgerEntryType.OPENING_POSITION,
        currency="",
    )
    missing_cost = _entry(
        entry_id="opening-2",
        entry_type=LedgerEntryType.OPENING_POSITION,
        unit_price=None,
        currency="USD",
    )

    snapshot = replay_ledger([missing_currency, missing_cost])

    assert snapshot.positions == ()
    assert snapshot.cash_balances == ()
    assert {item.field for item in snapshot.missing_data} == {
        "ledger.currency",
        "ledger.unit_price",
    }


def test_cash_withdrawal_cannot_create_negative_cash_without_explicit_policy() -> None:
    withdrawal = _entry(
        entry_id="withdrawal",
        entry_type=LedgerEntryType.CASH_WITHDRAWAL,
        symbol=None,
        quantity=None,
        unit_price=None,
        native_cash_delta=Decimal("-1"),
    )

    with pytest.raises(LedgerReplayError, match="insufficient cash"):
        replay_ledger([withdrawal])
