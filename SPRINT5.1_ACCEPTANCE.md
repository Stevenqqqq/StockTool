# Sprint 5.1 Acceptance

## Scope

Sprint 5.1 is a narrowly scoped acceptance repair for the existing Research Workspace. It corrects price-data provenance, prevents cross-symbol backtest contamination in research scoring, and removes the user-visible internal `unknown` sentinel for incomplete composite scores. Sprint 6 was not started.

No investment-analysis formula, provider fallback order, Research Workspace information architecture, or real user data was redesigned or modified.

## Root causes and corrections

### 1. Actual data provenance was overwritten

**Root cause:** `_ensure_symbol_data()` persisted downloaded price data but then supplied fixed Dashboard metadata (`線上下載`, `auto`, and no cache file) to `_set_price_data()`. This discarded the returned `FetchResult` provenance and could incorrectly label a cache fallback as online.

**Correction:** the Dashboard now preserves the successful `FetchResult` values for source/provider, source type, cache file, provider query symbol, requested start date, and requested end date. Existing SQLite-only data continues to use `SQLite 匯入資料` and `sqlite`; no downloaded data is relabelled as SQLite. The ResearchSnapshot receives the preserved provider, source type, and query symbol.

Verified outcomes:

- yfinance result: `yfinance / online / 2330.TW`;
- FinMind result: `finmind / online / 2330`;
- cache fallback: `yfinance / cache / 2330.TW`, retaining its cache file;
- live isolated source check for `2330/TWSE`: `資料來源：yfinance；類型：online；實際查詢代號：2330.TW`.

### 2. An unrelated backtest could enter the current stock score

**Root cause:** `_build_research_snapshot()` passed `st.session_state.backtest_result` to `score_stock()` without checking the result's recorded research identity. A prior AAPL backtest could therefore affect a 2330 risk component.

**Correction:** `_research_backtest_result()` is a conservative identity gate. It only returns a result if `last_parameters` contains a non-empty symbol and an explicit canonical market, and both match the current ResearchSnapshot after the existing display-symbol normalization. Unknown, missing, or mismatched identity returns `None`. The existing backtest object and `last_parameters` are never mutated. Newly executed Dashboard backtests record a market only when it can be safely determined.

Verified outcomes:

- AAPL/US backtest is not passed to 2330/TWSE scoring;
- `2330.TW` plus TWSE is accepted for a 2330/TWSE workspace;
- missing identity and market mismatch are rejected;
- the original `backtest_result` object and parameter mapping remain unchanged.

### 3. `unknown` appeared in user-visible score evidence

**Root cause:** the evidence builder interpolated `StockScoreResult.total_score` directly. The internal sentinel therefore appeared as `完整總分 unknown`.

**Correction:** incomplete totals are formatted as `完整總分：資料不足`; coverage and known component information remain visible. Missing component scores are not converted to zero and no inferred total is introduced.

## Modified files

- `src/stock_tool/dashboard/app.py`
  - preserves actual `FetchResult` provenance;
  - applies the conservative research-backtest identity gate;
  - records a market for newly run backtests only when it is explicit;
  - adds narrow type-boundary casts for existing UI provider values so focused mypy can validate the changed module without runtime behavior changes.
- `src/stock_tool/application/research_snapshot.py`
  - formats incomplete score evidence without exposing `unknown`.
- `tests/test_sprint51_research_integrity.py`
  - new regression coverage for provenance, cache UI metadata, identity gating, immutability, and partial-score display.

## Regression tests

The new test module verifies:

1. yfinance provenance is `yfinance / online`;
2. FinMind provenance is `finmind / online`;
3. cache fallback preserves provider, `cache` source type, cache file, provider symbol, and date range;
4. the ResearchSnapshot and rendered header match the FetchResult metadata;
5. an AAPL/US backtest cannot enter a 2330/TWSE score;
6. a normalized matching 2330/TWSE backtest is retained;
7. missing, unknown, or mismatched backtest identity is rejected;
8. original backtest session values are not modified;
9. partial user-visible text contains no `unknown`, shows `完整總分：資料不足`, preserves 50% coverage, and does not create missing component contributions.

## Verification

All commands used the project Python 3.11.9 virtual environment.

