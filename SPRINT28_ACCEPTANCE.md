# Sprint 28 implementation evidence

狀態：implementation evidence complete；等待獨立 CTO acceptance。本文件不是 CTO acceptance。

## Checkpoint

- Sprint 27 checkpoint commit：`3b5bce9dcd8a8c60613ab796497f536e7be64c54`
- Sprint 27 annotated tag：`sprint27-accepted`
- 本輪未建立 commit、tag、push 或 PR。
- `artifacts_sprint25_1_1_quality.log` 保持未追蹤且未納入 source archive。

## 實作範圍

- 新增 `DailyResearchChangeApplicationService`、schema-versioned `DailyResearchChangeSet`、reference-bound deterministic comparison 與 immutable change history。
- `DailyResearchBriefStore` 增加成功 brief 的 content-addressed history，JSON 為唯一權威；HTML 僅為可丟棄投影。
- Home 顯示「今天的重點變化」，並保留 priority、理由、目前／前次值、fingerprint、reference 與 AI boundary。
- Scheduler 與 Streamlit 研究簡報流程共用 brief history/change projection，失敗不覆蓋上一份成功 brief。
- 新增 `scripts/verify_evidence_bundle.py`，以 raw bytes、exact size/SHA-256、UTF-8、timestamp、guard/cleanup 與 session binding fail closed 驗證 evidence bundle。

## 測試與品質

- targeted（change、brief、scheduler、inbox、home、schedule UI、shell、evidence verifier）：通過。
- full pytest：`1254 passed, 2 skipped`。
- branch coverage：`82.52%`（門檻 82.51%）。
- `quality_gate.bat`：exit 0；targeted/full/coverage/Black/Ruff/focused mypy/compile/privacy/release layout/regression 全部通過。
- pip check：通過，無 broken requirements。
- pip-audit：exit 0，零已知漏洞；原始 UTF-8 JSON：`artifacts/sprint28/pip-audit.json`。
- focused mypy（新增 change/verifier/tests）：通過；compileall、Ruff、Black 通過。

## Candidate 與 source archive

- 目前最終候選 Stable：`release/staging-sprint28-final2/StockTool/StockTool.exe`，7,110,470 bytes，SHA-256 `A4C5215F8D68FFF29F40BB35B066058B54D863A68FDBCEF5BF356B2C995188B6`。
- 目前最終候選 Payload：`release/staging-sprint28-final2/StockTool/Payload/StockToolPayload.exe`，23,934,962 bytes，SHA-256 `173CF2D4810C3D0157990051721321D203689EB71A7CE2E26DAF2BDFEC5310D3`。
- 目前最終候選 Source ZIP：`release/staging-sprint28-final2-source.zip`，2,606,894 bytes，SHA-256 `E80AEA44002E3BD22E776F3E0A712EDD83F172A95E03134D77EFF48B1F7D9619`。
- `artifacts/sprint28/candidate-hash-binding-final2.json` 與實體檔案 exact size/SHA-256 一致；候選版本為 1.2.2。
- Formal EXE 未變：`release/StockTool/StockTool.exe`，SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。
- source archive：required、forbidden、content mismatch、duplicate 均為 0；最終候選獨立驗證詳見 `artifacts/sprint28/source-archive-verification-final2.json`。
- candidate binding：`artifacts/sprint28/candidate-hash-binding-final2.json`；舊 `staging-sprint28-final` 證據保留作歷史資料，不作目前候選引用。

## EXE、performance 與資料保全

- evidence launcher final2 offline smoke：`artifacts/sprint28/exe-smoke-final2/`；health ready，harness exit 0，cleanup verified，listener 0。
- performance canonical：`artifacts/sprint28/performance-canonical-final2.json`；indicators、Excel、cached workflow、portfolio risk 與 EXE health 均通過，EXE readiness 三次最大值低於 5 秒。
- 真實資料：`real-data-before.json`／`real-data-after.json`／`real-data-diff.json`，191→191，added=[]、removed=[]、changed=[]、zero_diff=true。
- 正式 Task Scheduler `\StockTool\DailyResearchBrief` 查詢為不存在；未建立或修改正式 task。
- 收尾確認 StockTool／StockToolPayload、8501/8502 listener 均為 0。

## Browser evidence

- 歷史 `staging-sprint28-final` 的 `browser-final/`、`browser-final-success/`、`browser-final-inbox/` 證據均保留；因候選不同，僅作歷史 evidence，不移植其 hash。
- 目前候選 live session：`artifacts/sprint28/browser-final2-settings5/`，session `sprint28-final2-settings5`；capture-session-manifest SHA-256 `77EDA0618F6C181E9B7EA889FF53FA20D288B0AE31C8F3E55B8695881432BD56`。
- 同一 session 直接取得 `home.png`（首頁）、`changes.png`（今日重點變化與收件匣）、`brief.png`（收件匣／研究入口）及捲動後 `settings.png`（每日研究排程）。DOM 分別包含每日證據鏈簡報、今天的重點變化、每日研究收件匣，以及「目前狀態：未安裝」「週一至週五 18:30（Asia/Taipei）」與操作按鈕。
- `artifacts/sprint28/browser-final2-settings5/browser-result.json`、capture manifest、launch、guard、cleanup 與所有 PNG/DOM/console/transport 均以 raw-byte size/SHA-256 綁定；`scripts/verify_evidence_bundle.py` exit 0。
- live session active console error count 為 0；guard `status=passed`、`harness_exit_code=0`、`cleanup.verified=true`、candidate processes/listeners 均為 0，real-data 191→191 zero diff。`artifacts/sprint28/browser-result-final2-live.json` 為目前候選彙總。
- 最新遞迴 index：`artifacts/sprint28/evidence-hash-index-live.json`（SHA-256 `7DA459A7FEA44C07CE25ABFC974FF3396473C689A503E1B1088EFEC9A5C925E7`）及 sidecar；entries、missing、extra、mismatch 均為 0。歷史失敗檔 `browser-final2-settings/launcher.stderr.txt` 的非 UTF-8 狀態被明確列入 index，未刪除、未作為目前 session 證據引用。
- Native Chrome 100%／125%／150%：`deferred_to_formal_release`，未以 viewport resize 冒充。

## 限制與 rollback

- Native Chrome 100%／125%／150% 仍為 `deferred_to_formal_release`；未以 viewport resize 冒充。
- Rollback：移除 change-summary projection/history，保留已驗證的 brief history、scheduler records、formal release 與真實資料。
- 未簽章、未發布、未 promotion、未修改 formal release、未開始 Sprint 29。
