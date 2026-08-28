# Stock Analysis Tool v1.0 Product Whitepaper

審查日期：2026-07-10  
審查範圍：`README.md`、`pyproject.toml`、`src/`、`tests/`、`data/`、`reports/`、`dashboard`、EXE launcher/build scripts。  
審查角色：Principal Software Architect、Senior Quantitative Research Engineer、Financial Data Engineer、Senior Product Manager、Senior UI/UX Designer、QA Lead、Windows Desktop Engineer。  
審查限制：本文件只做產品級審查與規劃，未修改任何程式碼，也未新增產品功能。

## Executive Summary

目前專案已經超過一般 side project：資料匯入、自動抓股價、技術指標、基本面評分、回測、風控、報表、Streamlit UI、EXE launcher、題材查詢、AI-style 摘要與研究報告摘要都有可執行實作，且目前測試結果為 `179 passed in 12.71s`。

但若把它視為即將發布的正式 v1.0 產品，成熟度仍不足。核心問題不是單一 bug，而是產品級可信度尚未完成：資料治理、provider 契約、point-in-time universe、基本面資料可靠度、UI 狀態管理、EXE 發布工程、E2E 測試、版本化與可追溯性仍偏弱。

結論：目前狀態適合稱為「本機研究工具 Alpha / Beta」，不適合直接稱為成熟 v1.0。若要變成可信、可交付、可長期維護的 v1.0，P0 必須聚焦在資料正確性、可追溯性、UI workflow 穩定、EXE 可部署性與測試矩陣。

## A. 專案架構圖

```text
stock-analysis-tool/
  pyproject.toml
  README.md
  使用教學_簡易版.txt
  launcher.py
  build_exe.bat
  clean_build.bat
  run_from_source.bat
  StockTool.spec

  data/
    sample/
      sample_tw_prices.csv
      sample_tw_prices_for_indicators.csv
      sample_tw_indicators.csv
      sample_fundamentals.csv
      sample_fundamental_scores.csv
      sample_strategy_performance.csv
      concept_stocks.csv
    processed/
      stock_data.sqlite
      fundamentals_auto.csv
    cache/
      yfinance_*.csv

  reports/
    sample_stock_report.xlsx
    sample_stock_report.html

  src/stock_tool/
    cli.py
    data/
      loader.py
      cleaner.py
      storage.py
      providers.py
      cache.py
      auto_fetch.py
    indicators/
      common.py
      trend.py
      momentum.py
      volatility.py
      volume.py
    fundamentals/
      loader.py
      scoring.py
      auto_fetch.py
    strategies/
      base.py
      ma_cross.py
      breakout.py
      rsi_reversal.py
      macd_trend.py
      volume_price_breakout.py
      fundamental_growth.py
    backtest/
      orders.py
      broker.py
      portfolio.py
      engine.py
      metrics.py
    risk/
      rules.py
    reports/
      models.py
      excel.py
      html.py
      charts.py
    dashboard/
      app.py
    concepts.py
    company_research.py
    serenity_agent.py
    research_reports.py
    stock_scoring.py
    entry_reference.py
    screener.py
    portfolio_management.py
    watchlist.py

  tests/
    test_auto_fetch.py
    test_backtest.py
    test_cli.py
    test_company_research.py
    test_concepts.py
    test_dashboard.py
    test_data_cleaning.py
    test_data_loader.py
    test_data_providers.py
    test_entry_reference.py
    test_fundamentals.py
    test_indicators.py
    test_launcher.py
    test_portfolio_management.py
    test_reports.py
    test_research_reports.py
    test_risk.py
    test_screener.py
    test_serenity_agent.py
    test_stock_scoring.py
    test_storage.py
    test_strategies.py
    test_watchlist.py
```

## B. 模組依賴圖

