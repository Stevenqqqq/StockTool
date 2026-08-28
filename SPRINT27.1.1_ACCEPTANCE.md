# Sprint 27.1.1 implementation evidence

狀態：`IMPLEMENTATION EVIDENCE READY FOR INDEPENDENT CTO REVIEW`。
本文件不是 CTO 驗收、正式發布或 release approval。

## 修正範圍

- `src/stock_tool/application/daily_research_inbox.py`
  - schema v2 outcome 強制非空 `claim_id`。
  - 以單一 claim/outcome graph validator 驗證檔名、schema、唯一性與
    `claim_id`／`run_id`／`brief_fingerprint` 的完整對應。
  - orphan、cross-link、遺失或損壞 claim、重複 claim/outcome 均 fail closed。
  - claim-only 狀態為 pending；claim 仍是跨重啟去重權威。
  - Windows 通知僅在既有 packaged identity 與 WinRT construction probe 都成功時
    才可用；probe 不會呼叫 `Show`。
- `tests/test_daily_research_inbox.py`
  - 覆蓋 graph 對抗情境、pending restart dedup、outcome/history fault、XML
    escape、probe success/failure/timeout 與實際 Windows PowerShell construction probe。

沒有修改正式 EXE、installer、Registry、Start Menu、AppUserModelID、production task、
真實 Portfolio／Watchlist 或真實使用者資料。

## 測試與品質

- 實際主要命令：
  - `.venv\\Scripts\\python.exe -m pytest -q tests\\test_daily_research_inbox.py tests\\test_daily_home.py tests\\test_daily_schedule_ui.py tests\\test_daily_research_scheduler.py`
  - `cmd /c quality_gate.bat`
  - `cmd /c build_exe.bat`（`STOCK_TOOL_STAGING_PARENT=release\\staging-sprint27.1.1`）
  - `.venv\\Scripts\\python.exe -m stock_tool.release_archive --root . --output release\\staging-sprint27.1.1-source.zip`
  - `.venv\\Scripts\\pip-audit.exe --format json --output artifacts\\sprint27.1.1\\pip-audit.json`
  - `.venv\\Scripts\\python.exe scripts\\measure_performance.py --output artifacts\\sprint27.1.1\\performance-result.json --stable-entry release\\staging-sprint27.1.1\\StockTool\\StockTool.exe`
- 上述命令均 exit 0。
- targeted：84 passed
  - `test_daily_research_inbox.py`、`test_daily_home.py`、
    `test_daily_schedule_ui.py`、`test_daily_research_scheduler.py`
- full pytest：1,215 passed、2 skipped。
- branch coverage：82.49%（高於 82.47% 基準）。
- `cmd /c quality_gate.bat`：exit 0；pytest、coverage、Black、Ruff、focused mypy、
  compile、privacy、release layout、regression baseline 全部通過。
- `pip check`：exit 0；`pip-audit --format json`：exit 0、零已知漏洞。
- performance hard gate：passed，見
  `artifacts/sprint27.1.1/performance-result.json`。
- source archive：required／forbidden／content mismatch／duplicate 均為 0，見
  `artifacts/sprint27.1.1/source-archive-verification.json`。

## Windows 通知能力證據

- 實際 PowerShell WinRT construction probe：exit 0、stdout
  `stocktool-winrt-probe-ok`、stderr 空、未呼叫 `Show`；見
  `artifacts/sprint27.1.1/windows-runtime-probe.json`。
- 本機沒有既有 StockTool packaged identity，因此 production capability 安全回報
  unavailable，未發送 OS notification，見
  `artifacts/sprint27.1.1/windows-notification-capability.json`。此為正式
  installer identity 階段的限制，不以 fake identity 或系統修改規避。

## 候選、瀏覽器與資料保全

