# Sprint 13.1 Corporate Action Correctness Fix

**Status:** Implementation complete and ready for independent acceptance review.

## Scope

Sprint 13.1 corrects only the corporate-action and adjusted-price contracts
identified by the Sprint 13 independent review. It does not begin Sprint 14,
does not promote the staging build, and does not alter the formal
`release\StockTool` package or real user data.

## Root Causes And Corrections

### Return basis and cash dividends

Sprint 13 allowed an explicit cash-dividend action in `price_return` mode and
would credit the payable-date cash. `BacktestEngine` now rejects that
combination at construction with `cash dividends require total_return`.
Splits remain available with either return basis because a split changes share
quantity and average cost without creating return cash. Raw prices with
explicit actions plus `total_return` retain the ex-date entitlement,
payable-date credit, and configured tax behavior.

### Economic event versus source identity

`CorporateAction.event_id` remains a source/provenance identity. The model now
also exposes a source-independent `economic_event_key` based on market,
symbol, action type, and effective date, plus `economic_terms_key` for split
ratio, cash per share, currency, and payable date.

- Equivalent observations from several providers are consolidated and applied
  once. The audit retains all source evidence, including source,
  `available_date`, and provenance.
- Different economic terms for the same economic event are treated as a
  conflict. No action is applied and every conflicting source is recorded as
  an unavailable audit row with `conflicting sources` in the reason.

### Cross-market integrity

The current backtest ledger is still keyed by symbol only. Before processing
explicit actions, the engine now requires each action symbol's complete price
history to have exactly the action's one known market. A history that changes
from `ABC/US` to `ABC/TWSE`, even on different dates, fails closed with a
`market identity ambiguity` error. This prevents an action from being applied
to a position from another market; a market-qualified ledger remains a later
Sprint 14 concern.

### Adjusted total-return contract

`adjusted_total_return` now requires `return_basis=total_return` and an
explicit immutable `AdjustedSeriesContract`. The contract requires a non-empty
source, `verified=True`, the `adjusted_close` price column, and a
`total_return` basis. The engine uses `adjusted_close` for both execution and
marking only after that contract is supplied. A column called
`adjusted_close`, including one equal to `close`, is not accepted as evidence
on its own. Explicit corporate actions remain rejected in adjusted-total-return
mode to prevent double counting.

## Modified Files

- `src/stock_tool/data/corporate_actions.py`
- `src/stock_tool/data/__init__.py`
- `src/stock_tool/backtest/engine.py`
- `tests/test_corporate_actions.py`
- `tests/test_adjusted_price_policy.py`
- `README.md`

## Regression Tests

New deterministic coverage verifies:

- a flat-price cash dividend with `price_return` fails closed and cannot credit
  the after-tax cash;
- equivalent `provider-a` and `provider-b` 2-for-1 split evidence results in
  10 shares becoming 20, never 40, with both providers in the audit evidence;
- conflicting 2-for-1 and 3-for-1 evidence results in no action and explicit
  unavailable audit rows;
- a same-symbol US-to-TWSE historical market change fails closed before the
  TWSE action can affect the US position;
- adjusted total return rejects a missing contract and a price-return basis,
  while a verified fixture contract executes and marks using `adjusted_close`
  without turning the raw 100/100/50 series into a false loss.

## Verification

### Sprint 13.1 targeted tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest.py tests/test_benchmark_golden.py tests/test_corporate_actions.py tests/test_adjusted_price_policy.py tests/test_point_in_time_universe.py tests/test_fundamental_available_date.py tests/test_reports.py tests/test_report_manifest.py -q -rA
# 85 passed
```

### Full pytest and branch coverage

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term
# 592 passed in 112.32s
# Total coverage: 81.28%
```

The measured branch coverage exceeds the 78.50% gate. An earlier equivalent
run emitted the same 592-pass/81.28% result but exceeded the outer 120-second
command wrapper during cleanup; the recorded result above is the rerun with a
normal exit code.

