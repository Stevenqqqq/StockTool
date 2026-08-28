# Sprint 13 Acceptance Record

**Status:** Implementation complete and ready for independent acceptance review.

## Scope And Recovery Boundary

Sprint 13 adds an explicit, opt-in corporate-actions contract and aligns
benchmark return-basis policy for research backtests. It does not begin Sprint
14, alter the formal `release\StockTool` package, modify trading signals,
change T+1 execution, alter costs, or touch real user data.

## Implemented Contract

### Price policy and return basis

- `raw_price_with_explicit_actions`: permits source-backed split and cash
  dividend events.
- `adjusted_total_return`: rejects explicit action events to prevent double
  counting.
- `unknown`: fails closed if explicit actions are supplied.
- Strategy and benchmark return bases are explicit `price_return` or
  `total_return`. A mismatch produces structured
  `benchmark_return_basis_mismatch`; the report does not show two benchmark
  result sets.
- Existing no-action runs retain their legacy equity curve behavior.

### Corporate action data and point-in-time behavior

`CorporateAction` is immutable and market-qualified through the existing
`Symbol` / `Market` domain model. Its local CSV import contract requires
`symbol`, `market`, `action_type`, `effective_date`, `available_date`, and
`source`; it also persists provenance, confidence, completeness, and notes.

- Split events apply before the day's pending-order execution only when the
  action was available on or before its effective date. Non-integral reverse
  split results are recorded as unavailable without rounding.
- Cash dividends capture the prior-close eligible quantity on the effective
  date and credit cash only on the payable date, after configured tax.
- Missing, delayed, missing-payable-date, or unmatched-market events are
  audited as unavailable rather than inferred or applied early.
- Explicit actions require market-qualified prices. Duplicate symbol/date rows
  across different markets fail closed because the existing portfolio ledger
  is still symbol-keyed and cannot safely represent that ambiguity.

### Auditability and reports

`BacktestResult` now carries a corporate-action audit and daily cash plus
holdings reconciliation. Excel and HTML reports include both tables. The
reproducibility manifest hashes both outputs in addition to the established
trade, equity, alert, and metric outputs. Report packages use a single
canonical benchmark comparison and record its return basis, price policy, and
source.

## Modified Files

- `src/stock_tool/data/corporate_actions.py`
- `src/stock_tool/data/__init__.py`
- `src/stock_tool/backtest/engine.py`
- `src/stock_tool/backtest/metrics.py`
- `src/stock_tool/backtest/portfolio.py`
- `src/stock_tool/backtest/__init__.py`
- `src/stock_tool/application/reporting.py`
- `src/stock_tool/reports/models.py`
- `src/stock_tool/reports/excel.py`
- `src/stock_tool/reports/html.py`
- `README.md`
- `tests/test_corporate_actions.py`
- `tests/test_adjusted_price_policy.py`
- `tests/test_report_manifest.py`
- `tests/fixtures/corporate_actions_golden.csv`

## Test-Driven Evidence

The initial Sprint 13 test run failed at collection with:

```text
ModuleNotFoundError: No module named 'stock_tool.data.corporate_actions'
```

The subsequent controlled golden fixtures verify:

- 2-for-1 split quantity/cost-basis continuity and daily reconciliation;
- reverse split fractional-quantity refusal without rounding;
- ex-date eligibility, payable-date dividend credit, and tax deduction;
- unavailable date refusal and duplicate action de-duplication;
- CSV import metadata and cross-market duplicate symbol/date fail-closed
  behavior;
- adjusted-price double-count prevention and unknown-policy refusal;
- explicit benchmark return-basis mismatch behavior;
- report manifest hashes for corporate action audit and daily reconciliation;
- report-level canonical benchmark behavior.

## Verification

### Targeted tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest.py tests/test_benchmark_golden.py tests/test_corporate_actions.py tests/test_adjusted_price_policy.py tests/test_point_in_time_universe.py tests/test_fundamental_available_date.py tests/test_reports.py tests/test_report_manifest.py -q -rA
# 80 passed
```

### Full pytest and coverage

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing
# 587 passed in 101.01s
# Total branch coverage: 81.23%
```

The measured coverage exceeds the configured 78.50% gate.

### Focused quality checks

