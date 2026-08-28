# Sprint 26.2.1 implementation evidence

狀態：**BLOCKED — implementation evidence ready for independent CTO review**。
本文件不是 CTO acceptance、release approval 或 production task activation。

## 範圍與修正

- `daily_research_scheduler.py`：Python weekday 0–6 對應 Monday–Sunday；預設排程 XML 僅 Monday–Friday；refresh 先於新時段 hash 判斷；immutable `run-*.json` 為權威、latest/history 為可重建 projection；strict bool settings、corrupt settings disabled；語系無關的 XML／LIST query 與未安裝映射；未安裝 task 的 run-now 不送出 `/Run`。
- `tests/test_daily_research_scheduler.py`、`tests/test_daily_schedule_ui.py`：weekday 集合、query fallback、strict bool、31→30 history、fault injection、refresh ordering、run-now 與 UI 回歸。
- `src/stock_tool/dashboard/pages/settings_workspace.py`：未安裝狀態與 Asia/Taipei 18:30 的繁中顯示。
- `scripts/verify_sprint26_2_task.py`：唯一 nonce temporary task lifecycle，UTF-8 XML sidecar。
- `PRODUCT_EXECUTION_PLAN.md`：Sprint 26.2.1 scope、rollback、未安裝 production task 與 zoom deferred 契約。

## Checkpoint governance

- Sprint 26 checkpoint 未改寫：commit `87e3d51092c56469d23e7ef7d218126544bea77d`、tag `sprint26-accepted-2026-08-09`。
- excluded acceptance metadata-only supplement：commit `26bc171b6d96451403ecb6bd931fb42ed06002ef`，僅含 `SPRINT26.1.1.1.1_ACCEPTANCE.md`，未含 Sprint 26.2 source、artifact 或 `artifacts_sprint25_1_1_quality.log`。
- 未 push、未建 PR、未建立 production task、未 commit Sprint 26.2.1。

## Automated verification

- `tests/test_daily_research_scheduler.py tests/test_daily_schedule_ui.py`：40 passed。
- `cmd /c quality_gate.bat`：exit 0；`1170 passed, 2 skipped, 2 warnings`；branch coverage `82.47%`（gate `78.50%`）；Black、Ruff、focused mypy、compile、privacy、release layout、regression baseline 均通過。Durable output：`artifacts/sprint26.2.1/quality-gate-final2.log`（UTF-8、無 BOM、含 `[quality-gate] PASSED`）。
- `pip check`：exit 0，`artifacts/sprint26.2.1/pip-check-final.log`。
- official `pip-audit --format json --progress-spinner off`：exit 0、0 vulnerabilities；`artifacts/sprint26.2.1/pip-audit-final.json` 可直接 UTF-8 parse。
- performance hard gate：`artifacts/sprint26.2.1/performance-final.json`，5 項各 3 次，`passed=true`；EXE health max 約 3.803 秒／threshold 5 秒。
- artifact 文字／JSON／JSONL／log／sha256 scan：246 files，BOM 0，UTF-8 decode/JSON parse errors 0。
- source ZIP：`artifacts/sprint26.2.1/sprint26.2.1-source.zip`；SHA-256 `B660F45BCC79D7BED1ED36CA78D5DF54596EB163BB3947CF84E413E70C01585E`；`source-verify-final4` missing/forbidden/content-mismatch/duplicate 全為 0。
- `git diff --check`：exit 0。

## Candidate and formal hashes

| artifact | path | size | SHA-256 |
|---|---|---:|---|
| stable | `release/staging-sprint26.2.1/StockTool/StockTool.exe` | 7,110,802 | `DF11F90299F37E7860721C6F2C3E682E8089A598D6AFC45E7A79B7A52CB08630` |
| payload | `release/staging-sprint26.2.1/StockTool/versions/1.2.2/StockToolPayload.exe` | 23,883,425 | `6E40D8EF5532B7246E42AE2C1C231C4A1FD0F74AABAF3596CE2E078641C421EC` |
| source ZIP | `artifacts/sprint26.2.1/sprint26.2.1-source.zip` | 2,568,357 | `B660F45BCC79D7BED1ED36CA78D5DF54596EB163BB3947CF84E413E70C01585E` |
| formal EXE | `release/StockTool/StockTool.exe` | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

