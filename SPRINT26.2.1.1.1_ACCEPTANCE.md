# Sprint 26.2.1.1.1 implementation evidence

本文件只記錄 implementation evidence，未宣稱 CTO acceptance、正式發布或 release approval。

## Scope and correction

本輪僅修正相同 final candidate 的 headless daily-research cache fallback 證據。初次兩次隔離 replay 均誠實回傳 partial=10，根因是沒有目前 brief 時未從上一個成功 loop snapshot 建立明確 research continuation，且 `persistent_state` 被分類成 partial。最小修正為：

- `src/stock_tool/application/daily_research_scheduler.py`：只從上一個成功 snapshot 的明確 `research_coverage` event 建立 continuation；不從價格推導或產生 synthetic brief。
- `src/stock_tool/application/daily_research_brief.py`：有效目前來源的 `persistent_state` 顯示 fresh；`data_repair`、stale/cache 與 resolved 的既有語意保留。
- 新增 `tests/test_daily_research_scheduler.py` 與 `tests/test_daily_research_brief.py` regression。

因 source 確實變更，已重新建立 `release/staging-sprint26.2.1.1.1` 與 source ZIP，並重跑完整 quality gate。

## Superseded provenance

既有檔案均保留：

- `artifacts/sprint26.2.1.1/headless-success-final2/`：標記 `superseded_invalid_provenance`；原執行的 `source_type` 是 online。
- `artifacts/sprint26.2.1.1/provider-replay/`：標記 `superseded_invalid_provenance`；provider-result 是事後 probe，不是同一次執行證據。
- `artifacts/sprint26.2.1.1.1/cache-fallback-20260809-01/`、`-02/`：保留為本輪 partial=10 failed guards，未改寫為 success。

索引：`artifacts/sprint26.2.1.1.1/browser-history-index.json`。遞迴索引共 117 筆 guard（passed 86、failed 31、invalid 0），其中 3 筆標為 `superseded_invalid_provenance`；歷史 failed evidence 未刪除或隱藏。

## Final candidate binding

`artifacts/sprint26.2.1.1.1/candidate-hashes.json` 與 `browser-result.json` 均重新核對實體檔：

| artifact | size | SHA-256 |
|---|---:|---|
| stable `release/staging-sprint26.2.1.1.1/StockTool/StockTool.exe` | 7,110,263 | `1B21B6D582D65F9CC702D4C72E62A681D10E82B677EF4C17B5BC166E85A83F07` |
| payload `.../versions/1.2.2/StockToolPayload.exe` | 23,884,248 | `96B919A0DB5962E3F527E50528FC9D89B3392C68B47EE9A8F8CC1410B847027F` |
| source ZIP `artifacts/sprint26.2.1.1.1/sprint26.2.1.1.1-source.zip` | 2,569,329 | `37AB7ACB8AC6C9A3EA418C0760C1446217BA0A5B8AF5AC410E06B14A86F6157A` |
| formal `release/StockTool/StockTool.exe` | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

Source archive verification：`missing_required_inputs=0`、`forbidden_entries=0`、`content_mismatches=0`、`duplicate_entries=0`，見 `source-archive-verification.json`。
Stable 與 payload FileVersion/ProductVersion 均為 `1.2.2`；final health smoke 以 stable entry readiness 3.7769s 通過。

## Same-run cache fallback success=0

Evidence root：`artifacts/sprint26.2.1.1.1/cache-fallback-final/`。

- 新 Temp root 的 `pre-launch-fixture-manifest.json` 在啟動前建立，共 8 個預載檔案；沒有本輪 latest brief、HTML、run record 或 history。
- cache CSV 為 UTF-8 無 BOM；來源標示為 previously validated local cache fixture，最後資料日期 `2026-08-08`，不是即時資料。
- launch mode=`offline`，duration=10 秒；transport 同次記錄 `query1.finance.yahoo.com` CONNECT blocked。
- 同次執行後 `price_identity.provenance.source_type=cache`，cache payload SHA 與 pre-launch manifest 相同。
- `latest_evidence_chain_brief.json` 啟動前不存在，生成時間與 mtime 均在 launch `2026-08-09T10:03:30.004436Z` 至 cleanup `2026-08-09T10:03:33.819836Z` 之間。
- brief schema_version=2、status=`success`、content fingerprint=`7ab18ccfd31f9a48aefa65c96523266a0223fd4c1a87ef0358372b8247f763da`；4 個 reference IDs 全部解析。
- immutable run record status=`success`、exit_code=0；latest/history 可重讀。
- guard status=`passed`、harness_exit_code=0、cleanup verified、candidate processes remaining=[]、listeners remaining=0。
- `cache-fallback-validation.json` 保存上述欄位與 evidence hashes；`browser-result.json` 的 `success=0` 僅指向此 guard。

## Exit-code matrix (same final candidate)

`artifacts/sprint26.2.1.1.1/browser-result.json` 綁定下列五種同候選結果，每項 guard/harness/cleanup/real-data 均通過：

| scenario | observed | evidence |
|---|---:|---|
| success | 0 | `cache-fallback-final/run/` |
| partial | 10 | `matrix/partial-10/` |
| skipped | 20 | `matrix/skipped-20/` |
| already-running | 30 | `matrix/already-running-30-final/` |
| failed | 40 | `matrix/failed-40-corrupt/` |

`overall_passed=true` 僅因五項 observed exit、hash、時間、guard 與 cleanup 條件全部成立。Native Chrome 100%/125%/150% 仍為 `deferred_to_formal_release`；本輪沒有用 viewport resize 冒充。

## Verification

實際命令與結果：

- targeted `pytest tests/test_daily_research_scheduler.py tests/test_daily_research_brief.py -q`：61 passed，exit 0，見 `targeted.log`。
- `cmd /c quality_gate.bat`：exit 0；full pytest 1172 passed、2 skipped、2 warnings；branch coverage 82.47%（gate 78.50%）。Black、Ruff、focused mypy、compile、privacy、release layout、regression baseline 全部通過，見 `quality-gate.log`。
- `pip check`：exit 0，見 `pip-check.log`。
- official `pip-audit --format=json`：exit 0、0 known vulnerabilities、JSON 可解析且無 BOM，見 `pip-audit.json`。
- performance hard gate：exit 0，5 項各 3 次；indicators max 0.0705s、Excel max 1.0487s、cached workflow max 0.0078s、allocation/risk max 0.0346s、EXE health max 3.7756s，見 `performance-result.json`。
- artifact UTF-8/privacy scan：本輪 65 個 JSON/JSONL/log/CSV/sha256，BOM=0、JSON parse errors=0、private absolute path/credential/token/API key hits=0。

## Data and cleanup

- guard before/after 均為 191 files，added=[]、removed=[]、changed=[]、`zero_diff=true`。
- 專用 `real-data-before.json`、`real-data-after.json`、`real-data-diff.json` 保存 191→191 zero diff；三個 run evidence 亦各自保存 zero diff。
- formal EXE SHA 維持 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。
- 收尾檢查 StockTool/StockToolPayload process=0、8501/8502 listener=0、temporary Task Scheduler=0；production task 未建立。
- 未修改、移動或覆寫真實使用者資料，未修改 formal EXE、installer 或發布狀態。

## Status

`IMPLEMENTATION EVIDENCE COMPLETE — PENDING INDEPENDENT CTO ACCEPTANCE`。

剩餘限制：原生 Chrome zoom 仍 deferred_to_formal_release；本輪 headless cache replay 使用明確標示的歷史 local cache fixture，不代表即時市場資料。
