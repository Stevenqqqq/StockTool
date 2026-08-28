# Sprint 25.1 implementation evidence

**狀態：BLOCKED — native Chrome 100%／125%／150% 原生選單證據尚未取得。**

本文件只記錄 Sprint 25.1 implementation evidence，並不代表 CTO 驗收、正式發布或 promotion。

## 修正範圍

- `src/stock_tool/application/market_monitor.py`
  - 新增官方公司清單 allow-list（TWSE `t187ap03_L`、TPEx `mopsfin_t187ap03_O`）。只有清單內四碼普通股可進入 breadth、排行與有效股票數；ETF、權證、債券、可轉債及其他商品排除。universe 取得失敗時 fail-closed，quote 不計入股票統計。
  - 支援 TPEx `SecuritiesCompanyCode`、`CompanyName`、`TradingShares`、`TransactionAmount` 欄位。
  - TWSE／TPEx 來源 metadata 各自保存 data date、universe、payload hash 與涵蓋率；合併日期不一致時顯示明確 warning，不取 max(date)。
  - TWSE 官方 breadth 另存來源與日期並與 derived breadth 比對；TPEx／無可靠官方數字明確標示「僅為自行推導」。
  - cache schema 由 1 提升為 2，舊 cache 安全拒絕；排行由 UI 對每個市場重新計算，名次由 1 連續排列。
- `src/stock_tool/dashboard/pages/discovery.py`
  - 市場總覽顯示股票 universe 規則、各來源日期、排除摘要、官方／自行推導 breadth 狀態。
  - warning 改為摘要數量與可展開細節，避免每筆排除資料各顯示大型 warning。
- `tests/test_market_monitor.py`
  - 加入 TPEx 真實欄位形狀、權證／ETF 排除、universe unavailable fail-closed、分市場四類排行、日期落差、官方 breadth 與 schema bump 回歸測試。
- `PRODUCT_EXECUTION_PLAN.md`
  - 新增 Sprint 25.1 修正範圍、資料規則、失敗模式與 rollback。

## 實際驗證命令與結果

| 命令 | 結果 |
|---|---|
| `.venv\\Scripts\\python.exe -m pytest tests/test_market_monitor.py tests/test_roadmap_structure.py -q` | **26 passed** |
| `.venv\\Scripts\\python.exe -m pytest -q` | **1102 passed, 2 skipped** |
| `cmd /c quality_gate.bat`（UTF-8 環境） | exit 0；full pytest 1102 passed／2 skipped；branch coverage **83.05%**（gate 78.5%）；Black、Ruff、focused mypy、compile、privacy、release layout、regression baseline 均通過 |
| `.venv\\Scripts\\python.exe -m pip check` | exit 0；No broken requirements |
| `.venv\\Scripts\\python.exe -m pip_audit --format=json --output artifacts/sprint25.1/pip-audit.json` | exit 0；No known vulnerabilities |
| `.venv\\Scripts\\python.exe -m compileall -q src scripts` | exit 0 |
| `git diff --check` | exit 0 |

## 官方 payload 與語意檢查

`artifacts/sprint25.1/official-online-check.json` 由 final source 直接線上取得官方 payload 後產生：

- TWSE 有效普通股 1085 筆；TPEx 有效普通股 888 筆；合併 1973 筆。
- TWSE、TPEx、COMBINED 各自重新計算漲幅、跌幅、成交量、成交額四類 Top 20，四類名次均為 1–20 連續。
- TWSE source date `2026-08-04`、TPEx source date `2026-08-05`；合併保留日期落差 warning。
- TWSE breadth 為官方比對；TPEx breadth 為「僅為自行推導」。
- 非股票商品不進入排行或有效股票數。

## Final candidate hash binding

`artifacts/sprint25.1/candidate-hash-binding.json`：

