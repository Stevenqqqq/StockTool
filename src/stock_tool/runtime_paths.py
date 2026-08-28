"""Canonical runtime paths and conservative migration for local user data."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

USER_DATA_ENV_VAR = "STOCK_TOOL_USER_DATA_DIR"
_PORTFOLIO_REQUIRED_COLUMNS = {"symbol", "quantity", "average_cost", "market"}
_WATCHLIST_REQUIRED_COLUMNS = {"symbol", "market"}


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Resolved private runtime locations, independent of release assets."""

    root: Path

    @classmethod
    def from_environment(cls) -> RuntimePaths:
        """Resolve the user-data root from an override or Windows local app data."""

        override = os.environ.get(USER_DATA_ENV_VAR, "").strip()
        if override:
            return cls(Path(override).expanduser().resolve())
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return cls((base / "StockTool").resolve())

    @property
    def data_dir(self) -> Path:
        """Return the root directory for mutable data files."""

        return self.root / "data"

    @property
    def portfolio_file(self) -> Path:
        """Return the private manual-portfolio CSV location."""

        return self.data_dir / "portfolio.csv"

    @property
    def watchlist_file(self) -> Path:
        """Return the private watchlist CSV location."""

        return self.data_dir / "watchlist.csv"

    @property
    def processed_dir(self) -> Path:
        """Return the mutable processed-data directory."""

        return self.data_dir / "processed"

    @property
    def corporate_actions_file(self) -> Path:
        """Return the optional source-backed corporate-action contract file."""

        return self.processed_dir / "corporate_actions.csv"

    @property
    def cache_dir(self) -> Path:
        """Return the mutable provider-cache directory."""

        return self.data_dir / "cache"

    @property
    def market_snapshot_file(self) -> Path:
        """Return the official post-market snapshot cache path without creating it."""

        return self.cache_dir / "official_market_snapshot.json"

    @property
    def daily_research_dir(self) -> Path:
        """Return private derived Daily Research Loop snapshot storage."""

        return self.data_dir / "daily_research"

    @property
    def ai_research_dir(self) -> Path:
        """Return private latest-note storage for evidence-linked AI research."""

        return self.data_dir / "ai_research"

    @property
    def research_library_dir(self) -> Path:
        """Return private, versioned Research Library storage."""

        return self.data_dir / "research_library"

    @property
    def ledger_dir(self) -> Path:
        """Return private append-only Portfolio Ledger storage."""

        return self.data_dir / "ledger"

    @property
    def ledger_database_file(self) -> Path:
        """Return the dedicated Portfolio Ledger SQLite path without creating it."""

        return self.ledger_dir / "portfolio_ledger.sqlite"

    @property
    def daily_research_snapshot_file(self) -> Path:
        """Return the last successful derived Daily Brief snapshot sidecar path."""

        return self.daily_research_dir / "last_successful_daily_brief.json"

    @property
    def daily_research_brief_file(self) -> Path:
        """Return the latest evidence-chain brief JSON inside private runtime data."""

        return self.daily_research_dir / "latest_evidence_chain_brief.json"

    @property
    def daily_research_brief_html_file(self) -> Path:
        """Return the latest evidence-chain HTML export inside private runtime data."""

        return self.daily_research_dir / "latest_evidence_chain_brief.html"

    @property
    def daily_research_brief_history_dir(self) -> Path:
        """Return immutable, content-addressed successful brief history."""

        return self.daily_research_dir / "brief-history"

    @property
    def daily_research_change_file(self) -> Path:
        """Return the authoritative latest change summary JSON."""

        return self.daily_research_dir / "latest_change_summary.json"

    @property
    def daily_research_change_history_dir(self) -> Path:
        """Return immutable change-summary history."""

        return self.daily_research_dir / "change-history"

    @property
    def daily_schedule_dir(self) -> Path:
        """Return private scheduler state under the daily-research runtime area."""

        return self.daily_research_dir / "schedule"

    @property
    def daily_schedule_settings_file(self) -> Path:
        """Return the versioned scheduler settings path."""

        return self.daily_schedule_dir / "schedule-settings.json"

    @property
    def daily_schedule_latest_run_file(self) -> Path:
        """Return the latest scheduled-run record path."""

        return self.daily_schedule_dir / "latest-scheduled-run.json"

    @property
    def daily_schedule_runs_dir(self) -> Path:
        """Return the immutable bounded run-record directory."""

        return self.daily_schedule_dir / "runs"

    @property
    def daily_research_run_manifests_dir(self) -> Path:
        """Return immutable per-run orchestration manifests for Daily Research."""

        return self.daily_research_dir / "run-manifests"

    @property
    def daily_schedule_lock_file(self) -> Path:
        """Return the single-run lock path."""

        return self.daily_schedule_dir / "schedule.lock"

    @property
    def daily_notification_dir(self) -> Path:
        """Return private notification settings and ledger storage."""

        return self.daily_research_dir / "notifications"

    @property
    def daily_notification_settings_file(self) -> Path:
        """Return the notification settings file without creating it."""

        return self.daily_notification_dir / "notification-settings.json"

    @property
    def daily_notification_ledger_dir(self) -> Path:
        """Return immutable notification ledger records directory."""

        return self.daily_notification_dir / "ledger"

    @property
    def daily_notification_history_file(self) -> Path:
        """Return the bounded notification ledger projection."""

        return self.daily_notification_dir / "history.json"

    @property
    def macro_dir(self) -> Path:
        """Return private, validated macro-evidence storage."""

        return self.data_dir / "macro"

    @property
    def macro_latest_file(self) -> Path:
        """Return the authoritative latest macro snapshot JSON."""

        return self.macro_dir / "latest.json"

    @property
    def macro_history_dir(self) -> Path:
        """Return immutable content-addressed macro snapshot history."""

        return self.macro_dir / "history"

    @property
    def macro_revision_ledger_file(self) -> Path:
        """Return the bounded, replayable macro observation revision ledger."""

        return self.macro_dir / "revision-ledger.json"

    @property
    def prediction_lab_dir(self) -> Path:
        """Return the private root for immutable Prediction Lab records."""

        return self.data_dir / "prediction_lab"

    @property
    def prediction_lab_predictions_dir(self) -> Path:
        """Return the immutable prediction registration directory."""

        return self.prediction_lab_dir / "predictions"

    @property
    def prediction_lab_outcomes_dir(self) -> Path:
        """Return the immutable prediction outcome directory."""

        return self.prediction_lab_dir / "outcomes"

    @property
    def prediction_lab_index_file(self) -> Path:
        """Return the rebuildable Prediction Lab index projection."""

        return self.prediction_lab_dir / "index.json"

    @property
    def reports_dir(self) -> Path:
        """Return the user report-output directory."""

        return self.root / "reports"

    @property
    def logs_dir(self) -> Path:
        """Return the user log directory."""

        return self.root / "logs"

    @property
    def backups_dir(self) -> Path:
        """Return the private migration and user-data backup directory."""

        return self.root / "backups"

    @property
    def settings_file(self) -> Path:
        """Return the user settings file location."""

        return self.root / "settings.json"

    def ensure_directories(self) -> RuntimePaths:
        """Create all writable directories and return this immutable instance."""

        for directory in (
            self.data_dir,
            self.processed_dir,
            self.cache_dir,
            self.daily_research_dir,
            self.daily_schedule_dir,
            self.daily_schedule_runs_dir,
            self.daily_research_run_manifests_dir,
            self.daily_notification_dir,
            self.daily_notification_ledger_dir,
            self.macro_dir,
            self.macro_history_dir,
            self.prediction_lab_dir,
            self.prediction_lab_predictions_dir,
            self.prediction_lab_outcomes_dir,
            self.ai_research_dir,
            self.research_library_dir,
            self.ledger_dir,
            self.reports_dir,
            self.logs_dir,
            self.backups_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True, slots=True)