```powershell
.\.venv\Scripts\python.exe -m black --check src/stock_tool/data/corporate_actions.py src/stock_tool/backtest/engine.py src/stock_tool/backtest/portfolio.py src/stock_tool/backtest/metrics.py src/stock_tool/application/reporting.py src/stock_tool/reports/models.py src/stock_tool/reports/excel.py src/stock_tool/reports/html.py tests/test_corporate_actions.py tests/test_adjusted_price_policy.py tests/test_report_manifest.py
# 11 files would be left unchanged.

.\.venv\Scripts\python.exe -m ruff check src/stock_tool/data/corporate_actions.py src/stock_tool/backtest/engine.py src/stock_tool/backtest/portfolio.py src/stock_tool/backtest/metrics.py src/stock_tool/application/reporting.py src/stock_tool/reports/models.py src/stock_tool/reports/excel.py src/stock_tool/reports/html.py tests/test_corporate_actions.py tests/test_adjusted_price_policy.py tests/test_report_manifest.py
# All checks passed.

.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src/stock_tool/data/corporate_actions.py src/stock_tool/backtest/engine.py src/stock_tool/backtest/portfolio.py src/stock_tool/backtest/metrics.py src/stock_tool/application/reporting.py src/stock_tool/reports/models.py src/stock_tool/reports/excel.py src/stock_tool/reports/html.py
# Success: no issues found in 8 source files.
```

## Staging EXE

`build_exe.bat` completed using the existing staging-first flow. Formal
`release\StockTool` was not replaced.

- Staging EXE: `release\staging\StockTool\StockTool.exe`
- Version: `1.2.2`
- Size: `24,080,171` bytes
- Last write UTC: `2026-07-19T16:38:56.0707760Z`
- SHA-256: `1EAD38FEA2E958BF60C9CDDCFD1013E3D0908FD685ED6BDF265C0C70F92D52DB`

The isolated runtime smoke test returned `HTTP 200` and `ok` from
`/_stcore/health`; the homepage returned HTTP 200. `reports`, `logs`, and
`data/cache` were each successfully written under an isolated
`STOCK_TOOL_USER_DATA_DIR`. The launcher and Streamlit child processes were
stopped; no StockTool process or 8501/8502 listener remained.

The initial PowerShell `Invoke-WebRequest` readiness loop did not observe the
health endpoint despite the server being live. A subsequent no-proxy
`curl.exe` probe returned `HTTP 200` / `ok`, and the server log confirmed
Uvicorn on `localhost:8501`. This is recorded as a test-harness observation,
not a product failure. The isolated temporary smoke directory could not be
removed by the execution sandbox's destructive-command policy; it contains
only test runtime files outside the release and user-data locations.

The formal EXE remains unchanged:

- `release\StockTool\StockTool.exe`
- SHA-256: `AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F`

## Release Privacy Scan

The staging release contains no `.env`, `secrets*.toml`, `portfolio.csv`,
`watchlist.csv`, `stock_data.sqlite`, `reports`, `logs`, or `data/cache`.

The text-pattern scan reported 14 packaged dependency source files containing
generic terms such as `token`, `authorization`, or `password`; no secret value
was emitted, and these are Streamlit/jsonschema library code rather than
runtime credentials. Public assets and `data/sample` remain included.

## User-Data Integrity

All checks were read-only against `%LOCALAPPDATA%\StockTool`.

| File | Before / After |
|---|---|
| `data\portfolio.csv` | exists, 4 rows, 131 bytes, `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `data\watchlist.csv` | absent |
| `data\processed\stock_data.sqlite` | exists, 315,392 bytes, `FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C` |
| `settings.json` | absent |

Before and after metadata and hashes are identical.

## Source Archive

- Archive: `release\baseline\stocktool-sprint13-20260720-source.zip`
- Entries: 251
- SHA-256: `453B5E1F7A5EB2B96E1B762944BB15613BC470996C9465901B7760AA1B5912A8`
- Sidecar: `release\baseline\stocktool-sprint13-20260720-source.zip.sha256`

The archive was extracted and verified via keyword-only
`verify_source_archive(archive_path=..., extracted_root=...)` with:

- missing required build inputs: 0;
- forbidden entries: 0;
- content mismatches: 0.

It includes the Sprint 13 corporate-action module, golden fixture, new tests,
and `.streamlit/config.toml` only from the Streamlit directory.

## Rollback And Known Limitations

Rollback is simply to retain the existing formal `release\StockTool` package;
Sprint 13 produced only a staging candidate and did not promote it.

- Corporate-action data is local/imported and does not claim comprehensive
  exchange coverage.
- The portfolio ledger remains symbol-keyed. In explicit-action mode,
  same-symbol, same-date multi-market price rows are rejected rather than
  guessed; a future market-qualified portfolio ledger belongs to a later
  Sprint.
- No fractional share conversion, withholding jurisdiction logic, rights
  issues, mergers, spinoffs, or full corporate-action provider are implemented.
- Benchmark comparison remains unavailable without compatible explicit basis
  metadata or exact date alignment; no forward fill is used.
