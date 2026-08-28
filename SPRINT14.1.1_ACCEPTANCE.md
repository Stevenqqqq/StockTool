# Sprint 14.1.1 Acceptance Handoff

**Status:** Implementation complete and ready for independent acceptance review.

## Scope

Sprint 14.1.1 is a narrow corrective patch to the Portfolio Ledger Foundation.
It does not start Sprint 14.2 or Sprint 15, does not modify the dashboard,
persistence, repositories, providers, backtest, risk, scoring, corporate
actions, or the formal release.

## Root Cause

`LedgerEntry.__post_init__()` correctly derived a normalized local
`target_currency` with `_optional_text()`, but the `FX_CONVERSION` validation
still checked the original `self.target_currency`. A whitespace-only original
string was truthy, so construction succeeded and normalization later changed
the stored target currency to `None`. Replay then reached `_fx()` with invalid
state and raised an unhelpful `AssertionError`.

## Correction

`FX_CONVERSION` now checks the normalized `target_currency` before validating
the cash legs. `None`, an empty string, spaces, and tabs therefore fail during
`LedgerEntry` construction with:

```text
FX conversion requires a valid target_currency
```

The existing Sprint 14.1 fee contract remains unchanged:

```text
source_principal = target_cash_delta / fx_rate
native_cash_delta = -(source_principal + fee)
target_cash_delta = source_principal * fx_rate
```

This removes the delayed replay assertion without changing T+1 execution,
transaction cost handling, or any other portfolio behavior.

## Modified Files

- `src/stock_tool/portfolio/ledger.py`
- `tests/test_portfolio_ledger_validation.py`
- `SPRINT14.1.1_ACCEPTANCE.md`

## New Regression Coverage

- `target_currency=""`, `"   "`, and `"\t"` each fail during construction.
- The failing construction cases never reach `replay_ledger()`.
- A valid USD-to-TWD conversion with 100 USD principal, 1 USD fee, rate 32,
  and 3,200 TWD receipt still replays correctly.
- A valid FX conversion retains its `to_dict()` / `from_dict()` round trip.

The initial RED run produced three failures: the empty string raised the older
generic message and whitespace/tab values constructed successfully. After the
minimal validation-order correction, all three cases fail closed at the public
constructor boundary.

## Verification

Commands ran from the repository root using Python 3.11.9 and `PYTHONPATH=src`:

```text
.venv\Scripts\python.exe -m pytest tests\test_portfolio_ledger.py tests\test_portfolio_ledger_legacy_import.py tests\test_portfolio_ledger_missing_data.py tests\test_portfolio_ledger_replay.py tests\test_portfolio_ledger_validation.py -q -rA
.venv\Scripts\python.exe -m pytest <all tests\test_portfolio*.py files> -q -rA
.venv\Scripts\python.exe -m pytest tests\test_corporate_actions.py tests\test_backtest.py tests\test_backtest_point_in_time.py tests\test_point_in_time_universe.py tests\test_fundamental_available_date.py tests\test_reports.py tests\test_report_citations.py tests\test_report_manifest.py tests\test_research_reports.py -q -rA
.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term
.venv\Scripts\python.exe -m black --check src\stock_tool\portfolio\ledger.py tests\test_portfolio_ledger_validation.py tests\test_portfolio_ledger.py tests\test_portfolio_ledger_replay.py tests\test_portfolio_ledger_legacy_import.py tests\test_portfolio_ledger_missing_data.py
.venv\Scripts\python.exe -m ruff check src\stock_tool\portfolio\ledger.py tests\test_portfolio_ledger_validation.py tests\test_portfolio_ledger.py tests\test_portfolio_ledger_replay.py tests\test_portfolio_ledger_legacy_import.py tests\test_portfolio_ledger_missing_data.py
.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\portfolio\ledger.py
cmd /c build_exe.bat
```

Results:

- Sprint 14 / 14.1 / 14.1.1 ledger tests: **27 passed**.
- All portfolio tests: **66 passed**.
- Corporate action, backtest, Point-in-Time, fundamental available-date, and
  report regressions: **82 passed**.
- Full pytest: **621 passed**.
- Branch coverage: **81.49%** (gate: 78.50%).
- Focused Black: passed after formatting the changed source file.
- Focused Ruff: passed.
- Focused mypy: `Success: no issues found in 1 source file`.

## Staging EXE

`build_exe.bat` rebuilt **staging only**. `publish_release.bat` was not run.

- Path: `release\staging\StockTool\StockTool.exe`
- Size: `24,109,669` bytes
- Last write UTC: `2026-07-22T04:50:08.1770520Z`
- SHA-256: `B71089B83B1115EABCD718F8C4EC9A1BE5E3EF4291315E1A3546E58FFE484037`
- `/_stcore/health`: HTTP 200, body `ok`.
- Home endpoint: HTTP 200.
- Isolated runtime writes succeeded for `reports`, `logs`, and `data/cache`.
- Cleanup confirmed zero `StockTool` processes and zero listeners on 8501/8502.

The formal EXE was not modified:

- Path: `release\StockTool\StockTool.exe`
- Size: `24,063,733` bytes
- Last write UTC: `2026-07-18T14:30:41.9396264Z`
- Before and after SHA-256:
  `AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F`

## Privacy And User Data

The staging required-public-assets validation passed. The forbidden-file scan
found zero `.env`, `secrets*.toml`, portfolio, watchlist, SQLite, runtime
report/log/cache, or ledger-data files. Keyword scanning found 32 identifier
matches only in bundled Streamlit dependency source/documentation; no matched
value was emitted. These are dependency API/schema references, not release
runtime data files.

Real user data was not changed, moved, or overwritten. Before and after
metadata and SHA-256 values match exactly:

| Path | State |
| --- | --- |
| `%LOCALAPPDATA%\StockTool\data\portfolio.csv` | present, 131 bytes, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `%LOCALAPPDATA%\StockTool\data\watchlist.csv` | absent |
| `%LOCALAPPDATA%\StockTool\data\processed\stock_data.sqlite` | present, 315,392 bytes, SHA-256 `FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C` |
| `%LOCALAPPDATA%\StockTool\settings.json` | absent |

Note: the initial metadata helper counted the existing portfolio CSV rows
without displaying any row values. No user-data values were retained or
reported; all later checks used filesystem metadata and SHA-256 only.

## Temporary Cleanup

`%TEMP%\stocktool-cto-s141-smoke` was resolved to the absolute direct child
`C:\Users\steve\AppData\Local\Temp\stocktool-cto-s141-smoke` before removal.
No wildcard was used. It existed before cleanup and was absent afterward.

The isolated pytest and archive verification directories were also confirmed
absent after their runs:

- `%TEMP%\stocktool-sprint1411-pytest`
- `%TEMP%\stocktool-sprint1411-archiveverify`

## Source Archive

- Archive: `release\baseline\stocktool-sprint14.1.1-20260722-source.zip`
- Entries: 259
- Size: `2,289,635` bytes
- SHA-256: `50FCB42C28645E3F50E8503CD8EE4F27E6591665E6CCE44E3A9045C07B2B3A50`
- Sidecar: `release\baseline\stocktool-sprint14.1.1-20260722-source.zip.sha256`

The archive was extracted to an isolated temporary directory and verified with
the keyword-only `verify_source_archive(...)` API:

- required build inputs missing: 0
- forbidden entries: 0
- archive content mismatches: 0

## Known Limitations

- Ledger persistence, repositories, migrations, broker import, FIFO/tax lots,
  and dashboard ledger workflows remain outside this corrective patch.
- The staging package is not promoted to `release\StockTool` by this Sprint.
- Sprint 14.2 and Sprint 15 were not started.
