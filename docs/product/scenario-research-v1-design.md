# Scenario Research v1 — Breakout Confirmation 修訂設計

日期：2026-10-07。狀態：設計提案，待 Product Owner 核准及 Sol 獨立審查。此文件不是實作授權、驗收或正式 baseline 更新。

## 1. 本批決策與邊界

只完成 Breakout Confirmation 的「資料檢查 → 條件證據 → 回測 → OOS → 案例檢視 → 保存 → 離線重放」流程。

重用 StrategyBase、StrategyRegistry、BacktestEngine、Backtest Evidence metrics 及現有驗證服務，不修改 BacktestEngine、撮合、成本或既有策略 signal 公式。Bottom Reversal、Momentum Pullback、左側／確認／突破三時點比較延後。6669、6933、3006 是案例索引，不是有效性證明，不依其績效選參數。

第一版純 OHLCV、單一市場＋代號、long-only、一次進出、不加碼、不部分平倉。不使用法人、融資融券、盤中大單、AI 或基本面條件；不修改 Entry Reference、舊研究庫及正式資料。

以下是一套唯一算法。所有比較與重放使用同一算法版本；參數表是預先登錄的起始假設，不代表最佳值。

## 2. 時間、指標與參數

索引 t 是已通過資料檢查的一根完整日線；所有條件在 t 收盤後可知。前 N 根指 t-N 至 t-1；不以曆日補值。日線日期採交易所本地交易日。

| 參數 | 起始值 | 定義 |
|---|---:|---|
| N | 20 | 突破前期 high 回看根數 |
| A | 14 | ATR 算術平均根數，不使用 Wilder/EMA |
| V | 20 | 成交量基準回看根數 |
| F | 20 | 趨勢 SMA 根數 |
| S | 5 | SMA 斜率比較間隔 |
| B | 0 | 突破緩衝 ATR 倍數 |
| M | 1.5 | 量能確認倍數 |
| K | 1 | 突破失效緩衝 ATR 倍數 |
| E | 10 | 移動出場前期 low 回看根數 |
| H | 40 | 情境最多存續根數，含觸發日 |
| R | 2 | 終止後連續重置根數 |

所有期間參數為正整數，H >= 2、M > 0、B >= 0、K > 0；不接受 NaN、inf、字串默轉或錯誤四捨五入。實際允許範圍由 schema 固定。研究主結果固定以上版本；敏感度另存，不覆寫主結果。

定義：

- TR_i = max(high_i-low_i, abs(high_i-close_(i-1)), abs(low_i-close_(i-1)))。
- ATR_t^- = mean(TR_(t-A), ..., TR_(t-1))，不含當日；若 <= 0 或缺資料，不能判斷突破，不以 0 替代。
- P_t = max(high_(t-N), ..., high_(t-1))。
- Q_t = P_t + B × ATR_t^-。
- U_t = mean(volume_(t-V), ..., volume_(t-1))，必須 > 0。
- SMA_F(t) = mean(close_(t-F+1), ..., close_t)。趨勢可以使用當日已完成收盤，但不能使用 t+1。
- D_t = min(low_(t-E), ..., low_(t-1))，不含當日。

至少須有 W = max(N, A+1, V, F+S-1, E) 根完整前置資料，才能評估第一根測試日。ATR 需前收盤，所以 A+1 不可省略。日期、價格與量只在顯示時格式化；計算與比較不先四捨五入。

## 3. 唯一情境生命週期

狀態為 READY → ACTIVE → RESET_WAIT → READY；另有評估期結束的 RIGHT_CENSORED。此狀態表示研究情境，不表示帳戶持倉。

### 3.1 READY：共同案例起點

當且僅當 close_(t-1) <= Q_t 且 close_t > Q_t，建立一個價格突破案例。

注意兩個比較都使用同一個 Q_t，而非昨天的 Q_(t-1)；這是「穿越當日可知的前期區間」定義。等於門檻不算突破。