```text
Streamlit Dashboard
  -> data.auto_fetch
  -> data.loader / cleaner / storage
  -> indicators
  -> fundamentals.loader / scoring / auto_fetch
  -> stock_scoring
  -> entry_reference
  -> strategies
  -> backtest.engine
  -> risk.rules
  -> reports.models / excel / html / charts
  -> concepts
  -> company_research
  -> serenity_agent
  -> research_reports
  -> portfolio_management
  -> watchlist
  -> screener

CLI
  -> data.loader / cleaner / storage
  -> indicators
  -> strategies
  -> backtest.engine
  -> reports

BacktestEngine
  -> BrokerSimulator
  -> Portfolio
  -> Order / Trade / Position
  -> PerformanceMetrics
  -> RiskManager

Reports
  -> BacktestResult
  -> PerformanceMetrics
  -> RiskAlert
  -> charts

AI-style Research
  -> stock_scoring
  -> company_research
  -> concepts
  -> research_reports
  -> serenity_agent
  -> yfinance info
```

主要架構問題：`dashboard/app.py` 同時承擔 UI、資料抓取、狀態管理、持久化、評分、報表、題材查詢與錯誤處理。這讓功能增加很快，但 v1.0 長期維護風險高。

## C. 功能清單

已觀察到的功能面：

1. CSV / Excel 股價匯入。
2. 股價資料清洗與警告。
3. SQLite 儲存股價。
4. yfinance / FinMind optional / cache 自動抓股價。
5. 台股上市、上櫃、美股 symbol 轉換。
6. 技術指標：SMA、EMA、RSI、MACD、KD、Bollinger、ATR、成交量均線、乖離率、報酬率、波動率。
7. 基本面 CSV 匯入與基本面評分。
8. yfinance best-effort 基本面補資料。
9. 綜合股票評分：技術 30%、基本 30%、估值 20%、風險 20%。
10. 入場參考價研究模型。
11. 策略模組與多種策略。
12. BacktestEngine、BrokerSimulator、Portfolio、Order、Trade、Position、PerformanceMetrics。
13. T+1 下一根 K 棒成交模型。
14. 交易成本、稅費、滑價與最低手續費。
15. 停損、停利、保守日線 trailing stop。
16. RiskManager risk gate。
17. 股票篩選器。
18. 自選股。
19. 手動投資組合管理。
20. 投資組合風險。
21. 產業 / 概念股查詢。
22. 公司業務脈絡摘要。
23. Serenity-style 本機規則 Agent。
24. PDF 研究報告文字抽取與摘要。
25. Excel 報表。
26. HTML 報表。
27. Streamlit dashboard。
28. CLI。
29. PyInstaller onedir EXE launcher。
30. Windows batch 啟動與打包腳本。

## D. 真正完成的功能

以下功能可視為「研究工具層級已完成」，但不等於產品級完全成熟：

1. 股價資料匯入與清洗：必要欄位、日期、重複列、OHLC 合理性、負成交量、缺值警告已有實作與測試。
2. 技術指標：核心指標皆為獨立函式，有 type hints/docstrings，測試包含不修改原始資料與依 symbol 分組。
3. 回測核心：T 日訊號、T+1 成交原則有明確設計與測試；交易成本、滑價、稅費會進現金流。
4. 風控 risk gate：買賣前檢查現金、最大持股比例、最大持股數、單筆風險、賣出持股不足；有 rejected order。
5. 報表：Excel/HTML 可產生，且包含存活者偏誤與 trailing stop 模型揭露。
6. 自動股價抓取：台股 `.TW` / `.TWO` fallback、US symbol、cache、錯誤紀錄與 user-readable error 已具備。
7. 基本面評分：缺資料會 unknown，不會硬算完整分數。
8. 綜合評分：四分項權重已存在，且提供可用資料分數與 coverage。
9. Windows launcher：可建立 reports/logs、選 port、啟動 Streamlit、開瀏覽器。
10. 測試：目前 pytest 全數通過，覆蓋多個核心邏輯。

## E. 半完成功能

這些功能「能用」，但不夠成熟：

