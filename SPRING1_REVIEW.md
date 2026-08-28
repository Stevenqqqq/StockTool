# Sprint 1 Review

審查日期：2026-07-10  
審查角色：Principal Engineer、Principal QA、Principal Product Manager  
審查依據：`PROJECT_WHITEPAPER.md`、`PRODUCT_VISION.md`、`PRODUCT_EXECUTION_PLAN.md` 與目前 Sprint 1 產物。  
審查限制：本次只做 Sprint Review，未修改任何程式、測試、設定或既有規劃文件。

## Executive Verdict

**結論：Request Changes。Sprint 1 功能性完成，但尚未達到 merge-ready。**

目前變更沒有破壞既有行為，測試、格式檢查、EXE 建置與基本 smoke test 均有正面證據；也沒有進入 Sprint 2 的 domain/provider 重構。但 Sprint 1 的核心交付不是「多一個測試」，而是形成下一階段可依賴的版本基線。現況仍缺三項 Execution Plan 明定的證據：

1. Golden test 沒有使用既有 sample data。
2. 沒有 6488 與 AAPL 的固定驗收紀錄。
3. Source archive 不完全對應最終 Sprint 1 文件狀態。

此外，目前環境沒有可用的 Git，因此只能以 archive + checksum 暫代版本控制，無法執行真正的 branch/tag/merge。這不代表程式有錯，但會阻擋 Sprint 2 entry gate。

## Findings

### High：沒有可執行的版本控制與 Merge 基線

**證據**

- `docs/architecture/contracts.md:69-75` 明確記錄目前無法使用 `git`。
- `PRODUCT_EXECUTION_PLAN.md:145` 要求建立版本控制基線。
- `PRODUCT_EXECUTION_PLAN.md:167` 要求 tag 或不可變備份。
- 目前只有 ZIP archive 與 SHA-256，沒有 branch、commit、tag 或可驗證的 merge target。

**影響**

- 無法真正執行或稽核 merge。
- Sprint 2 若發生回歸，只能整包還原，無法精確比較與 cherry-pick。
- 變更歷史、作者、決策與 baseline delta 無法由版本控制保留。

**必要修改**

在 Sprint 2 開始前恢復 Git，建立 Sprint 1 baseline commit/tag，並保存 remote 或等效離機備份。若仍無法使用 Git，必須指定另一套具版本、權限與歷史的 repository；單一本機 ZIP 不足以長期取代版本控制。

### Medium：Golden test 未使用 Execution Plan 指定的既有 sample data

**證據**

- `PRODUCT_EXECUTION_PLAN.md:159` 要求「既有 sample 股票研究輸出 golden test」。
- `tests/test_regression_baseline.py:18-73` 在測試內自行建構 indicators、fundamentals 與 prices。
- 該測試沒有讀取 `data/sample/`、`sample_tw_*`、`load_csv()` 或 `load_excel()`。

**影響**

- 測試能保護 scoring、backtest 與 HTML report 的一條合成路徑，但不能偵測 sample CSV 欄位、內容、loader、cleaner 或實際範例研究流程的改變。
- README 宣稱 sample research baseline 已被固定，但目前固定的是測試內的人工 DataFrame。

**必要修改**

補一個從版本化 `data/sample/` 檔案出發的 deterministic golden test，至少經過 loader、cleaner、indicator/scoring 與 report 的既有公開介面。不得連線，不得使用會隨日期變動的資料。

### Medium：缺少 6488 與 AAPL 固定驗收紀錄

**證據**

- `PRODUCT_EXECUTION_PLAN.md:166` 明確要求對 2330、6488、AAPL 建立固定驗收紀錄。
- `tests/test_regression_baseline.py:25,48,66,84,92,97` 只使用 2330。
- Sprint 1 fixture、contract 與 acceptance evidence 中沒有 6488 或 AAPL。
- EXE smoke test只證明 localhost 回應 HTTP 200，沒有證明三個市場代號的固定研究流程。

**影響**