在 t0 觸發時凍結：P0=P_t0、ATR0=ATR_t0^-、Q0=Q_t0、U0=U_t0、L0=P0-K×ATR0；並保存趨勢數值、日期、因果輸入指紋。

L0 <= 0 的價格突破仍建立共同 case_id，情境在 t0 立即以 INVALID_SCALE 終止；兩變體條件狀態均為 INVALID（先於量能/趨勢判斷），不發 buy 或 sell，部位為無部位。不稱 FILTERED_OUT、BREAKOUT_FAILED 或零損益交易，也不進入 ACTIVE/H 倒數。t0 終止後進 RESET_WAIT：自 t0+1 開始，照相同凍結 Q0、連續 R 根 close <= Q0 的規則重置，達標後下一根才 READY。不能下一日直接反覆新增無效尺度案例。案例漏斗另列 INVALID_SCALE 數並保存價格觸發證據。

### 3.2 兩個比較變體

- Price-only control：共同價格案例成立即產生一次 buy 研究訊號。
- Breakout Confirmation：只在同一 t0，同時滿足 volume_t0 > M×U0、close_t0 > SMA_F(t0)、SMA_F(t0) > SMA_F(t0-S)，才產生一次 buy 訊號。

量能或趨勢不滿足，就記為 FILTERED_OUT，列出每項實際值與差距。不能在後續某日條件變好時補發本案例進場，不能把未確認案例刪掉。第一版「確認」是突破當日的量能與趨勢確認，不是隔幾天追認。

Price-only control 是新情境算法的一個控制變體，使用同一案例母體與出場規則。既有 VolumePriceBreakoutStrategy 原封不動；若另列其績效，只能標為不同策略參考，不能混作配對比較。

### 3.3 ACTIVE：每日終止判定及優先序

從 t0+1 開始，每日收盤依序檢查；第一個符合即終止情境：

1. close_t < L0：BREAKOUT_FAILED。
2. close_t < D_t：TRAILING_RANGE_EXIT。
3. t-t0+1 >= H：EXPIRED。

L0、P0、Q0、ATR0 全程不變；只有明確命名的 D_t 隨過去 E 根更新，不能把 D_t 描述為原始凍結支撐。等於 L0/D_t 不觸發退出。價格與逾期同日成立時保留價格原因為主要原因，證據可列全部命中條件。

對曾產生 buy 訊號的變體，在終止日產生一次 sell 訊號。對 FILTERED_OUT 變體只記情境終止，不產生 sell。情境終止不等於已平倉；執行仍由引擎決定。H 是從共同觸發日計算的情境壽命，不是從實際 entry execution 計算的持有天數。

評估期先結束時，記 RIGHT_CENSORED，不補造退出或延用窗外價格。未觸發終止的已成交部位保持 open，不計入 closed round trips。最後一日已發出的訊號可能仍為待成交。

### 3.4 RESET_WAIT：重新啟動

ACTIVE 期間不得建立另一個案例。終止日不能同日重新啟動。

從終止後第一根開始，累計連續 close_t <= Q0 的根數；大於 Q0 時計數歸零。達 R 根後，在下一根才回 READY，重新依當日 P_t、ATR_t^-、Q_t 判斷新的穿越。此前即使刷新高也不算新案例。FILTERED_OUT、失敗與逾期案例完全使用相同重置規則。

此規則有意放棄部分連續突破；它避免重複計數及為某個變體單獨尋找有利再進場。敏感度第一版不掃 R/H/B/K，避免比較母體到處改變。

## 4. 研究情境、訊號、訂單與成交分開保存

### 4.1 因果 case_id 與完整研究指紋分離

`case_id = SHA256(canonical({identity, evaluation_start, warmup_start, t0, common_rule_version, common_parameters, causal_prefix_digest}))`。

