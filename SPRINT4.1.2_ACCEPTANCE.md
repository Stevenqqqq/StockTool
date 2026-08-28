# Sprint 4.1.2 Acceptance

## Scope

本 Sprint 只處理投資組合健康度資料串接、canonical risk input、匯率顯示與資料不足 UX。未開始 Sprint 5，也未修改回測、Provider、基本面評分公式、股票評分公式或 Growin/TradingView 功能。

## Baseline and Change State

- Baseline: `SPRINT4.1.1_ACCEPTANCE.md`
- Python: 3.11.9
- Pre-change source archive: `release/baseline/stocktool-sprint4.1.2-20260712-prechange-source.zip`
- Pre-change archive SHA-256: `D71CA43EC9B877BA14E8CC884B28D72696763642018A076A8C18A5EBDA04ACB3`
- Pre-change archive entries: 14
- Existing portfolio before/after: 4 rows, SHA-256 unchanged at `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`
- Watchlist: not present before/after

## Root Causes and Fixes

### Canonical portfolio risk input

新增 `src/stock_tool/portfolio_analytics.py`。公開 helper：

```text
build_portfolio_risk_inputs(prices, positions, volatility_window=20)
    -> PortfolioRiskInputResult
```

結果包含每個 `symbol + market` 一列的 `volatility_20`、`max_drawdown`、觀測筆數與來源，並包含 canonical `MissingData`。波動率只使用該身份的 trailing close-to-close returns；最大回撤只使用該身份提供的 loaded close history。資料不足時保留 `NaN`/MissingData，不補零，也不把不同市場或股票的歷史混合。

`PortfolioHealthService.assess()` 新增向後相容的 `risk_inputs` 參數，接受 `PortfolioRiskInputResult` 或 DataFrame；舊的 indicators 參數仍可使用。Dashboard 由 helper 準備 risk input，不在 `app.py` 計算金融公式。

### Composite score and position quality

`_portfolio_composite_scores()` 現在保留 `total_score`、`available_score`、coverage、status 與 missing data。健康度只接受 canonical identity 且完整的 `total_score`；`available_score` 不會被誤當成完整總分。缺少分數時列出實際持股 `symbol/market`，非持股資料不影響 position quality。

### Mixed-market price precedence

價格合併仍只使用 `symbol + market + date` 去重。SQLite legacy row 沒有 market 時維持 `UNKNOWN`，不繼承最後查詢市場；同一身份的 current session row 置於 SQLite 後方，因此同身份同日期由目前 session 資料優先。不同市場不互相覆蓋。

### FX and missing-data UX

- USD/TWD 輸入值為 0 時不建立匯率、不合併跨幣別總市值。
- 匯率只有按下套用後才生效，畫面標示手動、非即時與套用時間。
- TWD/USD base 方向沿用既有 `PortfolioValuationService` 與 `PortfolioStressService` 的明確公式。
- 健康度資料缺口新增「缺少資料與修復方式」表格，列出功能、狀態、身份、原因、修復方式與能否自動補齊。
- Dashboard warning 以 deterministic 去重；缺少 metrics 顯示 `—`，不顯示截斷的 `資料不…`。

### Fundamental regression protection

Bundled fundamental data 缺少 market 時，不會因 market qualification 把資料或 derived scores 設為 `None`；若沒有可靠 market map，保留 legacy frame 供原有基本面頁使用，portfolio health 仍只接受明確 canonical identity。

## Modified Files

- `src/stock_tool/portfolio_analytics.py`
- `src/stock_tool/portfolio_health.py`
- `src/stock_tool/dashboard/app.py`
- `tests/test_portfolio_analytics.py`

## Tests Added or Updated

- canonical `symbol + market` risk input
- per-identity loaded-period max drawdown
- insufficient volatility history produces MissingData and never zero
- no cross-market history mixing
- input DataFrame immutability
- missing-data repair table deduplication
- unavailable Dashboard metric uses visible dash
- existing bundled fundamentals regression
- existing SQLite/current-session price precedence regression
- existing mixed-market and stress regression suite retained

