# Sprint 27.1 implementation evidence

狀態：implementation evidence ready for independent CTO review；本文件不代表 CTO acceptance、release approval 或正式通知啟用。

## 範圍與修正

- 將每日研究通知改為 claim-first exactly-once 契約：`claim-*.json` 先以 atomic write/fsync 發布，claim 寫入失敗時不呼叫 notifier；通知完成後才寫 immutable `outcome-*.json`。claim 是去重權威，history 只是可由 immutable records 重建的 projection。
- 對 schema version、ledger/run/fingerprint/claim identity、檔名、含時區 ISO-8601 `created_at`、status 與重複 immutable records 做 fail-closed 驗證；reason 只保存遮罩後文字。
- Windows adapter 先做唯讀 packaged identity capability probe；沒有既有 identity 時回報 unavailable，不建立 AppUserModelID、不改 Registry/Start Menu/installer。Settings 顯示 capability，站內收件匣仍可用。
- 變更檔案：`src/stock_tool/application/daily_research_inbox.py`、`tests/test_daily_research_inbox.py`、`src/stock_tool/dashboard/pages/settings_workspace.py`、`PRODUCT_EXECUTION_PLAN.md`。Sprint 27 原有工作區變更保持未提交。

## 測試與品質

- Sprint 27.1 targeted：`tests/test_daily_research_inbox.py` 29、`tests/test_daily_research_scheduler.py` 40、`tests/test_daily_schedule_ui.py` 2、`tests/test_daily_home.py` 11；共 82 passed，命令與輸出：`artifacts/sprint27.1/targeted-tests.log`，exit `0`。
- 完整 quality gate：`artifacts/sprint27.1/quality-gate.log`，`1209 passed, 2 skipped, 2 warnings`，exit `0`；branch coverage `82.47%`（達到 Sprint 26.2 baseline 82.47%）。
- Black、Ruff、focused mypy、compileall、release layout、regression baseline、privacy gate 均由 quality gate 通過；`artifacts/sprint27.1/quality-gate.exit` 為 `0`。
- pip check exit `0`：`artifacts/sprint27.1/pip-check.log`。官方 `.venv` pip-audit exit `0`、列出套件無已知漏洞：`artifacts/sprint27.1/pip-audit.json`；本機專案套件因不在 PyPI 而標示 scanner 的 `skip_reason`，不是 ignore/allowlist，保留為限制。
- 性能 gate：`artifacts/sprint27.1/performance-result.json`，五項固定資料三次測量均通過（indicators/scoring、Excel、cached workflow、allocation/risk、candidate health ready；health max 約 3.788 秒）。
- UTF-8/JSON/JSONL/log/CSV/sha256 掃描：`artifacts/sprint27.1/encoding-scan.json`，144 files、101 JSON/JSONL，BOM/parse issues `0`。

## Candidate 與來源封存

