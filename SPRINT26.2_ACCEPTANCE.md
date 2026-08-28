# Sprint 26.2 implementation evidence

狀態：implementation evidence complete — pending independent CTO acceptance。
本文件不代表 CTO 驗收、正式發布或 production task 啟用。

## Checkpoint

- branch：`main`
- Sprint 26 checkpoint commit：`87e3d51092c56469d23e7ef7d218126544bea77d`
- annotated tag：`sprint26-accepted-2026-08-09`
- checkpoint tag object：`8abbb584aad0aba5d0f3f41fc4b4880faf806904`
- checkpoint command：`git diff --check`，exit 0。
- checkpoint 僅納入 Sprint 26 已驗收 allowlist；未納入 `artifacts_sprint25_1_1_quality.log`、artifacts 或其他私有資料。
- Sprint 26.2 source 仍未 commit、未 push、未 tag。

## Sprint 26.2 implementation

- 新增 `src/stock_tool/application/daily_research_scheduler.py`：disabled-by-default schedule settings、Asia/Taipei 週一至週五 18:30、headless runner、schema-versioned atomic stores、bounded run history、stale-safe lock、idempotency、exit codes 0/10/20/30/40。
- 新增 `scripts/verify_sprint26_2_task.py`：只建立唯一 nonce 的 temporary Task Scheduler task，執行 create/query/disable/enable/delete，不執行 StockTool。
- `launcher.py` 新增 `--daily-research-run --trigger scheduled|manual`，不啟動 Streamlit。
- Settings 工作區加入每日研究排程狀態、plan、啟用/停用/立即執行/移除按鈕；所有改動均由明確使用者操作觸發。
- `scripts/evidence_launcher.py` 與 `scripts/browser_transport_harness.py` 保持候選啟動隔離與 real-data guard；final evidence 僅使用 final candidate。
- `PRODUCT_EXECUTION_PLAN.md` 已記錄 Sprint 26.2 scope、non-goals、rollback、temporary-task acceptance 與 deferred production activation/toast。

## Automated verification

Quality gate command：`cmd /c quality_gate.bat`，exit 0；完整輸出：`artifacts/sprint26.2/quality-gate-final.log`。

- targeted：68 tests，exit 0；`artifacts/sprint26.2/targeted-final.log`。
- full pytest：1145 passed、2 skipped、2 warnings。
- branch coverage：82.50%，gate 78.50%，通過。
- Black、Ruff、focused mypy、compileall、privacy scan、release layout、regression baseline：全部通過。
- pip check：exit 0，`artifacts/sprint26.2/pip-check.log`。
- official `.venv` pip-audit：exit 0、JSON 可解析、已知漏洞 0；唯一 skip_reason 是本機套件 `stock-analysis-tool` 不在 PyPI，未使用 ignore/skip 白名單。`artifacts/sprint26.2/pip-audit.json`。
- performance hard gate：`artifacts/sprint26.2/performance-result.json`；每項 3 次，indicators max 0.0743s、Excel max 1.0529s、cached research max 0.0070s、allocation/risk max 0.0358s、EXE health max 3.7934s，全部低於門檻。
- `git diff --check`：exit 0。

## Task Scheduler lifecycle

- temporary task：`\StockTool\Acceptance\Sprint26_2_27c578576d88`。
- `artifacts/sprint26.2/task-scheduler-lifecycle.json`：plan/create/query/disable/enable/delete 全部成功，task_executed=false，cleanup_verified=true，production_task_touched=false。
- before/after/diff：`task-scheduler-before.json`、`task-scheduler-after.json`、`task-scheduler-diff.json`；added/removed/changed 均為空，zero_diff=true。
- fixed production task `\StockTool\DailyResearchBrief`：未安裝；本輪沒有啟用正式排程。

## Final candidate and source archive

Final staging：`release/staging-sprint26.2-final`。

