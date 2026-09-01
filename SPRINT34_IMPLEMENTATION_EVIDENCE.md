# Sprint 34 最終封口最後修正：實作證據

## 狀態與邊界

- 狀態：implementation evidence complete；等待 Sol 獨立驗收。
- 本輪僅修正鍵盤 E2E、隔離伺服器警告驗證與 mypy 證據語意，未新增產品功能或 UI。
- 未發布、未簽章、未 commit/tag/push，未修改正式版、已安裝版、正式排程或真實使用者資料。
- Canonical fresh evidence root：`artifacts/sprint34/final-closure-correction-20260831-canonical/`。
- 前一輪 `artifacts/sprint34/final-closure-correction-20260831/` 的 Black exit 1 原始證據保留，未改寫成成功；修正唯一格式問題後，全部門檻於 canonical root 重新執行。

## 純鍵盤 E2E

- fresh navigation 後的純鍵盤區段只使用 CDP `Input.dispatchKeyEvent`；沒有 `click()` 或 JavaScript `focus()`。
- 覆蓋 `Tab`、`ArrowDown`、`Shift+Tab`、`Space`、`Enter`。
- 29 個原生鍵盤事件全部記錄；12 個必要 StockTool 步驟皆為 `is_valid_stocktool_step=true`。
- `Shift+Tab` 落在可見的 StockTool 標題連結，並非 body、Deploy、Main menu、iframe 或無標籤零尺寸元素。
- `Space` 實際觸發「重新檢查本機狀態」；觸發前後 alert 與主內容長度均改變。
- active app-origin console error／warning 均為 0；extension 訊息另行分類，本輪為 0。
- 原始證據：`keyboard_navigation_trace.json`、`browser_verification_results.json`、`browser_final.dom.html`、`browser_console.json` 與 `screenshots/`。
- 同一 staging candidate 的獨立 guarded session：`staging-browser-session/staging-browser-result.json`；session `sprint34-staging-browser-7102a969a7814f0e9e7abe803748834e`，Shift+Tab、Space、console=0、guard cleanup 與 real-data zero diff 均通過。

## 隔離伺服器驗證

- `scroll_reset` 改用 Streamlit 1.58 支援的 inline v2 component；不再建立 v1 iframe，也不再產生 component loading 或 sandbox console warning。
- 使用新建 tempfile 作 `STOCK_TOOL_USER_DATA_DIR`。
- 啟動參數明確包含 `--server.address=127.0.0.1` 與 `--browser.gatherUsageStats=false`。
- 研究首頁、探索、策略、持倉、研究庫、設定六工作區均實際開啟；server deprecation warning 與 app-origin browser warning/error 均為 0。
- stdout/stderr 無 Network URL、External URL 或 `0.0.0.0`；listener 僅為 loopback。
- 驗證結束後該 Chrome/Streamlit process tree 已關閉，listener 為 0，temp runtime 已刪除。
- 原始證據：`isolated_server_warnings_report.json`、`server-warning-stdout.log`、`server-warning-stderr.log`。

## Mypy 證據

- focused source mypy：exit 0，0 errors。
- full mypy current：exit 1，75 errors，誠實標示為 failed。
- 相同 full mypy 指令於 Temp `git archive HEAD` baseline：exit 1，81 errors。
- 以路徑、訊息與錯誤碼比較（忽略行列漂移）：`candidate introduced errors=0`，另有 6 個既有錯誤已消除。
- 未使用「candidate files 0 errors」等不精確文字。
- 原始證據：`06_focused_mypy.log`、`07_full_mypy_current.log`、`07_full_mypy_baseline.log`、`07_full_mypy_comparison.json`。

## Fresh 驗證結果

| 驗證 | Fresh 結果 |
|---|---|
| Targeted pytest | 168 passed |
| Full pytest＋branch coverage | 1586 passed、2 skipped、2 warnings；82.82% |
| Ruff | exit 0 |
| Black | exit 0 |
| focused mypy | exit 0 |
| full mypy | current 75 errors、baseline 81 errors；candidate introduced errors=0 |
| compileall | exit 0 |
| pip check | exit 0 |
| pip-audit | exit 0，0 known vulnerabilities |
| privacy scan | exit 0 |
| `stock_tool.quality_gate` | exit 0，PASSED |
| 隔離 server warning verification | exit 0，0 warnings |
| guarded staging EXE smoke | harness exit 0、cleanup verified、real-data zero diff |
| staging candidate browser | 同一 session；Shift+Tab/Space 通過、app-origin warning/error 0 |

完整命令、stdout、stderr、exit code 與耗時位於 `pipeline_summary.json` 及編號 raw logs。

## 候選與正式檔案綁定

- Staging stable：`build/staging_sprint34_final_closure_correction_20260831_canonical/StockTool/StockTool.exe`
  - size：8,144,225 bytes
  - SHA-256：`d5e659cc746897568dfe05a6479de285e5926c9bc8aa1a3f18498a3e1cce9e64`
- Staging payload：`build/staging_sprint34_final_closure_correction_20260831_canonical/StockTool/Payload/StockToolPayload.exe`
  - size：24,155,645 bytes
  - SHA-256：`448ad54f5bc514ae2e8911d3e665ced2ff85127e1c98664556ec8d7475ac644b`
- Source manifest digest：`ec321181dc18af09bccac4df93a00c1f0d35bf8812ffd41811c363cb1d56b2c9`
- Formal 與 installed v1.4.0 EXE 均保持：
  - size：8,144,118 bytes
  - SHA-256：`ea2aa333b806fda33f85b4b8766236efddbdba84a0f1b6e77439e14eb7bfdd58`

最終 EXE 只經 `scripts/evidence_launcher.py` 啟動；`exe-smoke-final/guard-result.json` 結果為 status=passed、harness=0、cleanup verified、candidate processes=[]、listeners=0、real-data zero diff。

## 資料與清理

- Protected manifest：11,592 → 11,592。
- missing=0、extra=0、mismatch=0。
- StockTool／StockToolPayload 候選程序為 0；8501／8502 listener 為 0。
- 正式 task 僅作唯讀查詢且不存在；未建立或修改排程。
- 證據：`zero-diff-before.json`、`zero-diff-after.json`、`zero-diff-report.json`、`final-evidence-summary.json`。

## 限制與誠實邊界

- `browser_verification_results.json` 內 100%／125%／150% 是 CDP responsive scale/viewport 檢查，不宣稱為 Chrome 原生 zoom 驗收。
- 本文件僅為實作者證據，不代表 Sol／CTO 驗收或發布核准。