class UserDataMigrationItem:
    """Outcome for one legacy user-data item."""

    name: str
    status: str
    source: Path
    target: Path
    source_sha256: str | None = None
    target_sha256: str | None = None
    source_rows: int | None = None
    target_rows: int | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class UserDataMigrationResult:
    """Repeat-safe legacy migration result without destructive side effects."""

    items: tuple[UserDataMigrationItem, ...]
    warnings: tuple[str, ...] = ()
    manifest_path: Path | None = None

    def item(self, name: str) -> UserDataMigrationItem | None:
        """Return the migration outcome for one named item."""

        return next((item for item in self.items if item.name == name), None)


def default_runtime_paths() -> RuntimePaths:
    """Resolve and create the current process's canonical user-data paths."""

    return RuntimePaths.from_environment().ensure_directories()


def migrate_legacy_user_data(
    paths: RuntimePaths,
    *,
    legacy_root: str | Path,
) -> UserDataMigrationResult:
    """Copy legacy release runtime data once without overwriting newer user data.

    The legacy source is retained. Each copied source is first copied to a timestamped
    backup under the new user-data root, then verified before becoming active data.
    """

    paths.ensure_directories()
    source_root = Path(legacy_root)
    backup_root = paths.backups_dir / f"legacy-migration-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    mappings = (
        ("portfolio", source_root / "data" / "portfolio.csv", paths.portfolio_file),
        ("watchlist", source_root / "data" / "watchlist.csv", paths.watchlist_file),
        ("processed", source_root / "data" / "processed", paths.processed_dir),
        ("cache", source_root / "data" / "cache", paths.cache_dir),
        ("reports", source_root / "reports", paths.reports_dir),
        ("logs", source_root / "logs", paths.logs_dir),
    )
    items: list[UserDataMigrationItem] = []
    warnings: list[str] = []
    for name, source, target in mappings:
        item = _migrate_item(name, source, target, backup_root)
        items.append(item)
        if item.warning:
            warnings.append(item.warning)
    manifest_path = _write_migration_manifest(
        paths=paths,
        source_root=source_root,
        items=tuple(items),
        warnings=tuple(warnings),
    )
    return UserDataMigrationResult(
        items=tuple(items),
        warnings=tuple(warnings),
        manifest_path=manifest_path,
    )


