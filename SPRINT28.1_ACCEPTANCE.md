# Sprint 28.1 implementation evidence

狀態：**implementation evidence ready for independent acceptance**。本文件不代表 CTO 驗收、正式發布或 Sprint 29 核准。

## 修正範圍

- 新增不可變、market-qualified 的 `DailyResearchChangeSet` 信任合約：所有 brief/change fingerprint 均為完整 64 碼 SHA-256；跨欄位 identity、current/previous fingerprint、狀態、reference closure、唯一排序與 `generated_at` 完整性均 fail-closed。
- Brief history 只在真正沒有歷史時建立 baseline；歷史檔損壞、身分衝突或 fingerprint 不符時保留上一份有效 change summary 並安全警告，不會偽造首次基準。
- Inbox/notification claim 加入 change fingerprint、狀態、priority 與 reference audit binding；同一 change fingerprint 即使 run 不同也不重複 claim。
- `scripts/verify_evidence_bundle.py` 改為唯讀 strict schema verifier：驗證 required captures、同一 session 時序、guard/cleanup、candidate 實體精確 size/SHA-256、UTF-8 無 BOM/CRLF、evidence index、Task Scheduler 及 real-data zero-diff。
- `PRODUCT_EXECUTION_PLAN.md` 已補入 Sprint 28.1 correction 範圍與待獨立驗收狀態。

## 測試與品質

- Sprint 28.1 adversarial targeted pytest：163 passed。
- 最終 `quality_gate.bat`：exit 0；full pytest **1270 passed, 2 skipped**；branch coverage **82.62%**（高於 82.51%）。
- Black、Ruff、focused mypy、compileall、project privacy scan、release layout、regression baseline：均通過。
- `pip check`：No broken requirements found。
- `pip-audit`：exit 0，No known vulnerabilities found；UTF-8 JSON：`artifacts/sprint28.1/pip-audit-final.json`。
- `git diff --check`：通過。

## 候選、封存與效能

| 成品 | 路徑 | 大小 | SHA-256 |
| --- | --- | ---: | --- |
| Stable candidate | `release/staging-sprint28.1/StockTool/StockTool.exe` | 7,110,207 | `7D08423428BDD222960CC7BD1E8E5864B31082721EDE24B6AB88A009868DE42B` |
| Payload candidate | `release/staging-sprint28.1/StockTool/versions/1.2.2/StockToolPayload.exe` | 23,940,439 | `DC6F656432D2850A38DD6549D15CF00BF566B4ABF11F465AA45A2E42433D863E` |
| Source ZIP | `release/staging-sprint28.1-source.zip` | 2,616,285 | `D701A421B87488814AF68FED380326769C13ACC83049625DFC8ED379C444B447` |
| Formal EXE（未修改） | `release/StockTool/StockTool.exe` | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

- Source archive 獨立驗證：missing required inputs、forbidden entries、content mismatches、duplicate entries 均為 0。
- Canonical performance（三次完整 cold runs）：indicators/scoring max 0.068s、Excel max 1.032s、cached workflow max 0.009s、allocation/risk max 0.037s、EXE health max 3.791s；全部在既定門檻內。
- `artifacts/sprint28.1/exe-smoke-online/`、`exe-smoke-offline/`、`exe-smoke-partial/`：皆經 `scripts/evidence_launcher.py`，guard passed、cleanup verified、real-data zero-diff。

## Browser 與證據完整性

- 最終有效 bundle：`artifacts/sprint28.1/evidence-bundle-final3c/`，session `sprint28.1-final3c-c6d8c1f3`。
- 同一候選存活期間擷取首頁、變化、每日簡報與設定頁的 screenshot、DOM、active console、launch、transport、cleanup；實際開啟檢查首頁與簡報畫面，均為有效 StockTool 畫面。
- `browser-result.json`：`status=passed`、`overall_passed=true`、active console errors 0。
- `guard-result.json`：`status=passed`、`harness_exit_code=0`、`cleanup_verified=true`、candidate processes `[]`、listeners 0、191→191 zero diff。
- `scripts/verify_evidence_bundle.py artifacts/sprint28.1/evidence-bundle-final3c --workspace-root .`：exit 0；capture manifest、browser result 與 evidence index 使用實體 raw bytes 精確雜湊及 size。
- `browser-evidence-history-index.json` 保留 `evidence-bundle`、`final`、`final2`、空的 guard-rejected `final3`、console-schema-invalid `final3b` 等歷史 evidence；未刪除或改寫 raw capture。

## 資料與治理

- 真實 `%LOCALAPPDATA%\StockTool`：final live guard before=191、after=191，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。
- 最終 cleanup：StockTool/StockToolPayload process 0；8501/8502 listener 0；正式 `\StockTool\DailyResearchBrief` task query 為 absent。
- 未修改 formal EXE、正式排程、installer、簽章、發布狀態或真實使用者資料；未 commit、tag、push 或開始 Sprint 29。

## 已知限制

- 隔離候選資料根沒有真實持股/自選股，因此 browser 簡報安全顯示 `partial` 與資料不足；此為預期的安全降級，不是成功內容偽造。
- 原生 Chrome 100%/125%/150% 縮放不以 viewport resize 冒充，維持後續正式驗收項目。
