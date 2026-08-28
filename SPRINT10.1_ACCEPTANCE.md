# Sprint 10.1 Acceptance Record

**Status:** ready for independent acceptance review

This document records the Sprint 10.1 corrective implementation and the
verification performed against the Sprint 9.1 / StockTool v1.1.0 formal
baseline. v1.2.0 is not declared independently accepted by this document.
Sprint 11 was not started.

## Scope

Sprint 10.1 addresses only the five reported Sprint 10 acceptance blockers:

1. Excel formula-injection protection for external and user-provided text.
2. Complete, private, deterministic report manifest hashing.
3. A single canonical benchmark result across the report package and exporters.
4. Safe normalization of benchmark and equity-curve dates.
5. Deterministic hashing of sets across independent Python processes.

No new provider, strategy, scoring formula, backtest rule, portfolio rule,
risk rule, or database schema was introduced.

## Root Causes And Corrections

### Excel formula injection

`reports/excel.py` now routes text written to summary cells and table headers
through `_excel_safe_value`. After leading whitespace is ignored, strings that
start with `=`, `+`, `-`, or `@` are prefixed with a text marker. They remain
plain text when reopened by `openpyxl`; ordinary numbers and percentage values
retain their numeric formatting. Provider warnings, source labels, and
manifest-derived labels use the same path.

### Manifest completeness

`application/reporting.py` now records `analysis_date`, a canonical technical
indicator input hash, and output hashes for trade log, equity curve, risk
alerts, and backtest metrics. The manifest stores hashes and required metadata,
not the raw private output frames. DataFrame canonicalization sorts columns and
canonical row representations, so equivalent row/column order does not change
the hash. `models.py` canonicalizes set values by sorted canonical
representation while preserving list and tuple order.

### Benchmark single source of truth

`ReportPackage` exposes one canonical benchmark through
`ReportData.benchmark_comparison`. `resolved_backtest_metrics()` replaces
conflicting backtest benchmark display fields with that canonical result before
Excel/HTML output and manifest generation. The compatibility accessor
`package.benchmark` reads the same object; no second benchmark is stored.

### Date and timezone handling

`metrics.py` and `application/reporting.py` normalize timezone-aware and
timezone-naive dates through UTC parsing followed by timezone removal and
normalization. Invalid dates or values return an unavailable comparison with a
specific missing reason. The implementation does not forward-fill, silently
drop dates, or synthesize benchmark data.

## Modified Files

- `src/stock_tool/application/reporting.py`
- `src/stock_tool/backtest/metrics.py`
- `src/stock_tool/reports/excel.py`
- `src/stock_tool/reports/models.py`
- `tests/test_report_manifest.py`
- `tests/test_benchmark_golden.py`

## Added Regression Coverage

The focused tests cover formula safety after an `openpyxl` round trip;
analysis date, technical input, trade log, equity curve, risk alert, and
backtest output hash changes; semantic DataFrame reorder stability; ten fresh
Python-process set-hash checks; canonical benchmark sharing across package,
Excel, HTML, manifest, and output summary; timezone-aware/naive alignment;
invalid date/value unavailability; and legacy exporter compatibility.

## Verification Results

All commands used the project Python 3.11.9 environment and disabled the
project's unrelated global pytest addopts where applicable.

### Targeted tests

Command:

```text
$env:STOCK_TOOL_USER_DATA_DIR = Join-Path $env:TEMP 'stocktool-sprint10-1-targeted-mypy'
.venv\Scripts\python.exe -m pytest -o addopts='' tests\test_report_manifest.py tests\test_benchmark_golden.py tests\test_reports.py tests\test_backtest.py tests\test_dashboard.py -q
```

Result: **82 passed** in 23.16 seconds.

### Full test suite and coverage

Command:

```text
$env:STOCK_TOOL_USER_DATA_DIR = Join-Path $env:TEMP 'stocktool-sprint10-1-full'
.venv\Scripts\python.exe -m pytest -o addopts='' --cov=stock_tool --cov-branch --cov-report=term -q
```

Result: **469 passed**, branch coverage **80.40%**. The measured value is
above the required 80.12% gate and was not obtained by excluding the new
modules or lowering the threshold.

### Focused quality checks

Command:

```text
.venv\Scripts\python.exe -m black --check src\stock_tool\backtest\metrics.py src\stock_tool\reports\models.py src\stock_tool\reports\excel.py src\stock_tool\application\reporting.py tests\test_report_manifest.py tests\test_benchmark_golden.py
.venv\Scripts\python.exe -m ruff check src\stock_tool\backtest\metrics.py src\stock_tool\reports\models.py src\stock_tool\reports\excel.py src\stock_tool\application\reporting.py tests\test_report_manifest.py tests\test_benchmark_golden.py
.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\backtest\metrics.py src\stock_tool\reports\models.py src\stock_tool\reports\excel.py src\stock_tool\application\reporting.py tests\test_report_manifest.py tests\test_benchmark_golden.py
```

