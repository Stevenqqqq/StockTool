# StockTool Product Execution Plan

文件日期：2026-07-10  
依據文件：`PROJECT_WHITEPAPER.md`、`PRODUCT_VISION.md`  
規劃角色：Principal Software Architect、Technical Program Manager、Principal Product Manager  
規劃限制：本文件只定義執行順序、驗收條件、風險與回滾策略；未修改任何程式，也未新增產品功能。

## 0. 執行摘要

本計畫把 Product Vision 轉成 19 個可驗收 Sprint，預設每個 Sprint 為兩週。單一小型團隊依序執行約需 38 週；若只有一位主要開發者，應預留 45–60 週，且不得透過省略測試、資料治理或 Windows 驗證來縮短時程。

執行順序遵守四項原則：

1. 先建立資料契約與可追溯性，再重做首頁。
2. 以漸進式遷移取代一次重寫，舊流程在新流程驗收前保持可回退。
3. 確定性計算先於 AI；AI 不得修改原始資料、分數或回測結果。
4. 每個版本都必須有獨立穩定化 Sprint，不把打包與驗收留到最後一天。

## 1. 產品總體目標

> 讓使用者輸入一檔股票、公司或產業題材後，在同一個可信、可追溯、可重現的研究工作區完成資料取得、公司理解、綜合評分、策略驗證與風險判讀。

## 2. Definition of Done

### 2.1 產品層級完成

產品真正完成，必須同時符合下列條件，而不是只代表畫面存在或單元測試通過：

1. 新使用者雙擊 Windows 應用程式後，30 秒內知道如何開始第一份研究。
2. 輸入台股上市、台股上櫃或美股標的後，不必先操作資料匯入頁，即可進入研究工作區。
3. 研究工作區能同時顯示公司摘要、價格脈絡、綜合評分、主要優缺點、主要風險、資料覆蓋率與來源狀態。
4. 資料不足時不產生完整假分數、假權重、假損益或沒有依據的文字結論。
5. 每個重要數字能追溯到資料來源、資料期間、取得時間、清洗警告與模型版本。
6. 回測固定遵守下一根 K 棒成交，且報酬已包含交易成本、稅費、滑價與設定的成交模型。
7. 題材研究能區分核心製造、關鍵供應、設計平台、下游需求與間接受益，不以文字相似度冒充供應鏈證據。
8. 投資組合遇到缺價時，明確標示不可計算欄位，不輸出誤導性權重與損益。
9. Excel、HTML 或後續 PDF 匯出包含可重現資訊、資料缺口與風險聲明。
10. 產品不自動下單、不輸出保證語氣、不把歷史回測描述為未來結果。

### 2.2 工程層級完成

每個功能必須同時滿足：

1. 有明確輸入、輸出、錯誤與 missing-data 契約。
2. 有 type hints、核心 docstring 與責任邊界。
3. 有正常、邊界、失敗與資料不足測試。
4. 不破壞既有核心測試；所有既有測試持續通過。
5. 核心計算模組行覆蓋率目標至少 90%，專案整體至少 80%；若現況尚未達標，版本不得降低既有覆蓋率，並逐 Sprint 提升。
6. 所有資料庫變更有 migration、備份與回滾驗證。
7. 所有 UI 功能由 application service 取得資料，不直接在畫面層拼接多個 provider 與 domain module。
8. 所有外部資料源失敗都有可理解訊息、詳細 log、重試邊界與 fallback 結果。

### 2.3 Sprint 完成

一個 Sprint 只有在下列條件全部成立時才能關閉：

1. Sprint acceptance tests 全部通過。
2. 完整 `pytest` 通過，沒有略過既有失敗。
3. 格式、靜態檢查與安全檢查符合該版本 gate。
4. 手動驗收情境已有紀錄。
5. rollback 在測試環境演練成功。
6. 文件、版本註記與已知限制同步更新。
7. 沒有未揭露的 High severity 問題。

### 2.4 版本完成

每個版本除 Sprint DoD 外，還必須：

1. 在乾淨 Windows 11 測試環境完成安裝或 onedir 啟動。
2. 驗證台股上市、台股上櫃、美股與離線/快取四種資料情境。
3. 驗證 `reports/`、`logs/` 與使用者資料目錄可寫入。
4. 發行物不包含 API token、私人報告、開發者 cache、持倉或個人資料。
5. 產生版本號、release notes、SHA-256 checksum 與已知限制。
6. 保留上一個可用版本與資料備份，確認可降版。

## 3. MVP

MVP 定義為 v1.1「可信本機研究版」。它不是十項 Product Vision 的最終成熟形態，而是能完整跑通 Killer Feature 的最小可信版本。

### 3.1 MVP 一定要做

1. 全域股票搜尋與市場辨識。
2. 搜尋後自動補股價、基本面與公司摘要；部分失敗時仍能顯示可用結果。
3. 單一 Research Workspace，整合研究摘要、評分卡、圖表、主要風險與資料狀態。
4. 綜合評分維持技術 30%、基本面 30%、估值 20%、風險 20%，並顯示覆蓋率、優點、缺點與 missing data。
5. 資料來源 metadata、provider attempts、清洗警告與更新時間。
6. 既有下一根 K 棒回測、交易成本、RiskManager 與 benchmark 能從 Research Workspace 進入。
7. 基本自選股與持倉入口，缺價有可修復狀態。
8. Excel/HTML 匯出包含資料與參數摘要。
9. 六項主導航：研究首頁、探索、策略、持倉、研究庫、設定。
10. Windows onedir EXE、E2E smoke test、乾淨 Windows 啟動驗證。

### 3.2 MVP 明確不要做

1. 不做自動下單、模擬下單或券商連線。
2. 不做即時行情終端、盤中警報或新聞串流。
3. 不做 AI 漲跌預測、AI 選股保證或自動目標價。
4. 不接外部 LLM，不在 v1.1 建立完整 RAG。
5. 不做 OCR、付費研究報告抓取或未授權內容散布。
6. 不做手機專用 App、雲端同步或多使用者帳號。
7. 不做多幣別完整帳務、股利與 corporate actions；這些排入 v2。
8. 不重寫回測引擎為 event-driven framework。
9. 不做 plugin marketplace。
10. 不以增加更多指標、策略或題材清單作為 MVP 進度。

## 4. Roadmap

| 版本 | 產品目標 | Sprint | 版本出口條件 |
|---|---|---:|---|
| v1.1 | 可信本機研究版 | 1–6 | 一次搜尋可完成可追溯研究總覽；EXE 在乾淨 Windows 啟動 |
| v1.2 | 資料治理與證據版 | 7–10 | 基本面、公司、題材與報表有正式資料模型、來源與 migration |
| v2 | 專業量化研究版 | 11–15 | point-in-time、策略健檢、corporate actions、完整 portfolio/risk 核心可驗證 |
| v3 | 可交付智慧研究產品 | 16–19 | 有引用的 AI 協助、研究庫、簽章安裝程式、安全與正式發布流程 |

### 4.1 v1.1：可信本機研究版

範圍：統一資料契約、application service、Research Workspace、新首頁、基本 provenance、E2E 與 EXE 穩定化。

不包含：AI/RAG、point-in-time fundamentals、多幣別、installer、code signing。

### 4.2 v1.2：資料治理與證據版

範圍：fundamentals、company profile、concept knowledge、document metadata、provider reliability、benchmark 與 reproducibility manifest。

不包含：完整歷史 universe、delisted data、進階 portfolio accounting。

### 4.3 v2：專業量化研究版

範圍：available date、point-in-time universe import、walk-forward、out-of-sample、參數敏感度、corporate actions、portfolio ledger、多幣別與風險情境。

不包含：自動交易與即時交易執行。

### 4.4 v3：可交付智慧研究產品

範圍：有引用的 AI 協助整理與論點健檢、研究文件庫、簽章 installer、更新與 rollback、安全盤點與正式發布制度。

不包含：AI 價格預測、無來源生成事實、券商下單。

## 5. Sprint Planning

### Sprint 1：基線、契約與變更護欄

**目標**

凍結目前可用行為，建立版本控制基線、golden fixtures、feature flag 與每個版本的 acceptance checklist。沒有可重現 baseline，不開始架構遷移。

**預計修改或新增檔案**

- `pyproject.toml`
- `README.md`
- `docs/architecture/contracts.md`（新增）
- `docs/release/acceptance-v1.1.md`（新增）
- `src/stock_tool/config.py`
- `tests/fixtures/`（新增或整理）
- `tests/test_regression_baseline.py`（新增）

**新增測試**

- 既有 sample 股票研究輸出 golden test。
- 既有回測、評分、報表關鍵輸出快照。
- 設定預設值與 feature flag 測試。

**驗證方式**

- 完整 `pytest` 維持通過。
- 對 2330、6488、AAPL 建立固定驗收紀錄。
- 建立版本基線 tag 或不可變備份。

**最大風險**

Golden tests 把既有錯誤也凍結。只鎖定公開行為與已知正確不變量，不鎖定易變文案與浮動線上數值。

**Rollback**

本 Sprint 不改核心行為；移除 feature flag 與新測試即可回到基線。所有後續 Sprint 以此 tag/備份為共同 rollback 點。

### Sprint 2：統一 Domain 與 Provider 契約

**目標**

建立統一的 `Symbol`、`Market`、`ProviderResult`、`DataSourceMetadata`、`QualityReport` 與 missing-data 表示法，不改變既有計算結果。

**預計修改或新增檔案**

- `src/stock_tool/domain/models.py`（新增）
- `src/stock_tool/data/contracts.py`（新增）
- `src/stock_tool/data/providers.py`
- `src/stock_tool/data/auto_fetch.py`
- `src/stock_tool/data/cleaner.py`
- `src/stock_tool/data/storage.py`
- `tests/test_domain_models.py`（新增）
- `tests/test_provider_contracts.py`（新增）

**新增測試**

- TWSE、TPEx、US symbol normalization contract。
- Provider 成功、空資料、schema drift、部分資料與 fallback contract。
- QualityReport 不修改原始 DataFrame。
- missing、unknown、not-applicable 的序列化測試。

**驗證方式**

- 新舊 provider 結果對固定 fixtures 等價。
- 所有既有 data、indicator、scoring、backtest tests 通過。

**最大風險**

一次替換資料形狀可能影響 dashboard、report 與 tests。

**Rollback**

先以 adapter 包裝舊回傳格式；新 contract 置於 feature flag 後。若下游出現回歸，切回 legacy adapter，不回滾資料內容。

### Sprint 3：資料血緣與 Application Service

**目標**

建立 `DataHydrationService` 與 `AnalysisService`，讓一次搜尋協調 provider、cache、storage、indicators、fundamentals 與 scoring；新增 ingestion run metadata。

**預計修改或新增檔案**

- `src/stock_tool/application/data_hydration.py`（新增）
- `src/stock_tool/application/analysis.py`（新增）
- `src/stock_tool/application/results.py`（新增）
- `src/stock_tool/data/storage.py`
- `src/stock_tool/data/migrations/001_ingestion_runs.sql`（新增）
- `src/stock_tool/stock_scoring.py`
- `tests/test_data_hydration_service.py`（新增）
- `tests/test_analysis_service.py`（新增）
- `tests/test_ingestion_runs.py`（新增）

**新增測試**

- 一次請求整合股價、基本面、指標與評分。
- 部分 provider 失敗仍回傳 partial result。
- 每次下載、cache 命中、清洗警告寫入 ingestion metadata。
- 同一輸入可產生一致 deterministic result。

**驗證方式**

- 使用 recorded fixtures 驗證線上、cache、upload、sample 四種來源標示。
- 比對服務輸出與既有各模組直接呼叫結果。

**最大風險**

服務層成為新的上帝物件。

**Rollback**

