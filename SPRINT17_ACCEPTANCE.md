# Sprint 17 Acceptance

Status: Implementation complete and ready for independent CTO acceptance review.

## Scope

Sprint 17 adds a private, local-only Research Library. It saves versioned,
market-qualified evidence-linked notes, exposes saved versions in the existing
Library workspace, records document-reference lifecycle metadata, and supports
validated backup/restore. It does not add OCR, cloud sync, a new AI provider,
background work, automated trading, or a formal release promotion.

## Implementation

Modified or added files:

- `src/stock_tool/runtime_paths.py`
- `src/stock_tool/research/library.py` (new)
- `src/stock_tool/research/document_store.py` (new)
- `src/stock_tool/dashboard/pages/research.py`
- `src/stock_tool/dashboard/pages/library.py`
- `src/stock_tool/dashboard/shell.py`
- `tests/test_research_library.py` (new)
- `tests/test_document_lifecycle.py` (new)
- `tests/test_backup_restore.py` (new)

`RuntimePaths.research_library_dir` resolves to the process-local
`data/research_library` directory. All tests and smoke checks used a distinct
`STOCK_TOOL_USER_DATA_DIR`; no production runtime path was used as a test
fixture.

### Data and lifecycle contract

- Every saved entry has schema version, UUID entry ID, canonical `symbol` and
  `market`, title, created/updated timestamps, per-identity version, lifecycle
  state, snapshot/evidence fingerprints, content hash, data-as-of, source list,
  immutable EvidenceBundle, and validated AI/local-rules note.
- Saving the same research again creates a new version; it cannot silently
  overwrite an earlier entry. Same ticker in different markets remains
  separate.
- Entry loading revalidates the note against the saved EvidenceBundle. Citation
  IDs, excerpts, provider/URL metadata, coverage, confidence, and missing-data
  derived values cannot be forged through persisted JSON.
- Delete is explicit and writes a `deleted` tombstone. Cache cleanup does not
  delete library entries.
- `DocumentStore` stores only local reference metadata and content hashes, not
  PDF/document content. A removed source becomes `broken_reference`, preserves
  original hash metadata, and exposes no fake URL.

### Backup and restore

Backups contain only Research Library JSON and a versioned manifest with
relative paths, sizes, and SHA-256 hashes. Restore validates manifest schema,
paths, count/content hashes, and library entry/citation relationships in a
staging directory before an atomic replacement. Zip-slip, tampered content,
unknown/corrupt schemas, or validation failures leave the current library
unchanged. Backups exclude portfolio/watchlist, provider cache, reports, logs,
other SQLite files, source archives, executables, `.env`, and secrets.

## Tests and Quality Checks

Targeted command:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_research_library.py tests/test_document_lifecycle.py tests/test_backup_restore.py tests/test_research_assistant.py tests/test_research_assistant_dashboard.py tests/test_research_workspace.py tests/test_dashboard_shell.py
```

Result: `49 passed`.

Full test command:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Result: exit code 0; collection verified `827` tests; no failures.

Coverage command:

```powershell
.venv\Scripts\python.exe -m pytest --cov=src/stock_tool --cov-branch --cov-report=term -q
```

Result: branch coverage `82.30%`, meeting the Sprint 17 gate of `82.30%` and
the configured `78.50%` gate.

Focused quality commands:

```powershell
.venv\Scripts\python.exe -m black --check src/stock_tool/research/library.py src/stock_tool/research/document_store.py src/stock_tool/runtime_paths.py src/stock_tool/dashboard/pages/research.py src/stock_tool/dashboard/pages/library.py src/stock_tool/dashboard/shell.py tests/test_research_library.py tests/test_document_lifecycle.py tests/test_backup_restore.py
.venv\Scripts\python.exe -m ruff check src/stock_tool/research/library.py src/stock_tool/research/document_store.py src/stock_tool/runtime_paths.py src/stock_tool/dashboard/pages/research.py src/stock_tool/dashboard/pages/library.py src/stock_tool/dashboard/shell.py tests/test_research_library.py tests/test_document_lifecycle.py tests/test_backup_restore.py
.venv\Scripts\python.exe -m mypy --ignore-missing-imports src/stock_tool/research/library.py src/stock_tool/research/document_store.py src/stock_tool/runtime_paths.py src/stock_tool/dashboard/pages/research.py src/stock_tool/dashboard/pages/library.py src/stock_tool/dashboard/shell.py tests/test_research_library.py tests/test_document_lifecycle.py tests/test_backup_restore.py
.venv\Scripts\python.exe -m compileall -q src
```

Result: Black passed, Ruff passed, mypy reported `Success: no issues found in
9 source files`, and compileall passed.

## Candidate EXE and Smoke Test

Candidate only; the formal `release\StockTool` directory was not replaced.

- Staging path: `release\staging-sprint17\StockTool\StockTool.exe`
- Size: `24,214,609` bytes
- Modified UTC: `2026-07-27T08:25:09.3951762Z`
- SHA-256: `99B8BFD0277CFA0A775B2132A74FAF9C359950D6BC0500E17B1CA87D2F44D108`

With a fresh isolated `STOCK_TOOL_USER_DATA_DIR`, the candidate returned
`HTTP 200` and `ok` from `/_stcore/health`; `/` returned `HTTP 200`; and
`reports`, `logs`, `data/cache`, `data/ai_research`, and
`data/research_library` were writable. Cleanup ended with zero `StockTool`
processes and zero listeners on ports 8501 and 8502.

`build_exe.bat` completed the PyInstaller candidate build but exited nonzero at
the known versioned-staging delayed-expansion check. This Sprint intentionally
did not alter that batch-script issue. The existing release-asset copy and
allowlist validation were then run explicitly against the produced candidate.

## Privacy and Integrity

- Staging release content privacy scan: `0` violations.
- Staging forbidden runtime/private-file scan: `0` files.
- Source archive required inputs missing: `0`.
- Source archive forbidden entries: `0`.
- Source archive content mismatches: `0`.
- Formal EXE remains unchanged: SHA-256
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- Production portfolio CSV and processed price SQLite were checked only by
  existence, size, modified time, and SHA-256. Watchlist and settings were
  absent. All before/after records were identical.

## Source Archive and Rollback

- Archive: `release\baseline\stocktool-sprint17-20260727-source.zip`
- Entries: `283`
- SHA-256: `D313932D14D01F522C5F4336BFEA4700600B553F6BDFDD6CE593016123CBF270`
- Sidecar: `release\baseline\stocktool-sprint17-20260727-source.zip.sha256`

Rollback is to keep using the unchanged formal release and the prior accepted
Sprint 15.1.3.1 source archive. The Sprint 17 candidate is staging-only.

## Known Limitations

- The library persists the verified research note and EvidenceBundle, not a
  full OCR/document-content archive; missing local documents are explicitly
  broken references.
- Reopening a library entry exposes its stored evidence-linked version and can
  explicitly reopen the stock research workflow; saved research is never
  labelled as current market data.
- No automatic migration of existing AI cache entries, no private-document OCR,
  no cloud sync, no full research-history product, and no formal release
  promotion were performed.
- The known `build_exe.bat` versioned-staging exit-code issue remains outside
  this Sprint's approved scope.

Sprint 18 and any formal release promotion were not started.
