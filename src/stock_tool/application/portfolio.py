"""Application boundary for the immutable Portfolio Ledger foundation."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from stock_tool.portfolio.ledger import (
    LedgerEntry,
    LedgerImportResult,
    LedgerSnapshot,
    import_legacy_opening_positions,
    replay_ledger,
)
from stock_tool.portfolio.ledger_repository import LedgerAppendResult, LedgerRepository
from stock_tool.runtime_paths import RuntimePaths, default_runtime_paths


@dataclass(frozen=True, slots=True)
class LedgerBootstrapOutcome:
    """Explicit legacy bootstrap result without changing the source CSV."""

    import_result: LedgerImportResult
    append_result: LedgerAppendResult
    snapshot: LedgerSnapshot


class PortfolioLedgerService:
    """Replay explicit entries and perform read-only legacy opening imports."""

    def __init__(self, *, repository: LedgerRepository | None = None) -> None:
        self._repository = repository

    @classmethod
    def from_runtime_paths(cls, paths: RuntimePaths | None = None) -> PortfolioLedgerService:
        """Create an explicit application boundary over the canonical runtime database."""

        resolved_paths = paths or default_runtime_paths()
        return cls(repository=LedgerRepository(resolved_paths.ledger_database_file))

    def replay(self, entries: Iterable[LedgerEntry]) -> LedgerSnapshot:
        """Return a deterministic snapshot for immutable caller-supplied entries."""

        return replay_ledger(entries)

    def import_legacy_frame(self, frame: pd.DataFrame) -> LedgerImportResult:
        """Convert an aggregate legacy portfolio frame without persisting changes."""

        return self.preview_legacy_frame(frame)

    def preview_legacy_frame(self, frame: pd.DataFrame) -> LedgerImportResult:
        """Preview a legacy import without initializing or writing the repository."""

        return import_legacy_opening_positions(frame)

    def preview_legacy_csv(self, path: str | Path) -> LedgerImportResult:
        """Read a legacy CSV and preview its conversion without persistence side effects."""

        return self.preview_legacy_frame(pd.read_csv(Path(path), dtype=str))

    def append_entries(self, entries: Iterable[LedgerEntry]) -> LedgerAppendResult:
        """Append immutable ledger entries through the explicit repository boundary."""

        return self._require_repository().append_entries(tuple(entries))

    def load_entries(self) -> tuple[LedgerEntry, ...]:
        """Load validated immutable entries from the configured repository."""

        return self._require_repository().load_entries()

    def replay_persisted(self) -> LedgerSnapshot:
        """Replay exactly the deterministic persisted entry sequence."""

        return self.replay(self.load_entries())

    def bootstrap_legacy_entries(self, frame: pd.DataFrame) -> LedgerBootstrapOutcome:
        """Explicitly persist valid deterministic legacy opening entries once."""

        import_result = self.preview_legacy_frame(frame)
        append_result = self.append_entries(import_result.entries)
        return LedgerBootstrapOutcome(
            import_result=import_result,
            append_result=append_result,
            snapshot=self.replay_persisted(),
        )

    def import_and_replay_legacy_csv(self, path: str | Path) -> LedgerImportOutcome:
        """Read a legacy CSV only, convert valid rows, and replay opening positions."""

        frame = pd.read_csv(Path(path), dtype=str)
        result = self.preview_legacy_frame(frame)
        return LedgerImportOutcome(import_result=result, snapshot=self.replay(result.entries))

    def _require_repository(self) -> LedgerRepository:
        if self._repository is None:
            raise RuntimeError("Portfolio Ledger persistence requires an explicit repository.")
        return self._repository


class LedgerImportOutcome:
    """One explicit read-only legacy import and its deterministic snapshot."""

    def __init__(self, *, import_result: LedgerImportResult, snapshot: LedgerSnapshot) -> None:
        self.import_result = import_result
        self.snapshot = snapshot