- identity 是市場＋代號＋標的類型；共同參數為 N/A/V/F/S/B/K/E/H/R，不含量能變體 M、資金、成本或執行結果。
- causal_prefix_digest 只雜湊此窗固定 warmup_start 至 t0 的正規化 OHLCV，包含暖機與情境重置所需歷史，不能漏掉較早的狀態影響。
- 不含 evaluation_end、完整資料檔 hash、run/package ID、抓取時間、後來補齊的 coverage 文件、變體結果、未來退出或績效。來源及 coverage 證據仍由完整 package 綁定。
- 同一評估/暖機起點、規則及資料前綴下，追加/修改 t0 之後行情或延長評估期，既有案例 ID 與當時條件必須不變。修改 t0 以前行情、評估起點或重置語境則可改 ID，必須列為不同研究。
- 兩變體與 M 敏感度使用同一母體建立器，不各自建立案例。

另設 run_input_digest 綁定完整暖機/評估資料、結束日、所有變體/參數、成本、coverage/交易日證據及相容版本；run_id 是保存實例識別。package_digest 綁定完整檔案 manifest（輸入、結果及 metadata；digest 自身不參與自身雜湊）。追加未來行情時 run/package 指紋必須改變，相同前綴案例仍保有原 case_id。相同 case_id 不代表整次績效相同，配對仍須核對評估範圍與設定。

保存四條獨立軸線，不能用單一「成功/失敗」覆蓋：

1. 情境：ACTIVE / INVALID_SCALE / BREAKOUT_FAILED / TRAILING_RANGE_EXIT / EXPIRED / RIGHT_CENSORED。
2. 條件：PASS / FILTERED_OUT / INVALID，附各條件當時數值。
3. 執行：無訊號 / 已發訊號 / 待成交 / 拒單 / 已成交，buy/sell 分別記錄。
4. 部位：無部位 / 未平倉 / 已平倉，以實際 fills 與既有 Portfolio/Backtest Evidence 為準。

buy 被拒絕時，預先形成的情境 exit 訊號不代表曾持倉；引擎若拒絕無持倉 sell，也照實保存，不捏造交易。不得把 signal_count 當成交次數；需分開計算 nonzero buy/sell 訊號、fills、closed round trips。

每變體沿用同一初始資金、allocation、風控、費稅滑價與可用日期，分開跑現有引擎。不同績效導致資金/股數/拒單不同是實際結果，不能強迫兩者成交相同股數。比較時同時列金額與每筆淨報酬，不只比較金額期望值。

### 4.2 Adapter sizing 契約

buy 列固定 target_percent=本次 allocation、quantity=None、cash_amount=None；allocation 與 Workspace 已驗證設定一致。

sell 列清除全部 sizing：target_percent=None、quantity=None、cash_amount=None，沿用引擎/Broker 對無 sizing sell 的「退出當下全部持股」。不得把 buy 的 allocation 經 `_attach_sizing` 帶到 sell，也不以 target_percent=0 或固定進場股數替代此契約。只在新情境 adapter 處理，不修改 StrategyBase、舊策略或引擎。

已唯讀核對 `backtest/engine.py::_risk_order_quantity` 及 `backtest/broker.py::_resolve_quantity`：sell 帶 target_percent 代表目標剩餘持倉；無 target_percent/quantity 才取目前 position.quantity。回歸須經 normalize、風控及實際撮合，不能只比 adapter DataFrame。

第一版不打開額外 stop_loss/take_profit/trailing_stop 疊加條件，避免與共同出場原因混淆；既有風控拒單仍保留。若曾發生意外延遲成交，造成下一案例進場前仍有前案持倉或 pending 訂單，應以執行稽核標為比較不可用，隱藏其有效性結論，不默默加碼、取消訂單或假裝清倉。若要自動處理這些狀態需改核心 contract，停止並另提核准。

## 5. 共同母體與比較分母

