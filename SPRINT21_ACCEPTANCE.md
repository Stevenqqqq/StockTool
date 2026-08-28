# Sprint 21 implementation evidence

狀態：IMPLEMENTATION EVIDENCE COMPLETE — PENDING INDEPENDENT CTO ACCEPTANCE。

本次只產品化既有策略工作區與可重現健檢流程，未新增策略、provider、dependency 或前端框架；BacktestEngine、BrokerSimulator、策略介面、T+1 與既有成本公式未改寫。

## 修改檔案與架構

- `src/stock_tool/application/strategy_workspace.py`
  - 新增 `StrategyWorkspaceApplicationService`，協調既有 Strategy Registry、`BacktestEngine`、`StrategyValidationService` 與既有 `BacktestFormValues` validation。
  - 提供 missing/partial/fresh/stale data snapshot、標準回測、OOS、Walk-forward（最多 10 folds）、敏感度（最多 25 組）、錯誤與部分完成狀態。
  - 建立 deterministic、privacy-safe strategy run manifest；只保存 session，不自動寫入研究庫或真實使用者資料。
  - manifest digest 綁定 symbol、market、strategy/parameters、資料期間／來源／筆數、成本、風險、T+1、corporate-action policy、版本與狀態；條件改變會失效，重跑才恢復 current。
- `src/stock_tool/dashboard/pages/strategy_workspace.py`
  - 新增原生「策略研究工作區」：已載入標的選擇、資料狀態、策略 Registry、參數、成本、執行前檢查、標準結果、健檢摘要及安全 JSON 下載。
  - 無資料與未知市場均 fail closed；保留既有 legacy 策略頁入口。
- `src/stock_tool/dashboard/shell.py`
  - 策略主導航直接渲染 native workspace，並保留既有 overview/legacy fallback。
- `tests/test_strategy_workspace.py`
  - data state、manifest determinism/privacy、成本與 T+1 binding、未知市場、standard run、bounded health、條件變更過期回歸。
- `tests/test_dashboard_navigation.py`
  - 原生策略主導航／無資料 AppTest。

## 測試與品質

- Targeted：`pytest tests/test_strategy_workspace.py tests/test_strategy_page.py tests/test_dashboard_navigation.py::test_strategy_primary_workspace_is_native_and_handles_missing_data -q` → 9 passed。
- 完整 `cmd /c quality_gate.bat` → exit 0；`988 passed, 2 skipped`；branch coverage `82.53%`（門檻 78.5%）。
- quality gate 內含 targeted、full pytest、coverage、Black、Ruff、focused mypy、compileall、privacy、release layout、regression baseline；詳見 `artifacts/sprint21/quality-gate.log`。
- 官方 `.venv` `pip-audit --format json` → exit 0、無已知漏洞；`artifacts/sprint21/pip-audit.json`。
- performance hard gate → passed；`artifacts/sprint21/performance-result.json`。

## 候選與完整性

- `build_exe.bat` exit 0，staging：`release/staging-sprint21/StockTool`。
- stable EXE SHA-256：`A208849AB93FC1DDE2FDD130ED2E5C84EE60CBA0802AC1FD30D995187EB5B38F`。
- payload EXE SHA-256：`E4549EF2F577857278E6924FAEE08F43552AC23CF5E4309ECF9656D59DB82003`。
- 候選版本：`1.2.2`；staging payload/privacy validation 通過。
- artifact 對照：`artifacts/sprint21/candidate-hashes.json`。
- source archive：`artifacts/sprint21/staging-sprint21-source.zip`；SHA-256 `499E50397C1CBC3CF2ED35E33A5EF23F04F6C26908274DEDFA4B1F926085950F`。獨立解壓驗證 missing required inputs、forbidden、content mismatch、duplicate 均為 0，包含 `stable_launcher.py` 與 `StableLauncher.spec`。

## EXE、隔離資料與清理

- 候選 `--version` 回傳 `1.2.2`；隔離 EXE health/performance smoke 通過。
- process-scoped transport harness online/offline/partial 均 exit 0，證據位於 `artifacts/sprint21/transport-*`，每次使用獨立 user-data root。
- 真實資料只讀 manifest：`artifacts/sprint21/real-user-data-before.json`、`real-user-data-after.json`、`real-user-data-diff.json`；file count 與內容零差異。
- 正式 `release/StockTool/StockTool.exe` 前後 SHA-256 均為 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。
- 收尾 StockTool／StockToolPayload process 與 8501/8502 listener 均為 0。

## Browser best-effort

已嘗試連線真實瀏覽器控制面，但環境回報 `No browser is available`。因此沒有用 AppTest、fixture、假 JSON 或舊截圖冒充瀏覽器操作；九個情境結果誠實記錄於 `artifacts/sprint21/browser/browser-result.json`。依 Sprint 21 規則，這是 best-effort limitation，未單獨阻擋 implementation evidence；完整鍵盤／縮放／可見畫面需在可用瀏覽器環境由 CTO 另行驗證。

本文件只記錄 implementation evidence，不代表獨立 CTO acceptance、release approval 或下一 Sprint 核准。
