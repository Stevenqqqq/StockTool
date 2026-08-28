"""Privacy-safe, read-only diagnostics for the native Settings workspace."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import quote

from stock_tool import __version__
from stock_tool.runtime_paths import RuntimePaths

_SCHEMA_VERSION = 1
_FRESH_AFTER = timedelta(days=1)
_STALE_AFTER = timedelta(days=7)
_KNOWN_SECRET_KEYS = (
    "FINMIND_TOKEN",
    "OPENAI_API_KEY",
    "STOCKTOOL_OPENAI_API_KEY",
)


@dataclass(frozen=True, slots=True)
class SettingsComponentStatus:
    """A redacted status row; it never contains a private path or file value."""

    key: str
    label: str
    status: str
    exists: bool
    count: int
    freshness: str
    details: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a stable, privacy-safe representation for the manifest."""

        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "exists": self.exists,
            "count": self.count,
            "freshness": self.freshness,
            "details": {key: value for key, value in self.details},
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class SettingsWorkspaceManifest:
    """Deterministic diagnostic core plus a non-core check timestamp."""

    core: Mapping[str, object]
    checked_at_utc: str

    @property
    def digest(self) -> str:
        """Return a digest that excludes the non-deterministic check timestamp."""

        payload = json.dumps(
            self.core, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict[str, object]:
        """Return a safe download payload with an explicit digest."""

        return {
            **dict(self.core),
            "checked_at_utc": self.checked_at_utc,
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class SettingsWorkspaceSnapshot:
    """One read-only settings/data-health observation."""

    status: str
    components: tuple[SettingsComponentStatus, ...]
    gaps: tuple[str, ...]
    warnings: tuple[str, ...]
    manifest: SettingsWorkspaceManifest

    @property
    def digest(self) -> str:
        return self.manifest.digest

    def to_manifest_dict(self) -> dict[str, object]:
        """Return the privacy-safe manifest exposed by the UI."""

        return self.manifest.to_dict()


class SettingsWorkspaceApplicationService:
    """Inspect local state without creating directories or writing any files."""

    def __init__(
        self,
        paths: RuntimePaths,
        *,
        database_path: Path | None = None,
        environment: Mapping[str, str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.paths = paths
        self.database_path = (
            Path(database_path)
            if database_path is not None
            else paths.processed_dir / "stock_data.sqlite"
        )
        self.environment = dict(os.environ if environment is None else environment)
        self._now = now or (lambda: datetime.now(UTC))

    def inspect(self) -> SettingsWorkspaceSnapshot:
        """Read all configured components once and return a redacted snapshot."""

        checked_at = _utc_iso(self._now())
        components = (
            self._inspect_settings(),
            self._inspect_portfolio(),
            self._inspect_watchlist(),
            self._inspect_research_library(),
            self._inspect_ledger(),
            self._inspect_database(),
            self._inspect_cache(),
            self._inspect_provider_settings(),
        )
        gaps = tuple(
            _component_gap(component) for component in components if component.status != "healthy"
        )[:3]
        warnings = tuple(
            dict.fromkeys(warning for component in components for warning in component.warnings)
        )
        core = {
            "schema_version": _SCHEMA_VERSION,
            "application_version": __version__,
            "status": _overall_status(components),
            "components": [component.to_dict() for component in components],
            "gaps": list(gaps),
            "warnings": list(warnings),
        }
        manifest = SettingsWorkspaceManifest(core=core, checked_at_utc=checked_at)
        return SettingsWorkspaceSnapshot(
            status=str(core["status"]),
            components=components,
            gaps=gaps,
            warnings=warnings,
            manifest=manifest,
        )

    def refresh(self) -> SettingsWorkspaceSnapshot:
        """Re-read local state; this method intentionally performs no writes."""

        return self.inspect()

    def _inspect_settings(self) -> SettingsComponentStatus:
        path = self.paths.settings_file
        if not _regular_file(path):
            return _missing("settings", "本機設定", "尚未建立設定檔。")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return _error("settings", "本機設定", "設定檔無法讀取或格式損壞。")
        if not isinstance(payload, dict):
            return _error("settings", "本機設定", "設定檔格式不正確。")
        return _healthy(
            "settings", "本機設定", count=len(payload), freshness=_freshness(path, self._now())
        )

    def _inspect_portfolio(self) -> SettingsComponentStatus:
        return _inspect_csv_component(
            self.paths.portfolio_file,
            key="portfolio",
            label="Portfolio 持股",
            required=("symbol", "market", "quantity", "average_cost"),
            now=self._now,
        )

    def _inspect_watchlist(self) -> SettingsComponentStatus:
        return _inspect_csv_component(
            self.paths.watchlist_file,
            key="watchlist",
            label="Watchlist 自選股",
            required=("symbol", "market"),
            now=self._now,
        )

    def _inspect_research_library(self) -> SettingsComponentStatus:
        directory = self.paths.research_library_dir
        if not directory.is_dir() or directory.is_symlink():
            return _missing("research_library", "Research Library", "尚未建立研究庫。")
        entries = sorted(directory.glob("entries/*.json"))
        if not entries:
            return _missing("research_library", "Research Library", "研究庫目前沒有可讀保存版本。")
        for entry in entries:
            if not _regular_file(entry):
                return _error(
                    "research_library", "Research Library", "研究庫包含無法安全讀取的項目。"
                )
            try:
                payload = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return _error("research_library", "Research Library", "研究庫包含損壞項目。")
            if not isinstance(payload, dict):
                return _error(
                    "research_library", "Research Library", "研究庫包含格式不正確的項目。"
                )
        return _healthy(
            "research_library",
            "Research Library",
            count=len(entries),
            freshness=_freshness(max(entries, key=lambda item: item.stat().st_mtime), self._now()),
        )

    def _inspect_ledger(self) -> SettingsComponentStatus:
        path = self.paths.ledger_database_file
        if not _regular_file(path):
            return _missing("ledger", "Ledger", "尚未建立 Ledger；檢查不會自動建立它。")
        try:
            with closing(_sqlite_read_only(path)) as connection:
                table_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                    ).fetchone()[0]
                )
                row_count = _sqlite_row_count(connection, "portfolio_ledger_entries")
        except (OSError, sqlite3.Error):
            return _error("ledger", "Ledger", "Ledger SQLite 無法安全讀取。")
        return _healthy(
            "ledger",
            "Ledger",
            count=row_count,
            freshness=_freshness(path, self._now()),
            details=(
                ("table_count", str(table_count)),
                ("row_count", str(row_count)),
            ),
        )

    def _inspect_database(self) -> SettingsComponentStatus:
        path = self.database_path
        if not _regular_file(path):
            return _missing("sqlite", "SQLite／資料庫", "尚未建立本機市場資料資料庫。")
        try:
            with closing(_sqlite_read_only(path)) as connection:
                table_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                    ).fetchone()[0]
                )
        except (OSError, sqlite3.Error):
            return _error("sqlite", "SQLite／資料庫", "本機資料庫無法安全讀取。")
        return _healthy(
            "sqlite",
            "SQLite／資料庫",
            count=table_count,
            freshness=_freshness(path, self._now()),
            details=(("table_count", str(table_count)),),
        )

    def _inspect_cache(self) -> SettingsComponentStatus:
        directory = self.paths.cache_dir
        if not directory.is_dir() or directory.is_symlink():
            return _missing("market_cache", "Market-data cache", "尚未建立行情快取。")
        files = [path for path in directory.rglob("*") if path.is_file() and not path.is_symlink()]
        if not files:
            return _missing("market_cache", "Market-data cache", "行情快取目前沒有檔案。")
        newest = max(files, key=lambda item: item.stat().st_mtime)
        freshness = _freshness(newest, self._now())
        status = "stale" if freshness == "stale" else "healthy"
        warning = ("行情快取已過期，需由使用者明確更新資料。",) if status == "stale" else ()
        return SettingsComponentStatus(
            key="market_cache",
            label="Market-data cache",
            status=status,
            exists=True,
            count=len(files),
            freshness=freshness,
            warnings=warning,
        )

    def _inspect_provider_settings(self) -> SettingsComponentStatus:
        configured = tuple(
            key for key in _KNOWN_SECRET_KEYS if self.environment.get(key, "").strip()
        )
        presence = "configured" if configured else "not_configured"
        # Optional credentials are configuration presence, not local data health.
        status = "healthy"
        return SettingsComponentStatus(
            key="provider_settings",
            label="Provider／外部 AI 設定",
            status=status,
            exists=bool(configured),
            count=len(configured),
            freshness="not_applicable",
            details=(("presence", presence),),
            warnings=(),
        )


