# Sprint 7.1.1 Implementation Handoff

Status: Implementation complete and ready for independent acceptance review.

Date: 2026-07-14

## Scope

Sprint 7.1.1 is a corrective patch for the Sprint 7.1 research-document identity contract. It does not begin Sprint 8 and does not change Dashboard, provider, backtest, portfolio, risk, scoring, migration, or release UI behavior.

## Root Cause

`ResearchRepository.upsert_research_document()` previously performed:

1. `SELECT` the existing `document_id` owner;
2. compare the owner in Python;
3. execute an unconditional `INSERT ... ON CONFLICT DO UPDATE` that overwrote `symbol` and `market`.

Two independent SQLite connections could both read no row before either write. Both then passed the Python check and the last writer could overwrite the first document's canonical identity. This was a TOCTOU race and violated the documented global `document_id` ownership contract.

## Atomicity Fix

`upsert_research_document()` now uses one conditional SQLite UPSERT:

```sql
INSERT INTO research_documents (...)
VALUES (...)
ON CONFLICT(document_id) DO UPDATE SET
    -- mutable document fields only
WHERE research_documents.symbol = excluded.symbol
  AND research_documents.market = excluded.market
```

Properties of the fix:

- New IDs insert normally.
- Same `document_id` and same canonical identity update deterministically.
- The conflict update no longer writes `symbol` or `market`.
- A different symbol or market makes the update predicate false, so SQLite changes zero rows atomically.
- Only after the zero-row result does the repository read the existing owner to construct the existing `RepositoryDataError`; this read cannot authorize or mutate a conflicting write.
- The repository connection context rolls back the rejected transaction path and always closes the connection.

There is no SELECT-to-write authorization gap: the owner predicate is evaluated by the same database statement that performs the insert or update.

## Modified Files

- `src/stock_tool/data/repositories.py`
- `tests/test_research_repositories.py`

## New Deterministic Regression Coverage

The test-only connection wrapper places a `threading.Barrier` immediately before the first `INSERT INTO research_documents` statement. A second start barrier ensures both writer threads enter the repository call together. No sleep, retry loop, or probability-based race is used.

Covered cases:

- MU/US and MU/TWSE concurrently claim one `document_id`: exactly one succeeds; the other raises `RepositoryDataError`.
- The surviving record retains the winning title, metadata, `content_hash`, symbol, and market.
- The database file can be renamed after thread completion, proving no test connection remains open on Windows.
- Same identity concurrent writes both succeed and retain the canonical identity.
- Different `document_id` values concurrently write successfully.
- Existing sequential cross-market collision, get, delete, and same-identity update tests remain in place.

The pre-fix targeted test reproduced the defect: `1 failed, 9 passed`, with both cross-market writers succeeding. The fixed implementation passes the same deterministic test.

## Verification

### Sprint 7.1.1 targeted tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_research_repositories.py -o addopts='' -q
```

Result: `10 passed in 2.05s`.

### Sprint 7 and Sprint 7.1 repository and migration coverage

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_research_repositories.py tests\test_database_migrations.py tests\test_ingestion_migration.py tests\test_storage.py tests\test_storage_connection_lifecycle.py tests\test_release_assets.py tests\test_release_archive.py -o addopts='' -q
```

Result: `30 passed in 5.20s`.

### Full pytest

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' -q
```

Result: `406 passed in 27.02s`.

### Branch coverage

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing -q
```

Result: all tests passed; total coverage `79.24%` (gate: `78.50%`).

### Focused quality checks

```powershell
.\.venv\Scripts\python.exe -m black --check src\stock_tool\data\repositories.py tests\test_research_repositories.py
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\data\repositories.py tests\test_research_repositories.py
.\.venv\Scripts\python.exe -m mypy --follow-imports=skip --ignore-missing-imports src\stock_tool\data\repositories.py tests\test_research_repositories.py
```

Results:

- Black: `2 files would be left unchanged.`
- Ruff: `All checks passed!`
- mypy: `Success: no issues found in 2 source files`.

## EXE Build And Smoke Verification

The existing staging-first build and promotion flow was used after tests passed.

- EXE: `release\\StockTool\\StockTool.exe`
- last write: `2026-07-14 17:55:14 +08:00`
- size: `23,879,960` bytes
- SHA-256: `160742C1D48D3F399C32EFF2BB66EDFB219D2D41EA282038F48E5846419D5D4E`

Verified using an explicit isolated `STOCK_TOOL_USER_DATA_DIR` passed through `cmd.exe` to the EXE launcher:

- `StockTool.exe --version` returned `1.1.0`.
- `/_stcore/health` returned HTTP 200 with body `ok` on 8501.
- With 8501 held, the launcher used 8502 and health returned `ok`.
- With both 8501 and 8502 held, the launcher exited with code `1`.
- Isolated `reports`, `logs`, and `data/cache` write probes succeeded.
- Bundled sample price data loaded with 8 rows; bundled fundamentals loaded with 3 rows.
- No `StockTool` process or 8501/8502 listener remained after the smoke tests.

## Release Privacy And Public Assets

Release asset validation passed. Required public assets are present:

- `StockTool.exe`
- `README.md`
- `.env.example`
- `使用教學_簡易版.txt`
- `啟動股票工具.bat`
- `data/sample/`

Privacy scan result: zero forbidden `.env`, Streamlit secrets, token, private key, portfolio, watchlist, reports, logs, or cache entries in `release/StockTool`. The only bundled Streamlit configuration file is `_internal/.streamlit/config.toml`. The dependency CA bundle `_internal/certifi/cacert.pem` is a public CA certificate bundle, not a private key.

## Real User Data Integrity

The required CSV integrity checks were read-only:

- Before and after: `%LOCALAPPDATA%\\StockTool\\data\\portfolio.csv` exists, has 4 rows, and SHA-256 is `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
- Before and after: `%LOCALAPPDATA%\\StockTool\\data\\watchlist.csv` is absent.

Constraint observation: an initial EXE smoke attempt used a PowerShell health probe that generated invalid HTTP requests against Uvicorn and did not reliably pass the isolated runtime override. It was stopped immediately. The existing release-promotion/runtime migration flow also writes a timestamped migration manifest under `%LOCALAPPDATA%\\StockTool\\backups`. No portfolio or watchlist row or hash changed, and no existing user file was removed or overwritten. These runtime metadata writes were not cleaned up to avoid modifying real user data. All subsequent smoke validation used the explicit isolated runtime path described above.

## Source Archive

- archive: `release\\baseline\\stocktool-sprint7.1.1-20260714-source.zip`
- entries: `198`
- SHA-256: `04D7C53F983FBBDB44BF073E998A696A77AD1146B1A9107528A47883CE94D171`
- sidecar: `release\\baseline\\stocktool-sprint7.1.1-20260714-source.zip.sha256`

Archive extraction and manifest verification:

- required build inputs missing: `0`
- forbidden entries: `0`
- archive content mismatch: `0`
- workspace mismatch: `0`
- sidecar SHA-256 matches the ZIP.

## Known Limitations

- This patch protects the global `document_id` ownership contract within SQLite. It does not add a larger document-content/DLP model.
- The existing release promotion flow creates a local migration manifest as part of its safety check. A future approved release-process change should make that pre-promotion check explicitly isolated for automated smoke/build work when strict zero-write access to LocalAppData is required.
- Sprint 8 was not started.

Implementation complete and ready for independent acceptance review.
