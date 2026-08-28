from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd

from stock_tool.application.portfolio import PortfolioLedgerService
from stock_tool.portfolio.ledger import LedgerEntry, LedgerEntryType, replay_ledger
from stock_tool.portfolio.ledger_repository import LedgerRepository
from stock_tool.runtime_paths import RuntimePaths


def _deposit(entry_id: str, amount: str = "10") -> LedgerEntry:
    return LedgerEntry(
        entry_id=entry_id,
        entry_type=LedgerEntryType.CASH_DEPOSIT,
        effective_at=datetime(2026, 7, 22, tzinfo=UTC),
        sequence=0,
        currency="USD",
        native_cash_delta=Decimal(amount),
        source="fixture",
    )


def _legacy_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "2330",
                "market": "TWSE",
                "currency": "TWD",
                "quantity": "2",
                "average_cost": "600",
            },
            {
                "symbol": "MU",
                "market": "US",
                "currency": "USD",
                "quantity": "1",
                "average_cost": "100",
            },
            {
                "symbol": "BAD",
                "market": "UNKNOWN",
                "currency": "USD",
                "quantity": "1",
                "average_cost": "10",
            },
        ]
    )


def test_preview_is_read_only_and_explicit_bootstrap_is_idempotent(tmp_path) -> None:
    database = tmp_path / "ledger.sqlite"
    service = PortfolioLedgerService(repository=LedgerRepository(database))
    frame = _legacy_frame()

    preview = service.preview_legacy_frame(frame)

    assert not database.exists()
    assert len(preview.entries) == 2
    assert len(preview.missing_data) == 1

    first = service.bootstrap_legacy_entries(frame)
    second = service.bootstrap_legacy_entries(frame)

    assert first.append_result.inserted == 2
    assert second.append_result.inserted == 0
    assert second.append_result.unchanged == 2
    assert first.snapshot == second.snapshot
    assert service.replay_persisted() == replay_ledger(preview.entries)


def test_preview_and_bootstrap_do_not_modify_original_csv(tmp_path) -> None:
    source = tmp_path / "portfolio.csv"
    source.write_text(
        "symbol,market,currency,quantity,average_cost\n2330,TWSE,TWD,2,600\n",
        encoding="utf-8",
    )
    before = source.read_bytes()
    service = PortfolioLedgerService(repository=LedgerRepository(tmp_path / "ledger.sqlite"))

    preview = service.preview_legacy_csv(source)
    outcome = service.bootstrap_legacy_entries(pd.read_csv(source, dtype=str))

    assert len(preview.entries) == 1
    assert outcome.snapshot.position_count == 1
    assert source.read_bytes() == before


def test_persisted_entries_reopen_and_replay_match_application_memory_replay(tmp_path) -> None:
    database = tmp_path / "ledger.sqlite"
    first = PortfolioLedgerService(repository=LedgerRepository(database))
    entries = (_deposit("deposit", "100"),)

    result = first.append_entries(entries)
    second = PortfolioLedgerService(repository=LedgerRepository(database))

    assert result.inserted == 1
    assert second.load_entries() == entries
    assert second.replay_persisted() == first.replay(entries)


def test_runtime_factory_uses_canonical_private_ledger_path_only_when_explicit(tmp_path) -> None:
    paths = RuntimePaths(tmp_path / "isolated-user-data")

    service = PortfolioLedgerService.from_runtime_paths(paths)

    assert (
        paths.ledger_database_file
        == tmp_path / "isolated-user-data" / "data" / "ledger" / "portfolio_ledger.sqlite"
    )
    assert not paths.ledger_database_file.exists()
    service.append_entries((_deposit("runtime"),))
    assert paths.ledger_database_file.exists()
