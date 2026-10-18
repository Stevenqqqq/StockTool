# StockTool 目前狀態

更新日期：2026-10-18。供第三方顧問閱讀已獨立驗收的原始碼；產品決定與發布核准仍由 Product Owner 負責。

## 版本與閱讀基準

- GitHub：PR [#1](https://github.com/Stevenqqqq/StockTool/pull/1)，分支 `codex/sync-accepted-research-20261011`，尚未合併 main。
- 本頁對應的最新程式提交：`abe51c7c8d28718422071c819fc8156646031709`；文件在後續獨立提交保存。分支最新 HEAD 請以 GitHub 或 `git rev-parse HEAD` 為準。
- 總覽與情境日期呈現提交：`8e3825be015e5ae063e45a449a30a15242a7c5b5`。前次同步基準：`55fb4417453a539c00c8f1db5390e6d7d6b999dd`；本次核對 main：`11ee8d7438e9a06115d3ab75a99d088d4ef55d13`。
- 正式本機安裝參考仍為 **v1.4.3 的分項驗收狀態**。本分支的新原始碼、候選內部版本字串及候選驗收，均不代表正式安裝已更新。
- 最新基本面／持股來源追溯：[r2 同步帳本](accepted-fundamental-holding-sync-20261015.json)。
- 先前來源與驗收追溯：[本次來源帳本](accepted-source-sync-20261015.json)、[前次同步說明](accepted-source-sync-20261011.md)。歷史文件描述的是各自凍結當時的狀態。

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

- 最新基本面／持股 r2 已通過 Sol 限定範圍獨立驗收：**85 targeted passed、2000 full passed、2 warnings**；獨立總覆蓋率 **83.57073121886499%**，純分支 **74.5569875151027%**。獨立驗證 CSV 雙程序身分隔離、合成週末／離線／FX 過期／缺價／衝突，以及凍結 EXE 關閉重啟。來源與候選保持凍結；不是正式安裝或真實供應商復原驗收。
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