- Sprint 1 沒有形成 TWSE、TPEx、US 三市場的可重現驗收基線。
- Sprint 2 修改 Symbol/Market contract 時，缺少計畫原本要求的三市場比較依據。

**必要修改**

使用 recorded fixtures 或固定 sample data，建立 2330/TWSE、6488/TPEx、AAPL/US 三份離線驗收紀錄。驗收至少固定輸入代號、市場、實際 query symbol、資料來源類型、可用欄位與結果狀態；不要把即時線上價格固定進 golden file。

### Medium：Source archive 與最終 Sprint 1 文件不一致

**證據**

- `docs/architecture/contracts.md:82-85` 與 `docs/release/acceptance-v1.1.md:21-23` 記錄 source archive 及其 SHA-256。
- Archive hash 本身與文件紀錄一致。
- 直接比較 archive 內容後，`README.md`、`pyproject.toml`、baseline test、fixture 與 `config.py` 和目前工作區一致。
- 但 archive 內的 `docs/architecture/contracts.md` 與 `docs/release/acceptance-v1.1.md` 不是目前最終版本；兩份文件是在 archive 建立後補上驗證紀錄。

**影響**

- Archive 可以還原核心程式與測試，但不能精確還原 review 前宣稱的最終 Sprint 1 狀態。
- 「不可變 baseline」與其驗收證據存在時間順序落差。

**必要修改**

完成所有 Sprint 1 文件後重新建立 final source archive，重新產生 SHA-256，驗證還原結果與最終工作區一致。恢復 Git 後，應以 tag/commit 作為主基線，ZIP 僅作離線備份。

### Low：Coverage 只有紀錄，尚未形成自動防退步 Gate

**證據**

- 現行 coverage 為 70%。
- `pyproject.toml:33-39` 啟用 branch coverage 與顯示設定，但沒有 `fail_under`。
- `docs/release/acceptance-v1.1.md:13` 只記錄 coverage baseline。

**影響**

後續 Sprint 即使 coverage 下降，pytest-cov 仍可能回傳成功。這和「基線護欄」的產品目的仍有落差。

**建議**

在修正 Sprint 1 時把現有精確 coverage 記錄為最低門檻，或先採保守整數門檻 70%，之後逐 Sprint 只升不降。這是 merge 前建議修正；若暫不自動化，至少要在 Sprint 2 checklist 設為人工必驗 gate。

### Low：Feature flags 是宣告，不是目前可操作的切換機制

**證據**

- `src/stock_tool/config.py:12-14` 明確說明 Sprint 1 沒有 runtime consumer。
- `FeatureFlags` 目前只被 baseline test 使用。

**判定**

這是刻意的 scope control，不是缺陷。Sprint 1 沒有新 UI 或服務需要 rollback，因此不應為了讓 flag「看起來有用」而提前修改 dashboard。文件必須持續使用「feature-flag declaration」，不能宣稱已有可操作 runtime migration switch。

### Medium（既有債務）：目前 EXE 不是乾淨公開發行包

**證據**

- `docs/release/acceptance-v1.1.md:30-36` 已揭露限制。
- `release/StockTool/data/processed` 與 `release/StockTool/data/cache` 仍存在。
- `PRODUCT_EXECUTION_PLAN.md` 將乾淨發行與完整 EXE release hardening 排在後續 Sprint。

**判定**

這是已揭露的既有 release debt，不屬於 Sprint 1 必修，因此不因它單獨退回 Sprint 1。但它會阻擋 v1.1 對外發布。在完成資料隔離前，現有 EXE 只能視為本機驗證 artifact。

## 1. Sprint 1 是否真正完成

**判定：部分完成，工程產物已完成，Sprint Gate 尚未完成。**

已完成：

- 新增 baseline fixture 與跨 scoring/backtest/report 的回歸測試。
- 新增明確且不影響 runtime 的 migration posture declaration。
- 新增 contract、acceptance checklist、README baseline 說明與 coverage 設定。
- 完整 pytest 通過。
- 新增 Python 檔通過 Ruff 與 Black。
- EXE 建置成功，localhost 回應 HTTP 200，reports 可寫入，README 一致。
- Source archive 可還原，且排除 `.env`、`.venv`、release、cache、processed、reports 與 logs。

