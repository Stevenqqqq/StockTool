# Sprint 26.1.1.1.1 implementation evidence

狀態：implementation evidence complete，等待獨立 CTO 驗收。這不是 CTO acceptance、發布或 promotion。

## 範圍與候選

本輪只補 browser evidence provenance；沒有修改 DailyResearchBrief 產品核心、正式 EXE、installer、版本號或真實使用者資料。候選與既有 staging 相同，並在本輪重新核對：

- stable：`DB2B688EE9F1FE4F01C810A3FCD4E27DF7F7F8BF5BA793491A175865311E3EDC`
- payload：`7EA271B5BD893976FE6C67A9D5939024E0469263BD6EEF5D5AD7A0776226BBC7`
- source ZIP：`23A21E1F8D31180E8B2747D966B599D59132B80A2A91407C0A6D1E83E353E834`
- formal `release/StockTool/StockTool.exe`：`4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`

候選綁定檔：`artifacts/sprint26.1.1.1.1/candidate-hashes.json`。

## Browser provenance

使用 `scripts/evidence_launcher.py` 啟動同一個全新隔離資料根，online duration/timeout 為 60/240 秒；首頁完成渲染後才擷取，擷取完成後才讓 harness 結束與 cleanup。

- session：`sprint26.1.1.1-session-20260809103241185`
- launch_started：`2026-08-09T02:32:44.135778+00:00`
- capture interval：`2026-08-09T02:33:12.909818Z` 至 `2026-08-09T02:33:15.276158Z`
- cleanup_completed：`2026-08-09T02:33:45.295046+00:00`
- capture manifest：`artifacts/sprint26.1.1.1.1/capture-session-manifest.json`
- capture manifest SHA-256：`5F26FFC16867C8B9DC1BF64670796D63E64D28843CC65239258434C7A1AC622A`
- home PNG：`2B8FA6AC848BC15E0413F2F5737EDE20E38C89874D8EC2695F054FCD86AC9178`（70,075 bytes）
- brief PNG：`548FC04379C65910511F9F7A4E7DE9AA8CA0C0438B9A2877143F65651A44AB2F`（91,405 bytes）
- active console errors：0；兩個 console JSON 均為本 session 的 `[]`。

已使用影像檢視工具親自檢查 `home.png` 與 `brief.png`：前者顯示 StockTool 首頁主要內容，後者顯示本 session 的「每日證據鏈研究簡報」與狀態／資料缺口。DOM hard gate 亦驗證 StockTool、首頁／簡報標題、主要控制項與 brief 結構。

online、offline、partial 的詳細 path/hash 與 mode 驗證位於 `artifacts/sprint26.1.1.1.1/browser-result.json`；offline/partial 分別綁定 `exe-smoke-20260809103241185-offline` 與 `exe-smoke-20260809103241185-partial` 的實際 launch mode。browser-result `overall_passed=true`，native zoom 維持 `deferred_to_formal_release`。

## Guard、歷史與失效證據

online guard：`status=passed`、`harness_exit_code=0`、`cleanup_verified=true`、`candidate_processes_remaining=[]`、`listeners_remaining=0`、real-data zero diff。guard hash 為 `57E8E684A8FAD43459AFAD0E16C122B1D27ED8456DFEE986ECE4306AEEBC7F61`。

`artifacts/sprint26.1.1.1/superseded-invalid-online.json` 原樣保留並標示 `superseded_invalid`：舊 home 空白、brief 檔案與 failed fixture 相同、且檔案在 cleanup 後才產生。不得把該輪畫面當成目前驗收證據。`artifacts/sprint26.1.1.1.1/browser-history-index.json` 遞迴掃描 50 個 guard，保留 8 個歷史 failed guards，並另列 superseded/invalid passed evidence；目前驗收只引用本輪 browser-result。

## 測試與品質

實際命令與輸出保存在 `artifacts/sprint26.1.1.1.1/`：

- targeted：`.venv\\Scripts\\python.exe -m pytest tests/test_daily_research_brief.py tests/test_daily_home.py -q`；31 passed。
- `cmd /c quality_gate.bat`：exit 0；full pytest 1,128 passed、2 skipped、2 warnings；branch coverage 83.14%（gate 78.5%）。
- quality gate 同時完成 Black、Ruff、focused mypy、compile、project privacy、release layout、regression baseline。
- pip check：exit 0，`No broken requirements found.`（`pip-check.log` 為 UTF-8、無 BOM）。
- official pip-audit：exit 0、`No known vulnerabilities found`；JSON 可直接以 UTF-8 parse。
- performance：5 項固定 workload 各 3 次，`performance.json` overall passed；EXE health ready max 2.531 秒，其他門檻亦通過。
- source archive：`source-archive-verification.json` 的 missing/forbidden/content mismatch/duplicate 全為 0；source ZIP hash 與候選綁定一致。
- `git diff --check`：exit 0。

## 資料保全與清理

本輪事件後真實資料基線為 191 檔。`real-data-before.json`、`real-data-after.json`、`real-data-diff.json` 顯示：`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。候選與 smoke 均使用隔離 temporary data root；未寫入 `%LOCALAPPDATA%\\StockTool`。

收尾檢查：StockTool/StockToolPayload process=0；8501/8502 listener=0。正式 EXE hash 維持上述值，未修改正式 release。未發布、未簽章、未 commit、未 tag、未 push，未開始 Sprint 26.2。

## 限制

原生 Chrome 100%/125%/150% zoom 仍為 `deferred_to_formal_release`，沒有以 viewport resize 或舊截圖冒充；其餘本輪 hard gate 以同一 live session、capture manifest 與 hash binding 保存，交由 CTO 獨立驗收。