服務只 orchestration，不搬動計算公式；保留舊 dashboard 呼叫路徑，直到 Sprint 5 完成驗收。

### Sprint 4：Dashboard Shell 與六項導航

**目標**

建立新的應用 shell、六項導航、全域搜尋與統一 session state；先完成骨架，不在同一 Sprint 搬完所有頁面。

**預計修改或新增檔案**

- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/dashboard/navigation.py`（新增）
- `src/stock_tool/dashboard/state.py`（新增）
- `src/stock_tool/dashboard/pages/home.py`（新增）
- `src/stock_tool/dashboard/components/search.py`（新增）
- `src/stock_tool/dashboard/components/status.py`（新增）
- `tests/test_dashboard_navigation.py`（新增）
- `tests/test_dashboard_state.py`（新增）

**新增測試**

- 六項導航存在且順序固定。
- 搜尋狀態在頁面切換後保持。
- 首次、loading、partial、ready、stale、error 六種狀態。
- 鍵盤提交、空輸入與歧義標的處理。

**驗證方式**

- Streamlit component test 或 AppTest。
- 桌面 1366×768、1920×1080 與窄視窗手動驗收。

**最大風險**

Streamlit rerun 造成重複下載、狀態遺失或畫面閃動。

**Rollback**

保留 `legacy_dashboard` feature flag；新 shell 未通過 E2E 前，EXE 預設仍可切回舊入口。

### Sprint 5：Research Workspace 與證據鏈研究快照 MVP

**目標**

把個股分析、技術指標、基本面、研究摘要、評分、風險與資料來源整合成同一 Research Workspace。

**預計修改或新增檔案**

- `src/stock_tool/dashboard/pages/research.py`（新增）
- `src/stock_tool/dashboard/components/research_header.py`（新增）
- `src/stock_tool/dashboard/components/scorecard.py`（新增）
- `src/stock_tool/dashboard/components/research_chart.py`（新增）
- `src/stock_tool/dashboard/components/evidence_panel.py`（新增）
- `src/stock_tool/dashboard/components/risk_summary.py`（新增）
- `src/stock_tool/application/analysis.py`
- `src/stock_tool/company_research.py`
- `src/stock_tool/entry_reference.py`
- `tests/test_research_workspace.py`（新增）

**新增測試**

- 研究快照完整、部分資料與不足三種狀態。
- 綜合評分權重、coverage、優點、缺點與 missing data 顯示。
- 「建議入場價」不再出現，改為含假設的「情境參考區間」。
- 重要事實有來源；推論有明確標籤。
- Research Workspace 不直接修改 service 回傳資料。

**驗證方式**

- 2330、6488、MU 與一個不存在代號的端到端情境。
- 使用者可在第一屏看到公司、分數、主要風險與資料狀態。

**最大風險**

為了塞入所有資訊而重現舊 dashboard 的資訊過載。

**Rollback**

每個區塊獨立 feature flag；若整體 Workspace 不穩，保留新搜尋但導回舊個股頁，不回滾 service 與 metadata。

### Sprint 6：v1.1 穩定化、E2E 與 Windows 發布

**目標**

停止功能開發，完成 Research Workspace E2E、EXE smoke test、使用者資料分離、文件與 v1.1 發行。

**預計修改或新增檔案**

- `launcher.py`
- `build_exe.bat`
- `clean_build.bat`
- `run_from_source.bat`
- `StockTool.spec`
- `README.md`
- `使用教學_簡易版.txt`
- `tests/e2e/test_research_journey.py`（新增）
- `tests/test_release_layout.py`（新增）
- `tests/test_exe_smoke.py`（新增）
- `docs/release/v1.1-checklist.md`（新增）

**新增測試**

- 搜尋到研究快照的 browser E2E。
- provider 失敗與 cache fallback E2E。
- EXE 啟動、port fallback、瀏覽器 URL、reports/logs 寫入。
- 發行物不含 `.env` 私密值、個人 cache、持倉與私人報告。

**驗證方式**

- Python 3.11.9 venv 完整測試。
- 乾淨 Windows 11 VM 執行 onedir 成品。
- 以 TWSE、TPEx、US、offline 四情境完成 acceptance checklist。

**最大風險**

PyInstaller hidden imports、路徑與防毒誤判造成開發機成功、使用者機失敗。

**Rollback**

保留上一版 `release/StockTool` 壓縮檔與 checksum；新 EXE 失敗時立即退回舊版，使用者資料目錄不降版也不刪除。

### Sprint 7：正式資料庫模型與 Migration

**目標**

建立 fundamentals、company profile、concept knowledge、documents 與 schema version；把 runtime user data 與 release sample data 分離。

**預計修改或新增檔案**

- `src/stock_tool/data/storage.py`
- `src/stock_tool/data/repositories.py`（新增）
- `src/stock_tool/data/migrations/002_research_entities.sql`（新增）
- `src/stock_tool/fundamentals/loader.py`
- `src/stock_tool/fundamentals/auto_fetch.py`
- `src/stock_tool/concepts.py`
- `src/stock_tool/research_reports.py`
- `tests/test_database_migrations.py`（新增）
- `tests/test_research_repositories.py`（新增）

**新增測試**

- 空資料庫升級、既有資料庫升級與重複執行 migration。
- migration 前後 row count、hash 與關鍵欄位一致。
- sample data 與 user data 路徑隔離。
- migration 失敗後資料庫可從備份恢復。

**驗證方式**

- 使用 v1.1 實際資料副本演練升級與降版。
- 新安裝與升級安裝輸出相同 schema version。

**最大風險**

資料庫 migration 損壞既有使用者資料。

**Rollback**

採 additive migration；升級前自動備份 SQLite。migration 失敗時不啟動新版本，還原備份並保留錯誤 log。

### Sprint 8：Provider Reliability 與資料證據中心

**目標**

建立 provider registry、capability、retry/backoff、rate limit、TTL、health 狀態與「資料與證據中心」。

**預計修改或新增檔案**

- `src/stock_tool/data/registry.py`（新增）
- `src/stock_tool/data/policies.py`（新增）
- `src/stock_tool/data/providers.py`
- `src/stock_tool/data/auto_fetch.py`
- `src/stock_tool/data/cache.py`
- `src/stock_tool/dashboard/pages/library.py`（新增）
- `src/stock_tool/dashboard/components/data_quality.py`（新增）
- `tests/test_provider_registry.py`（新增）
- `tests/test_provider_policies.py`（新增）
- `tests/test_data_evidence_center.py`（新增）

**新增測試**

- timeout、429、短暫 5xx、永久 4xx、schema drift、空資料。
- retry 次數與 backoff 上限。
- cache fresh、stale、expired 與 forced refresh。
- fallback 不會把 sample data 標為線上資料。
- 錯誤訊息含摘要、可用內容、已嘗試來源與下一步。

**驗證方式**

- 使用 recorded HTTP fixtures，避免 CI 依賴真實網路。
- 真實網路僅做非阻塞 smoke，不作為唯一驗收依據。

**最大風險**

重試策略放大外部服務負載或讓 UI 等待過久。

**Rollback**

provider policy 可設定為 single-attempt legacy 模式；registry 失敗時維持既有 provider 順序與 cache fallback。

### Sprint 9：產業鏈、題材與文件證據

**目標**

把題材知識從 Python 常數外部化，建立 relation type、confidence、source、verified_at，並讓 PDF 摘要至少能引用頁碼。

**預計修改或新增檔案**

- `src/stock_tool/concepts.py`
- `src/stock_tool/concept_repository.py`（新增）
- `src/stock_tool/company_research.py`
- `src/stock_tool/serenity_agent.py`
- `src/stock_tool/research_reports.py`
- `src/stock_tool/dashboard/pages/discovery.py`（新增）
- `data/sample/concept_stocks.csv`
- `tests/test_concept_relations.py`（新增）
- `tests/test_report_citations.py`（新增）

**新增測試**

- HBM、封裝、CoWoS、人形機器人等固定 evidence fixtures。
- 核心製造、設備材料、設計平台、下游需求、間接受益分類。
- 無來源關係不得標為高信心。
- PDF 摘要引用頁碼並保留原文位置。
- NVIDIA/AMD 不被分類為封裝代工廠的反例測試。

**驗證方式**

- 由人工審核一組固定題材的 precision，而不是只看結果數量。
- 每筆關聯可從 UI 回到來源與驗證日期。

**最大風險**

題材資料快速過期，或以少量人工資料製造「完整知識圖譜」錯覺。

**Rollback**

新知識表採版本化匯入；保留上一版本資料集。新匹配器信心不足時顯示無結果，不回退到模糊大量配對。

### Sprint 10：Benchmark、可重現報表與 v1.2 發布

**目標**

讓 benchmark 成為一等資料來源，報表加入 reproducibility manifest、input hash、provider attempts、模型與參數版本，完成 v1.2。

**預計修改或新增檔案**

- `src/stock_tool/reports/models.py`
- `src/stock_tool/reports/excel.py`
- `src/stock_tool/reports/html.py`
- `src/stock_tool/reports/charts.py`
- `src/stock_tool/backtest/metrics.py`
- `src/stock_tool/application/reporting.py`（新增）
- `tests/test_report_manifest.py`（新增）
- `tests/test_benchmark_golden.py`（新增）
- `docs/release/v1.2-checklist.md`（新增）

**新增測試**

- benchmark 與策略使用相同起訖日及交易日對齊。
- input hash、參數、成本與 provider metadata 可重現。
- Excel/HTML 缺資料顯示一致。
- 相同輸入生成相同 deterministic manifest。

**驗證方式**

- Golden dataset 手算 benchmark return、drawdown 與 excess return。
- 使用報表 manifest 重新執行研究並比對關鍵輸出。

**最大風險**

報表格式變更破壞既有使用者流程或 Excel 相容性。

**Rollback**

保留 report schema version 與 legacy exporter 一個版本週期；新欄位只追加，不刪除舊工作表與必要欄位。

### Sprint 11：Point-in-Time 與 Available Date

**目標**

建立 historical universe、delisted placeholder/import schema、fundamental filing date/available date，防止策略使用尚未公開的資訊。

**預計修改或新增檔案**

- `src/stock_tool/data/universe.py`（新增）
- `src/stock_tool/data/corporate_models.py`（新增）
- `src/stock_tool/fundamentals/models.py`（新增）
- `src/stock_tool/fundamentals/loader.py`
- `src/stock_tool/backtest/engine.py`
- `src/stock_tool/backtest/config.py`（新增或整理）
- `tests/test_point_in_time_universe.py`（新增）
- `tests/test_fundamental_available_date.py`（新增）

**新增測試**

- 公告日前基本面不可見。
- universe 成員依日期變動。
- 無 historical universe 時產生 survivorship warning。
- delisted 資料缺失時不宣稱已解決 survivorship bias。

**驗證方式**

- 小型人工 point-in-time fixture 手算每個日期可用資料。
- 檢查所有基本面策略只讀 available data。

**最大風險**

免費資料源無法提供完整歷史 universe，導致能力被過度宣稱。

**Rollback**

新 point-in-time 模式必須顯式啟用；缺資料時退回「警告模式」，不退回默默使用今天成分股的模式。

### Sprint 12：策略 Registry 與策略健檢

**目標**

建立 strategy registry、walk-forward、out-of-sample 與參數敏感度；策略頁從績效展示改為研究健檢。

**預計修改或新增檔案**

- `src/stock_tool/strategies/registry.py`（新增）
- `src/stock_tool/backtest/validation.py`（新增）
- `src/stock_tool/backtest/engine.py`
- `src/stock_tool/backtest/metrics.py`
- `src/stock_tool/dashboard/pages/strategy.py`（新增或遷移）
- `tests/test_strategy_registry.py`（新增）
- `tests/test_walk_forward.py`（新增）
- `tests/test_parameter_sensitivity.py`（新增）

**新增測試**

- Registry 自動讀取 name、parameters、description、risk notes。
- Train/test 日期嚴格分離。
- Walk-forward 每一窗只使用當時資料。
- 參數敏感度不改寫原策略參數。
- 小樣本與單一最佳參數產生 overfitting warning。

**驗證方式**

- 使用合成資料驗證無 look-ahead。
- 比較樣本內、樣本外與成本後績效。

**最大風險**

功能看似專業，但錯誤切窗反而引入隱性未來資訊。

**Rollback**

保留現有單次回測路徑；新健檢作為獨立 validation layer，若失敗不影響既有 BacktestEngine。

### Sprint 13：Corporate Actions 與 Benchmark 正確性

**目標**

支援 dividends、splits 與 corporate action audit，明確定義 adjusted/unadjusted price 使用規則。

**預計修改或新增檔案**

- `src/stock_tool/data/corporate_actions.py`（新增）
- `src/stock_tool/data/cleaner.py`
- `src/stock_tool/backtest/broker.py`
- `src/stock_tool/backtest/portfolio.py`
- `src/stock_tool/backtest/metrics.py`
- `tests/test_corporate_actions.py`（新增）
- `tests/test_adjusted_price_policy.py`（新增）

**新增測試**

- Split 前後持股數、成本與市值守恆。
- Cash dividend 現金流入與稅費政策。
- adjusted price 不與 dividend cash flow 重複計算。
- benchmark 使用相同 corporate action policy。

**驗證方式**

- 以可手算的 split/dividend golden dataset 對帳。
- Equity curve 每日現金、持股、市值與總資產核對。

**最大風險**

重複調整價格與現金股利，導致報酬高估。

**Rollback**

corporate action policy 版本化；舊報表標示 legacy policy。新政策無法驗證時禁止混用，不自動轉換既有結果。

### Sprint 14：Portfolio Ledger、多幣別與完整帳務

**目標**

建立不可變交易流水、現金流水、實現/未實現損益、股利、FX 與缺價狀態。

**預計修改或新增檔案**

- `src/stock_tool/portfolio_management.py`
- `src/stock_tool/portfolio/ledger.py`（新增）
- `src/stock_tool/portfolio/fx.py`（新增）
- `src/stock_tool/application/portfolio.py`（新增）
- `src/stock_tool/dashboard/pages/portfolio.py`（新增或遷移）
- `tests/test_portfolio_ledger.py`（新增）
- `tests/test_portfolio_fx.py`（新增）
- `tests/test_portfolio_missing_price.py`（新增）

**新增測試**

- 零股、整股、部分賣出與平均成本。
- 手續費、稅費、股利與 FX 現金流。
- 缺價部位不計算虛假權重。
- Ledger replay 產生一致 portfolio snapshot。

**驗證方式**

- 人工帳本逐筆對帳。
- 匯入既有持股後比較 v1.2 顯示與新 ledger 的可比欄位。

**最大風險**

成本基礎、幣別或歷史持股資料不完整，無法可靠轉換。

**Rollback**

既有持股資料只讀匯入新 ledger，不覆寫原檔；轉換不完整時維持 legacy portfolio 並標示待補資料。

### Sprint 15：Portfolio Risk、CI Gate 與 v2 發布

**目標**

加入產業/因子曝險、scenario stress、資料不足降級；建立 pytest、coverage、ruff、mypy、安全掃描 gate，完成 v2。

**預計修改或新增檔案**

- `src/stock_tool/risk/rules.py`
- `src/stock_tool/risk/scenarios.py`（新增）
- `src/stock_tool/application/risk.py`（新增）
- `src/stock_tool/dashboard/components/portfolio_risk.py`（新增）
- `pyproject.toml`
- `.github/workflows/quality.yml`（若採 GitHub CI，新增）
- `tests/test_risk_scenarios.py`（新增）
- `tests/test_sector_exposure.py`（新增）
- `docs/release/v2-checklist.md`（新增）

**新增測試**

- 單股、產業、幣別集中度。
- 波動、利率、匯率與市場跌幅情境。
- 缺少 sector/factor 時產生 unknown，不硬算。
- CI 對格式、型別、安全與測試失敗正確阻擋。

**驗證方式**

- 固定 portfolio fixture 手算曝險與 stress loss。
- v2 全流程 E2E 與 Windows clean-machine release candidate。

**最大風險**

Scenario 數字被誤解為預測或精準 VaR。

**Rollback**

Risk scenario 是附加分析，不修改 ledger；若模型有問題可停用 scenario UI，保留既有持倉與基本風控。

### Sprint 16：有引用的 AI 協助整理與研究健檢

**目標**

讓 AI 只讀取 `ResearchSnapshot` 與證據庫，執行摘要、關聯說明與論點健檢；所有事實有引用，所有推論有標籤，無 AI 時仍有 deterministic fallback。

**預計修改或新增檔案**

- `src/stock_tool/research/evidence.py`（新增）
- `src/stock_tool/research/assistant.py`（新增）
- `src/stock_tool/research/citations.py`（新增）
- `src/stock_tool/company_research.py`
- `src/stock_tool/serenity_agent.py`
- `src/stock_tool/dashboard/components/research_assistant.py`（新增）
- `tests/test_research_assistant.py`（新增）
- `tests/test_ai_citation_policy.py`（新增）
- `tests/test_ai_fallback.py`（新增）

**新增測試**

- AI 不得改寫 deterministic score、price、metrics。
- 沒有來源的事實不進入 facts 區。
- 引用不存在、過期或衝突時降低信心並警告。
- 無 API key、離線、timeout 時退回本機規則摘要。
- Prompt injection 存在於上傳文件時不得改變系統規則或讀取敏感設定。

**驗證方式**

- 固定 evidence fixtures 與 mock model output contract tests。
- 人工抽查事實、引用、推論與 missing evidence。

**最大風險**

AI 產生無來源事實、過度自信結論、洩漏文件或 API key。

**Rollback**

AI 是獨立 feature flag；停用後 Research Workspace 使用既有 deterministic 摘要，所有核心研究與報表仍可運作。

### Sprint 17：研究庫、文件生命週期與備份還原

**目標**

完成研究庫：保存研究快照、報表、文件 metadata、頁碼引用、版本與刪除/備份政策；不在此 Sprint 加 OCR。

**預計修改或新增檔案**

- `src/stock_tool/research/library.py`（新增）
- `src/stock_tool/research/document_store.py`（新增）
- `src/stock_tool/research_reports.py`
- `src/stock_tool/application/reporting.py`
- `src/stock_tool/dashboard/pages/library.py`
- `tests/test_research_library.py`（新增）
- `tests/test_document_lifecycle.py`（新增）
- `tests/test_backup_restore.py`（新增）

**新增測試**

- 儲存、搜尋、重新開啟與刪除研究快照。
- 引用文件移除後顯示 broken citation，不保留假連結。
- 備份與還原後 hash、版本與引用一致。
- 私人文件不進入 release artifact。

**驗證方式**

- 建立研究、關閉應用、重新開啟、還原備份的 E2E。
- 驗證研究快照仍能重現或明確標示 provider 已不可用。

**最大風險**

私人研究文件、著作權內容或持倉資料被誤打包或意外外洩。

**Rollback**

研究庫使用獨立 user-data 目錄與 manifest；升級前備份。新索引失敗時仍可按檔案與 metadata 直接讀取。

### Sprint 18：Windows Installer、簽章、更新與降版

**目標**

把 onedir 工程成品轉為正式 Windows 安裝流程，加入 code signing、版本升級、解除安裝、資料保留與 rollback。

**預計修改或新增檔案**

- `launcher.py`
- `StockTool.spec`
- `build_exe.bat`
- `installer/StockTool.iss` 或等效 installer 設定（新增）
- `installer/update_manifest.json`（新增）
- `scripts/sign_release.ps1`（新增）
- `scripts/verify_release.ps1`（新增）
- `tests/test_installer_manifest.py`（新增）
- `tests/test_user_data_paths.py`（新增）

**新增測試**

- 首次安裝、覆蓋升級、降版、解除安裝與保留使用者資料。
- 簽章與 checksum 驗證。
- port 8501/8502、無瀏覽器、自動開啟失敗與無寫入權限。
- 更新中斷後可恢復上一版本。

**驗證方式**

- 乾淨 Windows 10/11 VM。
- 標準使用者權限與無管理員權限情境。
- Windows Defender 與 SmartScreen 驗證紀錄。

**最大風險**

更新或解除安裝誤刪使用者資料，或簽章流程不穩造成無法發行。

**Rollback**

程式與使用者資料分離；更新採 side-by-side staging，驗證成功後才切換。保留上一簽章版本 installer 與 rollback manifest。

### Sprint 19：v3 Release Candidate 與正式發布

**目標**

凍結功能，完成安全、授權、效能、可用性、文件、clean-machine 與產品 acceptance，正式發布 v3。

**預計修改或新增檔案**

- `pyproject.toml`
- `README.md`
- `使用教學_簡易版.txt`
- `CHANGELOG.md`（新增）
- `SECURITY.md`（新增）
- `PRIVACY.md`（新增）
- `THIRD_PARTY_LICENSES.md`（新增）
- `docs/release/v3-checklist.md`（新增）
- `tests/e2e/test_product_acceptance.py`（新增）
- `tests/performance/test_large_dataset.py`（新增）
- `tests/security/`（新增）

**新增測試**

- 十項核心能力完整 acceptance journey。
- 台股上市、上櫃、美股、cache、offline、partial data。
- 大型資料效能與記憶體上限。
- dependency vulnerability、secret scan、SBOM 與 license gate。
- accessibility、鍵盤操作、縮放與主要視覺回歸。

**驗證方式**

- Release candidate 連續七天不改功能，只修 blocker。
- 兩台乾淨 Windows 裝置或 VM 完成安裝、升級、研究、匯出、備份、還原與解除安裝。
- 所有 P0/P1 acceptance criteria 簽核。

**最大風險**

在 RC 期間持續加入功能，導致無法形成穩定發布基線。

**Rollback**

正式發布採 staged rollout；保留 v2 與 v3 RC installer、checksum、資料 migration 文件。若出現 blocker，停止發布並回到上一簽章版本。

## 6. Architecture Migration

### 6.1 不要動

在沒有對應 golden tests 前，下列核心行為不重寫：

1. 技術指標公式與不使用未來資料的 rolling/EMA 邏輯。
2. BacktestEngine 的 T 日訊號、T+1 成交不變量。
3. BrokerSimulator 的現金、手續費、稅費與滑價扣除順序。
4. RiskManager 每筆訂單前 risk gate 與 rejected order 紀錄。
5. 現有 StrategyBase 公開介面。
6. CSV/Excel loader 與 cleaner 已驗證的資料品質規則。
7. CLI 既有指令的基本相容性；可降級為進階工具，但不任意破壞。
8. 既有 sample fixtures，除非建立版本化替代資料並保留來源。

### 6.2 一定重構

1. `dashboard/app.py`：拆成 shell、pages、components、state 與 application services。
2. `concepts.py`：拆成 knowledge data、repository、matching、ranking 與 source metadata。
3. Symbol/Market：建立單一 domain model。
4. Provider：建立 registry、result/error contract 與 reliability policy。
5. Data provenance：建立 ingestion run、source metadata、quality report 與資料版本。
6. Storage：建立 repository 與 migration，不讓 UI 直接操作散落 CSV/SQLite path。
7. Missing data：統一 `missing`、`unknown`、`not applicable` 與 `stale`。
8. Application service：UI 只呼叫 `AnalysisService`、`PortfolioService`、`ReportService` 等 use case。
9. User data：與 sample/release artifact 分離。
10. Report：加入 schema version 與 reproducibility manifest。

### 6.3 延後

1. 完整 event-driven backtest engine。
2. 即時行情與盤中事件流。
3. 分散式運算與雲端 queue。
4. Plugin marketplace。
5. 手機原生 App。
6. 多使用者與權限系統。
7. OCR 與複雜表格辨識。
8. 自動下單與券商 adapter。
9. 進階圖表引擎替換。
10. 自動生成或最佳化交易策略。

### 6.4 遷移方法

採 Strangler Pattern：

```text
Legacy Dashboard
  -> Adapter
  -> New Application Services
  -> Existing Domain Calculations

