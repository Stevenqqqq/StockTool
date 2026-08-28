# Sprint 3 Acceptance

驗收日期：2026-07-11  
執行環境：Windows、Python 3.11.9、PyInstaller 6.21.0

## Verdict

**Accepted.** Sprint 3 僅新增 Application Service 與資料血緣能力；未啟用 Dashboard/CLI 整合，未改動既有指標、基本面、股票評分、回測與風控公式，也未開始 Sprint 4。

## 1. Pre-change Baseline

- Archive: `release/baseline/stocktool-sprint2.1.1-20260711-source.zip`
- SHA-256: `3E09CF77169309F6E9C1FE697960D8FF7928F3297847665BA0597FD4F1221E7D`
- Isolated extraction verified source, tests, docs, build scripts, prior redaction implementation, and redaction tests.
- Excluded: `.venv`, `build`, `release/StockTool`, `.env`, runtime cache/reports/logs, `__pycache__`, and `.pyc`.
- Git executable was not available and was not installed.

## 2. Delivered Scope

### Application services

- Added `DataHydrationService`: consumes `ContractPriceDataProvider`, preserves canonical requested/resolved symbols and dates from `ProviderResult`, returns a defensive OHLCV copy, derives latest-data date/freshness, records source/cache/quality/warning/attempt/error lineage, and remains usable if metadata persistence fails.
- Added `AnalysisService`: composes injected hydration, indicator, fundamental, and score collaborators. It returns explicit `success`, `partial`, `insufficient_data`, `stale`, or `error` states. Provider failures short-circuit and never fabricate indicators, fundamentals, or scores.
- Added serializable application result models. `to_dict()` deliberately contains metadata and availability flags, never DataFrame payloads.

### SQLite ingestion lineage

- Added additive `001_ingestion_runs` migration with run ID, timestamps, canonical symbols, provider/source, date range, cache hit, status, row counts, quality summary, warnings/errors/attempts, and latest data date.
- Existing `prices` schema remains intact. Migrations are repeat-safe, support legacy databases, and preserve an explicit rollback marker so a rolled-back migration is not silently re-applied.
- Added `backup_database()`, `restore_database()`, and `rollback_ingestion_runs_migration()`. The rollback removes only Sprint 3 lineage metadata and leaves price rows untouched.
- Lineage persistence stores no raw provider payload or stack trace.

### Security and release safety

- Application results and SQLite metadata reuse the Sprint 2.1.1 idempotent provider redaction policy. Tokens, API keys, authorization values, passwords, secrets, and sensitive URL query values are redacted before serialization or storage.
- `build_exe.bat` no longer copies `data/cache/` or `data/processed/` into a release. It creates empty writable cache, reports, and logs folders and bundles SQL migration resources.

## 3. Files Changed

- `src/stock_tool/application/__init__.py`
- `src/stock_tool/application/results.py`
- `src/stock_tool/application/data_hydration.py`
- `src/stock_tool/application/analysis.py`
- `src/stock_tool/data/storage.py`
- `src/stock_tool/data/migrations/001_ingestion_runs.sql`
- `src/stock_tool/data/migrations/001_ingestion_runs.down.sql`
- `tests/test_application_services.py`
- `tests/test_ingestion_migration.py`
- `build_exe.bat`
- `README.md`
- `SPRINT3_ACCEPTANCE.md`

## 4. Test Evidence

| Verification | Result |
|---|---|
| New Sprint 3 tests | `10 passed` |
| Sprint 3 target set: application, migration, Provider Contract, data providers, baseline, CLI, Dashboard | `66 passed` |
| Full pytest | `242 passed in 9.61s` |
| Full coverage pytest | `242 passed in 16.99s` |
| Coverage | `72.35%`, above the required Sprint 3 gate of `71.52%` |
| Migration apply/repeat/legacy-upgrade/rollback/restore | passed through `tests/test_ingestion_migration.py` |
| Provider redaction regression | passed through `tests/test_provider_contracts.py` |
| Input DataFrame immutability and direct-module equivalence | passed through `tests/test_application_services.py` |
| Black, Sprint 3 changed-file/focused check | passed; 7 files unchanged |
| Ruff, Sprint 3 changed-file/focused check | passed |
| Focused mypy, application + storage | passed; 0 issues in 5 source files |

Whole-project Black/Ruff debt remains outside this Sprint and is not represented as passing. This Sprint did not add to that debt.

## 5. EXE and Release Verification

- Build: `cmd /c build_exe.bat` passed.
- Artifact: `release/StockTool/StockTool.exe`
- SHA-256: `4D850B11F256E3F96CECBD56220BC82AFFAE69D7A7E30B3CBD93000D478E8229`
- HTTP smoke: EXE served `http://localhost:8501` with HTTP `200`.
- `reports/`, `logs/`, and `data/cache/` write probes passed.
- Migration resource was present in the bundled `_internal/stock_tool/data/migrations/` directory.
- Smoke process and all listeners on ports `8501`/`8502` were terminated after verification.
- Final release scan found no real `.env`, no files under `data/cache/`, `data/processed/`, `reports/`, or `logs/`. The release contains only sample data plus empty writable runtime folders.

## 6. Backward Compatibility

- The existing Dashboard and CLI were not connected to the new services.
- Legacy `prices` databases upgrade without losing price rows.
- Existing Provider Contract sanitization and default-off boundaries remain unchanged.
- No core analytical or trading logic was changed.

## 7. Remaining Limits and Risks

1. Application services are intentionally not wired into UI or CLI; that is deferred to a separately approved Sprint 4 scope.
2. Freshness is only marked stale when a caller supplies both `as_of_date` and `stale_after_days`; the service does not invent a market-calendar policy.
3. Provider redaction is a targeted safeguard, not a full DLP system.
4. SQLite migration rollback intentionally drops lineage history and records a rollback marker; operators should create a backup before rollback and restore it when reapplying lineage storage is required.
5. PyInstaller emits known `pycparser.lextab/yacctab` hidden-import warnings during build, but the release passed HTTP smoke and writable-folder checks.
6. Git remains unavailable, so source archives and SHA-256 files serve as the release baseline rather than a Git merge baseline.

## 8. Final Source Archive

The final post-verification archive is stored beside its SHA-256 sidecar in `release/baseline/`. It excludes runtime and private data using the same rules as the pre-change baseline.

## 9. Exit Gate

- [x] Sprint 3 scope only; no Sprint 4 work.
- [x] Application orchestration uses dependency injection and does not alter calculation formulas.
- [x] No fabricated analysis when provider data is unavailable.
- [x] Ingestion metadata is redacted, additive, repeat-safe, and recoverable.
- [x] Legacy Dashboard/CLI and Provider Contract regressions pass.
- [x] Coverage remains above the required `71.52%` gate.
- [x] EXE build, HTTP smoke, writable-folder, and release-privacy checks pass.
