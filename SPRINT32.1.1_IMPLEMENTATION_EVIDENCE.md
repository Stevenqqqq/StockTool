# Sprint 32.1.1 Implementation Evidence

> 本文件只記錄實作者證據；不代表 CTO/Sol 獨立驗收、正式發布或版本核准。

## 範圍與修改

- `HeadlessDailyResearchRunner` 在進入鎖定執行前建立 run-level stage accumulator。
- 六個階段固定依序輸出：`target_refresh`、`market_refresh`、`brief`、`change`、
  `prediction_registration`、`notification`。已完成階段保留；例外階段為
  `failure`；未執行階段為 `skipped`。
- Home、scheduled、headless 共用同一 runner 與同一市場 refresh snapshot／fingerprint；
  每次 run 的 TWSE/TPEX refresh 各一次，下游不再重新 refresh 或取另一份快取。
- 僅在明確 `STOCK_TOOL_EVIDENCE_MODE=sprint32.1.1` 且資料根在 Temp 隔離根時，才使用
  official-shaped deterministic fixture；production 預設不啟用 fixture。
- 首頁將工程 provider 訊息轉成簡短繁中下一步，詳細診斷仍保留在 manifest／log。

## Targeted 與完整品質

Targeted 命令：

```text
.venv\Scripts\python.exe -m pytest tests/test_daily_research_scheduler.py tests/test_daily_research_runner.py tests/test_daily_research_changes.py tests/test_daily_home.py tests/test_market_monitor.py tests/test_launcher.py -q
```

- 153 tests collected，exit code 0；原始輸出：`artifacts/sprint32.1.1/targeted-tests.log`
- 結果摘要：`artifacts/sprint32.1.1/targeted-tests-result.json`
- 覆蓋 stage exception、target／market／brief／change／snapshot／manifest fault、通知
  disabled/unavailable/sent/failed/duplicate、Prediction Lab fresh/duplicate/stale/
  partial/unavailable/date mismatch、同 snapshot 傳遞、refresh 次數、manual/scheduled/
  headless parity、idempotency 與 no-target。

完整品質門命令：

```text
.venv\Scripts\python.exe -m stock_tool.quality_gate
```

- exit code 0；`1446 passed, 2 skipped, 2 warnings`
- branch coverage：82.71%
- Black、Ruff、focused mypy、compileall、privacy、release layout、regression baseline：
  全部通過；privacy violations=0
- 原始 log：`artifacts/sprint32.1.1/quality-gate.log`
- `pip check` exit 0：`artifacts/sprint32.1.1/pip-check.log`
- official `pip-audit` exit 0、known vulnerabilities=0，UTF-8 JSON：
  `artifacts/sprint32.1.1/pip-audit.json`（stderr 分離於 `pip-audit.stderr.log`）

## Candidate、source 與正式檔案

本輪使用 build6 stable/payload；roadmap 文字在建置後補入，因此保留舊 source ZIP，另建
目前 source snapshot 的 final ZIP，沒有覆寫舊 source 證據：

| artifact | size | SHA-256 |
|---|---:|---|
| `release/staging-sprint32.1.1-build6/StockTool/StockTool.exe` | 7,111,438 | `CB8AAE81760155D82CA616D2645B8590B42963A67D20A1CA28FED5FB077EFB93` |
| `release/staging-sprint32.1.1-build6/StockTool/versions/1.3.0/StockToolPayload.exe` | 24,054,620 | `FC00308FF26D5E9E598AD7D2F7D668091BFDB50E472B6B9C28ED94B8A210FA65` |
| `release/staging-sprint32.1.1-build6-source-final.zip` | 2,731,710 | `70DD05CD4FC2005E5D6A4ACD370995F1F36F48D79F9223AC672A0C160A454920` |
| `release/StockTool/StockTool.exe`（formal） | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

Source archive verification：`artifacts/sprint32.1.1/source-archive-verification.json`，
367 entries，missing/forbidden/content mismatch/duplicate 全為 0。
候選綁定：`artifacts/sprint32.1.1/candidate-hash-binding.json`。

## Headless evidence

所有候選啟動均經 `scripts/evidence_launcher.py` 並使用全新隔離 Temp data root：

- success：`artifacts/sprint32.1.1/headless-success-build6-preloaded-5fd97f42e8094b989e41bb4fcc817868/`
  - exit 0、run status `success`、六階段全為 success、Prediction Lab `created_count=12`
- partial：`artifacts/sprint32.1.1/headless-partial-build6-153fbc16fb8b40f0a59700cc6df0b704/`
  - exit 10、run status `partial`、`success/partial/partial/skipped/skipped/skipped`
- no-target：`artifacts/sprint32.1.1/headless-no-target-build6-ddcacd75584c41e9a6ec75ac0ce5a204/`
  - exit 20、run status `skipped_no_targets`、六階段全為 skipped

三個 journey 的 harness exit 均為 0，guard passed、cleanup verified，且無 candidate
process/listener 殘留。歷史 build5／失敗 evidence 保留，未被本輪引用。

## Browser success evidence

同一 final candidate/session：

- `artifacts/sprint32.1.1/browser-success-build6-live2/`
- session：`sprint32.1.1-browser-build6-live2`
- launch：2026-08-24T15:03:29.063225Z；health ready：2026-08-24T15:03:32.088389Z
- capture manifest SHA-256：`2AF9E645CF529897901687660D27979602F5BDD161B441F6BEEF1E24D6BEDCD2`，size 3,340
- PNG：`home.png` SHA `5BF28632F872E93156E1E537CAABCB62453B8B38170846F4BAC6A825E58B43D4`；
  `success-stages.png` SHA `4113B4365068B8758A63E15974A267BF4D0DA09ADB4DE47085B1EB2934979362`
- DOM／console／launch／guard／cleanup 均由同一 session 產生並 hash-bound；active console
  errors=0、horizontal overflow=false。
- UI 顯示六階段完成及 Prediction Lab 今日登錄／累積樣本 12；`browser-result.json`
  `overall_passed=true`。
- 原生 Chrome 100%／125%／150%：`deferred_to_formal_release`，未以 viewport resize 冒充。

Browser 索引：`artifacts/sprint32.1.1/browser-result.json`。

## 資料與收尾

- `real-data-before.json`／`real-data-after.json`／`real-data-current.json`／
  `real-data-diff.json`：added=[]、removed=[]、changed=[]、zero_diff=true。
- formal、已安裝 v1.3.0 與桌面捷徑 preservation diff：zero diff。
- StockTool／StockToolPayload process=0、8501/8502 listener=0；正式排程查詢為不存在，
  沒有建立或修改 production task。
- artifact index：`artifact-hash-index.json` entry_count=340，existing verifier
  passed，missing/extra/mismatch/errors 全為 0。
- evidence index：`evidence-hash-index.json` entry_count=338；兩者 sidecar 均以 raw
  bytes 驗證一致，未做 CRLF/BOM 正規化。
- `artifacts/sprint32.1.1/final-verification.json` 彙整本輪 exact hash、時間窗、fixture、
  stage matrix、品質與 cleanup 結果。

## 限制與狀態

這是 implementation evidence，尚待 CTO/Sol 獨立驗收；沒有發布、簽章、版本提升、正式
排程啟用或正式 EXE 覆寫。原生瀏覽器縮放仍是 deferred，deterministic fixture 僅限隔離
evidence mode，不代表 production provider 線上可用性。
