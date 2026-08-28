# SPRINT 27 implementation evidence

狀態：implementation evidence complete — pending independent CTO acceptance。

本文件只記錄實作證據，不代表 CTO 驗收、正式發布、簽章或 release approval。

## Phase A checkpoint

- checkpoint commit：`35b681611ff41e86e8d11762b6111b5c666416d2`
- annotated tag：`sprint26.2-accepted-2026-08-09`
- checkpoint 只納入 Sprint 26.2 核准的 source、tests、roadmap 與 acceptance 文件；未使用 `git add -A`。
- `artifacts_sprint25_1_1_quality.log` 保持未追蹤，未納入 checkpoint；`artifacts/` 未納入 checkpoint。
- 未 push、未建立 PR；Sprint 27 source 仍未提交。

## Sprint 27 implementation

- 新增 `src/stock_tool/application/daily_research_inbox.py`：以 immutable scheduled-run records 與 schema-v2 brief 為權威來源，建立最多 30 筆的唯讀收件匣、缺檔／壞 schema／fingerprint／reference fail-closed 驗證、繁中原因與下一步、驗證後 JSON/HTML 匯出。
- 新增嚴格 disabled-by-default notification settings、atomic immutable notification ledger、bounded history projection、run_id／brief fingerprint 去重、injectable `Notifier`、deterministic fake 與 Windows built-in adapter。
- `src/stock_tool/runtime_paths.py` 新增私有 notification settings／ledger 路徑；`daily_research_scheduler.py` 與 `launcher.py` 以 success callback 串接通知，notifier 失敗不改變 runner 結果。
- `home.py`、`shell.py`、`settings_workspace.py`、`app.py` 接入每日研究收件匣與通知設定；UI 不會因 render 自動刷新或連線。
- `PRODUCT_EXECUTION_PLAN.md` 更新 Sprint 26.2 independently accepted 與 Sprint 27 scope/non-goals/rollback/acceptance；原生 Chrome zoom 維持 deferred。
- `src/stock_tool/quality_gate.py`、`tests/test_daily_research_inbox.py`、`tests/test_daily_schedule_ui.py`、`tests/test_daily_home.py` 納入 quality gate。

## Automated verification

- targeted pytest：99 collected／99 passed；`artifacts/sprint27/targeted-pytest.log`、`targeted-collect.log`。
- full quality gate：`1188 passed, 2 skipped, 2 warnings`；branch coverage `82.25%`，gate `78.50%`；`artifacts/sprint27/quality-gate-final.log`。
- Black、Ruff、focused mypy、compileall、project privacy、release layout、regression baseline：quality gate exit 0。
- pip check：exit 0，`artifacts/sprint27/pip-check.log`；本輪 `final-pip-check.log` 亦為 UTF-8 且 exit 0。
- official pip-audit：exit 0、98 dependencies、0 vulnerabilities；UTF-8 JSON `artifacts/sprint27/pip-audit.json` 與本輪 `final-pip-audit.json`。
- performance hard gate：`artifacts/sprint27/final-performance-result.json`，固定五項指標均 pass；EXE health-ready max `3.7863769999239594s`（threshold 5s）。歷史第一次 readiness 超過 5s 的失敗保留於 `performance-attempt-20260809T125301-failed.json`，未覆寫。
- `git diff --check`：pass。

## Final candidate and source archive

最終 staging candidate 位於 `release/staging-sprint27-final`，未覆寫 `release/StockTool`。

