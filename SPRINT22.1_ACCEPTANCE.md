# StockTool Sprint 22.1 implementation evidence

狀態：`BLOCKED` — browser journeys 仍缺少可用的真實瀏覽器控制面；本文件不是 CTO acceptance。

## 範圍與修改

本 correction 保留 Sprint 21.1 checkpoint（`43de40bd626d7ed785f7450fc527820fed7acee5`、`sprint21.1-accepted-2026-08-02`），沒有 commit/push，也沒有接觸正式 release 或真實使用者資料。

修改／新增的產品與測試檔案：

- `src/stock_tool/application/portfolio_workspace.py`：壓力結果以 manifest digest 與完整 `StressScenario` 綁定，提供 current 判斷；manifest 保存 FX source/effective/applied/stale metadata。
- `src/stock_tool/application/__init__.py`：匯出新的 stress evidence model。
- `src/stock_tool/dashboard/pages/portfolio_workspace.py`：變更持股、重新載入、更新資料、FX、重新分析及情境參數時失效壓力結果；手動匯率使用實際 UTC `applied_at`、過期 fail-closed；顯示 FX metadata；三處 `use_container_width` 改為 `width="stretch"`；分析使用分類資料。
- `src/stock_tool/dashboard/shell.py`：native portfolio refresh 注入既有 `PortfolioRefreshService`/FX resolution callback，分類只取既有 cache。
- `src/stock_tool/dashboard/app.py`：composition root 注入既有 refresh 與 source-backed classification callback，並支援 native manual FX state。
- `tests/test_portfolio_workspace.py`：stress manifest/scenario、持股變更後 stale、混合市場分類、手動 FX timestamp/expiration 與 AppTest regression。

## 驗證命令與結果

| gate | command/result |
|---|---|
| targeted | `.venv\\Scripts\\python.exe -m pytest tests/test_portfolio_workspace.py tests/test_dashboard_shell.py tests/test_dashboard_navigation.py tests/test_portfolio_fx.py -q` — passed |
| full | `.venv\\Scripts\\python.exe -m pytest --cov=stock_tool --cov-branch ... -q` — **1024 passed, 2 skipped** |
| coverage | branch coverage **83.11%**（門檻 78.5%） |
| quality wrapper | `cmd /c quality_gate.bat` — exit 0；Black、Ruff、focused mypy、compile、privacy、release layout、regression baseline 全部 passed |
| pip | `pip check` — no broken requirements；UTF-8 mode 官方 `pip-audit --format json` — exit 0、no known vulnerabilities |
| performance | `scripts/measure_performance.py`，3 runs/measurement，`artifacts/sprint22.1/performance-result.json` — passed；未調整任何門檻 |
| staging | `STOCK_TOOL_STAGING_PARENT=release\\staging-sprint22.1 cmd /c build_exe.bat` — exit 0；trust-boundary、payload asset validation passed |
| source archive | `release_archive --output artifacts/sprint22.1/staging-sprint22.1-source.zip`；獨立解壓驗證 missing/forbidden/content mismatch/duplicate 全為 0，workspace mismatch 0 |
| EXE smoke | stable/payload `--version` 均 1.2.2 exit 0；health `200/ok` on 8501；cleanup 後 process/listener 皆 0 |

## Candidate hashes

完整資料在 `artifacts/sprint22.1/candidate-hashes.json`：

- stable EXE：`4910F004C43E7EC7477B5B407A0BF905A72DCC72A82C8880DB6A2857CB4A519F`
- payload EXE：`B1AAD0C6E97EBDF7209B381D65DDF8F304A7396984DE5D1572D09716A48F5AF4`
- source ZIP：`5201DEBF7C1AFF2557A1E921410B47C1FF4EE9FD97B2C729930B5D9C1E536161`
- formal `release/StockTool/StockTool.exe`：`4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`（unchanged）

## Real-data preservation

只讀 manifest：`artifacts/sprint22.1-real-data-before.json`、`artifacts/sprint22.1-real-data-after.json`、`artifacts/sprint22.1-real-data-compare.json`。比較結果 `file_count` 保持原 185，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。未刪除或修改既有真實資料檔案。

## Browser limitation

`artifacts/sprint22.1/browser-result.json` 保留 2330/TWSE、6488/TPEX、AAPL/US × online/offline-cache/partial-failure 九個情境；每項明確為 `BLOCKED`，沒有以 AppTest、fixture 或假截圖冒充 browser evidence。因目前環境沒有可操作的真實 browser control surface，未產生真實 screenshot/DOM/active-console journey 證據；這是本 Sprint 的唯一未完成硬證據。

清理證據：`artifacts/sprint22.1/cleanup.json`，StockTool/StockToolPayload process 0、8501/8502 listener 0。未宣稱 CTO acceptance、正式發布或下一 Sprint 核准。
