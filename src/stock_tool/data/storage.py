"""SQLite storage for canonical OHLCV rows and redacted ingestion lineage."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence
from uuid import uuid4

from stock_tool.data.contracts import sanitize_provider_text
from stock_tool.domain.models import Market, Symbol


class MigrationError(RuntimeError):
    """Raised when an additive SQLite migration fails and its backup is restored."""


class PriceIdentityMetadataError(ValueError):
    """Raised when market-qualified price sidecar metadata is unsafe or malformed."""


@dataclass(frozen=True, slots=True)
class PersistedPriceProvenance:
    """Market-qualified, non-sensitive provenance for one persisted price identity."""

    symbol: Symbol
    provider: str | None
    provider_symbol: str | None
    source_type: str | None
    last_data_date: str | None
    checked_at: str | None
    fetched_at: str | None = None
    payload_sha256: str | None = None

    def __post_init__(self) -> None:
        """Reject unresolved identity metadata instead of silently guessing a market."""

        if self.symbol.market not in {Market.TWSE, Market.TPEX, Market.US}:
            raise PriceIdentityMetadataError(
                "Persisted market-qualified price data requires TWSE, TPEX, or US."
            )
        object.__setattr__(self, "provider", _safe_optional_text(self.provider))
        object.__setattr__(self, "provider_symbol", _safe_optional_text(self.provider_symbol))
        object.__setattr__(self, "source_type", _safe_optional_text(self.source_type))
        object.__setattr__(self, "last_data_date", _normalize_optional_date(self.last_data_date))
        object.__setattr__(self, "checked_at", _normalize_optional_timestamp(self.checked_at))
        object.__setattr__(self, "fetched_at", _normalize_optional_timestamp(self.fetched_at))
        payload_hash = self.payload_sha256
        if payload_hash is not None:
            payload_hash = str(payload_hash).strip().lower()
            if len(payload_hash) != 64 or any(
                char not in "0123456789abcdef" for char in payload_hash
            ):
                raise PriceIdentityMetadataError("Price sidecar payload hash is invalid.")
        object.__setattr__(self, "payload_sha256", payload_hash)

    def to_dict(self) -> dict[str, str | None]:
        """Serialize safe, provider-neutral identity metadata for the sidecar."""

        return {
            "symbol": self.symbol.code,
            "market": self.symbol.market.value,
            "provider": self.provider,
            "provider_symbol": self.provider_symbol,
            "source_type": self.source_type,
            "last_data_date": self.last_data_date,
            "checked_at": self.checked_at,
            "fetched_at": self.fetched_at,
            "payload_sha256": self.payload_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PersistedPriceProvenance:
        """Deserialize a sidecar entry while retaining strict market identity validation."""

        try:
            symbol = Symbol.parse(str(payload["symbol"]), market=str(payload["market"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise PriceIdentityMetadataError("Price sidecar identity is invalid.") from exc
        return cls(
            symbol=symbol,
            provider=_mapping_optional_text(payload, "provider"),
            provider_symbol=_mapping_optional_text(payload, "provider_symbol"),
            source_type=_mapping_optional_text(payload, "source_type"),
            last_data_date=_mapping_optional_text(payload, "last_data_date"),
            checked_at=_mapping_optional_text(payload, "checked_at"),
            fetched_at=_mapping_optional_text(payload, "fetched_at"),
            payload_sha256=_mapping_optional_text(payload, "payload_sha256"),
        )


@dataclass(frozen=True, slots=True)
class MarketQualifiedPriceContext:
    """Safe sidecar records and diagnostics available after an application restart."""

    records: tuple[dict[str, Any], ...]
    provenance: tuple[PersistedPriceProvenance, ...]
    warnings: tuple[str, ...] = ()


class SQLitePriceStorage:
    """Persist canonical OHLCV records and additive ingestion-run metadata."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.last_migration_backup: Path | None = None

    @property
    def price_identity_sidecar_path(self) -> Path:
        """Return the additive sidecar path without changing the legacy prices schema."""

        return self.database_path.with_name(f"{self.database_path.stem}.price_identity.json")

    def initialize(self) -> None:
        """Create the original price table and apply repeat-safe additive migrations."""

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.last_migration_backup = None
        backup_path: Path | None = None
        migration_started = False
        pending: tuple[Path, ...] = ()
        try:
            with self._connection() as connection:
                # One lock covers backup eligibility, pending-migration discovery, and writes.
                # A second initializer therefore observes the first initializer's committed state.
                connection.execute("BEGIN IMMEDIATE")
                has_existing_tables = _connection_has_tables(connection)
                _validate_existing_base_schema(connection)
                needs_base_schema = _base_schema_needs_creation(connection)
                pending = self._pending_migration_paths_for_connection(connection)
                if has_existing_tables and (needs_base_schema or pending):
                    backup_path = self._create_migration_backup()
                    self.last_migration_backup = backup_path

                if needs_base_schema:
                    migration_started = True
                    _ensure_base_schema(connection)

                # Re-check after the write lock and base-schema preparation. This avoids using a
                # stale pending list computed by a concurrent initializer.
                pending = self._pending_migration_paths_for_connection(connection)
                for migration_path in pending:
                    migration_started = True
                    _execute_migration_script(connection, migration_path)
                    connection.execute(
                        "INSERT INTO schema_migrations (version) VALUES (?)",
                        (migration_path.stem,),
                    )
        except Exception as exc:
            if backup_path is not None:
                try:
                    self._restore_backup_snapshot(backup_path)
                except Exception as restore_exc:
                    raise MigrationError(
                        "Additive SQLite migration failed and the pre-migration backup "
                        "could not be restored."
                    ) from restore_exc
                failed_versions = ", ".join(path.stem for path in pending)
                raise MigrationError(
                    f"Additive SQLite migration failed ({failed_versions}); "
                    "the pre-migration backup was restored."
                ) from exc
            if isinstance(exc, MigrationError) or not migration_started:
                raise
            failed_versions = ", ".join(path.stem for path in pending)
            raise MigrationError(
                f"Additive SQLite migration failed ({failed_versions}); "
                "the transaction was rolled back."
            ) from exc

    def save_price_data(self, records: list[dict[str, Any]]) -> int:
        """Upsert standardized price records and return the submitted row count."""

        self.initialize()
        rows = [
            (
                record["date"],
                record["symbol"],
                record["open"],
                record["high"],
                record["low"],
                record["close"],
                record["volume"],
                record.get("adjusted_close"),
            )
            for record in records
        ]

        with self._connection() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO prices (
                    date, symbol, open, high, low, close, volume, adjusted_close
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def save_market_qualified_price_data(
        self,
        records: list[dict[str, Any]],
        *,
        provenance: PersistedPriceProvenance,
    ) -> int:
        """Persist one explicit market identity in an atomic companion sidecar.

        The legacy SQLite table is retained for compatibility. The sidecar is
        the only persistence path used for market-qualified restart valuation,
        so duplicate tickers in different markets cannot collide.
        """

        normalized_records = _normalize_market_qualified_records(records, provenance.symbol)
        self.save_price_data(normalized_records)
        payload, warnings = self._read_price_identity_sidecar()
        if warnings:
            raise PriceIdentityMetadataError(warnings[0])
        entries = payload["entries"]
        entries[provenance.symbol.canonical] = {
            "provenance": provenance.to_dict(),
            "records": normalized_records,
        }
        self._write_price_identity_sidecar(payload)
        return len(normalized_records)

    def save_market_qualified_price_batch(
        self,
        entries: Sequence[tuple[list[dict[str, Any]], PersistedPriceProvenance]],
    ) -> int:
        """Publish several market identities as one all-or-nothing update.

        Benchmark refreshes are a single evidence set: a successful TWSE row
        must not become visible while TPEX or US is still old.  All records
        are validated before any write, SQLite rows are committed together,
        and the companion sidecar is replaced only after that commit.  If the
        sidecar publish fails, the exact pre-call SQLite/sidecar bytes are
        restored so a reader can continue using the previous complete set.
        """

        if not entries:
            raise PriceIdentityMetadataError("Price batch must not be empty.")
        normalized_entries: list[tuple[list[dict[str, Any]], PersistedPriceProvenance]] = []
        seen: set[str] = set()
        for records, provenance in entries:
            if provenance.symbol.canonical in seen:
                raise PriceIdentityMetadataError("Price batch contains duplicate identities.")
            seen.add(provenance.symbol.canonical)
            normalized_entries.append(
                (_normalize_market_qualified_records(records, provenance.symbol), provenance)
            )

        self.initialize()
        database_existed = self.database_path.exists()
        database_before = self.database_path.read_bytes() if database_existed else None
        sidecar_path = self.price_identity_sidecar_path
        sidecar_existed = sidecar_path.exists()
        sidecar_before = sidecar_path.read_bytes() if sidecar_existed else None
        try:
            with self._connection() as connection:
                for records, _provenance in normalized_entries:
                    connection.executemany(
                        """
                        INSERT OR REPLACE INTO prices (
                            date, symbol, open, high, low, close, volume, adjusted_close
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                record["date"],
                                record["symbol"],
                                record["open"],
                                record["high"],
                                record["low"],
                                record["close"],
                                record["volume"],
                                record.get("adjusted_close"),
                            )
                            for record in records
                        ],
                    )
            payload, warnings = self._read_price_identity_sidecar()
            if warnings:
                raise PriceIdentityMetadataError(warnings[0])
            entries_payload = payload["entries"]
            for records, provenance in normalized_entries:
                entries_payload[provenance.symbol.canonical] = {
                    "provenance": provenance.to_dict(),
                    "records": records,
                }
            self._write_price_identity_sidecar(payload)
            return sum(len(records) for records, _ in normalized_entries)
        except Exception:
            # Restore only the files touched by this invocation.  Restoration
            # is deliberately byte-for-byte and never scans or removes an
            # unrelated path.
            try:
                if database_before is None:
                    if self.database_path.exists():
                        self.database_path.unlink()
                else:
                    self.database_path.write_bytes(database_before)
                if sidecar_before is None:
                    if sidecar_path.exists():
                        sidecar_path.unlink()
                else:
                    sidecar_path.write_bytes(sidecar_before)
            except OSError:
                # Preserve the original failure while making the inability to
                # restore explicit to the caller.
                raise
            raise

    def load_market_qualified_price_context(self) -> MarketQualifiedPriceContext:
        """Load validated market-qualified rows without accepting corrupt sidecar metadata."""

        payload, warnings = self._read_price_identity_sidecar()
        if warnings:
            return MarketQualifiedPriceContext(records=(), provenance=(), warnings=warnings)

        records: list[dict[str, Any]] = []
        provenance_rows: list[PersistedPriceProvenance] = []
        try:
            for canonical, entry in sorted(payload["entries"].items()):
                if not isinstance(entry, Mapping):
                    raise PriceIdentityMetadataError("Price sidecar entry is invalid.")
                raw_provenance = entry.get("provenance")
                raw_records = entry.get("records")
                if not isinstance(raw_provenance, Mapping) or not isinstance(raw_records, list):
                    raise PriceIdentityMetadataError("Price sidecar entry is incomplete.")
                provenance = PersistedPriceProvenance.from_dict(raw_provenance)
                if canonical != provenance.symbol.canonical:
                    raise PriceIdentityMetadataError(
                        "Price sidecar identity key does not match metadata."
                    )
                normalized = _normalize_market_qualified_records(raw_records, provenance.symbol)
                provenance_rows.append(provenance)
                for record in normalized:
                    records.append(
                        {
                            **record,
                            "market": provenance.symbol.market.value,
                            "provider": provenance.provider,
                            "provider_symbol": provenance.provider_symbol,
                            "source_type": provenance.source_type,
                            "last_data_date": provenance.last_data_date,
                            "checked_at": provenance.checked_at,
                            "fetched_at": provenance.fetched_at,
                            "payload_sha256": provenance.payload_sha256,
                        }
                    )
            return MarketQualifiedPriceContext(
                records=tuple(records), provenance=tuple(provenance_rows)
            )
        except (TypeError, ValueError, PriceIdentityMetadataError):
            return MarketQualifiedPriceContext(
                records=(),
                provenance=(),
                warnings=(
                    "市場別價格 metadata 無法安全讀取；已保留 SQLite 原始資料但不會用於市場別估值。",
                ),
            )

    def _read_price_identity_sidecar(self) -> tuple[dict[str, Any], tuple[str, ...]]:
        """Read a validated sidecar payload without falling back to inferred identity."""

        path = self.price_identity_sidecar_path
        if not path.exists():
            return {"schema_version": 1, "entries": {}}, ()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(raw, dict)
                or raw.get("schema_version") != 1
                or not isinstance(raw.get("entries"), dict)
            ):
                raise PriceIdentityMetadataError("Price sidecar format is not supported.")
            return raw, ()
        except (OSError, json.JSONDecodeError, PriceIdentityMetadataError):
            return (
                {"schema_version": 1, "entries": {}},
                ("市場別價格 metadata 無法安全讀取；已保留 SQLite 原始資料但不會用於市場別估值。",),
            )

    def _write_price_identity_sidecar(self, payload: Mapping[str, Any]) -> None:
        """Atomically replace only the companion sidecar after complete validation."""

        path = self.price_identity_sidecar_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def load_price_data(
        self,
        *,
        symbol: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Load price records from SQLite with optional parameterized filters."""

        self.initialize()
        query = (
            "SELECT date, symbol, open, high, low, close, volume, adjusted_close "
            "FROM prices WHERE 1 = 1"
        )
        params: list[Any] = []

        if symbol is not None:
            query += " AND symbol = ?"
            params.append(symbol)
        if start_date is not None:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date is not None:
            query += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY symbol, date"
        with self._connection() as connection:
            cursor = connection.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def count_price_rows(self) -> int:
        """Return the number of rows stored in the original price table."""

        self.initialize()
        with self._connection() as connection:
            cursor = connection.execute("SELECT COUNT(*) AS count FROM prices")
            row = cursor.fetchone()
            return int(row["count"])

    def record_ingestion_run(self, record: Mapping[str, Any]) -> None:
        """Persist a redacted ingestion record without raw payloads or stack traces."""

        self.initialize()
        normalized = _normalize_ingestion_record(record)
        with self._connection() as connection:
            if not _table_exists(connection, "ingestion_runs"):
                raise RuntimeError("The ingestion_runs migration is currently rolled back.")
            connection.execute(
                """
                INSERT INTO ingestion_runs (
                    run_id, started_at, completed_at, requested_symbol_json, resolved_symbol_json,
                    provider_symbol, provider, source_type, request_start, request_end, cache_hit,
                    status, input_rows, output_rows, quality_summary_json, warnings_json, errors_json,
                    attempts_json, last_data_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    completed_at = excluded.completed_at,
                    requested_symbol_json = excluded.requested_symbol_json,
                    resolved_symbol_json = excluded.resolved_symbol_json,
                    provider_symbol = excluded.provider_symbol,
                    provider = excluded.provider,
                    source_type = excluded.source_type,
                    request_start = excluded.request_start,
                    request_end = excluded.request_end,
                    cache_hit = excluded.cache_hit,
                    status = excluded.status,
                    input_rows = excluded.input_rows,
                    output_rows = excluded.output_rows,
                    quality_summary_json = excluded.quality_summary_json,
                    warnings_json = excluded.warnings_json,
                    errors_json = excluded.errors_json,
                    attempts_json = excluded.attempts_json,
                    last_data_date = excluded.last_data_date
                """,
                normalized,
            )

    def list_ingestion_runs(self) -> list[dict[str, Any]]:
        """Return lineage records, or an empty list when its migration was rolled back."""

        self.initialize()
        with self._connection() as connection:
            if not _table_exists(connection, "ingestion_runs"):
                return []
            rows = connection.execute("""
                SELECT run_id, started_at, completed_at, requested_symbol_json, resolved_symbol_json,
                       provider_symbol, provider, source_type, request_start, request_end, cache_hit,
                       status, input_rows, output_rows, quality_summary_json, warnings_json, errors_json,
                       attempts_json, last_data_date
                FROM ingestion_runs
                ORDER BY completed_at DESC, run_id DESC
                """).fetchall()
        return [_deserialize_ingestion_row(row) for row in rows]

    def applied_migrations(self) -> tuple[str, ...]:
        """Return ordered migration versions applied to this database."""

        self.initialize()
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT version FROM schema_migrations "
                "WHERE version NOT LIKE '%.rolled_back' ORDER BY version"
            ).fetchall()
        return tuple(str(row["version"]) for row in rows)

    def schema_version(self) -> str | None:
        """Return the latest applied additive schema version, if one exists."""

        migrations = self.applied_migrations()
        return migrations[-1] if migrations else None

    @contextmanager
    def repository_connection(self) -> Iterator[sqlite3.Connection]:
        """Provide initialized, transaction-safe access for data repositories only."""

        self.initialize()
        with self._connection() as connection:
            yield connection

    def backup_database(self, destination: str | Path) -> Path:
        """Create a SQLite backup that can restore pre-migration state without data loss."""

        self.initialize()
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.resolve() == self.database_path.resolve():
            raise ValueError("Backup destination must differ from the active database path.")
        if destination_path.exists():
            destination_path.unlink()
        with self._connection() as source, self._connection_at(destination_path) as target:
            source.backup(target)
        return destination_path

    def restore_database(self, backup_path: str | Path) -> None:
        """Restore a caller-supplied SQLite backup using SQLite's backup API."""

        source_path = Path(backup_path)
        if not source_path.is_file():
            raise FileNotFoundError(f"SQLite backup was not found: {source_path}")
        if source_path.resolve() == self.database_path.resolve():
            raise ValueError("Backup path must differ from the active database path.")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection_at(source_path) as source, self._connection() as target:
            source.backup(target)

    def rollback_ingestion_runs_migration(self) -> None:
        """Remove lineage metadata and persist a marker preventing automatic re-application."""

        self.initialize()
        rollback_path = self._migration_directory() / "001_ingestion_runs.down.sql"
        with self._connection() as connection:
            connection.executescript(rollback_path.read_text(encoding="utf-8"))
            connection.execute(
                "DELETE FROM schema_migrations WHERE version = ?", ("001_ingestion_runs",)
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                ("001_ingestion_runs.rolled_back",),
            )

    def _pending_migration_paths(self) -> tuple[Path, ...]:
        """Return current pending migrations for diagnostic callers outside initialization."""

        with self._connection() as connection:
            return self._pending_migration_paths_for_connection(connection)

    def _pending_migration_paths_for_connection(
        self, connection: sqlite3.Connection
    ) -> tuple[Path, ...]:
        """Return pending migrations using the caller's current locked SQLite snapshot."""

        applied = _applied_migration_versions(connection)
        return tuple(
            migration_path
            for migration_path in self._migration_paths()
            if migration_path.stem not in applied
            and f"{migration_path.stem}.rolled_back" not in applied
        )

    def _migration_paths(self) -> tuple[Path, ...]:
        """Return ordered additive migration scripts; intended for test-only injection."""

        return tuple(
            path
            for path in sorted(self._migration_directory().glob("[0-9][0-9][0-9]_*.sql"))
            if not path.name.endswith(".down.sql")
        )

    def _create_migration_backup(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        base_name = f"{self.database_path.stem}.pre-migration-{timestamp}"
        backup_path = self.database_path.with_name(f"{base_name}{self.database_path.suffix}")
        sequence = 1
        while backup_path.exists():
            backup_path = self.database_path.with_name(
                f"{base_name}-{sequence}{self.database_path.suffix}"
            )
            sequence += 1
        with (
            self._connection_at(self.database_path) as source,
            self._connection_at(backup_path) as target,
        ):
            source.backup(target)
        return backup_path

    def _restore_backup_snapshot(self, backup_path: Path) -> None:
        with self._connection_at(backup_path) as source, self._connection() as target:
            source.backup(target)

    @staticmethod
    def _migration_directory() -> Path:
        return Path(__file__).resolve().parent / "migrations"

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Open, commit or roll back, and always close the active database connection."""

        with self._connection_at(self.database_path) as connection:
            yield connection

    @staticmethod
    @contextmanager
    def _connection_at(path: Path) -> Iterator[sqlite3.Connection]:
        """Provide one exception-safe SQLite connection for a specific database path."""

        connection = sqlite3.connect(path)
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


_MARKET_QUALIFIED_PRICE_COLUMNS = (
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adjusted_close",
)


def _normalize_market_qualified_records(
    records: list[dict[str, Any]],
    symbol: Symbol,
) -> list[dict[str, Any]]:
    """Validate one explicit identity's OHLCV rows before they enter the sidecar."""

    if not records:
        raise PriceIdentityMetadataError(
            "Market-qualified price sidecar records must not be empty."
        )
    normalized: list[dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, Mapping):
            raise PriceIdentityMetadataError("Market-qualified price sidecar row is invalid.")
        missing = [column for column in _MARKET_QUALIFIED_PRICE_COLUMNS if column not in raw]
        if missing:
            raise PriceIdentityMetadataError(
                "Market-qualified price sidecar row is missing " + ", ".join(missing) + "."
            )
        row_symbol = str(raw["symbol"]).strip().upper()
        if row_symbol != symbol.code:
            raise PriceIdentityMetadataError(
                "Market-qualified price sidecar row does not match its canonical symbol."
            )
        try:
            row_date = date.fromisoformat(str(raw["date"]))
            numeric = {
                column: float(raw[column]) for column in _MARKET_QUALIFIED_PRICE_COLUMNS[2:-1]
            }
            if not all(math.isfinite(value) for value in numeric.values()):
                raise PriceIdentityMetadataError(
                    "Market-qualified price sidecar row contains non-finite OHLCV data."
                )
            adjusted = raw["adjusted_close"]
            adjusted_close = None if adjusted is None else float(adjusted)
            if adjusted_close is not None and not math.isfinite(adjusted_close):
                adjusted_close = None
        except (TypeError, ValueError) as exc:
            raise PriceIdentityMetadataError(
                "Market-qualified price sidecar row contains invalid OHLCV data."
            ) from exc
        normalized_row: dict[str, Any] = {
            "date": row_date.isoformat(),
            "symbol": symbol.code,
            **numeric,
            "adjusted_close": adjusted_close,
        }
        if "payload_sha256" in raw and raw["payload_sha256"] is not None:
            payload_hash = str(raw["payload_sha256"]).strip().lower()
            if len(payload_hash) != 64 or any(
                char not in "0123456789abcdef" for char in payload_hash
            ):
                raise PriceIdentityMetadataError("Market-qualified row payload hash is invalid.")
            normalized_row["payload_sha256"] = payload_hash
        if "provider" in raw and raw["provider"] is not None:
            normalized_row["provider"] = _safe_optional_text(raw["provider"])
        if "corporate_action_required" in raw:
            required_action = raw["corporate_action_required"]
            if not isinstance(required_action, bool):
                raise PriceIdentityMetadataError("corporate_action_required must be boolean.")
            normalized_row["corporate_action_required"] = required_action
        if "corporate_action_evidence" in raw and raw["corporate_action_evidence"] is not None:
            normalized_row["corporate_action_evidence"] = _normalize_corporate_action_evidence(
                raw["corporate_action_evidence"]
            )
        if "corporate_action_coverage" in raw and raw["corporate_action_coverage"] is not None:
            normalized_row["corporate_action_coverage"] = _normalize_corporate_action_coverage(
                raw["corporate_action_coverage"]
            )
        normalized.append(normalized_row)
    by_date = {str(row["date"]): row for row in normalized}
    return [by_date[key] for key in sorted(by_date)]


def _normalize_corporate_action_evidence(value: Any) -> dict[str, Any]:
    """Persist source-backed corporate-action evidence without transient flags.

    The outcome provider needs the publication date and price-policy identity
    after a restart.  Older storage code retained only ``source`` and the
    effective date, which made a complete action look like an action with no
    availability evidence.  Keep the small, typed evidence contract here;
    never persist free-form notes or arbitrary provider fields.
    """

    if not isinstance(value, Mapping):
        raise PriceIdentityMetadataError("corporate action evidence is invalid.")
    source = value.get("source")
    effective_date = value.get("effective_date")
    payload_hash = value.get("payload_hash", value.get("payload_sha256"))
    policy_version = value.get("policy_version")
    if not (
        isinstance(source, str)
        and source.strip()
        and isinstance(effective_date, str)
        and effective_date.strip()
        and isinstance(policy_version, str)
        and policy_version.strip()
    ):
        raise PriceIdentityMetadataError("corporate action evidence is incomplete.")
    try:
        normalized_date = date.fromisoformat(effective_date.strip()).isoformat()
    except ValueError as exc:
        raise PriceIdentityMetadataError("corporate action evidence date is invalid.") from exc
    normalized_hash = str(payload_hash or "").strip().lower()
    if len(normalized_hash) != 64 or any(
        char not in "0123456789abcdef" for char in normalized_hash
    ):
        raise PriceIdentityMetadataError("corporate action evidence hash is invalid.")
    available_raw = value.get("available_date")
    normalized_available: str | None = None
    if available_raw is not None and str(available_raw).strip():
        try:
            normalized_available = date.fromisoformat(str(available_raw).strip()).isoformat()
        except ValueError as exc:
            raise PriceIdentityMetadataError(
                "corporate action evidence available date is invalid."
            ) from exc
    adjusted_raw_policy = value.get("adjusted_raw_policy")
    if adjusted_raw_policy is not None:
        adjusted_raw_policy = str(adjusted_raw_policy).strip().lower()
        if adjusted_raw_policy not in {"raw", "adjusted"}:
            raise PriceIdentityMetadataError(
                "corporate action evidence adjusted/raw policy is invalid."
            )

    # Preserve a caller-supplied deterministic event identity/terms when
    # present.  Otherwise derive terms from the finite economic fields only;
    # this lets the provider detect conflicting rows after reload without
    # carrying arbitrary source text into the sidecar.
    event_id_raw = value.get("event_id")
    event_id: str | None = None
    if event_id_raw is not None:
        event_id = sanitize_provider_text(str(event_id_raw).strip()) or None
    terms_raw = value.get("terms")
    terms: str | None = None
    if terms_raw is not None:
        terms = sanitize_provider_text(str(terms_raw).strip()) or None
    if terms is None:
        terms_payload = {
            key: value[key]
            for key in (
                "action_type",
                "split_ratio",
                "cash_per_share",
                "currency",
                "payable_date",
                "tax_rate",
            )
            if key in value
        }
        if terms_payload:
            terms = json.dumps(terms_payload, sort_keys=True, separators=(",", ":"))

    normalized: dict[str, Any] = {
        "source": sanitize_provider_text(source.strip()),
        "effective_date": normalized_date,
        "payload_hash": normalized_hash,
        "policy_version": sanitize_provider_text(policy_version.strip()),
    }
    if normalized_available is not None:
        normalized["available_date"] = normalized_available
    if adjusted_raw_policy is not None:
        normalized["adjusted_raw_policy"] = adjusted_raw_policy
    if event_id is not None:
        normalized["event_id"] = event_id
    if terms is not None:
        normalized["terms"] = terms
    return normalized


def _normalize_corporate_action_coverage(value: Any) -> dict[str, Any]:
    """Normalize source-backed evidence that no action occurred in a window.

    Absence of an action row is not proof of absence.  A caller must persist a
    separate, explicit coverage record with a source and payload hash before
    the outcome evaluator may treat the interval as clear.
    """

    if not isinstance(value, Mapping):
        raise PriceIdentityMetadataError("corporate action coverage is invalid.")
    source = value.get("source")
    start = value.get("coverage_start", value.get("start_date"))
    end = value.get("coverage_end", value.get("end_date"))
    payload_hash = value.get("payload_hash", value.get("payload_sha256"))
    confirmed = value.get("no_action_confirmed")
    policy_version = value.get("policy_version")
    if (
        not isinstance(source, str)
        or not source.strip()
        or not isinstance(start, str)
        or not isinstance(end, str)
        or not isinstance(confirmed, bool)
        or not confirmed
        or not isinstance(policy_version, str)
        or not policy_version.strip()
    ):
        raise PriceIdentityMetadataError("corporate action coverage is incomplete.")
    try:
        normalized_start = date.fromisoformat(start.strip()).isoformat()
        normalized_end = date.fromisoformat(end.strip()).isoformat()
    except ValueError as exc:
        raise PriceIdentityMetadataError("corporate action coverage date is invalid.") from exc
    if normalized_start > normalized_end:
        raise PriceIdentityMetadataError("corporate action coverage range is invalid.")
    normalized_hash = str(payload_hash or "").strip().lower()
    if len(normalized_hash) != 64 or any(
        char not in "0123456789abcdef" for char in normalized_hash
    ):
        raise PriceIdentityMetadataError("corporate action coverage hash is invalid.")
    return {
        "source": sanitize_provider_text(source.strip()),
        "coverage_start": normalized_start,
        "coverage_end": normalized_end,
        "payload_hash": normalized_hash,
        "policy_version": sanitize_provider_text(policy_version.strip()),
        "no_action_confirmed": True,
    }


def _mapping_optional_text(payload: Mapping[str, Any], key: str) -> str | None:
    """Read one optional sidecar field without coercing containers into text."""

    value = payload.get(key)
    if value is None or isinstance(value, str):
        return value
    raise PriceIdentityMetadataError(f"Price sidecar field {key} is invalid.")


def _safe_optional_text(value: object) -> str | None:
    """Retain only secret-safe optional diagnostic text."""

    if value is None:
        return None
    text = sanitize_provider_text(str(value)).strip()
    return text or None


def _normalize_optional_date(value: str | None) -> str | None:
    """Normalize an optional market-data date without substituting the current date."""

    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError as exc:
        raise PriceIdentityMetadataError("Price sidecar last_data_date is invalid.") from exc


def _normalize_optional_timestamp(value: str | None) -> str | None:
    """Normalize an optional provider check time without treating it as market time."""

    if value is None or not str(value).strip():
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise PriceIdentityMetadataError("Price sidecar checked_at is invalid.") from exc


_INGESTION_KEYS = (
    "run_id",
    "started_at",
    "completed_at",
    "requested_symbol",
    "resolved_symbol",
    "provider_symbol",
    "provider",
    "source_type",
    "request_start",
    "request_end",
    "cache_hit",
    "status",
    "input_rows",
    "output_rows",
    "quality_summary",
    "warnings",
    "errors",
    "attempts",
    "last_data_date",
)


def _normalize_ingestion_record(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Validate fields and apply redaction before SQLite receives metadata."""

    missing = [key for key in _INGESTION_KEYS if key not in record]
    if missing:
        raise ValueError(f"Ingestion record missing required field(s): {', '.join(missing)}")
    sanitized = _sanitize_value(dict(record))
    return (
        str(sanitized["run_id"]),
        str(sanitized["started_at"]),
        str(sanitized["completed_at"]),
        _json_text(sanitized["requested_symbol"]),
        _json_text(sanitized["resolved_symbol"]),
        str(sanitized["provider_symbol"]),
        str(sanitized["provider"]),
        str(sanitized["source_type"]),
        sanitized["request_start"],
        sanitized["request_end"],
        int(bool(sanitized["cache_hit"])),
        str(sanitized["status"]),
        int(sanitized["input_rows"]),
        int(sanitized["output_rows"]),
        _json_text(sanitized["quality_summary"]),
        _json_text(sanitized["warnings"]),
        _json_text(sanitized["errors"]),
        _json_text(sanitized["attempts"]),
        sanitized["last_data_date"],
    )


def _deserialize_ingestion_row(row: sqlite3.Row) -> dict[str, Any]:
    """Decode persisted JSON metadata while keeping defensive redaction in place."""

    return {
        "run_id": str(row["run_id"]),
        "started_at": str(row["started_at"]),
        "completed_at": str(row["completed_at"]),
        "requested_symbol": _read_json(row["requested_symbol_json"]),
        "resolved_symbol": _read_json(row["resolved_symbol_json"]),
        "provider_symbol": sanitize_provider_text(str(row["provider_symbol"])),
        "provider": sanitize_provider_text(str(row["provider"])),
        "source_type": str(row["source_type"]),
        "request_start": row["request_start"],
        "request_end": row["request_end"],
        "cache_hit": bool(row["cache_hit"]),
        "status": str(row["status"]),
        "input_rows": int(row["input_rows"]),
        "output_rows": int(row["output_rows"]),
        "quality_summary": _read_json(row["quality_summary_json"]),
        "warnings": _read_json(row["warnings_json"]),
        "errors": _read_json(row["errors_json"]),
        "attempts": _read_json(row["attempts_json"]),
        "last_data_date": row["last_data_date"],
    }


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    """Return whether a migration-owned table is available without raising raw SQL errors."""

    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


_BASE_TABLE_REQUIRED_COLUMNS = {
    "prices": frozenset(
        {
            "date",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "adjusted_close",
        }
    ),
    "schema_migrations": frozenset({"version", "applied_at"}),
}


def _connection_has_tables(connection: sqlite3.Connection) -> bool:
    """Return whether the current SQLite snapshot has any user-visible table."""

    return (
        connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1").fetchone()
        is not None
    )


def _validate_existing_base_schema(connection: sqlite3.Connection) -> None:
    """Reject same-name base tables that cannot safely support the existing contract."""

    for table_name, required_columns in _BASE_TABLE_REQUIRED_COLUMNS.items():
        if not _table_exists(connection, table_name):
            continue
        columns = {
            str(row["name"])
            for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        }
        missing = sorted(required_columns.difference(columns))
        if missing:
            raise MigrationError(
                f"Incompatible existing table schema for {table_name}: "
                f"missing required column(s) {', '.join(missing)}."
            )


def _base_schema_needs_creation(connection: sqlite3.Connection) -> bool:
    """Return whether a known v1.1 base table must be added to this locked database."""

    return any(
        not _table_exists(connection, table_name) for table_name in _BASE_TABLE_REQUIRED_COLUMNS
    )


def _applied_migration_versions(connection: sqlite3.Connection) -> frozenset[str]:
    """Read migration state without assuming a legacy database has the tracking table."""

    if not _table_exists(connection, "schema_migrations"):
        return frozenset()
    return frozenset(
        str(row["version"])
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    )


def _ensure_base_schema(connection: sqlite3.Connection) -> None:
    """Create only the original v1.1 tables before additive migrations run."""

    connection.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            adjusted_close REAL,
            PRIMARY KEY (date, symbol)
        )
        """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)


def _execute_migration_script(connection: sqlite3.Connection, migration_path: Path) -> None:
    """Execute one migration statement at a time inside the caller's transaction."""

    statement = ""
    for line in migration_path.read_text(encoding="utf-8").splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        connection.execute(statement)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_provider_text(value)
    if isinstance(value, Mapping):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_sanitize_value(item) for item in value]
    return value


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json(value: str) -> Any:
    return _sanitize_value(json.loads(value))
