# Sprint 3.2 Acceptance

驗收日期：2026-07-11  
執行環境：Windows、Python 3.11.9、PyInstaller 6.21.0

## Verdict

**Accepted with documented limits.** Sprint 3.2 的 Portfolio correctness、使用者資料隔離、跨幣別估值、持股健康度、本機規則式研究摘要與 deterministic stress test 已完成並驗證。Sprint 4 未開始，未修改 Dashboard 導航，也未改寫個股分析、回測或風控核心。

## 1. Baseline 與使用者資料安全

- Sprint 3.1 source archive：release/baseline/stocktool-sprint3.1-20260711-source.zip
- Sprint 3.1 source archive SHA-256：DBFA3DA16189AE66C03F08D468801D26B1D8655E9F584E2B59D4F902087838A2
- Sprint 3.2 修改前 source snapshot：release/baseline/stocktool-sprint3.2-20260711-prechange-source.zip
- 修改前 snapshot SHA-256：0BFF5E1FBC8B50D3D054B32D5867A9519CE3BC7E8A874363DAF895F7C83753EF
- 使用者資料備份 manifest：backups/sprint3.2-prechange-20260711/manifest.json
- 目前使用者 portfolio 與備份均為 4 rows，SHA-256 均為 A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6
- 未安裝 Git；baseline 使用 archive 與 SHA-256。

Windows runtime/user data path：

%LOCALAPPDATA%\StockTool\

包含 data/portfolio.csv、data/watchlist.csv、data/processed/、data/cache/、reports/、logs/、backups/ 與 settings.json。STOCK_TOOL_USER_DATA_DIR 可供測試或進階使用者覆寫。

舊版 release runtime data 只有在新位置不存在時才會複製；會先備份、驗證 row count 與 SHA-256，成功前不刪除舊檔。新舊資料同時存在時保留新資料並產生 warning。build_exe.bat 只刪除 release/StockTool/ 成品，不會刪除 %LOCALAPPDATA%\StockTool\。

## 2. 修改檔案

- pyproject.toml：coverage gate 從 70% 提升為 72.63%。
- README.md：補充 Sprint 3.2 runtime path、跨幣別估值、legacy SQLite 市場欄位限制、健康度與壓力測試說明。
- src/stock_tool/portfolio_management.py：限制 legacy/unknown market 不參與安全價格 lookup；同幣別權重需為已知 TWD/USD。
- src/stock_tool/portfolio_valuation.py：補強 unknown FX quote、可替換且有期限的 CachedFxRateProvider、安全 market parsing 與 base-currency valuation。
- src/stock_tool/portfolio_health.py：補上市場/幣別/產業集中度證據、加權風險輸入與 canonical technical/composite missing fields。
- src/stock_tool/portfolio_research.py：摘要納入完整 missing-data findings。
- src/stock_tool/dashboard/app.py：移除持股使用 symbol/market，CUSTOM 幣別明確輸入，加入價格/匯率更新入口與來源日期資訊；保留既有導航與 legacy UI。
- tests/fixtures/sprint32_positions.csv：版本化、非私人固定 fixture。
- tests/test_sprint32_portfolio.py：Sprint 3.2 correctness、safety、health、brief、stress test 回歸測試。

Sprint 3.2 前置已存在並保留的核心檔案包括 runtime_paths.py、portfolio_stress.py、launcher.py 與 build_exe.bat；本輪未重寫其既有架構。

## 3. 公開 Portfolio contract

Portfolio position 的 canonical identity 是 symbol + market。同一代號在 TWSE、TPEX、US 可以同時存在；移除、價格 lookup 與補抓價格都必須使用完整 identity。AUTO 與 CUSTOM 不會被默默猜成 TWSE；CUSTOM 必須提供 TWD 或 USD。

Valuation contract 保留 native_currency、native_cost_basis、native_market_value、native_unrealized_pnl、fx_rate_to_base、base_cost_basis、base_market_value、base_unrealized_pnl 與 weight。

