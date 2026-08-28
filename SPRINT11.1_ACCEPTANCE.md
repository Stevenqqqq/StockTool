# Sprint 11.1 Acceptance Evidence

**Status:** Implementation complete and ready for independent CTO acceptance review.

## Scope

This corrective patch addresses only the two Sprint 11 review findings: legacy
fundamental-date compatibility and the legacy-mode survivorship-bias warning.
Sprint 12 was not started. `SPRINT11_ACCEPTANCE.md` remains unchanged as the
record of the original Sprint 11 request-changes outcome.

## Root Causes and Fixes

### Legacy fundamental CSV date handling

`load_fundamentals_csv()` adds the canonical `available_date` column for legacy
CSV files. The legacy fundamental visibility path then unconditionally replaced
an existing `date` with that empty column. That removed valid as-of dates and
left `FundamentalGrowthStrategy` with an invalid right-side `merge_asof` key.

The legacy path now:

- uses a non-null `available_date` where supplied;
- falls back row-by-row to the pre-existing `date` where it is absent;
- normalizes both `date` and `available_date` to `datetime64[ns]` in the
  prepared strategy frame; and
- returns an empty frame plus an explicit warning only when neither field has a
  usable value.

Strict point-in-time behavior is unchanged: rows without `available_date`
remain excluded, and visibility remains constrained by `available_date <=
decision_date`.

### Legacy survivorship-bias disclosure

Legacy backtests do not apply `HistoricalUniverse` membership filtering. A
complete universe previously suppressed the generic warning even though it was
not being used to filter signals. Legacy mode now always records:

> Legacy mode does not filter trading signals with the historical universe;
> survivorship bias may remain.

Strict mode still requires a historical universe, filters signals by the
universe, and fails closed when the universe is missing. T-day signal and T+1
execution semantics were not changed.

## RED Tests

Before implementation, the focused regression run failed as intended:

- legacy CSV input raised a pandas `MergeError` because valid `date` values had
  been overwritten by null `available_date` values with an incompatible dtype;
- legacy partial availability data left `date` as a non-datetime series; and
- legacy mode with a complete historical universe emitted no legacy filtering
  warning.

## Modified Files

- `src/stock_tool/fundamentals/models.py`
- `src/stock_tool/strategies/fundamental_growth.py`
- `src/stock_tool/backtest/engine.py`
- `tests/test_fundamental_available_date.py`
- `tests/test_backtest_point_in_time.py`

## Regression Coverage

- Legacy CSV with an effective `date` and empty synthesized `available_date`
  preserves the date and produces Fundamental Growth signals without
  `MergeError`.
- Legacy rows use available date where present and fall back to date where it is
  absent.
- Strict mode continues to exclude missing available dates.
- A complete universe still produces the explicit legacy-mode survivorship
  warning; the corresponding strict run does not emit that legacy warning.

## Verification

Commands were run from the project root with `.venv\\Scripts\\python.exe`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamental_available_date.py tests\test_backtest_point_in_time.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_point_in_time_universe.py tests\test_fundamental_available_date.py tests\test_backtest_point_in_time.py tests\test_strategies.py tests\test_backtest.py tests\test_fundamentals.py tests\test_reports.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest --cov=src\stock_tool --cov-branch --cov-report=term-missing -q
.\.venv\Scripts\python.exe -m black --check src\stock_tool\fundamentals\models.py src\stock_tool\strategies\fundamental_growth.py src\stock_tool\backtest\engine.py tests\test_fundamental_available_date.py tests\test_backtest_point_in_time.py
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\fundamentals\models.py src\stock_tool\strategies\fundamental_growth.py src\stock_tool\backtest\engine.py tests\test_fundamental_available_date.py tests\test_backtest_point_in_time.py
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\fundamentals\models.py src\stock_tool\strategies\fundamental_growth.py src\stock_tool\backtest\engine.py tests\test_fundamental_available_date.py tests\test_backtest_point_in_time.py
```

| Check | Actual result |
| --- | --- |
| Sprint 11.1 targeted tests | 13 passed |
| Sprint 11 targeted tests | 75 passed |
| Full pytest | 536 passed |
| Branch coverage | 80.96% (gate: 78.50%) |
| Black | 5 focused files unchanged after formatting |
| Ruff | All checks passed |
| mypy | Success: no issues found in 5 source files |

## Staging EXE and Cold Starts

`cmd /d /c build_exe.bat` completed using the staging-first build path.

| Item | Value |
| --- | --- |
| EXE | `release/staging/StockTool/StockTool.exe` |
| Version | `1.2.2` |
| Modified | `2026-07-18T12:48:33.8092803+08:00` |
| Size | 24,022,677 bytes |
| SHA-256 | `0801C99607D0C5AE029FC50E8E53D7226969A315370D6BFDE6B2971517F2E28C` |

Two isolated `STOCK_TOOL_USER_DATA_DIR` cold-start checks passed:

| Run | Health endpoint | Observed launch-to-health | Result |
| --- | --- | ---: | --- |
| 1 | `http://127.0.0.1:8501/_stcore/health` | 18,983 ms | HTTP 200 body `ok` |
| 2, with 8501 occupied | `http://127.0.0.1:8502/_stcore/health` | 15,914 ms | HTTP 200 body `ok` |

Both results were below the launcher 45-second readiness timeout. The isolated
`reports`, `logs`, and `data/cache` directories were verified writable for both
runs. Test StockTool processes and 8501/8502 listeners were stopped after the
smokes, and temporary smoke directories were removed.

## Privacy and User-Data Integrity

The staging release was validated using the required public release assets.
Filename-based release privacy scan found zero prohibited entries after allowing
the public `.env.example`: no real `.env`, secrets TOML, portfolio, watchlist,
runtime SQLite, cache, logs, or reports were packaged.

Real user data was read only and identical before and after validation:

| Path | Before | After |
| --- | --- | --- |
| `%LOCALAPPDATA%\\StockTool\\data\\portfolio.csv` | 4 rows, `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` | identical |
| `%LOCALAPPDATA%\\StockTool\\data\\watchlist.csv` | absent | absent |
| `%LOCALAPPDATA%\\StockTool\\data\\processed\\stock_data.sqlite` | `71485B3A141654CB08A085EE043871F484DDE52A1765B3CDF9B3F9761D9B914E` | identical |

## Source Archive

| Item | Value |
| --- | --- |
| Archive | `release/baseline/stocktool-sprint11.1-20260718-source.zip` |
| Entries | 236, including manifest |
| SHA-256 | `7997712EA87B9BB8651998A04215379762A272AE95639BB5D70905911F01FB81` |
| Sidecar | `release/baseline/stocktool-sprint11.1-20260718-source.zip.sha256` |

The archive was extracted to a temporary directory and validated through
`verify_source_archive`: required build inputs missing `0`, forbidden entries
`0`, content mismatches `0`, and the sidecar matched the ZIP hash.

## Known Limitations

- Sprint 11 supplies import contracts and deterministic fixtures only; it does
  not provide a complete licensed historical universe or delisted-security
  dataset.
- Legacy mode remains intentionally compatible and carries explicit
  look-ahead/survivorship-bias limitations. It is not equivalent to strict
  point-in-time research.
- No launcher redesign was made because both cold starts were under the current
  45-second readiness timeout.

## Rollback

The Sprint 11 v1.2.2 staging artifact and the existing Sprint 11 source archive
remain available as the immediate rollback baseline. This patch is limited to
fundamental strategy date preparation and legacy backtest warnings; reverting
the five files listed above restores the prior Sprint 11 implementation.
