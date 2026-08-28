# Sprint 5.2.2 Terra Handoff

## Handoff status

This document is an implementation handoff for independent ChatGPT CTO review.
It is **not** a formal acceptance, merge decision, or release approval. Sprint 6
has not started.

The pre-existing `SPRINT5.2.2_ACCEPTANCE.md` was treated as an unverified
candidate artifact. The checks below were independently executed against the
current workspace.

## Baseline and scope review

Formal comparison baseline:

- `SPRINT5.2.1_ACCEPTANCE.md`
- `release/baseline/stocktool-sprint5.2.1-20260713-source.zip`
- `release/baseline/stocktool-sprint5.2.1-20260713-source.zip.sha256`

The source comparison found only the expected Sprint 5.2.2 source deltas:

- `README.md`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/fundamentals/auto_fetch.py`
- `src/stock_tool/fundamentals/loader.py`
- `src/stock_tool/fundamentals/scoring.py`
- `tests/test_dashboard.py`
- `tests/test_fundamentals.py`

No stock-scoring weights or formula, backtest, trading cost, risk-management,
or portfolio-health formula was changed.

## Independent candidate review

### Root cause

Confirmed. Legacy fundamental CSV rows without `market` could not be safely
distinguished from a requested market. A symbol-only match could therefore
prevent a `MU / US` fetch or allow cross-market data to be used in a research
snapshot. This caused fundamental and valuation inputs to remain unavailable
or be incorrectly matched.

The candidate implementation correctly introduced a canonical fundamental
identity and metadata:

- Identity: `symbol + market + fiscal_period`.
- Required market values are `TWSE`, `TPEX`, `US`, or explicit `UNKNOWN`.
- Legacy rows with no usable market remain `UNKNOWN`; they are not inferred.
- Automatic rows record `period_type`, `as_of_date`, provider source, and
  provider symbol.

`period_type=mixed` is intentionally retained for an automatic row built from
current/TTM fields and the latest available statement fields. `as_of_date` is
the retrieval/snapshot date, not an assertion that it is the fiscal period end.
The README documents both boundaries.

### Issues found during independent review and corrected

1. Fundamental merge documentation claimed a full identity, but the dashboard
   deduplicated on only `symbol + market`, discarding other fiscal periods.
   It now deduplicates on `symbol + market + fiscal_period`, with deterministic
   ordering within that identity.
2. A generic market-qualification helper could use current price data to turn a
   legacy `UNKNOWN` fundamental row into `US`. This silently guessed an
   identity. Fundamental rows and fundamental scores now preserve `UNKNOWN`;
   only an explicit provider response supplies a market.
3. Fundamental scoring output omitted `fiscal_period`, `period_type`, and
   `as_of_date`, weakening end-to-end identity/provenance. The scoring output
   now carries those metadata fields without changing the scoring calculation.

### Provider safety assessment

The yfinance fundamental path retains controlled failure behavior: empty,
missing, or provider-failed data raises a transparent `FundamentalFetchError`
rather than manufacturing a score. The implementation remains defensive for
missing statement fields. A live request is not a test dependency.

## Modified files in this repair pass

- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/fundamentals/scoring.py`
- `tests/test_dashboard.py`
- `tests/test_fundamentals.py`

The candidate's loader, automatic fetcher, README, and their earlier tests
were reviewed but not rewritten in this pass.

## New regression coverage

- Distinct fiscal periods for one `symbol + market` survive dashboard merge.
- A legacy `MU + UNKNOWN` row remains unknown even when a `MU + US` price is
  present.
- A controlled `MU / US` fetch occurs when only legacy `MU + UNKNOWN` exists;
  the persisted fundamental row, score, and Research Workspace input are
  canonical `MU + US`.
- Fundamental score output preserves fiscal-period and provenance metadata.
- Existing tests retain coverage for legacy CSV loading, cross-market identity,
  transparent provider failure, and no fabricated score.

## Verification results

### Before modification