def _inspect_csv_component(
    path: Path,
    *,
    key: str,
    label: str,
    required: tuple[str, ...],
    now: Callable[[], datetime],
) -> SettingsComponentStatus:
    if not _regular_file(path):
        return _missing(key, label, f"{label} 尚未建立。")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = tuple(reader.fieldnames or ())
            if any(column not in fieldnames for column in required):
                return _error(key, label, f"{label} 欄位不完整。")
            count = sum(1 for _ in reader)
    except (OSError, UnicodeError, csv.Error):
        return _error(key, label, f"{label} 無法安全讀取。")
    if count == 0:
        return SettingsComponentStatus(
            key=key,
            label=label,
            status="partial",
            exists=True,
            count=0,
            freshness=_freshness(path, now()),
            warnings=(f"{label} 目前沒有資料列。",),
        )
    return _healthy(key, label, count=count, freshness=_freshness(path, now()))


def _sqlite_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{quote(str(path.resolve()))}?mode=ro", uri=True)


def _sqlite_row_count(connection: sqlite3.Connection, table: str) -> int:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if exists is None:
        return 0
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _freshness(path: Path, now: datetime) -> str:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return "missing"
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    age = max(current.astimezone(UTC) - modified, timedelta(0))
    if age <= _FRESH_AFTER:
        return "fresh"
    if age <= _STALE_AFTER:
        return "stale"
    return "stale"


