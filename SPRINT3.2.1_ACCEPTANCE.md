# Sprint 3.2.1 Acceptance

Date: 2026-07-11

## Verdict

Accepted. This is a Sprint 3.2 acceptance repair only. Sprint 4 was not started.

## Crash Recovery State

The workspace was inspected after the interruption instead of being reset. The partial
Sprint 3.2.1 changes in `portfolio_health.py`, `portfolio_stress.py`, `dashboard/app.py`,
`runtime_paths.py`, and `build_exe.bat` were retained and completed. At resumption:

- `SPRINT3.2.1_ACCEPTANCE.md` and the Sprint 3.2.1 source archive did not exist.
- `release/StockTool/StockTool.exe` was still the Sprint 3.2 executable.
- Two Dashboard regressions failed.
- No assumption was made that prior tests or build outputs were valid.

The real user portfolio at `%LOCALAPPDATA%\\StockTool\\data\\portfolio.csv` was not edited,
moved, or overwritten by this repair.

## Regressions Fixed

### Bundled fundamentals score unexpectedly became `None`

Root cause: `_set_fundamentals_state()` filtered score rows through market qualification.
Bundled fundamentals have no market column and there may be no price identity map during
initialization, so the filtering returned no rows and discarded the existing score output.

Fix: keep the existing, unqualified score frame for the legacy fundamentals view when no
reliable market map exists. Portfolio health independently qualifies it against canonical
price identities, so it never treats an unknown market as a canonical portfolio score.

### SQLite price won over the current session price

Root cause: a legacy SQLite row has `market=UNKNOWN`, while the current one-symbol session
row had no market column. The session row was rejected, leaving only the SQLite value.

Fix: source metadata can qualify a session frame only when it contains exactly one non-empty
symbol. Mixed frames without a market column remain unqualified. Price merge still deduplicates
only on `symbol + market + date`; known identities sort before `UNKNOWN` for deterministic
display, and a later current-session row wins only when the complete identity matches.

## Delivered Behavior

- Price identity is canonical `symbol + market`; `TWSE`, `TPEX`, and `US` are distinct.
- Legacy SQLite rows without a market remain `UNKNOWN`; no market is inferred from a later
  query for a different symbol.
- A mixed `00935/TWSE` and `DRAM/US` frame cannot be relabeled as one session market.
- Risk inputs use the latest valid indicator per canonical identity and apply each aggregate
  portfolio weight once. Historical row count does not change the result.
- Position quality uses only held identities, uses base-currency weights, ignores non-holdings,
  and reports missing composite scores instead of calculating a substitute score.
- Dashboard builds canonical composite stock-score inputs before calling portfolio health; a
  fundamental score is not passed as a composite score.
- `USD/TWD +10%` means one USD exchanges for 10% more TWD. TWD-base valuations adjust USD
  positions by `1.10`; USD-base valuations adjust TWD positions by `1 / 1.10`.
- Market-decline UI options are limited to `TWSE`, `TPEX`, and `US`, and are shown only for
  that scenario.
- `build_exe.bat` runs repeat-safe legacy user-data migration before destructive release
  cleanup. A manifest is written under the runtime backup path; unsafe migration outcomes stop
  the cleanup.

## Modified Files

- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/portfolio_health.py`
- `src/stock_tool/portfolio_stress.py`
- `src/stock_tool/runtime_paths.py`
- `build_exe.bat`
- `tests/test_dashboard.py`
- `tests/test_sprint32_portfolio.py`
- `tests/test_runtime_paths.py`

The focused Ruff run also found and this repair corrected a concrete Dashboard `F821`:
the SQLite success caption referenced undefined `all_prices`; it now reports
`len(result.data)`.

## New Regression Coverage

- Single-symbol session market fallback is scoped and mixed unmarked data is rejected.
- Mixed TWSE/US price identities remain separate; reverse current-frame ordering is deterministic.
- Current session data wins only for the same `symbol + market + date` identity.
- Weighted volatility and drawdown remain `0.30` for 50/50 assets at `0.10` and `0.50`, even
  when one asset has 100 history rows.
- Position quality is weighted, excludes an outside symbol, selects the latest duplicate score,
  and reports missing held scores.
- Dashboard composite-score assembly supplies usable canonical stock scores to health.
- USD/TWD stress covers TWD base, USD base, positive, negative, and zero shocks without
  mutating valuation inputs.
- Market-decline options include TWSE/TPEX/US only.
- Legacy release migration writes a manifest, preserves newer runtime portfolio data, and blocks
  destructive cleanup for invalid legacy data.

## Verification

Targeted tests:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_sprint32_portfolio.py tests/test_runtime_paths.py tests/test_dashboard.py::test_dashboard_auto_loads_bundled_fundamentals tests/test_dashboard.py::test_dashboard_portfolio_price_context_merges_sqlite_and_current_session tests/test_dashboard.py::test_dashboard_session_market_fallback_is_scoped_to_one_symbol_only tests/test_dashboard.py::test_dashboard_price_merge_keeps_market_identities_and_current_wins_same_identity tests/test_dashboard.py::test_dashboard_stress_market_options_only_apply_to_market_decline -q
```

