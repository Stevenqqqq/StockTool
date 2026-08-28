# StockTool Sprint 24.1 implementation evidence

狀態：BLOCKED — implementation evidence 尚未具備獨立 CTO 驗收所需的完整 browser hard gate。本文不代表 CTO acceptance、發布或下一 Sprint 核准。

## 修正範圍

- `ResearchContextQueue.consume_for_destination()` 會在保留 FIFO 順序的前提下，原子取出最早的相符 destination；不相符項目不會被刪除，malformed destination fail closed。
- Strategy loaded selection 改為 `MARKET / SYMBOL` 唯一身分；handoff 以相同身分聚焦，不再從全域 source market 猜測，資料列只取 exact market + symbol。
- Research→Holdings 會消費一次性 `portfolio_workspace_focus`，對已存在持股設定可見的 market-qualified selection；不存在時顯示「目前不在持倉」及下一步，絕不自動新增或修改資料。
- 研究接力 stale／snapshot 不符時清除舊 strategy run，顯示發生原因、可用內容、拒絕原因與下一步。
- 建立 Sprint 24.1 machine-readable post-incident comparison，保留六個事件檔案與 SHA-256。

## Targeted tests

命令：

```text
.venv\Scripts\python.exe -m pytest -q tests/test_research_context.py tests/test_research_handoff.py tests/test_dashboard_shell.py tests/test_dashboard_navigation.py tests/test_strategy_workspace.py tests/test_portfolio_workspace.py tests/test_portfolio_fx.py tests/test_evidence_launcher.py
```

結果：120 passed。涵蓋 queue head-of-line、malformed／rerun、TWSE/TPEX 同代號隔離、Strategy exact identity、Holdings focus consume／not-in-holdings、evidence launcher guard。

## Full quality

- `pytest -q`：1078 passed, 2 skipped。
- `cmd /c quality_gate.bat`：exit 0；1078 passed, 2 skipped；branch coverage 83.05%（gate 78.50%）。
- Black：passed。
- Ruff：passed（42 source files）。
- focused mypy：passed。
- compile：passed。
- project privacy／release layout／regression baseline：passed。
- `pip check`：passed。
- official `.venv` `pip-audit`（UTF-8 environment）：exit 0，無已知漏洞；JSON 為 `artifacts/sprint24.1/pip-audit.json`。
- performance hard gate：passed，`artifacts/sprint24.1/performance-result.json`。
- `git diff --check`：passed。

## Candidate and archive

- staging stable：`release/staging-sprint24.1/StockTool/StockTool.exe`；version resource 1.2.2；SHA-256 `69C4CBEA167878251FDB87730D93D8E6EB3A74AA2890FE2845E75102D93961D8`。
- staging payload：`release/staging-sprint24.1/StockTool/versions/1.2.2/StockToolPayload.exe`；version resource 1.2.2；SHA-256 `85F831171E465EAF1AC117CD6AF65AD90977C64F580CE7AA30CA5E671E9D7236`。
- source ZIP：`artifacts/sprint24.1/sprint24.1-source.zip`；SHA-256 `C45FD7CF2D24BAABBB80D16F5C24BB986C0397B9B31739F2ACA5C7E7E8AC5F6F`；sidecar `.sha256` 已建立（最後一次 source/test 修改後重建）。
- source archive verification：missing required inputs 0、forbidden entries 0、content mismatches 0、duplicate entries 0。
- binding：`artifacts/sprint24.1/candidate-hash-binding.json`。
- formal `release/StockTool/StockTool.exe` SHA-256 維持 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。

## Guarded EXE and real-data preservation

- candidate health smoke 僅經 `scripts/evidence_launcher.py` → `browser_transport_harness.py`：`artifacts/sprint24.1/exe-smoke-final/guard-result.json`，health ready，cleanup verified。
- browser-live guarded run 同樣只經 evidence launcher：`artifacts/sprint24.1/browser-live/guard-result.json`；before=191、after=191、added=[]、removed=[]、changed=[]、zero_diff=true；candidate processes 0、listeners 0。
- post-incident read-only comparison：`artifacts/sprint24.1/real-data-comparison.json`。目前基線為 191 檔，未將原 185→191 事件改寫成 zero-diff。
- 六個事件檔案均保留且 hash 已列在 machine-readable comparison；未刪除、移動或修改。

## Browser hard gate

已連接最終候選 URL `http://127.0.0.1:8501/` 並保存 `artifacts/sprint24.1/browser-final/home-100.png`、DOM 與 active console。active console error count 為 0。可見研究首頁與主導航，但目前控制面無法操作 Streamlit 主導航 radio（策略點擊逾時），因此無法誠實完成研究→探索→研究、研究→策略、研究→持倉、研究→研究庫、返回研究、真實 Tab／Shift+Tab 及原生 100/125/150% zoom 證據。未使用 AppTest、viewport resize、舊截圖或假 JSON 冒充。機器結果：`artifacts/sprint24.1/browser/browser-result.json`，status=blocked，且已綁定 final stable/payload/source hashes。

## Governance

未 commit、未 tag、未 push、未發布、未簽章、未修改正式 release、未開始 Sprint 25。真實使用者資料只讀快照；測試候選皆使用全新 temporary data root。因 browser hard gate 缺失，本 Sprint 維持 BLOCKED，交由獨立 CTO 判定後續處置。
