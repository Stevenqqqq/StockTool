# StockTool 目前狀態

更新日期：2026-10-23。供第三方顧問閱讀已獨立限定驗收的原始碼；產品決定與發布核准仍由 Product Owner 負責。

## 版本與閱讀基準

- GitHub：PR [#1](https://github.com/Stevenqqqq/StockTool/pull/1)，分支 `codex/sync-accepted-research-20261011`，尚未合併 main。
- 最新同步為「日常使用流程改善 v1」與「完成日線一致性 P1」的已驗收產品、必要測試及本狀態文件，保存在同一提交；本頁不填入自我參照的提交 SHA，最新 HEAD 以 PR #1 或 `git rev-parse HEAD` 為準。同步前 PR HEAD：`c1aed16fbec8b05711d1ea7b904ca464533d4798`；先前研究重點程式提交：`a75522ed618d649a8a8bb34a6701f40c55030ce5`。
- 總覽與情境日期呈現提交：`8e3825be015e5ae063e45a449a30a15242a7c5b5`。前次同步基準：`55fb4417453a539c00c8f1db5390e6d7d6b999dd`；本次核對 main：`11ee8d7438e9a06115d3ab75a99d088d4ef55d13`。
- 正式本機安裝參考仍為 **v1.4.3 的分項驗收狀態**。本分支的新原始碼、候選內部版本字串及候選驗收，均不代表正式安裝已更新。
- 先前基本面／持股來源追溯：[r2 同步帳本](accepted-fundamental-holding-sync-20261015.json)。
- 先前來源與驗收追溯：[本次來源帳本](accepted-source-sync-20261015.json)、[前次同步說明](accepted-source-sync-20261011.md)。歷史文件描述的是各自凍結當時的狀態。

- 先前來源與獨立驗收結果：[個股研究重點整合 v1 同步帳本](accepted-research-focus-sync-20261022.json)、[真實行情 P1 r2 同步帳本](accepted-real-market-sync-20261022.json)。本次兩輪的來源與驗收邊界如下。

## 最新同步：日常使用流程改善 v1＋完成日線一致性 P1

Product Owner 於 2026-10-23 確認兩輪均已通過 **G4／Antigravity 獨立限定驗收**，並授權同步既有 PR #1。這不是全產品、全量品質門檻、EXE、正式安裝或發布驗收。以下區分產品範圍與原有證據，不將實作者測試數改稱 G4 的獨立測試數。

### 日常使用流程改善 v1：保留的六個 UX 檔案

- 研究頁改用精簡共用頁首，研究重點移至總覽；重複細節可展開，但重要缺口、過期與 Synthetic 警告不折疊隱藏。
- 價量與自選股比較的來源／資料狀態改用較清楚的正文；換股入口移至上方，可直接進入既有比較並返回研究／探索。不新增模型、Provider、研究系統或評分。
- 原凍結交接的正常 UI 證據涵蓋 3006→6669→6933、三檔比較、比較跳回研究、來源展開與空白查詢保留；含 1280×720 與一個 900×720 長名稱案例。Synthetic／完全缺價格主要是回歸證據，不宣稱正常瀏覽器完整旅程；未宣稱摘要全部塞入單一首屏或完成原生縮放／全部鍵盤驗證。
- UX 凍結來源索引 SHA256：`801a7f371e839b99d8e62e2c739c328e5f4aaec144d7dc2c508ce551319529eb`。以下六檔在最新 P1 候選及本次同步中均保持 UX 驗收時的原始 bytes：

| 檔案（相對 `src/stock_tool/`） | SHA256 |
| --- | --- |
| `dashboard/components/research_header.py` | `6607bbe33bddace0781cc179119ced968eeef7d98eed33c68ee6bf47afc15c78` |
| `dashboard/components/price_volume_observation.py` | `e58e3b94ba4076590de9f4d0a1e761f032aa707483cb12b7801f0bfc7f9fb1a6` |
| `dashboard/components/watchlist_comparison.py` | `a93f2e5da533d3df0931e2a74ff0f9471d0191060ffd703500c993bf23f3a0ce` |
| `dashboard/pages/research.py` | `ecd8d4ce393a068de1785c17f45559f147df95bd6fddbaaa2fac39cf95e670ca` |
| `dashboard/shell.py` | `f0785e34035f122c10ed635481480f7feba0c2b0da41a6a43b7004b479654b75` |
| `dashboard/styles.py` | `cf2b6d1ba0119e1565c4f51c1a95a4f11258805af1b19a79e7723beb65fd41ae` |

### 完成日線一致性 P1：修復結果

- 沿用 `application/completed_daily_prices.py`，依明確市場與逐列原始 `fetched_at` 判定完成日線；不借用 `checked_at`、讀取時間或其他市場身分。未改台灣18:30／美東18:00保守門檻，盤中快取不因重讀或重啟而升格。
- `dashboard/app.py::_portfolio_price_context` 在合併 SQLite／session 前過濾，保護首頁、手動每日研究及估值；盤中 session 不能蓋掉同市場＋代號＋日期的有效收盤。摘要來源日期使用過濾後實際行情日，不再沿用資料包的盤中日期。
- `application/daily_research_scheduler.py::_load_price_context` 同樣保護背景每日研究與持股發布；行情日期與檢查時間分開保存。
- `application/holding_analysis.py` 的單股分析及 `validated_holding_prices` 都使用過濾後副本，canonical valuation 不會重新吃回原始盤中價；週末／離線參考估值、FX 過期／未知拒絕、缺價與價格衝突安全規則維持。
- `application/daily_holdings.py` 與 `dashboard/components/daily_holdings.py` 對舊保存摘要補上讀取保護：即使雜湊合法，未完成日線也不可繼續顯示為收盤估值／訊號或作比較基準；原檔保留，正常更新可形成有效新基準。
- 最新 P1 凍結來源索引 SHA256：`0ab4b817adb26044cc2e2ee4e2317d40308cbe6804b51104951be89e6c128492`，211 檔。P1 相對 UX 基準只變更六個產品檔及 `test_dashboard.py`；六個 UX 產品檔未變。本次只同步兩輪差異及必要測試，不整包覆蓋工作樹。
- 原實作證據：凍結候選相關測試 **259 passed**；合成正常來源首頁 AppTest 保留原始100／999兩列，摘要取前一完成日收盤100、兩股市值200，重讀一致且隔離行情／sidecar／持股輸入雜湊不變。這些數字不是本輪重跑，也不是實際 EXE／瀏覽器畫面驗收。

### 品質與交付限制：未解決、未豁免

- 原 P1 全量紀錄為 **2118 passed／8 failed／3 warnings，exit 1**；覆蓋率83.62%僅表示原78.50%門檻達標，不能抵銷失敗。
- 八項在前一已凍結來源也已重現，**仍未解決，沒有取得豁免，不視為全量通過**：`test_research_document_workspace.py` 三項舊 UI fake 缺 `markdown`；`test_sprint51_research_integrity.py` 五項舊 fixture 缺可用完成日線，涉及三項來源與兩項 score／backtest 呼叫斷言。本次不修改這兩個檔案。
- P1 修改的13檔 Black、17檔 Ruff 與 compile 自測通過；擴大 Black 時未修改的 `test_daily_research_loop.py` 尚有格式差異，mypy 缺 pandas stubs 仍未通過。沒有以限定驗收抹除這些品質限制。
- 本輪**只做凍結檔案一致性、Git 差異與隱私檢查**；不重新開發、跑測試／驗收或建置。同步為 **12個產品檔＋8個必要測試＋本狀態文件，共21檔**，其餘未驗收修改留在本機。
- **本輪沒有新 EXE、EXE UI 或正式安裝／生命週期驗收**。正式本機安裝仍為v1.4.3分項狀態，guest lifecycle既有豁免、空研究庫與捷徑雙擊等交付限制維持；不因來源同步提升。
- 真實資料資格仍 **incomplete／正式 Scenario Research NO-GO**。保守完成日線判定不證明歷史交易日、公司行動或來源調整 coverage 完整；不修改原始行情、回測引擎或既有資格門檻。
- Yahoo行情延遲、量能／價格調整口徑、部分公司資料缺漏等限制保留。既有研究庫與歷史內容不批次追溯重算；未宣稱清理所有歷史結果。
- 不上傳本機驗收報告／截圖、機器路徑、原始擷取、runtime、快取、憑證、持股或 EXE；未安裝、發布、force push 或合併 main。歷史章節的狀態與數字只代表各批當時範圍。

## 目前架構與程式入口

以 Python／Streamlit 本機介面為主，UI 使用 application 層組裝的研究快照；行情、公司文件、評分與資料日期保留各自來源。資料與快取放在使用者 runtime，程式庫、策略計算及外部 AI 傳送邊界分開。

| 層次 | 主要入口（相對 repository 根目錄） |
| --- | --- |
| 啟動、導覽、研究組裝 | `src/stock_tool/dashboard/app.py`、`dashboard/shell.py`、`dashboard/pages/research.py` |
| 免費行情與快取 | `src/stock_tool/data/auto_fetch.py`、`data/storage.py`、`yfinance_runtime.py` |
| 完成日線與研究快照 | `src/stock_tool/application/completed_daily_prices.py`、`application/research_snapshot.py` |
| 公司證據與中文說明 | `src/stock_tool/company_research.py`、`company_dossier.py`、`company_explanation.py` |
| 共用標的名稱 | `src/stock_tool/application/instrument_names.py`、`dashboard/instrument_names.py` |
| 圖表、價量與情境呈現 | `src/stock_tool/dashboard/components/research_chart.py`、`price_volume_observation.py`、`scenario_reference_presentation.py`、`risk_summary.py` |
| 持股與每日整理 | `src/stock_tool/application/holding_analysis.py`、`daily_holdings.py`、`daily_holdings_job.py`、`daily_research_runner.py` |
| 研究保存與可選 AI | `src/stock_tool/research/library.py`、`work_session.py`、`public_selection.py`、`public_request.py`、`citations.py`、`groq_transport.py` |
| 策略與回測證據 | `src/stock_tool/application/strategy_workspace.py`、`strategies/registry.py`、`backtest/engine.py`、`backtest/trade_evidence.py` |
| 合成 Scenario console | `src/stock_tool/application/scenario_research.py`、`application/scenario_store.py`；檢視入口 `scripts/scenario_synthetic_smoke.py` |

## 已實作與已驗收範圍

| 流程 | 可用能力與驗收邊界 |
| --- | --- |
| 個股研究 | 搜尋股票、免費行情、公司證據、部分評分、圖表、風險與來源。正常 3006 流程曾以隔離候選實際查詢供應商並操作畫面；未保證所有股票或免費供應商永久完整。 |
| Research Overview | 有公司詳細資料時，總覽仍直接顯示 K 線／價格線、SMA20／60、成交量與簡短觀察。獨立合成 EXE 已驗期間、股票、頁籤、寬窄畫面、缺漏與表格備援；不足不補造 OHLC 或成交量。 |
| 持股與每日整理 | 自動更新、中文變化摘要、保存去重、跳至研究、斷線保留與重啟已分項驗收。程式內背景檢查與既有排程有各自啟動條件，不承諾關閉程式後仍持續執行。 |
| 標的名稱與首屏 | 上市、上櫃及 ETF 官方來源分開；市場＋代號共用名稱，更新失敗保留最後有效名稱。中文業務、價格日期、待查問題及重要缺口在首屏呈現。 |
| 本機研究與 AI | 研究庫與版本化工作階段分開保存。外部 AI 使用公開公司證據白名單、傳送預覽／選取清單與引用檢查；私有持股不應外送。本機整理不能冒充外部模型。本次沒有新增服務、費用或外部 AI 實測。 |
| Research Integrity／Backtest Evidence | strict point-in-time、公司行動安全拒絕與失效時清除舊績效已驗收。區分 fills／完整交易，提供費稅滑價一致的交易品質、MFE／MAE；缺可靠 high／low 或無完整交易時如實 unavailable。 |
| Scenario Research v1 | **僅合成 console 流程已驗收**：qualification gate、Breakout lifecycle、OOS 狀態隔離、案例證據、allocation／全數退出、版本化保存與離線重放。執行入口只允許明確合成目的及 `SYNTH_` 身分。未接正式研究 UI、未開放真實資料正式研究或有效性比較。 |

## 10/11 之後的最新修復

1. **價量整合與情境日期 P1**：總覽、下方風險與風險頁籤共用日期資格。未知或晚於觀測日的情境不顯示可用價位；較早日期明示歷史參考。量能只比較觀測日與此前 20 筆有效成交量，不含當日於基準均量；不足、缺漏或日期重複時 unavailable。
2. **正常研究的資料不足修復**：修正 Windows 非 ASCII certifi 路徑的 TLS 問題，以逐位元相同公開 CA 複本處理，不關閉 TLS、不覆寫自訂 CA。修正 `fetched_at` 傳遞。局部缺資料保留價格、圖表、公司與可用評分，顯示評分項目覆蓋率及非完整總分；集中重複提示，重要缺口仍直接可見。
3. **完成日線與跨時區 r4**：原始行情保留；收盤研究只使用可確認完成的副本。依原始取得時間及市場時區判斷，當日採台灣 18:30／美東 18:00 的保守發布緩衝。盤中快取不能因數日後再讀就升格。研究副本正規化當地交易日期，價格、指標、圖表、量能、情境及保存證據一致。TWSE `2026-10-12T16:00Z` 與 US `2026-10-14T00:00Z` 均為當地 10/13；Sol 已獨立驗證 EXE 保存、新程序重開及原件不變。

4. **基本面持久性與持股快取估值 r2**：基本面新回應先限定明確市場，再把同一份結果存 CSV 及交給畫面；AUTO／舊 UNKNOWN 不借行情市場猜補，重啟保留市場身分與舊 CSV 欄位。逾 24 小時但符合既有七日期限、來源與完成收盤檢查的價格，可作明示非即時的快取參考估值；原日期與取得時間保留。FX 門檻不變；缺價、價格衝突或 FX 失效時保留可用原幣結果，拒絕完整組合總額與權重。入口為 `dashboard/app.py`、`application/holding_analysis.py`、`dashboard/pages/portfolio_workspace.py`；回歸為 `tests/test_fundamental_persistence_and_holding_reference.py`，純合成 EXE 檢視入口為 `scripts/fundamental_holding_cache_review_app.py`。

上述是正常研究的呈現與輸入安全修復，沒有更改評分公式、Entry Reference、BacktestEngine 或真實資料資格規則。一般研究中的情境參考區間，也不代表 Scenario Research 策略正式通過。

## 驗證與尚存限制

- 基本面／持股 r2 歷史候選已通過 Sol 限定範圍獨立驗收：**85 targeted passed、2000 full passed、2 warnings**；獨立總覆蓋率 **83.57073121886499%**，純分支 **74.5569875151027%**。獨立驗證 CSV 雙程序身分隔離、合成週末／離線／FX 過期／缺價／衝突，以及凍結 EXE 關閉重啟。來源與候選保持凍結；不是正式安裝或真實供應商復原驗收。
- 這些是已驗收本機工作樹的歷史結果，包含本機另存的離線實驗測試；**不是本次精選 GitHub 分支新跑出的測試數**。本輪只做差異、來源一致性、提交內容隱私及 Git 檢查，不重跑驗收或建置 EXE。
- Black 限制保留：本批六檔 formatter API 通過；repo CLI 指出兩份非本批測試檔需重排，另一次單 worker CLI 停滯中止，不宣稱全專案 CLI 通過。先前 CDP 首頁 H1 空的來源混載問題已另行修正並獨立驗收，不再列為目前阻擋。
- 公司財報、營收結構、文件日期與成長欄位可能缺漏；mixed 或缺 `available_date` 的資料不能提前用於正式歷史策略。部分評分與公司證據完整性分開，不用 AI 猜補。
- **真實資料資格 incomplete／正式 Scenario 研究 NO-GO**。TWSE/3006 固定期間 2025-02-24～06-30 的 86 日曆分項已通過，不能取代期初狀態、跨界事件、MOPS 完整性、TWT85U 缺 38 日及全年日曆差異等剩餘資格證據。沒有 3006／6669／6933 的策略有效性結論。
- 保守收盤後緩衝不宣稱個股交易狀態或公司行動 coverage 已 verified。其他市場、全股票覆蓋、完整外部 AI、歷史研究庫、窄畫面及重啟等只沿用各批實際驗證範圍，不推廣成全面通過。
- 正式 v1.4.3 的 guest lifecycle 豁免、空研究庫、捷徑雙擊等既有交付限制保留；部分隔離 runtime 仍保存。原始 EXE、安裝器、真實資料、憑證、快取、原始擷取檔及含機器路徑的驗收檔不納入本次同步。
- 原始檔依已驗收 bytes 保存，部分 diff 包含既有換行格式差異；檢視實際邏輯可用 `git diff --ignore-space-at-eol`。本輪沒有順手格式化或重新開發。

## 待 Product Owner 決定的下一步

1. 第三方顧問先審閱本頁、來源帳本及 PR 差異，決定是否需要下一批產品改善。
2. 若要將已驗收修復交付日常使用，另行核准版本化、安裝交付與必要驗證；本 PR 不自動授權。
3. 若要開放真實資料 Scenario 研究，先決定既有官方資料詢問方案，補足資格證據；不以合成通過或一般行情可讀取代。

## 自選股多檔比較 r3（2026-10-18 同步）

- 已整合正常自選股導覽，可比較 2～5 檔：共用公司名稱、有效收盤、5／20 交易日報酬、SMA20／60 相對位置、當日量／前20日均量比、日期與來源，並跳轉既有個股研究。重用 completed_daily_prices，不增加 provider、AI、策略或綜合評分。
- 同日期可依既有指標排序；日期不一致提示並停用排名。單檔或單項缺漏不清空其他結果；更新失敗保留既有行情並明示狀態。
- 入口：`src/stock_tool/application/watchlist_comparison.py`、`src/stock_tool/dashboard/components/watchlist_comparison.py`、`dashboard/app.py::_page_watchlist`。回歸：`tests/test_watchlist_comparison.py`；合成驗證入口：`scripts/watchlist_comparison_r3_review_app.py`。
- Sol 來源 UI／25 項定向、測試路徑修正、來源與候選綁定已通過。歷史完整回歸 2022 passed／2 warnings，總覆蓋率 83.65%、純分支 74.70%；本次同步未重跑驗收。
- 10/18 唯一 EXE 已獨立補驗完整／局部缺漏、排序、日期不同、正常導覽、3006→6669 研究切換及離線保留。先前 EXE 比較頁整體未驗證狀態由此限定補驗取代；**窄畫面、跨程序重啟、真實供應商與資料庫持久性仍未在本批新增驗證**。合成資料不代表真實績效。
- Black CLI、正式安裝既有限制，以及 Scenario Research 真實資料 incomplete／NO-GO 均保留；不代表已安裝版本更新。
- [同步來源與驗收帳本](accepted-watchlist-r3-sync-20261018.json)保存原始檔及獨立報告 SHA256。只同步七個已驗收程式／測試／合成 helper；排除候選 EXE、原始擷取、私人資料及其他本機未驗收變更。兩份舊測試保留驗收原始 bytes，因此包含換行差異；實質修改僅測試執行器與非 Temp 路徑。

## 突破形態觀察 v1（2026-10-19 同步）

- Research Overview 重用完成日線、SMA及既有 Rules 預設條件：前20日高點、嚴格大於前20日均量1.5倍、收盤高於SMA20且SMA20向上。顯示觀測日、參考價、距離、條件與最近三次歷史事件；不是策略成交、預測或績效。
- 入口：`src/stock_tool/application/breakout_observation.py::observe_breakout`、`dashboard/components/breakout_observation.py`；既有 `price_volume_observation.py` 接入。測試：`tests/test_breakout_observation.py`。
- Sol 限定範圍獨立驗收通過：34 targeted、2040 full passed／3 warnings；總覆蓋率83.6717%，純分支74.7361%。這是凍結本機候選的歷史驗收結果，不是本次同步重新執行的結果。
- 唯一EXE獨立操作涵蓋6933首頁搜尋、突破／量能不足、3006局部資料不足、6669換股未突破、期間與圖表頁籤。原6933互動缺口已補齊；資料不足仍保留其他公司資訊。
- 未完成日線、未知／重複日期、身分衝突、不合理OHLCV、可見公司行動及重大不連續保守拒絕。這些檢查不等於歷史公司行動／交易日coverage完整；正式Scenario Research仍incomplete／NO-GO，BacktestEngine、Replay與資格gate未改。
- mypy缺pandas-stubs仍未通過；本批Black API／Ruff／compile通過，不宣稱全專案Black CLI通過。專門窄畫面、公司行動疑慮EXE呈現、EXE跨程序重啟及舊研究庫未新增驗證；Session State/default警告與正式安裝限制保留。
- 公開行情只做三檔有限資料流程檢視，不是官方歷史完整性、公開行情UI或策略有效性驗收。原始CSV不在該凍結證據索引內，不隨Git同步。
- [本批來源帳本](accepted-breakout-observation-sync-20261019.json)保存四個已驗收檔案與獨立報告雜湊。候選、runtime、原始擷取、私人資料與其他未驗收修改均排除；沒有安裝、建置、發布或合併main。
## 真實行情端到端與來源隔離 P1 r2（2026-10-22 同步）

- Sol 已獨立核對原批公開原件、正常來源 UI、比較與研究跳轉，並於 10/21 補驗解除來源隔離 P1。本次只同步已驗收 bytes；未重新查 API、跑驗收或建置 EXE。
- 產品入口：`dashboard/app.py::_build_research_snapshot`、`dashboard/components/research_header.py`、`watchlist_comparison.py`。先按市場＋代號限定行情，再以列級取得時間執行完成日線判定；全域 session 的來源／時間／warnings 不能補資格。來源欄缺失保持未知；缺取得時間拒用價量衍生結果，但保留公司資料。舊 session-only 行情須重新載入，不靠同代號文字猜補。
- 測試入口：`tests/test_research_provenance_isolation.py`（35項新回歸）、`test_normal_research_availability.py`、`test_research_header_completeness.py`、`test_dashboard.py`。獨立相關測試 **175 passed**，另 **23個獨立探測通過**，不是198項pytest；2 warnings為既有壞日期fixture及reviewer預先匯入造成的anyio提示。四檔Ruff、Black單worker、compile通過；不解除全repo歷史限制。

初次取得約台北2026-10-20 00:42–00:46，三股均為 **TWSE／TWD、2026-10-16有效日線**。使用yfinance的Yahoo Close／OHLCV，非Adj Close。以下是當次凍結結果，不是現在報價：

|標的|收盤|5／20筆報酬|量／此前20筆均量|突破觀察|
|---|---:|---|---:|---|
|3006 晶豪科|244.50|-8.43%／-7.39%|0.89|未突破；前20日高296.50|
|6669 緯穎|1845.00|-17.63%／-20.30%|3.51|未突破；前20日高2345.00|
|6933 AMAX-KY（官方公司全名艾瑪斯科技控股股份有限公司）|451.50|+18.19%／+57.87%|0.85|價格突破432.00，確認條件未齊|

- 核對來源：Yahoo Finance chart公開回應（`query1.finance.yahoo.com/v8/finance/chart/{代號}.TW`，3mo／1d），以及TWSE [3006 STOCK_DAY](https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=20261001&stockNo=3006)、[6669](https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=20261001&stockNo=6669)、[6933](https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=20261001&stockNo=6933)。只作驗證，未新增產品provider；原始回應不隨Git上傳。
- 通過範圍：每股App與Yahoo有62筆有效重疊OHLCV一致；與TWSE十月共同11日的OHLC一致。5／20筆報酬、SMA20／60相對位置、排除當日的20筆均量及最新突破條件重算一致。較短Yahoo原件不能證明完整歷史事件清單或暖機等價。
- **成交量口徑尚未核明**：每股11日均與TWSE不同（共33筆），未猜原因、換算或混接。10/16 Yahoo／TWSE股數分別為3006：7,928,392／8,046,666；6669：12,287,772／13,858,059；6933：2,023,918／2,066,435。量比僅證明與Yahoo輸入一致，沒有交易所總成交量等價性結論。
- **行情延遲限制**：當次Yahoo 10/19 close為null，產品保留10/16有效日線；TWSE已有10/19收盤239／1885／406.5。不能宣稱產品取得交易所最新收盤。後續Sol正常UI取得10/20資料（3006：231.50、6669：1925.00、6933：396.00），驗過搜尋、比較、缺漏恢復及研究跳轉，但這批新價格未另核官方，不能併入10/16核對。
- 分割／公司行動：Yahoo歷史OHLC可能已經來源調整；6669的Yahoo split事件不等於官方完整coverage。同來源同日期不保證完整歷史價格基準。公司揭露缺口、HTTP406／逾時、舊搜尋草稿與SQLite載入層文字等已列限制保留。
- 本批是來源與有限流程驗收。沒有新的full pytest／coverage、新EXE／安裝生命週期驗收；正式安裝仍為v1.4.3分項狀態。**Scenario Research合成流程已驗收，真實資料資格仍incomplete／正式研究NO-GO**，沒有三股策略有效性結論。未驗正式資料前後逐檔零變更。

## 個股研究重點整合 v1（2026-10-22 同步）

- 已通過獨立限定驗收：既有Research Workspace首屏整理為「目前觀察／支持與反向證據／優先待查」。唯一產品變動是 `src/stock_tool/dashboard/components/research_header.py`；必要回歸為 `tests/test_research_focus.py`，不建立新研究系統、評分或AI推論。
- 目前觀察重用公司中文摘句及既有突破狀態、日期、前高、距離、量比；支持／反向欄只分類原突破條件，**不是完整公司投資論點或看多／看空評級**。缺漏顯示不可判讀，不當作反向證據；可用價量及公司資訊保留。
- 沿用既有評分提醒與待查問題；公司風險只呈現同市場＋代號的原文與來源。行情觀測／取得、公司發布／取得日期分列，未知不補造；首屏保留重要缺口，展開能核對完整時間和原文。已知Synthetic/sample/中文模擬標記及SYNTH_代號顯示警告與模擬價格標題，不能保證識破偽造來源標籤。
- 獨立測試 **136 passed、1個既有pandas warning**，含17項新回歸；另13個元件探測通過，不算額外pytest。兩檔Ruff、Black CLI單worker、compile獨立通過。這些是既有驗收紀錄，本次同步未重跑。
- 獨立正常UI僅涵蓋凍結來源、全新無secrets隔離runtime的3006／TWSE：搜尋→研究，實際顯示晶豪科、TWD231.50、2026-10-20、yfinance；前20日高296.50、距離-21.92%、量比0.69、三項未達條件與既有結果一致。42.7分／70%覆蓋未當完整研究；公司風險原文不足、財報及未知發布日缺口仍可見。
- 實際操作圖表1Y→6M再回總覽，header逐字不變；展開確認ESMT官方連結及完整原文取得時間。1280×720可讀且主內容無橫向溢位，完整首屏區域仍需垂直捲動；沒有宣稱所有內容單一viewport看完。
- **尚未新增正常瀏覽器驗證**：6669／6933、Synthetic、缺漏／錯公司僅有元件與回歸證據；窄畫面、原生縮放、完整鍵盤旅程未重驗。沒有本批full pytest／coverage、新EXE或安裝／發布驗收。
- **兩項非阻擋P2保留**：業務首句仍偏DDR4／DRAM／Flash名詞，完整白話解釋在下方；來源／缺漏caption對比偏低、header仍偏長。驗收未要求本批繼續修改。
- Yahoo延遲、分割／成交量口徑未核明及公司揭露／歷史涵蓋限制沿用；本次UI沒有重作交易所價格／量能核對，10/20不代表交易所最新行情。真實Scenario Research仍incomplete／NO-GO，正式安裝仍v1.4.3分項狀態，既有品質及交付限制不升格。
- [同步帳本](accepted-research-focus-sync-20261022.json)保留來源／證據索引及獨立報告SHA256；私人報告、截圖、原始擷取、runtime、憑證與EXE未上傳。本次只同步已驗收原始碼、必要測試和文件，不重建、安裝、發布或合併main。