### Focused quality checks

```powershell
.\.venv\Scripts\python.exe -m black --check src/stock_tool/data/corporate_actions.py src/stock_tool/data/__init__.py src/stock_tool/backtest/engine.py tests/test_corporate_actions.py tests/test_adjusted_price_policy.py
# 5 files would be left unchanged.

.\.venv\Scripts\python.exe -m ruff check src/stock_tool/data/corporate_actions.py src/stock_tool/data/__init__.py src/stock_tool/backtest/engine.py tests/test_corporate_actions.py tests/test_adjusted_price_policy.py
# All checks passed.

.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src/stock_tool/data/corporate_actions.py src/stock_tool/data/__init__.py src/stock_tool/backtest/engine.py
# Success: no issues found in 3 source files.
```

## Staging EXE And Smoke Test

`build_exe.bat` rebuilt the staging-only package. Formal release promotion was
not performed.

- Staging EXE: `release\staging\StockTool\StockTool.exe`
- Version: `1.2.2`
- Size: `24,084,526` bytes
- Last write UTC: `2026-07-19T18:01:21.9762345Z`
- SHA-256: `8D9E3325BAA88043B777262DBA59E18D61D453EFC66BAC6CBED112FD8B7DB89F`

Using an isolated `STOCK_TOOL_USER_DATA_DIR`, the staging EXE returned HTTP
200 with body `ok` from `/_stcore/health`; the homepage returned HTTP 200.
`reports`, `logs`, and `data/cache` write probes all succeeded. The full
StockTool process tree was stopped, and final checks found zero StockTool
processes and zero listeners on ports 8501 and 8502.

The formal package remains unchanged:

- `release\StockTool\StockTool.exe`
- SHA-256: `AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F`

The execution environment blocked removal of the two explicitly named,
isolated temporary smoke/archive directories under `%TEMP%`. They contain no
formal release or real user data; no processes or listeners remain. This is a
test-environment cleanup limitation to resolve before any final promotion.

## Privacy Scan And User-Data Integrity

The staging release scan found:

- forbidden filenames (`.env`, `secrets*.toml`, `portfolio.csv`,
  `watchlist.csv`, `stock_data.sqlite`): 0;
- runtime `reports`, `logs`, and `cache` directories in the package: 0;
- credential-pattern matches in public top-level text assets: 0.

Read-only before/after checks against `%LOCALAPPDATA%\StockTool` are identical:

| Path | State | SHA-256 |
|---|---|---|
| `data\portfolio.csv` | exists, 131 bytes, 4 rows | `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `data\watchlist.csv` | absent | n/a |
| `data\processed\stock_data.sqlite` | exists, 315,392 bytes | `FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C` |
| `settings.json` | absent | n/a |

## Source Archive And Rollback

- Source archive: `release\baseline\stocktool-sprint13.1-20260720-source.zip`
- Entries: `251`
- SHA-256: `69797D3DD59A18A9ACBA330EA57BD4DFB79BA9AEFA72091E636FD04F2421C0A0`
- Sidecar: `release\baseline\stocktool-sprint13.1-20260720-source.zip.sha256`

`verify_source_archive(archive_path=..., extracted_root=...)` reported:

- required build inputs missing: 0;
- forbidden entries: 0;
- content mismatches: 0.

Rollback remains the existing formal `release\StockTool` package because this
Sprint created a staging candidate only.

## Known Limitations

- Corporate-action coverage remains local/import/fixture based; it does not
  claim complete market coverage.
- The portfolio ledger is symbol-keyed. Sprint 13.1 rejects ambiguous action
  histories rather than implementing a market-qualified ledger.
- Rights issues, mergers, spinoffs, fractional-share handling, and
  jurisdiction-specific withholding remain out of scope.
- The isolated temporary smoke/archive directories were not removed because
  the execution environment rejected the safe cleanup command; they should be
  removed manually or by a permitted cleanup runner before promotion.
