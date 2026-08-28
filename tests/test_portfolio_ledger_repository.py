from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import sqlite3

import pytest

from stock_tool.domain.models import Market, Symbol
from stock_tool.portfolio.ledger import LedgerEntry, LedgerEntryType, replay_ledger
from stock_tool.portfolio.ledger_repository import (
    LedgerAccountingConflictError,
    LedgerRepository,
    LedgerRepositoryError,
    LedgerSchemaError,
)


def _entry(
    entry_id: str,
    entry_type: LedgerEntryType,
    *,
    sequence: int,
    effective_at: datetime | None = None,
    symbol: Symbol | None = None,
    currency: str = "USD",
    quantity: str | None = None,
    unit_price: str | None = None,
    native_cash_delta: str | None = None,
    fee: str = "0",
    tax: str = "0",
    target_currency: str | None = None,
    target_cash_delta: str | None = None,
    fx_rate: str | None = None,
    metadata: tuple[tuple[str, str], ...] = (),
) -> LedgerEntry:
    return LedgerEntry(
        entry_id=entry_id,
        entry_type=entry_type,
        effective_at=effective_at or datetime(2026, 7, 22, 9, tzinfo=UTC),
        sequence=sequence,
        symbol=symbol,
        currency=currency,
        quantity=Decimal(quantity) if quantity is not None else None,
        unit_price=Decimal(unit_price) if unit_price is not None else None,
        native_cash_delta=Decimal(native_cash_delta) if native_cash_delta is not None else None,
        fee=Decimal(fee),
        tax=Decimal(tax),
        target_currency=target_currency,
        target_cash_delta=Decimal(target_cash_delta) if target_cash_delta is not None else None,
        fx_rate=Decimal(fx_rate) if fx_rate is not None else None,
        source="fixture",
        metadata=metadata,
    )


def _all_entry_types() -> tuple[LedgerEntry, ...]:
    mu = Symbol.parse("MU", market=Market.US)
    return (
        _entry(
            "opening",
            LedgerEntryType.OPENING_POSITION,
            sequence=0,
            symbol=mu,
            quantity="1",
            unit_price="100",
        ),
        _entry(
            "buy",
            LedgerEntryType.BUY,
            sequence=1,
            symbol=mu,
            quantity="1",
            unit_price="10",
            fee="1",
        ),
        _entry(
            "sell",
            LedgerEntryType.SELL,
            sequence=2,
            symbol=mu,
            quantity="1",
            unit_price="11",
            fee="1",
        ),
        _entry("deposit", LedgerEntryType.CASH_DEPOSIT, sequence=3, native_cash_delta="50"),
        _entry("withdraw", LedgerEntryType.CASH_WITHDRAWAL, sequence=4, native_cash_delta="-5"),
        _entry(
            "dividend",
            LedgerEntryType.DIVIDEND,
            sequence=5,
            symbol=mu,
            native_cash_delta="2",
            tax="1",
        ),
        _entry("fee", LedgerEntryType.FEE, sequence=6, native_cash_delta="-1", fee="1"),
        _entry("tax", LedgerEntryType.TAX, sequence=7, native_cash_delta="-1", tax="1"),
        _entry(
            "fx",
            LedgerEntryType.FX_CONVERSION,
            sequence=8,
            native_cash_delta="-101",
            fee="1",
            target_currency="TWD",
            target_cash_delta="3200",
            fx_rate="32",
            metadata=(("provider", "fixture"), ("kind", "fx")),
        ),
    )


def test_roundtrip_preserves_all_entry_types_exact_values_and_canonical_identity(tmp_path) -> None:
    repository = LedgerRepository(tmp_path / "ledger.sqlite")
    entries = _all_entry_types()

    result = repository.append_entries(entries)
    restored = LedgerRepository(repository.database_path).load_entries()

    assert result.inserted == len(entries)
    assert restored == entries
    fx = next(entry for entry in restored if entry.entry_id == "fx")
    assert fx.fee == Decimal("1")
    assert fx.effective_at.tzinfo is UTC
    assert fx.target_currency == "TWD"
    assert fx.metadata == (("kind", "fx"), ("provider", "fixture"))
    assert restored[0].symbol == Symbol.parse("MU", market=Market.US)


def test_equivalent_metadata_serializes_deterministically(tmp_path) -> None:
    repository = LedgerRepository(tmp_path / "ledger.sqlite")
    first = _entry(
        "metadata",
        LedgerEntryType.CASH_DEPOSIT,
        sequence=0,
        native_cash_delta="1.00000000000000000001",
        metadata=(("z", "last"), ("a", "first")),
    )
    same_payload = _entry(
        "metadata",
        LedgerEntryType.CASH_DEPOSIT,
        sequence=0,
        native_cash_delta="1.00000000000000000001",
        metadata=(("a", "first"), ("z", "last")),
    )

    first_result = repository.append_entries((first,))
    second_result = repository.append_entries((same_payload,))

    assert first_result.inserted == 1
    assert second_result == type(second_result)(inserted=0, unchanged=1, entry_ids=("metadata",))
    assert repository.load_entries()[0].native_cash_delta == Decimal("1.00000000000000000001")


