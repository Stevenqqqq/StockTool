# Sprint 9.1 Acceptance Handoff

**Status:** Implementation complete and ready for independent acceptance review.

## Scope And Root Causes

Sprint 9.1 is a corrective patch for Sprint 9 only. Sprint 10 was not started.

1. **Windows EXE readiness:** the launcher treated the Streamlit home page as a readiness signal. A home page can be reachable before the application is fully ready and does not verify the internal health contract.
2. **Canonical concept identity:** the Company Research/Serenity relation path could fall back to `AUTO` market identity, which made Taiwan suffixes, unresolved numeric symbols, and persisted relations ambiguous.
3. **PDF evidence citations:** report extraction used too much page text as a citation, so a displayed point was not necessarily linked to an exact supporting sentence.
4. **Concept imports:** concept and relation records were saved one at a time, allowing a malformed later record to leave a partial dataset.

## Changes

| File | Change |
| --- | --- |
| `launcher.py` | Readiness now requests `http://localhost:{port}/_stcore/health` through an explicit proxy-free opener. It requires HTTP 200 and body `ok`; only then is the browser opened. |
| `src/stock_tool/dashboard/app.py` | Company Research and Serenity share a canonical concept identity helper. It uses the existing `Symbol`/`Market` domain model, does not query with `AUTO`, and asks the user to confirm an unresolved numeric symbol's market. |
| `src/stock_tool/data/repositories.py` | Added one-transaction `upsert_concept_dataset()` repository boundary. |
| `src/stock_tool/concept_repository.py` | Validates the full concepts/aliases/relations dataset before persistence, rejects `AUTO` identities and alias collisions, then imports it atomically through `ResearchRepository`. |
| `src/stock_tool/research_reports.py` | Report points now cite a bounded, directly supporting sentence with actual page offsets. A PDF with no citable sentence reports data insufficiency. |
| `tests/test_sprint91_evidence_safety.py` | Added isolated regression coverage for launcher health semantics, identity normalization/isolation, atomic concept import, and bounded multi-page PDF evidence. |

No Provider, scoring, backtest, portfolio, risk, schema, or trading logic was changed.

## Correctness Details

### Launcher readiness

- `_health_check()` uses `urllib.request.ProxyHandler({})`, so the localhost health request bypasses configured proxies.
- The required response is exactly HTTP 200 with body `ok` after trimming transport whitespace.
- Browser launch remains after readiness; its failure is covered by a deterministic launcher regression test and does not terminate the running server.
- Packaged smoke tests validated normal port `8501` and occupied-port fallback to `8502` using an isolated `STOCK_TOOL_USER_DATA_DIR` and direct local TCP health requests.

### Canonical relation identity

- `2330` / `TWSE` and `2330.TW` / `TWSE` normalize to the same canonical identity.
- `6488` / `TPEX` and `6488.TWO` / `TPEX` normalize to the same canonical identity.
- `MU` / `US` remains `MU` / `US`.
- A Taiwan suffix conflicting with a selected market is rejected by the existing domain model.
- A bare unresolved numeric symbol does not use `AUTO` to query relations; the UI shows a market-confirmation message instead.
- SQLite persistence/reopen regression coverage verifies market-qualified relations remain distinct and a `2330` TWSE relation cannot be returned for `2330` US.

### PDF evidence

Each `ReportPoint` is built from a sentence on the same page. Its citation quote is bounded to 320 characters and `start_offset`/`end_offset` locate that exact quote in the page text. The regression suite includes a second-page citation and a no-citable-sentence case that reports `資料不足` rather than inventing evidence.

### Atomic concept dataset import

All concept keys, aliases, relation types, market-qualified identities, confidence, URLs, and ISO dates are validated before any write. The repository then writes the complete dataset through one SQLite transaction. Invalid relation and alias-collision tests verify that no concept or relation partial state remains. Re-importing a valid dataset remains idempotent.

## Test Results

All test runs used an isolated `STOCK_TOOL_USER_DATA_DIR`; no test used or cleaned real portfolio, watchlist, cache, report, log, or runtime SQLite data.