- stable EXE：`release/staging-sprint27-final/StockTool/StockTool.exe`，version resource `1.2.2`，SHA-256 `EA61AA44116FB0A03D510DE177E753165C18EDD4BC259E220C16720B326DBBEA`，size `7,110,857`。
- payload：`release/staging-sprint27-final/StockTool/versions/1.2.2/StockToolPayload.exe`，version resource `1.2.2`，SHA-256 `378649FE51E334A74C5433F5A6B3D79FF3036CC99A3064DA3DAD991D14FF7AD1`，size `23,902,826`。
- source ZIP：`artifacts/sprint27/sprint27-source.zip`，SHA-256 `1E0B4275FB059862A7426389C98AFACE5D3EE3B7365E02BCF453A6597AA4BF1B`；`final-source-archive-verification.json`：missing/forbidden/mismatch/duplicate 全部 0。
- formal EXE：`release/StockTool/StockTool.exe`，SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`，前後一致。
- candidate binding：`artifacts/sprint27/final-candidate-hashes.json`、`.sha256`、`final-version-resource.json`。
- 初次 final staging build 曾遇到 PyInstaller 後的 Windows move access-denied；保留該歷史輸出，完成同一 staging 的 payload validation、versioned copy 與 authority activation 後再取得下列 final hashes。未因此修改正式 release。

## Isolated EXE / headless matrix

所有下列 final candidate 執行均透過 `scripts/evidence_launcher.py`，使用獨立 temporary data root，並以 guard 做真實資料 before/after 與 cleanup。

- success=0：`artifacts/sprint27/final-headless-success/guard`；schema-v2 brief、immutable run record、latest/history 可讀，references resolved，offline cache fallback；guard passed、harness 0、cleanup verified。
- partial=10：`artifacts/sprint27/final-headless-partial-final`；guard passed。
- skipped=20：`artifacts/sprint27/final-headless-skipped-final`；guard passed。
- already-running=30：`artifacts/sprint27/final-headless-already-running-final3`；guard passed。
- failed=40：`artifacts/sprint27/final-headless-failed-final`；guard passed。
- 完整允許 exit-code singleton 與 observed code：`artifacts/sprint27/final-headless-status-matrix.json`，`matrix_passed=true`。
- online／offline／partial health smoke：`artifacts/sprint27/final-exe-smoke-{online,offline,partial}` 與 `final-exe-smoke-summary.json`，三者 health-ready、guard、cleanup、zero diff 均 pass。
- final performance 的 EXE readiness 亦透過 evidence launcher；無候選程序或 listener 殘留。

## Browser evidence

最終 live session 使用上述 final stable candidate、獨立 data root，capture 時 listener 存活；擷取後才由 guard cleanup。已親自檢查三張 PNG：

- session：`sprint27-browser-final2-20260809T132659`
- `artifacts/sprint27/browser-final2/home.png`：StockTool 首頁與主要輸入。
- `artifacts/sprint27/browser-final2/inbox-visible.png`：每日證據鏈研究簡報與每日研究收件匣。
- `artifacts/sprint27/browser-final2/settings-notification.png`：通知停用狀態、啟用／停用／測試通知按鈕。
- PNG SHA-256：home `5C7013726EC67846A4AD31FF678897A1F844E0A3059B49500D41EF9BDC795A80`；inbox `6B4A22D8AE852F999BAE0C538C90B909CBF6723112D26E8EC6546C3AC1B7F5EB`；settings `59229EC60C156EEDB00A1255B80E2E0BCA736437FC49378F9747CFE547FC5D04`。
- 同 session DOM、active console、transport、launch、guard、cleanup 均保存於 `artifacts/sprint27/browser-final2`；三個 active console error count 均為 0。
- capture session manifest：`artifacts/sprint27/final-browser-session-manifest.json`，SHA-256 `51021F3D8E9B241BB24EF4C751066B012A75A557238E18A001FA4BE2765CA0E2`；每個 capture timestamp 都在 launch→cleanup window。
- final browser result：`artifacts/sprint27/final-browser-result.json`，SHA-256 `9EF1BA0194300A7268749675631EBD6B00CF2B8542F82B74CA79C385017D1200`，`overall_passed=true`、`active_console_error_count=0`，並綁定 stable/payload/source/formal hashes 與 manifest hash。
- browser history：`artifacts/sprint27/browser-history-index.json`；目前掃描 `157` 筆 guard，`passed=117`、`failed=40`。歷史失敗未刪除或改寫。
- 原生 Chrome 100%／125%／150% zoom：`deferred_to_formal_release`；未以 viewport resize 冒充。
- 先前 browser session duration 到期後產生 teardown console 的失敗輪次保留於 `browser-final-attempt2`；不被 final result 引用。

## Notifications

- `artifacts/sprint27/notification-evidence-final.json` 綁定 final candidate 與 settings screenshot；預設停用，未送出 OS 測試通知。
- 未安裝 packaged AppUserModelID 時 Windows adapter 回報 unavailable，不修改 Registry／Start Menu；站內收件匣仍可用。
- notification ledger 與 settings 測試涵蓋 strict bool、success-only、run/fingerprint dedup、non-success suppression、notifier exception、corruption、bounded history 與 privacy redaction。

## Real-data and cleanup

- `%LOCALAPPDATA%\\StockTool` 只讀 baseline 191 files；`artifacts/sprint27/real-data-before.json`、`final-final-real-data-after.json`、`final-final-real-data-diff.json`：`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。
- formal EXE hash zero diff；production `\\StockTool\\DailyResearchBrief` task absent，未建立或啟用正式 task。
- final guards：StockTool／StockToolPayload process 0、8501／8502 listeners 0；temporary scheduler task 0。
- `artifacts_sprint25_1_1_quality.log` 仍為使用者既有未追蹤檔，未修改、未提交、未放入 source ZIP。
- `artifacts/sprint27/final-artifact-encoding-scan.json`：256 個 JSON/JSONL/log/txt/csv/sha256 檔案均為 strict UTF-8、無 BOM，JSON/JSONL 全部可解析。

## Historical disclosure and limitations

- 舊 candidate `release/staging-sprint27` 的 hashes 與 browser evidence 保留；`superseded-old-candidate-hashes.json` 說明它不是 final candidate。
- 曾有一次僅讀取 `--version` 的直接候選探測未帶 evidence launcher；未產生資料差異或殘留，已由 `version-audit-incident.json` 與 `real-data-direct-diff.json` 揭露，且不被引用為 final smoke 通過證據。
- final candidate 的 guarded `--version` probe 亦保留於 `final-version-smoke`；因版本程序不開 HTTP health，guard status 為 failed，但輸出為 `1.2.2`。版本 resource 以 `final-version-resource.json` 重新核對；health smoke 與 headless matrix 均使用 guarded final candidate。
- Windows notification adapter 需正式 packaged identity 才能可靠呈現 OS notification；本輪不修改系統身分。
- 原生 zoom deferred；其餘 browser screenshot/DOM/console/transport/guard 證據均為 final candidate 同 session。

## Governance

未簽章、未發布、未 promotion、未 push、未建立 Sprint 28，未修改正式 EXE、正式 installer、正式 Task Scheduler 或真實使用者資料。此文件等待獨立 CTO 驗收。
