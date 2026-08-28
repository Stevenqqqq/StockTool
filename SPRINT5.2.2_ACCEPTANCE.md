# Sprint 5.2.2 Delivery Verification

Date: 2026-07-13

Status: implementation delivery is ready for independent acceptance review.
This document does not declare Sprint 5.2.2 formally accepted, merged, or
released, and Sprint 6 has not started.

## Scope

Sprint 5.2.2 addresses canonical identity for automatic fundamental data so a
legacy `MU + UNKNOWN` row cannot be treated as complete `MU + US` data. Scope
is limited to fundamental identity, period metadata, Research Workspace
matching, regression coverage, and delivery verification.

It does not change stock-scoring weights or formulas, backtest calculations,
costs, risk rules, portfolio-health formulas, real user data, or Serenity
Agent behavior.

## Delivered Behavior

- Fundamental identity is `symbol + market + fiscal_period`.
- Supported canonical markets are `TWSE`, `TPEX`, `US`, and explicit
  `UNKNOWN`.
- Legacy rows without market remain `UNKNOWN`; the application does not infer
  a market from the ticker or price data.
- A legacy `MU + UNKNOWN` row does not suppress a canonical `MU + US` fetch.
- Automatic rows carry `period_type` and `as_of_date`. `period_type=mixed`
  means current/TTM and latest-statement metrics may be combined; `as_of_date`
  is a retrieval/snapshot date, not a fiscal period end or publication date.
- Fundamental scoring and the Research Workspace filter by the same canonical
  `symbol + market` identity.

## Regression Coverage

The focused suite includes coverage for legacy `UNKNOWN` behavior, market
normalization, period metadata, same-symbol cross-market coexistence,
full-identity lookup, provider data persistence, and controlled `MU / US`
Research Workspace integration. The latter uses a controlled provider double;
it does not require live network access.

## Re-verified Results

The following commands were re-run for this documentation correction. No
source, test, EXE, archive, or user-data file was changed during this pass.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fundamentals.py tests\test_dashboard.py -o addopts='' -q
.\.venv\Scripts\python.exe -m pytest -o addopts='' -q
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term -o addopts=''
.\.venv\Scripts\python.exe -m black --check src\stock_tool\fundamentals\loader.py src\stock_tool\fundamentals\auto_fetch.py src\stock_tool\fundamentals\scoring.py src\stock_tool\dashboard\app.py tests\test_fundamentals.py tests\test_dashboard.py
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\fundamentals\loader.py src\stock_tool\fundamentals\auto_fetch.py src\stock_tool\fundamentals\scoring.py src\stock_tool\dashboard\app.py tests\test_fundamentals.py tests\test_dashboard.py
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\fundamentals\loader.py src\stock_tool\fundamentals\auto_fetch.py src\stock_tool\fundamentals\scoring.py src\stock_tool\dashboard\app.py
```

| Check | Actual result |
| --- | --- |
| Sprint 5.2.2 targeted tests | `44 passed` in 4.07s |
| Full pytest | `371 passed` in 29.00s |
| Branch coverage | `78.71%` (gate: `78.50%`) |
| Focused Black | Passed |
| Focused Ruff | Passed |
| Focused mypy | Passed with `--ignore-missing-imports` |
| Python | 3.11.9 |

No test was skipped, no coverage exclusion was added, and the coverage gate was
not lowered.

No live MU provider request was used for this correction. Automated evidence is
the controlled `MU / US` integration test; live yfinance availability remains
an external best-effort condition.

## Existing EXE Verification

The EXE was not rebuilt because its existing final artifact was unchanged.

- EXE: `release\StockTool\StockTool.exe`
- Last write UTC: `2026-07-13T15:00:01.1346435Z`
- Size: `23,861,793` bytes
- SHA-256:
  `37F2B5827D4685FE49F049CFDB5490E574FCA2CF101D38F7C1998065FFC638EB`

An isolated `STOCK_TOOL_USER_DATA_DIR` smoke test verified:

- `http://127.0.0.1:8501/_stcore/health` returned HTTP 200 with body `ok`.
- Isolated `reports`, `logs`, and `data\cache` directories were writable.
- The isolated runtime directory was removed after the test.
- No `StockTool` process or listener on ports 8501, 8502, or 8510 remained.

## Release Privacy Scan

The release privacy scan found `0` forbidden entries. It contained no real
`.env`, Streamlit secrets file, token, `portfolio.csv`, `watchlist.csv`,
runtime report, log, or cache. The packaged Streamlit configuration remains the
allowed `_internal/.streamlit/config.toml` only.

## User Data Integrity

Real user data was read only for integrity validation:

- `%LOCALAPPDATA%\StockTool\data\portfolio.csv` remained at `4` data rows,
  before and after verification, with SHA-256
  `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
- `%LOCALAPPDATA%\StockTool\data\watchlist.csv` was absent before and after
  verification.

No real user data was modified, moved, or overwritten.

## Existing Source Archive Verification

The source archive was not recreated because it was unchanged. The acceptance
document is not an archive entry, so this documentation-only correction does
not invalidate archive/workspace content verification.

- Archive:
  `release\baseline\stocktool-sprint5.2.2-20260713-source.zip`
- SHA-256 sidecar:
  `release\baseline\stocktool-sprint5.2.2-20260713-source.zip.sha256`
- Entries: `185`
- SHA-256:
  `F7F532822A4B88E44F1BDBEE8679BB940BACCB4353DDB2EB42CE01695744F306`
- Sidecar matches actual archive SHA-256: yes.
- Missing required build inputs: `0`.
- Forbidden entries: `0`.
- Content mismatches against the current workspace: `0`.

## Known Limitations

1. yfinance is best-effort. Network, certificate, provider availability, or
   incomplete returned fields can still produce a transparent missing-data
   state.
2. `period_type=mixed` is not a point-in-time historical-fundamentals dataset
   and must not be used as an announcement-date substitute in historical
   backtests.
3. Legacy `UNKNOWN` rows remain isolated until a canonical-market import or
   successful provider refresh is available.

Sprint 5.2.2 is ready for ChatGPT CTO independent acceptance review. This is
not a formal acceptance declaration.