| Check | Command / scope | Result |
| --- | --- | --- |
| Sprint 9.1 targeted and related tests | `.venv\\Scripts\\python.exe -m pytest -o addopts='' tests/test_sprint91_evidence_safety.py tests/test_concept_relations.py tests/test_report_citations.py tests/test_launcher.py tests/test_exe_smoke.py tests/test_dashboard.py tests/test_research_repositories.py tests/test_database_migrations.py -q` | **76 passed** |
| Full test suite and branch coverage | `.venv\\Scripts\\python.exe -m pytest -o addopts='' --cov=stock_tool --cov-branch --cov-report=term -q` | **446 passed; 80.12%** branch coverage (gate: 80.05%) |
| Black | `.venv\\Scripts\\python.exe -m black --check launcher.py src/stock_tool/concept_repository.py src/stock_tool/data/repositories.py src/stock_tool/dashboard/app.py src/stock_tool/research_reports.py tests/test_sprint91_evidence_safety.py` | **6 files unchanged** |
| Ruff | `.venv\\Scripts\\python.exe -m ruff check` over the same six changed files | **All checks passed** |
| mypy | `.venv\\Scripts\\python.exe -m mypy --ignore-missing-imports launcher.py src/stock_tool/concept_repository.py src/stock_tool/data/repositories.py src/stock_tool/research_reports.py tests/test_sprint91_evidence_safety.py` | **Success: no issues found in 5 source files** |

## EXE Build And Smoke

`build_exe.bat` completed with the existing staging-first workflow. The verified staging package was promoted only after smoke tests and required-assets checks.

| Item | Result |
| --- | --- |
| Official EXE | `release\\StockTool\\StockTool.exe` |
| Version | `1.1.0` |
| Last write | `2026-07-15 12:16:33 +08:00` |
| Size | `23,929,128` bytes |
| SHA-256 | `C565DBCF26AC40BFCA1A9C740F4C2602AA0A9ACDDA89F55D209E34160D41F5C3` |
| Primary smoke | `8501`, `/_stcore/health` returned HTTP 200 / `ok` |
| Fallback smoke | an occupied `8501` caused startup on `8502`; health returned HTTP 200 / `ok` |
| Browser failure behavior | deterministic launcher test confirms browser-open failure does not stop the server |
| Isolated runtime writes | `reports`, `logs`, and `data\\cache` write probes succeeded |
| Cleanup | 0 `StockTool` processes and 0 listeners on 8501/8502/8510 after smoke |
| Rollback | pre-Sprint 9.1 release retained at `release\\previous\\StockTool`; an older previous release was preserved at `release\\previous\\StockTool-pre-sprint9.1-20260715-122354` |

The release required-assets check passed for `StockTool.exe`, `README.md`, `.env.example`, `使用教學_簡易版.txt`, `啟動股票工具.bat`, and bundled sample concept data.

## Privacy And User Data

- Release scan: **0 forbidden release entries** for real `.env`, Streamlit `secrets*.toml`, tokens, portfolio/watchlist files, runtime logs/reports/cache, or private key containers.
- The only `.streamlit` configuration packaged is the allowlisted `config.toml`; no Streamlit secrets TOML is present. `streamlit/runtime/secrets.py` is dependency source code, not a user secrets file.
- Real user data was read only:
  - `%LOCALAPPDATA%\\StockTool\\data\\portfolio.csv`: present, 4 rows, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` before and after validation.
  - `%LOCALAPPDATA%\\StockTool\\data\\watchlist.csv`: absent before and after validation.
- Existing Sprint 9 manual seed rows in the real runtime SQLite database were not read, removed, altered, or cleaned by Sprint 9.1.

## Source Archive

| Item | Result |
| --- | --- |
| Archive | `release\\baseline\\stocktool-sprint9.1-20260715-source.zip` |
| Entries | 218 |
| Size | 2,155,734 bytes |
| SHA-256 | `63DB2BA58B8A3AA26972780E9BE0407A775DD406ADF489D83BFB6C8CAD57AE10` |
| Sidecar | `stocktool-sprint9.1-20260715-source.zip.sha256`, hash matches archive |
| Required build inputs missing | 0 |
| Forbidden archive entries | 0 |
| Extracted content mismatches | 0 |
| Workspace content mismatches | 0 |

## Known Limitations

1. PDF extraction remains deterministic text/sentence extraction. It provides traceable evidence, not semantic verification of a report's investment claims.
2. A numeric symbol without a known market now requires explicit market confirmation for concept relations; this is deliberate to prevent cross-market contamination.
3. The release retains Streamlit's internal `secrets.py` module as a third-party dependency; it contains no user secrets. No `.streamlit/secrets.toml` is packaged.
4. No new provider, schema, retry/TTL, scoring, backtest, portfolio, risk, or AI capability was introduced.

Sprint 10 was not started.