所有符合共同價格起點的案例都保留：確認失敗、形態失敗、零成交、拒單、待成交、未平倉及已完成。不能先篩「後來突破成功」再比較。

比較表必須有：母體案例數、通過確認數、buy 訊號數、成交數、拒單數、待成交數、完整交易數、open 數、各情境終止原因。共同資料與共同參數相同時兩變體 case_id 集合必須完全一致。

交易 metrics 僅以各變體真實 closed round trips 計算；FILTERED_OUT 不當成零損益交易，未平倉也不進勝率分母。配對結果另標「雙方均已平倉子集」，不得用它替代全案例主結果。

敏感度第一批只允許 M 的預先登錄鄰近值 {1.2, 1.5, 1.8}，共享同一價格案例母體，不排名選最佳。不做三時點進場比較或自動參數最佳化。

## 6. OOS 與 Walk-forward 的唯一邊界

- 參數、切分日期、成本及變體在查看評估結果前凍結。已用來調規則的區間不得再稱未看過樣本外。
- 每窗取精確 W 根窗前完整日線暖機；只計算 rolling 指標，不建立 case，不產生訊號，不延續 READY/ACTIVE/RESET 記憶。
- 第一個評估日以 READY、零情境、初始現金、空倉、空 pending/rejected 訂單、全新 engine/strategy instance 開始。前一根 close 可用於首次穿越比較，但不帶入窗前情境。
- 只送評估區間價格與評估期訊號給引擎，不允許用窗外行情成交；末日 pending/open 保留，下一窗不接續。
- 測試窗以閉區間定義，必須 previous.end < next.start；拒絕重疊，不能事後去重。按 bars 建窗時要求 step_bars >= test_bars，並檢查實際日期。訓練/暖機區間可重疊。
- 逐窗報告初始資金、日期、暖機、案例、closed/open/pending 與 metrics。不得相加/平均各窗總報酬冒稱連續資產曲線，不跨窗拼接未平倉交易。
- 固定參數 Walk-forward 是跨期穩定性研究，不自動重新訓練；以後若調參，須把選擇限定在當窗訓練期並另行設計。

現有 validation._run_period 先在整段歷史產生訊號再裁切，不能直接用於此有狀態情境。以情境專用的有限評估入口提供 evaluation_start/end：先暖機指標、再初始化情境，保留舊策略原路徑。不得在 UI 用截掉訊號的方式冒充重置。

## 7. 所有入口共用資料資格檢查

Research Workspace、Strategy Workspace 接力、標準執行、OOS、每個 Walk-forward fold、每個敏感度執行、離線重新計算，必須調用同一 ScenarioResearch service 與同一 validation 結果。不能依「UI 已檢查過」略過程式入口；仍保留執行前複核。

檢查範圍是實際使用的完整 W 暖機＋評估區間，不是只查可見圖表或評估期。至少檢查：

- 市場＋代號＋標的類型一致；第一版只限普通股，不能讓 ETF 使用公司股票情境。
- 唯一且正確的交易日期、穩定排序、有限正 OHLC、high >= max(open,close,low)、low <= min(open,close,high)。
- volume 有明確單位、有限且 > 0。第一版零量/停牌、無法區分休市與缺棒的日期缺口不自行略過；無法驗證時阻擋完整流程並說明缺口。
- 歷史覆蓋與交易日來源可核對；沒有交易日/停牌依據，就不能因為「有 100 列」宣稱連續完整。這可能是資料資格 blocker，不以新 provider 或插值偷偷補足。
- 完整 W、ATR/均量分母、指標欄位均有效；整段必需資料失效時阻擋，不只跳過有問題的案例留下漂亮績效。
- 重用 raw_research_safety_errors、CorporateAction、PricePolicy；暖機內的已知事件也不能漏掉。不降低 25% 篩檢門檻、不推估比例、不混用 adjusted close 與 raw OHLC/volume。

### 公司行動覆蓋未知

