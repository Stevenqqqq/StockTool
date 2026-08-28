# Sprint 14 Acceptance Handoff

**Status:** Implementation complete and ready for independent acceptance review.

## Scope

Sprint 14 implements an isolated Portfolio Ledger Foundation only. It does not
change the dashboard, existing portfolio CSV workflow, provider behavior,
backtest, risk rules, scoring, or the formal `release\StockTool` package.

## Architecture And Accounting Contract

- New bounded domain module: `stock_tool.portfolio.ledger`.
- Immutable `LedgerEntry`, `LedgerPosition`, `LedgerSnapshot`, and
  `LedgerImportResult` models use `Decimal` for all monetary and quantity
  calculations. Public serialization represents Decimal values as strings.
- Entries are ordered deterministically by UTC `effective_at`, explicit
  `sequence`, and `entry_id`; duplicate entry IDs fail closed.
- Market-qualified `Symbol` identity is required for positions. Same ticker in
  different markets remains distinct.
- Supported entry types are `opening_position`, `buy`, `sell`,
  `cash_deposit`, `cash_withdrawal`, `dividend`, `fee`, `tax`, and
  `fx_conversion`. Unsupported entries and invalid/insufficient cash or
  position states fail closed.
- Cost basis policy is average cost. Buy fees and taxes are included in cost;
  sell fees and taxes reduce sale proceeds. A buy or sell with an explicit
  contradictory `native_cash_delta` is rejected rather than silently ignored.
- FX conversion preserves both explicit native cash legs and verifies its
  stated rate. Valuation can only attach explicit market prices and never
  invents FX, a latest price, or cross-currency weight.

## Legacy CSV Boundary

`PortfolioLedgerService.import_and_replay_legacy_csv()` is a read-only,
explicit conversion of aggregate legacy rows to opening-position entries. It
does not write a ledger, invent historical cash flows, or infer prior realized
P/L. Missing market identity, currency, quantity, or average cost produces
structured `MissingData`. Realized P/L is marked unavailable for currencies
created from legacy opening positions.

## Golden Reconciliation

The controlled average-cost fixture proves the following exact reconciliation:

| Item | USD |
| --- | ---: |
| Opening cash deposit | 1,000 |
| First buy: 3 x 100 plus 3 fee | -303 |
| Second buy: 2 x 120 plus 2 fee | -242 |
| Partial sale: 2 x 130 less 1 fee and 2 tax | 257 |
| Net dividend cash (gross 10 less tax 1) | 9 |
| Ending cash | 721 |

Ending position: 3 shares, average cost 109, cost basis 327. Realized P/L is
39, gross dividend income is 10, total fees are 6, and total taxes are 3.

## Modified Files

- `src/stock_tool/portfolio/__init__.py` (new)
- `src/stock_tool/portfolio/ledger.py` (new)
- `src/stock_tool/application/portfolio.py` (new)
- `src/stock_tool/application/__init__.py`
- `tests/test_portfolio_ledger.py` (new)
- `tests/test_portfolio_ledger_replay.py` (new)
- `tests/test_portfolio_ledger_legacy_import.py` (new)
- `tests/test_portfolio_ledger_missing_data.py` (new)
- `README.md`

## Test And Quality Evidence

Commands executed from the repository root with `PYTHONPATH=src`:

```text
.venv\Scripts\python.exe -m pytest tests\test_portfolio_ledger.py tests\test_portfolio_ledger_replay.py tests\test_portfolio_ledger_legacy_import.py tests\test_portfolio_ledger_missing_data.py -q -rA
.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term
.venv\Scripts\python.exe -m black --check src\stock_tool\portfolio\__init__.py src\stock_tool\portfolio\ledger.py src\stock_tool\application\portfolio.py tests\test_portfolio_ledger.py tests\test_portfolio_ledger_replay.py tests\test_portfolio_ledger_legacy_import.py tests\test_portfolio_ledger_missing_data.py
.venv\Scripts\python.exe -m ruff check src\stock_tool\portfolio\__init__.py src\stock_tool\portfolio\ledger.py src\stock_tool\application\portfolio.py tests\test_portfolio_ledger.py tests\test_portfolio_ledger_replay.py tests\test_portfolio_ledger_legacy_import.py tests\test_portfolio_ledger_missing_data.py
.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\portfolio\__init__.py src\stock_tool\portfolio\ledger.py src\stock_tool\application\portfolio.py
```