def prepare_release_user_data_migration(
    *,
    legacy_root: str | Path,
    paths: RuntimePaths | None = None,
) -> UserDataMigrationResult:
    """Migrate legacy release data and block destructive cleanup on unsafe outcomes."""

    result = migrate_legacy_user_data(paths or default_runtime_paths(), legacy_root=legacy_root)
    unsafe = [
        item
        for item in result.items
        if item.status in {"failed", "failed_validation", "skipped_invalid"}
    ]
    if unsafe or result.manifest_path is None:
        details = (
            ", ".join(f"{item.name}:{item.status}" for item in unsafe) or "manifest unavailable"
        )
        raise RuntimeError(
            "Legacy user-data migration did not complete safely; release cleanup is blocked "
            f"({details})."
        )
    return result


def _migrate_item(
    name: str, source: Path, target: Path, backup_root: Path
) -> UserDataMigrationItem:
    if not source.exists() or _is_empty(source):
        return UserDataMigrationItem(name=name, status="absent", source=source, target=target)
    if target.exists() and not _is_empty(target):
        warning = f"Legacy {name} was not overwritten because current user data already exists."
        return UserDataMigrationItem(
            name=name,
            status="skipped_existing",
            source=source,
            target=target,
            warning=warning,
        )
    if source.is_file() and name in {"portfolio", "watchlist"}:
        valid, row_count, validation_warning = _validate_csv(source, name)
        if not valid:
            return UserDataMigrationItem(
                name=name,
                status="skipped_invalid",
                source=source,
                target=target,
                warning=validation_warning,
            )
    else:
        row_count = None

    backup_target = backup_root / (source.name if source.is_file() else name)
    try:
        _copy_path(source, backup_target)
        _copy_path(backup_target, target)
    except OSError as exc:
        return UserDataMigrationItem(
            name=name,
            status="failed",
            source=source,
            target=target,
            warning=f"Legacy {name} could not be copied safely: {exc}",
        )

    source_digest = _path_digest(source)
    target_digest = _path_digest(target)
    target_rows = (
        _csv_row_count(target) if target.is_file() and name in {"portfolio", "watchlist"} else None
    )
    if source_digest != target_digest or (row_count is not None and row_count != target_rows):
        return UserDataMigrationItem(
            name=name,
            status="failed_validation",
            source=source,
            target=target,
            source_sha256=source_digest,
            target_sha256=target_digest,
            source_rows=row_count,
            target_rows=target_rows,
            warning=f"Legacy {name} copy failed validation; the original source was retained.",
        )
    return UserDataMigrationItem(
        name=name,
        status="migrated",
        source=source,
        target=target,
        source_sha256=source_digest,
        target_sha256=target_digest,
        source_rows=row_count,
        target_rows=target_rows,
    )