「事件列表為空」不等於「完整查證沒有事件」。保存事件來源、涵蓋期間、查詢/匯入時間及 coverage_status（verified / unknown / incomplete）。查詢成功本身也不自動等於 verified。

- 已知跨事件、異常跳變或事件資料矛盾：沿用既有門檻阻擋。
- coverage unknown/incomplete，即使沒有大跳變：允許查看條件與探索性案例，但顯著標「公司行動覆蓋未確認」，不得產出正式 OOS 比較或有效性結論；正式比較入口阻擋。
- verified 且期間無事件，其他檢查通過：才可進入正式比較。verified 的證據來源/期間必須可核對，不能人工點選「信任」取代證據。

這是完整流程的交付前置條件，不承諾現有供應資料已具備。若查不到可靠 coverage 證據，交付必須列為未完成/阻擋，不能靠三支股票合成 fixture 宣稱真實案例可用。

三套第一版無基本面依賴，不放寬 strict PIT。若未來加基本面條件，需以 available_date 與歷史修訂版本獨立驗證；不能把報告期間當可得日。

### 7.1 現有來源盤點（2026-10-07，僅讀 repo，未下載或驗證線上可用性）

| 現有來源/契約 | 已確認可重用 | 未確認或不能推論的範圍 |
|---|---|---|
| `data/corporate_actions.py`：CorporateAction、load_corporate_actions_csv | 已有市場、代號、事件類型、生效日、來源、可得性/完整性契約及 CSV 匯入驗證。 | 單筆事件 complete 不能證明整段事件目錄完整；沒有因此取得全期間「無事件」證明。未確認現有本機真實事件檔內容，本輪不讀正式資料。 |
| `application/strategy_workspace.py::integrity_errors` | 已有 corporate_actions_path 注入與 raw 安全檢查。 | path 不存在時採空事件集合；這不是 coverage verified。新情境入口須另外驗證 coverage 證據，不能沿用空集合當完整。 |
| `data/auto_fetch.py` 現有 yfinance 日線路徑 | 使用 auto_adjust=False 的行情取得路徑。 | 現行呼叫 actions=False，OHLCV 不自帶完整事件歷史證明；不可宣稱已接上 Yahoo 公司行動。此輪不呼叫 API、不改取得方式。 |
| `data/providers.py` 及既有行情 CSV/Excel 匯入 | 可重用行情/來源契約與本機資料輸入。 | 行情檔、來源名稱或最近抓取成功均不證明公司行動、交易日或個股上市/停牌覆蓋完整。 |
| `application/official_trading_calendars.json`＋`prediction_lab.py::MarketTradingCalendar.default_for` | repo 內 TWSE、TPEX 各有 2025/2026 年資料（每年各 244 日），US 有 2026 年資料（251 日）；含官方 endpoint、抓取時間、raw/normalized hash 及 normalization version，既有載入器有 provenance/schema 檢查。 | 本輪只核對檔案內容與程式；未重新下載原文，不能確認抓取後臨時休市修訂、個股停牌、上市前/下市後區間。其他年度缺覆蓋，不外推週一至週五。 |

交易日檔記錄的抓取日為 2026-08-27；TWSE endpoint 是 holidaySchedule，TPEX 是 bulletin/tradingDate，US 是 NYSE Trading_Days.pdf。這些是既有檔案記錄，不是本次線上核驗結果；raw hash 也不代表原始檔目前仍可取得。正式 package 必須保存所用年度的既有來源/正規化證據並經載入器驗證，不能只複製 dates 陣列。

目前尚未確認有可直接支援任意個股/區間的公司行動 coverage certificate，或全歷史個股停牌/上市狀態資料。現有 deterministic 公司行動 fixture 只供回歸，不是 coverage 來源。本批禁止新增 provider、下載或以人工勾選替代來源完整性；不足時維持 unknown/incomplete 及原阻擋，不承諾三支真實案例可正式比較。

