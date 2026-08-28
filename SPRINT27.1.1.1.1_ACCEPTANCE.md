# Sprint 27.1.1.1.1 implementation evidence

本文件只記錄本輪修正的 implementation evidence，等待獨立 CTO 驗收；不代表發布、簽章或正式 acceptance。

## 範圍

- 修正 `_atomic_create_json` 的跨程序 exclusive-create 競態：`FileExistsError` 立即向上拋出，只有本次成功取得 descriptor 的 invocation 才能清理自己的部分檔案。
- 移除 `create_claim()` 與 `status()` 的 unreachable compatibility body。
- 保留 claim identity、完整 graph validation、pending claim 與既有 notification exactly-once 行為。
- 本輪未修改 formal EXE、installer、正式排程、registry、Start Menu 或真實使用者資料；未 commit/tag/push。

## 修改檔案

- `src/stock_tool/application/daily_research_inbox.py`
- `tests/test_daily_research_inbox.py`
- `SPRINT27.1.1.1.1_ACCEPTANCE.md`

## 競態與回歸測試

- focused inbox/home/schedule：61 passed。
- concurrency/adversarial focused subset：20 passed（`artifacts/sprint27.1.1.1.1/concurrency-focused.log`）。
- full pytest：1228 passed, 2 skipped, 2 warnings。
- 新增/保留測試涵蓋：既有 winner claim 的 bytes/hash 不變、delayed loser、兩個獨立 store/service、兩個獨立 Python process staggered contention、restart deduplication、owned partial-file cleanup，以及既有 simultaneous thread/process tests。
- 競態結果：loser 只得到 duplicate/FileExistsError；winner claim 可解析；notifier send count=1；重啟後仍為 1。

## 品質閘門

`cmd /c quality_gate.bat` exit 0（本輪 `artifacts/sprint27.1.1.1.1/quality-gate.log`）：

- branch coverage：82.51%（門檻 82.51%）。
- 1228 passed, 2 skipped；Black、Ruff、focused mypy、compileall、privacy、release layout、regression baseline 全部通過。
- targeted 與 full pytest log：`artifacts/sprint27.1.1.1.1/targeted-tests.log`、`artifacts/sprint27.1.1.1.1/full-pytest.log`。
- pip check exit 0：`artifacts/sprint27.1.1.1.1/pip-check.log`。
- 官方 pip-audit exit 0、JSON 可解析：`artifacts/sprint27.1.1.1.1/pip-audit.json`。
- UTF-8/BOM/JSON validation：`artifacts/sprint27.1.1.1.1/encoding-validation.json`，61 files、0 errors。

## 新候選與 source archive

build command：`$env:STOCK_TOOL_STAGING_PARENT='release/staging-sprint27.1.1.1.1'; cmd /c build_exe.bat`，exit 0。stable 與 payload `--version` 均為 `1.2.2`。

`artifacts/sprint27.1.1.1.1/candidate-hash-binding.json`：

| 成品 | SHA-256 | 大小 |
| --- | --- | ---: |
| `release/staging-sprint27.1.1.1.1/StockTool/StockTool.exe` | `91638003E917A2A379E5A159A0B0BF23EDA08E50C4E94635A3A20E896FB7498B` | 7,110,500 |
| `release/staging-sprint27.1.1.1.1/StockTool/Payload/StockToolPayload.exe` | `9DCD369C1D482C7903F5876CA01884C01B409B31F2E58BD5E0FD18BCD5915B3A` | 23,914,314 |
| `release/staging-sprint27.1.1.1.1-source.zip` | `897F76F9DAE15610E57C4F4E01CC9639699F6B0637BF48040030DFE37E572DF7` | 2,591,161 |
| formal `release/StockTool/StockTool.exe` | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` | 24,145,141 |

source archive command `python -m stock_tool.release_archive --root . --output release/staging-sprint27.1.1.1.1-source.zip` exit 0；missing/forbidden/content mismatch/duplicate 均為 0（`source-archive-verification.json`）。hash index 與 sidecar：`artifacts/sprint27.1.1.1.1/evidence-hash-index.json`、`evidence-hash-index.sha256`，386 files（index/sidecar 自身明確排除並由 sidecar 綁定）。

## Performance hard gate

新候選、全新隔離資料根、三次固定測量：`artifacts/sprint27.1.1.1.1/performance-result.json`，overall passed=true；`exe_health_ready` = 3.78024s、3.77870s、3.78967s，max 3.78967s <= 5s。其他項目亦均通過門檻。冷啟動診斷與「不以重跑掩蓋失敗」判定在 `performance-diagnosis.json`。

歷史 6.306s failure 未被覆寫；`performance-history.json` 以 `preserved_historical_failure` 明確索引使用者提供的歷史事件（原始檔案目前不在 workspace 可尋範圍，沒有冒充可驗證原始檔）。workspace 中可驗證的既有 5.05352s failure `artifacts/sprint27/performance-attempt-20260809T125301-failed.json` 亦保留。新 canonical 只指向本輪結果。

## 隔離 EXE/browser smoke

- health smoke：`artifacts/sprint27.1.1.1.1/health-smoke/`，guard passed、harness exit 0、health ready 3.78171s、191→191 zero diff、cleanup verified。
- headless no-target smoke：`artifacts/sprint27.1.1.1.1/headless-skipped/`，透過 evidence launcher，exit 20/skipped_no_targets，cleanup passed。
- live browser session：`sprint27.1.1.1.1-online-20260811T123530Z`。同一 session 取得首頁與設定頁/每日研究排程畫面；PNG、DOM、console、launch、guard、cleanup 的 hash/size/timestamp 在 `browser-session/capture-session-manifest.json`，結果在 `browser-result.json`。active console errors=0、guard passed、harness_exit_code=0、candidate/listener remaining=0、overall_passed=true。
- 首頁畫面已實際檢查；設定頁畫面實際顯示「每日研究排程」、週一至週五 18:30（Asia/Taipei）與通知不可用。Native Chrome 100/125/150% 維持 `deferred_to_formal_release`，未以 viewport 冒充。

Windows WinRT construction probe 仍為既有 hash-bound exit 0、`show_called=false`；沒有 packaged identity 時通知維持 unavailable，不偽造 AppUserModelID（`artifacts/sprint27.1.1/windows-runtime-probe.json`）。

## 真實資料與清理

`artifacts/sprint27.1.1.1.1/real-data-before.json`、`real-data-after.json`、`real-data-diff.json`：191→191，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。正式 EXE hash 維持上述基線。

`cleanup-audit.json`：StockTool/StockToolPayload=0、8501/8502 listeners=0、temporary task=0、production `\\StockTool\\DailyResearchBrief` absent。所有候選均由 `scripts/evidence_launcher.py` 啟動；無 direct candidate fallback。

## 限制與歷史

- 既有 Sprint 27.1.1 與歷史 failed evidence 未刪除或改寫；本文件為獨立 27.1.1.1.1 evidence，不附加到舊 acceptance。
- 原始 6.306s failure binary 不在目前 workspace，已以外部來源索引誠實保留，不宣稱已重新驗證該檔案。
- 沒有 packaged Windows identity，因此 OS notification unavailable；站內收件匣與設定頁仍可用。
- 本輪沒有正式發布、簽章、promotion、commit、tag、push 或 Sprint 28。

## 本輪狀態

claim race、delayed loser、restart deduplication、performance canonical、候選重建、隔離 browser/EXE smoke 與資料清理均有可核對證據；但原始 6.306 秒 failure 檔案不在目前 workspace，只有使用者提供的歷史事件索引，故本文件保留該缺口並交由 CTO 判定，不自行宣稱完整通過。
