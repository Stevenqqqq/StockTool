# 股票分析與回測工具

這是一套研究、學習、風險分析與輔助判斷用途的股票分析工具。它不是投資顧問，不承諾任何收益，不自動下單，也不構成個人化投資建議。歷史資料與回測結果不代表未來報酬。

## 最新交付：v1.4.3 MU r2 修正版（2026-09-30）

使用者已核准本機更新及私人 GitHub Release。此版修正 MU 公司資料缺漏與重試呈現，
將「評分項目覆蓋率」與公司研究完整性分開；部分資料恢復仍誠實顯示缺口。
1280／760px 的覆蓋率標籤、價格及日期已在最後 EXE 獨立實測。
程式內版本仍為 1.4.3，發布識別為 `v1.4.3-mu-r2`；請勿只靠版號判斷是否已更新。
固定啟動器 SHA-256 為 `957E5F3C...AC102285`，payload 為 `797C1BBC...4625B50`。
下載與限制見 [私人 GitHub Release](https://github.com/Stevenqqqq/StockTool/releases/tag/v1.4.3-mu-r2)
及 [交付說明](docs/release/v1.4.3-mu-r2.md)。安裝器未簽章；guest lifecycle 未執行，保留既有豁免。

## v1.4.3 個人主機更新（2026-09-27；未對外發布）

本版將已由 Sol 驗收的持股與公司研究工作流程版本化為 1.4.3，不新增產品功能。
桌面「股票分析工具」與開始功能表「StockTool」皆使用安裝目錄的固定 `StockTool.exe`，
由 `current-version.json` 選擇已驗證的版本 payload。
持股、研究、備份與 Groq 憑證保留於 `%LOCALAPPDATA%\StockTool`；不自動合併舊預覽資料。
使用者已核准本次在目前主機直接升級，並明確豁免 guest 安裝生命週期。已安裝位置與
`release\StockTool\` 本機正式目錄均為 1.4.3；原有使用者資料逐檔未變。已通過雜湊、
資產與隔離啟動核對，但桌面畫面及實際重啟尚未驗證；不宣稱 guest lifecycle 通過，
也不代表已在 GitHub 對外發布。詳見 `docs/product/v1.4.3-host-upgrade.md`。

## v1.4.2 個人正式發布版（2026-09-03 已核准）

v1.4.2 延續已驗收的 Prediction Lab、5/20 交易日結果追蹤、官方市場日曆、
market-qualified benchmark 與公司行動 fail-closed 邊界。這是僅提升 `pypdf` 安全下限的
個人正式發布版；Windows 安裝程式仍未簽章；
安裝時顯示未知發行者不代表程式已取得系統管理員權限。

本次 lifecycle 等價證據豁免已由使用者於 2026-09-03 核准：本次僅為 pypdf 安全更新，
installer source 與 behavior 未變，v1.4.1 lifecycle 已通過，且主機沒有安全 VM 可供重播。
因此不宣稱已重新執行完整的 clean install、repair、upgrade 與 uninstall lifecycle 矩陣；
正式交付仍已在目前主機完成靜默升級、installed EXE／桌面捷徑驗證與隔離啟動 smoke。

## Sprint 13 Corporate Actions And Benchmark Policy

Corporate-action support is intentionally opt-in. A backtest must declare one
price policy: `raw_price_with_explicit_actions`, `adjusted_total_return`, or
`unknown`. Splits may be applied to raw prices with either return basis because
they preserve value and cost basis. Cash dividends may be applied only with
`total_return`; a `price_return` backtest with an explicit cash-dividend action
fails closed rather than crediting cash. `adjusted_total_return` requires both
`total_return` and a verified `AdjustedSeriesContract` for the source-backed
`adjusted_close` column. The column name, or `adjusted_close == close`, is not
proof that the data includes total return. Adjusted total-return prices reject
explicit actions to prevent double counting; an unknown policy fails closed
when actions are supplied.

The local CSV import contract requires `symbol`, `market`, `action_type`,
`effective_date`, `available_date`, and `source`. Dividend rows additionally
need `payable_date`, `cash_per_share`, and `currency`; split rows need
`split_ratio`. `available_date` is a point-in-time guard: an action known only
after its effective date is recorded as unavailable rather than applied.

Corporate actions are not comprehensive market data. Missing, partial, or
unknown source coverage remains a research limitation. Benchmark comparison is
only available when strategy and benchmark use the same explicit return basis
(`price_return` or `total_return`) and exact date alignment; StockTool never
forward-fills benchmark observations.

Equivalent records from multiple sources are consolidated once by the
market-qualified economic event and its economic terms. The economic terms
include split ratio, cash per share, currency, payable date, and normalized
cash-dividend tax rate; source, availability, and provenance remain in the
audit evidence. Conflicting terms for the same economic event fail closed and
are recorded as unavailable. Because the
current backtest ledger remains symbol-keyed, explicit actions also fail closed
when one historical price series uses the same symbol in more than one market.

## v1.2 報表重現與 Benchmark

v1.2 將 benchmark 視為正式研究輸入，而不是可任意混用的價格表。策略資金曲線與
benchmark 必須在相同研究區間、相同交易日期完整對齊；系統不會自動前向填補、刪除
重複日期或以錯位的起訖資料計算比較結果。無法可靠對齊時，benchmark 報酬、最大回撤
與超額報酬會顯示「資料不足」，不會以 0 取代。

Excel 與 HTML 報表新增 Benchmark、資料來源、資料品質與可重現性 Manifest 區塊。
Manifest 記錄已遮罩的資料來源、輸入雜湊、策略與成本參數、benchmark 對齊資訊及關鍵
輸出雜湊，方便核對同一份研究輸入是否被重現。Manifest 不會保存原始行情、私人 PDF、
投資組合或憑證；它本身也不能重新下載已不存在的外部資料。重現時仍需取得相同的輸入
資料或相符快取。

從報表的「可重現性 Manifest」與「資料來源」區塊可查看 input hash、實際 provider、
查詢代號、日期範圍與回測參數。所有歷史績效與 benchmark 比較僅供研究，並不代表未來
報酬或任何買賣建議。

## 快速開始

建議使用 Python 3.11 或以上版本。本專案使用 `pyproject.toml` 管理依賴，沒有 `requirements.txt`；請用 editable install 安裝主套件與 dev 測試工具。

Windows / PowerShell 建議流程：

```powershell
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

確認目前使用的是 venv 內的 Python 與 pip：

```powershell
python --version
python -m pip --version
```

執行測試：

```powershell
python -m pytest
```

### 開發、測試與發行基線

在修改核心資料、評分、回測、風控或報表邏輯前，先確認目前基線：

```powershell
python -m pytest tests/test_regression_baseline.py
python -m pytest
python -m pytest --cov=stock_tool --cov-report=term-missing
```

Sprint 1.1 將目前公開研究行為固定在
`tests/fixtures/sprint1_baseline.json`。Golden test 會從版本化的
`data/sample/sample_tw_prices_for_indicators.csv` 與
`data/sample/sample_fundamental_scores.csv` 開始，依序驗證資料載入、清洗、
技術指標、綜合評分、下一根 K 棒成交與 HTML 報表風險揭露，不依賴網路或
即時行情。這不是投資結果保證；它只是防止後續重構在沒有明確核准的情況下
改變既有程式行為。

同一份離線基線固定驗證三種市場代號規則：

| 使用者代號 | 市場 | 實際查詢代號 |
|---|---|---|
| `2330` | TWSE | `2330.TW` |
| `6488` | TPEx | `6488.TWO` |
| `AAPL` | US | `AAPL` |

`pyproject.toml` 設定 coverage gate 為 72.63%。Sprint 5.2 驗收另外要求
branch coverage 不低於 78.50%；不能只看測試案例是否通過。

完整的行為邊界位於 `docs/architecture/contracts.md`，v1.1 發行驗收清單
位於 `docs/release/acceptance-v1.1.md`。在進行架構遷移前，請建立 Git tag
或等效的不可變備份，並保存 EXE 的 SHA-256 checksum。若環境沒有 Git，
不要在驗證流程中自行安裝；請明確記錄限制，並以最終 source archive 與
SHA-256 checksum 暫代 merge baseline。

發行驗證順序固定為：完整 pytest、coverage gate、EXE build、EXE smoke
test、README 一致性檢查，最後才建立 `release/baseline/` 下的 source
archive 與 checksum。不要在測試或文件仍可能變動時提早封存 source archive。

### Sprint 2 Domain 與 Provider 契約

Sprint 2 新增 provider-independent domain models 與 default-off provider contract，
目的是讓後續 application service 能取得一致的資料狀態，不是改變目前 dashboard、
CLI、評分或回測結果：

- `stock_tool.domain.models.Symbol`：以 `code + Market` 表示 canonical identity。
- `MissingData`：明確區分 `missing`、`unknown`、`not_applicable`、`stale`。
- `ProviderResult`：包含 `status`、validated data、source metadata、quality report、
  provider attempts、warnings 與 structured error。
- `QualityReport`：重用既有 `clean_price_data()` 規則，回報空資料、schema drift、
  重複欄位、部分可用資料與無效資料，不修改輸入 DataFrame，也不補假資料。
- `LegacyPriceDataProviderAdapter`：在不改舊 CSV/Excel provider 介面的前提下，
  將舊回傳格式包裝成新 contract。

新 contract 預設由 `provider_contracts_enabled=False` 關閉。既有程式仍呼叫
`fetch_prices()`；只有 contract 測試或後續 migration 明確 opt in 時才使用：

```python
from stock_tool.data import fetch_prices_result

result = fetch_prices_result(
    "2330",
    market="TWSE",
    contracts_enabled=True,
)
print(result.status.value)
print(result.metadata.to_dict())
print(result.quality.to_dict())
```

這個 opt-in API 仍使用原本的 provider/fallback 流程。Sprint 2 沒有建立
`DataHydrationService`、ingestion metadata、storage migration 或新 UI；那些屬於
Sprint 3 之後的工作。

啟動儀表板：

```powershell
streamlit run src/stock_tool/dashboard/app.py
```

或使用和 EXE 相同的 launcher 流程從原始碼啟動，會自動選擇 `8501`，若被占用則改用 `8502`，並嘗試開啟瀏覽器：

```powershell
.\run_from_source.bat
```

CLI 基本用法：

```powershell
python -m stock_tool --help
python -m stock_tool import-data --file data/sample/sample_tw_prices.csv
python -m stock_tool analyze --symbol 2330
python -m stock_tool backtest --strategy ma_cross --symbol 2330
python -m stock_tool report --symbol 2330 --output reports/2330_report.xlsx
```

### Sprint 3 Application Service 與資料血緣

Sprint 3 新增 opt-in application services，供後續工作流程整合使用。既有
Dashboard 與 CLI 仍維持原本路徑；本次不改技術指標、基本面、綜合評分或回測公式。

- `DataHydrationService` 消費 canonical `ProviderResult`，回傳已驗證 OHLCV 的防禦性副本並記錄資料來源血緣。
- `AnalysisService` 透過注入的協作者串接 hydration、技術指標、基本面評分與綜合評分，明確回傳 `success`、`partial`、`insufficient_data`、`stale` 或 `error`。Provider 失敗時不會產生假分析或假分數。
- `SQLitePriceStorage` 新增加法式 `001_ingestion_runs` migration，紀錄 run ID、requested/resolved symbol、provider、來源類型、日期、cache hit、列數、品質摘要、warning、attempt、error 與最後資料日期；不保存原始 payload 或 stack trace。
- application result 與 SQLite 血緣資料沿用 Provider Contract 的遮罩政策，不保存 API key、token、Authorization、password、secret 或敏感 URL query 值。

`SQLitePriceStorage.initialize()` 會重複安全地套用 migration 並保留既有 `prices` 資料。需要回復前請先使用 `backup_database(path)`；`restore_database(path)` 可還原 SQLite 備份。`rollback_ingestion_runs_migration()` 只移除 Sprint 3 的血緣 metadata，不會刪除價格資料。

Windows release build 僅帶入 `data/sample/`；使用者資料不會放在或寫入 `release/StockTool/`。不會複製本機 cache、processed 資料、投資組合、watchlist、reports、logs 或真實 `.env` 到 release。

### Sprint 3.2 投資組合資料安全與多幣別估值

可寫入的使用者資料統一存放於：

```text
%LOCALAPPDATA%\StockTool\
  data\portfolio.csv
  data\watchlist.csv
  data\processed\
  data\cache\
  reports\
  logs\
  backups\
  settings.json
```

進階使用者或測試可設定 `STOCK_TOOL_USER_DATA_DIR` 覆寫此位置。啟動新版 EXE 時，若舊 release 內的使用者資料存在且新位置尚無資料，系統會先建立備份、再複製並驗證列數與 SHA-256；舊資料會保留。若新舊位置同時有資料，系統不會覆蓋新位置，而會留下明確警告。

投資組合以「股票代號 + 市場」為唯一識別。台股上市、上櫃與美股預設使用 TWD、TWD、USD；CUSTOM 市場必須明確填入幣別。跨幣別總市值、損益與權重只會在所有持股價格及 FX 匯率都可用時顯示。缺少匯率時，系統會顯示資料不足，而不會把 TWD 與 USD 直接相加。

「投資組合健康度與本機規則式摘要」是 deterministic 的研究輔助，包含集中度、風險、既有股票評分覆蓋與資料可信度。它不會呼叫外部 AI、不會傳送持股資料、不預測價格，也不提供買賣指令。壓力測試僅依使用者設定的假設做算術情境推演，不是預測。

### Sprint 5.2 回測操作引導與投資組合風險提示

「策略回測」頁面依序顯示：選擇標的與資料、選擇策略、策略參數、資金與成本、執行前檢查、執行，以及結果解讀。它只用歷史資料檢驗既有規則，不會自動下單；訊號仍在 T 日產生，最早於 T+1 的下一根 K 棒開盤價成交。

介面所有比例皆以百分比輸入，傳入引擎時才轉成原有 rate：例如策略投入 `40%` 會傳入 `0.40`，手續費 `0.1425%` 會傳入 `0.001425`。策略投入比例會直接對應既有策略的 `target_percent`，而單一持股上限仍會傳給既有 `BacktestEngine` 與 `Broker`；投入比例高於上限時，執行前檢查會阻擋回測。

成本預設只代表研究假設：

| 市場 | 預設手續費 | 預設賣出稅費 | 預設滑價 | 幣別 |
|---|---:|---:|---:|---|
| TWSE / TPEX | 0.1425% | 0.3000% | 0.1000% | TWD |
| US | 0.1000% | 0.0000% | 0.1000% | USD |

自行調整成本後，介面會改為「自訂研究假設」，不會在 rerun 或市場切換時靜默覆寫。未知市場不會猜測幣別或成本，必須由使用者明確確認。這些設定不改變 Broker 的費用公式：手續費會套用於買賣，交易稅只在賣出時套用，滑價仍套用於既有 next-open 模擬成交價。

移動停利的日線模型也以中文說明：每一日收盤後更新持倉期間的最高收盤價；回落達設定比例時只產生研究賣出訊號，最早下一根 K 棒成交。這不是即時盤中停損模型。

投資組合健康度與策略回測是獨立功能，不需要先做回測。投資組合缺少價格、匯率、歷史股價、基本面或完整綜合評分時，頁面會顯示中文下一步操作與可展開的技術原因；系統不會因此補假價格、假匯率或假分數。

### 已匯入資料與自動載入

若已使用 `import-data` 匯入資料，資料會儲存在：

```text
%LOCALAPPDATA%\StockTool\data\processed\stock_data.sqlite
```

Windows EXE 與原始碼模式都透過同一個 runtime path service 讀取這個 SQLite 檔案。也就是說，只要資料已經匯入，下次打開 `StockTool.exe` 或執行 Streamlit 時，不需要再手動上傳 CSV。開發者若明確設定 `STOCK_TOOL_USER_DATA_DIR`，則以該目錄為準。

不是只能使用預載的 `2330`。若要加入其他股票，請到儀表板的「自動抓資料」頁面輸入股票代號：

- 台股上市：輸入 `6789` 會查詢 `6789.TW`
- 台股上櫃：輸入 `6488` 會查詢 `6488.TWO`
- 美股：輸入 `AAPL` 會查詢 `AAPL`

下載成功後會自動寫入使用者資料目錄的 `data/processed/stock_data.sqlite`，並和既有股票資料合併。下次重開 EXE 時，這些已抓過的股票會自動載入。

若畫面顯示「資料不足」，通常代表缺少基本面或估值資料，不是股價沒有載入。股價資料可以自動下載；基本面第一階段仍以 CSV 或範例資料為主。系統會先顯示「可用資料評分」，例如只用技術面與風險面評估；完整 0-100 總分只有在技術面、基本面、估值面、風險面都具備資料時才會顯示。

### 今日 AI 研究簡報

研究首頁的「今日 AI 研究簡報」會從已建立的 Daily Brief、持股／有效自選股候選與既有個股研究快照中，最多整理三檔值得重新研究的股票。它不會自動下載資料，也不會修改持股、自選股、評分、風險分數或回測結果。

- 每一個 `FACT` 都必須直接連回現有 evidence ID；`CALCULATION` 是 StockTool 的既有確定性計算；`INFERENCE`、`MISSING`、`WARNING` 會明確標示。
- 未設定 AI Provider、離線、逾時、限流、回傳非結構化 JSON 或引用驗證失敗時，系統改用「本機規則模式」，不會把本機摘要說成 AI，也不會顯示買賣指令、目標價或報酬預測。
- 成功的 AI 簡報只會以 `市場 + 股票代號` 保存一份最新結果到 `%LOCALAPPDATA%\StockTool\data\ai_research\`；同一份研究快照與證據不會重複呼叫 AI。損毀或不相容快取會安全忽略。
- 可選環境變數為 `STOCK_TOOL_AI_BASE_URL`、`STOCK_TOOL_AI_API_KEY`、`STOCK_TOOL_AI_MODEL`。請只在自己的環境設定 API Key；`.env.example` 只保留空白 placeholder，正式 EXE、報表、快取與診斷不會保存 API Key。

此功能是研究整理工具。文件、PDF、新聞與其他 evidence 都視為不可信資料，不能改變系統規則、讀取金鑰、執行命令或修改持股。引用不足時會顯示資料不足，而不是補成事實。

### 產業 / 概念股查詢

若你不是要找單一股票，而是想輸入一個產業或概念，請到「產業 / 概念股查詢」頁面。可輸入例如 `半導體`、`AI`、`AI伺服器`、`HBM`、`封裝`、`矽電容`、`CoWoS`、`CoPoS`、`TGV`、`CPO`、`矽光子`、`電動車`、`綠能`、`資安`、`雲端`、`金融`、`航運`。也可以輸入美股代號或公司名，例如 `TSM`、`NVDA`。

查詢流程：

1. 台股上市與上櫃會優先查詢 TWSE/TPEx 官方公開公司資料與交易所產業分類。
2. 熱門台股題材會使用內建概念題材對照，再用 TWSE/TPEx 線上公司資料確認股票代號、名稱、市場與交易所產業。
3. 美股會使用 yfinance 的線上搜尋與產業篩選。
4. 查到候選股票後，可自動更新前 N 檔股價與基本面，並寫入 `data/processed/stock_data.sqlite` 與 `data/processed/fundamentals_auto.csv`。
5. 本機 `data/sample/concept_stocks.csv` 只會在你勾選「線上來源失敗時才使用本機備援清單」時使用，不會被標示成線上資料。

目前內建的熱門題材包含：`PCB`、`記憶體`、`HBM`、`HBM供應鏈`、`封裝 / 先進封裝`、`矽電容`、`CoWoS`、`CoPoS`、`TGV`、`CPO / 矽光子`、`電源`、`低軌衛星`、`人形機器人`、`AI伺服器`、`電動車`、`綠能`、`資安`、`雲端`、`金融`、`航運` 等。

部分內建題材會在「備註」欄附上個股角色說明。例如輸入 `封裝` 時，系統會優先列出先進封裝、封測、載板、設備與測試相關候選股，並在日月光投控、台積電、欣興等個股旁標示其供應鏈角色。NVDA、AMD 這類美股若出現在封裝題材，會被標示為 `晶片設計 / 先進封裝需求端（非封裝代工）`，代表它們大量使用或參與封裝架構協同設計，不代表它們是 OSAT 封測廠。這些角色說明是研究索引，不代表完整名單，也不宣稱即時市占排名。

部分題材會顯示「股價反應階段」與「階段說明」。例如 `矽電容` 會標為 `初期觀察`，代表題材可能仍在市場認知、供應鏈驗證與營收落地的早期研究階段。這不是進場訊號，也不代表未來一定上漲；仍需檢查股價是否已提前反映、成交量是否異常、公司實際營收占比、量產時程與客戶認證。

輸入 `HBM` 時，系統會同時列出直接高頻寬記憶體製造商與相關供應鏈，但會在「關聯類型」欄標示 `直接製造商` 或 `供應鏈關聯（非直接 HBM 製造商）`。目前台股不會被標成 HBM 記憶體製造商；台股若出現，會以先進封裝、測試、載板、設備或材料供應鏈呈現。若只想看供應鏈，也可以輸入 `HBM供應鏈`、`CoWoS`、`先進封裝` 等較精確的關鍵字。

限制：交易所產業分類不等於完整概念股清單；內建題材對照是研究索引，可能漏列或需要更新；yfinance 免費資料也可能缺漏、延遲或分類不一致。若查到 `PNK`、`OTC` 等店頭或粉單標的，系統會保留結果但加上流動性與資訊揭露風險提示。查詢結果不是買賣建議。

### 全自動查詢 / 補資料

首頁與「AI 分析與評分」頁提供「全自動查詢 / 補資料」面板。輸入股票代號後，系統會依序執行：

1. 查詢本機 `data/processed/stock_data.sqlite`。
2. 如果沒有足夠股價資料，使用免費資料源自動下載股價並寫入 SQLite。
3. 嘗試用 yfinance 盡力補齊基本面與估值欄位。
4. 將自動抓到的基本面存到 `data/processed/fundamentals_auto.csv`。
5. 重新計算技術指標、基本面分數與綜合評分。

注意：自動基本面資料不保證所有股票都有完整欄位，也不保證資料即時或完全正確。缺少的欄位仍會保留空值，系統不會為了產生漂亮分數而補假資料。

目前可用的匯入指令範例：

```powershell
python -m stock_tool import-data --file data/sample/sample_tw_prices_for_indicators.csv --database data/processed/stock_data.sqlite
python -m stock_tool import-data --file data/cache/yfinance_2330.tw_1d_2024-06-21_2026-06-21.csv --database data/processed/stock_data.sqlite
```

匯入流程會做欄位檢查、日期轉換、重複資料處理與價格/成交量檢查；缺值會警告，不會默默補假資料。

CLI 不會連接券商，也不會自動下單。回測指令預設使用非零手續費、交易稅與滑價；正式研究時仍應依市場、券商與流動性條件自行調整參數。

本機設定可從範本複製：

```powershell
Copy-Item .env.example .env
```

`.env` 只保留本機設定，不要提交真實 API key 或敏感資訊。本專案第一階段不假設任何付費 API。

## Windows EXE 打包與啟動

### Windows 建置與個人發布流程

`build_exe.bat` 只會建立 `release\staging\StockTool\`，不會刪除或覆寫目前的正式
`release\StockTool\`。完成 staging 驗證後，再執行 `publish_release.bat`；它會先建立唯一時間戳的
`release\rollback\StockTool-pre-sprint12-release-YYYYMMDD-HHMMSS\` rollback 備份並驗證，再提升 staging 成品。
正式 EXE 路徑為 `release\StockTool\StockTool.exe`；v1.4.2 曾於 2026-09-03 核准為個人正式發布版，
目前本機正式目錄已於 2026-09-27 同步至 v1.4.3。發布前的
正式成品會保留在本次時間戳 rollback 目錄，promotion 過程中的舊正式版也會保留在非破壞性的
promotion hold。若 promotion 後的資產或 EXE 雜湊檢查失敗，腳本會將舊正式版恢復。
本次跨版本提升時，既有腳本的版本相依驗證在搬動檔案前擋下 1.4.2 舊正式目錄；
因此本次在分別驗證舊版與新版並建立 rollback 後，以受控的本機目錄切換完成提升。

正式使用者請點兩下 `release\StockTool\StockTool.exe`。工具的可變資料不在 release 資料夾：
預設位置是 `%LOCALAPPDATA%\StockTool\`，包含 `data\cache\`、`reports\`、`logs\`、
`portfolio.csv` 與 `watchlist.csv`。開發或隔離測試可用 `STOCK_TOOL_USER_DATA_DIR` 指向另一個
可寫目錄。請用視窗的 `Ctrl+C` 正常停止工具；若瀏覽器沒有自動開啟，請依 console 顯示的網址
手動開啟 `http://localhost:8501` 或 `8502`。

若 8501 已被使用，啟動器會改用 8502；兩者都被占用時，會顯示中文錯誤，並寫入
`%LOCALAPPDATA%\StockTool\logs\launcher_*_error.log`。外部免費資料來源可能失敗或延遲；畫面
會區分 `online`、`cache`、`sample`、`sqlite` 與 `partial/stale` 狀態，不會把快取資料標示成線上
最新資料。歷史績效不代表未來報酬，本工具不會自動下單，也不提供保證獲利或個人化投資建議。

v1.1.0 的 rollback package 與校驗碼位於 `release\baseline\`；依
`docs\release\v1.1-checklist.md` 的步驟停止程式後，再由具備 Windows 檔案權限的維護者執行回復。

Streamlit 儀表板入口檔案是：

```text
src/stock_tool/dashboard/app.py
```

若要建立 Windows onedir 版本，請先完成快速開始中的 venv 安裝，然後執行：

```powershell
.\build_exe.bat
```

打包腳本會：

- 使用 `.venv\Scripts\python.exe`。
- 安裝專案 dev 依賴，包含 `pyinstaller`。
- 清理舊的 `build/` 與 `dist/`。
- 使用 PyInstaller `--onedir` 建立 `StockTool.exe`。
- 複製 `README.md`、`.env.example`、`data/sample/`。
- 不建立或覆蓋 release 內的私人 `reports/`、`logs/`、portfolio、watchlist 或 cache；這些會在使用者資料目錄建立。

成品位置：

```text
release/StockTool/StockTool.exe
```

一般使用者啟動方式：

```text
點兩下 release/StockTool/StockTool.exe
```

啟動後會使用 `%LOCALAPPDATA%\StockTool\reports\` 與 `%LOCALAPPDATA%\StockTool\logs\`，啟動 Streamlit 本機服務，並嘗試開啟：

```text
http://localhost:8501
```

若 `8501` 被占用，launcher 會嘗試改用：

```text
http://localhost:8502
```

清理打包產物：

```powershell
.\clean_build.bat
```

### EXE 常見問題

- **Windows 防火牆提示**：Streamlit 只在本機啟動儀表板。若 Windows 詢問是否允許網路存取，通常允許私人網路即可；不需要開放到公用網路。
- **防毒誤判**：PyInstaller 打包的 EXE 有時會被防毒軟體誤判。請確認檔案來源是本機自行打包，必要時將 `release/StockTool/` 加入信任清單。
- **連接埠 8501 被占用**：啟動器會自動嘗試 `8502`。若兩個連接埠都被占用，請關閉既有 Streamlit 或其他本機服務後再啟動。
- **報表資料夾無法寫入**：請確認 `%LOCALAPPDATA%\StockTool\reports\` 對目前 Windows 使用者可寫入。可設定 `STOCK_TOOL_USER_DATA_DIR` 改用另一個可寫目錄。
- **錯誤紀錄**：EXE 會將 Streamlit 子行程輸出寫到 `%LOCALAPPDATA%\StockTool\logs\`。若 UI 沒有啟動，請先查看最新的 `streamlit_*.log` 與 `streamlit_*_error.log`。
- **EXE 啟動後瀏覽器沒打開**：可手動開啟 console 顯示的網址，例如 `http://localhost:8501` 或 `http://localhost:8502`。
- **不要放入敏感資訊**：`.env.example` 可以打包，真實 `.env`、API key、私人交易紀錄或未授權資料不應放入成品資料夾。

## 量化研究限制與防誤用

本專案是研究工具，不是投資顧問，也不會自動下單。回測與評分只能描述已輸入資料下的歷史結果，不能代表未來報酬。

使用時請特別注意：

- **前視偏誤**：策略訊號在 T 日產生，回測引擎最早只能在 T+1 的下一根 K 棒成交。基本面資料若用於策略，必須提供實際公告日或可得日，不可用財報期間日直接假設市場已知。
- **存活者偏誤**：若資料集只包含目前仍上市或仍被追蹤的股票，回測可能高估績效。研究多檔股票或選股策略時，應納入下市、變更代號、停止交易與當時成分股資料。本專案不會編造下市股資料，也不宣稱已完整解決存活者偏誤；若沒有提供歷史當下成分股名單或下市證券資料，回測報表會顯示中文風險提示。
- **過度擬合**：參數最佳化不代表穩健。建議保留樣本外期間，使用滾動前推測試或分段測試，並記錄所有嘗試過的參數組合。
- **基準比較**：回測結果應與合適基準比較，例如台股可使用加權指數、0050 或使用者自訂指數資料；美股可改用 SPY、QQQ 或對應產業 ETF。
- **交易成本**：手續費、交易稅、滑價與最低手續費都要依市場與券商條件設定。零成本假設只適合單元測試，不適合研究結論。
- **流動性限制**：目前第一階段未完整模擬掛單深度、漲跌停、部分成交限制與停牌。成交量不足或價格異常時，應降低研究結論可信度。

## 資料匯入

第一階段支援 CSV 與 Excel 股價資料匯入，並統一成標準欄位：

```text
date
symbol
open
high
low
close
volume
adjusted_close
```

必要欄位為 `date`, `symbol`, `open`, `high`, `low`, `close`, `volume`。`adjusted_close` 可缺省，系統會保留為空值，不會自行補假資料。

範例 CSV 位於：

```text
data/sample/sample_tw_prices.csv
```

### Python 使用範例

```python
from stock_tool.data.cleaner import clean_price_data
from stock_tool.data.loader import load_csv
from stock_tool.data.storage import SQLitePriceStorage

rows = load_csv("data/sample/sample_tw_prices.csv")
cleaned = clean_price_data(rows)

storage = SQLitePriceStorage("data/processed/stock_data.sqlite")
storage.save_price_data(cleaned.records)

print(f"saved rows: {len(cleaned.records)}")
print(f"warnings: {len(cleaned.warnings)}")
```

### Excel 匯入範例

```python
from stock_tool.data.loader import load_excel

rows = load_excel("data/raw/prices.xlsx", sheet_name="prices")
```

Excel 匯入需要安裝 `openpyxl`。若未安裝，系統會拋出明確錯誤，不會靜默失敗。

### 資料來源介面

資料來源可透過資料來源介面替換。第一階段提供本機 CSV 與 Excel 資料來源，未來可新增 API 資料來源，但不會在程式中假設 API 一定存在。

```python
from stock_tool.data import provider_for_file

provider = provider_for_file("data/sample/sample_tw_prices.csv")
rows = provider.load_price_data()
```

若使用者有自行整理的歷史成分股、下市股或當時可交易 universe 資料，可透過 `point_in_time_universe` 參數保留 metadata。這只是架構預留，不會自動補齊缺少的下市股票或歷史成分股。

```python
provider = provider_for_file(
    "data/sample/sample_tw_prices.csv",
    point_in_time_universe="data/raw/historical_universe.csv",
)
```

## 自動抓資料與快取

工具提供免費公開資料抓取功能，目前第一順位使用 `yfinance`。如果 yfinance 失敗，會依序嘗試 FinMind（需要 `FINMIND_TOKEN` 且目前只用於台股）與本機快取。如果仍沒有可用資料，系統會用可讀訊息列出每個 provider 的安全診斷資訊，並建議改用 CSV 上傳，不會補假資料。

快取位置（EXE 與預設開發流程）：

```text
%LOCALAPPDATA%\StockTool\data\cache\
```

Python 範例：

```python
from stock_tool.data.auto_fetch import fetch_prices

result = fetch_prices(
    "2330",
    market="TWSE",
    start="2024-01-01",
    use_cache=True,
)

print(result.data.tail())
print(result.from_cache)
print(result.cache_file)
```

市場參數：

- `TWSE`：台股上市，例如 `2330` 會轉成 yfinance query symbol `2330.TW`。
- `TPEX`：台股上櫃，例如 `6488` 會轉成 yfinance query symbol `6488.TWO`。
- `US`：美股，例如 `AAPL` 會維持 `AAPL`。

若使用者已輸入 `2330.TW` 或 `6488.TWO`，系統不會重複加上副檔名。

資料來源選項：

- `auto`：依 registry 的固定相容順序嘗試 yfinance、適用時的 FinMind、快取。
- `yfinance`：只嘗試 yfinance，失敗後使用快取。
- `finmind`：只嘗試 FinMind，失敗後使用快取；需要 `.env` 或環境變數設定 `FINMIND_TOKEN`。
- `cache`：優先讀取本機快取；若使用強制重新整理，會先嘗試線上資料，再在失敗時依政策使用可標示的過期備援快取。

自動抓資料的限制：

- 免費公開來源可能缺少部分台股、美股、ETF 或歷史區間。
- 快取會保留 provider、查詢代號、市場、日期區間、取得時間與最後資料日；快取狀態為 fresh、stale、expired、corrupt 或 missing。損毀與過期快取不會被靜默當成新資料。
- 可在新版六項主導航的「研究庫」工作區查看「資料與證據中心」：實際查詢代號、提供者、資料來源、資料日期、列數、品質、快取狀態、嘗試與備援紀錄，以及本次 runtime 的 Provider Health。
- 「強制重新整理」會先嘗試線上資料；若只能使用過期快取，畫面會明確標示為研究備援資料。
- CSV 上傳與範例資料會保留各自來源，不會被標示成線上下載或快取。
- 研究結論仍應保留資料來源、日期範圍與清洗警告。

## 資料清洗規則

資料清洗會執行：

- 檢查必要欄位是否缺少。
- 自動轉換日期格式為 `YYYY-MM-DD`。
- 移除同一 `date` + `symbol` 的重複資料，保留第一筆並提出警告。
- 檢查 `open`, `high`, `low`, `close` 是否為正數且為有限數值。
- 檢查 `high` 是否小於 `low`。
- 檢查 `high` 是否低於 `open` 或 `close`。
- 檢查 `low` 是否高於 `open` 或 `close`。
- 檢查 `volume` 是否為負數。
- 對缺值提出警告，不補假資料。

## 儲存

目前使用 SQLite 作為本機資料儲存：

```text
data/processed/stock_data.sqlite
```

資料表名稱為 `prices`，主鍵為 `date` + `symbol`。未來可在不改動分析層的前提下新增 DuckDB 或 API provider。

## 技術指標

技術指標函式位於 `stock_tool.indicators`。所有函式都接受 `pandas.DataFrame`，回傳新的 DataFrame，不修改原始資料。若資料中有 `symbol` 欄位，會依股票分組計算；若有 `date` 欄位，會先依日期排序後再做 rolling / EMA 計算，避免不同股票或未來資料混入。

```python
import pandas as pd

from stock_tool.indicators import (
    add_atr,
    add_bias,
    add_bollinger_bands,
    add_ema,
    add_macd,
    add_rolling_return,
    add_rolling_volatility,
    add_rsi,
    add_sma,
    add_stochastic_oscillator,
    add_volume_moving_average,
)

prices = pd.read_csv("data/sample/sample_tw_prices.csv", dtype={"symbol": str})

result = add_sma(prices)
result = add_ema(result)
result = add_rsi(result)
result = add_macd(result)
result = add_bollinger_bands(result)
result = add_atr(result)
result = add_stochastic_oscillator(result)
result = add_volume_moving_average(result)
result = add_bias(result)
result = add_rolling_return(result, periods=(5, 20))
result = add_rolling_volatility(result, periods=(5, 20))
```

也可以直接執行範例：

```bash
python examples/indicator_usage.py
```

已支援的第一階段指標：

- SMA：預設 5、10、20、60、120、240 日。
- EMA：預設 12、26 日。
- RSI：預設 14 日。
- MACD：預設 12、26、9，輸出 `macd_dif`, `macd_dea`, `macd_histogram`。
- Bollinger Bands：預設 20 日、2 倍標準差。
- ATR：預設 14 日。
- KD / Stochastic Oscillator：預設 9、3、3。
- 成交量均線：預設 5、20 日。
- 乖離率：預設 5、10、20、60、120、240 日。
- 近 N 日報酬率。
- 近 N 日波動率。

## 策略模組

策略位於 `stock_tool.strategies`，所有策略都繼承 `StrategyBase`，並提供：

- `name`
- `parameters`
- `generate_signals()`
- `validate_parameters()`
- `description`
- `risk_notes`

策略輸出的 `signal` 只使用三種值：

- `1`：買入研究訊號。
- `0`：持有或無動作。
- `-1`：賣出研究訊號。

策略訊號可直接送入 `BacktestEngine`，引擎會維持 T 日產生訊號、T+1 或下一根可用 K 棒成交的規則。

```python
import pandas as pd

from stock_tool.backtest import BacktestEngine, BrokerConfig
from stock_tool.strategies import BreakoutStrategy

prices = pd.read_csv("data/sample/sample_tw_prices_for_indicators.csv", dtype={"symbol": str})
strategy = BreakoutStrategy(lookback=10, high_col="close", low_col="close", target_percent=0.5)
signals = strategy.generate_signals(prices)

benchmark = prices[["date", "close"]].copy()
engine = BacktestEngine(
    initial_cash=1_000_000,
    max_position_pct=0.5,
    broker_config=BrokerConfig(
        commission_rate=0.001425,
        tax_rate=0.003,
        slippage_rate=0.001,
        execution_price_col="open",
    ),
)
result = engine.run(prices, signals, benchmark=benchmark)

print(result.metrics)
```

可執行策略比較範例：

```bash
python examples/strategy_usage.py
```

### Sprint 12 策略健檢

「策略」工作區保留既有的單次回測，並新增研究用途的「策略健檢」。它使用唯一的
`stock_tool.strategies.registry` 管理目前六種既有策略，不會自動新增、挑選或套用策略。
健檢會在同一份已載入資料、相同交易成本與既有次一根 K 棒成交模型下，分別顯示：

- 依日期順序切分的樣本內與樣本外結果；樣本外交易只計入樣本外期間，允許的技術指標 warm-up 不會計入樣本外績效。
- expanding 或 rolling walk-forward 的個別 fold，預設最多 10 個，不會把各 fold 合併成單一漂亮數字。
- Registry 明確允許的鄰近參數敏感度，預設最多 25 種組合；部位大小、初始資金、手續費、稅費與滑價不是可掃描參數。
- 資料不足、零交易、fold 不足與單一參數尖峰等結構化限制。單一尖峰只會標示「可能對參數過度敏感」，不代表其他參數或未來期間必然失效。

基本面成長策略的健檢一律要求 `available_date`；缺少可得日期時會顯示資料不足，而不會用
`fiscal_period` 或未知日期提前使用資料。這些結果僅用於研究策略穩健性，不構成任何買賣建議，
也不會改變既有單次回測、使用者持股或策略參數。

範例輸出會寫入：

```text
data/sample/sample_strategy_performance.csv
```

## 基本面分析與評分

第一階段基本面資料支援 CSV 匯入，不假設有 API。標準欄位如下：

```text
symbol
fiscal_period
revenue
revenue_growth_yoy
eps
eps_growth_yoy
gross_margin
operating_margin
net_margin
roe
roa
debt_ratio
operating_cash_flow
free_cash_flow
pe_ratio
pb_ratio
dividend_yield
```

基本面評分總分為 100 分：

- 成長性 25 分。
- 獲利能力 25 分。
- 財務安全 20 分。
- 估值合理性 20 分。
- 現金流品質 10 分。

資料不足時，對應分項會標示為「資料不足」，總分也會標示為「資料不足」，不會用缺漏資料硬算精準分數。分數只作為研究參考，不是買賣建議。

```python
from stock_tool.fundamentals import load_fundamentals_csv, score_fundamentals

fundamentals = load_fundamentals_csv("data/sample/sample_fundamentals.csv")
scores = score_fundamentals(fundamentals)

print(scores)
```

範例評分輸出位於：

```text
data/sample/sample_fundamental_scores.csv
```

若需要產業調整，可透過 `IndustryScoringProfile` 與 `MetricRule` 覆寫特定產業的門檻。

## AI 分析與綜合股票評分

儀表板新增「AI 分析與評分」頁面。這裡的 AI 摘要是本機規則式摘要，不呼叫外部 AI API、不需要 API key、不預測明天漲跌，也不提供個人化投資建議。所有分數都會列出原因、缺漏資料與風險限制。

綜合股票評分使用 0 到 100 分架構：

- 技術面 30%：均線趨勢、MACD、RSI、20 日報酬等。
- 基本面 30%：由成長性、獲利能力、財務安全與現金流品質換算。
- 估值面 20%：使用基本面評分中的 valuation score。
- 風險面 20%：使用最大回撤、20 日波動率、ATR/收盤價與最近回測風險。

若基本面或估值資料尚未匯入，全資料總分會顯示「資料不足」，不會硬算精準總分；頁面會另外顯示「研究分數」與資料覆蓋率，方便先檢查技術面與風險面。估值面若已取得 PE / PB，但缺少股利殖利率，系統會保守計算可用估值分數，並在缺漏資料中標示 `dividend_yield`，不會默默補假資料。

「分數原因」會依技術面、基本面、估值面與風險面分項顯示優點與缺點 / 需要檢查項目，讓使用者知道分數是由哪些條件加分、哪些條件拖累或缺資料。

Research Workspace 與既有分析頁會顯示「情境參考區間（研究用，非投資建議）」。區間由已載入日線資料推估，主要參考 20 日均線、60 日均線、近 20 日高低點與 ATR，並揭露計算基準日、假設、突破觀察值與風險參考值。它不是個人化買進建議，也不代表一定能成交或獲利；實際交易仍需考慮隔日開盤、滑價、手續費、交易稅、流動性與個人風險承受度。

## Research Workspace

新版「研究首頁」在成功搜尋後會進入 Research Workspace，將公司介紹、價格與成交量圖、既有綜合評分、基本面、主要風險、情境參考區間及資料來源集中在同一份唯讀研究快照。快照會分開標示「事實資料」、「研究計算」與「研究推論」；若基本面、公司資料或完整評分不足，畫面會保留可用資料、顯示 coverage 與缺少項目，不會補成完整分數。

圖表支援 6M、1Y、3Y、MAX，以及 SMA20／SMA60。資料有完整 OHLC 時使用 K 線；只有收盤價時會安全降級為收盤價走勢；缺成交量時不會繪製假成交量。圖表僅使用已載入資料，不宣稱即時行情。

Python 範例：

```python
from stock_tool.stock_scoring import score_stock, score_components_frame
from stock_tool.entry_reference import estimate_entry_reference

result = score_stock(
    symbol="2330",
    price_data=prices,
    technical_indicators=indicators,
    fundamental_scores=fundamental_scores,
    backtest_result=backtest_result,
)

print(result.total_score)
print(result.summary)
print(score_components_frame(result))

scenario = estimate_entry_reference(prices, indicators, symbol="2330")
print(scenario.reference_price, scenario.zone_low, scenario.zone_high)
```

### 公司業務脈絡摘要

「AI 分析與評分」頁面包含「公司業務脈絡」頁籤，用於回答：

- 公司主要在做什麼。
- 技術特點或產品觀察重點。
- 連結到哪些產業或題材。
- 目前可能應用在哪些市場。
- 未來可能應用在哪些方向。
- 主要瓶頸與需要補充查證的問題。

資料來源與限制：

- 公司名稱、產業與描述第一順位使用 yfinance 公司基本資料。
- 題材關聯使用本機規則式對照，例如半導體、PCB、記憶體、電源、低軌衛星、人形機器人、AI 伺服器等。
- 若可辨識更細的產品或供應鏈角色，會優先顯示更貼近公司的技術重點，例如 MU 的 HBM / AI 記憶體、SNDK 的 NAND / SSD 儲存、機器人供應鏈中的減速器、伺服控制、工業電腦或整機平台。
- 摘要是研究脈絡整理，不代表營收占比、訂單保證或投資結論。
- 若 yfinance 沒有公司描述，系統會顯示資料不足，不會為了完整摘要而編造。

### Serenity 供應鏈瓶頸小 Agent

「AI 分析與評分」頁面新增「Serenity 小 Agent」頁籤。這不是外部 AI API，也不會讀取 Codex skill runtime；它是把 Serenity / @aleabitoreddit 風格的供應鏈瓶頸研究框架轉成可測試的本機規則引擎。

小 Agent 會整合：

- 公司業務脈絡與技術特點。
- 已載入股價與技術指標。
- 綜合股票評分中的資料覆蓋率、風險面與基本面 / 估值缺口。
- 使用者匯入的研究報告 PDF 摘要。

輸出內容包含：

- 研究匹配度與信心標籤。
- 供應鏈瓶頸強度。
- 架構遷移關聯，例如 HBM、CPO、先進封裝、800V 電力、人形機器人等。
- 證據品質與缺口。
- 催化與股價反應階段。
- 財務轉換品質。
- 風險、失效條件與下一步查證問題。

限制：

- 社群貼文、第三方摘要與題材關鍵字只能當線索，不是證據。
- 若缺少年報、法說、公司公告、客戶認證、量產、訂單、股本稀釋或市場占有率資料，會列在「證據缺口」。
- 研究匹配度不是買賣建議，也不是預測報酬。
- 對小型股或熱門題材，仍需另外檢查流動性、股本膨脹、可轉債、認股權證、放空比例與題材擁擠。

### 研究報告 PDF 摘要

儀表板新增「研究報告摘要」頁面，可匯入你已有權使用的 PDF 研究報告，或在本機版輸入 PDF 路徑，例如：

```text
D:\Downloads\矽力-KY 分析.pdf
```

系統會在本機抽取 PDF 文字並產生保守摘要，包含：

- 研究重點
- 主要業務
- 技術特點
- 產業連結 / 應用場景
- 可能催化
- 瓶頸 / 需要驗證
- 估值觀察
- 風險
- 資料限制

匯入摘要後，「AI 分析與評分」頁的「研究報告」分頁會顯示同股票代號的報告摘要，方便把股價、基本面、技術面與研究報告放在同一個研究流程中檢查。

注意：

- 此功能是本機規則式摘要，不呼叫外部 AI API。
- 不會自動抓取或重製付費券商報告；頁面只提供公開資料搜尋連結。
- 掃描圖片型 PDF 目前不做 OCR，可能會顯示資料不足。
- 摘要會壓縮原文內容，數字、評等與假設請回到原始 PDF 核對。
- 報告摘要不是買賣建議，也不代表未來報酬。

## 自選股、篩選器與投資組合

### 產業 / 概念股查詢

這個頁面用於從產業或概念反查候選股票，並依市場分類為台股上市、台股上櫃與美股。查詢成功後，可把候選股加入自選股，或直接更新股價與基本面供後續 AI 分析、篩選器與回測使用。

目前資料來源：

- TWSE OpenAPI：台股上市公司基本資料與交易所產業分類。
- TPEx OpenAPI：台股上櫃公司基本資料與交易所產業分類。
- yfinance：美股線上搜尋與產業篩選。
- `data/sample/concept_stocks.csv`：可選的本機備援，不是主要資料源。

### 自選股清單

自選股儲存在：

```text
%LOCALAPPDATA%\StockTool\data\watchlist.csv
```

Python 範例：

```python
from stock_tool.watchlist import add_watchlist_symbol, load_watchlist, save_watchlist

watchlist = load_watchlist()
watchlist = add_watchlist_symbol(watchlist, symbol="2330", market="TW", note="研究觀察")
save_watchlist(watchlist)
```

### 股票篩選器

篩選器使用已計算好的技術指標資料，取每檔股票最新一列進行篩選。若指定條件需要的欄位不存在，結果會附上警告，不會假裝已完成篩選。

```python
from stock_tool.screener import ScreenerCriteria, screen_stocks

result = screen_stocks(
    indicators,
    ScreenerCriteria(min_volume=1_000_000, min_return_20d=0.05, max_volatility_20d=0.30),
)

print(result.matches)
print(result.warnings)
```

### 投資組合管理

投資組合為手動持股紀錄，用於部位、市值與未實現損益追蹤；它不會連接券商，也不會下單。

儲存位置：

```text
%LOCALAPPDATA%\StockTool\data\portfolio.csv
```

```python
from stock_tool.portfolio_management import (
    add_portfolio_position,
    load_portfolio,
    portfolio_summary,
    save_portfolio,
)

portfolio = load_portfolio()
portfolio = add_portfolio_position(
    portfolio,
    symbol="2330",
    quantity=37,
    average_cost=600,
    market="TWSE",
    note="零股持股，單位為股",
)
save_portfolio(portfolio)
summary = portfolio_summary(portfolio, latest_prices)
```

投資組合管理的持股數量以「股」為單位，支援台股零股。`quantity=37` 代表 37 股，不是 37 張；若要記錄 1 張台股，請輸入 1000 股。

### Portfolio Ledger Foundation

`stock_tool.portfolio.ledger` 提供獨立、不可變且以 `Decimal` 計算的帳務核心。它可重播明確的買賣、入出金、股利、費用、稅費與 FX 轉換，並以 `market + symbol` 區分不同市場的相同代號。Sprint 14 固定採 average-cost policy；不支援的交易、超賣、重複 `entry_id`、缺少 FX 或缺少價格都不會被靜默補值。

既有 `portfolio.csv` 只有彙總持倉，沒有歷史交易明細，因此只能透過唯讀 `opening_position` import 作為期初部位。此 import 不會推測舊交易、不會建立虛構現金流，也不會覆寫原始 CSV；期初以前的已實現損益會明確標示為資料不足。Ledger 尚未接入 Dashboard 或正式 runtime migration。

投資組合頁會先使用目前 session 與 runtime SQLite 中最新的有效資料，不會在畫面重整時自動連網。按下「更新並分析持股」後，系統會逐檔補齊缺少或已過期的價格／歷史資料、盡力取得基本面、重算既有指標與研究分數，並更新健康度與本機規則式摘要。單檔失敗不會中斷其他持股；每筆結果會保留資料來源、實際查詢代號、最後資料日與更新時間。未確認市場的 AUTO／CUSTOM 持股不會被猜測，會明確顯示需要人工確認。

投資組合健康度頁面會要求價格與市場身份都可辨識；舊版 SQLite `prices` 表沒有市場欄位，因此不會被猜成 TWSE、TPEX 或 US。混合 TWD/USD 持股會依序嘗試線上 USD/TWD、未過期的 runtime FX cache、使用者在「進階設定／資料備援」明確提供的手動匯率；全部失敗時只顯示各幣別原生摘要，不合併總市值或權重，也不會以 1.0 補值。匯率會分別顯示市場資料日期（`effective_at`）與下載／快取時間（`fetched_at`）：快取 TTL 只依下載／快取時間判斷，市場資料是否明顯過舊則依獨立、保守的資料日期政策顯示警告；過期或損毀快取不會被靜默當成最新資料。

健康度分數由集中度、風險、既有股票研究結果與資料可信度構成，所有構面會顯示分數、權重、貢獻、原因、警示與 evidence。資料涵蓋率低於門檻時，整體健康度顯示「資料不足」，不會補出精準分數。壓力測試是使用者指定假設的 deterministic arithmetic scenario，不是價格預測。

## 投資風險控制

風控工具位於 `stock_tool.risk`，可設定單一股票最大持倉比例、單一交易最大虧損、總持股數上限、現金水位、最大回撤、波動率、連續虧損與產業集中度限制。`RiskConfig` 不允許 `max_position_pct=1.0`，避免滿倉單一股票。

```python
from stock_tool.risk import RiskConfig, RiskManager

config = RiskConfig(
    max_position_pct=0.25,
    max_trade_loss_pct=0.01,
    max_positions=10,
    min_cash_ratio=0.05,
)
risk_manager = RiskManager(config)
```

`BacktestEngine` 在每筆 pending order 送入模擬 broker 前會先經過 `RiskManager` risk gate。買單會檢查現金、單一股票持倉比例、最大持股數、現金水位與單筆交易風險；賣單會檢查是否有足夠持股。若風控拒絕，訂單會留在 `rejected_orders`，不會產生成交紀錄。

沒有足夠資料的規則不會假裝完成。例如產業集中度需要傳入 `industry_map`；未提供時不會臆測股票產業。停損、固定停利與移動停利都採保守日線模型：T 日收盤後產生風控訊號，最早在 T+1 下一根 K 棒依設定的成交價格模型成交。

移動停利可透過 `BacktestEngine(trailing_stop_pct=0.10)` 或 CLI `--trailing-stop-pct 0.10` 啟用。引擎會在持倉後記錄持倉以來最高收盤價；若 T 日收盤價自最高收盤價回落達設定比例，T 日只產生 `trailing_stop` 賣出訊號，實際成交最早發生在 T+1。此模型只使用截至 T 日收盤可得的資料，不使用 T+1 或更晚資料判斷 T 日訊號。

`PositionSizer` 支援：

- 固定金額部位。
- 固定比例部位。
- 根據 ATR 的波動率部位。
- 根據最大虧損的部位計算。

## 報表輸出

報表模組位於 `stock_tool.reports`，支援 Excel 與 HTML。Excel 會建立以下工作表：

```text
摘要
股價資料
技術指標
基本面評分
回測結果
交易紀錄
資金曲線
風險提示
參數
```

HTML 報表包含價格圖、資金曲線、回撤曲線、交易紀錄、指標摘要與風險提示。資料不足時會顯示「資料不足」，並固定包含「歷史績效不代表未來報酬」聲明。若報表包含回測結果，但沒有提供 `point_in_time_universe`，風險提示會加入存活者偏誤警告；這代表資料限制尚未解除，不代表系統已修正該偏誤。

可執行 sample report：

```bash
python examples/report_usage.py
```

輸出位置：

```text
reports/sample_stock_report.xlsx
reports/sample_stock_report.html
```

## Streamlit 儀表板

啟動本機儀表板：

```bash
streamlit run src/stock_tool/dashboard/app.py
```

### Sprint 4 工作區

預設儀表板使用六個主要工作區，讓研究流程與既有工具有一致入口：

1. **研究首頁**：每天先查看持股、自選股與研究資料的重點，再從股票代號與市場開始研究。
2. **探索**：產業／概念股查詢、股票篩選器與自選股清單。
3. **策略**：策略回測與其既有參數、成本及風險設定。
4. **持倉**：投資組合管理、估值、健康度與壓力測試。
5. **研究庫**：研究報告摘要、既有分析輸出與報表下載。
6. **設定**：資料匯入、自動抓資料與資料來源相關操作。

每個工作區先顯示用途、使用前資料需求與明確操作入口，再以「此工作區功能」快速切換對應的既有功能；Sprint 4.1 沒有移除任何既有研究、回測、風控或報表功能。

### 開始研究與資料狀態

- 在「研究首頁」輸入股票代號後，必須明確選擇市場：`TWSE`、`TPEX` 或 `US`。這可避免把相同代號誤解為不同市場的股票。
- 每日首頁只使用本機已載入的持股、自選股、價格、基本面與研究快照建立「今日關注」。每個提醒會附資料依據與資料日期；缺少價格、匯率或基本面時會顯示「資料不足」，不會補成假數字。
- 「更新今日資料」必須由使用者主動按下，最多更新持股與自選股中的前 20 個市場別股票。每檔仍沿用既有 provider fallback 與快取契約；單檔失敗不會中斷其他更新，也不會修改持股或自選股檔案。
- Daily Research Loop 只會在一次完整的手動更新成功後，將衍生的 Daily Brief 快照保存到使用者 runtime 的 `data/daily_research/`。下次啟動會先顯示上次成功檢查與資料時間；相同資料不會製造假變化，部分更新或資料可能過期時會保留前次成功摘要並明確標示，不會把舊資料冒充最新資料。首頁最多列出三項由確定性規則排序的變化，每項均附資料來源、資料時間與下一步研究或資料修復入口。
- 「繼續研究」會保留最近的市場別研究快照。它是本機工作階段的續接入口，不代表即時行情、新聞或買賣建議。
- 搜尋使用表單提交，按 Enter 或按「開始研究」只會執行一次；切換工作區不會重新下載相同請求。使用者主動再次提交相同代號與市場時，系統會建立新的提交並允許重試。
- 畫面會明確標示首次使用、更新中、部分資料可用、資料就緒、資料可能過舊或更新失敗。資料不足時不會把結果顯示成完整分析。
- 供應商或網路的技術細節會寫入本機錯誤紀錄；畫面只顯示可理解且不含敏感資訊的說明。
- 首頁只讀取本機持股與自選股的筆數，不顯示私人明細。檔案不存在或無法安全讀取時會顯示「資料不足」；真正的空清單才會顯示 `0`。

### Legacy dashboard／診斷模式

若新版工作區發生問題，可到「設定」的 **Legacy dashboard／診斷模式** 卡片，暫時回到 Sprint 4 前的完整頁面清單。此模式僅供相容性診斷；側欄的「返回新版工作區」可立即切回新版 Shell。

使用者可以上傳 CSV、使用免費公開來源抓取資料、依產業或概念查詢候選股、維護自選股、匯入 PDF 研究報告摘要、篩選股票、查看 AI 摘要與綜合評分、手動管理持股、選擇策略、調整策略參數、設定交易成本與滑價、查看資金曲線與最大回撤，並下載 Excel 報表。資料不足時會顯示「資料不足」或明確提示。

## 測試

```bash
python -m pytest
```

目前測試涵蓋：

- CSV 匯入。
- Excel 匯入。
- 資料來源介面。
- CLI 基本執行。
- 缺少欄位檢查。
- 日期轉換。
- 重複資料移除。
- 不合理 OHLC 價格檢查。
- 負成交量檢查。
- 缺值警告。
- SQLite 儲存與讀取。
- 自動抓資料標準化與 data/cache 快取。
- 自動抓資料失敗時不產生假資料。
- 產業 / 概念股線上查詢與市場分類。
- 自選股清單新增、移除與儲存。
- 股票篩選器缺欄位警告。
- 綜合股票評分四分項權重。
- AI 摘要與策略健檢不輸出保證語句。
- 手動投資組合市值與未實現損益計算。
- 啟動器錯誤紀錄路徑。
- 技術指標計算。
- 技術指標不修改原始資料。
- 技術指標依 `symbol` 分組，不跨股票計算。
- 技術指標不足資料時輸出 `NaN`。
## 台股代號自動修正

自動抓資料會保留使用者選擇的市場作為第一順位，但台股數字代號會自動嘗試上市與上櫃兩種 yfinance 後綴：

- 選 `TWSE` 並輸入 `3105` 時，會先查 `3105.TW`，若沒有資料會自動再查 `3105.TWO`。
- 選 `TWSE` 並輸入 `6207` 時，同樣會在 `.TW` 無資料後自動改查 `.TWO`。
- 選 `TPEx` 時順序相反，會先查 `.TWO`，再視需要嘗試 `.TW`。
- 美股代號例如 `AAPL` 不會被加上台股後綴。

如果系統自動改用另一個後綴，儀表板會顯示實際命中的查詢代號。這只是資料來源代號修正，不代表投資建議。
## 基本面資料身分與期間語意（Sprint 5.2.2）

- 基本面資料以 `symbol + market` 識別公司；支援的正式市場為 `TWSE`、`TPEX` 與 `US`。
- 舊 CSV 若沒有 `market`，系統會保留為 `UNKNOWN`，不會自行猜測或把同代號跨市場資料混在一起。
- 自動下載的基本面會保存 `market`、`period_type`、`as_of_date`、`source` 與 `provider_symbol`。
- `period_type=mixed` 表示該列同時使用目前/TTM 指標與最新可得財報欄位；`fiscal_period` 不等於資料公開日。
- 研究首頁只接受市場身分相符的基本面與評分。若只有舊的 `UNKNOWN` 資料，會重新嘗試取得該市場資料，不會把舊資料顯示成完整結果。
- 自動基本面仍屬 best-effort 研究資料；使用歷史基本面進行回測時，必須另有實際公告日或可得日資料，避免前視偏誤。

## Sprint 7 Research Storage

Sprint 7 adds an additive SQLite research-storage boundary. It is not a new
Dashboard workflow: current UI behavior, providers, scores, and backtests are
unchanged. `ResearchRepository` is the supported data-layer API for persisted
fundamentals, company profiles, concept knowledge/relations, and research
document metadata. Callers provide a market-qualified `ResearchIdentity`; a
symbol alone never causes a market to be inferred.

```python
from stock_tool.data.repositories import (
    FundamentalRecord,
    ResearchIdentity,
    ResearchProvenance,
    ResearchRepository,
)

repository = ResearchRepository("C:/safe-runtime/data/processed/research.sqlite")
repository.upsert_fundamental(
    FundamentalRecord(
        identity=ResearchIdentity("MU", "US"),
        fiscal_period="2025FY",
        period_type="annual",
        as_of_date="2025-12-31",
        metrics={"revenue": 1.0, "eps": 1.0},
        provenance=ResearchProvenance(
            provider="fixture",
            source_type="fixture",
            provider_symbol="MU",
            source_url=None,
            fetched_at="2026-07-14T00:00:00+00:00",
            updated_at="2026-07-14T00:00:00+00:00",
        ),
    )
)
```

`SQLitePriceStorage.initialize()` applies ordered migrations recorded in
`schema_migrations`. New migrations are additive only. Before a pending
migration upgrades an existing SQLite database, StockTool creates a sibling
`*.pre-migration-*.sqlite` backup. Migration statements run in one transaction;
on failure the transaction is rolled back and the backup is restored. The
system does not drop unknown tables or overwrite malformed/corrupt databases.

Research document records have no dedicated raw-content field and are intended
for metadata plus a content hash. Sprint 7.1 does not inspect arbitrary
metadata values for raw private document content, so callers must not place raw
private source text in document metadata.

Runtime research databases belong under the user runtime root, normally
`%LOCALAPPDATA%\\StockTool\\data\\processed\\`. They must not be placed in
`release/`, `data/sample/`, or a source archive. Test and release verification
use only temporary isolated runtime directories; no real portfolio, watchlist,
or runtime SQLite database is used by automated tests.

## Sprint 11 Point-In-Time Research

Historical-universe CSV imports use this local contract:

```text
symbol,market,effective_from,effective_to,status,source,dataset_completeness
2330,TWSE,2024-01-01,,listed,local_import,partial
```

`market` is required and is canonicalized with the existing `Symbol` / `Market`
contract. `dataset_completeness` must be `complete`, `partial`, or `unknown`.
`delisted_placeholder` records a known data gap; it is not evidence of complete
delisted-security coverage. The bundled `data/sample/historical_universe_synthetic.csv`
is a small deterministic fixture, not a complete historical universe.

For historical fundamental strategy inputs, include `filing_date`,
`available_date`, and `source`. Strict point-in-time mode uses only rows whose
`available_date` is on or before the decision date. A missing `available_date`
is excluded in strict mode. Legacy mode remains available for compatibility but
emits an explicit look-ahead/survivorship limitation warning. Neither mode
claims that survivorship bias is resolved without a complete, verifiable
point-in-time universe and delisted-security dataset.

## Sprint 9 題材證據與 PDF 引用

題材探索使用市場限定的 canonical relation：`concept_key + symbol + market + relation_type`。
每筆關係另外保存 evidence、單一 0 到 1 的 confidence、source_name、source_url、verified_at
與 dataset_version。UI 依 confidence 顯示高（>= 0.75）、中（>= 0.50）與低，缺少 evidence
或 source URL 的關係不會顯示為高信心。`manual_seed` 會明確顯示為人工種子，缺少驗證日期時
顯示「尚未驗證」，過期關係不會顯示為最新資料。

版本化的內建樣本位於 `data/sample/concepts/`，首次沒有任何 canonical concept 資料時才會載入
runtime SQLite。它是研究索引，不會覆寫既有資料，也不代表完整或已驗證供應鏈。原有
`data/sample/concept_stocks.csv` 與 `concepts.py` 保留為 legacy compatibility input；它們的
規則式提示不得被當作已驗證的公司—題材關係。

研究報告 PDF 僅在本機 session 抽取，摘要重點可回到一頁以上的 citation（頁碼、頁內 offsets
與有限原文片段）。掃描型或無可擷取文字的 PDF 會顯示 OCR 未支援；系統不會把私人 PDF 原文
收入 release、source archive 或 research document metadata。

## Sprint 30 Prediction Lab（Phase 0）

「預測評估實驗室（實驗）」是每日研究流程中的唯讀、確定性樣本登錄區，
不是預測器，也不提供買賣建議。它只重用已驗證的官方盤後排名，為每個已知
市場建立 Top／Middle／Bottom 的 5 與 20 個交易日樣本，並在未來實際資料
可用時追加 append-only outcome。每個 PredictionRecord 與 PredictionOutcome
都有 market-qualified identity、來源 hash、規則版本及 semantic/exact
fingerprint；immutable records 是權威資料，index 只是可重建 projection。

只有成功且完整的每日研究快照才會登錄樣本。partial、offline、stale、
unavailable 或資料不足會保留說明但不建立假樣本。所有資料只寫入隔離的
StockTool runtime root，不會修改 Portfolio、Watchlist、Research Library，
也不會呼叫新的 provider、AI、排程或背景服務。外部文章或市場倍增敘述不屬於
本實驗的證據。
