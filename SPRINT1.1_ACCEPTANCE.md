# Sprint 1.1 Acceptance

驗收日期：2026-07-10  
驗收範圍：只完成 `SPRING1_REVIEW.md` 要求的 Sprint 1 closure patch；未開始 Sprint 2。  
執行環境：Windows 10、Python 3.11.9、PyInstaller 6.21.0。

## Acceptance Verdict

**Sprint 1.1：Accepted with documented version-control constraint。**

Golden test、三市場固定驗證、70% coverage gate、EXE build、smoke test、README
一致性與最終 source archive 流程均已完成。此 Sprint 沒有修改股票分析核心邏輯、
provider、dashboard、回測、風控、投資組合或報表功能，也沒有開始 Sprint 2。

目前系統找不到 `git` executable。依指示未自行安裝 Git，因此本次沒有建立 Git
commit、tag 或 merge baseline；最終 source archive 與 detached SHA-256 僅作為
暫時基線，不能取代正式版本控制歷史。

## 1. Sample Golden Test

`tests/test_regression_baseline.py` 不再建立人工 OHLCV DataFrame，而是從以下版本化
sample files 開始：

- `data/sample/sample_tw_prices_for_indicators.csv`：260 筆 2330 日線資料。
- `data/sample/sample_fundamental_scores.csv`：固定基本面評分資料。

驗證資料流：

```text
load_csv
  -> clean_price_data
  -> technical indicators
  -> stock scoring
  -> T+1 backtest execution
  -> HTML report disclosures
```

Golden fixture 固定資料期間為 2024-01-02 至 2024-12-30，並記錄最後一筆 SMA、
RSI、MACD、ATR、20 日報酬與 20 日波動率。回測固定驗證 2024-01-02 產生訊號、
2024-01-03 以 open 580.72 成交，避免退回同日成交。

## 2. Market Acceptance

三個案例皆為離線 symbol contract，不連線、不固定即時價格：

| 使用者代號 | 市場 | 固定查詢代號 | 狀態 |
|---|---|---|---|
| `2330` | TWSE | `2330.TW` | validated |
| `6488` | TPEx | `6488.TWO` | validated |
| `AAPL` | US | `AAPL` | validated |

每個案例同時記錄 source type 為 `offline_symbol_contract_fixture`，以及標準欄位
`date, symbol, open, high, low, close, volume, adjusted_close`。這是 contract
baseline，不宣稱線上 provider 在任何時間都一定能下載成功。

## 3. Coverage Gate

`pyproject.toml` 已設定：

```toml
[tool.coverage.report]
fail_under = 70
```

驗證指令：

```powershell
python -m pytest --cov=stock_tool --cov-report=term-missing
```

結果：`181 passed`，total coverage `70.21%`，70% gate 通過。低於 70% 時命令會
回傳失敗。

## 4. Test Evidence

| 驗證 | 結果 |
|---|---|
| Targeted golden/market tests | `2 passed` |
| Full pytest | `181 passed in 7.98s` |
| Coverage pytest | `181 passed in 14.59s` |
| Coverage | `70.21%`，required 70.0% reached |
| Black check | passed |
| Ruff check | passed |

## 5. Windows EXE Evidence

- Build command：`cmd /c build_exe.bat`
- Build result：passed，onedir artifact 已重建。
- EXE：`release/StockTool/StockTool.exe`
- EXE SHA-256：
  `4D6125FA55A4D08D3207AA788BD751BAE6EF4E42C111368E72DCDEF14F98EC7E`
- HTTP smoke：`http://localhost:8501` 回傳 HTTP 200。
- `reports/` write probe：passed。
- 根目錄與 release `README.md` SHA-256：一致。
- Release sample files：7 個。
- Release `.env.example`：存在。
- 測試結束後新增 StockTool processes：0。
- 測試結束後 8501/8502 listeners：0。

## 6. Source Archive

Source archive 是所有 pytest、coverage、EXE、smoke 與 README 驗證完成後的最後
release step：

- Archive：`release/baseline/stocktool-sprint1.1-20260710-source.zip`
- Checksum：`release/baseline/stocktool-sprint1.1-20260710-source.zip.sha256`

Archive 包含最終 README、pyproject、source、tests、fixtures、sample data、文件與
build scripts。它排除 `.venv`、`build`、`release` 內容、`reports`、`logs`、
`data/cache`、`data/processed`、`__pycache__`、`.pyc` 與真正的 `.env`。Archive
會解壓至隔離暫存目錄，確認必要檔案存在且關鍵檔案 hash 與工作區一致。

## 7. Files Changed

- `tests/test_regression_baseline.py`
- `tests/fixtures/sprint1_baseline.json`
- `pyproject.toml`
- `README.md`
- `docs/architecture/contracts.md`
- `docs/release/acceptance-v1.1.md`
- `SPRINT1.1_ACCEPTANCE.md`

產生或重建的 artifacts：

- `release/StockTool/`
- `release/baseline/stocktool-sprint1.1-20260710-source.zip`
- `release/baseline/stocktool-sprint1.1-20260710-source.zip.sha256`

## 8. Known Limitations

1. Git 不可用且未安裝，因此沒有真正的 merge baseline；開始 Sprint 2 前仍應建立
   可稽核的版本控制基線。
2. `build_exe.bat` 仍會複製 `data/processed` 與 `data/cache`。這是 review 已揭露、
   且明確延後的 release-hardening debt；本 Sprint 未擴張範圍處理。
3. 三市場 acceptance 是固定離線 symbol contract，不是線上 provider SLA 或即時
   行情可用性保證。
4. Coverage gate 是最低 70%，不是最終產品品質目標；本 Sprint 未為提高數字而
   擴張測試或重構其他模組。

## 9. Scope Confirmation

- [x] 只完成 Sprint 1.1。
- [x] 沒有開始 Sprint 2。
- [x] 沒有新增產品功能。
- [x] 沒有修改核心分析、回測、風控、provider 或 dashboard 邏輯。
- [x] 沒有自行安裝 Git。
- [x] Source archive 排在 release 驗證最後。