New Research Workspace
  -> New Application Services
  -> Existing Domain Calculations
```

每個新服務先服務舊 UI，再服務新 UI。新 UI 通過 E2E 後才移除舊入口。資料庫 migration 只採 additive-first，至少保留一個版本的舊 reader/exporter。

## 7. UI Migration

### 7.1 最終保留的主頁面

1. 研究首頁。
2. 探索。
3. 策略。
4. 持倉。
5. 研究庫。
6. 設定。

### 7.2 從主導航移除

1. 資料匯入。
2. 自動抓資料。
3. 單檔股票分析。
4. 技術指標。
5. AI 分析與評分。
6. 基本面評分。
7. 投資組合風險。
8. 報表下載。

這些能力不是刪除，而是改為 Research Workspace、資料證據中心、策略或持倉流程中的情境功能。

### 7.3 合併對照

| 舊頁面或能力 | 新位置 |
|---|---|
| 首頁 Dashboard | 研究首頁 |
| 資料匯入 + 自動抓資料 | 搜尋後自動執行；手動補救位於研究庫/資料狀態 |
| 單檔股票分析 + 技術指標 + 基本面 + AI 分析 + 股票評分 | Research Workspace |
| 產業/概念股查詢 + Screener + Watchlist | 探索 |
| 策略回測 + benchmark + 成本 + risk gate | 策略 |
| 投資組合管理 + 投資組合風險 | 持倉 |
| PDF 摘要 + 資料來源 + 歷史研究 | 研究庫 |
| 報表下載 | 各 Research Workspace、策略、持倉頁的匯出動作 |

### 7.4 首頁重新設計

首次開啟：大型全域搜尋、三個示例、簡短風險聲明。  
回訪首頁：繼續研究、自選股變化、持倉風險、最近題材、待補資料。  
首頁禁止：空白大表格、provider 技術細節、十多個功能按鈕、假即時新聞瀑布。

### 7.5 Research Workspace 形成方式

Research Workspace 使用單一 `ResearchSnapshot`，並具有明確狀態機：

```text
EMPTY
  -> RESOLVING_SYMBOL
  -> HYDRATING_DATA
  -> PARTIAL_READY
  -> READY
  -> STALE
  -> REFRESHING