TWSE/TPEX 預設 TWD，US 預設 USD，base currency 預設 TWD。權重只使用 base-currency market value；缺 price 或 FX 時 consolidated totals 與 weight 為 unknown，不會直接相加 TWD 與 USD。

## 4. Currency / FX contract

Currency 支援 TWD、USD；FxQuote 包含 currency pair、rate、source、fetched_at、effective_at、stale、unknown。FxRateProvider 是可替換 protocol，StaticFxRateProvider 用於固定 fixture/manual fallback，CachedFxRateProvider 只使用設定期限內的 cache。manual quote 的 source 明確為 manual，fixture 不會標成線上最新匯率。

沒有 FX rate 時不產生跨幣別假結果；stale quote 可以保留原生/base 計算，但會產生 stale warning，並進入健康度資料品質 evidence。

## 5. Portfolio health

PortfolioHealthService 是 deterministic、可測試且不修改輸入 DataFrame 的規則引擎：

- 集中度 30%：最大持股、前三大持股、市場集中、幣別集中；產業只有欄位存在時才計算。
- 風險 25%：既有 volatility/drawdown 欄位，按 market-qualified weight 加權。
- 持股品質與趨勢 25%：重用 caller 提供的 composite stock score，不重算另一套股票評分。
- 資料可信度 20%：價格、FX、基本面、技術指標 coverage 與 valuation evidence。

主要設定集中在 PortfolioHealthConfig：minimum coverage 70%、maximum position 35%、top-three 75%、market/currency 80%、industry 60%、target volatility 35%、target drawdown 30%。coverage 低於門檻或必要 component unknown 時，overall score 為 None、status 為 insufficient_data；未實現損益不直接提高或降低健康度。

每個 component 都輸出 score、weight、contribution、reasons、warnings、missing_data 與 evidence。technical indicator 缺失使用 technical_indicators，composite score 缺失使用 composite_score；missing、unknown、not_applicable、stale 不混用。

## 6. 本機規則式研究摘要

PortfolioResearchBrief 完全由 PortfolioHealthResult 與其 evidence/missing-data 產生，不呼叫外部 LLM/API、不新增 API key、不傳送私人持股、不預測明天漲跌、不輸出買進、賣出、加碼或減碼指令。輸出包含 overall summary、strengths、top risks、concentration findings、currency findings、data quality findings、counterarguments、next checks、missing data、evidence 與 disclaimer。

## 7. Stress test

支援所有持股下跌、最大持股下跌、指定市場下跌與 USD/TWD 匯率變動。X 是使用者明確設定的 deterministic shock，輸出 base-currency before/after/impact 與 assumptions。缺少 FX 或 consolidated base value 時回傳 missing-data，不猜測跨幣別結果；不修改實際 portfolio 或 valuation DataFrame。Stress test 不是 forecast 或投資建議。

## 8. 測試結果

Sprint 3.2 targeted：

    .venv\Scripts\python.exe -m pytest -v tests\test_sprint32_portfolio.py tests\test_portfolio_management.py tests\test_portfolio_valuation.py tests\test_portfolio_health.py tests\test_portfolio_research.py tests\test_runtime_paths.py tests\test_dashboard.py

結果：54 passed in 3.45s

完整 pytest：

    .venv\Scripts\python.exe -m pytest -v

結果：281 passed in 12.29s

Coverage：

    .venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing

結果：73.50%，pyproject gate 72.63% 通過。

Focused Black（Sprint 3.2 core/fixture scope）：

    .venv\Scripts\python.exe -m black --check src\stock_tool\runtime_paths.py src\stock_tool\portfolio_management.py src\stock_tool\portfolio_valuation.py src\stock_tool\portfolio_health.py src\stock_tool\portfolio_research.py src\stock_tool\portfolio_stress.py tests\test_sprint32_portfolio.py

結果：7 files unchanged。

