# Sprint 7 Acceptance Record

## Status

Implementation complete and ready for independent acceptance review.

## Scope and baseline

Sprint 7 implements the approved formal research-storage layer and safe,
additive SQLite migrations only. Sprint 8 was not started. The governance
baseline in `AGENTS.md` now records Sprint 6.1 / StockTool v1.1.0.

Before implementation, the following rollback inputs were checked read-only:

- `release/baseline/stocktool-sprint6.1-20260714-source.zip`: sidecar hash
  matched the archive.
- `release/baseline/stocktool-sprint5.2.2-20260713-rollback.zip`: sidecar hash
  matched the archive.

The real `%LOCALAPPDATA%\\StockTool\\data\\portfolio.csv` was read-only and
remained four rows with SHA-256
`A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
`watchlist.csv` was absent before and after this Sprint.

## Modified files

- `AGENTS.md`: only updated the formal acceptance baseline to Sprint 6.1 /
  StockTool v1.1.0.
- `src/stock_tool/data/storage.py`: additive migration runner, schema-version
  access, backup-and-restore failure handling, and repository connection
  boundary.
- `src/stock_tool/data/migrations/002_research_entities.sql`: repeat-safe,
  additive research schema.
- `src/stock_tool/data/repositories.py`: market-qualified repository API for
  research data.
- `src/stock_tool/data/__init__.py`: public exports for the storage boundary.
- `tests/test_database_migrations.py`: migration safety, repeatability,
  rollback, backup restore, and corrupt-database regression tests.
- `tests/test_research_repositories.py`: CRUD, identity, provenance/state,
  path isolation, and non-destructive invalid-data tests.
- `tests/test_ingestion_migration.py`: updated ordered-migration expectations
  after the additive 002 schema.
- `README.md`: Research Storage usage and safety documentation.

## Schema and migration model

`002_research_entities` is an additive migration recorded in
`schema_migrations`. It creates these repository-owned tables:

- `research_fundamentals`
- `research_company_profiles`
- `research_concepts`
- `research_concept_relations`
- `research_documents`

Every asset-bound record has a canonical `symbol + market` identity. The
fundamentals primary key also includes `fiscal_period`, `period_type`, and
`as_of_date`. Provider/source lineage records `provider`, `source_type`,
`provider_symbol`, optional sanitized `source_url`, `fetched_at`, `updated_at`,
state (`complete`, `partial`, `stale`, or `unknown`), and redacted warnings.

`ResearchIdentity` accepts only the existing canonical markets TWSE, TPEX, and
US; missing or unsupported market input becomes `UNKNOWN`. It does not infer a
market from a symbol, so same-symbol records in different markets do not
collide.

## Migration safety invariants

- Migration SQL uses only additive `CREATE TABLE IF NOT EXISTS` and
  `CREATE INDEX IF NOT EXISTS` statements.
- A pending migration on an existing database first makes a sibling
  `*.pre-migration-*.sqlite` backup.
- All pending migrations run inside one `BEGIN IMMEDIATE` transaction.
- On failure, the transaction rolls back and the pre-migration backup is
  restored with SQLite's backup API before a `MigrationError` is surfaced.
- Re-running an already-upgraded database is idempotent and creates no new
  backup.
- Unknown tables, unknown columns, existing prices, and corrupt SQLite bytes
  are not deleted or overwritten by Sprint 7 code.
- Tests use only new temporary databases and temporary runtime roots. No real
  runtime SQLite database was initialized or migrated.

The legacy Sprint 3 ingestion migration rollback remains an existing,
explicitly scoped compatibility path for `001_ingestion_runs`; it is not called
by Sprint 7. Sprint 7 does not add a destructive down migration.

## Repository behavior

`ResearchRepository` is the SQL boundary for persisted research entities.
Its public CRUD operations use parameterized SQL and report missing data as no
record rather than fabricated values. A stored `partial` or `stale` state is
preserved as provenance. Duplicate upserts are deterministic for the same
canonical identity; different markets remain independent. Invalid input and
corrupt serialized metadata raise a domain error without modifying existing
data. Research documents have no dedicated raw-content field and are intended
for metadata plus content hashes. Sprint 7 does not inspect arbitrary metadata
values for raw private document content; callers remain responsible for not
placing private source text in metadata.

Sprint 7 deliberately does not refactor Dashboard, provider retry/TTL, scoring,
backtest, risk, or portfolio behavior. Existing fundamentals/provider flows are
not yet migrated to this new repository boundary; an approved later Sprint must
add those adapters without weakening canonical identity rules.

## Tests and coverage

Targeted command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_database_migrations.py tests\test_research_repositories.py tests\test_ingestion_migration.py tests\test_storage.py tests\test_storage_connection_lifecycle.py -o addopts='' -q
```

