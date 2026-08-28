# Sprint 26.2.1.1.1.1 implementation evidence

Status: `IMPLEMENTATION EVIDENCE COMPLETE — PENDING INDEPENDENT CTO ACCEPTANCE`

本輪只修正嚴格 exit-code gate 與 cache-fallback durable evidence；未修改產品 source、正式 EXE、installer、版本號、production Task Scheduler 或真實使用者資料。未 commit、tag、push 或發布。

## Strict exit-code gate

- `scripts/evidence_launcher.py` 與 `scripts/browser_transport_harness.py` 已移除 `action=append` 的隱含 `[0]`；未指定時 accepted set 為 `[0]`，明確指定時只接受明確集合。
- `tests/test_evidence_launcher.py` targeted：`86 passed`，涵蓋未指定、10/20/30/40 單值、多值及 launcher→transport 精確轉送。
- `scripts/measure_performance.py` 仍只透過 `run_evidence`，沒有 direct candidate `Popen` fallback。

## Fresh offline cache-fallback

新隔離 fixture 的 pre-launch manifest：`artifacts/sprint26.2.1.1.1.1/pre-launch-fixture-manifest.json`。

- Cache CSV 為 UTF-8 無 BOM；metadata/CSV 實際計算的最後資料日：`2026-08-07`。
- 啟動前不存在：
  `data/daily_research/latest_evidence_chain_brief.json`、
  `data/daily_research/latest_evidence_chain_brief.html`、
  `data/daily_research/schedule/latest-scheduled-run.json`、
  `data/daily_research/schedule/runs/history.json`。
- 同一次 evidence_launcher 執行（offline、Yahoo endpoint blocked、10 秒視窗）觀察到：exit `0`、brief schema `2`/`success`、run record `success`/`0`、price identity `source_type=cache`、cache SHA 與 pre-launch 一致、reference IDs 全部解析、harness `0`、cleanup verified、191→191 zero diff。
- validation：`artifacts/sprint26.2.1.1.1.1/cache-fallback-final/cache-fallback-validation.json`。

## Durable outputs

同一次執行的 brief JSON/HTML、immutable run、latest/history、price identity、launch、transport、guard、cleanup 與 pre-launch manifest 已複製至 `artifacts/sprint26.2.1.1.1.1/cache-fallback-final/durable/`，由 `durable-output-manifest.json` 以相對路徑、size、SHA-256 綁定；不依賴 Temp 路徑。

舊的 `artifacts/sprint26.2.1.1.1` evidence 未刪除或覆寫，並在 `superseded-invalid-evidence.json` 標示為 `superseded_invalid_evidence`（舊 parser 的 implicit-zero 契約或 durable path 不可獨立重播）。

## Exit-code matrix

`artifacts/sprint26.2.1.1.1.1/matrix/matrix-result.json`：

| scenario | allowed set | observed | guard | zero diff |
|---|---:|---:|---|---|
| success | `[0]` | 0 | passed | true |
| partial | `[10]` | 10 | passed | true |
| skipped | `[20]` | 20 | passed | true |
| already-running | `[30]` | 30 | passed | true |
| failed | `[40]` | 40 | passed | true |

第一次使用仍有完整 cache 的 partial 嘗試觀察到 success/0，未被冒充為 partial；該 guard 保留並標為 superseded，最新 partial 使用無 cache 隔離 fixture。

## Quality and security

- `cmd /c quality_gate.bat`：exit `0`；`1179 passed, 2 skipped, 2 warnings`；branch coverage `82.47%`（gate `78.5%`）；Black、Ruff、focused mypy、compile、privacy、release layout、regression baseline 全通過。
- targeted：`86 passed`。
- `pip check`：exit `0`，`pip-check.log` 為 UTF-8 無 BOM。
- official `pip-audit --format json`：exit `0`，98 dependencies、0 vulnerabilities；`pip-audit.json` 可直接 UTF-8 JSON parse。
- performance hard gate：`performance-result.json`，固定項目各 3 次，overall passed。
- source archive：`source-archive-verification.json`；missing/forbidden/content mismatch/duplicate 均為 `0`。
- 新 artifacts UTF-8/BOM/JSON/privacy scan：`privacy-scan.json`，58 files、parse errors `0`、BOM `0`、private/secret findings `0`。

## Hash binding

- stable：`1B21B6D582D65F9CC702D4C72E62A681D10E82B677EF4C17B5BC166E85A83F07`
- payload：`96B919A0DB5962E3F527E50528FC9D89B3392C68B47EE9A8F8CC1410B847027F`
- source ZIP：`FCB83CF2D190F03B2290C0E0E67138EEF8473AC4BBCF61FAB5E1FE48AC910369`
- formal EXE（未變更）：`4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`

Candidate/source binding：`artifacts/sprint26.2.1.1.1.1/candidate-hashes.json`；因本輪只改 scripts/tests，未重建產品 candidate，stable/payload 已重新核對。

## Cleanup and limitations

`cleanup-verification.json`：StockTool/StockToolPayload process `0`、8501/8502 listener `0`、temporary task `0`、production task absent；real-data before/after `191/191`，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。

Native Chrome 100%/125%/150% 仍為 `deferred_to_formal_release`，本輪沒有以 viewport resize 冒充。最終判定留待獨立 CTO 驗收。