Commands executed before source edits:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamentals.py tests\test_dashboard.py -o addopts='' -q
.\.venv\Scripts\python.exe -m pytest -o addopts='' -q
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term -o addopts=''
```

Results:

- Focused tests: `42 passed`.
- Full suite: `369 passed`.
- Branch coverage: `78.76%`.

The independent review then added failing regression tests for the fiscal
period merge and implicit market inference. Both failed before the repair.

### After modification

Commands executed:

```powershell
.\.venv\Scripts\python.exe -m black src\stock_tool\fundamentals\loader.py src\stock_tool\fundamentals\auto_fetch.py src\stock_tool\fundamentals\scoring.py src\stock_tool\dashboard\app.py tests\test_fundamentals.py tests\test_dashboard.py
.\.venv\Scripts\python.exe -m black --check src\stock_tool\fundamentals\loader.py src\stock_tool\fundamentals\auto_fetch.py src\stock_tool\fundamentals\scoring.py src\stock_tool\dashboard\app.py tests\test_fundamentals.py tests\test_dashboard.py
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\fundamentals\loader.py src\stock_tool\fundamentals\auto_fetch.py src\stock_tool\fundamentals\scoring.py src\stock_tool\dashboard\app.py tests\test_fundamentals.py tests\test_dashboard.py
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\fundamentals\loader.py src\stock_tool\fundamentals\auto_fetch.py src\stock_tool\fundamentals\scoring.py src\stock_tool\dashboard\app.py
.\.venv\Scripts\python.exe -m pytest tests\test_fundamentals.py tests\test_dashboard.py -o addopts='' -q
.\.venv\Scripts\python.exe -m pytest -o addopts='' -q
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term -o addopts=''
```

Results:

- Focused Sprint 5.2.2 tests: `44 passed`.
- Full suite: `371 passed`.
- Branch coverage: `78.71%`, above the `78.50%` gate.
- Focused Black: passed.
- Focused Ruff: passed.
- Focused mypy: passed. `--ignore-missing-imports` is required for the current
  environment's uninstalled third-party typing stubs; it did not suppress
  errors in the checked project files.

### MU controlled integration and live spot check

The controlled integration regression passed: legacy `MU + UNKNOWN` did not
count as `MU + US`; the mocked provider was called for `MU / US`; returned
fundamental data, scoring input, and Research Workspace snapshot all used
`MU + US`.

The independent live `fetch_yfinance_fundamentals("MU", market="US")` spot
check did not succeed in this environment. yfinance reported a local
certificate verification error while configuring its CA file. The result was a
transparent provider failure, not a generated fundamental row or score. This
is recorded as an environment/network limitation, not evidence that the
controlled implementation is incorrect.

## EXE and runtime verification

- EXE: `release/StockTool/StockTool.exe`
- Build command: `cmd /c build_exe.bat`
- Last write UTC: `2026-07-13T15:00:01.1346435Z`
- Size: `23,861,793` bytes
- SHA-256: `37F2B5827D4685FE49F049CFDB5490E574FCA2CF101D38F7C1998065FFC638EB`

The rebuilt EXE was started with an isolated `STOCK_TOOL_USER_DATA_DIR`.

- `http://127.0.0.1:8501/_stcore/health` returned `HTTP 200` with `ok`.
- Isolated `reports`, `logs`, and `data/cache` directories were created and
  written successfully.
- Smoke-test processes were stopped and listeners on 8501, 8502, and 8510
  were absent after cleanup.

## Privacy and user-data checks

Release scan result: zero forbidden entries. The release did not contain a
real `.env`, Streamlit secrets file, token, `portfolio.csv`, `watchlist.csv`,
runtime reports, logs, or cache. The only packaged Streamlit configuration was
`_internal/.streamlit/config.toml`.

Real user data was read only for integrity validation:

- `%LOCALAPPDATA%\StockTool\data\portfolio.csv`: before and after both had
  `4` data rows and SHA-256
  `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
- `%LOCALAPPDATA%\StockTool\data\watchlist.csv`: absent before and after.

## Source archive

- Archive:
  `release/baseline/stocktool-sprint5.2.2-20260713-source.zip`
- SHA-256 sidecar:
  `release/baseline/stocktool-sprint5.2.2-20260713-source.zip.sha256`
- Size: `2,088,424` bytes
- Entries: `185`
- SHA-256:
  `F7F532822A4B88E44F1BDBEE8679BB940BACCB4353DDB2EB42CE01695744F306`

The archive was extracted to an isolated temporary directory and checked with
the release archive verifier:

- Missing required build inputs: `0`.
- Forbidden entries: `0`.
- Content mismatches: `0`.

The temporary extraction directory was removed after verification.

## Remaining limitations

1. Fundamental auto-fetch remains best-effort. yfinance can omit metrics,
   return incomplete statement data, or fail because of network/certificate
   conditions. The system must then show data insufficiency rather than a
   fabricated full score.
2. `period_type=mixed` is not point-in-time historical fundamentals and must
   not be used as an announcement-date substitute for historical backtests.
3. `UNKNOWN` legacy data is intentionally isolated. A user who needs that
   historical row to participate in a canonical market analysis must re-import
   it with an explicit market or allow a successful provider refresh.

## Ready for independent acceptance

**Yes, ready for ChatGPT CTO independent acceptance review.** This statement
only confirms the implementation handoff and verification evidence above; it
does not declare Sprint 5.2.2 formally accepted or merged.
