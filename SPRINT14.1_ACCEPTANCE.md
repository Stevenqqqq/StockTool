# Sprint 14.1 Acceptance Handoff

**Status:** Implementation complete and ready for independent acceptance review.

## Scope

Sprint 14.1 is a corrective patch to the isolated Portfolio Ledger Foundation.
It does not change UI, persistence, repositories, runtime migrations, provider
behavior, backtest behavior, formal release, or real user data. Sprint 15 was
not started.

## Root Causes And Corrections

### FX fee accounting

Previously, `FX_CONVERSION` accepted a non-zero `fee`, but replay calculated
the target amount from the full source cash delta and did not add the fee to
`fees_paid`. The result silently ignored a material accounting field.

The final source-currency FX contract is:

```text
source_principal = target_cash_delta / fx_rate
native_cash_delta = -(source_principal + fee)
target_cash_delta = source_principal * fx_rate
```

- FX fees are charged in the source currency.
- `native_cash_delta` is the total source-currency cash movement, including the
  fee.
- `target_cash_delta` is the actual target-currency receipt.
- A non-zero FX tax is unsupported and rejected.
- The three monetary terms must agree exactly or the entry fails closed.

The controlled test uses a 100 USD principal, 1 USD fee, rate 32, source delta
-101 USD, and target delta 3,200 TWD. Replay leaves USD cash at 0, credits TWD
cash by 3,200, and records 1 USD in `fees_paid`.

### Entry-type validation matrix

Previously, a subset of entry types accepted fields that replay later ignored.
`_EntryFieldPolicy` and `_validate_entry_field_policy()` now provide one
central, typed validation boundary before replay.

| Entry type | Allowed accounting fields | Rejected non-applicable fields |
| --- | --- | --- |
| `opening_position` | symbol, quantity, unit price | cash delta, fee, tax, target/FX fields |
| `cash_deposit` / `cash_withdrawal` | native cash delta | symbol, quantity, unit price, fee, tax, target/FX fields |
| `dividend` | optional symbol, net cash delta, tax | quantity, unit price, fee, target/FX fields |
| `fee` | negative cash delta and/or matching fee amount | symbol, quantity, unit price, tax, target/FX fields |
| `tax` | negative cash delta and/or matching tax amount | symbol, quantity, unit price, fee, target/FX fields |
| `buy` / `sell` | symbol, quantity, unit price, fee, tax, matching cash delta | target/FX fields |
| `fx_conversion` | source cash delta, source fee, target currency/amount, FX rate | symbol, quantity, unit price, tax |

Standalone fee and tax entries must reduce cash. If both their declared amount
and `native_cash_delta` are supplied, they must match exactly.

### Valuation evidence

`LedgerSnapshot.with_market_prices()` previously treated a zero market price as
a genuine valuation and could produce zero market value and artificial
unrealized P/L. It now treats every non-positive price as unavailable and
emits `MissingData(field="latest_price")`.

When all prices are present but positions use multiple native currencies,
weights remain `None` and the snapshot emits
`MissingData(field="fx_rate")`. No FX=1 assumption, cross-currency total, or
automatic FX lookup is introduced.

## Modified Files

- `src/stock_tool/portfolio/ledger.py`
- `tests/test_portfolio_ledger_validation.py` (new)

## New Regression Coverage

- FX source fee reduces source cash and accumulates in `fees_paid`.
- FX fee/rate/cash mismatch fails closed; non-zero FX tax is rejected.
- Opening position, cash flow, dividend, fee, and tax field-policy violations
  are rejected rather than ignored.
- Standalone fee and tax debit cash and accumulate correctly; contradictory
  amounts are rejected.
- Zero and negative market prices produce missing evidence rather than a false
  valuation.
- Mixed TWD/USD positions with complete prices but no FX evidence have no
  weights and expose structured FX missing data.
- Positive same-currency prices retain deterministic weights of 0.25 and 0.75.
- The existing average-cost golden reconciliation remains unchanged.

## Test And Quality Evidence

Commands executed from the repository root with `PYTHONPATH=src`:

```text
.venv\Scripts\python.exe -m pytest tests\test_portfolio_ledger_validation.py tests\test_portfolio_ledger.py tests\test_portfolio_ledger_replay.py tests\test_portfolio_ledger_legacy_import.py tests\test_portfolio_ledger_missing_data.py -q -rA
.venv\Scripts\python.exe -m pytest <all tests\test_portfolio*.py files> -q -rA
.venv\Scripts\python.exe -m pytest tests\test_corporate_actions.py tests\test_backtest.py tests\test_point_in_time_universe.py tests\test_fundamental_available_date.py tests\test_reports.py -q -rA
.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term
.venv\Scripts\python.exe -m black --check src\stock_tool\portfolio\ledger.py tests\test_portfolio_ledger_validation.py tests\test_portfolio_ledger.py tests\test_portfolio_ledger_replay.py tests\test_portfolio_ledger_legacy_import.py tests\test_portfolio_ledger_missing_data.py
.venv\Scripts\python.exe -m ruff check src\stock_tool\portfolio\ledger.py tests\test_portfolio_ledger_validation.py tests\test_portfolio_ledger.py tests\test_portfolio_ledger_replay.py tests\test_portfolio_ledger_legacy_import.py tests\test_portfolio_ledger_missing_data.py
.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\portfolio\ledger.py
```

Results:

- Sprint 14 + 14.1 ledger targeted tests: **23 passed**.
- Portfolio test suite: **62 passed**.
- Corporate action, backtest, point-in-time, fundamental available-date, and
  report regressions: **57 passed**.
- Full pytest: **617 passed**.
- Branch coverage: **81.48%** (gate: 78.50%).
- Focused Black: passed.
- Focused Ruff: passed.
- Focused mypy: `Success: no issues found in 1 source file`.

## Staging EXE Evidence

`build_exe.bat` rebuilt staging only; `publish_release.bat` was not run.

- Staging EXE: `release\staging\StockTool\StockTool.exe`
- Size: `24,109,654` bytes
- Last write (UTC): `2026-07-22T04:09:36.5957339Z`
- SHA-256: `6A4148C13CE6AADB3F819ADA36EEA4F2719F26BD62C84DA4B0F7A55ADE71EE73`
- Required public release assets: passed.
- Isolated smoke: `/_stcore/health` returned HTTP 200 with body `ok`; the home
  page returned HTTP 200.
- Isolated runtime writes: `reports`, `logs`, and `data/cache` all succeeded.
- Cleanup: zero StockTool processes and zero 8501/8502 listeners remained.

The formal EXE was not modified. Its before and after SHA-256 is unchanged:
`AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F`.

## Privacy And User-Data Integrity

The staging release scan found zero forbidden files, zero runtime cache/log/
report files, and zero `ledger` files. The keyword scan reported 15 matches in
the public README and bundled dependency documentation/schema references; no
secret value was emitted or treated as a credential finding.

Canonical real user data was read only before and after verification:

| Path | Before and after state |
| --- | --- |
| `%LOCALAPPDATA%\StockTool\data\portfolio.csv` | 131 bytes, 4 rows, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `%LOCALAPPDATA%\StockTool\data\watchlist.csv` | absent |
| `%LOCALAPPDATA%\StockTool\data\processed\stock_data.sqlite` | 315,392 bytes, SHA-256 `FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C` |
| `%LOCALAPPDATA%\StockTool\settings.json` | absent |

All values matched exactly. No real user data was opened for content,
migrated, moved, overwritten, or deleted.

## Temporary Verification Cleanup

Each deletion first resolved an absolute path and confirmed it was exactly the
named child of `%TEMP%`; no wildcard or workspace/release path was used.

- `%TEMP%\stocktool-sprint14-smoke`: removed.
- `%TEMP%\stocktool-sprint14-archiveverify`: removed.
- `%TEMP%\stocktool-sprint14-1-smoke`: removed.
- `%TEMP%\stocktool-sprint14-1-pytest`: removed.
- `%TEMP%\stocktool-sprint14-1-archiveverify`: removed.

## Source Archive

- Archive: `release\baseline\stocktool-sprint14.1-20260722-source.zip`
- Entries: 259
- SHA-256: `86E05899637B750172FF47F606E80CB8AC4DD580422DD8164E73B3838B3E2586`
- Standard `.sha256` sidecar exists and matches.
- Extracted verification: required build inputs missing = 0; forbidden entries
  = 0; workspace content mismatches = 0.

## Known Limitations

- Ledger persistence, repositories, migrations, dashboard entry workflow,
  broker import, FIFO, tax lots, and corporate-action adjustment remain out of
  scope.
- Cross-currency portfolio weights intentionally remain unavailable until a
  future approved layer supplies explicit FX evidence.
- Sprint 15 work was not started.
