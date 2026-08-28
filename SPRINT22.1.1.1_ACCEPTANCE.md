# StockTool Sprint 22.1.1.1 implementation evidence

本文件只記錄實作證據，等待 CTO 獨立驗收；不代表正式發布或 release approval。

## 修正

- `src/stock_tool/dashboard/pages/portfolio_workspace.py` 新增 `_health_percent()`，將健康度 component score（0–100）以兩位小數百分比呈現；市場、幣別及其他 exposure weight 仍使用既有 `_percent()`（0–1 ratio）。未改動健康度計算、權重、manifest 或資料結構。
- `tests/test_portfolio_workspace.py` 鎖定 84.82、92.13、100.00 的健康度顯示、0.5445 exposure 顯示 54.45%，並拒絕 8482.00%／10000.00%。
- Sprint 22.1.1 的 keyword-only refresh callback、成功後 analysis/stress invalidation、exception fail-closed regression 均保留。

## 自動化驗證

| 檢查 | 結果 |
|---|---|
| targeted pytest (`tests/test_dashboard_shell.py tests/test_portfolio_workspace.py tests/test_dashboard_navigation.py tests/test_portfolio_fx.py`) | 71 passed |
| full pytest | 1026 passed, 2 skipped |
| branch coverage | 83.14%（門檻 78.5%） |
| `cmd /c quality_gate.bat` | exit 0；targeted/full/coverage/Black/Ruff/focused mypy/compile/privacy/release layout/regression baseline 全部通過 |
| `pip check` | exit 0，No broken requirements found |
| official `.venv` pip-audit | exit 0，No known vulnerabilities；`artifacts/sprint22.1.1.1/pip-audit.json` |
| performance hard gate | passed；`artifacts/sprint22.1.1.1/performance-result.json` |
| `git diff --check` | exit 0 |

## 隔離候選

建置命令：`STOCK_TOOL_STAGING_PARENT=release\\staging-sprint22.1.1.1 cmd /c build_exe.bat`，exit 0。正式 `release/StockTool` 未被覆寫。

候選雜湊記錄：`artifacts/sprint22.1.1.1/candidate-hashes.json`。

- stable EXE：`release/staging-sprint22.1.1.1/StockTool/StockTool.exe`，SHA-256 `F6D4DB1D56C24BF5FB44D7898723880E610D01D7F196EB3F8954907B8A910B23`
- payload EXE：`release/staging-sprint22.1.1.1/StockTool/versions/1.2.2/StockToolPayload.exe`，SHA-256 `C06A0FC014AC9C71C150B989378A2FE3BE9867E6105BB7F44DEBCE6490F9ECF3`
- source archive：`artifacts/sprint22.1.1.1/staging-sprint22.1.1.1-source.zip`，SHA-256 `5F83A1C592A7F5E433C504C509386837E797725FEED85ADA9D52479DAF4500A5`
- formal EXE：SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`，未變更。

`artifacts/sprint22.1.1.1/exe-smoke.json` 證明 stable/payload `--version` 均為 1.2.2 且 exit 0，候選 health endpoint 為 HTTP 200、body `ok`，使用全新隔離資料根目錄。

Source archive 獨立驗證：`artifacts/sprint22.1.1.1/source-archive-verification.json`；missing required inputs、forbidden entries、content mismatches、duplicate entries、workspace missing、workspace mismatches 均為 0。`stable_launcher.py` 與 `StableLauncher.spec` 仍在 required build inputs。

## 真實瀏覽器證據

實際以候選 stable EXE、1280x720、隔離 `STOCK_TOOL_USER_DATA_DIR` 完成持倉流程：

1. 透過可見 UI 新增 `2330/TWSE`、`6488/TPEX`、`AAPL/US`。
2. 按下「更新市場資料」，頁面完成更新狀態呈現。
3. 輸入並套用 USD/TWD=32，畫面記錄真實 UTC `effective_at/applied_at`。
4. 分析持倉；健康度 component score 均落在 0.00%–100.00%，未出現 8482.00% 或 10000.00%；market/native_currency exposure 仍以 ratio 百分比呈現。
5. 執行壓力測試，再將 AAPL quantity 由 2 改為 3；舊分析與壓力結果消失並回到「尚未分析持股」。

證據集中於 `artifacts/sprint22.1.1.1/browser-result.json`：三市場情境均為 passed，active console error/warning count 為 0，並綁定候選 hashes、隔離根目錄及證據路徑。截圖、DOM、console、provider metadata：

- `artifacts/sprint22.1.1.1/browser/holdings-health.png`
- `artifacts/sprint22.1.1.1/browser/holdings-health-dom.txt`
- `artifacts/sprint22.1.1.1/browser/stress-result.png`
- `artifacts/sprint22.1.1.1/browser/stress-result-dom.txt`
- `artifacts/sprint22.1.1.1/browser/stress-invalidated.png`
- `artifacts/sprint22.1.1.1/browser/stress-invalidated-dom.txt`
- `artifacts/sprint22.1.1.1/browser/console-active.json`
- `artifacts/sprint22.1.1.1/browser/provider-metadata.json`

## 資料保全與清理

`artifacts/sprint22.1.1.1-real-before.json`、`artifacts/sprint22.1.1.1-real-after.json` 與 `artifacts/sprint22.1.1.1-real-compare.json` 顯示真實 `%LOCALAPPDATA%\\StockTool` `added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。本次只讀取 manifest，未修改、搬移或刪除真實資料。

`artifacts/sprint22.1.1.1/cleanup.json`：StockTool process 0、StockToolPayload process 0、8501 listener 0、8502 listener 0；formal EXE hash 仍符合基線。

未 commit、push、tag、簽章、發布或開始 Sprint 23。