任何狀態
  -> RECOVERABLE_ERROR
  -> PARTIAL_READY 或 READY
```

第一層顯示公司、分數、優缺點、風險與資料可信度；第二層顯示圖表、產業鏈、估值情境與策略健檢；第三層顯示原始資料、公式、交易、provider attempts 與引用。

## 8. Data Flow

### 8.1 對原始順序的修正

`Provider → Cache → Indicators → Scoring → Portfolio → Report → AI` 不適合作為正式 canonical flow，原因有三個：

1. Provider 原始資料在進入 cache 前必須先標準化與品質檢查，否則 cache 會保存不可信格式。
2. Portfolio 不是每次個股評分的必要前置步驟，而是 Research Snapshot 的一個可選 consumer。
3. AI 必須在 deterministic calculations 與 evidence 完成後運作；Report 應最後封裝 deterministic 結果、AI 協助摘要與引用，因此不是 `Report → AI`。

### 8.2 正式資料流

```text
User Query / Import
  -> SymbolResolver
  -> ProviderRegistry
  -> ProviderResult + DataSourceMetadata
  -> Normalize / Clean / Validate
  -> QualityReport
  -> Cache + Repository + IngestionRun
  -> DataSnapshot
       |-> Price Data -> Indicators -> Technical Score
       |-> Fundamentals -> Fundamental / Valuation Score
       |-> Price + Benchmark -> Risk Score
       |-> Company / Concept / Documents -> Evidence Graph
       |-> Strategy -> Backtest -> Strategy Health
       |-> Holdings -> Portfolio Ledger -> Portfolio Risk
  -> Deterministic ResearchSnapshot
  -> AI-assisted Summary / Thesis Health Check
       - facts require citations
       - inference is labeled
       - never mutates scores or source data
  -> Report Renderer + Reproducibility Manifest
  -> UI / Excel / HTML / PDF
```

### 8.3 各階段正式產物

| 階段 | 輸出物 | 不允許的行為 |
|---|---|---|
| Provider | `ProviderResult` | 直接把未知 schema 傳給 scoring |
| Normalize/Quality | `QualityReport` | 默默補假資料 |
| Cache/Storage | `DataSnapshot` + provenance | 把 sample 說成 online |
| Indicators/Fundamentals | Deterministic features | 使用未來資料或未公告財報 |
| Scoring | `ScoreResult` + coverage | 資料不足仍換算完整 100 分 |
| Backtest | `BacktestResult` + assumptions | 同日訊號同日成交 |
| Portfolio | `PortfolioSnapshot` + missing price state | 缺價仍算完整權重 |
| AI | `AIResearchNote` + citations | 修改 deterministic 結果或生成無來源事實 |
| Report | `ReportManifest` | 遺漏資料版本、成本、參數或風險聲明 |

## 9. Testing Plan

### 9.1 每 Sprint 新增的 pytest

| Sprint | 主要 pytest 檔案 | 驗證重點 |
|---:|---|---|
| 1 | `test_regression_baseline.py` | 現有公開行為與 golden baseline |
| 2 | `test_domain_models.py`, `test_provider_contracts.py` | 統一 symbol/provider/missing contract |
| 3 | `test_data_hydration_service.py`, `test_analysis_service.py`, `test_ingestion_runs.py` | 一次研究 orchestration 與 provenance |
| 4 | `test_dashboard_navigation.py`, `test_dashboard_state.py` | 六導航與狀態機 |
| 5 | `test_research_workspace.py` | 研究快照、評分、優缺點、風險、來源 |
| 6 | `test_research_journey.py`, `test_release_layout.py`, `test_exe_smoke.py` | E2E 與 Windows 發行 |
| 7 | `test_database_migrations.py`, `test_research_repositories.py` | schema 升級、備份、資料隔離 |
| 8 | `test_provider_registry.py`, `test_provider_policies.py`, `test_data_evidence_center.py` | retry、TTL、fallback、錯誤 UX |
| 9 | `test_concept_relations.py`, `test_report_citations.py` | 產業鏈角色、來源、信心與頁碼 |
| 10 | `test_report_manifest.py`, `test_benchmark_golden.py` | 可重現報表與 benchmark correctness |
| 11 | `test_point_in_time_universe.py`, `test_fundamental_available_date.py` | survivorship 與公告日偏誤 |
| 12 | `test_strategy_registry.py`, `test_walk_forward.py`, `test_parameter_sensitivity.py` | 策略健檢、切窗與 overfitting |
| 13 | `test_corporate_actions.py`, `test_adjusted_price_policy.py` | split、dividend、adjusted price |
| 14 | `test_portfolio_ledger.py`, `test_portfolio_fx.py`, `test_portfolio_missing_price.py` | 帳務、多幣別、缺價 |
| 15 | `test_risk_scenarios.py`, `test_sector_exposure.py` | 情境壓力與集中度 |
| 16 | `test_research_assistant.py`, `test_ai_citation_policy.py`, `test_ai_fallback.py` | AI 引用、界線、離線 fallback、安全 |
| 17 | `test_research_library.py`, `test_document_lifecycle.py`, `test_backup_restore.py` | 研究庫與文件生命週期 |
| 18 | `test_installer_manifest.py`, `test_user_data_paths.py` | installer、升降版、資料保留 |
| 19 | `test_product_acceptance.py`, performance/security suites | 完整產品 acceptance |

### 9.2 永久回歸測試

每個 Sprint 都必須持續執行：

1. 資料清洗與缺值警告。
2. 指標不修改原始資料、不使用未來資料。
3. 回測不可同日成交。
4. 交易成本、稅費與滑價扣除。
5. 最大回撤與無交易情境。
6. RiskManager risk gate。
7. 基本面與綜合評分 missing-data 行為。
8. 報表生成。
9. CLI 基本執行。
10. Launcher 與 release layout。

### 9.3 測試分層

```text
Unit tests
  -> Contract tests
  -> Repository / migration tests
  -> Service integration tests
  -> Streamlit component tests
  -> Browser E2E
  -> EXE / installer smoke tests
  -> Clean Windows acceptance
```

真實線上 provider 測試不能成為 CI 唯一依據；CI 使用 recorded fixtures，另設排程 smoke test 監控 schema drift。

## 10. Release Plan

### 10.1 v1.1

**驗收**：搜尋到 Research Workspace、partial-data UX、評分 coverage、既有回測、基本匯出與四種資料情境。  
**打包**：Python 3.11.9 venv、PyInstaller onedir、乾淨 release directory、checksum。  
**發布**：限量 Beta；附 README、簡易教學、sample data、known limitations。  
**Go/No-Go**：clean Windows 11 smoke、完整 pytest、無 High issue。

### 10.2 v1.2

**驗收**：migration、資料證據中心、題材關係來源、benchmark、reproducibility manifest。  
**打包**：onedir；升級前自動備份 user database；release artifact 不帶開發資料。  
**發布**：Beta/Release Candidate；提供 migration notes 與資料備份指引。  
**Go/No-Go**：v1.1 資料升級與降版演練成功。

### 10.3 v2

**驗收**：point-in-time、available date、walk-forward、corporate actions、ledger、FX 與 risk scenario。  
**打包**：版本化 onedir 或 installer preview；完整 SBOM 草案與 CI gate。  
**發布**：專業研究版公開 Beta；清楚標示 historical universe 與資料授權限制。  
**Go/No-Go**：quant golden datasets、portfolio reconciliation、兩次 clean-machine acceptance。

### 10.4 v3

**驗收**：AI citations、研究庫、備份還原、正式 installer、簽章、安全與效能。  
**打包**：code-signed installer、versioned update manifest、checksum、SBOM、第三方授權文件。  
**發布**：staged rollout；先小範圍，再擴大；保留上一穩定版下載與 rollback。  
**Go/No-Go**：七天 RC freeze、零已知 High issue、Windows 10/11 acceptance、更新與降版演練。

### 10.5 每次發布固定步驟

1. 建立 release branch/tag 與 immutable source snapshot。
2. 安裝鎖定依賴並執行完整 quality gates。
3. 在乾淨目錄打包，不複製 runtime cache、private reports、portfolio 或 token。
4. 產生 checksum、SBOM、release notes 與 known limitations。
5. 在 clean Windows 執行 smoke/E2E。
6. 簽核 acceptance checklist。
7. 發布 staged artifact。
8. 監控啟動失敗、migration、provider 與 crash log。
9. 達 rollback threshold 時停止發布並恢復上一版。

## 11. Risk Register

### 11.1 全域風險

| ID | 風險 | 嚴重度 | 主要控制 |
|---|---|---|---|
| R1 | Dashboard 遷移造成既有功能回歸 | High | feature flag、adapter、E2E、legacy fallback |
| R2 | Migration 損壞使用者資料 | High | additive migration、升級前備份、restore test |
| R3 | Provider schema/rate limit 改變 | High | contract fixtures、registry、retry/TTL、scheduled smoke |
| R4 | 分數或 AI 在資料不足時誤導 | High | coverage gate、unknown、citation policy、deterministic authority |
| R5 | 回測引入 look-ahead 或 survivorship bias | High | point-in-time fixtures、available date、golden tests、warnings |
| R6 | Portfolio 帳務錯誤 | High | immutable ledger、reconciliation、golden cash-flow fixtures |
| R7 | EXE/installer 在乾淨 Windows 失敗 | High | clean VM、signed artifact、smoke automation |
| R8 | 私人資料、token 或報告被打包 | High | user-data separation、secret scan、release manifest allowlist |
| R9 | 題材資料錯誤或過時 | Medium | source、confidence、verified_at、precision review |
| R10 | Scope creep 延遲核心可信流程 | High | MVP freeze、版本 exit criteria、RC feature freeze |
| R11 | 第三方資料與文件授權不清 | High | license review、禁止未授權散布、source policy |
| R12 | Streamlit 狀態與效能限制 | Medium | service cache、state machine、performance fixtures |

### 11.2 每 Sprint 最大風險與關閉條件

| Sprint | 風險 | 關閉條件 |
|---:|---|---|
| 1 | 錯誤行為被 golden test 固化 | Golden 只鎖定已驗證不變量 |
| 2 | 新 contract 破壞下游 | Adapter equivalence tests 全通過 |
| 3 | Service 再次成為上帝物件 | Orchestration 與 calculation 邊界 review 通過 |
| 4 | Streamlit rerun 狀態錯亂 | 六狀態 component tests 與手動驗收通過 |
| 5 | Research Workspace 資訊過載 | 第一屏 usability acceptance 通過 |
| 6 | 開發機可用、乾淨機不可用 | Clean Windows EXE smoke 通過 |
| 7 | Migration 損壞資料 | Backup/restore 與重複 migration 通過 |
| 8 | Retry 造成等待或封鎖 | Timeout budget 與 rate-limit tests 通過 |
| 9 | 概念股誤配 | 固定題材 precision 與反例測試通過 |
| 10 | 報表不可重現 | Manifest replay 關鍵輸出一致 |
| 11 | 假裝解決 survivorship bias | 缺 universe 必有 warning，文件明確限制 |
| 12 | Walk-forward 隱性未來函數 | 人工切窗 fixture 全通過 |
| 13 | 股利與 adjusted price 重複計算 | Golden accounting 對帳一致 |
| 14 | Ledger/FX 成本基礎錯誤 | 逐筆人工 reconciliation 通過 |
| 15 | Stress 數字被當成預測 | UI、報表與模型限制驗收通過 |
| 16 | AI hallucination/prompt injection | Citation、安全、offline fallback tests 通過 |
| 17 | 私人文件生命週期失控 | Delete、backup、restore、release exclusion 通過 |
| 18 | 安裝/更新誤刪資料 | Side-by-side update 與 rollback 演練通過 |
| 19 | RC 期間持續加功能 | 七天 feature freeze 完成 |

## 12. 依賴關係與執行治理

### 12.1 關鍵依賴

```text
Sprint 1
  -> Sprint 2 contracts
  -> Sprint 3 services/provenance
  -> Sprint 4 UI shell
  -> Sprint 5 Research Workspace
  -> Sprint 6 v1.1

