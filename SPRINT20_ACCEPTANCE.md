# Sprint 20 implementation evidence

狀態：**BLOCKED — 等待獨立驗收**

本文件只記錄 Sprint 20 implementation evidence，不代表 CTO acceptance、正式發布或 release approval。

## 範圍與實作

- 新增 `src/stock_tool/application/explore.py`：以既有 `concept_stocks.csv` 索引與既有 watchlist helper 建立 Explore application service。
- `src/stock_tool/dashboard/pages/discovery.py`：加入探索入口、股票代號／公司名稱／題材搜尋、TWSE／TPEX／US 篩選、固定排序、原因／來源／更新時間／stale／partial／missing 狀態，以及「以此代號研究目前資料」與「加入自選股」操作。
- `src/stock_tool/dashboard/shell.py`、`src/stock_tool/dashboard/app.py`：將 canonical `Symbol` 透過既有 `begin_search` 路由至 Research Workspace；保留既有 legacy entrypoint。
- 新增 `tests/test_explore_application.py`，並補強 `tests/test_dashboard_navigation.py`、`tests/test_dashboard_shell.py` 的 Explore、canonical market、watchlist idempotency 與資料不足回歸。
- 新增 `scripts/sprint20_evidence.py`、`scripts/sprint20_browser_evidence.py`，僅產生唯讀 manifest／machine-readable evidence；不讀寫真實資料內容。

探索結果不新增 provider、不建立新的儲存系統、不提供投資推薦或交易訊號。缺欄位時呈現「資料不足」，不補造公司、來源或日期。自選股寫入僅經既有 `load_watchlist`／`add_watchlist_symbol`／`save_watchlist`。

## 測試與品質

命令與結果：

- `.venv\Scripts\python.exe -m pytest tests/test_explore_application.py tests/test_discovery.py tests/test_concepts.py tests/test_dashboard_navigation.py tests/test_dashboard_shell.py tests/test_dashboard_workspace_overview.py tests/test_watchlist.py -q`：通過。
- `.venv\Scripts\python.exe -m pytest -q`：**977 passed, 2 skipped**。
- `.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=json:artifacts/sprint20/coverage.json -q`：**83.07%**，門檻 78.50% 通過。
- `cmd /c quality_gate.bat`：第一次因測試埠號瞬時碰撞失敗；final candidate 重新執行 `artifacts/sprint20/quality-gate-final.log`：**exit 0**，977 passed／2 skipped，coverage **83.07%**，targeted、full pytest、Black、Ruff、focused mypy、compile、privacy、release layout、regression baseline 全部通過。
- Sprint 20 focused Black／Ruff：通過；focused mypy（`explore.py`、`discovery.py`、`shell.py`）：`Success: no issues found in 3 source files`。
- `.venv\Scripts\python.exe -m compileall -q src scripts`：exit 0。
- `.venv\Scripts\python.exe -m pip check`：`No broken requirements found.`
- `PYTHONUTF8=1 .venv\Scripts\python.exe -m pip_audit --format json --output artifacts/sprint20/pip-audit.json`：exit 0、未發現已知漏洞；本機 editable `stock-analysis-tool` 為 pip-audit `skip_reason`（不在 PyPI），未以 ignore／skip 白名單掩蓋。

## Candidate EXE／staging

建置命令：`cmd /c "set STOCK_TOOL_STAGING_PARENT=release\staging-sprint20&& build_exe.bat"`，exit 0。候選成品未寫入 `release\StockTool`。

`artifacts/sprint20/candidate-artifacts.json`：

