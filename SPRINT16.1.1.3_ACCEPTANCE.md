# Sprint 16.1.1.3 Acceptance

Status: **Implementation complete and ready for independent CTO acceptance review.**

## Scope

Sprint 16.1.1.3 is a narrow AI trust-boundary correction. Sprint 17 was not started. `release/StockTool` was neither modified nor promoted.

## Root Cause and Correction

The prior direct-command policy let any short English word behave as a ticker. It missed numeric symbols and polite commands such as `Buy 2330.` and `Please buy MU.`, while incorrectly rejecting `Buy signals are historically noisy.`

`src/stock_tool/research/citations.py` now derives allowed targets only from the active `EvidenceBundle`: its canonical symbol, safe Taiwan suffix equivalents (`2330` / `2330.TW`, `6488` / `6488.TWO`), and explicit generic references (`this stock`, `the stock`, `the position`, `shares`, `這檔股票`, `这只股票`, `持股`, `倉位`, `仓位`). Symbols supplied by model text are never accepted as evidence identities. An otherwise complete imperative or recommendation with an unknown direct object is rejected; it is not considered a ticker. This preserves research text whose object phrase continues beyond the action, including `Buy signals are historically noisy.`

One violating claim still rejects the complete provider response: mode is `local_rules`, no partial AI claims are retained, and no new or forced-regeneration AI cache is written. Unicode NFKC, `casefold`, and format-character normalization remain in place.

## Modified Files and Tests

- `src/stock_tool/research/citations.py`
- `tests/test_ai_fallback.py`

No provider, EvidenceBundle contract, assistant cache format, dashboard, portfolio, watchlist, backtest, build script, formal release, or real user data was changed.

The targeted regression suite covers `Buy 2330.`, `Sell 2330.`, polite English and Traditional/Simplified Chinese commands, `BRK.B`, `2330.TW` under `2330/TWSE`, unknown `Buy AAPL.` under `MU/US`, mixed valid/unsafe results, and cache preservation. It also re-executes the earlier injection, secret, shell, guaranteed-return, immediate-action, malformed-schema, forged-cache-citation, coverage-type/range, valid-cache, and allowed research-context cases.

The first attempted targeted run used system Python 3.10 and stopped at collection because this project requires Python 3.11 `datetime.UTC`. All final results use `.venv\\Scripts\\python.exe` (Python 3.11.9); no pre-change result is used as final evidence.

## Verification

```text
.venv\\Scripts\\python.exe -m pytest tests/test_ai_fallback.py tests/test_ai_citation_policy.py tests/test_research_assistant.py -q
.venv\\Scripts\\python.exe -m pytest -q
.venv\\Scripts\\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing -q
.venv\\Scripts\\python.exe -m black --check src/stock_tool/research/citations.py tests/test_ai_fallback.py
.venv\\Scripts\\python.exe -m ruff check src/stock_tool/research/citations.py tests/test_ai_fallback.py
.venv\\Scripts\\python.exe -m mypy src/stock_tool/research/citations.py src/stock_tool/research/assistant.py
```

- Sprint 16.1.1.3 targeted: **115 passed**.
- Full pytest: **810 collected; completed without failures**.
- Branch coverage: **82.30%**; gate **78.50%** passed.
- Black: **2 files would be left unchanged**.
- Ruff: **All checks passed**.
- Focused mypy: **Success: no issues found in 2 source files**.

## Staging Candidate

- Candidate: `release/staging-sprint16.1.1.3/StockTool/StockTool.exe`
- Version: `1.2.2`
- Size: `24,193,746` bytes
- Modified UTC: `2026-07-27T05:42:25.9049653Z`
- SHA-256: `FB6CA716938B5D8096804EAB80878891591BA12D2FA38BFF50F4C80251D88FE0`

`build_exe.bat` was invoked with `STOCK_TOOL_STAGING_PARENT=release\\staging-sprint16.1.1.3`. PyInstaller created the candidate, but the known delayed-expansion asset-copy issue made the versioned override exit non-zero while checking the default staging path. This sprint did not modify that batch file. Existing `copy_release_assets()` and `validate_release_assets()` then validated the generated candidate. The batch build was not an end-to-end successful versioned override; the known limitation remains out of scope.

With an isolated `STOCK_TOOL_USER_DATA_DIR`, `/_stcore/health` returned HTTP `200` with `ok`, `/` returned HTTP `200`, and `reports`, `logs`, `data/cache`, and `data/ai_research` were writable. Smoke cleanup left `0` StockTool processes and `0` listeners on 8501/8502.

## Privacy and User Data Integrity

- Required public staging assets: valid.
- Staging forbidden-file scan (`.env`, `secrets*.toml`, portfolio, watchlist, SQLite, reports, logs, cache): **0 entries**.
- Source rebuild-boundary privacy scan: **0 violations**.
- Formal EXE unchanged before/after: `release/StockTool/StockTool.exe`, `24,145,141` bytes, SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- Real runtime was read only and unchanged: `portfolio.csv` exists, 131 bytes, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`; `watchlist.csv` absent; `stock_data.sqlite` exists, 716,800 bytes, SHA-256 `FD563A543FE847FA09AB61CEBA947BBFCE04272836EDB46B5FE714CB337E1293`; `settings.json` absent.

## Source Archive and Rollback

- Archive: `release/baseline/stocktool-sprint16.1.1.3-20260727-source.zip`
- Size: `2,355,068` bytes; entries: `278`.
- SHA-256: `DB3EAA4DEAA73F458D0A3A27CC83D48B5775F000882DDE42F1556EEB361CAB57`.
- Sidecar matches. Extraction verification: required inputs missing `0`, forbidden entries `0`, content mismatches `0`.

Rollback remains the unchanged formal EXE above plus the preserved Sprint 15.1.3.1 source archive. No formal promotion was attempted.

## Known Limitations

- This is a bounded direct-command policy, not a general natural-language investment-advice classifier.
- The versioned-staging delayed-expansion issue in `build_exe.bat` remains for separately approved build work.
- Sprint 17 was not started.