未完成：

- sample-data-driven golden test。
- 6488 與 AAPL 固定驗收紀錄。
- 精確對應最終 Sprint 狀態的 source baseline。
- 可執行的版本控制 merge/tag。

## 2. 是否符合 Execution Plan

| Execution Plan 要求 | 狀態 | Review |
|---|---|---|
| 凍結目前公開行為 | 部分符合 | scoring/backtest/report 有一條合成 baseline |
| 版本控制基線 | 不符合 | 只有本機 archive，Git 不可用 |
| Golden fixtures | 部分符合 | 有 JSON fixture，但沒有使用既有 sample data |
| Feature flag | 符合本 Sprint 邊界 | 有 declaration，刻意沒有 runtime consumer |
| Acceptance checklist | 符合 | 文件存在且清楚區分 Sprint 1 與 v1.1 |
| 完整 pytest 維持通過 | 符合 | 獨立重跑結果：180 passed in 8.03s |
| 2330、6488、AAPL 固定驗收 | 不符合 | 目前只有 2330 |
| tag 或不可變備份 | 部分符合 | 有 archive + hash，但 archive 文件不是最終狀態 |
| 不改核心行為 | 符合 | 未修改核心計算、dashboard、provider 或 storage |

總體符合度：**約 70%，但缺少的項目正是 Sprint 1 作為後續遷移基線的核心證據，因此不能只按檔案數量判定完成。**

## 3. Scope Creep

**產品與架構 scope creep：沒有。**

未發現 Sprint 2 的 `Symbol`、`Market`、`ProviderResult`、`QualityReport`、provider refactor 或 dashboard migration。也沒有新增使用者功能、策略、指標、AI 或資料來源。

**驗證範圍擴張：有，但可接受。**

Sprint 1 額外執行 EXE rebuild、HTTP smoke test、reports write test 與 source archive restore。這些活動在 Roadmap 中部分屬於 Sprint 6，但使用者明確要求驗證 EXE 與 README；它們沒有修改核心程式，並提高了 Sprint 1 證據品質，因此不視為有害 scope creep。

## 4. Technical Debt

### Sprint 1 新增或留下的債務

1. 本機 archive 暫代 Git，無法提供真正版本歷史與 merge 能力。
2. Baseline test 內重複建立 synthetic DataFrames，沒有覆蓋 sample import journey。
3. 三市場 acceptance matrix 尚未建立。
4. Coverage baseline 尚未自動阻止下降。
5. Feature flags 尚未具 runtime consumer；這是刻意延期，不應在 Sprint 1 補接。
6. Final documentation 與 archive 內容有一個小版本差。

### 既有但未因 Sprint 1 惡化的債務

1. EXE release 仍包含 processed/cache。
2. Dashboard 與 concepts 大檔案仍未重構。
3. Provider contract、provenance、migration 與 point-in-time 尚未完成。
4. 整體 coverage 70%，距最終目標 80% 仍有差距。

## 5. Definition of Done 是否達成

### Sprint DoD

| DoD | 狀態 | 證據 |
|---|---|---|
| Acceptance tests 通過 | 部分 | 現有 baseline test 通過，但計畫要求的兩檔與 sample journey 缺少 |
| 完整 pytest 通過 | 達成 | 180 passed in 8.03s |
| 格式與靜態檢查符合 gate | 達成於新增 Python 檔 | Ruff/Black 通過；尚無全專案 CI gate |
| 手動驗收有紀錄 | 部分 | EXE smoke 有紀錄；三市場固定驗收不完整 |
| Rollback 演練成功 | 部分 | archive 可還原，但不是最終文件狀態 |
| 文件與已知限制同步 | 達成 | contracts、acceptance、README 與 EXE 限制已記錄 |
| 無未揭露 High issue | 達成 | Git 與 release-data 限制已有揭露 |

