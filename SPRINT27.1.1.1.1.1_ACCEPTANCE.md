# Sprint 27.1.1.1.1.1 Acceptance Evidence

## 狀態

`BLOCKED` — 使用者指定的 5.5325 秒冷啟動失敗原始 evidence 在本輪開始時不在工作區，無法聲稱已保留原始失敗檔案。該數值只以 `artifacts/sprint27.1.1.1.1.1/performance-history.json` 的明確 `raw_artifact_found=false` 紀錄保存，不以新測量冒充舊 evidence。

本文件是 implementation evidence，不是 CTO acceptance。

## Correction implementation

- `src/stock_tool/application/daily_research_scheduler.py`
  - frozen/packaged 啟動時明確解析 `SystemRoot`／`WINDIR` 下的 `System32/schtasks.exe`，再安全退回 PATH。
  - Windows 命令輸出使用 active code page（`mbcs`），並保留英文、繁中、日文 task-not-found 判斷；查無正式 task 回報 `not_installed`。
  - 維持 list-based subprocess invocation，不使用 shell 字串拼接。
- `tests/test_daily_research_scheduler.py`
  - 英文、繁中、日文查無 task regression。
  - frozen path resolution、fallback resolution、非 Windows encoding regression。
  - 實際 Windows 缺少正式 task 的 read-only test。
- `tests/test_daily_schedule_ui.py`
  - packaged/settings UI 的「未安裝」狀態 regression。

既有 exactly-once claim、winner bytes、delayed loser、staggered process 與 restart deduplication 修改均保留，未回退。

## Tests and quality

- Targeted scheduler/inbox/home/UI: **106 passed** (`targeted-tests-final.log`).
- Claim/race focused matrix: **19 passed, 29 deselected** (`concurrency-tests.log`).
- Full pytest: **1233 passed, 2 skipped, 2 warnings** (`full-pytest-final.log`).
- `cmd /c quality_gate.bat`: **exit 0**, all configured stages passed; full pytest 1233 passed, coverage **82.52%**, Black/Ruff/mypy/compile/privacy/release-layout/regression passed (`quality-gate-final.log`).
- `git diff --check`: exit 0.
- `pip check`: exit 0; no broken requirements (`pip-check.log`).
- Official `pip-audit --format json`: exit 0, no known vulnerabilities; pure UTF-8 parseable JSON (`pip-audit.json`, `pip-audit-exit.txt`).
- Artifact UTF-8/BOM/JSON validation: passed, 66 text/JSON files (`encoding-validation.json`).
- Source archive verification: missing/forbidden/content mismatch/duplicate all 0 (`source-archive-verify.json`).
- Project privacy scan: 0 violations (`privacy-scan.json`).

## Final candidate and hashes

- Stable EXE: `release/staging-sprint27.1.1.1.1.1-final/StockTool/StockTool.exe`, 7,111,060 bytes, SHA-256 `49D1698C66D24AE7180D18BA79DF91EB6C29F1F073B95CA8F30BA668259C8A19`.
- Payload EXE: `release/staging-sprint27.1.1.1.1.1-final/StockTool/Payload/StockToolPayload.exe`, 23,914,976 bytes, SHA-256 `C8837DE556A6868063F2E0BC2D465EB78B564E779E2901C61470CDEC8698B5A0`.
- Source ZIP: `release/staging-sprint27.1.1.1.1.1-final-source.zip`, 2,592,188 bytes, SHA-256 `5AAB2B935391F2CC4D5C7FF60484ED0C0155A228D2A4BD614E9FC5009A284EA8`.
- Formal EXE unchanged: `release/StockTool/StockTool.exe`, 24,145,141 bytes, SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- All four artifact bindings rechecked successfully (`candidate-hash-binding.json`, `candidate-hash-verify.json`).

Both candidate entry points report version `1.2.2`; isolated launch health was ready in 3.7801279 seconds (`exe-smoke.json`).

## Browser evidence

Final candidate session:

- Session ID: `sprint27.1.1.1.1.1-final-9d16968e8f0b443ca886dc447c862b0a`.
- Launch: `artifacts/sprint27.1.1.1.1.1/browser-session-final-candidate/launch.json`.
- Homepage PNG/DOM/console: `home.png`, `home.dom.txt`, `home.console.json`.
- Settings scheduler PNG/DOM/console: `settings-scheduler.png`, `settings-scheduler.dom.txt`, `settings-scheduler.console.json`.
- Capture manifest: `capture-session-manifest.json`, SHA-256 `B1FD72EC6F2EF4523B9A4CA4C59A623CBDB64438D4CB1F9046DBDFD14FD7C241`.
- Capture interval: launch `2026-08-11T15:47:16.695720+00:00`; captures `2026-08-11T15:47:55.632Z`–`2026-08-11T15:48:20.857Z`; cleanup `2026-08-11T15:52:17.904821+00:00`.
- Settings DOM and screenshot show `目前狀態：未安裝`, `週一至週五 18:30（Asia/Taipei）`, and the scheduler controls; no `目前狀態：錯誤`.
- Active console errors: **0** for homepage and settings.
- Browser result: scheduler semantic assertion `overall_passed=true`, guard `passed`, harness exit 0, cleanup verified, no remaining candidate processes/listeners, real-data zero diff (`browser-result.json`).
- Native Chrome 100%/125%/150% remains `deferred_to_formal_release`; no viewport substitution was used.

## Performance

- Canonical final-candidate measurement: three cold readiness runs `3.7854015`, `3.7687019`, `3.7641387` seconds; max **3.7854015 <= 5.0** (`performance-result.json`, `performance-binding.json`). No warm-up or cherry-picking was used.
- Historical 5.5325-second failure is retained as a user-reported, unreplayed record with `raw_artifact_found=false` in `performance-history.json`; the missing original artifact is the sole blocker.

## Data and cleanup

- Real user-data baseline: 191 files before and after; `added=[]`, `removed=[]`, `changed=[]`, `zero_diff=true` (`real-data-before.json`, `real-data-after.json`, `real-data-diff.json`).
- Final guard also independently reports 191→191 and zero diff.
- Final cleanup audit: StockTool/StockToolPayload processes 0, listeners 8501/8502 = 0, production task absent, temporary acceptance task absent (`cleanup-audit.json`). No formal task was created or modified.
- Evidence history from previous sessions is retained; the earlier stale-session console result is not cited as final evidence.

## Evidence index

`artifacts/sprint27.1.1.1.1.1/evidence-hash-index.json` and its sidecar bind all final artifact files; latest index SHA-256 is `97E0893AC08E6B81FDD14553635424D2E1793408EDFA04F5DD84A4FCF99C634D`.

No formal EXE, installer, registry, Start Menu, production task, real user data, commit, tag, push, signing, or publication was changed.
