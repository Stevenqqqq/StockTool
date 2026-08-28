from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from stock_tool.domain.models import Market, Symbol
from stock_tool.portfolio.ledger import LedgerEntry, LedgerEntryType, replay_ledger

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


def test_fx_fee_reduces_source_cash_and_accumulates_fee() -> None:
    snapshot = replay_ledger(
        [
            _entry(
                "deposit-usd",
                LedgerEntryType.CASH_DEPOSIT,
                sequence=1,
                native_cash_delta="101",
            ),
            _entry(
                "fx-usd-twd",
                LedgerEntryType.FX_CONVERSION,
                sequence=2,
                native_cash_delta="-101",
                fee="1",
                target_currency="TWD",
                target_cash_delta="3200",
                fx_rate="32",
            ),
        ]
    )

    assert snapshot.cash_balance("USD") == Decimal("0")
    assert snapshot.cash_balance("TWD") == Decimal("3200")
    assert snapshot.fees_paid("USD") == Decimal("1")


@pytest.mark.parametrize("target_currency", ["", "   ", "\t"])
def test_fx_conversion_rejects_blank_target_currency_at_construction(
    target_currency: str,
) -> None:
    with pytest.raises(ValueError, match="FX conversion requires a valid target_currency"):
        _entry(
            "invalid-fx-target-currency",
            LedgerEntryType.FX_CONVERSION,
            sequence=1,
            native_cash_delta="-101",
            fee="1",
            target_currency=target_currency,
            target_cash_delta="3200",
            fx_rate="32",
        )


def test_valid_fx_conversion_fee_roundtrip_is_unchanged() -> None:
    entry = _entry(
        "fx-usd-twd",
        LedgerEntryType.FX_CONVERSION,
        sequence=1,
        native_cash_delta="-101",
        fee="1",
        target_currency="TWD",
        target_cash_delta="3200",
        fx_rate="32",
    )

    restored = LedgerEntry.from_dict(entry.to_dict())

    assert restored == entry
    snapshot = replay_ledger(
        [
            _entry(
                "deposit-usd",
                LedgerEntryType.CASH_DEPOSIT,
                sequence=0,
                native_cash_delta="101",
            ),
            restored,
        ]
    )
    assert snapshot.cash_balance("USD") == Decimal("0")
    assert snapshot.cash_balance("TWD") == Decimal("3200")
    assert snapshot.fees_paid("USD") == Decimal("1")


def test_fx_fee_terms_must_be_consistent_and_tax_is_rejected() -> None:
    with pytest.raises(ValueError, match="native_cash_delta"):
        _entry(
            "bad-fx-fee",
            LedgerEntryType.FX_CONVERSION,
            sequence=1,
            native_cash_delta="-100",
            fee="1",
            target_currency="TWD",
            target_cash_delta="3200",
            fx_rate="32",
        )
    with pytest.raises(ValueError, match="tax"):
        _entry(
            "bad-fx-tax",
            LedgerEntryType.FX_CONVERSION,
            sequence=1,
            native_cash_delta="-100",
            tax="1",
            target_currency="TWD",
            target_cash_delta="3200",
            fx_rate="32",
        )


def test_non_applicable_entry_fields_are_rejected() -> None:
    mu = Symbol.parse("MU", market=Market.US)
    with pytest.raises(ValueError, match="opening_position.*native_cash_delta"):
        _entry(
            "bad-opening",
            LedgerEntryType.OPENING_POSITION,
            sequence=1,
            symbol=mu,
            quantity="1",
            unit_price="100",
            native_cash_delta="1",
        )
    with pytest.raises(ValueError, match="cash_deposit.*fee"):
        _entry(
            "bad-deposit",
            LedgerEntryType.CASH_DEPOSIT,
            sequence=1,
            native_cash_delta="10",
            fee="1",
        )
    with pytest.raises(ValueError, match="cash_withdrawal.*tax"):
        _entry(
            "bad-withdrawal",
            LedgerEntryType.CASH_WITHDRAWAL,
            sequence=1,
            native_cash_delta="-10",
            tax="1",
        )
    with pytest.raises(ValueError, match="dividend.*fee"):
        _entry(
            "bad-dividend",
            LedgerEntryType.DIVIDEND,
            sequence=1,
            native_cash_delta="10",
            fee="1",
        )