def _validate_csv(path: Path, name: str) -> tuple[bool, int | None, str | None]:
    try:
        frame = pd.read_csv(path, dtype=str)
    except (OSError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        return False, None, f"Legacy {name} CSV could not be read: {exc}"
    required = _PORTFOLIO_REQUIRED_COLUMNS if name == "portfolio" else _WATCHLIST_REQUIRED_COLUMNS
    missing = sorted(required.difference(frame.columns))
    if missing:
        return False, None, f"Legacy {name} CSV is missing required columns: {', '.join(missing)}."
    if name == "portfolio":
        quantities = pd.to_numeric(frame["quantity"], errors="coerce")
        costs = pd.to_numeric(frame["average_cost"], errors="coerce")
        if quantities.isna().any() or costs.isna().any():
            return False, None, "Legacy portfolio CSV has invalid quantity or average_cost values."
    return True, len(frame), None


def _csv_row_count(path: Path) -> int | None:
    try:
        return len(pd.read_csv(path, dtype=str))
    except (OSError, pd.errors.ParserError, UnicodeDecodeError):
        return None


def _is_empty(path: Path) -> bool:
    if path.is_file():
        return path.stat().st_size == 0
    return not any(path.iterdir())


def _copy_path(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, target)
    else:
        shutil.copytree(source, target, dirs_exist_ok=True)


def _path_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in _iter_files(path):
        relative = file_path.relative_to(path if path.is_dir() else path.parent)
        digest.update(str(relative).replace("\\", "/").encode("utf-8"))
        digest.update(file_path.read_bytes())
    return digest.hexdigest()


def _iter_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        return (path,)
    return tuple(sorted(item for item in path.rglob("*") if item.is_file()))


def _write_migration_manifest(
    *,
    paths: RuntimePaths,
    source_root: Path,
    items: tuple[UserDataMigrationItem, ...],
    warnings: tuple[str, ...],
) -> Path:
    """Persist an auditable, non-destructive migration manifest under user backups."""

    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = paths.backups_dir / f"legacy-migration-{timestamp}.json"
    payload = {
        "source_root": str(source_root),
        "created_at": datetime.now().isoformat(),
        "warnings": list(warnings),
        "items": [
            {
                "name": item.name,
                "status": item.status,
                "source": str(item.source),
                "target": str(item.target),
                "source_sha256": item.source_sha256,
                "target_sha256": item.target_sha256,
                "source_rows": item.source_rows,
                "target_rows": item.target_rows,
                "warning": item.warning,
            }
            for item in items
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
