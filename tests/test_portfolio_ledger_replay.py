from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from stock_tool.domain.models import Market, Symbol
from stock_tool.portfolio.ledger import LedgerEntry, LedgerEntryType, LedgerSnapshot, replay_ledger


def _buy(entry_id: str, *, sequence: int) -> LedgerEntry:
    return LedgerEntry(
        entry_id=entry_id,
        entry_type=LedgerEntryType.BUY,
        effective_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        sequence=sequence,
        symbol=Symbol.parse("2330", market=Market.TWSE),
        quantity=Decimal("1"),
        unit_price=Decimal("600"),
        currency="TWD",
        source="fixture",
    )


def _deposit(entry_id: str, *, sequence: int, amount: str) -> LedgerEntry:
    return LedgerEntry(
        entry_id=entry_id,
        entry_type=LedgerEntryType.CASH_DEPOSIT,
        effective_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        sequence=sequence,
        currency="TWD",
        native_cash_delta=Decimal(amount),
        source="fixture",
    )


def test_replay_is_deterministic_for_out_of_order_input_with_explicit_sequence() -> None:
    entries = [
        _buy("later", sequence=3),
        _buy("earlier", sequence=2),
        _deposit("deposit", sequence=1, amount="1200"),
    ]

    first = replay_ledger(entries)
    second = replay_ledger(list(reversed(entries)))

    assert first == second
    assert first.applied_entry_ids == ("deposit", "earlier", "later")


def test_replay_twice_and_serialization_roundtrip_are_identical() -> None:
    entries = [
        _deposit("deposit", sequence=1, amount="1200"),
        _buy("one", sequence=2),
        _buy("two", sequence=3),
    ]

    first = replay_ledger(entries)
    serialized = [entry.to_dict() for entry in entries]
    restored = [LedgerEntry.from_dict(item) for item in serialized]
    second = replay_ledger(restored)
    snapshot = LedgerSnapshot.from_dict(first.to_dict())

    assert first == second
    assert snapshot == first


def test_missing_prices_leave_market_value_and_weights_unknown() -> None:
    snapshot = replay_ledger(
        [_deposit("deposit", sequence=1, amount="600"), _buy("one", sequence=2)]
    )

    valued = snapshot.with_market_prices({})

    position = valued.positions[0]
    assert position.market_value is None
    assert position.unrealized_pnl is None
    assert position.weight is None
    assert any(item.field == "latest_price" for item in valued.missing_data)


def test_explicit_market_price_keeps_native_unrealized_pnl_without_fx_total() -> None:
    symbol = Symbol.parse("2330", market=Market.TWSE)
    valued = replay_ledger(
        [_deposit("deposit", sequence=1, amount="600"), _buy("one", sequence=2)]
    ).with_market_prices({symbol: Decimal("650")})

    position = valued.position(symbol)
    assert position.market_value == Decimal("650")
    assert position.unrealized_pnl == Decimal("50")
    assert position.weight == Decimal("1")