Sprint DoD 判定：**未完全達成。**

### Version DoD

v1.1 需要 Sprints 1–6，目前不適用。`docs/release/acceptance-v1.1.md` 正確地把 Product Acceptance 與 Windows Acceptance 保持未勾選，沒有假裝 v1.1 已完成。

### Product DoD

尚未達成，且本來就不應由 Sprint 1 達成。Research Workspace、資料 provenance、三市場完整主流程與乾淨 Windows 發行仍在後續 Sprint。

## 6. 是否應退回修改

**應退回一次小型 Sprint 1 closure patch，不應開始 Sprint 2。**

必修項目：

1. 恢復 Git 或等效正式版本控制，建立 baseline commit/tag。
2. 補 sample-data-driven golden test。
3. 補 2330、6488、AAPL 三市場固定離線驗收紀錄。
4. 所有文件完成後重新建立 final source archive 並更新 checksum。

建議同批完成：

5. 設定 coverage 不得低於 Sprint 1 baseline 的自動或明確人工 gate。

不應在 closure patch 做：

1. 不接入新的 runtime feature flag。
2. 不建立 Sprint 2 domain/provider models。
3. 不拆 dashboard。
4. 不修 release data separation；保持已知限制，依 Roadmap 處理。
5. 不增加股票分析功能。

## 7. Merge Decision

**目前決定：Request Changes，暫不 Merge。**

理由不是核心程式失敗，而是 Sprint 1 的目的就是提供下一階段可信 baseline；目前 baseline 在 sample journey、三市場 acceptance、最終 archive 與版本控制四方面仍不完整。

完成四項必修、重跑完整 pytest、確認 archive 與最終工作區一致，並建立可稽核 commit/tag 後，可轉為 **Approve**。EXE 夾帶 processed/cache 不阻擋 Sprint 1 code merge，但會繼續阻擋 v1.1 public release。

## Sprint 2 建議

### Sprint 2 Entry Gate

Sprint 2 不應開始，直到：

1. Sprint 1 closure patch 通過本文件四項必修。
2. Git baseline tag 或等效版本控制基線可用。
3. `test_regression_baseline.py`、sample golden 與三市場 acceptance 全部通過。
4. Full pytest 通過且 coverage 不低於 Sprint 1 baseline。
5. 沒有修改 baseline fixture 的未核准差異。

### Sprint 2 執行邊界

Sprint 2 只處理統一 Domain 與 Provider contracts：

- `Symbol`
- `Market`
- `ProviderResult`
- `DataSourceMetadata`
- `QualityReport`
- missing-data representation

不要在 Sprint 2 同時搬 UI、建立 ingestion migrations、改 Research Workspace 或重寫 provider orchestration；那些分別屬於 Sprint 3–5。

### Sprint 2 測試優先順序

1. 先寫 TWSE、TPEx、US symbol contract tests。
2. 再寫 provider success、empty、partial、schema drift 與 fallback contracts。
3. 驗證 QualityReport 不修改原始 DataFrame。
4. 驗證 missing、unknown、not-applicable 可穩定序列化。
5. 用 adapter equivalence tests 證明新 contract 和既有公開結果一致。
6. 每組變更後執行 baseline tests；完整 pytest 與 coverage 作 Sprint exit gate。

### Sprint 2 Rollback 原則

新 contract 先放在 adapter 後方，舊資料形狀保留到下游遷移完成。若任何 dashboard、report、backtest 或 CLI regression 出現，切回 legacy adapter，而不是修改 baseline fixture 來讓測試通過。

## Final Review Statement

Sprint 1 的方向正確、變更克制、核心系統保持穩定，且測試與 EXE 證據比 Sprint 前更完整。它目前欠缺的是「基線閉環」，不是額外功能。完成一個小型 closure patch 後即可批准；在此之前開始 Sprint 2，會違反 Execution Plan 自己設定的 entry gate。
