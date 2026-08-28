# StockTool Sprint 23 — implementation evidence

本文件只記錄 Sprint 23 的 implementation evidence，未代表 CTO acceptance、正式發布或 release approval。

## Checkpoint

- Sprint 22 本機 checkpoint commit：`64f650e570172f0b21af59205e0c7ea811764cd9`
- annotated tag：`sprint22-accepted-2026-08-02`（未 force 覆寫、未 push）
- checkpoint evidence：`artifacts/sprint23/checkpoint-before-sprint23.json`
- Sprint 23 source 尚未 commit 或 tag；工作樹仍保留未提交的 Sprint 23 內容及原有 `installer/artifacts/`。
- `PRODUCT_EXECUTION_PLAN.md` 已追加 Sprint 20–23 roadmap extension，Sprint 1–19 歷史與 formal baseline 未改寫。

## 修改檔案

- `PRODUCT_EXECUTION_PLAN.md`
- `src/stock_tool/application/settings_workspace.py`
- `src/stock_tool/application/__init__.py`
- `src/stock_tool/dashboard/pages/settings_workspace.py`
- `src/stock_tool/dashboard/shell.py`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/quality_gate.py`
- `tests/test_settings_workspace.py`
- `tests/test_dashboard_navigation.py`

## 實作能力

- 新增 `SettingsWorkspaceApplicationService`，只讀檢查 settings、Portfolio、Watchlist、Research Library、Ledger、SQLite/database、market cache 與 provider/AI presence。
- 狀態包含 healthy、partial、missing、stale、error；component count/freshness、前三大缺口、警告與安全下一步均由 application service 產生。
- manifest 只保存 schema/app version、狀態、count、freshness、gaps、warnings；digest 排除檢查時間，且不含私人絕對路徑、持股明細、文件內容、token 或 API key 值。
- render 與本機檢查不連網、不建立不存在的 Ledger/SQLite；「重新檢查本機狀態」只在明確按下後呼叫一次，例外時保留舊 snapshot 並 fail closed。
- 設定主導航直接進入原生頁；`開啟診斷模式` 仍可到達 legacy diagnostic route。

## Automated verification

| Check | Command/result |
|---|---|
| Sprint 23 targeted | `.venv\\Scripts\\python.exe -m pytest tests/test_settings_workspace.py tests/test_dashboard_navigation.py tests/test_dashboard_shell.py tests/test_portfolio_workspace.py tests/test_portfolio_fx.py -rA` — **77 passed** |
| Full quality gate | `cmd /c quality_gate.bat` — **exit 0** |
| Full pytest | **1032 passed, 2 skipped, 2 warnings** |
| Branch coverage | **83.14%**, threshold 78.5% |
| Black | passed; 37 files unchanged |
| Ruff | passed |
| Focused mypy | passed; 33 source files |
| compileall | passed |
| project privacy scan | 0 violations |
| release layout/source assets | passed |
| git diff --check | passed |
| pip check | `No broken requirements found.` |
| official `.venv` pip-audit | exit 0; no known vulnerabilities |
| Performance hard gate | passed on fixed-data rerun; indicators max 0.436s, Excel max 4.672s, cached workflow max 0.009s, allocation/risk max 0.112s, EXE health max 2.833s |

Durable logs and machine-readable output:

- `artifacts/sprint23/quality-gate.log`
- `artifacts/sprint23/targeted-tests-verbose.log`
- `artifacts/sprint23/performance-result.json`
- `artifacts/sprint23/pip-check.txt`
- `artifacts/sprint23/pip-audit.json`
- `artifacts/sprint23/privacy-release-validation.json`
- `artifacts/sprint23/source-archive-verification.json`

## Candidate and source archive

- staging root: `release/staging-sprint23/StockTool`
- stable EXE: `BD0E438DE7FE57B82EA3F187110E8EF4551139AF4A789FDA28EFB7DA63A6D42F` (7,108,746 bytes)
- payload EXE (`versions/1.2.2/StockToolPayload.exe`): `2365ABF7B44F48BB47D7E2F4A5C46224E0E5D2DA9FCDFAB693F388B22344272E` (23,702,866 bytes)
- source ZIP: `artifacts/sprint23/staging-sprint23-source.zip`
- source ZIP SHA-256: `8D444AB9E74B28C5D9D688ECA2BCC064B3BA93B6D01D026022BBE41F5720731E` (2,487,755 bytes)
- source archive independent extraction: missing required inputs 0, forbidden entries 0, content mismatches 0, duplicate entries 0。
- staging trust-boundary validation and payload validation passed。
- final hash binding assertion: `artifacts/sprint23/final-hash-assertion.json` — all frozen hashes matched。

## EXE smoke

- `artifacts/sprint23/exe-smoke.json`
- stable/payload `--version`: 1.2.2
- isolated user-data health endpoint: HTTP 200 / `ok`
- final cleanup：`artifacts/sprint23/cleanup-processes.json` — StockTool/StockToolPayload 0，8501/8502 listener 0。

## Browser evidence

Actual in-app browser evidence is under `artifacts/sprint23/browser/` and is bound to the final candidate hashes in `browser-result.json`:

- `empty_isolated_root`：實際顯示 missing 與前三大安全缺口。
- `partial_isolated_data`：實際顯示 Portfolio/Watchlist count、過期 cache、損壞 settings 與 fail-closed 缺口。
- `healthy_complete_fixture`：實際顯示整體健康、所有本機元件與 provider presence configured。
- 明確重新檢查：按鈕唯一、顯示「已重新讀取本機狀態；未修改任何資料」；隔離 before/after manifest `zero_diff=true`。
- privacy-safe manifest download event 已觀察，頁面隱私說明與 `manifest-download-dom.txt` 已保存。
- legacy diagnostic route 實際可到達，截圖與 DOM 已保存。
- Tab、Shift+Tab 與可見 focus 已以實際按鍵保存；active console error count 0（`console-active.json`）。
- 100/125/150% screenshot、viewport/overflow metadata 已保存。此 in-app browser 的 CUA zoom shortcut 未改變回報的 viewport scale，故 `browser-result.json` 將 zoom 標記為 best-effort limitation，未以假資料宣稱 zoom 已改變。
- browser machine result：`artifacts/sprint23/browser/browser-result.json`
- active/teardown console 分離：`console-active.json`、`console-teardown.json`
- browser machine result overall status：`BLOCKED`；125%／150% 的真實瀏覽器 zoom 尚未取得可核對的 scale 改變證據，未以截圖或 AppTest 冒充完成。

## Real-data and formal-release preservation

- formal EXE before/after：`4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`
- `%LOCALAPPDATA%\\StockTool` before/after file count：185 / 185
- read-only compare：`artifacts/sprint23/real-data-compare.json` — `added=[]`, `removed=[]`, `changed=[]`, `zero_diff=true`
- 不曾以正式資料根目錄作為測試 `STOCK_TOOL_USER_DATA_DIR`；所有 EXE/browser/AppTest 使用隔離根目錄。
- 未覆寫 `release/StockTool`、未建立 installer、未簽章、未發布、未 promotion、未 push、未建立 Sprint 23 commit/tag。

## Known limitation / handoff

- in-app browser 的真實 zoom shortcut 在本次控制面未改變瀏覽器回報 scale；已保留三組 screenshot、metadata、水平溢位檢查與 limitation。此項是目前唯一硬性證據 blocker，下一步需使用可控制瀏覽器 zoom 的外部瀏覽器／產品負責人人工補證。
- 其餘本文件與 `artifacts/sprint23/` 均為 implementation evidence，等待獨立 CTO acceptance。