Result: `28 passed`.

Full suite:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Result: `291 passed`.

Coverage:

```powershell
.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term -q
```

Result: `73.83%`, above the Sprint 3.2 baseline of `73.50%` and project gate of `72.63%`.

Focused changed-file quality checks:

```powershell
.venv\Scripts\python.exe -m black --check src\stock_tool\dashboard\app.py src\stock_tool\portfolio_health.py src\stock_tool\portfolio_stress.py src\stock_tool\runtime_paths.py tests\test_dashboard.py tests\test_sprint32_portfolio.py tests\test_runtime_paths.py
.venv\Scripts\python.exe -m ruff check src\stock_tool\dashboard\app.py src\stock_tool\portfolio_health.py src\stock_tool\portfolio_stress.py src\stock_tool\runtime_paths.py tests\test_dashboard.py tests\test_sprint32_portfolio.py tests\test_runtime_paths.py
.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\portfolio_health.py src\stock_tool\portfolio_stress.py src\stock_tool\runtime_paths.py
```

Result: Black passed, Ruff passed, and mypy reported `Success: no issues found in 3 source files`.

## EXE Delivery

Build command:

```powershell
.\build_exe.bat
```

Result: succeeded after its migration preflight. The new EXE is newer than the Sprint 3.2
artifact and has a different SHA-256.

- EXE: `C:\Users\steve\OneDrive\Documents\股票\release\StockTool\StockTool.exe`
- Timestamp: `2026-07-11T21:20:50.0600172+08:00`
- Size: `23,748,991` bytes
- SHA-256: `8A1BE2DA63450069BB19851DB238A60C23C875A772770B19B0EFF4CC91507AEF`

Smoke test used an isolated `STOCK_TOOL_USER_DATA_DIR` under the workspace:

- `http://127.0.0.1:8501/_stcore/health` returned HTTP 200 with body `ok`.
- `reports`, `logs`, and `data/cache` passed write/read probes.
- All test `StockTool` processes and ports 8501/8502 were stopped afterward.
- The isolated smoke runtime, including generated reports/logs/cache, was removed afterward.

## User Data Migration Validation

`prepare_release_user_data_migration()` was tested with a temporary legacy release containing
`portfolio.csv`. It creates a JSON manifest, retains the legacy source, does not overwrite an
already newer runtime portfolio, and raises before destructive release cleanup when the legacy
portfolio is invalid. The build script invokes this preflight before `rmdir /s /q
"%RELEASE_DIR%"`.

## Release Privacy Scan

The rebuilt `release/StockTool` contains application assets, `data/sample`, `.env.example`, and
the PyInstaller runtime only. The scan found no real `.env`, token file, portfolio, watchlist,
runtime reports, logs, cache, processed data, or `error.log` in the release artifact.

## Source Archive

- Archive: `C:\Users\steve\OneDrive\Documents\股票\release\baseline\stocktool-sprint3.2.1-20260711-source.zip`
- Sidecar: `C:\Users\steve\OneDrive\Documents\股票\release\baseline\stocktool-sprint3.2.1-20260711-source.zip.sha256`
- Size: `1,309,058` bytes
- SHA-256: `3C0E6CE2ABEE4EB50DCB37A866B65574F2C36E6F8E260E084315C987EA1FFAF4`

## Remaining Limits

- Legacy SQLite price rows without a market remain `UNKNOWN`; they are intentionally not used as
  market-qualified valuation inputs until a reliable migration or source mapping exists.
- Portfolio health remains a deterministic research measure, not a forecast, external AI output,
  or trading instruction.
- Live FX sourcing, full historical market migration, and broader Dashboard redesign remain
  outside this Sprint and are not Sprint 4 work performed here.

No Sprint 4 work was started.
