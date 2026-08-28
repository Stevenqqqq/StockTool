# Sprint 32 implementation evidence

本文件只記錄 Sprint 32 的 implementation evidence，未宣稱 CTO／Sol 驗收、正式發布或
正式排程啟用。所有候選啟動均使用 `scripts/evidence_launcher.py` 與新的隔離
`STOCK_TOOL_USER_DATA_DIR`；正式 `release/StockTool`、已安裝 v1.3.0、桌面捷徑與真實
使用者資料均為唯讀。

## Checkpoint

因工作樹含有無法歸屬於 Sprint 31.1 的既有 dirty 變更，未強行建立 commit。以
`artifacts/sprint32/checkpoint-sprint31.1/` 保存 12 個已驗收 Sprint 31.1 檔案的 source
snapshot；未納入 artifacts、cache、log、runtime 或使用者資料。

- manifest：`artifacts/sprint32/checkpoint-sprint31.1/checkpoint-manifest.json`
- manifest SHA-256：`DB115BD37F9621B39D514FDF931AD127BE382227A033286C4AEAED6DA264F1C0`
- file count：12
- sidecar：`checkpoint-manifest.sha256.json`

## 實作範圍

- 新增 `src/stock_tool/application/daily_research_runner.py`：以既有
  `HeadlessDailyResearchRunner` 為核心的共用 façade，產生不可變、UTF-8、schema-versioned
  六階段 run manifest 與 atomic latest projection。
- 首頁加入原生 `執行今日研究` action，保留既有 widget key、refresh、研究接力與資料流。
- scheduler/headless/首頁均走同一 runner；上限 20 個 market-qualified targets；同一市場
  snapshot 不在下游重新 refresh。
- `RuntimePaths` 新增隔離 run-manifest 目錄；launcher headless 入口改用共用 runner。
- `PRODUCT_EXECUTION_PLAN.md` 補 Sprint 32 scope、non-goals、rollback 與 pending acceptance，
  並將 Sprint 31.1 狀態記為已接受。

## 自動驗證

- targeted：187 passed；原始輸出 `artifacts/sprint32/logs/targeted-final.log`。
- full pytest：1415 passed、2 skipped、0 failed；`logs/full-pytest-final.log`。
- branch coverage：82.41%（quality gate 同輪報告 82.38%）；`logs/coverage-final.log`。
- quality gate：exit 0，targeted/full/coverage/Black/Ruff/focused mypy/compile/privacy/release
  layout/regression 全部完成；`logs/quality-gate.log`。
- Ruff、Black、mypy、compileall：exit 0；對應 logs。
- pip check：exit 0；pip-audit：exit 0、無已知漏洞（`.venv` pip 26.2）；
  `pip-audit-final.json`。
- performance：`performance-final.json`；三次 `exe_health_ready` 為
  2.531508、2.526110、2.526780 秒，最大值 2.531508 秒，門檻 5 秒，整體 passed。
- source archive：`release/staging-sprint32-source.zip`，SHA-256
  `5F7E7D2181936AA568D08DD363C770821F0A65F597F528464DE09B1D389A103B`，獨立驗證
  required/forbidden/content mismatch/duplicate 均為 0。

## Staging candidate

路徑：`release/staging-sprint32/StockTool/`

| artifact | size | SHA-256 | version |
|---|---:|---|---|
| stable `StockTool.exe` | 7,110,704 | `4CD8AC1954DAAB8A06B9821D2EF3D90103C6EBFB1425536FFF96D10D9EC005EA` | 1.3.0 |
| payload `versions/1.3.0/StockToolPayload.exe` | 24,040,528 | `BD7C3F95B52378926F19A69BFED29CA4D71FA8E9F148D4C72AA113BFDE4C13F2` | 1.3.0 |
| source ZIP | 2,718,743 | `5F7E7D2181936AA568D08DD363C770821F0A65F597F528464DE09B1D389A103B` | n/a |
| formal `release/StockTool/StockTool.exe` | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` | 1.2.2 |

完整 binding：`artifacts/sprint32/candidate-hashes.json`。

## Browser / EXE evidence

同一 live candidate session：
`artifacts/sprint32/browser-sprint32-browser-73d91621557845e5984eabdcc09899e3/`

- `home.png`、`home.dom.txt`、`home.console.json`：首頁、主要研究入口與一鍵按鈕；畫面已實際檢查。
- `daily-run.png`、`daily-run.dom.txt`、`daily-run.console.json`：隔離無標的情境，真實顯示
  `skipped_no_targets`，未建立預測樣本。
- `settings.png`、`settings.dom.txt`、`settings.console.json`：真實顯示正式排程「目前狀態：未安裝」、
  週一至週五 18:30（Asia/Taipei）；未建立或修改 task。
- 所有 active console error count：0。
- `capture-session-manifest.json`、`browser-result.json` 綁定同一 session、candidate hashes、
  launch/guard/cleanup raw bytes；`artifact-hash-index.json` 驗證 passed。
- `browser-verification.json` 以磁碟上的原始 bytes 重新核對 capture manifest、場景語意、
  capture 時窗、console、responsive 量測、guard 與候選 binding，結果 `passed=true`、
  `errors=[]`。最終 `artifact-hash-index.json` 為 105 entries，missing/extra/mismatch/errors
  全部為 0。
- online、offline、partial EXE health smoke 均由 evidence launcher 完成；headless manual run
  在隔離無標的資料根以 exit code 20（skipped）完成，沒有把 skipped 冒充 success。
- responsive measurements：1707×960、1280×720、1024×768、853×768 均無水平 overflow、
  無量測到控制項裁切；`responsive-measurements.json`。
- keyboard：保留既有自動化測試；本輪 browser CUA 觀察保存於 `keyboard-evidence.json`，
  不把未能完整證明的瀏覽器焦點循環宣稱為人工驗收。
- Chrome 原生 100%／125%／150%：`deferred_to_formal_release`，未以 viewport resize 冒充。

## 資料與清理

- `real-data-before.json`、`real-data-after.json`、`real-data-current.json`、
  `real-data-diff.json`：`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。
- formal/installed/shortcut before/after：`formal-installed-diff.json`，`zero_diff=true`。
- 最終 StockTool/StockToolPayload process=0、8501/8502 listener=0、Task Scheduler matching
  task=0；`logs/cleanup-final.json`。
- 本輪建立的 build/source-verify 暫存目錄已移除；未清理任何既有使用者資料或歷史 evidence。

## 限制與治理邊界

- 本文件是 implementation evidence，等待獨立 CTO/Sol 驗收；不代表正式發布或 promotion。
- 正式 v1.2.2、已安裝 v1.3.0、installer、桌面捷徑、正式排程與真實資料均未修改。
- 原生 Chrome zoom 與完整人工鍵盤／視覺驗收仍保留給正式人工驗證。