## 8. 獨立版本化保存與離線重放

新增獨立 Scenario Research package v1／專屬目錄，不更新、遷移或重新序列化既有 Research Library v1/v2 或研究工作階段。可保存其不可變 ID 作參考，但情境 package 的重放不能依賴舊庫當前內容。

每個不可變 package 保存：

- schema_version、scenario_algorithm_version、run_id、父研究參考 ID、程式來源版本/指紋。
- adapter/sizing、engine execution/accounting、risk、metrics/round-trip、資料正規化版本及其來源指紋；含 Python/必要數值套件版本與重放相容 profile。application_version（例如 1.4.3）不能單獨代表這些契約完全相同。
- 身分、完整參數、共同案例規則、變體、成本/風控/資金、精確暖機與評估窗。
- 正規化 OHLCV、公司行動資料與覆蓋證據、交易日依據，及各自內容 hash。
- 各來源日期、行情期間、抓取時間、研究產生時間分開；不合併成單一「資料截至日」。
- 條件逐步證據、共同 cases、signals、orders/rejections/pending、fills、open positions、round trips、metrics 與缺口。
- manifest 的 canonical serialization 規則及逐檔 SHA-256。明確區分完整性檢查與來源真實性：hash 不能證明供應資料正確。

保存採新 run ID、原子寫入；失敗不覆蓋舊 package。不同結果另建版本，不原地改歷史。

離線提供兩種明確模式：

1. 查看保存結果：驗證 manifest/資料檔後讀取當時結果，不發網路請求、不取得憑證。
2. 重新計算：只用 package 內固定輸入及已核准相容 profile 的本機程式重跑；完整核對第 8.1 節紀錄，不能只比總報酬。不得重算失敗後退回舊結果冒稱一致。

未知 schema、未知算法版本、缺檔、hash 不符或路徑穿越拒絕重算；已保存結果能否只讀顯示要明標，不能執行 package 內任意程式碼。合法但本機不支援的算法保留原檔，不自動升級。

備份/還原採獨立情境 package 匯出匯入，驗證後落在新目錄、同 ID 不覆蓋；既有研究庫備份功能不偷偷擴大宣稱已含新資料。

### 8.1 完整執行紀錄重放核對

依固定次序與關聯鍵核對每筆，不只比較數量或末值：

- 情境轉移、凍結值、條件證據、case_id 與訊號；包含未觸發/INVALID 案例。
- 全部 orders：order_id、標的、side、signal_date、各 sizing、reason、status、rejection_reason；pending/rejected 狀態與相應訂單關聯必須一致。
- 全部 fills：order 關聯、signal/execution 日期、價格、股數、gross、commission、tax、slippage、net_cash_flow、realized PnL、holding days 及 reason。
- 每日 equity_curve、positions_history、daily_reconciliation、corporate_action_audit，以及期末 Portfolio 現金、完整 positions（股數、成本、entry date、last price）、全部 warnings。
- 完整 round trips、MFE/MAE 與 unavailable 原因、所有 metrics 及樣本數；每個變體/fold 均逐項核對。

既有 BacktestResult 已公開 orders、trades、rejected_orders、equity_curve、positions_history、portfolio、daily_reconciliation、corporate_action_audit；adapter 以唯讀序列化保存，不新增撮合狀態。pending 由既有 orders 的實際 status 擷取，不從「沒有 fill」猜測；若無法忠實取得所需紀錄，重放能力標為未完成並提出 blocker，不虛構中途狀態。

身分、關聯、順序、枚舉、日期、整數、空值與 unavailable 原因需完全一致；有限浮點使用固定 abs_tol=1e-9、rel_tol=1e-9。None 不等於 0；inf 須同號且只允許既有 metrics 合法欄位；NaN 不可當作匹配成功。資料檔 hash 仍須 byte-exact，容差只適用重新計算出的數值。執行/保存當下 wall-clock metadata 不要求重新生成相同，保留原值與另立 replay attempt 紀錄，不能忽略交易日期差異。

