# Sprint 10 Acceptance Handoff

**Status:** Implementation complete and ready for independent acceptance review.

## Scope

Sprint 10 delivers the approved v1.2 release scope only: a strict benchmark
comparison contract, a deterministic reproducibility manifest, a reporting
application boundary, compatible Excel/HTML report sections, replay
verification, and the Windows v1.2 release. Sprint 11 has not started.

## Modified And Added Files

| Area | Files |
| --- | --- |
| Version and governance | `AGENTS.md`, `src/stock_tool/__init__.py`, `CHANGELOG.md` |
| Benchmark metrics | `src/stock_tool/backtest/metrics.py` |
| Report package and exporters | `src/stock_tool/reports/models.py`, `src/stock_tool/reports/excel.py`, `src/stock_tool/reports/html.py`, `src/stock_tool/reports/__init__.py` |
| Application boundary and dashboard handoff | `src/stock_tool/application/__init__.py`, `src/stock_tool/application/reporting.py`, `src/stock_tool/dashboard/app.py` |
| Tests and fixture | `tests/test_benchmark_golden.py`, `tests/test_report_manifest.py`, `tests/fixtures/benchmark_golden.csv`, versioned release tests and the Sprint 1 baseline fixture |
| Documentation | `README.md`, `使用教學_簡易版.txt`, `docs/release/v1.2-checklist.md` |

## Benchmark Contract

- `BenchmarkComparison` is the single benchmark calculation result used by
  `PerformanceMetrics`, `ReportingService`, Excel, and HTML.
- `BenchmarkMetadata` records symbol, market, provider, provider symbol,
  source type, requested period, interval, row count, optional fetch/update
  time, and sanitized warnings.
- The benchmark must have one valid observation for every strategy equity-curve
  date in the exact equity date range. The implementation neither forward-fills
  nor silently removes duplicate dates.
- A missing benchmark, invalid columns, empty values, duplicate dates, missing
  boundaries, or any mismatched strategy date yields an unavailable comparison
  with a structured reason. Reports show `資料不足`, never a fabricated 0%.
- Available outputs are benchmark total return, benchmark maximum drawdown,
  strategy excess return, actual aligned start/end dates, and observation count.

## Reproducibility Manifest And Replay

`ReportingService.build_package()` is the application entry point. It copies
input DataFrames, calculates the canonical benchmark result, and returns a
frozen `ReportPackage` containing `ReportData`, `BenchmarkComparison`, and a
`ReproducibilityManifest`. Callers must treat the DataFrames inside the package
as read-only.

Manifest schema version `1` uses canonical JSON with sorted keys, stable date
formats, normalized column/row order, stable numeric/empty-value representation,
and SHA-256. It contains report identity, input hashes, strategy and cost
settings, risk settings, sanitized provider attempts, data-quality/missing-data
reasons, output hashes, and benchmark alignment metadata.

`verify_report_replay()` rebuilds a package from supplied inputs and returns
structured top-level manifest mismatch keys. It verifies matching inputs without
writing runtime data. A changed price, benchmark, strategy parameter, or trading
cost changes the manifest identity. The manifest is an input/configuration
fingerprint, not an archive of external price data or private research content.

Provider strings use the existing sanitization policy. Tokens, API keys,
authorization values, passwords, secrets, private URL-query values, and Windows
absolute paths are redacted before they reach a manifest or report section.

## Report Compatibility

`generate_excel_report()` and `generate_html_report()` keep their legacy
`ReportData` interface for this compatibility cycle and additionally accept a
canonical `ReportPackage`. Excel appends `基準比較`, `資料來源`, `資料品質`, and
`可重現性 Manifest` sheets. HTML appends equivalent sections. Both formats use
the same package-level benchmark result and manifest hash.

## Tests

All tests used isolated `STOCK_TOOL_USER_DATA_DIR` locations. No test read,
cleaned, migrated, or wrote the real user portfolio, watchlist, runtime SQLite,
cache, reports, or logs.

| Check | Actual command / scope | Result |
| --- | --- | --- |
| Sprint 10 targeted tests | `pytest -o addopts='' tests/test_benchmark_golden.py tests/test_report_manifest.py tests/test_reports.py tests/test_backtest.py tests/test_dashboard.py -q` | **73 passed** |
| Version and regression subset | CLI, launcher, baseline, release-layout, benchmark and manifest tests | **29 passed** |
| Full suite with branch coverage | `pytest -o addopts='' --cov=stock_tool --cov-branch --cov-report=term -q` | **460 passed; 80.34%** |

The branch coverage result exceeds the Sprint 10 gate of 80.12%.

## Quality Checks

Focused checks covered the Sprint 10 source, exporter, dashboard handoff, and
new/updated version tests.