| artifact | SHA-256 | size |
|---|---|---:|
| stable `StockTool.exe` | `AA8230B8B06C97608057DF2E0CE11EA1FAAFE910782017332F8249FAA6E9CEA7` | 7,109,724 |
| payload `versions/1.2.2/StockToolPayload.exe` | `A6CA48618E31003056A00FBABE78A2E3A11C574635D88EBB2B80C36041EDB497` | 23,879,586 |
| source `artifacts/sprint26.2/sprint26.2-source.zip` | `355B01769899675A2A9A23FD7A1FA02F34BE2F7D87FD225E6C80B46A0ABF9C7B` | 2,563,851 |
| formal `release/StockTool/StockTool.exe` | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` | 24,145,141 |

`version-smoke.json` 確認 stable 與 payload 的 FileVersion/ProductVersion 均為 1.2.2。Source ZIP manifest 驗證：missing required inputs=0、forbidden=0、content mismatches=0、duplicates=0；`stable_launcher.py` 與 `StableLauncher.spec` 均為 required build inputs。Candidate binding：`candidate-hashes.json`、`source-archive-result.json`、`source-archive-final-verify.json`。

## Isolated EXE and browser evidence

所有 final candidate 啟動均經 `scripts/evidence_launcher.py`，使用新的 isolated `STOCK_TOOL_USER_DATA_DIR`；未直接啟動候選。

- health online：`final2-exe-online`，mode=online、health=true、guard passed、harness exit 0。
- health offline：`final2-exe-offline`，mode=offline、child-only proxy、health=true、guard passed、harness exit 0。
- health partial：`final2-exe-partial`，mode=partial、指定 endpoint block、health=true、guard passed、harness exit 0。
- headless success：`final2-exe-daily-success2`，`--daily-research-run --trigger manual`，exit 0、status=success。
- headless partial：`final2-exe-daily-partial`，exit 10、status=partial，上一成功 brief 不被覆寫。
- headless no-target：`final2-exe-daily-skipped`，exit 20、status=skipped_no_targets。
- browser live session：`browser-live-settings-final2`；同一候選 session 取得 `home.png`、`home.dom.txt`、`home.console.json`、`settings.png`、`settings.dom.txt`、`settings.console.json`。首頁顯示 StockTool、每日證據鏈入口；設定頁顯示每日研究排程契約。active console error count=0。
- live screenshot SHA-256：`home.png`=`127D5823C01F75F2B86B56B8743BA74DE29E06582A8EAA4D90EFD4840302F082`；`settings.png`=`E260ABA14B2A40BA7E1E5B038370E02365A80E8CD5F0D5D6FF6105BD514EE5AA`。
- machine-readable browser binding：`artifacts/sprint26.2/browser-result.json`（overall_passed=true，含 candidate/source/screenshot/DOM/console/guard hashes；SHA-256=`F60F99A232C629FCA7AF7CE70D6010AE9E06FC6755E61236C0D3D7B05695AADB`）。
- 原生 Chrome 100%/125%/150%：`deferred_to_formal_release`；未以 viewport resize 冒充。

## Data preservation and cleanup

- real-data baseline：191 files；`real-data-before.json` → `real-data-after.json`：added=[]、removed=[]、changed=[]、zero_diff=true；`real-data-diff.json`。
- `artifacts/sprint26.2/final-cleanup.json`：StockTool/StockToolPayload processes=0、8501/8502 listeners=0、production task absent、cleanup_verified=true。
- 正式 EXE SHA-256 維持指定 baseline；沒有讀寫、移動或覆寫 `%LOCALAPPDATA%\StockTool`。

## Known limitations / deferred

- Production Task Scheduler activation intentionally remains uninstalled and awaits accepted release/user action。
- Windows native toast/notification remains out of scope。
- Browser native zoom evidence is deferred to formal release verification。
- AI/provider unavailable paths use deterministic local fallback; no new provider or dependency was added。

以上為 implementation evidence，交由獨立 CTO 驗收；不宣稱正式發布或 release approval。