- stable `release/staging-sprint25.1/StockTool/StockTool.exe`：7,111,034 bytes，SHA-256 `8D95ADC7EFF21ABA09EBA7E0F327FCCDDA902EDE99AD66C8349AE598E04AC866`；`--version` 1.2.2。
- payload `release/staging-sprint25.1/StockTool/versions/1.2.2/StockToolPayload.exe`：23,755,183 bytes，SHA-256 `7EF940C888094EE040966BF2F2561697F9C1010FC8F6BB9458F09AFFCD71B594`；`--version` 1.2.2。
- source ZIP `artifacts/sprint25.1/sprint25.1-source.zip`：2,528,457 bytes，SHA-256 `5CE7114BF874713E721E2B575902E4A074881E05494D955FAE4C23FC66C63974`；sidecar 同 hash。
- formal `release/StockTool/StockTool.exe`：SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`，未變更。

Source archive 獨立解壓驗證：`missing_required_inputs=0`、`forbidden_entries=0`、`content_mismatches=0`、`duplicate_entries=0`；結果見 `artifacts/sprint25.1/privacy-release-validation.json`。

## EXE／隔離 smoke

所有候選啟動均經 `scripts/evidence_launcher.py` → `browser_transport_harness.py`，使用新 temporary data root：

- online：`artifacts/sprint25.1/exe-smoke-online/guard-result.json`，passed、real data zero-diff、cleanup verified。
- offline：`artifacts/sprint25.1/exe-smoke-offline/guard-result.json`，passed、cleanup verified。
- partial：`artifacts/sprint25.1/exe-smoke-partial/guard-result.json`，passed、cleanup verified。
- performance EXE readiness：`artifacts/sprint25.1/performance-current.json`，三次 max 2.524311 秒，門檻 5 秒，passed。

三次候選 health smoke 結束後 StockTool／StockToolPayload process 為 0，8501／8502 listener 為 0。

## Browser evidence

`artifacts/sprint25.1/browser/browser-result.json` 綁定 final stable、payload、source hash：

- 真實 Chrome 候選頁線上語意旅程：TWSE、TPEx、COMBINED 三項皆 passed；每項均保存 screenshot、DOM、active console、transport/provider metadata。
- screenshot SHA-256：TWSE `D0DA4674FC1D0B23DF2F344EAADC6784A9EFE19A63ABA27A2818CB914337DE10`；TPEx `4D2955B8533F41010045AD96C5AE6BA32FDB8390A66D11AE1437539BE9B1A557`；COMBINED `66FCA33EA6F566506CE0BA3A6C4CC718974040E10F1697186521764ECB6A6ABD`。
- active console error count 0；Tab／Shift+Tab 最佳努力操作均取得可見 `[active]` DOM focus。
- 目前 Chrome extension 只提供 viewport override，沒有原生瀏覽器選單與 authoritative zoom percentage 控制能力；未使用 viewport resize 冒充 100%／125%／150%。因此三個 native zoom 狀態均為 **BLOCKED**，總 browser evidence 不可宣稱通過。
- 最短人工補證步驟已寫入 `browser-result.json`：在 Chrome 開啟 `http://127.0.0.1:8501`，用原生選單依序選 100%、125%、150%，每張截圖同時看見選單實際比例與 StockTool。

## 效能歷史保全

`artifacts/sprint25.1/performance-canonical.json` 依時間保存三次結果，未覆寫既有歷史：

1. `artifacts/sprint25/performance-final-rerun.json`：Excel export max **6.444253299967386 秒**，明確 failed（保留原始失敗）。
2. `artifacts/sprint25/performance-final.json`：後續測量 pass。
3. `artifacts/sprint25.1/performance-current.json`：final candidate 目前 pass；Excel export max 1.062318200012669 秒。

歷史失敗與後續結果分開保存；後續測量使用已分離 timing／allocation instrumentation 的流程，未調整門檻，也沒有用 pass 覆寫 6.444 秒失敗。

## 真實資料保全與 cleanup

- `artifacts/sprint25.1/real-data-before.json`／`real-data-after.json`：目前真實 `%LOCALAPPDATA%\\StockTool` 均 191 files。
- `artifacts/sprint25.1/real-data-comparison.json`：`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。
- 六個 incident files 的當前 hash 見 `artifacts/sprint25.1/incident-files-current.json`，與既有紀錄一致，未刪除、修改或搬移。
- formal release 未修改；未簽章、未發布、未 promotion、未 commit/tag/push、未開始 Sprint 26。

## 目前唯一 hard blocker

Native Chrome 100%／125%／150% 原生選單畫面尚未取得。其餘商品 universe、TPEx parser、分市場排行、來源日期、breadth、cache schema、品質、效能、候選 smoke、source archive、privacy 與真實資料 zero-diff 證據已保存，等待補齊真正 Chrome 原生縮放證據後再交 CTO 獨立驗收。