def test_entries_load_in_effective_at_sequence_and_entry_id_order(tmp_path) -> None:
    repository = LedgerRepository(tmp_path / "ledger.sqlite")
    timestamp = datetime(2026, 7, 22, 9, tzinfo=UTC)
    entries = (
        _entry(
            "b",
            LedgerEntryType.CASH_DEPOSIT,
            sequence=2,
            effective_at=timestamp,
            native_cash_delta="1",
        ),
        _entry(
            "a",
            LedgerEntryType.CASH_DEPOSIT,
            sequence=2,
            effective_at=timestamp,
            native_cash_delta="1",
        ),
        _entry(
            "later",
            LedgerEntryType.CASH_DEPOSIT,
            sequence=0,
            effective_at=timestamp + timedelta(days=1),
            native_cash_delta="1",
        ),
        _entry(
            "first",
            LedgerEntryType.CASH_DEPOSIT,
            sequence=1,
            effective_at=timestamp,
            native_cash_delta="1",
        ),
    )

    repository.append_entries(entries)

    assert [entry.entry_id for entry in repository.load_entries()] == ["first", "a", "b", "later"]


def test_identical_entry_id_and_payload_is_idempotent_but_conflict_rolls_back_batch(
    tmp_path,
) -> None:
    repository = LedgerRepository(tmp_path / "ledger.sqlite")
    original = _entry("same", LedgerEntryType.CASH_DEPOSIT, sequence=1, native_cash_delta="10")
    repository.append_entries((original,))

    unchanged = repository.append_entries((original,))
    conflicting = _entry("same", LedgerEntryType.CASH_DEPOSIT, sequence=1, native_cash_delta="20")
    new_entry = _entry("new", LedgerEntryType.CASH_DEPOSIT, sequence=2, native_cash_delta="1")

    assert unchanged.inserted == 0
    assert unchanged.unchanged == 1
    with pytest.raises(LedgerAccountingConflictError, match="entry_id conflict"):
        repository.append_entries((new_entry, conflicting))
    assert repository.load_entries() == (original,)


def test_persisted_replay_matches_in_memory_and_fx_fee_cash_legs(tmp_path) -> None:
    repository = LedgerRepository(tmp_path / "ledger.sqlite")
    entries = (
        _entry("usd", LedgerEntryType.CASH_DEPOSIT, sequence=0, native_cash_delta="101"),
        _entry(
            "fx",
            LedgerEntryType.FX_CONVERSION,
            sequence=1,
            native_cash_delta="-101",
            fee="1",
            target_currency="TWD",
            target_cash_delta="3200",
            fx_rate="32",
        ),
    )
    repository.append_entries(entries)

    persisted = replay_ledger(repository.load_entries())

    assert persisted == replay_ledger(entries)
    assert persisted.cash_balance("USD") == Decimal("0")
    assert persisted.cash_balance("TWD") == Decimal("3200")
    assert persisted.fees_paid("USD") == Decimal("1")


def test_corrupt_payload_and_unsupported_schema_fail_closed(tmp_path) -> None:
    database = tmp_path / "ledger.sqlite"
    repository = LedgerRepository(database)
    repository.append_entries(
        (_entry("safe", LedgerEntryType.CASH_DEPOSIT, sequence=0, native_cash_delta="1"),)
    )
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE portfolio_ledger_entries SET payload_json = ?", ("{bad-json",))

    with pytest.raises(LedgerRepositoryError, match="corrupted"):
        LedgerRepository(database).load_entries()

    illegal_enum = tmp_path / "illegal-enum.sqlite"
    illegal_repository = LedgerRepository(illegal_enum)
    illegal_repository.append_entries(
        (_entry("safe", LedgerEntryType.CASH_DEPOSIT, sequence=0, native_cash_delta="1"),)
    )
    with sqlite3.connect(illegal_enum) as connection:
        payload = (
            connection.execute(
                "SELECT payload_json FROM portfolio_ledger_entries WHERE entry_id = ?", ("safe",)
            )
            .fetchone()[0]
            .replace("cash_deposit", "not_a_real_entry")
        )
        connection.execute(
            "UPDATE portfolio_ledger_entries SET payload_json = ?, payload_sha256 = ? WHERE entry_id = ?",
            (payload, "0" * 64, "safe"),
        )
    with pytest.raises(LedgerRepositoryError, match="invalid|corrupted"):
        LedgerRepository(illegal_enum).load_entries()

    unsupported = tmp_path / "unsupported.sqlite"
    LedgerRepository(unsupported).initialize()
    with sqlite3.connect(unsupported) as connection:
        connection.execute("UPDATE ledger_schema SET schema_version = 2")
    with pytest.raises(LedgerSchemaError, match="unsupported"):
        LedgerRepository(unsupported).load_entries()


def test_parameterized_sql_handles_literal_quote_without_injection(tmp_path) -> None:
    repository = LedgerRepository(tmp_path / "ledger.sqlite")
    entry = _entry("quote-'?", LedgerEntryType.CASH_DEPOSIT, sequence=0, native_cash_delta="1")

    repository.append_entries((entry,))

    assert repository.load_entries() == (entry,)


def test_blank_fx_target_is_rejected_before_repository_write(tmp_path) -> None:
    repository = LedgerRepository(tmp_path / "ledger.sqlite")

    with pytest.raises(ValueError, match="target_currency"):
        _entry(
            "invalid-fx",
            LedgerEntryType.FX_CONVERSION,
            sequence=0,
            native_cash_delta="-101",
            fee="1",
            target_currency="\t",
            target_cash_delta="3200",
            fx_rate="32",
        )

    assert not repository.database_path.exists()
