# Sprint 7.1 Implementation Handoff

Status: Implementation complete and ready for independent acceptance review.

Date: 2026-07-14

## Scope

Sprint 7.1 resolves the independent-review findings for Sprint 7 only:

- pre-write SQLite migration backups and exact failure recovery;
- concurrent initialization safety;
- canonical research identities delegated to the existing domain parser;
- collision-safe research-document identities;
- release asset allowlisting and sample-data delivery;
- regression coverage for incompatible schemas and corrupt persisted JSON.

No Dashboard, provider, backtest, risk, scoring, or portfolio behavior was changed. Sprint 8 was not started.

## Root Causes And Fixes

### Migration backup ordering and recovery

Root cause: `SQLitePriceStorage.initialize()` previously called `_ensure_base_schema()` before taking a migration backup. An old database therefore could be modified before its rollback point existed.

Fix:

- initialization now acquires `BEGIN IMMEDIATE` before inspecting migration state;
- for an existing database that needs base-schema work or a pending migration, it creates a consistent SQLite backup before any schema write;
- base schema validation and pending migration discovery are performed under the write lock;
- migration failure first rolls back/closes the active connection, then restores the pre-write backup with SQLite's backup API;
- existing same-name tables with incompatible required columns fail before writes;
- unknown tables and unknown columns are neither removed nor rebuilt.

New regression coverage snapshots both schema SQL and rows for prices-only and unknown-table-only legacy databases, injects a migration failure, and proves the post-failure database equals the pre-upgrade snapshot.

### Concurrent initialization

Root cause: a second process could calculate pending migrations before it obtained the write lock, then restore a stale backup after another process had completed the migration.

Fix: pending migrations are recalculated after `BEGIN IMMEDIATE` within the same transaction. A deterministic two-instance regression test verifies both initializers finish safely and migration `002` is recorded once only.

### Canonical research identity

Root cause: `ResearchIdentity` maintained a second suffix and market-normalization path that could drift from the established domain model.

Fix: known markets now delegate to `Symbol.parse` and `Market`.

- `2330` and `2330.TW` with `TWSE` normalize to `2330 / TWSE`.
- `6488.TWO` with `TPEX` normalizes to `6488 / TPEX`.
- `2330.TWO / TWSE` is rejected.
- `AAPL / US` remains `AAPL / US`.
- `UNKNOWN` is explicit unresolved identity only. It does not infer a market and cannot match a formal market identity.

### Research-document collisions

Chosen policy: `document_id` is globally unique. A duplicate upsert for the same canonical identity updates the record; reuse of the same ID for another symbol or market raises `RepositoryDataError`. This prevents cross-market silent overwrite. Tests cover collision, deterministic duplicate upsert, get, and delete behavior.

### Release contents

Root cause: the earlier release packaging path could produce an EXE directory containing only `StockTool.exe` and `_internal`.

Fix: `stock_tool.release_assets` defines the public release asset allowlist. `build_exe.bat` validates source assets before build, copies only allowlisted public assets to staging, then validates staging. `publish_release.bat` validates the staging and promoted release directories.

Required public release assets:

- `StockTool.exe`
- `README.md`
- `.env.example`
- `使用教學_簡易版.txt`
- `啟動股票工具.bat`
- `data/sample/`

The release smoke test loaded the bundled price sample (8 rows) and fundamentals sample (3 rows).

### Private document-content boundary

Research-document persistence is metadata-only. It has no dedicated raw-content field, but arbitrary JSON metadata is not a complete DLP boundary. Documentation was corrected to state that callers must not store raw private source text in metadata. No unapproved document-model redesign was made.

## Modified Files

- `src/stock_tool/data/storage.py`
- `src/stock_tool/data/repositories.py`
- `src/stock_tool/release_assets.py` (new)
- `build_exe.bat`
- `publish_release.bat`
- `tests/test_database_migrations.py`
- `tests/test_research_repositories.py`
- `tests/test_release_assets.py` (new)
- `README.md`
- `SPRINT7_ACCEPTANCE.md` (scope clarification only)

## Tests

### Sprint 7.1 targeted tests

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_database_migrations.py tests\test_research_repositories.py tests\test_release_assets.py tests\test_ingestion_migration.py tests\test_storage.py tests\test_storage_connection_lifecycle.py tests\test_release_archive.py -o addopts='' -q
```

Result: `28 passed in 7.43s`.

### Full pytest

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Result: `404 passed in 36.13s`.

### Branch coverage

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing
```