Focused Ruff：

    .venv\Scripts\python.exe -m ruff check src\stock_tool\runtime_paths.py src\stock_tool\portfolio_management.py src\stock_tool\portfolio_valuation.py src\stock_tool\portfolio_health.py src\stock_tool\portfolio_research.py src\stock_tool\portfolio_stress.py src\stock_tool\dashboard\app.py tests\test_sprint32_portfolio.py

結果：All checks passed。

Focused mypy：

    .venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\runtime_paths.py src\stock_tool\portfolio_management.py src\stock_tool\portfolio_valuation.py src\stock_tool\portfolio_health.py src\stock_tool\portfolio_research.py src\stock_tool\portfolio_stress.py

結果：0 issues in 6 source files。

注意：整個 dashboard/app.py 的 Black check 仍會提出 Sprint 3.1 以前的既有格式化差異。本輪沒有對整個 Dashboard 做格式化重寫；Ruff 與本輪 focused checks 均通過。這項既有 format debt 未隱藏，也不阻擋 Sprint 3.2 功能驗收。

## 9. EXE 與 runtime smoke test

- EXE：C:\Users\steve\OneDrive\Documents\股票\release\StockTool\StockTool.exe
- 建置時間：2026-07-11T20:23:40.8073382+08:00
- 大小：23,739,505 bytes
- SHA-256：5BCD8434BAA2202B8AA315CCF5A6E13A6C99D3134D9DA69809751AE6766A6D0F
- http://localhost:8501/_stcore/health：HTTP 200，body ok
- 隔離 smoke user-data 下 reports/、logs/、data/cache/ 的實際 write/read/delete probes：全部通過。
- smoke test 後 StockTool process：0。
- smoke test 後 8501/8502 listener：0。
- smoke test runtime directory：已清理。
- release 內容包含 README.md、.env.example、版本化 data/sample/ 與 onedir _internal/；不包含 runtime portfolio、watchlist、processed、cache、reports 或 logs。

Release privacy scan 沒有發現真實 .env、API token、私人 portfolio、watchlist、cache、reports 或 logs。PyInstaller 依賴內的 streamlit/runtime/secrets.py 與 Arrow 的 tz_private.h 是套件原始碼/標頭，不是使用者秘密或設定檔。

## 10. Source archive

- Archive：C:\Users\steve\OneDrive\Documents\股票\release\baseline\stocktool-sprint3.2-20260711-source.zip
- Sidecar：C:\Users\steve\OneDrive\Documents\股票\release\baseline\stocktool-sprint3.2-20260711-source.zip.sha256
- Archive 大小：430,835 bytes
- SHA-256：B4A54A5FEF3CB4045DC6275E496104D6A52E8FFF345B8273C634307ADF26AAD8
- Archive 僅包含 source、tests、docs、examples、README、sample data 與 build metadata；未包含 release、backups、artifacts、.venv、.coverage、cache、processed、reports、logs、私人 portfolio/watchlist 或真實 .env。

## 11. 已知限制與 Sprint 4 gate

1. 本輪沒有建立 live FX provider；線上 FX 仍需另行選定可信資料源，現有 boundary 支援 static/manual/cache。
2. 舊 SQLite prices schema 沒有 market 欄位，無法安全配對跨市場同代號；系統採保守 unknown，而不是猜測。
3. 健康度的產業集中需要 caller 提供 industry/sector 欄位；沒有資料時只輸出未評估原因。
4. Portfolio health 尚未全面接入所有個股 composite score 的自動更新流程；缺少時會顯示 not_applicable/insufficient_data。
5. Dashboard 仍保留 legacy portfolio UI；本輪只加入必要入口，未開始 Sprint 4 Dashboard Shell 或導航重構。
6. 全專案既有 Black format debt 尚未清理；本輪 focused Black/Ruff/mypy 只涵蓋 Sprint 3.2 相關範圍。
7. PyInstaller 仍可能顯示 pycparser hidden-import warning，但 EXE health、寫入、privacy scan 已通過。

Sprint 3.2 沒有已知的功能性阻擋問題；Sprint 4 尚未開始，是否進入 Sprint 4 需另行確認。
