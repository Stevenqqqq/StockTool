# Sprint 10.3 Delivery Record: Daily Research Loop (StockTool v1.2.2)

Status: ready for independent CTO acceptance review

## Scope

Sprint 10.3 adds a deterministic, user-initiated Daily Research Loop. It does
not add providers, background refreshes, notifications, AI ranking, trading,
or a database migration. The existing v1.2.1 release and source archive remain
available as the rollback baseline.

## Modified Files

- `src/stock_tool/application/daily_research_loop.py` (new)
- `src/stock_tool/runtime_paths.py`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/dashboard/shell.py`
- `src/stock_tool/dashboard/pages/home.py`
- `src/stock_tool/__init__.py`
- `tests/test_daily_research_loop.py` (new)
- `tests/test_cli.py`
- `tests/test_exe_smoke.py`
- `tests/test_release_layout.py`
- `tests/test_regression_baseline.py`
- `tests/fixtures/sprint1_baseline.json`
- `README.md`

## Snapshot And Diff Design

- `DailyResearchSnapshot` is an additive JSON sidecar at
  `data/daily_research/last_successful_daily_brief.json` under the runtime user
  data directory. It stores only derived Daily Brief evidence, not raw prices,
  portfolios, provider exceptions, or credentials.
- Snapshot keys are canonical `market + symbol` identities. The same ticker in
  different markets therefore cannot collide.
- The comparison key intentionally excludes check-time-only changes. Repeating
  a successful refresh with identical evidence produces no false event.
- A fully successful manual refresh replaces the last successful snapshot. A
  partial, failed, unavailable, or persistence-failed refresh preserves the
  earlier snapshot and reports its older status; it never labels old evidence
  as newly fetched data.
- Missing or corrupt snapshot files safely fall back to the v1.2.1 Daily Brief
  state. A first use has no invented previous change.

## Priority Policy

The first version is deterministic and shows at most three items. Risk changes
rank first, stale or missing price evidence next, then daily price/range/volume
changes, data-repair items, and research/fundamental/composite-score coverage
changes. Ties use a stable canonical event key. Events are classified as:

- `new_change`: evidence changed since the last successful snapshot.
- `persistent_state`: an existing attention item that remains applicable.
- `data_repair`: missing, stale, or unavailable evidence requiring a concrete
  repair action.

Each rendered item contains the reason, current value, comparison baseline,
source/provenance, data/check timestamp, and a deterministic CTA. The CTA
preserves market-qualified identity when it opens research, holdings, or data
repair workspaces.

## Automated Verification

Commands and actual results:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_daily_research_loop.py -q
# 17 passed

.\.venv\Scripts\python.exe -m pytest tests\test_daily_research_loop.py tests\test_daily_brief.py tests\test_daily_home.py tests\test_price_identity_persistence.py -q
# 40 passed

.\.venv\Scripts\python.exe -m pytest tests\test_dashboard.py -q
# 28 passed

.\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_exe_smoke.py tests\test_regression_baseline.py tests\test_release_layout.py tests\test_daily_research_loop.py -q
# 29 passed

.\.venv\Scripts\python.exe -m pytest -q
# 512 passed in 82.53s

.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing
# 512 passed; total branch coverage 80.64%
```

The 80.64% branch coverage result is above the Sprint 10.3 80.50% gate.

Focused quality checks:

```powershell
.\.venv\Scripts\python.exe -m black --check src\stock_tool\__init__.py src\stock_tool\application\daily_research_loop.py src\stock_tool\dashboard\app.py src\stock_tool\dashboard\pages\home.py src\stock_tool\dashboard\shell.py src\stock_tool\runtime_paths.py tests\test_daily_research_loop.py tests\test_cli.py tests\test_exe_smoke.py tests\test_release_layout.py tests\test_regression_baseline.py
# 11 files would be left unchanged.

.\.venv\Scripts\python.exe -m ruff check src\stock_tool\__init__.py src\stock_tool\application\daily_research_loop.py src\stock_tool\dashboard\app.py src\stock_tool\dashboard\pages\home.py src\stock_tool\dashboard\shell.py src\stock_tool\runtime_paths.py tests\test_daily_research_loop.py tests\test_cli.py tests\test_exe_smoke.py tests\test_release_layout.py tests\test_regression_baseline.py
# All checks passed.

.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\application\daily_research_loop.py src\stock_tool\dashboard\app.py src\stock_tool\dashboard\pages\home.py src\stock_tool\dashboard\shell.py src\stock_tool\runtime_paths.py
# Success: no issues found in 5 source files.
```

## Deterministic Five-Session Replay

`tests/test_daily_research_loop.py` executes the following isolated sequence:

1. First successful refresh creates a baseline without manufacturing a prior
   change.
2. A second identical refresh produces zero false-positive events.
3. Multiple changes are ranked deterministically and limited to the same top
   three events on replay.
4. A partial/stale refresh keeps the prior successful snapshot and clearly
   marks the result as partial rather than current.