Binding record：`artifacts/sprint26.2.1/candidate-hashes-final.json`。

## Task Scheduler evidence

- Temporary task lifecycle：`task-scheduler-lifecycle-final3.json`；task `\\StockTool\\Acceptance\\Sprint26_2_31125e8051f8`；create/query/disable/enable/delete 全部成功，before/after `not_installed`，cleanup verified，未執行 StockTool，real data untouched。
- XML：`task-scheduler-lifecycle-final3.xml`，SHA-256 `FD13A2D9381EDE2CD984F4A08F87F4B8E784A99CD71B958B641DB0B99DDA0739`，1,091 bytes，UTF-8 無 BOM；DaysOfWeek 精確為 Monday、Tuesday、Wednesday、Thursday、Friday，無 Sunday；StartWhenAvailable、IgnoreNew、PT30M 均存在。
- production task read-only before/after 均 `not_installed`：`task-scheduler-before-final.json`、`task-scheduler-after-final.json`、`task-scheduler-diff-final.json`；未安裝 `\\StockTool\\DailyResearchBrief`。

## Guarded EXE and browser evidence

- online/offline/partial health guards：`final-health-online-final-1724015174`、`final-health-offline-final-772055862`、`final-health-partial-final-125943085` 均 passed，harness exit 0、zero diff、cleanup verified。
- final live browser session：`browser-live-settings-final7`。同一 session 的首頁與設定頁截圖、DOM、console、launch、guard、cleanup、capture manifest 均保存；`capture-session-manifest.json` SHA-256 `1D136B1DDEEC8437AEF6851DA73E838A570061DEF8580485BDECBAC4729A25C7`。首頁與排程兩張畫面已實際開啟檢查；active console error count 0；設定頁 DOM/畫面顯示「目前狀態：未安裝」、週一至週五 18:30（Asia/Taipei）及啟用／停用／立即執行／移除按鈕。
- `browser-result.json` 綁定 stable/payload/source/formal hashes、capture manifest、PNG/DOM/console/launch/guard hashes；current file SHA-256 `7EEF6352C468A1E6909EF4047D3CA1A361EDF1BE1F1F18D0B1ED415F6495293D`（16,936 bytes）；history index `browser-history-index.json` 保留全部 104 筆 guard（79 passed、25 failed），未刪除歷史失敗。Native 100%／125%／150% zoom：`deferred_to_formal_release`。

## Headless status contract

- guarded current-candidate `partial=10`、`skipped=20`、`already-running=30`、`failed=40` 均有 harness exit 0、cleanup verified、real-data zero diff 證據。
- **BLOCKER：current final candidate 的 `success=0` 尚未取得。** 多次使用全新／隔離資料根的 guarded manual run 在 provider refresh 後回傳 `partial`／exit 10；先前 success evidence 綁定不同候選或不同時間，不予移植。故 `browser-result.json` `overall_passed=false`，不得將此項寫成成功。

## Data and cleanup preservation

- `real-data-before-final.json`／`real-data-after-final.json`／`real-data-diff-final.json`：191 → 191，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`；root 以 `%LOCALAPPDATA%/StockTool` 表示，僅保存檔案 metadata/hash。
- 最終核對：StockTool／StockToolPayload process 0、8501/8502 listener 0、temporary task 0、production task absent。
- formal EXE 未修改；未簽章、未發布、未 promotion、未開始 Sprint 27。

## Limitations

1. 需在同一 final candidate、隔離資料與可重現 provider refresh 下補得 `success=0` headless evidence；在此之前整體狀態維持 BLOCKED。
2. Native browser zoom 仍 deferred，不以 viewport resize 或舊截圖冒充。
3. 本文件只提供 implementation evidence，等待獨立 CTO 判定。