def _healthy(
    key: str,
    label: str,
    *,
    count: int,
    freshness: str,
    details: tuple[tuple[str, str], ...] = (),
) -> SettingsComponentStatus:
    return SettingsComponentStatus(
        key=key,
        label=label,
        status="healthy",
        exists=True,
        count=count,
        freshness=freshness,
        details=details,
    )


def _missing(key: str, label: str, warning: str) -> SettingsComponentStatus:
    return SettingsComponentStatus(
        key=key,
        label=label,
        status="missing",
        exists=False,
        count=0,
        freshness="missing",
        warnings=(warning,),
    )


def _error(key: str, label: str, warning: str) -> SettingsComponentStatus:
    return SettingsComponentStatus(
        key=key,
        label=label,
        status="error",
        exists=True,
        count=0,
        freshness="error",
        warnings=(warning,),
    )


def _component_gap(component: SettingsComponentStatus) -> str:
    return f"{component.label}：{component.status}；{_first_warning(component)}"


def _first_warning(component: SettingsComponentStatus) -> str:
    return component.warnings[0] if component.warnings else "請由設定頁提供的安全下一步處理。"


def _overall_status(components: tuple[SettingsComponentStatus, ...]) -> str:
    # Optional provider credentials are reported separately but never count as
    # a missing local-data component.
    states = {component.status for component in components if component.key != "provider_settings"}
    if "error" in states:
        return "error"
    if "partial" in states:
        return "partial"
    if "stale" in states:
        return "stale"
    if states and states <= {"missing"}:
        return "missing"
    if "missing" in states:
        return "partial"
    return "healthy"
