# Sprint 10.2 Acceptance Record

**Status:** ready for independent acceptance review

## Scope

Sprint 10.2 adds the Daily Research Home for StockTool v1.2.1. It is a
research-first landing experience, not an automated trading or investment
advice feature. It uses only the application's existing local data,
portfolio valuation, watchlist, research continuation state, provider
fallback stack, and explicit user-initiated refresh flow.

## Implementation Summary

### Before and after flow

- The previous landing experience exposed a dashboard summary before a clear
  research starting point.
- The new home starts with **"今天先看這些"**, a single global search action
  labelled **"研究一家公司"**, and structured daily research sections.
- The Research Workspace is entered only after a search or a user-selected
  continuation. It includes a visible return action to the Daily Research
  Home.
- The home page performs no automatic online download. **"更新今日資料"** is a
  separate user-clicked action and refreshes no more than 20 unique,
  market-qualified symbols in one run.

### Daily Brief design

- `DailyBriefService` is deterministic and does not mutate portfolio,
  watchlist, price, or research inputs.
- It uses the existing `PortfolioValuationService` output for portfolio
  values and weights; it does not recompute portfolio weights manually.
- Price events use available historical rows only: adjacent-trading-day price
  movement, prior 20-trading-day high/low breaks, volume spikes, stale data,
  and missing data. No wall-clock timestamp is presented as a market-data
  timestamp.
- Missing FX, price, fundamental, or scoring inputs remain explicit data gaps;
  the service does not fabricate a score, exchange rate, catalyst, news item,
  or recommendation.
- Watchlist and continuation identity are always symbol plus market. The same
  ticker in different markets remains distinct.

### Explicitly not implemented in this Sprint

- No external generative AI, fabricated news, synthetic catalysts, or trade
  instructions.
- No background scheduler, automatic retry loop, or network call on landing
  page load.
- No database schema change, new provider, scoring formula, backtest, risk,
  or portfolio-health formula change.
- No point-in-time historical universe or external benchmark-data feature.

## Modified Files