| 成品 | SHA-256 | Size |
| --- | --- | ---: |
| staging stable | `7CCA09C7D16BC1721D83329358C730D3F9D7B8EF807A729FD4BAFAABC5A884B6` | 7,110,371 |
| staging payload | `D00C8A96415B7A3071208553418BA3CBBD5D1C311E4A7FC2A3608FDE17F9474B` | 23,911,710 |
| source ZIP | `B3CAA7C69EF842B491D4E27716B32A4D24E3405A97EFE3EE58C91FA8DD4C5FBF` | 2,588,024 |
| formal EXE（未修改） | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` | 24,145,141 |

- stable／payload FileVersion 與 ProductVersion 均為 1.2.2，見
  `artifacts/sprint27.1.1/version-resource.json`。
- 候選僅由 `scripts/evidence_launcher.py` 啟動，健康端點就緒 3.77 秒；guard
  `passed`、harness exit 0、cleanup verified、殘留 candidate process 與
  8501/8502 listener 均為 0。
- 同一 live candidate session 的首頁與設定頁 PNG、DOM、console、launch、guard、
  cleanup hash binding 見 `artifacts/sprint27.1.1/browser-result.json`。
  兩頁 active console errors 為 0；DOM 匯出保留原始檔案，但瀏覽器控制面的非 ASCII
  文字解碼限制已明記，PNG 已直接檢視。原生 Chrome 100%／125%／150% 維持
  `deferred_to_formal_release`，未使用 viewport resize 冒充。
- 真實資料 before／after：191 → 191，`added=[]`、`removed=[]`、`changed=[]`、
  `zero_diff=true`，見 `artifacts/sprint27.1.1/real-data-diff.json`。
- production task query 為 absent；本輪未建立 temporary 或 production task。最終
  StockTool／StockToolPayload processes 與 8501／8502 listeners 均為 0。
- `browser-history-index.json` 保留 224 筆歷史 guard（178 passed、46 failed）；沒有
  刪除或覆寫歷史失敗證據。

## 證據完整性與限制

- `evidence-hashes.json` 刻意不列入自身及 sidecar，避免自指；其 sidecar 與
  `evidence-hashes-validation.json` 驗證所有列入檔案一致。
- 本輪證據均為 UTF-8、無 BOM 且 JSON 可解析，見
  `artifacts/sprint27.1.1/utf8-validation.json`。
- 仍待獨立 CTO 驗收；Windows OS toast 的實際發送／點擊啟動需在具有效 packaged
  identity 的正式 installer 階段驗證。
## Sprint 27.1.1.1 correction evidence (current)

This section is the current implementation evidence for the three ledger corrections. The earlier Sprint 27.1.1 material above is preserved as historical evidence and is not rewritten.

### Scope and source changes

- `src/stock_tool/application/daily_research_inbox.py`: filesystem-exclusive claim creation (`O_CREAT|O_EXCL`), deterministic claim identity validation, outcome-to-claim graph validation, timestamp ordering, and newest-pending status.
- `tests/test_daily_research_inbox.py`: independent-store contention, filesystem exclusive-create, forged identity, malformed/incomplete claim, earlier outcome, mixed pending, restart de-duplication, and Windows runtime-probe regressions.
- No formal release, installer, production task, registry, Start Menu, or real-user data was modified.

### Focused and complete verification

- Focused ledger/UI tests: 56 passed (43 inbox, 11 home, 2 schedule UI).
- Adversarial ledger subset: 7 passed, including two independent services racing on one claim with `send_count == 1`.
- Full pytest: `1223 passed, 2 skipped, 2 warnings`.
- Branch coverage: `82.50%` (gate `>=82.49%`).
- `cmd /c quality_gate.bat`: exit `0`; targeted/full pytest, coverage, Black, Ruff, focused mypy, compile, privacy, release-layout and regression baseline all passed.
- `pip check`: exit `0`, no broken requirements.
- Official `.venv` `pip-audit --format json`: exit `0`, no known vulnerabilities; UTF-8 JSON at `artifacts/sprint27.1.1.1/pip-audit.json`.
- Performance hard gate: passed; canonical result at `artifacts/sprint27.1.1.1/performance-result.json`.
- `git diff --check`: exit `0`.

### Claim/outcome evidence

- `artifacts/sprint27.1.1.1/ledger-targeted-junit.xml` records the contention and graph tests.
- Exclusive create is the only claim authority; no `exists()+replace()` path is used for claims and no process-local lock is used.
- A partially written or invalid claim is rejected by the shared graph validator before notification.
- `claim_id` is recomputed from `(run_id, brief_fingerprint)` on every read; filename and outcome linkage are checked, and an outcome earlier than its claim is rejected.
- A newer unmatched claim reports `pending` even when older sent/failed/unavailable outcomes exist; completing the claim restores the newest outcome status.

### Candidate and formal hashes

The source change required a fresh candidate. Hash/size binding is at `artifacts/sprint27.1.1.1/candidate-hash-binding.json`.

| Artifact | SHA-256 | Size |
| --- | --- | ---: |
| staging stable `release/staging-sprint27.1.1.1/StockTool/StockTool.exe` | `37E19CFE0C9EF4C7EFD0A7551CEEAAB8D689712A45E8FC615CDB11CE122B5B63` | 7,110,596 |
| staging payload `.../versions/1.2.2/StockToolPayload.exe` | `0260D639BD655A4BD503B9554E5906BFABBBFCC53F9048C8F5F1809F31060D94` | 23,914,301 |
| source ZIP `release/staging-sprint27.1.1.1-source.zip` | `BBC73C5A8E28A3DCD42932DA98811B6656A92654A9D1F449BB669157FB7A1571` | 2,590,325 |
| formal `release/StockTool/StockTool.exe` (unchanged) | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` | 24,145,141 |

