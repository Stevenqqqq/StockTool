# Sprint 11 Acceptance Record

**Status:** ready for independent CTO acceptance review

## Interrupted-run recovery

The first implementation run was interrupted after tests were added but before
production modules existed. The recovery run retained those RED tests, reran
them to confirm the expected collection failures, then implemented and
revalidated the approved Sprint 11 scope. No earlier acceptance numbers were
reused as final evidence.

## Implemented scope

- `HistoricalUniverse` imports market-qualified local CSV memberships with
  interval, status, source and completeness validation. It rejects invalid and
  overlapping intervals and never substitutes a current universe.
- Fundamental imports now preserve `filing_date`, `available_date`, and
  `source`. Strict mode uses only `available_date <= decision_date`; missing
  availability is excluded. Legacy mode remains compatible but warns.
- `FundamentalGrowthStrategy` uses the strict availability join when enabled.
- `BacktestEngine` exposes explicit `legacy`/`strict` point-in-time mode. Strict
  mode requires an imported universe and skips signals without one unambiguous
  historical membership. Existing T+1 execution, costs and risk gates remain
  unchanged.
- `data/sample/historical_universe_synthetic.csv` is a deterministic import
  fixture only. It is partial and does not claim complete delisted coverage.

## Files changed

- `src/stock_tool/data/corporate_models.py`
- `src/stock_tool/data/universe.py`
- `src/stock_tool/fundamentals/models.py`
- `src/stock_tool/fundamentals/loader.py`
- `src/stock_tool/fundamentals/auto_fetch.py`
- `src/stock_tool/fundamentals/__init__.py`
- `src/stock_tool/strategies/fundamental_growth.py`
- `src/stock_tool/backtest/engine.py`
- `data/sample/historical_universe_synthetic.csv`
- `tests/test_point_in_time_universe.py`
- `tests/test_fundamental_available_date.py`
- `tests/test_backtest_point_in_time.py`
- `README.md`

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_point_in_time_universe.py tests\test_fundamental_available_date.py tests\test_backtest_point_in_time.py tests\test_strategies.py tests\test_backtest.py tests\test_fundamentals.py tests\test_reports.py -q
# 72 passed

.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term
# 533 passed; branch coverage 80.96% (gate 78.50%)

.\.venv\Scripts\python.exe -m black --check <11 changed files>
.\.venv\Scripts\python.exe -m ruff check <11 changed files>
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports <8 changed source files>
# all passed; mypy: Success: no issues found in 8 source files.
```

## EXE smoke and privacy

`build_exe.bat` completed a staging-first build. The staging EXE returned
`ok` from `/_stcore/health` on port 8501 using an isolated
`STOCK_TOOL_USER_DATA_DIR`; isolated `reports`, `logs`, and `data/cache` were
created successfully. The test StockTool process was stopped and no listener
on 8501 or 8502 remained. The isolated smoke directory could not be removed by
the current execution policy and must be removed during independent acceptance.

| Item | Value |
| --- | --- |
| Staging EXE | `release/staging/StockTool/StockTool.exe` |
| Modified | `2026-07-18 12:14:07 +08:00` |
| Size | `24,022,009` bytes |
| SHA-256 | `6785905C568494F40A42A01262575ED42CA42AB39DD1CE928560F397D3509A28` |

The staging privacy scan found no `.env`, `secrets.toml`, portfolio, watchlist,
SQLite runtime database, reports, logs or cache content. Promotion was not run;
the preceding release remains the rollback baseline.

## User-data integrity

Real data was read only. Before/after checks were unchanged:

- portfolio: 4 rows, `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`
- watchlist: absent
- `stock_data.sqlite`: `71485B3A141654CB08A085EE043871F484DDE52A1765B3CDF9B3F9761D9B914E`

## Source archive and rollback

- archive: `release/baseline/stocktool-sprint11-20260718-source.zip`
- SHA-256: `5E31239E4A3D07D6415D947AA71EC87C1184AB1B83CF853C074720D91B50894E`
- entries: 236 including manifest
- archive verification: required inputs missing 0; forbidden entries 0;
  content mismatches 0.

Rollback is to retain the existing promoted release and discard the unpromoted
staging directory. No user runtime data or SQLite schema was migrated.

## Known limitations

- The project supplies only a local import contract and synthetic partial
  fixture. It does not download or claim complete historical constituents or
  delisted-security data.
- Strict fundamental mode excludes automatic yfinance fundamentals where a
  verified `available_date` is unavailable.
- Sprint 12 has not started.
