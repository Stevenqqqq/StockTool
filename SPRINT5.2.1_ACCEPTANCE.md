# Sprint 5.2.1 Acceptance

Date: 2026-07-13

## Scope

This is a narrow Sprint 5.2 acceptance repair. It does not start Sprint 6 and
does not change strategies, backtest calculations, trading costs, risk rules,
or portfolio-health formulas.

## Root Causes and Fixes

### Backtest result identity

`st.session_state.backtest_result` retained a completed result while the
Dashboard rendered its explanation from the current form values. Changing a
symbol, strategy, costs, allocation, maximum position, trailing stop, data
range, or source could therefore make an older result appear to use the new
settings.

`BacktestRunBinding` now freezes the exact executed form values next to the
existing result. It records the canonical symbol and market, strategy and
parameters, initial cash, allocation, maximum position, commission, tax,
slippage, trailing stop, data range, data source, cost preset, and the
immutable `BacktestSummary` used by the engine.

The Dashboard saves this binding only after a successful run and preserves the
existing `backtest_result`, `signals`, and `last_parameters` compatibility
paths. When the current form no longer matches, the retained result is shown
only with its saved summary and a clear Chinese warning that the form settings
have changed. A legacy result with no saved binding is not labelled as the
current form result and requests a re-run instead.

### Portfolio missing-data guidance

`PortfolioHealthService` produces canonical aggregate fields named
`portfolio_fundamentals`, `portfolio_indicators`, and
`portfolio_composite_scores`, while the Dashboard guidance only recognised
older per-record names. `portfolio_guidance.py` now maps all three canonical
fields to clear Chinese next steps:

- `portfolio_fundamentals`: supplement fundamentals for every holding.
- `portfolio_indicators`: obtain sufficient price history and calculate
  technical indicators.
- `portfolio_composite_scores`: complete each holding's Research Workspace
  snapshot and composite score.

The guidance test obtains `MissingData` from a real
`PortfolioHealthService.assess()` call rather than fabricating field names.

## Modified Files

- `src/stock_tool/dashboard/backtest_ui.py`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/dashboard/portfolio_guidance.py`
- `tests/test_sprint521_backtest_identity_and_guidance.py` (new)

## Regression Tests

The new tests cover:

- immutable binding of all executed backtest settings;
- symbol, strategy, cost, allocation, and maximum-position changes;
- unchanged-form display, changed-form warning, and legacy result handling;
- preservation of the saved binding while switching forms; and
- guidance for the actual canonical portfolio-health missing-data fields.

## Verification Results

| Check | Result |
| --- | --- |
| Sprint 5.2.1 targeted tests | 56 passed |
| Full pytest | 362 passed |
| Branch coverage | 78.68% (gate: 78.50%) |
| Focused Black | Passed |
| Focused Ruff | Passed |
| Focused mypy | Passed with `--ignore-missing-imports` on `app.py`, `backtest_ui.py`, and `portfolio_guidance.py` |

Focused quality commands:

```powershell
.\.venv\Scripts\python.exe -m black --check src\stock_tool\dashboard\backtest_ui.py src\stock_tool\dashboard\app.py src\stock_tool\dashboard\portfolio_guidance.py tests\test_sprint521_backtest_identity_and_guidance.py
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\dashboard\backtest_ui.py src\stock_tool\dashboard\app.py src\stock_tool\dashboard\portfolio_guidance.py tests\test_sprint521_backtest_identity_and_guidance.py
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\dashboard\app.py src\stock_tool\dashboard\backtest_ui.py src\stock_tool\dashboard\portfolio_guidance.py
```

Plain focused mypy reports the pre-existing absence of `pandas` type stubs;
the scoped `--ignore-missing-imports` run reported no project type errors.

## EXE Release Verification

- EXE: `release\StockTool\StockTool.exe`
- Built: `2026-07-13T18:27:44.9272766+08:00`
- Size: `23,859,781` bytes
- SHA-256: `93A937A823A38D64E11CBAC17D90FADACDFA3030593D8FAC176C84BE10E41248`
- Build: `cmd /c build_exe.bat` completed successfully.
- Smoke test: started with an isolated `STOCK_TOOL_USER_DATA_DIR`;
  `/_stcore/health` returned HTTP 200 with body `ok`.
- Runtime write check: isolated `reports`, `logs`, and `data\cache` directories
  were all writable.
- Cleanup: smoke runtime files were removed and no listeners remained on
  ports 8501, 8502, or 8510.

## Privacy and User Data

- Release privacy scan found no real `.env`, `secrets.toml`, token files,
  portfolio, watchlist, reports, logs, or cache. `.env.example` is the only
  permitted environment template.
- `%LOCALAPPDATA%\StockTool\data\portfolio.csv` remained at 4 data rows with
  SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`
  before and after the Sprint.
- No user watchlist file was present, and no user data was modified, moved, or
  overwritten.

## Source Archive

- Archive: `release\baseline\stocktool-sprint5.2.1-20260713-source.zip`
- SHA-256 sidecar: `release\baseline\stocktool-sprint5.2.1-20260713-source.zip.sha256`
- SHA-256: `E5E0195604CED157C8FEA450E5759A49E929F390278A482E6EE15409DA3BE52A`
- Entries: 185
- Archive verification after extraction: missing required build inputs = 0;
  forbidden entries = 0; content mismatches = 0.
- Included Sprint 5.2.1 test:
  `tests/test_sprint521_backtest_identity_and_guidance.py`.
- The archive includes only `.streamlit/config.toml` from `.streamlit`.

## Known Limitations

- A result created before Sprint 5.2.1 has no immutable form binding. The
  Backtest page intentionally does not present it as a result for the current
  form; users must re-run to create an auditable binding.
- The change is a presentation and session-state identity guard. It does not
  alter engine calculations or the existing 30/30/20/20 stock-scoring formula.

Sprint 6 has not been started.