| Check | Actual command / scope | Result |
| --- | --- | --- |
| Sprint 5.1 targeted tests | `python -m pytest tests/test_sprint51_research_integrity.py tests/test_research_workspace.py tests/test_dashboard.py tests/test_dashboard_shell.py tests/test_dashboard_navigation.py tests/test_dashboard_state.py tests/test_auto_fetch.py tests/test_provider_contracts.py tests/test_stock_scoring.py -q` | 103 passed |
| Full pytest | `python -m pytest` | **343 passed in 28.10s** |
| Branch coverage | `python -m pytest --cov=stock_tool --cov-branch --cov-report=term`; `python -m coverage report --precision=2 --fail-under=77.35` | **78.50%**, gate passed |
| Black | `python -m black --check src/stock_tool/dashboard/app.py src/stock_tool/application/research_snapshot.py tests/test_sprint51_research_integrity.py` | Passed, 3 files unchanged |
| Ruff | `python -m ruff check src/stock_tool/dashboard/app.py src/stock_tool/application/research_snapshot.py tests/test_sprint51_research_integrity.py` | Passed |
| mypy | `python -m mypy --ignore-missing-imports src/stock_tool/dashboard/app.py src/stock_tool/application/research_snapshot.py` | Passed, 2 source files |

No coverage exclusion or gate reduction was used.

## Provenance and UI validation

- An isolated source runtime on port 8510 returned HTTP 200 / `ok`.
- The live `2330/TWSE` Research Workspace showed yfinance as the actual provider, `online` as its source type, and `2330.TW` as the actual query symbol. It did not display `auto` as the provider.
- The deterministic cache-fallback regression test renders the Research Workspace header and confirms `資料來源：yfinance；類型：cache；實際查詢代號：2330.TW`.

## EXE delivery validation

| Item | Value |
| --- | --- |
| EXE | `C:\Users\steve\OneDrive\Documents\股票\release\StockTool\StockTool.exe` |
| Modified | 2026-07-13 12:44:56 +08:00 |
| Size | 23,838,634 bytes |
| SHA-256 | `2E2767981B2B9FD110C9B5723B71401AF7047C1D385F0F9F9796A9AB1BB6609D` |
| Build | `build_exe.bat` completed; hash differs from the Sprint 5 EXE. |
| Health smoke | Isolated EXE startup returned HTTP 200 / `ok` on port 8501, attempt 3. |
| Runtime writes | Isolated `reports/`, `logs/`, and `data/cache/` write checks passed. |

All smoke-test StockTool processes and listeners on ports 8501, 8502, and 8510 were closed. The isolated source and EXE runtime directories were removed.

## Release privacy and user-data verification

- Release scan found no real `.env`, `secrets.toml`, `secrets.*.toml`, credentials/private settings, token marker, `portfolio.csv`, `watchlist.csv`, runtime reports, logs, or cache.
- The only bundled Streamlit item is `_internal/.streamlit/config.toml`.
- The real user portfolio was unchanged:
  - before: 4 rows, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`;
  - after: 4 rows, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.

## Source archive

| Item | Value |
| --- | --- |
| Archive | `release/baseline/stocktool-sprint5.1-20260713-source.zip` |
| Sidecar | `release/baseline/stocktool-sprint5.1-20260713-source.zip.sha256` |
| Entries | 181 |
| SHA-256 | `122D1C1ED3B610A2AD7A6E887C8A32F10CF6C0D4772C78E25E49CB348E4C31EC` |

The archive was extracted to a temporary directory and verified against its manifest. Missing required build inputs: 0. Forbidden entries: 0. Content hash mismatches: 0. The only `.streamlit` entry is `.streamlit/config.toml`. The temporary extraction directory was removed after verification.

## Known limitations

- The Dashboard currently records backtest market identity only for newly run backtests where the existing data context provides an explicit market. Older results without a recorded market are intentionally excluded from Research Workspace scoring.
- Provider and fundamental data remain best-effort; cache provenance now distinguishes cached data but does not imply real-time freshness.
- Incomplete data remains partial or insufficient rather than producing a complete research score.

## Completion

Sprint 5.1 acceptance repair is complete. Sprint 6 was not started.
