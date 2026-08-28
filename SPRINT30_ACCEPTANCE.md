# Sprint 30 implementation evidence

狀態：implementation evidence complete，等待獨立驗收。未宣稱 CTO acceptance、正式發布或 release approval。

## checkpoint

- Sprint 29.1 r2 checkpoint：`0dfe2ae`，`checkpoint: accept Sprint 29.1 r2`。
- annotated tag：`sprint29.1-accepted`。
- 未 push、未建立 PR；Sprint 30 變更保持未提交。
- `git diff --check`：exit 0。
- 未納入既有 `artifacts_sprint25_1_1_quality.log` 與未相關的 `SPRINT28.1.1.1_ACCEPTANCE.md`。

## 產品實作

- 新增 [prediction_lab.py](src/stock_tool/application/prediction_lab.py)：Prediction Lab Phase 0 的 immutable `PredictionRecord`、append-only `PredictionOutcome`、strict schema/fingerprint/exact-record hash、market-qualified identity、top/middle/bottom 與 `horizon_trading_days` 5/20 日抽樣、evaluation status 與 fail-closed graph validator；保留 `horizon` 僅作既有 Python caller 相容 alias，canonical serialized field 為 `horizon_trading_days`。
- `PredictionLabStore` 使用 exclusive create、atomic publish、immutable record authority、可重建 bounded index、corrupt/duplicate/path escape/fault/concurrency fail-closed。
- `daily_research_scheduler.py` 與 dashboard 手動成功流程只在 fresh、完整 market snapshot 後登錄樣本；partial、offline、stale、provider failure 不新增樣本。
- 首頁順序調整為今天的重點變化、今日總經背景、每日證據鏈研究簡報、預測評估實驗室、每日研究收件匣與下一步研究入口；Prediction Lab 為唯讀實驗投影，明確標示不代表未來報酬、不構成投資建議、不使用真實資金。
- `RuntimePaths` 新增 Prediction Lab 私有 runtime paths；品質閘門 changed-files 清單納入新模組與測試。
- `scripts/measure_performance.py` 的 2 秒 process hold 只讓 evidence harness 在 readiness 後完成 durable capture，不是 warm-up；hard gate 的 health-ready 計時仍由 launch 到 health 200。
- 更新 `PRODUCT_EXECUTION_PLAN.md` 與 `README.md`，記錄 Phase 0 scope、non-goals、rollback 與 social/article reference 不得視為績效證據。

## 變更檔案