Result: `404 passed in 51.94s`; total branch coverage `79.25%` (gate: `78.50%`).

### Focused quality checks

Black:

```powershell
.\.venv\Scripts\python.exe -m black --check src\stock_tool\data\storage.py src\stock_tool\data\repositories.py src\stock_tool\release_assets.py tests\test_database_migrations.py tests\test_research_repositories.py tests\test_release_assets.py
```

Result: `6 files would be left unchanged.`

Ruff:

```powershell
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\data\storage.py src\stock_tool\data\repositories.py src\stock_tool\release_assets.py tests\test_database_migrations.py tests\test_research_repositories.py tests\test_release_assets.py
```

Result: `All checks passed!`

Mypy:

```powershell
.\.venv\Scripts\python.exe -m mypy --follow-imports=skip --ignore-missing-imports src\stock_tool\data\storage.py src\stock_tool\data\repositories.py src\stock_tool\release_assets.py tests\test_database_migrations.py tests\test_research_repositories.py tests\test_release_assets.py
```

Result: `Success: no issues found in 6 source files`.

## EXE Build And Smoke Tests

The release was built through the staging-first `build_exe.bat` and promoted only after the public asset allowlist passed.

EXE:

- path: `release\\StockTool\\StockTool.exe`
- last write: `2026-07-14 17:13:28 +08:00`
- size: `23,879,917` bytes
- SHA-256: `FAE034D003BC171D4F9BDB7A377E9003EA60A02AED0808C89C4FB6EF221740EC`

Isolated-runtime smoke results:

- `StockTool.exe --version` returned `1.1.0`.
- `/_stcore/health` returned HTTP 200 with body `ok` on port 8501.
- When port 8501 was held, the launcher started on port 8502 and health returned `ok`.
- When both 8501 and 8502 were held, the launcher exited with code 1 and wrote a clear isolated-runtime error log.
- isolated `reports/`, `logs/`, and `data/cache/` were created and successfully written.
- the bundled price and fundamental samples loaded successfully.
- all smoke-test `StockTool` processes and 8501/8502/8510 listeners were closed; temporary runtime files were removed.

## Release Privacy Scan

The final `release/StockTool` allowlist validation passed. Required assets are present and the privacy scan found zero forbidden files or runtime directories:

- no real `.env`, Streamlit secrets, token, private key, portfolio, watchlist, runtime report, log, or cache;
- the only Streamlit file is `_internal/.streamlit/config.toml`;
- the bundled `certifi/cacert.pem` is a public CA bundle required by dependencies and is explicitly not treated as a private key.

## Real User Data Integrity

Only read-only checks were performed against `%LOCALAPPDATA%\\StockTool\\data`.

- `portfolio.csv`: exists, 4 rows, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` before and after Sprint 7.1.
- `watchlist.csv`: absent before and after Sprint 7.1.

No real user data path was initialized, migrated, moved, overwritten, or used for tests.

## Source Archive And Rollback

Sprint 7.1 source archive:

- path: `release\\baseline\\stocktool-sprint7.1-20260714-source.zip`
- entries: `198`
- SHA-256: `CA90AECB4BCC0815E8BDBAE33A9BA5E7AA5961115934E22EC2AA0CA0E904F1EE`
- sidecar: `release\\baseline\\stocktool-sprint7.1-20260714-source.zip.sha256`

Archive verification passed:

- required build inputs missing: `0`;
- forbidden entries: `0`;
- archived workspace content mismatches: `0`;
- SHA-256 sidecar matches the ZIP.

The Sprint 6.1 / v1.1.0 rollback baseline remains retained, including the prior source archive and rollback package. The pre-promotion Sprint 7 release is retained separately under `release/previous/StockTool` for release-artifact rollback; it was privacy-scanned before promotion.

## Known Limitations

- Research repositories now provide the formal storage boundary, but Dashboard/provider integration and refresh-policy UI remain outside Sprint 7.
- `UNKNOWN` protects against market guessing but cannot resolve ambiguous legacy records without reliable source metadata.
- Existing legacy ingestion rollback code from earlier work remains unchanged; Sprint 7.1 migrations themselves are additive and are verified through backup-and-restore failure paths.
- Metadata persistence is not a full raw-document DLP system; raw private document content must not be placed in metadata pending separately approved work.

## Independent Review Handoff

Implementation complete and ready for independent acceptance review.