5. A new service instance reloads the sidecar and compares the next refresh
   correctly after a simulated restart.

Additional tests cover TWSE/TPEX/US identity separation, missing composite
scores, snapshot corruption, stale/provenance timestamps, CTA routing, manual
refresh integration, and an isolated Streamlit `AppTest` restart path.

## UI Verification

An isolated source Streamlit runtime on port 8510 returned `HTTP 200` with
body `ok`. Manual checks at 1366x768, 1920x1080, and a 390px narrow window
confirmed the Daily Research Loop is present before the existing present-state
cards, uses a single-column narrow layout, and has no horizontal overflow,
truncation, overlap, loading state, or unsafe HTML dependency. The page was
checked with market-qualified fixture holdings and persisted snapshot evidence.

## EXE Build And Smoke Tests

- `build_exe.bat` created a staging-first v1.2.2 package at
  `release/staging/StockTool`.
- Staging verification passed with `StockTool.exe --version` returning `1.2.2`.
- Launcher health smoke passed on normal port 8501 and, with 8501 deliberately
  occupied, on fallback port 8502. Both readiness probes returned `HTTP 200`
  with body `ok`.
- After staging verification, `publish_release.bat` promoted the package using
  its required-public-asset validation. The final release smoke on 8501 also
  returned `HTTP 200` / `ok`.
- In isolated `STOCK_TOOL_USER_DATA_DIR` directories, `reports`, `logs`,
  `data/cache`, and `data/daily_research` were each verified writable.
- All smoke-test StockTool processes and listeners on 8501, 8502, and 8510
  were stopped after verification.
- The isolated smoke runtime and archive-extraction directories under `%TEMP%`
  were removed after the checks.

Final EXE:

| Item | Value |
| --- | --- |
| Path | `release/StockTool/StockTool.exe` |
| Version | `1.2.2` |
| Modified | `2026-07-17 23:40:22 +08:00` |
| Size | `24,005,474` bytes |
| SHA-256 | `2F64707B1293F4C5827EAD43980154CB5BCAB50EA31D4DDCAE236163951F8CB2` |

## Release Privacy Scan

`validate_release_assets(release/StockTool)` passed. Recursive release scans
found no real `.env`, `secrets.toml`, `portfolio.csv`, `watchlist.csv`, runtime
cache, logs, reports, or SQLite user data. The only packaged Streamlit setting
is the allowlisted `_internal/.streamlit/config.toml`. The bundled
`streamlit/runtime/credentials.py` is application source code, not a supplied
credential file or private user data.

## Real User Data Integrity

Only read-only before/after checks were performed. No real runtime files were
used for tests or smoke runs.

| File | Before | After |
| --- | --- | --- |
| `%LOCALAPPDATA%/StockTool/data/portfolio.csv` | exists, 4 rows, `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` | identical |
| `%LOCALAPPDATA%/StockTool/data/watchlist.csv` | absent | absent |
| `%LOCALAPPDATA%/StockTool/data/processed/stock_data.sqlite` | 249,856 bytes, `71485B3A141654CB08A085EE043871F484DDE52A1765B3CDF9B3F9761D9B914E` | identical |

## Source Archive

| Item | Value |
| --- | --- |
| Archive | `release/baseline/stocktool-sprint10.3-20260717-source.zip` |
| Sidecar | `release/baseline/stocktool-sprint10.3-20260717-source.zip.sha256` |
| Entries | 229, including the archive manifest |
| SHA-256 | `008E082F13DC9ECA41180DCAA1FE257234E2AACF67DD6826558BCEB65487F281` |

The archive was created through the existing allowlisted archive builder and
verified with keyword-only `verify_source_archive(archive_path=...,
extracted_root=...)`: required build inputs missing `0`, forbidden entries `0`,
and content mismatches `0`.

## Rollback

- The previous v1.2.1 executable release was preserved at
  `release/previous/StockTool/` before promotion.
- The v1.2.1 source baseline remains at
  `release/baseline/stocktool-sprint10.2.1-20260716-source.zip` with its
  existing SHA-256 sidecar.
- Rolling back consists of stopping StockTool, preserving the current release
  separately, and restoring the preserved `release/previous/StockTool`
  directory. The Daily Research sidecar is additive and may be removed from an
  isolated runtime if a rollback requires a clean v1.2.1 state.

## Known Limitations And Deliberate Non-Goals

- There is no scheduler, background refresh, Windows notification, email,
  news aggregation, or automatic network activity on launch.
- The loop ranks only deterministic evidence already available to Daily Brief;
  it is not an AI prediction, investment recommendation, or order system.
- A partial provider result deliberately does not overwrite the last successful
  snapshot. The UI therefore reports partial/stale status instead of claiming
  a fresh market update.
- Snapshot persistence is a sidecar and does not migrate historic runtime
  databases or invent missing market identities.
- Sprint 11 and all subsequent roadmap work remain unstarted.