def test_standalone_fee_and_tax_require_consistent_explicit_cash_reduction() -> None:
    snapshot = replay_ledger(
        [
            _entry("deposit", LedgerEntryType.CASH_DEPOSIT, sequence=1, native_cash_delta="20"),
            _entry(
                "fee",
                LedgerEntryType.FEE,
                sequence=2,
                native_cash_delta="-5",
                fee="5",
            ),
            _entry(
                "tax",
                LedgerEntryType.TAX,
                sequence=3,
                native_cash_delta="-3",
                tax="3",
            ),
        ]
    )

    assert snapshot.cash_balance("USD") == Decimal("12")
    assert snapshot.fees_paid("USD") == Decimal("5")
    assert snapshot.taxes_paid("USD") == Decimal("3")

    with pytest.raises(ValueError, match="fee.*native_cash_delta"):
        _entry(
            "bad-fee",
            LedgerEntryType.FEE,
            sequence=1,
            native_cash_delta="-4",
            fee="5",
        )
    with pytest.raises(ValueError, match="tax.*native_cash_delta"):
        _entry(
            "bad-tax",
            LedgerEntryType.TAX,
            sequence=1,
            native_cash_delta="-4",
            tax="5",
        )


def test_non_positive_market_prices_are_missing_evidence() -> None:
    mu = Symbol.parse("MU", market=Market.US)
    snapshot = replay_ledger(
        [
            _entry("deposit", LedgerEntryType.CASH_DEPOSIT, sequence=1, native_cash_delta="100"),
            _entry(
                "buy", LedgerEntryType.BUY, sequence=2, symbol=mu, quantity="1", unit_price="100"
            ),
        ]
    )

    for price in (Decimal("0"), Decimal("-1")):
        valued = snapshot.with_market_prices({mu: price})
        position = valued.position(mu)
        assert position is not None
        assert position.market_value is None
        assert position.unrealized_pnl is None
        assert position.weight is None
        assert any(item.field == "latest_price" for item in valued.missing_data)


def test_mixed_currency_prices_require_explicit_fx_evidence_for_weights() -> None:
    mu = Symbol.parse("MU", market=Market.US)
    tsmc = Symbol.parse("2330", market=Market.TWSE)
    snapshot = replay_ledger(
        [
            _entry("usd", LedgerEntryType.CASH_DEPOSIT, sequence=1, native_cash_delta="100"),
            _entry(
                "twd",
                LedgerEntryType.CASH_DEPOSIT,
                sequence=2,
                currency="TWD",
                native_cash_delta="1000",
            ),
            _entry(
                "buy-us", LedgerEntryType.BUY, sequence=3, symbol=mu, quantity="1", unit_price="100"
            ),
            _entry(
                "buy-tw",
                LedgerEntryType.BUY,
                sequence=4,
                symbol=tsmc,
                quantity="1",
                unit_price="1000",
                currency="TWD",
            ),
        ]
    ).with_market_prices({mu: Decimal("110"), tsmc: Decimal("1100")})

    assert all(position.weight is None for position in snapshot.positions)
    assert any(item.field == "fx_rate" for item in snapshot.missing_data)


def test_single_currency_positive_prices_keep_existing_weight_calculation() -> None:
    mu = Symbol.parse("MU", market=Market.US)
    aapl = Symbol.parse("AAPL", market=Market.US)
    snapshot = replay_ledger(
        [
            _entry("deposit", LedgerEntryType.CASH_DEPOSIT, sequence=1, native_cash_delta="40"),
            _entry(
                "buy-mu", LedgerEntryType.BUY, sequence=2, symbol=mu, quantity="1", unit_price="10"
            ),
            _entry(
                "buy-aapl",
                LedgerEntryType.BUY,
                sequence=3,
                symbol=aapl,
                quantity="1",
                unit_price="30",
            ),
        ]
    ).with_market_prices({mu: Decimal("10"), aapl: Decimal("30")})

    assert snapshot.position(mu).weight == Decimal("0.25")
    assert snapshot.position(aapl).weight == Decimal("0.75")