```powershell
.\.venv\Scripts\python.exe -m black --check src\stock_tool\__init__.py src\stock_tool\backtest\metrics.py src\stock_tool\reports\models.py src\stock_tool\reports\excel.py src\stock_tool\reports\html.py src\stock_tool\reports\__init__.py src\stock_tool\application\__init__.py src\stock_tool\application\reporting.py src\stock_tool\dashboard\app.py tests\test_benchmark_golden.py tests\test_report_manifest.py tests\test_cli.py tests\test_exe_smoke.py tests\test_release_layout.py tests\test_regression_baseline.py
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\__init__.py src\stock_tool\backtest\metrics.py src\stock_tool\reports\models.py src\stock_tool\reports\excel.py src\stock_tool\reports\html.py src\stock_tool\reports\__init__.py src\stock_tool\application\__init__.py src\stock_tool\application\reporting.py src\stock_tool\dashboard\app.py tests\test_benchmark_golden.py tests\test_report_manifest.py tests\test_cli.py tests\test_exe_smoke.py tests\test_release_layout.py tests\test_regression_baseline.py
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\__init__.py src\stock_tool\backtest\metrics.py src\stock_tool\reports\models.py src\stock_tool\reports\excel.py src\stock_tool\reports\html.py src\stock_tool\reports\__init__.py src\stock_tool\application\__init__.py src\stock_tool\application\reporting.py src\stock_tool\dashboard\app.py tests\test_benchmark_golden.py tests\test_report_manifest.py tests\test_cli.py tests\test_exe_smoke.py tests\test_release_layout.py
```

- Black: **15 files would be left unchanged**.
- Ruff: **All checks passed**.
- Focused mypy: **Success: no issues found in 14 source files**.

`tests/test_regression_baseline.py` has three pre-existing strict-mypy findings
outside the Sprint 10 implementation scope. It remains included in Black/Ruff
and full pytest; it was intentionally excluded from the focused mypy command
rather than being changed merely to silence unrelated type debt.

## Windows Release And Smoke

- Build: staging-first `build_exe.bat`, followed by verified promotion with
  `publish_release.bat`.
- Official EXE: `release\StockTool\StockTool.exe`
- Version: `1.2.0`
- Last write time: `2026-07-15 16:17:39` (Asia/Taipei)
- Size: `23,943,719` bytes
- SHA-256: `38D69FF49D731E0CD8E0E4F198BD6E6CF495389630EE883DB0D947CB342451ED`
- Health smoke: official EXE returned HTTP 200 with body `ok` on `8501`.
- Fallback smoke: staging EXE returned HTTP 200 with body `ok` on `8502` while
  `8501` was deliberately occupied.
- Isolated runtime verification: `reports`, `logs`, and `data\cache` were all
  created and written successfully.
- Cleanup: no `StockTool.exe` process and no `8501`/`8502` listener remained
  after smoke tests.

The former v1.1.0 official release remains available for rollback at
`release\previous\StockTool\StockTool.exe`; its `--version` output is `1.1.0`.

## Privacy And User Data Integrity

- Release required-assets validation: passed.
- Release privacy scan: no real `.env`, Streamlit secrets file, portfolio,
  watchlist, logs, reports, cache, or private key file was found. The public
  certifi CA bundle is not treated as a private credential.
- Real portfolio before and after: exists, 4 rows,
  `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
- Real watchlist before and after: absent.
- The pre-existing approved Sprint 9 sample concepts/relations in runtime SQLite
  were not removed or changed.

## Source Archive

- Archive: `release\baseline\stocktool-sprint10-20260715-source.zip`
- Entries: `223`
- SHA-256: `BAE83E1327D22EB95DABE4B75A731809FEA1F787AA6482DC993E9F8753A69B86`
- Sidecar: `release\baseline\stocktool-sprint10-20260715-source.zip.sha256`
- Validation used the required keyword-only call:
  `verify_source_archive(archive_path=..., extracted_root=...)`.
- Required build inputs missing: `0`.
- Forbidden archive entries: `0`.
- Extracted content mismatches: `0`.
- Workspace content mismatches: `0`.
- Sidecar hash matches the ZIP hash.

## Known Limitations

1. Sprint 10 does not add a benchmark selection/download UI or a new provider;
   callers must supply benchmark data and metadata through the report boundary.
2. Strict date alignment intentionally rejects otherwise usable but differently
   dated series; it does not infer holidays, forward-fill, or synthesize values.
3. A manifest cannot restore deleted or revised third-party source data without
   the same input data or an appropriate cache.
4. This Sprint does not solve point-in-time universe or survivorship bias.
5. Sprint 11 has not started.