Sprint 7 storage/migrations
  -> Sprint 8 provider/evidence
  -> Sprint 9 concepts/documents
  -> Sprint 10 v1.2

Sprint 11 point-in-time
  -> Sprint 12 strategy validation
  -> Sprint 13 corporate actions
  -> Sprint 14 portfolio ledger
  -> Sprint 15 v2

Sprint 16 grounded AI
  -> Sprint 17 research library
  -> Sprint 18 Windows distribution
  -> Sprint 19 v3

```

## Roadmap extension: Sprint 20–23

The post-v3 local productization sequence is intentionally separate from formal
release, signing, promotion, and public rollout:

- Sprint 20 — Native Explore Workspace: local productization and independent
  validation complete; explainable local-index search and safe Research Workspace hand-off.
- Sprint 21 — Native Strategy Workspace: local productization and independent
  validation complete; reproducible strategy validation and stale-result binding.
- Sprint 22 — Native Portfolio Workspace: local productization and independent
  validation complete; market-qualified holdings, valuation, FX, health, risk, and stress evidence.
- Sprint 23 — Native Settings & Data Health Workspace: implementation evidence
  only; pending independent acceptance; privacy-safe local diagnostics and explicit refresh.

Sprint 20–22 are locally implemented and independently validated only. They must
not be represented as public release, signing, promotion, or rollout. Sprint 23
is implementation evidence pending acceptance. Existing Sprint 1–19 history and
the formal release baseline remain unchanged.

### Sprint 24 — Research Context & Workspace Handoff

**Status:** implementation scope approved; pending independent CTO acceptance.

**Theme and product risks:** preserve market-qualified identity while moving
between Explore, Research, Strategy, Holdings, and Library. The primary risks are
market loss (TWSE/TPEX/US collisions), stale-result reuse, duplicate rerun work,
and navigation actions that accidentally refresh or mutate user data.

**Goals:** provide one immutable, typed handoff contract and one-shot queue;
route explicit user actions across the existing workspaces; reject malformed,
unknown, conflicting, or stale contexts; and keep navigation side-effect free.

**Non-goals:** no new provider, AI/RAG, schema migration, trading behavior,
portfolio/watchlist/library auto-mutation, installer change, release, signing, or
version increment.

**Acceptance:** deterministic contract and queue tests; Explore/Library/Research
handoff tests; Strategy/Holdings identity and stale-result checks; no implicit
provider fetch or mutation; full quality, privacy, isolated EXE smoke, and
real-data zero-diff evidence.

**Rollback:** remove the Sprint 24 handoff adapter and restore the existing
workspace navigation paths; immutable saved research, portfolio data, and the
formal release baseline remain untouched.

### Sprint 25 — 台股盤後市場監控 MVP

**Status:** implementation scope approved; pending independent CTO acceptance.

**Scope and data sources:** add an explicit-update-only market overview to the
native Explore workspace.  TWSE uses the official OpenAPI base
`https://openapi.twse.com.tw/v1` and the `exchangeReport/STOCK_DAY_ALL` endpoint;
TPEx uses the official OpenAPI endpoint
`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`.
The implementation records endpoint, source, data date, fetched-at, valid and
excluded rows, coverage, and payload hash.  No third-party full-market provider,
background polling, or automatic render-time request is allowed.

**Contracts:** immutable `MarketSnapshotMetadata`, `MarketQuoteRow`,
`MarketBreadth`, `RankingEntry`, and `IndustryHeatRow` models use market-qualified
identities and deterministic ranking.  Numeric missing values, suspended/no-trade
rows, duplicates, malformed prices, partial classifications, and official-vs-
derived breadth disagreements remain explicit warnings rather than fabricated
values.  Industry heat is limited to the locally classified subset and labels the
unknown remainder.

**Cache and failure modes:** snapshots use schema-versioned, hash-validated,
atomic JSON writes under the configured runtime data directory.  Render only
replays a valid cache.  A failed update may show a complete stale cache with the
failure reason; corrupt, schema-mismatched, or absent cache is rejected or shown
as unavailable.  A partial online response remains visibly partial and is never
written as a complete cache.