Result: `14 passed in 3.73s`.

Full command:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Result: `394 passed in 36.52s`.

Coverage command:

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing
```

Result: `394 passed in 63.50s`; branch coverage `79.18%`, above the `78.50%`
gate.

The new regression tests cover an empty database, deterministic v1.1 fixture
upgrade, repeated migration, transactional failure, backup restoration,
price-row count/hash preservation, corrupt input preservation, repository CRUD,
same-symbol cross-market coexistence, provenance/timestamps, missing/partial/
stale states, duplicate handling, runtime/sample/release path separation, and
no access to the real user-data root.

## Focused quality checks

Black:

```powershell
.\.venv\Scripts\python.exe -m black --check src\stock_tool\data\storage.py src\stock_tool\data\repositories.py src\stock_tool\data\__init__.py tests\test_database_migrations.py tests\test_research_repositories.py tests\test_ingestion_migration.py
```

Result: `6 files would be left unchanged.`

Ruff:

```powershell
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\data\storage.py src\stock_tool\data\repositories.py src\stock_tool\data\__init__.py tests\test_database_migrations.py tests\test_research_repositories.py tests\test_ingestion_migration.py
```

Result: `All checks passed!`

Mypy:

```powershell
.\.venv\Scripts\python.exe -m mypy --follow-imports=skip --ignore-missing-imports src\stock_tool\data\storage.py src\stock_tool\data\repositories.py src\stock_tool\data\__init__.py tests\test_database_migrations.py tests\test_research_repositories.py tests\test_ingestion_migration.py
```

Result: `Success: no issues found in 6 source files`.

## EXE build and smoke verification

`build_exe.bat` created a new staging package. The staged package was validated
before promotion. Because `release/previous/StockTool` already held a protected
historical release, it was first read-only scanned (no user data) and preserved
as `release/baseline/stocktool-v1.1.0-previous-20260714`. Promotion then ran
through `publish_release.bat` with an isolated temporary
`STOCK_TOOL_USER_DATA_DIR`; it did not access the actual user runtime.

Official EXE:

- Path: `release/StockTool/StockTool.exe`
- Version: `1.1.0`
- Modified: `2026-07-14 16:16:19 +08:00`
- Size: `23,877,960` bytes
- SHA-256: `ACC53906DC544F47F3498E245BD4A74A82671ED1D9FA62BF406FCD65CFFE177D`

Smoke tests used isolated temporary runtime roots only:

- Port 8501: `/_stcore/health` returned HTTP 200 with body `ok`.
- Port 8501 occupied: launcher selected 8502 and health returned HTTP 200 with
  body `ok`.
- Ports 8501 and 8502 occupied: launcher exited with code 1 and created one
  readable launcher error log.
- `reports`, `logs`, and `data/cache` were created and write-probed.
- All test processes, ports 8501/8502/8510 listeners, and temporary runtime
  files were removed after the smoke tests.

## Release privacy scan

The official `release/StockTool` scan found:

- forbidden files (`.env`, `secrets*.toml`, `portfolio.csv`, `watchlist.csv`):
  `0`
- runtime directories (`logs`, `reports`, `cache`): `0`
- bundled Streamlit files: only `_internal/.streamlit/config.toml`

No real `.env`, token, private portfolio/watchlist, runtime report, log, or
cache was packaged.

## Source archive

- Archive: `release/baseline/stocktool-sprint7-20260714-source.zip`
- Sidecar: `release/baseline/stocktool-sprint7-20260714-source.zip.sha256`
- Entries: `196`
- SHA-256: `989D88E71EC5AF2265691390392167F63D019297CCE37CAB7B706548D30EE25A`

The archive was extracted to a temporary directory and verified against its
manifest and current workspace. Results: missing required build inputs `0`,
forbidden entries `0`, archive content mismatches `0`, workspace content
mismatches `0`, and sidecar hash matched. The temporary extraction directory
was removed afterward.

## Rollback method

For an application rollback, retain the formal Sprint 6.1 source archive and
the verified Sprint 5.2.2 rollback package listed above. For a database
migration failure, Sprint 7 automatically restores the timestamped sibling
SQLite backup. The current promotion also preserves the prior release under
`release/previous/StockTool`; no real user data is stored there.

## Known limitations

- The repository is a new data-layer boundary; provider/UI adapters are not
  deliberately wired in this Sprint to avoid an unapproved Dashboard or
  provider refactor.
- `UNKNOWN` is intentionally non-matchable rather than guessed. A later,
  approved data-quality workflow must resolve unknown market identities with
  evidence.
- Existing legacy migration rollback remains limited to its historical
  `001_ingestion_runs` scope. Sprint 7 adds no destructive rollback path.
- This record is implementation evidence only and awaits ChatGPT CTO's
  independent acceptance review.