Results: Black check passed with all six files unchanged; Ruff passed; mypy
reported `Success: no issues found in 6 source files`.

## EXE Delivery And Smoke

`build_exe.bat` completed successfully using the staging-first process. The
new official package is:

- Path: `release\StockTool\StockTool.exe`
- Version: `1.2.0`
- Last modified: `2026-07-15T18:35:43.8443698+08:00`
- Size: `23,945,816` bytes
- SHA-256: `1866EA24633814F018E977919DCFBD8DD6EBDCD58868C1CE742919883F066C60`

The previous official package was preserved at
`release\previous\StockTool-pre-sprint10.1-20260715-191200` before promotion.
The v1.1.0 rollback package remains available separately.

Using isolated `STOCK_TOOL_USER_DATA_DIR` directories:

- Normal launch on 8501: HTTP 200 and body `ok`.
- With 8501 occupied: fallback launch on 8502 returned HTTP 200 and body
  `ok`.
- `reports`, `logs`, and `data/cache` write probes passed in both cases.
- Test processes and 8501/8502 listeners were terminated and verified absent.
- Smoke-test runtime files were removed.
- An initial short staging probe timed out before readiness; diagnostics showed
  the child server still running and its health endpoint subsequently returned
  `ok`. The official package was then re-tested with the full readiness window
  in both port scenarios listed above; both passed.

## Privacy And User Data Integrity

The release scan found zero real `.env`, `secrets.toml`, portfolio, watchlist,
runtime report, runtime log, cache, or credential-file entries. The bundled
`streamlit/runtime/secrets.py` library module is code, not a credentials file;
no Streamlit secrets configuration was packaged.

Read-only user-data verification under `%LOCALAPPDATA%\StockTool` recorded:

- `data\portfolio.csv`: 4 rows,
  SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`
  before and after final delivery verification.
- `data\watchlist.csv`: absent before and after.
- Existing SQLite files were only hashed, never opened for migration or
  modification. The pre/post hashes for the four existing SQLite snapshots
  and active database were unchanged:
  - `backups\legacy-migration-20260711_195610\processed\stock_data.sqlite`:
    `9CC30A016D56664399E3A904552F32B2C4AEA41E0C7B0FA3D97ED8E3FD655A15`
  - `data\processed\stock_data.pre-migration-20260714T080358774953Z.sqlite`:
    `C58B893D9D616DC84C6B44B732C2E6D0FD638482BF6582EA9E669B1D03C3D3C2`
  - `data\processed\stock_data.pre-migration-20260714T215556071152Z.sqlite`:
    `FC38ACE7B5E3611D43F77BAB0F2D2875E9A84A95DCE4E87D8DEF1E4B86477378`
  - `data\processed\stock_data.sqlite`:
    `71485B3A141654CB08A085EE043871F484DDE52A1765B3CDF9B3F9761D9B914E`

No real user file was moved, overwritten, migrated, or cleaned.

## Source Archive

- Path: `release\baseline\stocktool-sprint10.1-20260715-source.zip`
- Entries: `223`
- SHA-256: `FC581533F937E76ED33A5A596394B198520C9E1F0BFC9A25E2FFBA2E8F80F98A`
- Sidecar: `release\baseline\stocktool-sprint10.1-20260715-source.zip.sha256`
- Sidecar matches the ZIP hash.
- Required build inputs missing: `0`.
- Forbidden entries: `0`.
- Extracted content mismatches: `0`.
- Workspace content mismatches: `0`.
- Verification used the required keyword-only API:
  `verify_source_archive(archive_path=..., extracted_root=...)`.
- The archive includes `examples/indicator_usage.py`,
  `examples/report_usage.py`, and `examples/strategy_usage.py`.
- `.streamlit` is allowlisted to `config.toml` only.

## Known Limitations

1. Benchmark data is still supplied through the existing report boundary; this
   Sprint does not add a benchmark provider or selection UI.
2. Strict date alignment reports unavailable when dates or values cannot be
   reliably aligned; it does not infer holidays, forward-fill, or synthesize
   observations.
3. Manifest hashes provide reproducibility evidence but cannot restore missing
   third-party source data.
4. Point-in-time universe and survivorship-bias handling remain outside this
   Sprint.
5. The status above is ready for independent acceptance review, not a formal
   acceptance declaration.
