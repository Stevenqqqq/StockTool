"""Append-only SQLite persistence for immutable portfolio ledger entries."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any

from stock_tool.portfolio.ledger import LedgerEntry

LEDGER_SCHEMA_VERSION = 1
_SCHEMA_TABLE = "ledger_schema"
_ENTRIES_TABLE = "portfolio_ledger_entries"
_REQUIRED_ENTRY_COLUMNS = frozenset(
    {
        "entry_id",
        "effective_at",
        "sequence",
        "symbol_code",
        "symbol_market",
        "entry_type",
        "currency",
        "target_currency",
        "payload_json",
        "payload_sha256",
    }
)


class LedgerRepositoryError(ValueError):
    """Raised when persisted ledger data cannot be safely used."""


class LedgerSchemaError(LedgerRepositoryError):
    """Raised when the dedicated ledger database has an unsupported schema."""


class LedgerAccountingConflictError(LedgerRepositoryError):
    """Raised when one immutable entry ID is reused with different accounting facts."""


@dataclass(frozen=True, slots=True)
class LedgerAppendResult:
    """Deterministic outcome of one all-or-nothing append request."""

    inserted: int
    unchanged: int
    entry_ids: tuple[str, ...]


class LedgerRepository:
    """Persist immutable entries without update, delete, or replay responsibilities."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        """Create the supported schema only for an empty dedicated ledger database."""

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                tables = _table_names(connection)
                if not tables:
                    _create_schema(connection)
                    return
                _validate_schema(connection, tables)
        except sqlite3.DatabaseError as exc:
            raise LedgerRepositoryError("Ledger database could not be initialized safely.") from exc

    def append_entries(self, entries: Sequence[LedgerEntry]) -> LedgerAppendResult:
        """Append an atomic batch, rejecting conflicting immutable entry IDs."""

        entries = tuple(entries)
        _validate_entry_batch(entries)
        self.initialize()
        inserted = 0
        unchanged = 0
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                _validate_schema(connection, _table_names(connection))
                for entry in entries:
                    payload_json, payload_hash = _canonical_payload(entry)
                    row = connection.execute(
                        f"SELECT payload_json, payload_sha256 FROM {_ENTRIES_TABLE} WHERE entry_id = ?",
                        (entry.entry_id,),
                    ).fetchone()
                    if row is None:
                        connection.execute(
                            f"""
                            INSERT INTO {_ENTRIES_TABLE} (
                                entry_id, effective_at, sequence, symbol_code, symbol_market,
                                entry_type, currency, target_currency, payload_json, payload_sha256
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            _entry_values(entry, payload_json, payload_hash),
                        )
                        inserted += 1
                    elif (
                        row["payload_sha256"] == payload_hash
                        and row["payload_json"] == payload_json
                    ):
                        unchanged += 1
                    else:
                        raise LedgerAccountingConflictError(
                            f"Ledger entry_id conflict for immutable entry: {entry.entry_id}"
                        )
        except LedgerRepositoryError:
            raise
        except sqlite3.DatabaseError as exc:
            raise LedgerRepositoryError("Ledger entry batch could not be saved safely.") from exc
        return LedgerAppendResult(
            inserted=inserted,
            unchanged=unchanged,
            entry_ids=tuple(entry.entry_id for entry in entries),
        )

    def load_entries(self) -> tuple[LedgerEntry, ...]:
        """Load and revalidate entries in deterministic replay order."""

        self.initialize()
        try:
            with self._connection() as connection:
                _validate_schema(connection, _table_names(connection))
                rows = connection.execute(f"""
                    SELECT entry_id, effective_at, sequence, symbol_code, symbol_market,
                           entry_type, currency, target_currency, payload_json, payload_sha256
                    FROM {_ENTRIES_TABLE}
                    ORDER BY effective_at ASC, sequence ASC, entry_id ASC
                    """).fetchall()
        except LedgerRepositoryError:
            raise
        except sqlite3.DatabaseError as exc:
            raise LedgerRepositoryError("Ledger entries could not be loaded safely.") from exc
        return tuple(_entry_from_row(row) for row in rows)

    def count_entries(self) -> int:
        """Return the persisted entry count for diagnostics and non-destructive tests."""

        self.initialize()
        try:
            with self._connection() as connection:
                _validate_schema(connection, _table_names(connection))
                row = connection.execute(
                    f"SELECT COUNT(*) AS count FROM {_ENTRIES_TABLE}"
                ).fetchone()
        except LedgerRepositoryError:
            raise
        except sqlite3.DatabaseError as exc:
            raise LedgerRepositoryError("Ledger entry count could not be loaded safely.") from exc
        return int(row["count"] if row is not None else 0)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Provide commit/rollback/close semantics for the private ledger database."""

        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(f"""
        CREATE TABLE {_SCHEMA_TABLE} (
            schema_key TEXT PRIMARY KEY CHECK (schema_key = 'version'),
            schema_version INTEGER NOT NULL
        )
        """)
    connection.execute(f"""
        CREATE TABLE {_ENTRIES_TABLE} (
            entry_id TEXT PRIMARY KEY,
            effective_at TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            symbol_code TEXT,
            symbol_market TEXT,
            entry_type TEXT NOT NULL,
            currency TEXT NOT NULL,
            target_currency TEXT,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL
        )
        """)
    connection.execute(f"""
        CREATE INDEX idx_portfolio_ledger_entries_replay
        ON {_ENTRIES_TABLE} (effective_at, sequence, entry_id)
        """)
    connection.execute(
        f"INSERT INTO {_SCHEMA_TABLE} (schema_key, schema_version) VALUES ('version', ?)",
        (LEDGER_SCHEMA_VERSION,),
    )


def _validate_schema(connection: sqlite3.Connection, tables: frozenset[str]) -> None:
    if _SCHEMA_TABLE not in tables or _ENTRIES_TABLE not in tables:
        raise LedgerSchemaError("Ledger database has no supported schema version.")
    version_rows = connection.execute(
        f"SELECT schema_version FROM {_SCHEMA_TABLE} WHERE schema_key = 'version'"
    ).fetchall()
    if len(version_rows) != 1:
        raise LedgerSchemaError("Ledger database schema version is invalid.")
    try:
        version = int(version_rows[0]["schema_version"])
    except (TypeError, ValueError) as exc:
        raise LedgerSchemaError("Ledger database schema version is invalid.") from exc
    if version != LEDGER_SCHEMA_VERSION:
        raise LedgerSchemaError(
            f"Ledger database schema version {version} is unsupported; expected {LEDGER_SCHEMA_VERSION}."
        )
    columns = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({_ENTRIES_TABLE})").fetchall()
    }
    if not _REQUIRED_ENTRY_COLUMNS.issubset(columns):
        raise LedgerSchemaError("Ledger entries table does not match the supported schema.")


def _table_names(connection: sqlite3.Connection) -> frozenset[str]:
    return frozenset(
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    )


def _validate_entry_batch(entries: tuple[LedgerEntry, ...]) -> None:
    payloads: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, LedgerEntry):
            raise TypeError("Ledger repository accepts LedgerEntry values only.")
        payload_json, _ = _canonical_payload(entry)
        previous = payloads.setdefault(entry.entry_id, payload_json)
        if previous != payload_json:
            raise LedgerAccountingConflictError(
                f"Ledger entry_id conflict within append batch: {entry.entry_id}"
            )


def _canonical_payload(entry: LedgerEntry) -> tuple[str, str]:
    try:
        payload_json = json.dumps(
            entry.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LedgerRepositoryError(
            "Ledger entry payload cannot be canonically serialized."
        ) from exc
    return payload_json, sha256(payload_json.encode("utf-8")).hexdigest()


def _entry_values(entry: LedgerEntry, payload_json: str, payload_hash: str) -> tuple[Any, ...]:
    return (
        entry.entry_id,
        entry.effective_at.isoformat(),
        entry.sequence,
        entry.symbol.code if entry.symbol is not None else None,
        entry.symbol.market.value if entry.symbol is not None else None,
        entry.entry_type.value,
        entry.currency,
        entry.target_currency,
        payload_json,
        payload_hash,
    )


def _entry_from_row(row: Mapping[str, Any]) -> LedgerEntry:
    entry_id = str(row["entry_id"])
    try:
        payload = json.loads(str(row["payload_json"]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise LedgerRepositoryError(
            f"Stored ledger entry {entry_id} payload is corrupted."
        ) from exc
    if not isinstance(payload, Mapping):
        raise LedgerRepositoryError(f"Stored ledger entry {entry_id} payload is corrupted.")
    try:
        entry = LedgerEntry.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise LedgerRepositoryError(f"Stored ledger entry {entry_id} payload is invalid.") from exc
    payload_json, payload_hash = _canonical_payload(entry)
    if str(row["payload_json"]) != payload_json or str(row["payload_sha256"]) != payload_hash:
        raise LedgerRepositoryError(f"Stored ledger entry {entry_id} payload is corrupted.")
    symbol_code = entry.symbol.code if entry.symbol is not None else None
    symbol_market = entry.symbol.market.value if entry.symbol is not None else None
    expected = (
        entry.entry_id,
        entry.effective_at.isoformat(),
        entry.sequence,
        symbol_code,
        symbol_market,
        entry.entry_type.value,
        entry.currency,
        entry.target_currency,
    )
    actual = tuple(
        row[name]
        for name in (
            "entry_id",
            "effective_at",
            "sequence",
            "symbol_code",
            "symbol_market",
            "entry_type",
            "currency",
            "target_currency",
        )
    )
    if actual != expected:
        raise LedgerRepositoryError(
            f"Stored ledger entry {entry_id} identity metadata is corrupted."
        )
    return entry