- `src/stock_tool/__init__.py`
- `src/stock_tool/application/__init__.py`
- `src/stock_tool/application/daily_brief.py` (new)
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/dashboard/components/search.py`
- `src/stock_tool/dashboard/pages/home.py`
- `src/stock_tool/dashboard/shell.py`
- `src/stock_tool/dashboard/state.py`
- `tests/test_daily_brief.py` (new)
- `tests/test_daily_home.py` (new)
- `tests/test_cli.py`
- `tests/test_exe_smoke.py`
- `tests/test_release_layout.py`
- `tests/fixtures/sprint1_baseline.json`
- `README.md`
- `使用教學_簡易版.txt`
- `CHANGELOG.md`

## Test Evidence

All test runs used an isolated `STOCK_TOOL_USER_DATA_DIR` under the Windows
temporary directory. No real portfolio, watchlist, cache, report, or runtime
SQLite data was used as test input.

| Check | Command / scope | Result |
| --- | --- | --- |
| Sprint 10.2 targeted tests | `pytest -o addopts='' tests/test_daily_brief.py tests/test_daily_home.py tests/test_dashboard_navigation.py tests/test_dashboard.py -q` | `53 passed in 20.67s` |
| Full pytest | `pytest -o addopts='' -q` | `486 passed in 80.84s` |
| Branch coverage | `pytest -o addopts='' --cov=stock_tool --cov-branch --cov-report=term` | `486 passed`; `80.50%` total, above the `80.40%` gate |
| Black | `black --check` on 13 changed source/test files | passed; 13 files unchanged |
| Ruff | `ruff check` on the same 13 files | passed |
| mypy | `mypy --ignore-missing-imports` on the same 13 files | `Success: no issues found in 13 source files` |

Targeted coverage includes first-use and returning home rendering, no raw
DataFrame exposure, deterministic and non-mutating brief generation,
market-qualified identities, capped refresh, partial refresh failure,
provider-contract forwarding, provenance metadata, and safe user-facing error
messages.

## UI and Research Validation

- Streamlit component tests verify first-use, portfolio/watchlist, empty-data,
  continuation, and refresh result states without external network access.
- The initial home state contains only three small example search prompts; it
  does not show empty data grids.
- The returned-state sections are `今日關注`, `持倉快照`, `自選股動態`, `繼續研究`, and
  `待處理事項`; each renders status text and actions rather than raw internal
  tables.
- Independent acceptance should still perform a final Windows visual review at
  1366x768, 1920x1080, and a narrow window because this Sprint did not add a
  browser-pixel test harness.

## EXE Build and Smoke Test

The staging-first build was validated before promotion. The prior v1.2.0
release was preserved at `release/previous/StockTool`; an older pre-existing
rollback directory was timestamp-archived rather than overwritten.

| Item | Value |
| --- | --- |
| Published EXE | `release/StockTool/StockTool.exe` |
| Version | `1.2.1` |
| Modified | `2026-07-15 22:01:06 +08:00` |
| Size | `23,975,483` bytes |
| SHA-256 | `14A8737AF42C05F16E77103BBEAF6790696E480EFD0B01F9FB9CEBC8391ABFD9` |
| Normal smoke | isolated EXE returned HTTP 200 and `ok` at `/_stcore/health` on port 8501 |
| Fallback smoke | with port 8501 occupied, isolated EXE returned HTTP 200 and `ok` on port 8502 |
| Runtime writes | isolated `reports`, `logs`, and `data/cache` paths accepted write probes |
| Cleanup | no `StockTool` process and no 8501, 8502, or 8510 listener remained |

The promoted release includes `StockTool.exe`, `README.md`, `.env.example`,
`使用教學_簡易版.txt`, `啟動股票工具.bat`, and `data/sample`.

## Privacy and User Data Integrity

- Release scan found zero forbidden `.env`, Streamlit secret, portfolio,
  watchlist, reports, logs, or cache files.
- The release contains one Streamlit configuration file and no private
  Streamlit credential file.
- Real user data was read only. Before and after verification:
  - `portfolio.csv`: exists, 4 data rows, 131 bytes,
    SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
  - `watchlist.csv`: absent before and after.
  - runtime `stock_data.sqlite`: exists before and after at
    `%LOCALAPPDATA%\\StockTool\\data\\processed\\stock_data.sqlite`, 249,856 bytes,
    SHA-256 `71485B3A141654CB08A085EE043871F484DDE52A1765B3CDF9B3F9761D9B914E`.

## Source Archive

| Item | Value |
| --- | --- |
| Archive | `release/baseline/stocktool-sprint10.2-20260715-source.zip` |
| Size | `2,191,028` bytes |
| Entries | 226 total ZIP entries: 225 source entries plus `SOURCE_ARCHIVE_MANIFEST.json` |
| SHA-256 | `F73C33EC835D3AFAA2463482271B179E6C9BA319F2E39136708A18A057D500EA` |
| Sidecar | `release/baseline/stocktool-sprint10.2-20260715-source.zip.sha256` |
| Verification | required build inputs missing: 0; forbidden entries: 0; content/workspace mismatches: 0 |

The source archive uses the existing allowlist. It contains the Sprint 10.2
source and tests plus required build inputs, and includes only
`.streamlit/config.toml` from Streamlit configuration.

## Rollback

To roll back the release, restore the preserved v1.2.0 directory from
`release/previous/StockTool` using the existing release promotion process.
The Sprint 10.1 source baseline remains at
`release/baseline/stocktool-sprint10.1-20260715-source.zip`.

## Known Limitations

- Daily refresh is deliberately explicit and price-data focused; it does not
  claim that every company profile or fundamental field has been refreshed.
- The maximum 20-symbol batch limit is intentional; symbols beyond the cap are
  reported rather than silently skipped.
- The Daily Brief reflects only available local evidence and carries its data
  dates forward. It is research assistance, not investment advice or a
  prediction.
- A final independent Windows visual review remains appropriate for actual
  display scaling and browser-specific behavior.
