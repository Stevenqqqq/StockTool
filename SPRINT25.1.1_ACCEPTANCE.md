# Sprint 25.1.1 implementation evidence

狀態：`BLOCKED`（pip-audit 發現目前虛擬環境的既知漏洞；本次核准範圍限定 breadth 日期語意，未擅自升級依賴）。本文件不是 CTO 驗收結論。

## 修正

- `src/stock_tool/application/market_monitor.py`
  - 官方 breadth 只有在 breadth date、quote date 存在且完全相同，並且 up/down/flat 三欄完整可解析時才標示 `compared`。
  - 日期落差標示 `official_stale`；日期缺失、來源不可用或內容不完整標示 `derived_only`。
  - 保留官方 breadth 原始 provenance、日期、來源與 payload metadata，不再對 stale/missing 資料產生 mismatch 結論。
- `src/stock_tool/dashboard/pages/discovery.py`
  - stale breadth 顯示「官方廣度日期過期，目前僅為自行推導」。
  - 市場總覽驗證警告改為繁體中文摘要與可展開細節。
- `tests/test_market_monitor.py`
  - 新增同日、不同日、缺日期、provenance、同日 mismatch 與 UI stale regression。
- `src/stock_tool/application/portfolio_workspace.py`
  - 修正缺少 FX 時資料狀態優先顯示 partial 的既有回歸，未改變估值公式。

## 驗證

- targeted：`pytest tests/test_market_monitor.py tests/test_roadmap_structure.py -q` → **30 passed**。
- full：`pytest -q` → **1106 passed, 2 skipped**。
- quality gate：`cmd /c quality_gate.bat` → **exit 0**；coverage **83.00%**；Black、Ruff、focused mypy、compile、privacy、release layout、regression baseline 均通過。日誌：`artifacts/sprint25.1.1/quality-gate-final.log`。
- pip check：通過（No broken requirements found）。
- pip-audit：**exit 1，7 vulnerabilities / 2 packages**（GitPython 3.1.57，pypdf 6.14.2）；未使用 ignore/skip/白名單，亦未在本 correction 範圍內升級依賴。最新結果：`artifacts/sprint25.1.1/pip-audit-final.json`。
- performance：`artifacts/sprint25.1.1/performance-canonical.json` 保留既有 Excel 6.444 秒失敗與後續量測；最終候選 `performance-current-final.json` 通過既有門檻。

## 候選與來源封存

- stable：`release/staging-sprint25.1.1/StockTool/StockTool.exe`，SHA-256 `F5BA2A82D9B29647FDD80525604B53DF889CC8499F0EFA52AE32BAD42C62B15C`，`--version` 1.2.2。
- payload：`release/staging-sprint25.1.1/StockTool/versions/1.2.2/StockToolPayload.exe`，SHA-256 `3F5FE4FB9D71AF512B7AA6F731024CF5F274CD874BF0B0ADE663335164F7675D`，`--version` 1.2.2。
- source ZIP：`artifacts/sprint25.1.1/sprint25.1.1-source.zip`，SHA-256 `3683B14727EA7F87C18DFC58EE144B6253564AA84DE4AE6D54C90685F639B37B`；獨立驗證 missing/forbidden/mismatch/duplicate 全為 0。
- candidate binding：`artifacts/sprint25.1.1/candidate-hash-binding.json`。
- formal EXE：`release/StockTool/StockTool.exe` SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`，未變更。

## 官方資料與瀏覽器

- `artifacts/sprint25.1.1/official-online-check.json`：TWSE quote date 2026-08-07、TPEx quote date 2026-08-07；TWSE official breadth date 2026-06-05 → `official_stale`，TPEx 無可靠 official breadth → `derived_only`。官方 provenance 與 payload hash 保留。
- `artifacts/sprint25.1.1/browser-result.json` 綁定本候選 stable/payload/source hash。TWSE、TPEx、COMBINED 線上語意畫面均保存 screenshot、DOM、active console 與 transport/provider metadata；active console error count 0。
- online/offline/partial EXE smoke 均通過，證據位於 `artifacts/sprint25.1.1/exe-smoke-{online,offline,partial}/guard-result.json`；三者 real-data diff 均為零。
- native Chrome 100%/125%/150% zoom 未重試，維持 `pending_cto_verification`，沒有以 viewport resize 冒充。

## 真實資料保全

- `artifacts/sprint25.1.1/real-data-before.json`、`real-data-after.json`、`real-data-comparison.json`：目前 191 檔；`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。
- 未修改、搬移或覆寫正式 EXE、installer 或真實使用者資料；候選程序與 8501/8502 listener 已清理為 0。

## 未完成項目

1. 官方 pip-audit 尚未達 exit 0（GitPython 及 pypdf 的既知漏洞）；需另行核准 dependency correction 後再重跑完整 evidence。
2. 原生 Chrome zoom 仍待 CTO verification；本次遵守指示不重複無效嘗試。