- stable：`release/staging-sprint27.1/StockTool/StockTool.exe`，SHA-256 `5FF47E09036FBC8672D33854D345DA703C014A206A7712E22EEE89F9BB290394`，size `7,109,836`。
- payload：`release/staging-sprint27.1/StockTool/versions/1.2.2/StockToolPayload.exe`，SHA-256 `F5BB6017651DDC1F9550AAEDEC1EA7467AA7CCA663A53D3A77D5A33829D67D9A`，size `23,910,403`。
- source ZIP：`artifacts/sprint27.1/sprint27.1-source.zip`，SHA-256 `7C5089B29CFDB8E22EFAD1F13E6E8F511A1C5AC8DE1B056721365E8998994CB3`，size `2,586,350`；`source-archive-verification.json` 的 missing/forbidden/content mismatch/duplicate 全為 `0`。
- formal EXE：`release/StockTool/StockTool.exe`，SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`，前後相同。
- 完整重要證據 hash/size 索引：`artifacts/sprint27.1/evidence-hashes.json`（SHA-256 `BCC0D1CBA19E5C4DE209834C31673F16E710924550FDE556DA0A8CF4BC3B7DB8`）。
- staging build 產物已完成並通過上述 hash/size/版本與 release-layout 驗證；原始 `build_exe.bat` 呼叫在桌面工具執行時間上限內回報 timeout，未留下建置程序，故將「wrapper exit code 的重播」列為獨立驗收限制，而非以 timeout 冒充成功。

## Browser / EXE evidence

- 最終候選 session：`artifacts/sprint27.1/browser-final2`，session `sprint27.1-browser-final2-20260809T155418`；home 收件匣 screenshot `home-inbox.png` SHA `42F6BD3554F53B50E57874BC154AB502EA221D530E0F78428F015BB8B76C1377`，Settings screenshot `settings-notification-visible.png` SHA `75F27D7E37F2CD37DCC48210D4DEC26BE273044D5B18D48BA3ACCB9711C62D64`。
- 同一 session 的 DOM/console/launch/guard/cleanup 與 capture timestamps 綁定於 `capture-session-manifest.json`（SHA `DFD492DD512183894D4446E53F05D3A39FDBC2648DC3801727F4E60CB9DE3554`）及 `browser-result.json`（SHA `13B1E865986DF3E2F4F0AA0C8DABEFD77D5E1DB2EE84C05A692FB583461D0293`）。active console error count `0`、`overall_passed=true`、guard status `passed`、harness exit `0`、cleanup verified、candidate process/listener `0`。
- Home semantic evidence 為真正 UTF-8 繁中：每日研究收件匣、成功/部分完成/失敗、cache/source、下一步及 JSON/HTML 按鈕；Settings 顯示每日研究通知、停用與 Windows capability unavailable。native Chrome 100/125/150% 維持 `deferred_to_formal_release`，沒有用 viewport resize 冒充。
- 歷史失敗 evidence 未刪除：`artifacts/sprint27.1/browser-history-index.json` 掃描 Sprint 26/26.1/26.1.1/26.1.1.1/26.1.1.1.1/27 guards，共 `162` 筆（passed `122`、failed `40`）；`superseded-evidence.json` 明確標記舊 Sprint 27 evidence superseded。

## Headless status matrix

所有候選 invocation 均經 `scripts/evidence_launcher.py`、offline transport 與全新隔離資料根；每列是嚴格 singleton allowed exit-code，不隱含加入 `0`。完整矩陣與 launch/transport/guard/cleanup hashes 位於 `artifacts/sprint27.1/headless-status-matrix.json`（SHA `403B611253A774AB441C73A23735BABB718D30E6EDE24ABB584FC209217F2B29`）。

| 情境 | candidate exit | observed status | guard / harness | real data |
|---|---:|---|---|---|
| success | 0 | success | passed / 0 | zero diff |
| partial | 10 | partial | passed / 0 | zero diff |
| skipped | 20 | skipped_no_targets | passed / 0 | zero diff |
| already-running | 30 | already_running | passed / 0 | zero diff |
| failed | 40 | invalid trigger | passed / 0 | zero diff |

success=0 的 durable cache-fallback evidence：`artifacts/sprint27.1/headless-success-cache8/durable/`。同一次執行證明 source_type=`cache`、schema v2 success brief、run record exit `0`、reference 可解析、transport 阻擋外部 provider、cache payload hash 綁定 pre-launch manifest、cleanup verified。

## 真實資料與清理

- `%LOCALAPPDATA%\\StockTool` read-only before/after/current：`191 → 191 → 191`，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`；`artifacts/sprint27.1/real-data-before.json`、`real-data-after.json`、`real-data-current.json`、`real-data-diff.json`、`real-data-current-diff.json`。
- 正式 `\\StockTool\\DailyResearchBrief` task 與 temporary acceptance task 均不存在；最後查詢未留下 task。StockTool/StockToolPayload process `0`，8501/8502 listener `0`。
- 未修改正式 EXE、正式 installer、正式排程、版本號、Portfolio、Watchlist、Research Library 或其他真實使用者資料；未 commit、tag、push 或啟用通知／正式排程。

## Known limitations / rollback

- Windows adapter 在目前環境沒有既有 packaged identity，因此 capability 為 unavailable；未發送 OS notification。站內收件匣與測試/注入路徑可用，正式通知需既有安裝身分。
- 原生 Chrome zoom 證據 deferred_to_formal_release。
- `build_exe.bat` wrapper 在桌面工具時間上限內 timeout，但產物已存在且完成獨立 hash、source archive、privacy、layout、EXE smoke 驗證；CTO 可要求以更長執行窗重播 wrapper。
- rollback：保留現有 Sprint 27 source/staging 與歷史 evidence；Sprint 27.1 source 未提交，移除本輪未提交 source 變更即可回到 Sprint 27 checkpoint，不觸碰 formal release 或真實資料。