任何差異回報首個位置、欄位及兩值，整次結果標 REPLAY_MISMATCH，不給「已重現」標章；原 package 不修改。若 signals/fills 相同而 metrics 改變，仍是失敗，不能自動用新版統計替換舊結果。

### 8.2 引擎與 metrics 版本相容

首次 profile 綁定已驗證的 engine/accounting、Broker、risk、scenario adapter、metrics/round-trip 實作指紋與 schema；不修改這些模組以補版本欄位，由獨立 package manifest 記錄。

本機必須有精確匹配的 profile，或經獨立 golden replay 驗證、明確登錄的相容映射，才可重算。scenario 版本相同但 engine 或 metrics 不相容時拒絕重算；不能僅看應用程式版本、套件能 import 或測試可啟動就判定相容。純格式來源差異也不可自行忽略，需明確映射證據。

已知且安全可讀的 schema 仍可只讀顯示歷史結果，顯著標「保存結果／未以目前環境重算」；未知 schema 或內容損毀則拒絕解析。不得從 package 載入/執行歷史 Python 程式。日後若要用新 engine/metrics 研究相同輸入，建立新 run/package 並列版本差異，不宣稱原版精確重放。

## 9. 最小畫面與模組

在 Research Workspace 既有「風險與情境」加入情境研究區：先顯示可用性與阻擋原因，再顯示規則版本/期間/成本及一個「執行歷史研究」入口。完整設定與計算仍由應用服務持有，不在兩個 Workspace 寫兩份。

結果分為共同案例漏斗、兩變體交易品質、OOS 各窗、歷史案例。沿用 Backtest Evidence 的三區與資料不足呈現，不計算另一套勝率。MFE/MAE coverage 直接可見。

案例預設只顯示截至 t0 的圖與當時條件；「查看後續」才展開實際成交、拒單、終止和績效。用後來跌破判定的 BREAKOUT_FAILED 只能放在後續結果，不能顯示為當時已知。

最小新增責任：版本化情境 evaluator/證據型別、BreakoutConfirmation StrategyBase adapter/registry 項、ScenarioResearch service、獨立 package store/replay、研究頁元件。validation 只加情境評估邊界入口；不重寫 BacktestEngine，不順手改其他策略。

## 10. 驗收條件（全部以 deterministic fixture 加實際隔離 UI 驗證）

