# Sprint 4.1.2.1 Acceptance

## Scope and Baseline

This is a minor acceptance repair for Sprint 4.1.2 only. Sprint 5 was not started. No backtest, stock-scoring, risk-rule, or provider core semantics were changed.

- Formal baseline: `SPRINT4.1.1_ACCEPTANCE.md`
- Prior Sprint 4.1.2 coverage: 77.11%
- Python: 3.11.9
- Real portfolio before repair: 4 rows, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`

## Root Causes

### Affected identity display

`build_portfolio_data_gaps()` received only free-form `MissingData` and incorrectly displayed every portfolio position in every gap row. It had no structured record of the position actually affected.

### Source archive reproducibility

Sprint 4.1.2's manual archive allowlist omitted `.streamlit/config.toml`, despite `build_exe.bat` passing the `.streamlit` directory to PyInstaller with `--add-data`.

## Repairs

### Structured affected identity

`src/stock_tool/portfolio_analytics.py` now defines:

```text
PortfolioIdentity(symbol, market)
PortfolioDataGap(missing_data, affected_identities)
```

`PortfolioRiskInputResult` carries `data_gaps`. Risk-input preparation creates a `PortfolioDataGap` for each individual identity with insufficient volatility or drawdown history. `build_portfolio_data_gaps()` accepts `structured_gaps` and uses only that metadata:

- a position-specific gap shows only its own `symbol/market`;
- same symbol in TWSE and US remains separate;
- `portfolio_fx` is shown as `整體投資組合`;
- gaps without identity metadata are shown as `無法判定`;
- no reason-string parsing occurs;
- positions, prices, and risk-input frames are not mutated.

Dashboard wiring now forwards `risk_inputs.data_gaps` to the data-gap table.

### Reproducible source archive

Added `src/stock_tool/release_archive.py`, an allowlisted archive builder with:

- explicit root files and source-tree inputs;
- all `.streamlit`, `src`, and `data/sample` build inputs;
- a `SOURCE_ARCHIVE_MANIFEST.json` containing required build inputs and SHA-256 hashes;
- ZIP-slip-safe extraction validation;
- privacy/runtime exclusions for real `.env`, user portfolio/watchlist, cache, logs, reports, build output, virtual environments, bytecode, and tool caches;
- SHA-256 sidecar generation.

The manifest test verifies `build_exe.bat` rebuild inputs, including `.streamlit/config.toml`, are present in the ZIP. The final archive was extracted into a temporary directory and checked for required inputs, forbidden entries, and content-hash mismatches.

## Modified Files

- `src/stock_tool/portfolio_analytics.py`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/release_archive.py`
- `tests/test_portfolio_analytics.py`
- `tests/test_release_archive.py`

## New Regression Tests

- only the affected holding is shown for a missing volatility input;
- same code in different markets remains distinct;
- `portfolio_fx` is portfolio-wide;
- no structured identity shows `無法判定`;
- reason text containing a ticker is not parsed;
- positions, prices, and risk-input frames remain unchanged;
- source archive includes `.streamlit/config.toml` and all required EXE build inputs;
- source archive extraction validates required files, manifest hashes, and exclusions.

## Validation

### Targeted tests

```text
.venv\Scripts\python.exe -m pytest tests/test_portfolio_analytics.py tests/test_release_archive.py tests/test_dashboard.py::test_dashboard_auto_loads_bundled_fundamentals tests/test_dashboard.py::test_dashboard_portfolio_price_context_merges_sqlite_and_current_session tests/test_dashboard.py::test_dashboard_price_merge_keeps_market_identities_and_current_wins_same_identity tests/test_sprint32_portfolio.py -q
```

Result: **27 passed**.

### Full pytest and branch coverage

- Full pytest: **320 passed**.
- Branch coverage: **77.31%**.
- Exact coverage gate: `python -m coverage report --precision=2 --fail-under=77.11` passed.

`pytest-cov --cov-fail-under=77.11` displayed a known integer-rounding comparison defect (`77 < 77`) despite the same run reporting 77.31%. The exact `coverage` command above validates the required decimal threshold without lowering it.

### Quality checks

- Black focused check for new/changed analytics, archive, and test files: passed.
- Ruff focused check including `dashboard/app.py`: passed.
- Focused mypy with `--ignore-missing-imports` for `portfolio_analytics.py` and `release_archive.py`: passed.
- Existing whole-file Black and mypy debt in the legacy Dashboard remains outside this narrow repair and was not hidden or reformatted wholesale.

## EXE Build and Smoke Test

`build_exe.bat` was run. Its controlling terminal exceeded the 120-second session limit while PyInstaller continued in its child process; the build was subsequently verified complete from the new release artifact.

- EXE: `release/StockTool/StockTool.exe`
- Build time: `2026-07-12 17:59:58` local
- Size: `23,786,559` bytes
- SHA-256: `1564748ABF996E94CDD2A468A2A0B7339C890EEF73675A01BEB8D0F94D8BF848`
- Health smoke: `http://127.0.0.1:8501/_stcore/health` returned `ok`, HTTP 200.
- Write/remove probes passed for `%LOCALAPPDATA%\StockTool\reports`, `%LOCALAPPDATA%\StockTool\logs`, and `%LOCALAPPDATA%\StockTool\data\cache`.
- Smoke-generated logs and probe files were removed. No StockTool process or 8501/8502 listener remained.

## Privacy and User Data Verification

- Release private-file scan: 0 real `.env`, `portfolio.csv`, `watchlist.csv`, runtime reports/logs, or cache files.
- Release controlled-text token scan: 0 hits.
- Real portfolio after repair: 4 rows, SHA-256 unchanged at `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
- No real watchlist was present before or after the repair.

## Source Archive

- Archive: `release/baseline/stocktool-sprint4.1.2.1-20260712-source.zip`
- SHA-256 sidecar: `release/baseline/stocktool-sprint4.1.2.1-20260712-source.zip.sha256`
- Size: `1,671,209` bytes
- Entries: `169` including `SOURCE_ARCHIVE_MANIFEST.json`
- SHA-256: `D5440112374D9167BD9C9F7DA83C32193411468A588A38F4C2196ACA2D6ED43B`
- `.streamlit/config.toml`: present.
- Extracted archive verification: missing build inputs `0`; forbidden entries `0`; content mismatches `0`.

## Known Limitations

1. A missing-data item without structured metadata remains deliberately `無法判定`; the system does not infer an identity from prose.
2. Legacy callers of `build_portfolio_data_gaps()` that do not provide structured gaps receive explicit unknown/portfolio-wide labels rather than inferred holdings.
3. The archive is source-reproducible, but rebuilding still requires a local Python 3.11 environment and installing declared dev dependencies.
4. Existing broad Dashboard formatting and type-checking debt is not part of Sprint 4.1.2.1.

## Sprint Boundary

Sprint 4.1.2.1 is complete. Sprint 5 was **not started**.