- `PRODUCT_EXECUTION_PLAN.md`
- `README.md`
- `scripts/measure_performance.py`
- `src/stock_tool/application/__init__.py`
- `src/stock_tool/application/daily_research_scheduler.py`
- `src/stock_tool/application/prediction_lab.py`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/dashboard/pages/home.py`
- `src/stock_tool/dashboard/shell.py`
- `src/stock_tool/quality_gate.py`
- `src/stock_tool/runtime_paths.py`
- `tests/test_prediction_lab.py`

## 測試與品質

命令與摘要：

- `.venv\\Scripts\\python.exe -m pytest tests/test_prediction_lab.py tests/test_daily_home.py tests/test_daily_research_scheduler.py tests/test_dashboard_shell.py -q`：exit 0，108 passed；v2 contract regression log：`artifacts/sprint30/targeted-final.log`。
- `.venv\\Scripts\\python.exe -m pytest -q`：exit 0，1345 passed、2 skipped、2 warnings（`artifacts/sprint30/full-pytest-v2.log`）。
- `.venv\\Scripts\\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term`：exit 0，branch coverage **82.44%**，高於 Sprint 29.1 accepted 82.43%（`artifacts/sprint30/coverage-v2.log`）。
- `cmd /c quality_gate.bat`：子程序 exit 0，full pytest、coverage、Black、Ruff、focused mypy、compile、privacy、release layout、regression baseline 均完成；`artifacts/sprint30/quality_gate-v2.log`。外層 PowerShell 摘要因主控台無法輸出一個 Unicode 符號而中斷，未改寫子程序結果；quality gate 內建 floor 仍為 78.5%，獨立 canonical coverage 為 82.44%。
- Black：exit 0；Ruff：exit 0；focused mypy：exit 0；compileall：exit 0。
- `.venv\\Scripts\\pip.exe check`：exit 0，No broken requirements（`artifacts/sprint30/pip-check-v2.log`）。
- 官方 `.venv` pip-audit：exit 0，98 dependencies、0 known vulnerabilities；UTF-8 JSON：`artifacts/sprint30/pip-audit-v2.json`。
- `git diff --check`：exit 0；privacy/release layout：quality gate 0 violations / passed。

## performance

`artifacts/sprint30/performance-v2-final/performance-result.json` 是 v2 final candidate 的三次 canonical cold run（非 warm-up、未丟棄第一趟）：

| measurement | 三次秒數 | max | gate |
|---|---:|---:|---|
| indicators + scoring | 0.060620 / 0.075127 / 0.056372 | 0.075127 | passed |
| Excel export | 1.014560 / 1.030469 / 1.035938 | 1.035938 | passed |
| cached research | 0.007531 / 0.000494 / 0.000489 | 0.007531 | passed |
| portfolio allocation/risk | 0.035990 / 0.030083 / 0.029731 | 0.035990 | passed |
| EXE health ready | **2.527317 / 2.510100 / 2.522917** | **2.527317** | passed (<=5s) |

先前 duration=0 的 harness race 失敗保留於 `artifacts/sprint30/performance/`，未改寫成成功；其 cold-start timing 子證據仍可追溯。這不影響 final health-ready measurement。

## candidate / source / formal hashes

| artifact | path | size | SHA-256 |
|---|---|---:|---|
| stable | `release/staging-sprint30-v2/StockTool/StockTool.exe` | 7,111,757 | `4E3CC55683D40967E7DFC6AF0B9746A0AD746D2874784F0256555EDBE8137EC8` |
| payload | `release/staging-sprint30-v2/StockTool/versions/1.2.2/StockToolPayload.exe` | 24,007,587 | `B2125015E4A3283FB4FDA422E426E061814BDEEA6E5CF6F9B2A384A60B4C3B66` |
| source ZIP | `release/staging-sprint30-v2-source.zip` | 2,659,380 | `E4C1E4207FC091BEEEE933AFB2E2224863BABE6CC2940E5C2C3D7E3F77B21726` |
| formal EXE | `release/StockTool/StockTool.exe` | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

v2 staging stable/payload FileVersion/ProductVersion 均為 1.2.2。source ZIP 含 `prediction_lab.py`、`test_prediction_lab.py`，351 entries、duplicate entries=0；`release_archive` exit 0（`artifacts/sprint30/source-archive-v2.log`）。

## EXE、browser 與 verifier

- 所有候選啟動均經 `scripts/evidence_launcher.py` → `browser_transport_harness.py`，使用全新 Temp runtime roots；沒有 direct candidate Popen。
- v2 Online final same-session bundle：`artifacts/sprint30/browser-v2-bundle/`，session `evidence-93da12d2a0504299a8a31029c0212246`。已擷取並親自檢查新的 `home.png`、`changes.png`、`brief.png`、`settings.png` 及對應 DOM/console；未引用 v1 capture bytes。
- Home/brief 畫面顯示「預測評估實驗室（實驗）」與資料不足時的安全狀態及研究限制；Settings 畫面顯示每日研究排程「未安裝」、週一至週五 18:30（Asia/Taipei）與通知 capability unavailable。
- active console error count=0；capture timestamps 均在 `launch_started_utc` 與 `cleanup_completed_utc` 之間。
- `scripts/verify_evidence_bundle.py artifacts/sprint30/browser-v2-bundle --workspace-root . --stable-candidate release/staging-sprint30-v2/StockTool/StockTool.exe --payload-candidate release/staging-sprint30-v2/StockTool/versions/1.2.2/StockToolPayload.exe --source-zip release/staging-sprint30-v2-source.zip --formal-exe release/StockTool/StockTool.exe`：exit 0，`passed=true`、`errors=[]`；candidate binding、capture manifest、raw PNG/DOM/console、strict allowlist、index/sidecar、task state、real-data manifests 均 exact match。
- v2 bundle raw bindings：`capture-session-manifest.json` 4,145 bytes / `3BB64E5AAE28710115D76D90E7E5183CAA36F3E5A8ACD195B28434A80C26295F`；`browser-result.json` 2,277 bytes / `55106D0CD43EFE20E32A716745EDC354F664C63C7C4741F8C73A4243B6AFF76B`；`evidence-hash-index.json` 4,225 bytes / `2D936B91A26EC86D8E7D4CF60305140889275AAEA291466F35CEA4831BD78FD1`。衍生摘要：`artifacts/sprint30/verification-summary-v2.json`。
- `verification-summary-v2.json` SHA-256：`66E4CA35975DAB877D611403465C6FDB4E4B392035F22AEECB3F74A3C56D73B9`。
- Isolated v2 online smoke：`artifacts/sprint30/exe-v2-online` passed；offline：`artifacts/sprint30/exe-v2-offline` passed；partial：`artifacts/sprint30/exe-v2-partial` passed。三者均有 guard/launch/transport/cleanup 與 zero-diff evidence。
- 同一 final candidate 的新增瀏覽器狀態證據：`artifacts/sprint30/browser-v2-scenario-evidence.json`（SHA-256 `6C0D193F16955B0BF0C2CDDEBA251C27B4CCF9B431412943EDD904C7D368A933`）。`offline-browser-v2-fixture` 與 `partial-browser-v2` 各自透過 evidence launcher、隔離資料根與 live browser 擷取首頁/Prediction Lab PNG、DOM、console；兩者均顯示安全的資料不足/更新失敗狀態，active console error=0，且 cleanup/real-data zero diff 通過。它們是分開的受控狀態 session；v2 canonical bundle 的 home/changes/brief/settings 則維持同一 session。
- Native Chrome 100%/125%/150% 仍為 `deferred_to_formal_release`，未以 viewport resize 冒充。

## data / cleanup / limitations

- `%LOCALAPPDATA%\\StockTool` 僅建立 read-only before/after manifests：191→191，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。
- `StockTool`/`StockToolPayload` process=0；8501/8502 listener=0。
- `\\StockTool\\DailyResearchBrief` production task absent；temporary acceptance task absent；未建立或修改任何 Task Scheduler task、registry、Start Menu、installer 或 formal release。
- 歷史 browser/performance failures 與 v1 bundle 保留於 `artifacts/sprint30/`，未刪除或覆寫成成功；v2 bundle 與歷史 evidence 分開。
- Prediction Lab 尚為 Phase 0：僅使用既有 deterministic market ranking，樣本到期 evaluation 尚未形成真實績效；首頁不顯示勝率、不提供預測、目標價或交易指令。
- AI/ML、背景排程啟用、Windows 原生通知與 native zoom 不在本 Sprint 內。