**Terms review (2026-08-05):** the [TWSE OpenAPI portal](https://openapi.twse.com.tw/)
and [TWSE use terms](https://www.twse.com.tw/zh/terms/use.html), plus the
[TPEx OpenAPI portal](https://www.tpex.org.tw/openapi/), were reviewed.  The
product records source attribution and preserves payload integrity; public API
availability is not treated as permission to redistribute raw data beyond the
documented research use.

**Non-goals:** no AI prediction, target price, recommendation, trading, broker
integration, intraday monitoring, US market monitor, schema migration, formal
release, signing, promotion, or user-data modification.

**Acceptance and rollback:** parser, coverage, ranking, cache, offline/partial,
render-no-network, handoff, quality, privacy, isolated EXE, and real-data
zero-diff evidence must be reproducible.  Rollback removes the market monitor
adapter and cache reader while leaving the existing Explore, Research, Watchlist,
formal release, and user data untouched.

### Sprint 25.1 — 官方股票 universe 與分市場一致性修正

**Status:** implementation scope approved; pending independent CTO acceptance.

**Correction scope:** every TWSE/TPEx breadth and ranking view is filtered by an
official four-digit ordinary-company allow-list.  ETFs, warrants, bonds,
convertibles and other products are excluded rather than inferred as stocks;
when the allow-list cannot be obtained the view is partial/unavailable and no
quote is counted.  The TPEx parser accepts the published
`SecuritiesCompanyCode`, `CompanyName`, `TradingShares` and `TransactionAmount`
shape.  TWSE and TPEx retain independent source dates and source metadata;
combined views warn on date disagreement, and the cache schema is bumped so an
older cache is rejected safely.

Official breadth is compared only where a reliable official summary is
available; TPEx and any unavailable summary are explicitly labelled
「僅為自行推導」.  The Explore warning UI presents a compact count with
expandable details.  Existing performance history, including the 6.444-second
Excel-export failure, remains immutable in the chronological evidence record.

**Non-goals and rollback:** no new provider, prediction, recommendation,
intraday polling, or user-data change.  Rollback removes the universe adapter
and schema-2 cache reader while preserving formal release and existing user
data; a schema-1 cache is never silently upgraded.

### Sprint 26 — Daily AI Evidence-Chain Research Brief MVP

**Status:** implementation scope approved; pending independent CTO acceptance.

**Scope:** adapt the existing DailyBrief, DailyResearchLoop, DailyResearchAssistant,
and MarketMonitor cache contracts into a bounded, deterministic daily evidence-chain
brief for market-qualified portfolio and watchlist identities.  The brief labels
facts, inferences, and items to verify; records source/date/reference metadata; and
offers explicit JSON/HTML export from the Research Home.  Render is read-only and
never fetches data; generation is an explicit user action.

**AI and failure policy:** the existing assistant/provider boundary may enrich
citation-backed inferences only.  Disabled, timed-out, malformed, uncited, or
prompt-injection content falls back to deterministic local rules.  A failed run
never replaces the last successful brief.  The schema-versioned JSON is the sole
authoritative record and is atomically published below the private runtime data
root.  HTML is a disposable projection generated from validated JSON; it is not
part of persistence or recovery authority and is never treated as an atomic JSON/HTML pair.

**Non-goals:** no new provider, key, dependency, scheduler, background polling,
prediction, target price, trading instruction, MOPS/social integration, portfolio,
watchlist or Research Library mutation, installer change, signing, publication, or
version increment.

**Acceptance and rollback:** targeted scenario tests, full quality gates, privacy
and isolated EXE/browser evidence must be reproducible.  Rollback removes the
evidence-chain adapter and its private sidecars while retaining existing Daily Brief,
Research, portfolio and formal release data.  Sprint 26.1 is the evidence-contract
correction: semantic fingerprints, citation references, atomic brief persistence and
snapshot identity isolation.  Windows scheduling/notification design is deferred to
Sprint 26.2 and is not part of this implementation.

### Sprint 26 accepted baseline

**Status:** independently accepted; retained as the local implementation baseline.
The evidence-chain brief remains deterministic, citation-bound, privacy-safe, and
available from the Research Home without background network activity.

### Sprint 26.2 — Windows daily research schedule

**Status:** independently accepted; retained as the local implementation baseline.

**Scope:** add a disabled-by-default, headless daily research runner that reuses the
existing Daily Brief, Daily Research Loop, Market Monitor cache and assistant
contracts.  The default schedule is weekdays at 18:30 in Asia/Taipei.  Each run is
bounded to one process and exits with a stable status code; it never trades, mutates
Portfolio/Watchlist/Research Library, or starts a background daemon.  Successful
schema-v2 briefs are atomically published under the private runtime root; partial,
failed, skipped and duplicate attempts are separate redacted run records.

**Scheduler contract:** schedule-settings, latest-run, immutable bounded history and
an exclusive stale-safe lock are UTF-8, schema-versioned and atomic.  The injected
Windows Task Scheduler adapter supports plan/query/install/enable/disable/run-now/
uninstall.  Production activation is explicit from Settings and uses the stable
launcher with InteractiveToken, LeastPrivilege, IgnoreNew, StartWhenAvailable and
PT30M.  Acceptance uses only a unique temporary task and requires a zero-diff
Task-Scheduler before/after record; no production task is installed in this sprint.

**Non-goals:** no new provider, dependency, AI key, notification/toast, resident
daemon, automatic startup, prediction, target price, trading instruction, formal
release, signing, promotion, version increment, or real-user-data migration.

**Rollback:** disable/remove the temporary scheduler state and remove the scheduler
adapter/runner while preserving the last successful brief, existing research data,
formal release, Portfolio and Watchlist.  A corrupt or partial attempt must never
replace the last successful brief.  Windows native toast and production task
activation remain deferred until a separately accepted follow-up.

**Acceptance:** targeted and full quality gates, coverage, privacy, isolated EXE
health/CLI evidence, source archive/hash binding, temporary Task Scheduler lifecycle,
browser settings/home evidence, process/listener cleanup, and real-data zero-diff
evidence are required before independent review.

### Sprint 26.2.1 — Scheduler correction evidence

**Status:** implementation evidence prepared; pending independent CTO acceptance.

**Scope:** correct weekday XML generation (Monday through Friday), refresh-before-
idempotency ordering, immutable scheduled-run records with recoverable projections,
strict boolean settings, language-independent Task Scheduler queries, and packaged
Settings presentation for an absent production task.  Acceptance uses only a unique
nonce temporary task; the production `\\StockTool\\DailyResearchBrief` task remains
uninstalled and untouched.

**Rollback:** disable and delete the temporary task, discard isolated candidate
runtime roots, and retain the prior successful brief and all historical evidence.
No formal release, installer, version, signing state, Portfolio, Watchlist, or real
user data is changed.

**Acceptance:** targeted/full quality gates, coverage, pip check/audit, performance,
source/hash binding, guarded EXE health and CLI status evidence, temporary scheduler
create/query/disable/enable/delete with Mon–Fri XML, Settings screenshot/DOM/console,
and real-data/process/listener zero-diff.  Native browser zoom remains deferred to
formal release verification; any unavailable provider success run is recorded as a
blocker rather than represented as a pass.

### Sprint 27 — Daily research notification inbox

**Status:** implementation evidence prepared; pending independent CTO acceptance.

**Scope:** add a read-only Daily Research Inbox backed by immutable scheduled-run
records and the validated schema-v2 brief.  The inbox is bounded to the latest 30
runs, shows success/partial/skipped/already-running/failed states with concise
Traditional-Chinese reasons and next steps, and exposes JSON/HTML only when the
latest brief fingerprint and evidence references validate.  Missing, corrupt,
mismatched or unresolved content fails closed.

**Notifications:** Windows notifications are disabled by default and separate from
the scheduler.  Strict UTF-8 settings use a schema-versioned claim/outcome ledger:
an immutable claim is atomically persisted before any notifier call, and immutable
sent/unavailable/failed outcomes are written afterwards.  A claim remains the
deduplication authority when outcome or history projection publication fails, and
history is rebuildable from immutable records.  Only a newly verified successful
brief may request a notification; notifier failure never changes the brief, run
record or runner exit code.  The Windows adapter probes an already packaged
AppUserModelID and uses the built-in toast path only when that identity exists; it
never registers or invents an identity.

**Non-goals:** no resident daemon, automatic startup, production Task Scheduler
activation, new provider/dependency, trading, prediction, portfolio/watchlist/
Research Library mutation, formal release, signing, promotion or real-user-data
migration.

**Rollback and acceptance:** remove the inbox/notification projection and private
runtime sidecars while retaining immutable scheduler records and the last successful
brief.  Acceptance requires targeted/full quality gates, privacy/audit, isolated
evidence-launcher EXE/browser evidence for home/inbox/settings, notification fault
and deduplication tests, cleanup and real-data zero-diff.  Native Chrome zoom remains
deferred to formal release verification.

### Sprint 27.1 — Notification exactly-once correction

**Status:** implementation evidence prepared; pending independent CTO acceptance.

**Scope:** close the notification trust boundary without changing the Daily Research
Inbox product surface.  Claims are written atomically before send, immutable outcomes
are independently validated, filename/identity/schema/time fields fail closed, and
history is a rebuildable projection rather than an authority.  Windows capability is
shown before enablement and the adapter sends only through an existing packaged
identity using an injected, testable system runner.

**Rollback:** disable notifications and remove only the private notification sidecars;
retain scheduler records, briefs, Portfolio, Watchlist, formal release and all
historical evidence.  No registry, Start Menu, installer, AppUserModelID or production
Task Scheduler state is changed.

**Acceptance:** fault-matrix and strict-ledger tests, coverage at or above the Sprint
26.2 accepted baseline, full quality/security gates, final isolated candidate/browser
evidence, historical failed-guard index, process/listener cleanup and real-data
zero-diff.  Native Chrome zoom remains deferred to formal release verification.

### Sprint 28 — 每日 AI 盯盤：變化偵測與優先摘要

**Status:** implementation scope approved; pending independent CTO acceptance.

**Scope:** compare the two latest fully validated schema-v2 DailyResearchBrief
records by market-qualified identity and publish a deterministic, citation-bound
change summary.  The summary covers first baseline, new or worsening risk,
improvement, resolved events, follow-up changes, no-change and insufficient-data
states.  It is read-only, bounded and rendered in the Home/Inbox flow.

**Contracts:** only successful briefs whose fingerprint, references, timestamps,
market identity and source metadata validate may be compared.  The authoritative
change JSON is UTF-8, schema-versioned and atomically published; immutable
content-addressed history is rebuildable.  HTML and dashboard cards are
disposable projections.  Repeated identical inputs are idempotent.

**AI boundary:** deterministic changes and evidence references remain authority.
The existing assistant may only rewrite cited facts into Traditional Chinese;
disabled, timed-out, malformed, uncited, prompt-injection or unavailable AI
falls back to deterministic text.  No target price, prediction, buy/sell command,
new provider, key or dependency is permitted.

**Non-goals and rollback:** no background daemon, scheduler change, notification
policy change, portfolio/watchlist/research-library mutation, formal release,
signing or version increment.  Rollback removes the change-summary projection
and private history while retaining validated briefs and scheduled-run records.

**Acceptance:** targeted and full quality gates, deterministic/adversarial
comparison tests, atomic publish fault tests, privacy and isolated candidate
evidence, exact hash-bound evidence verification, process/listener cleanup and
real-user-data zero-diff evidence.  Native Chrome zoom remains deferred to
formal-release verification.

### Sprint 28.1 — Change trust and evidence correction

**Status:** implementation correction in progress; pending independent CTO
acceptance.  This correction closes cross-field integrity gaps in immutable
DailyResearchChangeSet records and replaces permissive acceptance-bundle
checking with a read-only, fail-closed verifier.

**Scope:** require exact SHA-256 identifiers, protected non-future generation
time, canonical market-qualified identity, deterministic unique changes,
status invariants and exact reference closure.  Corrupt brief history blocks a
new baseline or change projection without overwriting the latest valid
projection.  Inbox and notification claims bind a verified change fingerprint
so a changed run identifier cannot create a second notification.

**Evidence and rollback:** the verifier rejects incomplete/mixed sessions,
non-zero or absent guard exits, raw-byte rewrites, stale captures, mismatched
candidate binding, changed real data and a present production task.  It never
normalizes or writes evidence.  Rollback removes only the new private change
projection and candidate evidence; it leaves historical evidence, formal
release, scheduler, Portfolio, Watchlist and Research Library untouched.

### Sprint 29 — 每日決策中心：總經脈絡與下一個觀察條件

**Status:** implementation scope approved; pending independent CTO acceptance.

**Scope:** add a schema-versioned, citation-bound MacroSnapshot application
service and a read-only Home projection titled 「今日總經背景」. The first
provider boundary uses official FRED CSV series (CPI、核心 CPI、失業率、非農
就業、聯邦基金利率與 10Y-2Y 利差), with bounded requests, immutable
content-addressed history, first-seen/revision preservation and an atomic
authoritative JSON latest snapshot. HTML and dashboard cards are disposable
projections generated from validated JSON.

**Rules and handoff:** a versioned deterministic rule registry emits only
rising、falling、unchanged、revised、insufficient_data、stale 或 unavailable。
每個訊號包含目前／前次值、變化、資料日期、規則版本、reference IDs、下一個
可觀察條件與限制；不產生預測、目標價、買賣指令或因果宣稱。Portfolio／
Watchlist 只在 market-qualified identity 與本機分類可驗證時連結，否則顯示
「尚無可驗證對應」。DailyResearchBrief 可引用已驗證的 macro context，且
AI 失敗時維持 deterministic fallback。

**Failure modes and non-goals:** render 不連線；只有使用者明確按下更新按鈕
才呼叫官方 provider。無法取得資料時使用最後一份已驗證快照並標 stale，沒有
可靠快照則 unavailable；損壞、schema 不符、hash/reference 不符一律拒用。
不新增 provider、AI key、依賴、背景輪詢、排程、交易、推薦、即時行情、正式
發布、簽章或版本提升，也不修改 Portfolio、Watchlist、Research Library 或
真實使用者資料。

**Rollback and acceptance:** remove only the private macro snapshot/history and
Home projection while retaining existing Daily Brief and scheduler records.
Acceptance requires macro parser/provider fixtures, tamper/future-time/reference
tests, cache/history atomic fault tests, deterministic rule and UI tests, full
quality/privacy gates, one final candidate/source hash binding, isolated EXE and
browser evidence, process/listener cleanup and real-user-data zero-diff evidence.
Native Chrome zoom, installer signing and formal release remain deferred.

### Sprint 29.1 — 每日決策中心修正

**Status:** implementation evidence prepared; pending independent CTO acceptance.

**Scope:** 修正 FRED `fredgraph.csv` 的官方 `observation_date` 解析契約，並以
exact-record SHA-256 保護 generated/fetched timestamps、觀測、reference 與
snapshot status。建立 ready／partial／stale／unavailable 的 fail-closed
不變量、重複 refresh idempotency，以及 history/latest 原子發布的 fault
handling；observation period 不得冒充 release date。最終候選的線上 FRED
快照與瀏覽器證據必須由同一 isolated session 產生並以原始 bytes 綁定。

**Non-goals:** 不改 formal EXE、版本、installer、正式排程、provider 清單或
真實 Portfolio／Watchlist／Research Library；不發布、不簽章、不建立交易或
預測功能。Chrome 原生 100%／125%／150% 縮放仍 deferred to formal release。

**Rollback:** 移除本 Sprint 的 private macro snapshot/history 與 Home 投影，
保留既有 Daily Brief、scheduler、歷史 evidence、formal release 與使用者資料。
任何 provider/parser、snapshot integrity 或 evidence verifier 失敗都應拒絕
新資料並保留上一份已驗證快照。

**Acceptance:** FRED header／status／tamper／release-date 測試、atomic
history/latest fault matrix、完整 pytest/coverage/quality/privacy gates、
final candidate/source hash binding、same-session online evidence、strict
evidence verifier `passed=true` 且 `errors=[]`、process/listener/task cleanup
與 real-user-data zero-diff；最後仍交由獨立 CTO 驗收。

### Sprint 29.1 correction evidence addendum

The Sprint 29.1 correction preserves per-series observation periods and
freshness metadata, connects market-qualified Portfolio/Watchlist identities to
the read-only Home and DailyResearchBrief projections, and records bounded
period-level FRED revisions without overwriting first-seen values.  Macro
evidence is accepted only when all six official series, payload hashes,
snapshot references, capture timestamps and same-session files are bound by
the strict verifier.  Missing deterministic exposure rules remain explicitly
unavailable.  Rollback removes only the private macro revision ledger and Home
projection; formal release, scheduler, Portfolio, Watchlist and historical
evidence are retained.

### Sprint 30 — 每日 AI 盯盤：變化偵測與優先摘要

**Status:** implementation scope approved; pending independent CTO acceptance.

**Scope:** 在既有 Daily Research Brief、Daily Research Loop、Market Monitor
與 Home projection 上，加入每日決策中心的變化排序與一個明確隔離的
「預測評估實驗室（實驗）」Phase 0。實驗室只從已驗證的官方盤後排名抽取
Top／Middle／Bottom 樣本，建立 5 與 20 個交易日的不可變 PredictionRecord，
在實際資料可用後追加 PredictionOutcome。所有身份都使用 market-qualified
symbol；record、outcome、source hash 與 semantic/exact fingerprint 均可重播。

**Rules and handoff:** 每日成功的手動或排程研究流程可註冊一次當日樣本；
offline、partial、unavailable、資料不足或未知身份一律 fail closed，不建立
假樣本。註冊不下載新資料、不修改 Portfolio、Watchlist 或 Research Library，
也不產生買賣指令、目標價、勝率或報酬預測。首頁以唯讀方式依序顯示今日變化、
總經背景、每日簡報、實驗室樣本及下一個研究入口；所有輸出留在隔離 runtime root。

**Non-goals and rollback:** 不新增 ML/LLM、provider、依賴、正式排程、通知、
交易或版本提升；不把任何外部文章的市場倍增說法當作證據。回滾只移除
`data/prediction_lab` 的私有記錄與 Home 卡片，保留 Daily Brief、MacroSnapshot、
正式 release、歷史 evidence 及真實使用者資料。Acceptance 需要完整 immutable
record/outcome graph、exclusive-create fault/concurrency tests、runner/UI 整合、
candidate/source hash binding、隔離 EXE/browser evidence 與 real-data zero-diff。

### Sprint 30.2 — 個人正式使用版 v1.3.0 發布收尾

**Status:** implementation scope approved; pending independent CTO acceptance.

**Scope:** 只處理版本、發布文件、乾淨建置、internal-test installer 與發布證據。
將已核對的 RC／1.2.2 候選版本統一提升為個人正式使用版 `v1.3.0`，並由
單一版本 authority 產生 Python package、stable launcher、payload、installer、
README/release notes、manifest 與 CLI `--version`。所有成品只寫入隔離的
`release/staging-sprint30.2-v1.3.0/` 與 `artifacts/sprint30.2/`，不覆蓋正式
`release/StockTool`。

**Non-goals:** 不新增功能、provider、AI、交易、預測邏輯或 UI redesign；不修改
Portfolio、Watchlist、Research Library、資料庫、設定或正式排程；不簽章、不公開
發布、不 promotion、不建立 production task，也不在本 Sprint 改變正式 v1.2.2。

**Clean-build and lifecycle contract:** 建置輸入來自可重現的隔離 source snapshot，
不把 dirty worktree 自述為 clean checkout。stable、payload、source ZIP、internal
installer 與 unchanged formal v1.2.2 EXE 均須以 size/SHA-256/version 綁定；source
archive 必須拒絕 duplicate、forbidden、cache、token、持倉、報告與私人資料。
隔離 lifecycle 只做 clean install、repair、upgrade rehearsal、uninstall、資料保留
與 cleanup；所有 installer logs 必須複製到本輪 artifacts 並納入 hash index。

**Rollback:** 保留正式 v1.2.2 與既有使用者資料；若 v1.3.0 staging 不符合驗收，
移除隔離 staging、internal installer 與暫時 runtime/task，回到正式 v1.2.2，絕不
刪除或搬移 `%LOCALAPPDATA%\\StockTool`。

**Acceptance:** targeted/full pytest、coverage、quality/security gates、pip
check/audit、performance、isolated EXE/browser same-session evidence、installer
lifecycle、strict canonical verifier、process/listener/task cleanup、formal hash
unchanged 與 real-user-data zero-diff。Chrome 原生 100%/125%/150% 由 CTO 最終
人工驗證；實作者不得以 viewport 或合成證據冒充通過。

### Sprint 31 — UI Foundation＋研究首頁／預測評估實驗室視覺重整

**Status:** implementation evidence ready; pending independent Sol/CTO acceptance.

**Scope:** 只改善 Streamlit dashboard 的 presentation layer：建立可測試的深色
金融研究設計 token、穩定的原生元件 CSS、focus-visible 與窄寬度版面規則；重整
首頁首屏的研究總覽、資料狀態、搜尋入口與既有數字；以唯讀、緊湊卡片呈現既有
Prediction Lab summary。既有 widget key、HomeAction、Research handoff、refresh、
download、warning 與資料流保持不變。

**Non-goals:** 不修改 application/domain/data 契約或研究計算，不新增 provider、
AI、網路抓取、依賴、字型、背景工作、排程、資料庫、板塊輪動、交易、預測、
Portfolio／Watchlist／Research Library 行為，不重寫全站、不建立 installer、不改
版本或正式 release。

**Acceptance:** styles token contract、首頁 first-use/returning/loading/partial/
unavailable/error、Prediction Lab empty/ready/warning/limitation、既有 actions 與
keys、safe rendering、render 不觸發寫入／provider、targeted/full quality gates、
隔離 EXE smoke、真實首頁／實驗室瀏覽器 evidence 與 formal/installed/real-data
zero-diff。Chrome 原生 100%/125%/150% 只可記錄實作者觀察，正式人工驗證仍交由
CTO；不得以 viewport resize 或合成畫面取代。

**Rollback:** 只撤回本 Sprint dashboard styles、首頁 presentation 與對應測試／
文件；保留既有 application/domain/data、正式 v1.2.2、已安裝 v1.3.0、runtime
資料、Portfolio、Watchlist、Research Library 與歷史 evidence。

### Sprint 31.1 — 真正的首頁 UI 重構與響應式修正

**Status:** independently accepted by product owner/Sol/CTO; native Chrome zoom verified
manually on Windows; retained implementation evidence remains historical.

**Scope:** 修正 Sprint 31 僅換色與固定欄位造成的驗收缺口。首頁首屏改為由
workspace header、資料狀態、原生研究 command panel 與緊湊摘要組成的研究工作台；
Prediction Lab 改為分組樣本摘要與 5／20 日狀態矩陣。新增可測試且會安全跳脫動態
文字的 UI primitives，並以 900／600 px breakpoints 讓主要卡片與原生元件在
1707×960、1280×720、1024×768、853×768 有效 viewport 下重排。StockTool 採
單一深色產品 theme，移除目前 Streamlit 不接受的 nested light/dark 設定。

**Non-goals:** 不修改 application/domain/data、研究公式、provider、持股、自選股、
研究庫、排程、版本、installer、正式 release、已安裝 v1.3.0 或真實使用者資料；
不增加 JavaScript、外部字型、前端 framework、dependency、預測、推薦或交易能力。

**Acceptance:** HTML escaping／theme token／responsive CSS／widget key／Home state／
Prediction Lab state tests，targeted/full coverage 與既有品質門，隔離 candidate EXE
smoke，同一候選的 first-use／populated browser evidence、四種有效 viewport 的
overflow/truncation 量測、Sprint 31 舊畫面與 31.1 新畫面同尺寸對照，以及 formal／
installed／shortcut／real-data zero-diff。原生 Chrome 100%／125%／150% 只能用
瀏覽器真正 zoom 操作證明；控制面不可用時明列等待 CTO 驗證，不以 viewport 冒充。

**Rollback:** 只撤回 Sprint 31.1 的 presentation primitives、首頁編排、theme 設定、
對應測試與文件；保留所有 application/domain/data、正式 release、已安裝程式、
使用者資料與歷史 evidence。

### Sprint 32 — 每日智慧盯盤：一鍵完整研究流程

**Status:** implementation scope approved; implementation evidence pending independent
CTO/Sol acceptance.

**Scope:** 以既有 `HeadlessDailyResearchRunner` 為唯一研究流程核心，提供 Home
「執行今日研究」與 scheduler/headless 共用的 application runner。每次執行對明確的
market-qualified Portfolio／Watchlist 標的設定最多 20 檔上限，市場資料每次 run 最多
刷新一次，並將同一份市場 snapshot/hash 傳給 Daily Brief、DailyResearchChangeSet、
Prediction Lab、Inbox 與可選通知。每個 run 產生 UTF-8、schema-versioned 的六階段
manifest（target_refresh、market_refresh、brief、change、prediction_registration、
notification），保存真實 status、輸入／輸出 fingerprint、資料日期與安全錯誤原因。

**Product rules:** 只有新鮮且完整的同一市場 snapshot 才能登錄 Prediction Lab；
partial、stale、offline、unavailable、無標的或任何階段失敗都不得建立樣本，並保留
上一份成功成果。deterministic brief／change 是權威，AI 只能作為可選增強；通知沿用
既有 exactly-once 與 run lock。手動、scheduled、headless 與首頁按鈕不得各自 refresh
或建立第二套商業流程。

**Non-goals:** 不新增 provider、dependency、AI 預測、交易、買賣建議、背景 daemon、
即時輪詢、正式排程修改、Prediction Lab outcome evaluator、版本提升、installer、
正式 release、Portfolio／Watchlist／Research Library 寫入或真實使用者資料變更。
Chrome 原生 100%／125%／150% 仍由 CTO 最終人工驗收，不以 viewport resize 冒充。

**Rollback:** 移除本 Sprint runner facade、Home action、run-manifest projection 與
對應測試／文件，保留既有 Headless runner、Daily Brief、ChangeSet、Prediction Lab、
通知 ledger、正式版本與真實資料。任何 manifest、snapshot 或 atomic publish 驗證失敗
都保留上一份成功結果並拒絕不完整輸出。

**Acceptance:** contract／stage failure／idempotency／lock／notification／no-target
測試、完整 pytest 與 branch coverage、quality/privacy gates、隔離 staging EXE smoke、
同候選 browser/session evidence、candidate/source hash binding、process/listener/task
cleanup，以及 formal／installed／real-user-data zero-diff。完成後交由獨立 CTO/Sol
驗收，不在本 Sprint 宣布正式發布。

### Sprint 32.1 — 每日研究流程階段真實性修正

**Status:** implementation evidence pending independent review; no release or version
change is authorized.

**Scope:** 修正 Sprint 32 驗收發現的流程一致性問題。Home、scheduled 與 headless
共用同一個 application runner；每次有效 run 對 TWSE／TPEX 官方市場資料只執行一次
`refresh`，並將不可變的市場 refresh result／snapshot fingerprint 傳給 brief、change、
Prediction Lab、Inbox 與 notification。run manifest 由核心實際累積六個 typed stage
結果（target_refresh、market_refresh、brief、change、prediction_registration、
notification），不再由 overall status 推算。

**Product rules:** 只有本次 run 取得、狀態 fresh、內容完整且日期一致的市場 snapshot
可建立 Prediction Lab sample；partial、stale、offline、unavailable、腐敗或沒有
標的時只保留既有成功成果並明確標示 skipped／unavailable／failure。通知停用、不可用、
失敗或去重須在 manifest 如實呈現；change 保存失敗不得被記成 success。既有最多 20
個 market-qualified identities、run lock、idempotency、Portfolio／Watchlist 與真實
資料邊界全部保留。

**Non-goals and rollback:** 不新增 provider、dependency、AI、交易、背景排程、UI
大改、Prediction Lab evaluator 或版本提升；不修改 formal／installed EXE、installer、
正式排程或真實使用者資料。回滾只移除本 Sprint runner facade、typed manifest 欄位與
對應測試／證據，保留 Sprint 32 原有流程與歷史失敗紀錄。

**Acceptance:** targeted／full pytest、branch coverage、quality/privacy gates、
隔離 staging-sprint32.1 EXE success／partial／no-target smoke、同候選同 session
browser evidence、artifact hash binding、process/listener/task cleanup，以及 formal／
installed／real-user-data zero-diff；native Chrome zoom 仍交由 CTO 最終人工驗證。

### Sprint 32.1.1 — 每日研究流程階段追蹤與隔離成功證據

**Status:** implementation evidence pending independent review; no release or version
change is authorized.

**Scope:** 建立 run-level stage accumulator，讓 target_refresh、market_refresh、brief、
change、prediction_registration、notification 六個階段保留真實結果；所有下游共用
同一份本次市場 refresh snapshot／fingerprint。僅在明確的隔離 evidence mode 下使用
官方形狀 fixture，完成可重播的 success、partial 與 no-target 證據；production 預設
不啟用 fixture、不修改 provider 行為。

**Product rules:** 只有本次 fresh、完整且日期一致的市場 snapshot 才能建立 Prediction
Lab samples。任何中途例外都保留已完成階段，當前階段為 failure，後續階段為 skipped；
通知、change 保存與樣本冪等狀態不得由 overall outcome 推算。首頁只顯示簡短繁中下一步，
詳細 provider 診斷留在 manifest／log。

**Non-goals and rollback:** 不新增 provider、dependency、AI、交易、背景排程、UI 大改、
版本提升或正式發布；不修改 formal／installed EXE、installer、正式排程、Portfolio／
Watchlist 或真實使用者資料。回滾僅移除本 Sprint stage trace、隔離 fixture seam、
證據與對應測試，保留 Sprint 32 原有 runner 契約及歷史失敗證據。

**Acceptance:** targeted／full pytest、branch coverage、quality/privacy gates、
隔離 staging EXE 的 success／partial／no-target headless 與同候選同 session browser
證據、artifact hash binding、process/listener/task cleanup，以及 formal／installed／
real-user-data zero-diff；native Chrome zoom 仍交由 CTO 最終人工驗證。本節僅代表
implementation evidence，不能代替獨立驗收或正式發布核准。

### Sprint 33 — Prediction Lab Phase 1：5／20 交易日到期樣本可信結算

**Status:** implementation evidence pending independent CTO/Sol acceptance; no release or
version change is authorized.

**Scope:** 在既有 Prediction Lab immutable prediction／outcome 契約上，加入以明確、
hash-bound 市場交易日曆與價格／基準證據為輸入的 5／20 交易日到期結算。評估器由
application service 注入唯讀 provider boundary，絕不在 UI render 或 replay 隱性連網；
同一筆樣本只允許 pending → eligible → evaluated（或 evidence 不足時 unavailable）
的明確狀態轉移。Prediction Lab 顯示結算覆蓋率、5／20 日狀態矩陣、median net return、
median net excess return 與 Top／Bottom spread，且所有績效都綁定 entry／exit／benchmark
identity、實際交易日、成本與 source hash。

**Product rules:** 交易日曆由現有已驗證日期序列提供；不能以 weekday 或日曆猜測補足
缺口。entry price 必須來自不可變 prediction registration evidence，exit／benchmark
必須有完整來源、日期與 payload hash；資料不足只產生 pending／eligible／unavailable，
不得製造績效或把不存在的資料標成 evaluated。評估結果 append-only、exactly-once、
可重播且不改寫 PredictionRecord；同一輸入重跑保留既有 winner bytes。Home、scheduled、
headless 只共用同一 runner，run manifest 增加第七個 typed stage
`prediction_outcome_evaluation`，舊六階段 schema 仍可安全讀取。

**Non-goals and rollback:** 不新增 provider、dependency、AI、交易、預測推薦、
outcome evaluator 以外的統計最佳化、背景排程、即時輪詢、UI 全站重設或版本提升；
不修改 formal／installed EXE、installer、正式排程、Portfolio／Watchlist／Research
Library 或真實使用者資料。回滾只移除結算 application service、第七階段 manifest 欄位、
唯讀 UI 摘要與對應測試／證據，保留既有 Prediction Lab Phase 0 records、歷史 evidence
與六階段舊 manifest。

**Acceptance:** evaluator RED→GREEN、交易日曆／價格／benchmark／成本與狀態轉移測試、
append-only fault／restart／idempotency、七階段 runner manifest、Prediction Lab UI
空／pending／partial／evaluated／corrupt 狀態、完整 pytest 與 branch coverage、quality／
privacy／source archive gates、隔離 staging EXE／same-session browser evidence、
artifact hash binding、process/listener/task cleanup，以及 formal／installed／shortcut／
real-user-data zero-diff。原生 Chrome 100%／125%／150% 仍交由 CTO 最終人工驗證；本節
僅代表 implementation evidence，不代替獨立驗收或正式發布核准。

### Sprint 33.1 — Prediction Lab Phase 1 驗收修正

**Status:** implementation evidence pending independent acceptance; no formal release,
version change, or Sprint 34 authorization.

**Scope:** 在既有 Sprint 33 evaluator 架構上補齊正式 runtime outcome provider、可驗證
 benchmark evidence、hash-bound TWSE／TPEx／US 交易日曆、非零且版本化交易成本政策，
 並讓 dashboard、DailyResearchRunner、scheduled/headless 與 launcher 使用相同的唯讀
 provider composition。評估結果仍只允許明確狀態轉移與 append-only、可重播的 evidence。

**Product rules:** benchmark return 必須可由起訖價格與來源 hash 重新計算；raw／adjusted
 或公司行動證據不一致時維持 eligible／unavailable。缺價、缺基準、日期不足或 provider
 暫時失敗不得製造 evaluated。交易日曆不得由本機剛好存在的價格列推算，缺少某日價格
 不得改變 5／20 交易日 target。render 與重播不發網路、不寫真實資料。

**Non-goals and rollback:** 不新增 provider、dependency、AI、交易、預測推薦、UI redesign、
 正式排程或版本提升；不修改 formal／installed EXE、installer、Portfolio、Watchlist、
 Research Library 或真實使用者資料。回滾僅移除 runtime provider composition、evidence
 欄位與本 Sprint 測試／證據，保留 Sprint 33 已驗收架構與歷史失敗紀錄。

**Acceptance:** targeted／full pytest 與實際 branch coverage 至少 82.71%、Black／Ruff／
mypy／compileall／quality／pip／privacy gates、五個獨立 browser journeys（empty、pending、
eligible/retryable、evaluated、corrupt/tampered）、EXE smoke、canonical artifact hash
 verifier、process/listener/task cleanup，以及 formal／installed／real-user-data zero-diff。
原生 Chrome 100%／125%／150% 仍交由 CTO 最終人工驗證；本節僅代表 implementation
 evidence，不代替獨立驗收或正式發布核准。

### Sprint 33.1.1 — Prediction Lab 生產結算封口

**Status:** implementation evidence pending independent acceptance; no formal release,
version change, or Sprint 34 authorization.

**Scope:** 封口 Sprint 33.1 的生產組裝缺口：以版本化且 hash-bound 的 TWSE、TPEx、US
官方交易日曆作為唯一 target authority，保存市場／年份／來源／端點／取得時間／schema
與 payload hash；接入可重播的 TWSE:TAIEX、TPEX:OTC、US:SPX benchmark evidence；讓
outcome evaluation 即使沒有新增 prediction，只要存在到期或可重試樣本仍會執行。正式
dashboard、manual、scheduled/headless 與 launcher 共用同一唯讀 provider pipeline，並
維持既有 corporate-action raw/adjusted policy、版本化 round-trip cost policy、狀態與
append-only 信任邊界。

**Product rules:** 不從 weekday、個股價格日期或少量手寫假日推算交易日；缺少可驗證日曆、
benchmark、價格、公司行動證據或成本政策時，保持 eligible／unavailable／retryable，
不得製造 evaluated 或虛構績效。資料與 manifest 只使用隔離 runtime root，render 與
重播不發網路、不寫入真實資料；所有 browser／EXE／source 證據必須與同一候選雜湊綁定。

**Non-goals and rollback:** 不新增 provider、dependency、AI、交易、預測推薦、背景
排程、UI redesign 或版本提升；不修改 formal／installed EXE、installer、正式排程、
Portfolio／Watchlist／Research Library 或真實使用者資料。回滾僅移除官方日曆資料、
runtime provider composition、第七階段結算接線與本 Sprint 測試／證據，保留 Sprint 33
原有 immutable records、歷史失敗證據與正式版本。

**Acceptance:** targeted／full pytest 與同一次 branch coverage 至少 82.71%、
Black／Ruff／mypy／compileall／quality／pip／privacy gates、官方日曆案例與 benchmark
sidecar replay、runner 三種 no-target／no-new／duplicate evaluation 情境、五個
empty／pending／eligible-retryable／evaluated／corrupt-tampered journeys、candidate／
source hash binding、process／listener／task cleanup，以及 formal／installed／shortcut／
real-user-data zero-diff。原生 Chrome 100%／125%／150% 仍交由 CTO 最終人工驗證。本節
僅代表 implementation evidence，不能代替獨立驗收或正式發布核准。

### 12.2 Sprint Entry Gate

1. 上一 Sprint tests 與 acceptance 全部通過。
2. 本 Sprint 需求、非目標與 rollback 已確認。
3. 有可恢復的 source baseline 與資料備份。
4. 依賴資料與 fixtures 已準備。
5. 沒有未處理的 High issue 影響本 Sprint。

### 12.3 變更原則

1. 每個 Sprint 只處理一個主要產品風險。
2. 核心公式變更必須先有 failing test 或 golden discrepancy。
3. UI migration 與 domain migration 不在同一 commit 大量混合。
4. 所有 schema 變更先 migration test，後接 UI。
5. 所有外部 AI/provider 能力都有本機或 partial fallback。
6. 任何版本若未達出口條件，延後版本，不降低 Definition of Done。

## 13. 對 Whitepaper 與 Vision 的執行修正

本計畫不重寫兩份原文件，但對執行順序做以下必要修正：

1. **AI 不排在 Report 之後**：AI 只讀取 deterministic ResearchSnapshot；Report 最後封裝所有結果與引用。
2. **v1.1 不追求十項功能完全成熟**：先完成一條可信研究主流程，其他能力透過既有功能整合，不擴張範圍。
3. **UI 重設不能先於資料契約**：先完成 Symbol、ProviderResult、provenance 與 service，避免新首頁繼續直接耦合舊模組。
4. **AI/RAG 延到 v3**：MVP 使用可驗證的 deterministic 摘要；沒有引用基礎前不擴大 AI 宣稱。
5. **題材搜尋以準確率優先**：寧可回傳少量、有角色與來源的結果，也不為了看起來完整而大量模糊配對。
6. **Windows 發布分兩階段**：v1.1 先穩定 onedir；v3 才把 installer、code signing、update 與 rollback 當成正式交付標準。
7. **point-in-time 與 corporate actions 不塞入 MVP**：它們是專業量化正確性的必要條件，但應在資料治理成熟後進入 v2。

## 14. 最終執行判斷

本計畫真正要交付的不是更多頁面，而是四個逐步增強、每一版都能獨立使用的產品狀態：

```text
v1.1：搜尋一檔股票，得到可信研究總覽
v1.2：知道每個結論的資料與證據從哪裡來
v2：能以專業量化標準驗證策略、帳務與風險
v3：能以安全、可安裝、可更新且有引用的智慧研究產品正式交付
```

任何 Sprint 若無法提升「可信、可追溯、可重現、可交付」其中至少一項，就不應進入本 Roadmap。