Source archive verification is at `artifacts/sprint27.1.1.1/source-archive-verification.json` with missing, forbidden, content-mismatch and duplicate counts all zero.

### Isolated candidate/browser evidence

- Candidate health smoke: `artifacts/sprint27.1.1.1/health-smoke/guard-result.json` status `passed`, harness exit `0`, cleanup verified, no remaining candidate process/listener, and real-data diff zero.
- Headless no-target smoke: `artifacts/sprint27.1.1.1/headless-smoke/guard-result.json` status `passed`, observed exit `20` (`skipped_no_targets`), expected set exactly `{20}`, cleanup verified.
- One invalid historical attempt is retained at `artifacts/sprint27.1.1.1/version-smoke/`: combined `--version` and daily-run arguments correctly failed closed with exit `1`; it is not used as passing evidence.
- Live browser session: `artifacts/sprint27.1.1.1/browser-session-20260811-0615/`. Home and notification-settings PNG/DOM/console captures were made while the candidate was healthy; active console errors `0`; guard status `passed`, harness exit `0`, cleanup verified, remaining processes/listeners empty. Machine-readable binding is `artifacts/sprint27.1.1.1/browser-result.json` (`overall_passed=true`).
- The new screenshots were visually inspected during the same live session. Native Chrome zoom remains `deferred_to_formal_release`; no viewport resize is claimed as zoom evidence.
- Windows Runtime construction probe: `artifacts/sprint27.1.1.1/winrt-probe.json`, exit `0`, stdout `stocktool-winrt-probe-ok`, stderr empty, `Show` not invoked. No packaged StockTool identity is present, so OS notification capability remains unavailable.

### Real-data and cleanup preservation

- `artifacts/sprint27.1.1.1/real-data-before.json`, `real-data-after.json`, and `real-data-diff.json`: `191 -> 191`, `added=[]`, `removed=[]`, `changed=[]`, `zero_diff=true`.
- Formal EXE hash is unchanged. Final checks found zero `StockTool`/`StockToolPayload` processes, zero listeners on 8501/8502, no production `\\StockTool\\DailyResearchBrief` task, and no temporary acceptance task.

This is implementation evidence only and remains pending independent CTO acceptance. No commit, tag, push, signing, publication, or Sprint 28 work was performed.

The retained preflight stderr at `artifacts/sprint27.1.1.1/browser-session/launcher.stderr.log` is legacy CP950 output from the intentionally failed guard attempt; it is explicitly excluded from current machine-evidence validation. All current JSON/log/text evidence is UTF-8 and parseable as recorded in `artifacts/sprint27.1.1.1/utf8-validation.json`.

Current browser capture hashes: home PNG `127D5823C01F75F2B86B56B8743BA74DE29E06582A8EAA4D90EFD4840302F082`; notification-settings PNG `0726F59AADA1E776A64D114B651D022237750D6AA2DE372C6C9B7D75E136E318`; capture-session-manifest `C9BBFB3972EA5C4E3C08DC7357B5CDF3E4C77B3E296692A01127D3197420F6B1`.
