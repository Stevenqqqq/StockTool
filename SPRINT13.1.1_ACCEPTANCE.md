# Sprint 13.1.1 Acceptance Record

**Status:** Implementation complete and ready for independent acceptance review.

## Scope

This corrective patch addresses one Corporate Action correctness defect only. It does not promote `release\StockTool`, change T+1 execution, transaction costs, strategies, UI, reports, or real user data.

## Root Cause And Correction

`CorporateAction.economic_terms_key` grouped cash dividends by split ratio, cash-per-share, currency, and payable date, but omitted the normalized `tax_rate`. Two providers could therefore report the same dividend event with different withholding rates and be treated as equivalent. The deterministic source sort then selected one representative action, changing the credited cash and performance without recording a conflict.

`tax_rate` is now included in `economic_terms_key` after the existing normalization performed by `CorporateAction.__post_init__`. The existing engine conflict path consequently treats different normalized tax rates as conflicting economic terms: it produces an unavailable corporate-action audit entry and does not credit cash. Equivalent sources with the same normalized tax rate stay in one group, retain all `source_evidence`, and apply exactly once.

The contract is deterministic: `economic_event_key` identifies the event; `economic_terms_key` includes every current cash-affecting term, including `tax_rate`. Provider input ordering cannot change the outcome.

## Modified Files

- `src/stock_tool/data/corporate_actions.py`
- `tests/test_corporate_actions.py`
- `README.md`
- `SPRINT13.1.1_ACCEPTANCE.md`

## Regression Tests

The following tests were added using a controlled single-share holding and a cash dividend of 2.00:

- A 10% versus 20% tax-rate conflict is unavailable, credits no dividend cash, and records both conflicting providers in the audit evidence.
- Two equivalent 10% sources credit the net dividend once, retain both sources, and produce identical equity curves and audits when provider input order is reversed.

The RED run before the code change failed as expected: the conflicting 10%/20% case ended with cash `118.0` rather than the expected pre-dividend `100.0`.

## Verification

### Targeted Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest.py tests/test_benchmark_golden.py tests/test_corporate_actions.py tests/test_adjusted_price_policy.py tests/test_point_in_time_universe.py tests/test_fundamental_available_date.py tests/test_reports.py tests/test_report_manifest.py -q -rA
```

Result: **87 passed**.

The focused corporate-action regression command also passed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_corporate_actions.py tests/test_adjusted_price_policy.py -q -rA
```

Result: **19 passed**.

### Full Test Suite And Coverage

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term
```

Result: **594 passed**. Branch coverage: **81.23%**, above the 78.50% gate.

### Focused Quality Checks

```powershell
.\.venv\Scripts\python.exe -m black --check src/stock_tool/data/corporate_actions.py tests/test_corporate_actions.py
.\.venv\Scripts\python.exe -m ruff check src/stock_tool/data/corporate_actions.py tests/test_corporate_actions.py
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src/stock_tool/data/corporate_actions.py src/stock_tool/backtest/engine.py
```

Results: Black check passed, Ruff passed, and mypy reported `Success: no issues found in 2 source files.`

## Staging EXE Verification

`build_exe.bat` rebuilt the staging package only. Formal `release\StockTool` was not replaced.

| Item | Value |
|---|---|
| Staging EXE | `release\staging\StockTool\StockTool.exe` |
| Version | `1.2.2` |
| UTC modified time | `2026-07-22T02:31:36.4325467Z` |
| Size | `24,084,546` bytes |
| SHA-256 | `1E84D2E14E03C85205398A9E2DC59BB43E330BBDF7DBB4A8273BAE9815C10C14` |
| Formal EXE SHA-256 before/after | `AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F` |

Using an isolated `STOCK_TOOL_USER_DATA_DIR`, the staging EXE returned:

- `GET /_stcore/health`: HTTP 200, body `ok`.
- `GET /`: HTTP 200.
- Isolated `reports/`, `logs/`, and `data/cache/` write probes: passed.
- Process cleanup: zero `StockTool` processes and zero listeners on ports 8501 and 8502 after shutdown.

The environment rejected deletion of the explicitly named isolated `%TEMP%` smoke directory by policy. It contains only smoke-test runtime files; it is not under the release package or `%LOCALAPPDATA%\StockTool`.

## Privacy Scan

The staging release scan found:

- forbidden filenames (`.env`, `secrets*.toml`, `portfolio.csv`, `watchlist.csv`, `stock_data.sqlite`): 0;
- packaged `reports`, `logs`, or `cache` directories: 0;
- credential-pattern matches in public top-level text assets: 0;
- packaged Streamlit configuration files: exactly one `_internal\.streamlit\config.toml`.

## User-Data Integrity

The canonical runtime location was checked read-only at `%LOCALAPPDATA%\StockTool`; it matches the pre-Sprint recorded values:

| Path | State | SHA-256 |
|---|---|---|
| `data\portfolio.csv` | exists, 131 bytes, 4 rows | `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `data\watchlist.csv` | absent | n/a |
| `data\processed\stock_data.sqlite` | exists, 315,392 bytes | `FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C` |
| `settings.json` | absent | n/a |

No canonical user-data hash changed. A legacy workspace `data\` copy is not the runtime user-data root and was not used for this assertion.

## Source Archive

| Item | Value |
|---|---|
| Archive | `release\baseline\stocktool-sprint13.1.1-20260722-source.zip` |
| Entries | 251 |
| SHA-256 | `C4D7D2E538F0532B5156BE0C923F44B1D729365BE0514A89529225F9DD466A7B` |
| Sidecar | `release\baseline\stocktool-sprint13.1.1-20260722-source.zip.sha256` |

The archive was verified with `verify_source_archive(archive_path=..., extracted_root=...)`: required build inputs missing `0`, forbidden entries `0`, and archive content mismatches `0`. The manifest was separately compared with the workspace: workspace content mismatches `0`.

## Known Limitations

- The portfolio ledger remains symbol-keyed; this Sprint only makes the existing corporate-action source conflict handling fail closed.
- Rights issues, mergers, spinoffs, fractional-share behavior, and provider corporate-action retrieval remain outside Sprint 13.1.1.
- The formal release remains unchanged pending independent CTO review.
- No Sprint 14 work was started.
