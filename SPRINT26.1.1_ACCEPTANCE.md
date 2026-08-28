# Sprint 26.1.1 Implementation Evidence

狀態：`BLOCKED — browser evidence harness timeout`

本次僅完成每日研究簡報安全封口與證據重建；未宣稱 CTO acceptance、發布或正式版本核准。

## 實作

- `DailyResearchBrief` schema 提升至 2；fingerprint 涵蓋 status、message、manifest 語意欄位、items、sources、references 與使用者可見語意，排除 generated-at 與暫存位置。
- `references` 僅保存可解析的 `EvidenceReference` ID；人類可讀標籤改為 `reference_labels`。未知、重複、不一致或竄改 citation 皆 fail closed。
- `DailyResearchBriefStore` 僅以 UTF-8 原子保存權威 JSON；HTML 是由已驗證 JSON 產生的非權威投影，HTML 寫入失敗不會回滾或形成跨版本組合。
- fault-injection 覆蓋暫存 JSON、發布/replace、HTML 投影失敗；每一失敗均保留上一份成功 JSON 可完整載入。
- 舊 loop event 只允許目前 Portfolio/Watchlist 的 market-qualified identity，避免洩漏過期標的。

## 測試與品質

- targeted：`tests/test_daily_research_brief.py tests/test_daily_home.py` — 31 passed。
- quality gate：exit 0；full pytest 1128 passed、2 skipped；branch coverage 83.14%；Black、Ruff、focused mypy、compile、privacy、release layout、regression baseline 全部通過。
- `pip check` exit 0。
- 官方 `pip-audit --format json` exit 0、0 vulnerabilities；UTF-8 可直接解析：`artifacts/sprint26.1.1/pip-audit.json`。
- performance hard gate 通過：`artifacts/sprint26.1.1/performance-final.json`。
- quality log 為 UTF-8（非 UTF-16LE）：`artifacts/sprint26.1.1/quality-gate-final.log`。

## Candidate / archive

- stable：`release/staging-sprint26.1.1/StockTool/StockTool.exe` — `DB2B688EE9F1FE4F01C810A3FCD4E27DF7F7F8BF5BA793491A175865311E3EDC`
- payload：`release/staging-sprint26.1.1/StockTool/versions/1.2.2/StockToolPayload.exe` — `7EA271B5BD893976FE6C67A9D5939024E0469263BD6EEF5D5AD7A0776226BBC7`
- source ZIP：`artifacts/sprint26.1.1/sprint26.1.1-source.zip` — `420F0854DAFD713C59B9F00891D7053F4C6A58A0D8CF1A71E48D356D7DDC33E9`
- source archive 獨立驗證：missing/forbidden/content mismatch/duplicate 均為 0。
- formal EXE `release/StockTool/StockTool.exe` 未變：`4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。

## 隔離 EXE 與資料保全

- `scripts/evidence_launcher.py` online/offline/partial 三次 smoke 均 passed，health ready、cleanup verified，8501/8502 無殘留。
- 真實資料 dedicated manifests：`artifacts/sprint26.1.1/real-data-before.json`、`real-data-after.json`、`real-data-diff.json`；191→191，added/removed/changed 全空，zero_diff=true。
- 所有候選啟動使用新 temporary data root；未修改 formal EXE 或真實資料。

## Browser / history

- `artifacts/sprint26.1.1/browser-history-index.json` 掃描 39 筆 guard，保留 8 筆歷史失敗（未刪除或隱藏）。
- 最新 `browser-result.json` 綁定本次 stable/payload/source hashes；首頁截圖、DOM、console 與 guard 路徑已保存。
- 本輪以隔離 fixture 實際取得首頁與簡報 PNG/DOM，active console error=0；但 evidence harness timeout，故不偽造 guard passed，browser overall 保持 `blocked`。
- 原生 100%/125%/150% zoom 維持 `deferred_to_formal_release`，未以 viewport resize 冒充。

## 限制與治理

- 唯一未封口硬門檻是可重播的 browser brief/console 成功證據；需後續在穩定候選 health session 中重跑，並重新 hash-bind browser-result。
- 未新增 dependency、排程、產品功能；未 commit/tag/push、未發布、未簽章，未修改 formal release 或真實使用者資料。
