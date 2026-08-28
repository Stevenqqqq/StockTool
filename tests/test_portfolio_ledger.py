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

UTC = timezone.utc


def _entry(
    entry_id: str,
    entry_type: LedgerEntryType,
    *,
    sequence: int,
    symbol: Symbol | None = None,
    quantity: str | None = None,
    unit_price: str | None = None,
    currency: str = "USD",
    native_cash_delta: str | None = None,
    fee: str = "0",
    tax: str = "0",
    target_currency: str | None = None,
    target_cash_delta: str | None = None,
    fx_rate: str | None = None,
) -> LedgerEntry:
    return LedgerEntry(
        entry_id=entry_id,
        entry_type=entry_type,
        effective_at=datetime(2026, 1, 2, tzinfo=UTC),
        sequence=sequence,
        symbol=symbol,
        quantity=Decimal(quantity) if quantity is not None else None,
        unit_price=Decimal(unit_price) if unit_price is not None else None,
        currency=currency,
        native_cash_delta=Decimal(native_cash_delta) if native_cash_delta is not None else None,
        fee=Decimal(fee),
        tax=Decimal(tax),
        target_currency=target_currency,
        target_cash_delta=(Decimal(target_cash_delta) if target_cash_delta is not None else None),
        fx_rate=Decimal(fx_rate) if fx_rate is not None else None,
        source="fixture",
    )


def test_average_cost_buy_partial_sell_and_expenses_have_manual_reconciliation() -> None:
    mu = Symbol.parse("MU", market=Market.US)
    entries = [
        _entry("deposit", LedgerEntryType.CASH_DEPOSIT, sequence=1, native_cash_delta="1000"),
        _entry(
            "buy-1",
            LedgerEntryType.BUY,
            sequence=2,
            symbol=mu,
            quantity="3",
            unit_price="100",
            fee="3",
        ),
        _entry(
            "buy-2",
            LedgerEntryType.BUY,
            sequence=3,
            symbol=mu,
            quantity="2",
            unit_price="120",
            fee="2",
        ),
        _entry(
            "sell",
            LedgerEntryType.SELL,
            sequence=4,
            symbol=mu,
            quantity="2",
            unit_price="130",
            fee="1",
            tax="2",
        ),
        _entry(
            "dividend",
            LedgerEntryType.DIVIDEND,
            sequence=5,
            symbol=mu,
            native_cash_delta="9",
            tax="1",
        ),
    ]

    snapshot = replay_ledger(entries)

    position = snapshot.position(mu)
    # Average cost: (3*100 + 3 + 2*120 + 2) / 5 = 109.00. Two shares sold.
    assert position is not None
    assert position.quantity == Decimal("3")
    assert position.average_cost == Decimal("109")
    assert position.cost_basis == Decimal("327")
    # Cash: 1000 - 303 - 242 + (260 - 1 - 2) + 9 = 721.
    assert snapshot.cash_balance("USD") == Decimal("721")
    # Realized: net sale 257 - removed cost 218 = 39.
    assert snapshot.realized_pnl("USD") == Decimal("39")
    assert snapshot.dividend_income("USD") == Decimal("10")
    assert snapshot.fees_paid("USD") == Decimal("6")
    assert snapshot.taxes_paid("USD") == Decimal("3")


def test_fractional_shares_and_full_sale_remove_position() -> None:
    aapl = Symbol.parse("AAPL", market=Market.US)
    snapshot = replay_ledger(
        [
            _entry("deposit", LedgerEntryType.CASH_DEPOSIT, sequence=1, native_cash_delta="100"),
            _entry(
                "buy",
                LedgerEntryType.BUY,
                sequence=2,
                symbol=aapl,
                quantity="0.5",
                unit_price="100",
            ),
            _entry(
                "sell",
                LedgerEntryType.SELL,
                sequence=3,
                symbol=aapl,
                quantity="0.5",
                unit_price="110",
            ),
        ]
    )

    assert snapshot.position(aapl) is None
    assert snapshot.cash_balance("USD") == Decimal("105")
    assert snapshot.realized_pnl("USD") == Decimal("5")


def test_oversell_and_duplicate_entry_id_fail_closed() -> None:
    mu = Symbol.parse("MU", market=Market.US)
    deposit = _entry("deposit", LedgerEntryType.CASH_DEPOSIT, sequence=0, native_cash_delta="10")
    buy = _entry("same", LedgerEntryType.BUY, sequence=1, symbol=mu, quantity="1", unit_price="10")
    oversell = _entry(
        "sell", LedgerEntryType.SELL, sequence=2, symbol=mu, quantity="2", unit_price="10"
    )

    with pytest.raises(LedgerReplayError, match="insufficient position"):
        replay_ledger([deposit, buy, oversell])
    with pytest.raises(LedgerReplayError, match="duplicate entry_id"):
        replay_ledger([deposit, buy, buy])


def test_buy_or_sell_rejects_contradictory_explicit_cash_delta() -> None:
    mu = Symbol.parse("MU", market=Market.US)

    with pytest.raises(ValueError, match="buy native_cash_delta"):
        _entry(
            "bad-buy",
            LedgerEntryType.BUY,
            sequence=1,
            symbol=mu,
            quantity="1",
            unit_price="10",
            native_cash_delta="-9",
        )
    with pytest.raises(ValueError, match="sell native_cash_delta"):
        _entry(
            "bad-sell",
            LedgerEntryType.SELL,
            sequence=2,
            symbol=mu,
            quantity="1",
            unit_price="10",
            native_cash_delta="9",
        )


def test_same_ticker_in_different_markets_never_merges() -> None:
    us = Symbol.parse("ABC", market=Market.US)
    twse = Symbol.parse("ABC", market=Market.TWSE)

    snapshot = replay_ledger(
        [
            _entry("deposit-us", LedgerEntryType.CASH_DEPOSIT, sequence=1, native_cash_delta="10"),
            _entry(
                "deposit-tw",
                LedgerEntryType.CASH_DEPOSIT,
                sequence=2,
                currency="TWD",
                native_cash_delta="40",
            ),
            _entry(
                "buy-us", LedgerEntryType.BUY, sequence=3, symbol=us, quantity="1", unit_price="10"
            ),
            _entry(
                "buy-tw",
                LedgerEntryType.BUY,
                sequence=4,
                symbol=twse,
                quantity="2",
                unit_price="20",
                currency="TWD",
            ),
        ]
    )

    assert snapshot.position(us).quantity == Decimal("1")
    assert snapshot.position(twse).quantity == Decimal("2")


def test_explicit_fx_conversion_preserves_both_native_cash_legs() -> None:
    snapshot = replay_ledger(
        [
            _entry(
                "deposit",
                LedgerEntryType.CASH_DEPOSIT,
                sequence=1,
                native_cash_delta="100",
                currency="USD",
            ),
            _entry(
                "fx",
                LedgerEntryType.FX_CONVERSION,
                sequence=2,
                currency="USD",
                native_cash_delta="-100",
                target_currency="TWD",
                target_cash_delta="3200",
                fx_rate="32",
            ),
        ]
    )

    assert snapshot.cash_balance("USD") == Decimal("0")
    assert snapshot.cash_balance("TWD") == Decimal("3200")