1. 自動基本面：依賴 yfinance best-effort，資料完整性與時效無法保證，台股基本面不足。
2. Provider 架構：有介面與 fallback，但缺 provider contract、health check、rate limit、retry policy、TTL、provenance schema。
3. Screener：目前是 latest indicator filter，還不是完整選股研究平台。
4. Portfolio：可手動持股與估算市值，但缺交易流水、現金流水、股利、匯率、多幣別、實現損益完整帳務。
5. Concept lookup：有熱門題材與線上查詢，但大量知識硬編碼在 `concepts.py`，缺來源、時間戳、信心等級與更新流程。
6. AI 功能：目前是本機規則式摘要，不是可引用資料來源的 LLM/RAG agent。命名為 AI 容易造成期待落差。
7. Research report PDF：可抽文字與摘要，但無 OCR、無表格抽取、無來源段落引用、無版權治理流程。
8. Dashboard：頁面很多，但 workflow 不夠一致，資料狀態在各頁分散。
9. EXE 發布：onedir 可用，但缺 installer、code signing、auto update、release checklist、乾淨機器驗證。
10. Benchmark：回測支援 benchmark，但 UI/資料端尚未把常用 benchmark 當成一等公民。

## F. 技術債

1. `src/stock_tool/dashboard/app.py` 約 2400 行，包含多種責任，是最大維護風險。
2. `src/stock_tool/concepts.py` 約 1300 行，硬編碼題材、別名、個股角色與 provider 查詢。
3. 資料模型不夠集中：price/fundamental/provider/report/dashboard session 各有自己的資料形狀。
4. SQLite schema 太薄：只有 price table，缺 provider metadata、ingestion runs、warnings、universe、corporate actions。
5. Provider 錯誤處理分散，尚無統一 ProviderResult / ProviderError hierarchy。
6. Dashboard 與 domain logic 邊界不清，導致測試需要直接 import dashboard helper。
7. `data/processed` 與 `data/cache` 目前混在專案資料夾，容易把使用者資料、sample data 與 release artifact 混淆。
8. `StockTool.spec` 被 build script 刪除重建，但同時存在於 repo，版本管理策略不清。
9. 題材資料與公司知識未資料庫化、未版本化、未標明資料日期。
10. 缺少 migrations，未來 schema 變更會影響既有使用者資料。
11. 缺少 configuration layer，很多預設路徑、日期範圍、provider 順序分散在模組。
12. 部分 `except Exception` 適合 UI 層，但核心 provider/research 應改為明確例外類型。

## G. UX 問題

1. 功能入口太多，新使用者不容易知道第一步該做什麼。
2. 「資料不足」雖然誠實，但沒有足夠 actionable next step，例如缺哪個欄位、去哪裡補、可否自動補。
3. 「AI 分析」名稱和實作有落差：實際是本機規則式分析，應改成「AI-style / 研究摘要」或清楚標示能力邊界。
4. 產業/概念查詢容易被使用者期待成 Growin/Fugle 等級知識圖譜，但目前更像 rule-based research index。
5. 各頁資料來源狀態不一致：使用者常不知道目前資料來自 SQLite、cache、sample、online 或 upload。
6. 投資組合若缺最新價格，表格出現 `None`，需要更清楚的「可修復操作」。
7. 自動抓資料錯誤雖已中文化，但仍可能過長，應有摘要版與詳細版。
8. 缺少全域 symbol search：使用者輸入股票代號後，應一次帶動股價、基本面、公司摘要、評分與報表。
9. 缺少 onboarding：第一次開 EXE 應顯示「輸入股票代號開始」而非讓使用者摸索頁面。
10. 缺少視覺層級與 responsive design 驗證；Streamlit 預設在手機上可開，但不是手機產品體驗。
11. 報表下載流程和 dashboard 分析流程連動不足。
12. 概念股表格欄位過多，重要欄位如關聯類型、可信度、資料來源、最後更新日應更突出。

