# Sprint 25 implementation evidence

狀態：`BLOCKED — native Chrome zoom evidence 尚未取得，待獨立 CTO 驗證`

本文件只記錄實作證據，不代表 CTO 驗收、正式發布或 promotion。

## Entry Gate

- 已閱讀 `AGENTS.md`、`PRODUCT_EXECUTION_PLAN.md`、`SPRINT24_ACCEPTANCE.md` 與 `SPRINT24.1_ACCEPTANCE.md`。
- Sprint 24.1 候選核對一致：stable `69C4CBEA167878251FDB87730D93D8E6EB3A74AA2890FE2845E75102D93961D8`、payload `85F831171E465EAF1AC117CD6AF65AD90977C64F580CE7AA30CA5E671E9D7236`、source `C45FD7CF2D24BAABBB80D16F5C24BB986C0397B9B31739F2ACA5C7E7E8AC5F6F`、formal `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。
- Entry Gate checkpoint（僅封存 Sprint 24.1，未包含 Sprint 25）：commit `5a3ca7555cc8a7cc590db037a97d4d857dfee745`；annotated tag `sprint24.1-accepted-2026-08-05`。
- Sprint 25 未 commit、未 tag、未 push。

## 變更範圍

- `src/stock_tool/application/market_monitor.py`：不可變快照模型、TWSE/TPEx parser、廣度、固定排序排行、產業熱度、官方摘要不一致警告、atomic cache、stale/offline/partial/unavailable service。
- `src/stock_tool/runtime_paths.py`、`src/stock_tool/dashboard/shell.py`、`src/stock_tool/dashboard/pages/discovery.py`：隔離快取注入、探索市場總覽、明確更新按鈕與 Research handoff。
- `src/stock_tool/application/__init__.py`、`src/stock_tool/quality_gate.py`：公開契約與品質閘門範圍。
- `scripts/evidence_launcher.py`、`tests/test_evidence_launcher.py`：既有 guard 支援既有隔離 root 的 cache replay，仍拒絕真實 root、workspace、release、artifacts 與 symlink。
- `scripts/measure_performance.py`：時間量測不再被全域 tracemalloc 插樁污染；原門檻與記憶體上限未降低。
- `tests/test_market_monitor.py`、`tests/test_roadmap_structure.py`、`PRODUCT_EXECUTION_PLAN.md`：parser/cache/UI/roadmap regression 與官方條款記錄。

## 官方來源與資料契約

- TWSE endpoint：`https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`
- TPEx endpoint：`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`
- 條款查閱日期：2026-08-05；入口：[TWSE OpenAPI](https://openapi.twse.com.tw/)、[TWSE 使用條款](https://www.twse.com.tw/zh/terms/use.html)、[TPEx OpenAPI](https://www.tpex.org.tw/openapi/)。
- 只在使用者按下「更新盤後市場資料」時連線；render 與 cache replay 不連線。
- snapshot metadata 記錄 source、endpoint、data date、fetch time、valid/excluded rows、coverage、payload hash、schema version。
- 股票身分固定為 market + symbol；缺欄位、重複、異常數字、停牌、`--` 與官方摘要不一致均保留 warning 或排除原因。
- 產業熱度只代表已有本機分類的股票子集合，未分類保留為 unknown。

## 自動化驗證

- targeted：market monitor、Explore render no-network、evidence guard、roadmap 結構測試通過。
- `cmd /c quality_gate.bat`（`PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`）：exit 0。
- full pytest：`1095 passed, 2 skipped, 2 warnings`。
- branch coverage：`83.12%`（gate `78.5%`）。
- Black：pass；Ruff：pass；focused mypy：pass；compileall：pass。
- pip check：`No broken requirements found.`
- official `.venv` pip-audit：exit 0，`No known vulnerabilities found`，JSON：`artifacts/sprint25/pip-audit.json`。
- performance：`artifacts/sprint25/performance-final.json`，3 次固定資料量測，overall `passed=true`；indicators/scoring max `0.0747s`、Excel export max `1.0385s`、cached workflow max `0.0077s`、allocation/risk max `0.0363s`、EXE health max `3.023s`；原有門檻與記憶體上限通過。
- project privacy/release layout/regression baseline：quality gate 全部 pass；privacy violations `0`。

## 候選成品與 source archive

- stable：`release/staging-sprint25/StockTool/StockTool.exe`，SHA-256 `DA807071931C89E00B2657204DE276F575AFB1A0F2C72C785D7F475AEB9583D4`，size `7,110,086`，`--version=1.2.2`。
- payload：`release/staging-sprint25/StockTool/versions/1.2.2/StockToolPayload.exe`，SHA-256 `B682892320463B4689DB52DEF3F18E2F25BEF28C8E4BEF43A486BADE4C6CE572`，size `23,748,120`，`--version=1.2.2`。
- source archive（最後一輪 source/doc 修改後重建）：`artifacts/sprint25/sprint25-source.zip`；SHA-256 `1B8A4626421F48B09060D27F5E6F8E2A71FDE776977941D3BBCA1A05DD48BBB6`，size `2,524,134`。
- source archive verify：missing required `0`、forbidden `0`、content mismatch `0`、duplicate `0`（獨立解壓於 `artifacts/sprint25/source-extracted-final2`）。
- hash binding：`artifacts/sprint25/candidate-hash-binding.json`；formal EXE 維持 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。
- 沒有覆寫 `release/StockTool`、沒有 installer/signing/promotion。

## EXE 與隔離 Browser 證據

所有候選啟動均經 `scripts/evidence_launcher.py` → `browser_transport_harness.py`，各自使用全新或明確 replay 的 temporary data root；guard before/after 均 `191→191`、`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`、cleanup verified。

machine-readable index：`artifacts/sprint25/browser/browser-result.json`（綁定 final stable/payload/source/formal hashes）。

已取得並保存 screenshot、DOM、active console、transport/launch/guard：

- online official market overview：`artifacts/sprint25/browser-online-final3/`，active console errors/warnings `0`。
- TWSE 2330 Research handoff（`2330.TW`）：同一目錄，market-qualified identity 正確。
- TWSE/TPEX/combined overview：`artifacts/sprint25/browser-markets-final4/`，三張畫面與 DOM、active console `0`。
- offline cache replay：`artifacts/sprint25/browser-offline-cache-final3/`，child-only transport blocked official endpoints，畫面明示 stale cache。
- partial failure：`artifacts/sprint25/browser-partial-final3/`，TWSE blocked、TPEX allowed，畫面明示 partial。
- offline without cache：`artifacts/sprint25/browser-offline-empty-final3/`，畫面明示 unavailable，不展示半份資料。

目前限制：

- TPEX Research handoff 的一次嘗試在候選 teardown 前進入 Connecting，未列為 passed。
- Chrome extension tab API 可操作頁面，但沒有 browser-native zoom menu；桌面前景被既有全螢幕第三方程式佔用，未能安全取得同時顯示候選頁與原生選單 100/125/150 的 authoritative screenshots。`browser-result.json` 因此 `native_zoom=blocked`、`overall_passed=false`。未用 viewport resize、假截圖或 AppTest 冒充縮放證據。
- 這是目前唯一硬性阻擋；待 CTO/產品負責人提供或完成原生 Chrome zoom 100/125/150 證據後，才可重新判定整體狀態。

## 真實資料保全

- before：`artifacts/sprint25/real-data-before.json`，file_count `191`。
- after：`artifacts/sprint25/real-data-after.json`，file_count `191`。
- comparison：`artifacts/sprint25/real-data-comparison.json`，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。
- 六個 incident files 的只讀 hash：`artifacts/sprint25/incident-files.json`；六筆均與事件基線一致，未刪除、移動或修改。
- 測試結束：StockTool/StockToolPayload process `0`、8501/8502 listener `0`；guard cleanup records preserved.

## Rollback / known limitations

- rollback 僅刪除 Sprint 25 staging 與隔離 runtime；正式 `release/StockTool` 與正式 user-data 未被寫入。
- 快取 schema/hash/過期驗證 fail closed；沒有可靠快取時只顯示 unavailable。
- 完整官方產業分類、美股監控、即時行情、背景輪詢、AI/交易建議不在本 Sprint。
- 等待獨立 CTO 驗收；本文件不得視為正式發布核准。