Results:

- Sprint 14 targeted ledger tests: **16 passed**.
- Full pytest: **610 passed**.
- Branch coverage: **81.38%** (gate: 78.50%).
- Black focused check: passed.
- Ruff focused check: passed.
- Focused mypy: `Success: no issues found in 3 source files`.

## Staging EXE Evidence

`build_exe.bat` rebuilt staging only. No release promotion command was run.

- Staging EXE: `release\staging\StockTool\StockTool.exe`
- Size: `24,107,229` bytes
- Last write (UTC): `2026-07-22T03:33:46.2435036Z`
- SHA-256: `CD093760ABAAF2E327030F627157048DEDCD8A5F2E56AFD4CF6FDBCE4C5F83C8`
- Required public release assets: passed.
- Isolated smoke result: `/_stcore/health` returned HTTP 200 with body `ok`;
  home returned HTTP 200.
- Isolated runtime writes: `reports`, `logs`, and `data/cache` all succeeded.
- Cleanup: no `StockTool` process and no listener on ports 8501 or 8502 remained.

The formal EXE was not modified and remains SHA-256
`AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F`.

## Privacy And User-Data Integrity

The staging release scan found:

- Forbidden runtime/private file names: 0.
- Runtime reports/logs/cache files: 0.
- Pattern scan returned only public documentation and bundled dependency schema
  references; no secret value was emitted or included as a release finding.

Canonical real user-data paths were only read before and after verification:

| Path | State after verification |
| --- | --- |
| `%LOCALAPPDATA%\StockTool\data\portfolio.csv` | 131 bytes, 4 rows, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `%LOCALAPPDATA%\StockTool\data\watchlist.csv` | absent |
| `%LOCALAPPDATA%\StockTool\data\processed\stock_data.sqlite` | 315,392 bytes, SHA-256 `FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C` |
| `%LOCALAPPDATA%\StockTool\settings.json` | absent |

All recorded states match the Sprint entry baseline. No real user data was
read for content, migrated, moved, overwritten, or deleted.

## Source Archive

- Archive: `release\baseline\stocktool-sprint14-20260722-source.zip`
- Entries: 258
- SHA-256: `84F2321EB2C9CD99D545CC3F628A52B2B5135360FC53CF523677AE22BBB54B2F`
- Standard `.sha256` sidecar exists and matches the archive.
- Extracted verification: required build inputs missing = 0; forbidden entries
  = 0; workspace content mismatches = 0.
- The archive includes the new ledger/application/test files, `README.md`,
  `build_exe.bat`, and `.streamlit/config.toml`.

## Rollback

Sprint 14 only replaced `release\staging\StockTool`. The formal
`release\StockTool` baseline remains untouched. Discarding the staging
directory reverts the staged artifact; no user-data rollback is required.

## Known Limitations And Deferred Work

- There is no persistent ledger repository, runtime migration, dashboard entry
  workflow, broker statement importer, or automated ledger persistence yet.
- Average cost is the only implemented cost-basis policy; no FIFO, corporate
  action adjustment, tax-lot, or broker reconciliation policy is introduced.
- Market price attachment intentionally leaves cross-currency totals and
  weights unavailable without explicit FX evidence.
- The execution environment rejected removal of two isolated temporary
  verification directories after successful cleanup of processes/listeners:
  `%TEMP%\stocktool-sprint14-smoke` and
  `%TEMP%\stocktool-sprint14-archiveverify`. They are outside the release and
  canonical user-data paths, contain only smoke/verification artifacts, and
  should be removed when the host permits it.
- Sprint 15 was not started.