## H. 架構問題

1. Dashboard 是上帝物件：應拆出 application services，例如 `AnalysisService`、`DataHydrationService`、`PortfolioService`、`ReportService`。
2. Provider 層只有函式式聚合，缺正式 provider registry、capability model、rate-limit policy。
3. 缺少資料血緣：一筆分析結果無法完整追溯到 provider、cache file、下載時間、清洗 warnings、資料版本。
4. 缺少 point-in-time data architecture：fundamentals、universe、index membership、delisted securities 都未形成正式資料模型。
5. 回測 engine 是研究用迭代器，不是完整 event-driven backtesting framework。
6. RiskManager 與 BacktestEngine 已整合，但投資組合 UI、screener、AI 評分沒有統一共享風控上下文。
7. Concept knowledge 不應長期放在 Python 常數，應外部化為 versioned knowledge base。
8. PDF report ingestion 缺 document store 與 citation model。
9. 報表缺 reproducibility manifest：沒有保存 code version、input hash、provider attempts、parameters snapshot。
10. 缺少 plugin/provider extension boundary：未來加入付費 API、OpenAI/RAG、券商匯出檔時會繼續膨脹 dashboard。

## I. 測試缺口

目前狀態：`179 passed in 12.71s`。

已覆蓋：

1. 資料匯入、清洗、storage。
2. 自動抓資料 symbol mapping、cache、fallback。
3. 技術指標。
4. 策略訊號。
5. 回測 next-bar、防同日成交、成本、停損、trailing stop、benchmark。
6. Risk gate。
7. 基本面與綜合評分。
8. 概念查詢核心規則。
9. Dashboard helper。
10. Portfolio/watchlist/screener。
11. Report generation。
12. Launcher helpers。

缺口：

1. 沒有 Streamlit E2E browser test。
2. 沒有 EXE 啟動後 UI smoke test 的自動化。
3. 沒有乾淨 Windows VM 安裝測試。
4. 沒有 provider contract tests with recorded fixtures。
5. 沒有網路不穩、rate limit、provider schema drift 的回歸測試。
6. 沒有資料庫 migration 測試。
7. 沒有大型資料效能測試。
8. 沒有 visual regression tests。
9. 沒有 accessibility tests。
10. 沒有 security scan / dependency vulnerability scan。
11. 沒有 mypy/ruff/black 在 CI 的正式門檻。
12. 沒有 release artifact checksum 驗證。
13. 沒有 benchmark correctness golden dataset。
14. 沒有 point-in-time survivorship test dataset。
15. 沒有 portfolio multi-currency / missing-price workflow E2E。

## J. 發布流程問題

目前發布能力：

1. `build_exe.bat` 可使用 `.venv` 和 PyInstaller onedir 打包。
2. release folder 包含 EXE、README、sample data、processed/cache data、reports/logs。
3. launcher 會啟動 Streamlit、選 port、寫 logs。

產品級缺口：

1. 沒有 code signing，Windows SmartScreen 與防毒誤判風險高。
2. 沒有 installer/MSI/NSIS/Inno Setup。
3. 沒有自動更新。
4. 沒有 uninstaller。
5. 沒有版本化 release notes。
6. 沒有 SBOM 與第三方套件授權盤點。
7. 沒有乾淨機器 smoke test。
8. 沒有 artifact hash。
9. 沒有 rollback 策略。
10. 沒有「使用者資料和程式資料分離」策略。
11. build script 會複製 `data/processed` 與 `data/cache`，容易把開發者本機資料混入發行版。
12. `release/` 已在 `.gitignore`，但正式發布仍需要可重現 artifact。

## K. 與 TradingView、XQ、QuantConnect 相比

### 相比 TradingView

優點：

1. 本機可控，不需要雲端帳號即可使用核心研究流程。
2. 可讀可改 Python 程式碼，適合學習與客製化。
3. 有本機回測與風控可測試邏輯。
4. 可匯入自己的 CSV / Excel / PDF。

