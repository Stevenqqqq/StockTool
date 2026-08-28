# StockTool Sprint 17.1.1 Correction Acceptance Record

## Status

Implementation and local regression verification are complete. This record is
not a formal acceptance declaration: independent CTO acceptance remains
pending because the host blocked the required isolated EXE HTTP/UI smoke.
Sprint 18, release promotion, formal publication, and twstock integration were
not started.

## Modified files

- `src/stock_tool/research/document_store.py`
- `src/stock_tool/research/library.py`
- `src/stock_tool/dashboard/pages/library.py`
- `src/stock_tool/dashboard/shell.py`
- `tests/test_research_library.py`
- `tests/test_research_library_dashboard.py`
- `SPRINT17.1.1_ACCEPTANCE.md`

## Blocker correction evidence

### DocumentStore production integration

- `ResearchDocumentLink` persists document ID, citation IDs, and optional page
  number in each `ResearchLibraryEntry`; `document_reference_ids` exposes the
  stable IDs.
- Schema version remains `1`. Loading an old entry without
  `document_references` defaults to an empty tuple; no migration touched user
  data.
- `ResearchLibrary.save()` accepts only registered, currently resolvable
  `DocumentReference` records. The production page calls
  `ResearchLibrary.resolve_document_references()`, which calls
  `DocumentStore.resolve()` on every saved link.
- Resolve status is `available` for an unchanged SHA-256, `missing` for a
  missing file, and `changed` for a SHA mismatch. Broken records clear their
  URL and the UI never renders a fake link.
- The Library UI displays Chinese document title, status, and page citation;
  missing/changed records show `文件遺失（引用失效）` or
  `文件內容已變更（引用失效）`.
- Only metadata/reference IDs and hashes are stored. No PDF/document content
  is copied and no OCR is performed.
- Default Research Library backups include `documents/documents.json` but no
  document bytes. Restore preserves the metadata/reference and existing backup
  duplicate, count, schema, size, hash, and traversal checks.

### Saved version versus current research

- The saved action is `查看保存版本`; it renders the immutable persisted
  entry and does not call a provider, `ensure_symbol_data`, cache update, or
  snapshot update.
- A separate `以此代號研究目前資料` action stores a distinct session payload.
  Only `_route_current_library_research()` converts that payload into the
  normal `SearchRequest`/Home workflow.
- The two actions have separate buttons, session keys, rerun behavior, and
  regression tests. Saved-version labels, citations, warnings, and close
  controls are Chinese.

## Tests and quality

- Targeted Research Library/DocumentStore/backup/UI path: **38 passed**.
- Full pytest: **848 passed**, one expected warning while constructing the
  hostile duplicate-ZIP fixture.
- Full branch coverage: **82.45%** (required: 82.30%).
- Black focused check: passed.
- Ruff focused check: passed.
- mypy focused check: passed for the four changed production modules.
- `python -m compileall -q src tests`: passed.
- UI regression coverage includes actual `render_library_workspace()` calls,
  rerun/session persistence, a provider callback that fails if called (zero
  calls while viewing a saved version), current-data routing, and missing/
  changed document rendering.
- Existing derived-metadata, snapshot/content/evidence hash, backup integrity,
  `None` rendering, old-library compatibility, and private-document-copy
  regressions remain green.

## Candidate EXE and hashes

- Candidate: `release\\staging-sprint17.1.1\\StockTool\\StockTool.exe`
- Candidate size: **24,228,530 bytes**.
- Candidate SHA-256:
  `A8EF705B591B9F93E469B0ACCC464F6880D6DEDAAC743AB4BE64F8570946F9F7`.
- Candidate `--version`: **1.2.2**, passed.
- Formal release SHA-256 (unchanged):
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- `build_exe.bat` completed PyInstaller but returned non-zero in its Windows
  Unicode asset-copy step. The exact allowlisted public assets were copied
  directly and `validate_release_assets()` passed; formal release was not
  touched.

## EXE/UI smoke status

- Required isolated `STOCK_TOOL_USER_DATA_DIR` HTTP health (`/_stcore/health`),
  home page, and real EXE UI clicks could not be executed: the host policy
  rejected background process launch, and Computer Use rejected the command
  wrapper needed to inject the isolated environment. Running the candidate
  without that environment would risk opening real user data, so it was not
  attempted.
- Direct candidate `--version` smoke passed. After the attempt,
  `StockTool.exe` processes: **0**; listeners on **8501/8502: 0**.
- Real user-data before/after read-only fingerprints were identical:
  `data/portfolio.csv` existed, 131 bytes,
  SHA-256 `a4d05d021c6fff6ec4c561a6b4186d53782722f5244b702f3b507f953e285bf6`;
  watchlist, ledger SQLite, and settings were absent before and after.

## Privacy and source archive

- Project privacy scan: **0 violations**.
- Candidate staging scan: **0 forbidden files** across 2,803 files.
- Source archive:
  `artifacts\\sprint17.1.1-source-verify-2\\stocktool-source.zip`
- Source archive entries: **284**.
- Source archive SHA-256:
  `3CA59EB317F4AA0F998DBA32FB76783F6844D4F98F5C0112286D2B6C9B0DDB0F`.
- Archive verification: 0 missing inputs, 0 forbidden entries, 0 content
  mismatches.

## Known limitations and rollback

- Independent CTO must still perform the isolated EXE/UI smoke, including
  saved-version provider-zero behavior, current-data separation,
  missing/changed-document UI, backup/restore and tampered-backup rejection.
- No OCR, cloud sync, new provider, installer, migration, promotion, or release
  publication was performed.
- Rollback is the unchanged formal `release\\StockTool\\StockTool.exe` and the
  Sprint 12/v1.2.2 accepted baseline.
