# Sprint 17.1.3 Correction — Implementation Evidence

Date: 2026-07-28

Scope: correction only for safe multi-document Research Library registration. No Sprint 18 work, twstock integration, promotion, or formal release was performed.

## Modified files

- `src/stock_tool/application/research_library.py`
  - Adds `_optional_text()` and uses it for path, title, and document ID inputs.
  - `None`, omitted, and whitespace-only document IDs generate `doc-<uuid>` IDs.
  - `None`, omitted, and whitespace-only titles use the original file name.
- `src/stock_tool/research/document_store.py`
  - Rejects non-string/blank explicit metadata instead of coercing it to the string `"None"`.
- `tests/test_research_library_application.py`
  - Covers optional ID/title inputs, sequential A/B registration, metadata-only persistence, and preserving a saved A citation after B is registered.
- `tests/test_research_document_workspace.py`
  - Covers the actual dashboard workspace path for registering and selecting two documents with page links.

## Blocker correction evidence

1. Optional defaults
   - The application service no longer calls `str(document_id).strip()` or `str(title).strip()`.
   - Targeted regression registers omitted, `None`, and whitespace IDs; each is a distinct `doc-<uuid>` and never `None`.
   - Omitted, `None`, and whitespace titles resolve to the source file name.

2. Safe multi-document references
   - Targeted regression registers `first.pdf` and `second.pdf`, verifies two `documents.json` records, and confirms the saved first entry still resolves to `first.pdf` as `available` after the second registration.
   - The isolated candidate-EXE dashboard workflow registered `reference-a.pdf` and `reference-b.pdf`; metadata inspection found two distinct IDs, schema-2 entry references for both IDs, and pages `[7, 8]`.
   - `documents.json` did not contain either synthetic PDF's content.

3. Existing integrity and compatibility protections
   - The targeted Research Library suite includes schema-2 document-reference hashing, hostile tamper, legacy-unverified, backup, and DocumentStore regression coverage.
   - Full pytest passed, including those tests.

## Commands and results

| Check | Command / result |
| --- | --- |
| Targeted Research Library/UI | `.venv\Scripts\python.exe -m pytest tests/test_research_library_application.py tests/test_research_document_workspace.py tests/test_research_library.py tests/test_document_lifecycle.py tests/test_research_library_dashboard.py -q` — **45 passed** |
| Full pytest + branch coverage | `.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing` — **864 passed, 1 known duplicate-ZIP-entry test warning, 82.54% total branch coverage** (threshold 78.50%) |
| Changed-file Black | `.venv\Scripts\python.exe -m black --check` on the four modified source/test files — pass |
| Ruff | `.venv\Scripts\python.exe -m ruff check src tests` — pass |
| Focused mypy | `.venv\Scripts\python.exe -m mypy src\stock_tool\application\research_library.py src\stock_tool\research\document_store.py` — pass |
| Compile | `.venv\Scripts\python.exe -m compileall -q src` — pass |
| Candidate build | `STOCK_TOOL_STAGING_PARENT=release\staging-sprint17.1.3` then `cmd /c build_exe.bat` — exit 0 |

The first invocation of pytest used the system Python 3.10 and failed at collection because the project requires Python >=3.11 (`datetime.UTC`). All recorded results above used the project `.venv` Python 3.11.9.

Full-repository `black --check src tests` remains non-green because it reports 30 existing, out-of-scope files that would be reformatted. They were not modified in this correction; changed-file Black is green.

## Candidate EXE and UI smoke

- Candidate: `release/staging-sprint17.1.3/StockTool/StockTool.exe`
- Isolated user data: `artifacts/sprint17.1.3-exe-smoke/user-data`
- HTTP health: `/_stcore/health` returned 200; homepage returned 200.
- Actual Streamlit UI workflow:
  1. Opened isolated AAPL research workspace.
  2. Registered two original local synthetic PDF paths through the dashboard, leaving titles blank.
  3. Selected both documents, set pages 7 and 8, and saved the immutable research version.
  4. Restarted the candidate EXE, opened Research Library, and chose `查看保存版本`.
  5. The saved view rendered both document titles as `可用` with `第 7 頁` and `第 8 頁`, plus saved claims/citations.
- Provider-free saved-view behavior, current-data routing, broken-document rendering, schema-2 hash/tamper rejection, legacy-unverified behavior, and backup protections are covered by the passing Research Library/dashboard regression suite. The isolated EXE smoke exercised the visible saved-view path; it does not instrument the frozen provider call count.

## Privacy, archive, and hashes

- Project privacy scan: `project_privacy_violations(Path.cwd())` — `()`.
- Candidate forbidden-file scan (`.env`, settings, portfolio/watchlist, ledger/cache) — 0 files.
- Source archive: `release/staging-sprint17.1.3-source.zip`
  - Created with `python -m stock_tool.release_archive --root . --output ...`.
  - Verified with `verify_source_archive(...)`: no missing build inputs, forbidden entries, or content mismatches.
- SHA-256:
  - candidate EXE: `49DB2ECF2C9333F50F11EE37046A6A9DCB708F144EF31D2FE1882A517B87791E`
  - source archive: `4128492FFCB0587D1AECD2D3136598CFCD7628E786F2BF6D43A30B2366E8957C`
  - unchanged formal EXE: `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`

## Real-user-data guard and rollback

- Before/after fingerprints for `C:\Users\steve\AppData\Local\StockTool` matched:
  - `data/portfolio.csv`: exists, 131 bytes, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`
  - `data/watchlist.csv`, `data/ledger/portfolio_ledger.sqlite`, and `settings.json`: absent before and after.
- All smoke writes used the isolated directory above. No real user files were moved, overwritten, or deleted.
- Final process audit: `StockTool` processes = 0; listeners on 8501/8502 = 0.
- Rollback: retain the formal `release/StockTool/StockTool.exe`; delete only the isolated `release/staging-sprint17.1.3` candidate and smoke artifacts if the candidate is rejected. No promotion was performed.

## Known limitations

- Full-repository Black remains blocked by 30 pre-existing formatting differences outside this correction's scope.
- This document records implementation evidence only. It does **not** declare CTO acceptance; independent CTO review remains required.