缺點：

1. 圖表、互動性、即時資料、社群腳本、生態系遠遠不足。
2. 沒有成熟 watchlist UX 與多視窗圖表。
3. 沒有穩定行情商與即時資料。
4. 無法接近 TradingView 的 Pine Script 便利性。

### 相比 XQ

優點：

1. Python 開源架構，較容易整合研究流程與客製化報表。
2. 可做本機資料清洗、回測與自訂指標。
3. 無券商綁定，不自動下單，研究風險較低。

缺點：

1. 台股資料完整度、即時性、基本面、籌碼、公告、新聞遠不如 XQ。
2. 沒有正式交易所資料授權。
3. 沒有成熟台股盤中工作流。
4. 產業/概念資料仍靠規則與免費資料源，不是正式資料庫。

### 相比 QuantConnect

優點：

1. 本機簡單，不需要上雲端就能跑。
2. 更適合初學者和單機研究。
3. 專注台股與中文使用情境。

缺點：

1. 回測引擎成熟度、資料工程、事件模型、企業行動、多資產、多幣別、雲端運算都遠不如 QuantConnect。
2. 沒有正式 universe selection / point-in-time fundamentals。
3. 缺少 portfolio construction、alpha model、execution model、risk model 的分層框架。
4. 缺少正式研究 notebook 與 live/paper trading pipeline。

## L. 最值得升級的 50 個地方

依產品價值排序：

1. 建立全域「輸入股票代號 -> 自動補股價 -> 補基本面 -> 計算指標 -> 評分 -> 報表」單一路徑。
2. 建立資料來源狀態中心，所有頁面顯示同一份 data provenance。
3. ProviderResult 標準化：provider、query symbol、date range、row count、cache path、warnings、download time。
4. 建立 ingestion_runs table，記錄每次匯入/下載/清洗結果。
5. 建立 fundamentals table，不要長期依賴 CSV。
6. 建立 company_profile table，保存公司名稱、產業、描述、資料來源、最後更新日。
7. 建立 concept knowledge table，將硬編碼題材搬出 Python。
8. 概念查詢結果加上 confidence、relation_type、source、updated_at。
9. AI 分析頁改成「研究總覽」工作流，降低期待落差。
10. 新增缺資料修復按鈕：缺股價、缺基本面、缺公司摘要、缺 benchmark 分別一鍵補。
11. 強化 yfinance provider schema drift handling。
12. 加入 provider retry/backoff/rate-limit。
13. 支援 provider TTL，避免 cache 永遠被當成新資料。
14. 把 sample data 和 user data 分離到不同目錄。
15. 建立正式 settings/config layer。
16. Dashboard 分頁重組為首頁、股票研究、題材研究、回測、投資組合、報表、設定。
17. 建立 E2E Streamlit 測試。
18. 建立 EXE smoke test。
19. 建立 release checklist。
20. 建立 Windows installer。
21. 對 EXE code signing。
22. 製作乾淨 Windows VM 發布驗證。
23. 報表加入 reproducibility manifest。
24. 報表加入 input data hash。
25. Backtest 加入 dividends/splits/corporate actions 模型。
26. 建立 benchmark provider 與常用 benchmark 選單。
27. 建立 point-in-time universe 資料模型。
28. 建立 delisted securities placeholder/import schema。
29. 基本面加入 filing_date / available_date，防止 point-in-time bias。
30. 策略加入 walk-forward / out-of-sample workflow。
31. 策略加入 parameter sensitivity report。
32. Screener 加入 factor ranking，不只是硬條件過濾。
33. Portfolio 加入交易流水與現金流水。
34. Portfolio 支援股利、匯率、多幣別。
35. Portfolio 缺價時顯示「一鍵補價」狀態與結果。
36. RiskManager 加入 portfolio scenario stress test。
37. RiskManager 加入 factor/sector exposure。
38. 題材研究加入來源連結與最後驗證日期。
39. PDF 摘要加入頁碼引用。
40. PDF 摘要支援 OCR optional。
41. PDF 摘要加入表格抽取與數字校驗。
42. 公司摘要加入公開來源 links，不自動抓付費報告。
43. 加入資料品質 dashboard。
44. 加入 logs viewer，讓使用者不用去資料夾找 log。
45. 統一錯誤訊息格式：摘要、原因、下一步、詳細資訊。
46. 加入 dependency vulnerability scan。
47. 加入 license/SBOM。
48. 加入 mypy/ruff/black CI gate。
49. 加入 performance benchmark dataset。
50. 加入正式版本號與 release notes。