- stable EXE：`release/staging-sprint20/StockTool/StockTool.exe`；7,109,892 bytes；SHA-256 `620EAA72CE218AD052A6445D34753B06153F5DEFCD9EAA22D411401753E827E2`。
- versioned payload：`release/staging-sprint20/StockTool/versions/1.2.2/StockToolPayload.exe`；23,637,175 bytes；SHA-256 `F08F51B55962517F2D0C524BE0CF28D2AACBD3103B1ADA2CDCD8ACFE58180E43`。
- stable／payload `--version` 均為 `1.2.2`；PE FileVersion／ProductVersion 均為 `1.2.2`。
- 正式 EXE `release/StockTool/StockTool.exe`：SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`，與 Sprint 20 前一致。

`artifacts/sprint20/staging-validation.json`：staging trust-boundary、public payload assets 通過；5,602 regular files、0 forbidden names，8 個第三方公開檔只經精確 allowlist。未包含真實 portfolio／watchlist／SQLite／credentials／私人文件。

`artifacts/sprint20/performance-result.json`：固定資料三次測量的 performance hard gate 通過；EXE health-ready 亦納入三次隔離測試。

## Process-scoped EXE smoke／cleanup

`scripts/browser_transport_harness.py` 只在候選 child process 使用隔離 `STOCK_TOOL_USER_DATA_DIR`：

- `online`、`offline`、`partial` 三次 launch metadata 均 health 200/`ok`，證據位於 `artifacts/sprint20/browser/{online,offline,partial}/`。
- `offline`／`partial` 使用 child-only proxy，不修改系統 proxy、防火牆或使用者設定；final candidate logs 位於 `artifacts/sprint20/browser-final/{online,offline,partial}/`。
- `artifacts/sprint20/exe-smoke.json` 保存 final 版本、候選 hash、process tree 與 health metadata。
- `artifacts/sprint20/cleanup.json`：StockTool process 0、StockToolPayload process 0、8501/8502 listener 0。

## Browser E2E blocker

已依 Browser skill 嘗試連接真正可見瀏覽器；控制面回報 **No browser is available**。因此未以 AppTest、HTTP harness、fixture 或 JavaScript 事件冒充瀏覽器旅程。

`artifacts/sprint20/browser/browser-result.json` 已建立九個必要情境（2330/TWSE、6488/TPEX、AAPL/US × online-first/offline-cache/partial-failure），每一項均明確為 `BLOCKED`，screenshot／DOM／active console／transport／provider metadata 留為空並記錄 blocker；overall status 為 `BLOCKED`。需在可用的真正瀏覽器控制面重跑並補齊三市場畫面、DOM、active console、鍵盤焦點與 100%／125%／150% zoom 證據後，才可解除此阻擋。

## Source archive／privacy／real-data preservation

- `artifacts/sprint20/source.zip` 與 `source.zip.sha256` 已在所有 Sprint 20 原始碼／測試修改完成後重建。SHA-256：`63FD4471BB582E9DC97A268E5A67354E0C2D6A15EC89706275F7BE604A3A3260`。
- 獨立解壓驗證：missing required inputs 0、forbidden entries 0、content mismatches 0、duplicate entries 0；manifest 包含 `stable_launcher.py`、`StableLauncher.spec`、Explore service 與 browser evidence script。
- project privacy scan：0 violations；`git diff --check`：exit 0。
- `artifacts/sprint20/real-user-data-before.json` 與 `real-user-data-after.json` 均為目前 185 檔 entry baseline；`real-user-data-diff.json`：added 0、removed 0、changed 0、`zero_diff=true`。既有三個新增真實資料檔未刪除、未修改。

## 變更與限制

本 Sprint 變更檔案：`src/stock_tool/application/explore.py`、`src/stock_tool/dashboard/pages/discovery.py`、`src/stock_tool/dashboard/shell.py`、`src/stock_tool/dashboard/app.py`、`tests/test_explore_application.py`、`tests/test_dashboard_navigation.py`、`tests/test_dashboard_shell.py`、`scripts/sprint20_evidence.py`、`scripts/sprint20_browser_evidence.py`。工作樹中其他既有 Sprint 變更未 reset、clean 或還原。

唯一已知 Sprint 20 必要阻擋：真正瀏覽器控制面不可用，故 browser E2E、真實鍵盤／焦點／縮放與三市場可見畫面證據尚未完成。狀態維持 **BLOCKED**；下一步是提供可用的真正瀏覽器控制面後，使用相同 final candidate 與全新隔離資料根目錄重跑九個旅程，並重新保存 screenshot／DOM／active console／transport evidence。不得以本文件宣告獨立驗收或正式發布。
