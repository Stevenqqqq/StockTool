# StockTool Sprint 22.1.1 implementation evidence

狀態：implementation complete，等待 CTO 驗收；不是正式發布或獨立 acceptance。

## 根因與修正

production `DashboardShellDependencies.refresh_portfolio_data` 原本以位置參數呼叫 callback，與 `_refresh_portfolio_analysis(st, portfolio, *, force_refresh: bool)` 的 keyword-only 契約不符，造成 native 持倉「更新市場資料」失敗並顯示 TypeError。

修正：

- `src/stock_tool/dashboard/shell.py` 新增 `PortfolioRefreshCallback` Protocol，明確宣告 `__call__(st, portfolio, *, force_refresh: bool) -> object`。
- shell 唯一正式呼叫改為 `refresh_portfolio_data(st, positions, force_refresh=True)`。
- 成功 refresh 後失效 native analysis/stress session state；refresh 例外時保留既有結果並由 UI fail-closed。
- `tests/test_dashboard_shell.py` 新增 strict keyword-only fake；修正前會因同一 TypeError 失敗，修正後驗證 callback 呼叫一次、`force_refresh is True`，以及成功失效／例外保留行為。
- `src/stock_tool/application/portfolio_workspace.py`、native workspace、既有 FX resolution 與 stress manifest 綁定未回退。

## 驗證

- targeted：`tests/test_dashboard_shell.py tests/test_portfolio_workspace.py tests/test_dashboard_navigation.py tests/test_portfolio_fx.py` — passed。
- full pytest：**1026 passed, 2 skipped**。
- branch coverage：**83.14%**（門檻 78.5%）。
- `cmd /c quality_gate.bat`：exit 0；targeted/full/coverage/Black/Ruff/focused mypy/compile/privacy/release layout/regression baseline 全部 passed。
- `pip check`：No broken requirements found。
- 官方 `.venv` `pip-audit --format json`：exit 0，No known vulnerabilities；結果留於 `artifacts/sprint22.1.1/pip-audit.json`。
- performance hard gate：`artifacts/sprint22.1.1/performance-result.json`，固定門檻未修改，passed。
- `git diff --check`：exit 0。

## Final candidate

使用 `STOCK_TOOL_STAGING_PARENT=release\\staging-sprint22.1.1 cmd /c build_exe.bat` 重新建立，並完成 staging trust-boundary、payload asset 與 source archive 驗證。完整 hashes 在 `artifacts/sprint22.1.1/candidate-hashes.json`：

- stable EXE：`D6BA0A2C349FCD67EDE03244ED730AB6640DCDB417FDA0C1FDA24AD452AB0B75`
- payload EXE：`D9A0FB4A602F756D1B1382315CC91939DEF4135E191AC3A99F2C26900C4534A1`
- source ZIP：`B3563859DDFB57443DE1315589275FB27D2BAF6E3DF8543F632F47769E81A3CD`
- formal `release/StockTool/StockTool.exe`：`4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`（unchanged）

`artifacts/sprint22.1.1/exe-smoke.json` 證明本次 final stable/payload hash、`--version` 均為 1.2.2 且 exit 0；health `200/ok` 在 8501。沒有沿用 Sprint 22.1 的 AA1010 舊 smoke。source archive 獨立驗證 missing/forbidden/content mismatch/duplicate/workspace mismatch 全為 0。

## 資料與治理

`artifacts/sprint22.1.1-real-before.json`、`artifacts/sprint22.1.1-real-after.json`、`artifacts/sprint22.1.1-real-compare.json` 為 `%LOCALAPPDATA%\\StockTool` 只讀 manifest；`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。正式 release、installer、簽章狀態未修改；沒有 commit、push、tag 或 Sprint 23。

收尾 `artifacts/sprint22.1.1/cleanup.json`：StockTool/StockToolPayload process 0、8501/8502 listener 0。

## Browser evidence

`artifacts/sprint22.1.1/browser-result.json` 綁定本次 candidate hashes，保留 2330/TWSE、6488/TPEX、AAPL/US × online/offline-cache/partial-failure 九個情境。當前環境沒有可操作的真實 browser control surface，故每項誠實標為 `BLOCKED`，沒有以 AppTest、fixture 或假截圖取代；由 CTO 親自重跑真實瀏覽器旅程。