## M. 最值得重構的 20 個地方

依風險排序：

1. 拆分 `dashboard/app.py`：UI pages、state、services、formatters、download/report helpers。
2. 拆分 `concepts.py`：knowledge data、query matcher、TW provider、US provider、ranking。
3. 建立 application service layer，dashboard 不直接 orchestrate domain modules。
4. 建立 unified `Symbol` / `Market` model，避免 TW/TWSE/TPEX/AUTO/CUSTOM 到處轉換。
5. 建立 unified `DataSourceMetadata`。
6. 建立 storage repository layer，避免 SQLite CSV 路徑分散。
7. 將 `data/processed` 視為 runtime user data，不再打包開發資料。
8. 建立 migration framework。
9. 將 fundamentals auto-fetch 和 scoring 分離成 provider -> normalized record -> scorer。
10. 將 company_research 規則資料外部化。
11. 將 Serenity agent 的 keyword groups 外部化並版本化。
12. 將 report localization table 獨立為 i18n/config。
13. BacktestEngine 拆成 execution loop、risk signal generator、order factory、accounting adapter。
14. BrokerSimulator 與 RiskManager 的 sizing 邏輯統一，避免重複計算 quantity。
15. Strategy registry 化，讓 dashboard 自動讀 strategy metadata。
16. Screener criteria schema 化，支援 UI 自動產生控制項。
17. 統一 missing data 表示法，不在各模組混用 `unknown`、`None`、`資料不足`、`pd.NA`。
18. 建立 reusable table formatter，避免 dashboard/reports 各自格式化。
19. 建立 logging policy，區分 user-facing error 與 debug log。
20. 建立 release packaging module，取代 batch script 中散落的複製邏輯。

## N. 建議 Roadmap

### v1.1：可信本機研究版

完成標準：

1. Dashboard 拆出 service layer，`app.py` 減少到可維護大小。
2. 全域股票查詢流程可一鍵完成股價、基本面、指標、評分。
3. 所有資料來源都有 provenance 顯示。
4. 使用者資料與 sample/release data 分離。
5. provider attempts、cache、清洗 warnings 寫入 SQLite。
6. E2E dashboard smoke test 完成。
7. EXE smoke test 完成。
8. README 與 UI 用詞一致，AI 功能能力邊界清楚。

### v1.2：資料治理與報表可信版

完成標準：

1. fundamentals、company_profile、concept knowledge 進 SQLite。
2. 報表包含 reproducibility manifest。
3. benchmark provider 與常用 benchmark UI 完成。
4. concept lookup 有 confidence、source、updated_at。
5. PDF 摘要有頁碼引用或明確限制。
6. provider TTL/rate-limit/retry 完成。
7. 資料品質 dashboard 完成。
8. migration 測試完成。

### v2.0：專業量化研究平台

完成標準：

1. Point-in-time universe 與 delisted securities import schema。
2. 基本面 available_date 支援，策略不得偷用未公告資料。
3. Walk-forward / out-of-sample / parameter sensitivity report。
4. Corporate actions、dividends、splits 模型。
5. Portfolio 支援交易流水、股利、多幣別、FX。
6. Risk scenario/stress/factor exposure。
7. Strategy registry 與 plugin-style strategy 擴充。
8. CI gate：pytest、coverage、ruff、mypy、security scan。