## Verification Results

### Targeted tests

Command:

```text
.venv\\Scripts\\python.exe -m pytest tests/test_portfolio_analytics.py tests/test_dashboard.py::test_dashboard_auto_loads_bundled_fundamentals tests/test_dashboard.py::test_dashboard_portfolio_price_context_merges_sqlite_and_current_session tests/test_dashboard.py::test_dashboard_price_merge_keeps_market_identities_and_current_wins_same_identity tests/test_sprint32_portfolio.py -q
```

Result: **22 passed**.

### Full pytest and coverage

Command:

```text
.venv\\Scripts\\python.exe -m pytest --cov=stock_tool --cov-report=term-missing --cov-fail-under=76.62
```

Result: **315 passed**, coverage **77.11%**. This is above the Sprint4.1.1 baseline of 76.62%.

### Quality checks

- Ruff focused command over the four changed files: **passed**.
- Black formatted and checked the new files `portfolio_analytics.py` and `test_portfolio_analytics.py`: **passed**.
- Existing-file Black check over `app.py` and `portfolio_health.py` reports pre-existing formatting debt; no broad formatting rewrite was made.
- Focused mypy with `--ignore-missing-imports` over `portfolio_analytics.py` and `portfolio_health.py`: **passed**.
- Full focused mypy over the existing Dashboard also reports the pre-existing pandas-stub and Literal-argument debt; these unrelated issues were not expanded in this Sprint.

### EXE

`cmd /c build_exe.bat` completed successfully.

- Path: `release/StockTool/StockTool.exe`
- Last write time: `2026-07-12 13:40:04`
- Size: `23,784,704` bytes
- SHA-256: `F873BA0A3FF0FA024634AD910353434E34E8D216826579EBBC695AB2D52A1617`
- This differs from Sprint4.1.1 SHA-256 `2268847420B52A8A0A4451FD64F695274F80E5DFB77EA371C60C853D2C9A6F74`.

EXE smoke using the new build returned `ok|HTTP=200` from `http://127.0.0.1:8501/_stcore/health`. Test processes and 8501/8502 listeners were closed afterward.

### Writable directories

Write/remove probes passed for:

- `%LOCALAPPDATA%\\StockTool\\reports`
- `%LOCALAPPDATA%\\StockTool\\logs`
- `%LOCALAPPDATA%\\StockTool\\data\\cache`

Smoke runtime logs were removed. Real portfolio data was not modified.

### Release privacy scan

The release scan found no real `.env`, `portfolio.csv`, `watchlist.csv`, runtime `reports`, runtime `logs`, private cache or token values. Bundled Streamlit/library source names and binary strings were excluded from the false-positive scan; no user data is packaged.

## Source Archive

- Path: `release/baseline/stocktool-sprint4.1.2-20260712-source.zip`
- Size: `1,672,893` bytes
- File entries: `170`
- SHA-256: `600F6A9C75844F6166218F441C7287C1BDF377871E3C7EF67DC90E49FB58377D`
- Sidecar: `release/baseline/stocktool-sprint4.1.2-20260712-source.zip.sha256`
- Included examples: `examples/indicator_usage.py`, `examples/report_usage.py`, `examples/strategy_usage.py`
- Archive was opened and every archived file was compared with its workspace counterpart; no content mismatch.
- Forbidden runtime/build/private entries: 0.

## Known Limitations

1. Portfolio health remains a deterministic research aid and is not investment advice or a trading instruction.
2. 20-day volatility requires at least 21 valid closes per canonical identity; loaded-period drawdown is not a substitute for a full historical risk series.
3. No automatic FX provider was added; manual USD/TWD is explicitly non-realtime.
4. Existing project-wide Black formatting debt and Dashboard mypy typing debt remain outside this Sprint.
5. Legacy SQLite rows without market remain `UNKNOWN` and are intentionally excluded from market-qualified valuation until reliably mapped.

## Sprint Boundary

Sprint 4.1.2 is delivered. Sprint 5 was **not started**.