| 編號 | 必須證明 |
|---|---|
| A1 | ATR 採前 A 根 TR 算術平均，含所需前收盤；當日 high/low/volume 不污染凍結基準。 |
| A2 | close_(t-1) <= Q_t < close_t 唯一觸發；相等、不足暖機、ATR=0 均不誤觸發。 |
| A3 | P0/Q0/ATR0/L0 不隨未來更新；失效/移動退出/逾期同日的優先序固定。 |
| A4 | ACTIVE 不重複觸發；RESET 連續 R 根、歸零與下一根才 READY 的邊界正確。 |
| A5 | 追加、刪除或改寫 t 後行情，t 以前訊號與當時證據完全不變。 |
| A6 | 兩變體共享相同 case_id 集合；FILTERED_OUT 不能消失或以零損益混入 closed metrics。 |
| A7 | buy 拒單、sell 拒單、末日 pending、open、已平倉全損的 0% 勝率皆如實顯示，情境終止不冒充成交。 |
| A8 | 費稅滑價、完整交易、MAE/MFE 延用既有 contract；無重複扣除、無 exit 後污染。 |
| A9 | 每個 OOS/fold 新實例、空倉、空訂單、情境重置；窗前已 ACTIVE 不延續，暖機資料仍可算指標。 |
| A10 | 重疊測試窗直接拒絕；末日訂單不能用下一窗首日成交；跨窗 open 不拼成完整交易。 |
| A11 | 所有入口對暖機內/評估內缺棒、無效 OHLCV、錯身分、公司行動及 unknown coverage 給相同判定。 |
| A12 | 範圍相同但行情數值改變時 hash/run identity 改變；舊結果不得宣稱仍對應新輸入。 |
| A13 | 保存、關閉重啟、離線查看/重算、備份/還原結果一致；斷網測試證明不偷偷抓最新資料。 |
| A14 | 損毀/缺檔/未知版本/路徑穿越拒絕；失敗保存與還原不覆蓋任何既有研究。 |
| A15 | UI 可看全部案例及當時條件、未觸發原因、實際進出與缺口；切換公司不殘留其他公司結果。 |
| A16 | 既有 Research Library v1/v2 檔案及開啟行為不變；只用合成/隔離資料核對。 |
| A17 | 固定起點/規則/前綴，追加未來行情或延長結束日：舊 case_id 不變、run_input/package 指紋改變；修改前綴或起點時 ID 改變，M 變體不改母體 ID。 |
| A18 | allocation=0.25 與 0.60 分別經實際引擎測試：buy 帶 allocation，sell 三個 sizing 均 None；退出股數等於退出前全部持股、期末空倉、2 fills/1 closed round trip，含費稅與價格變動；防止誤變成僅減至目標部位。 |
| A19 | L0=0 與 L0<0 都立即 INVALID_SCALE、兩變體無訂單；不跑 H 倒數；依凍結 Q0 重置 R 根且下一根才可重啟，無效案例保留於母體但不進交易分母。 |
| A20 | 固定原始輸入、參數與相容版本，在不改總報酬的前提下，分別篡改保存結果中的訂單/拒因/pending、fill 成本、每日現金/持倉、對帳、round trip 或 unavailable 原因，再重新產生格式合法且內容一致的 manifest、逐檔雜湊及 package_digest。確認檔案完整性檢查通過後，必須以固定輸入完整重算、逐欄檢出篡改差異，回報位置與欄位並標為 REPLAY_MISMATCH；不能只測 hash mismatch，也不能以保存結果作為重算輸入或可信基準。未篡改對照組須重放一致。另驗證引擎或 metrics 版本不相容時拒絕重算，所有檢查均不修改受檢 package。 |
| A21 | 日曆超出既有年度、缺 provenance、個股交易狀態未知及空公司行動集合皆不可冒稱 coverage verified；fixture 不可充當真實完整性證據。 |

工程交付另需 targeted、backtest baseline regression、full pytest、既有 coverage gate、quality checks、候選 EXE smoke、privacy scan、來源/候選 hash。獨立 EXE 畫面驗收由 Sol 執行；任何不可用項目分開列示，不以 fixture/health check 替代 API 或畫面實測。

## 11. 審查決策與交接

建議只核准上述固定規則與完整流程。實作前先確認公司行動 coverage/交易日依據能否取得；若不行，先回報資料資格 blocker，不能一邊做出績效一邊聲稱安全。不得自行改成 adjusted-price 路線或擴大 provider 範圍。

給 Sol（建議沿用高推理）：請集中核對固定門檻/重啟是否唯一、OOS 暖機與狀態是否隔離、共用母體與不同成交分母是否誠實、全入口檢查/unknown coverage 是否 fail closed、獨立保存能否不動舊庫而離線重放。指出阻擋與最小修訂，不改程式、不開始 Sprint。Product Owner 核准且審查結束後才進實作。

本次修訂交接：重點審查第 4.1 因果 ID、第 4.2 buy/sell sizing、第 3.1 INVALID_SCALE、第 7.1 現有來源及缺口、第 8.1–8.2 完整重放與版本相容，以及 A17–A21。只有此設計文件修改；不下載資料、不新增 provider、不修改引擎/舊策略/舊研究庫、不建立 commit，等待審查與核准。
