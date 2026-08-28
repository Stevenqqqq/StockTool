# Sprint 30 修正：implementation evidence

本文件只記錄本次 correction 的實作證據，等待獨立驗收；不代表 CTO acceptance、發布或下一個 Sprint。

## 修正範圍

- `src/stock_tool/application/prediction_lab.py`
  - claim 與 private temp 改為 PID 加 invocation UUID，避免同一程序執行緒共用 claim。
  - 保留 O_EXCL claim 與不可覆寫 hard-link authority publish；winner bytes 不可被 loser 刪除或覆寫。
  - 新增固定次數、短窗口的 winner replay；final authority 尚未出現時 fail closed，禁止無限等待。
  - replay 讀回 immutable winner 後重新驗證 prediction/outcome identity。
- `tests/test_prediction_lab.py`
  - 強化 manual/scheduler 同程序雙執行緒競爭：兩邊均 success、相同 6 IDs、6 個 final records、index 完整、winner bytes 一致、無 orphan。
  - 新增 bounded partial-visibility/replay 測試。
  - 新增 staggered independent-process service competition 測試。

## RED → GREEN

修改前新增的同程序競爭測試重現 `unavailable/success`（PID-only claim collision、final path 尚未出現）。修正後：

- `pytest tests/test_prediction_lab.py tests/test_daily_research_scheduler.py -o addopts='' --disable-warnings -q`
  - exit `0`
  - `86 passed`
- manual 與 scheduler 結果均為 `success`；兩份結果各含同一組 6 個 prediction IDs；final records=6；index 含完整 6 IDs；winner JSON bytes 完全一致。
- bounded pending replay 在固定窗口後 fail closed；winner 出現後可重讀；staggered independent processes 均回傳 success，無 orphan claim/temp。

## 品質與安全驗證

- full pytest：`1364 passed, 2 skipped`
- coverage：`82.50%`（門檻 80% 通過）
- strict release privacy scan：exit `0`，`0 violations`
- Black、Ruff、focused mypy、compileall、release layout：全部通過

## r3 candidate / performance

本輪 source 修改後建立新的 `release/staging-sprint30-correction-r3`，未覆寫舊 r2 或正式 release。

| artifact | path | size | SHA-256 |
|---|---|---:|---|
| stable | `release/staging-sprint30-correction-r3/StockTool/StockTool.exe` | 7,108,703 | `A979B12F9F70948EBF96985D8B99A96E363D3FF76F18D9CC1078479924614719` |
| payload | `release/staging-sprint30-correction-r3/StockTool/versions/1.2.2/StockToolPayload.exe` | 24,019,506 | `CD9FF41F65BBCA74D517D36C7D9A9C0D499307467C89E03D572AF89E24A12FB3` |
| source ZIP | `release/staging-sprint30-correction-r3-source.zip` | 2,668,786 | `9EB7C8C9AF8463B0E1EDC4A674CC663D12359EA507DEF7F5634F32C1E002860A` |
| formal baseline | `release/StockTool/StockTool.exe` | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

`artifacts/sprint30-correction-r3/performance-canonical.json`：三次 cold health-ready `2.5097948s / 2.5302997s / 2.5338611s`，max `2.5338611s <= 5s`，overall `passed=true`。

## Browser / EXE evidence

- 隔離環境注入具備完整來源元資料的固定盤後 fixture（3 檔台股、TWSE official source、fresh 狀態、hash-bound snapshot）。
- 在同一候選瀏覽器 session（session ID: `evidence-s30-r3-correction-ee147dc2`）依序執行：
  1. **首頁載入**：擷取 `home.png`、`home.dom.txt`、`home.console.json`。
  2. **設定頁**：點擊切換至設定頁，驗證顯示「目前狀態：未安裝」與週一至週五 18:30，擷取 `settings.png`、`settings.dom.txt`、`settings.console.json`。
  3. **研究首頁／變化**：切換回首頁，擷取 `changes.png`、`changes.dom.txt`、`changes.console.json`。
  4. **產生今日簡報與 Prediction Lab 驗證**：點擊「產生今日研究簡報」，成功觸發每日簡報生成與 Prediction Lab 自動抽樣登錄。畫面明確顯示：
     - 標題：「預測評估實驗室（實驗）」
     - 狀態：「狀態：樣本累積中」
     - 樣本數：「今日已登錄樣本：6；累積樣本：6」
     - 分桶：「分桶：Top 2、Middle 2、Bottom 2」
     - 5日結果：「5 個交易日：pending 3、eligible 0、evaluated 0、unavailable 0」
     - 20日結果：「20 個交易日：pending 3、eligible 0、evaluated 0、unavailable 0」
     - 擷取 `brief.png`、`brief.dom.txt`、`brief.console.json`。
- `browser-result.json` 明確記錄：
  - `status: "passed"`
  - `overall_passed: true`
  - `brief_generated: true`
  - `active_console_error_count: 0`
  - `real_data_zero_diff: true`
- strict verifier（`scripts/verify_evidence_bundle.py`）：exit `0`，`passed=true, errors=[]`；checked captures 包含全部 16 項 descriptors，evidence index 含 26 項 entries。
- native Chrome 100%/125%/150% 仍保留為 `deferred_to_formal_release`，未以 viewport resize 冒充。

## 資料與清理

- `%LOCALAPPDATA%\StockTool` 只讀 before/after/current：`191 → 191`，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。
- formal EXE hash 保持上述正式基線；未修改 installer、正式排程、registry、Start Menu 或真實資料。
- 收尾檢查：StockTool / StockToolPayload process `0`；8501/8502 listener `0`；未殘留 production task。

## 未完成／限制

- 需 CTO 獨立驗收；本文件不宣稱 acceptance。
- 原生 Chrome zoom deferred（維持 `deferred_to_formal_release`）。