### v3.0：可商用交付版

完成標準：

1. Code-signed Windows installer。
2. Auto update 與 rollback。
3. SBOM/license/vulnerability process。
4. Optional paid provider adapter，不硬編 API key。
5. RAG/LLM research assistant with citations，並保留本機規則 fallback。
6. 多使用者設定檔與資料庫備份/還原。
7. 完整產品 telemetry opt-in，不收集私人交易資料。
8. 正式使用者手冊與 troubleshooting knowledge base。

## P0 / P1 / P2 優先級

### P0：必修

1. 拆分 dashboard orchestration，建立 service layer。
2. 建立資料來源 provenance 與 ingestion_runs。
3. 使用者資料與發行 sample data 分離。
4. Provider contract、retry、rate limit、TTL。
5. 統一 symbol/market model。
6. 統一 missing data 與 user-facing error model。
7. EXE clean-machine smoke test。
8. Streamlit E2E smoke test。
9. 報表 reproducibility manifest。
10. AI 功能重新命名或強化揭露，避免使用者以為是完整 LLM 投資顧問。
11. 基本面資料可靠度揭露與 available_date 架構。
12. concept knowledge 從 Python 硬編碼外部化。

### P1：重要

1. fundamentals/company_profile 正式進 SQLite。
2. benchmark provider 與 UI。
3. point-in-time universe import schema。
4. strategy registry。
5. walk-forward / out-of-sample。
6. portfolio transaction ledger。
7. multi-currency / FX。
8. PDF 摘要頁碼引用。
9. data quality dashboard。
10. logs viewer。
11. code signing 與 installer。
12. CI quality gates。
13. SBOM/license inventory。
14. performance benchmark。
15. risk scenario/stress tests。

### P2：可延後

1. OCR。
2. 手機版專用 UI。
3. 進階互動式 K 線。
4. 進階圖表模板。
5. Auto update。
6. 多使用者 profile。
7. Cloud sync。
8. Optional LLM/RAG assistant。
9. 外部 plugin marketplace。
10. 更完整的題材知識圖譜編輯器。

## 產品成熟度判斷

目前專案距離成熟 v1.0 的主要差距，不在於「功能數量」，而在於「可信流程」：

1. 一筆分析結果需要可追溯來源。
2. 一次回測需要可重現。
3. 一個分數需要能說明資料缺口。
4. 一個 EXE 需要能在乾淨 Windows 機器穩定啟動。
5. 一個 dashboard 需要有清楚主路徑，而不是把所有能力攤在側欄。
6. 一個 AI 摘要需要有能力邊界與來源，不應讓使用者誤以為是精準投資建議。

現階段最合理的產品定位是：

```text
本機股票研究與回測工具 Beta
適合學習、研究、資料檢查與策略假設驗證
不適合宣稱為完整投資平台、行情終端或專業投顧系統
```

## 驗證紀錄

本次審查執行：

```text
.\.venv\Scripts\python.exe -m pytest
```

結果：

```text
179 passed in 12.71s
```

本次審查未執行：

1. EXE 實際啟動 UI。
2. Windows Defender / 防毒掃描。
3. 乾淨 Windows VM 測試。
4. 真實線上 provider 長時間穩定性測試。
5. Streamlit browser E2E 測試。

## Final Recommendation

下一步不要再優先堆新功能。應先把現有功能整理成可信、可追溯、可維護的產品主流程。

建議第一個實作批次：

1. 建立 `AnalysisService` 與 `DataHydrationService`。
2. 新增 ingestion metadata storage。
3. Dashboard 改成「輸入股票 -> 自動補資料 -> 產出研究總覽」主流程。
4. 將 concept knowledge 外部化為 CSV/JSON/SQLite。
5. 建立 EXE smoke test 與 release checklist。

完成上述後，這個專案才會從「功能很多的研究原型」往「可交付的 v1.0 產品」前進。
