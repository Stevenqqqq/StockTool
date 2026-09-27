# 持股與公司研究接續：實作進度

## 最新狀態：2026-09-21（覆蓋下方歷史狀態）

**開發端交付單一未發布候選，待 Sol 獨立驗收；真實持股未變更。** 交接及實測限制見 `research-workflow-handoff.md`。

### 9/21 接續

- 最後補驗：使用者手動上傳後，EXE 研究庫已出現還原版本 `5240d8ed`；主代理重複還原確認仍僅三筆，三份檔案雜湊與版本 ID 完全一致。停止、重啟 EXE 後還原版本的 JPM 身分、問題、中文草稿及四個來源可讀。證據 `20260921-exe-restored-dom.txt`、`20260921-exe-restored-restart-dom.txt`、`20260921-exe-restored.png`。備份下載事件已觸發，但未核對下載檔；損毀備份只有程式測試，未冒稱瀏覽器手動實測。這些限制已交 Sol 核對。候選測試程序已停止。
- 隔離候選已建置：2,845 檔，EXE SHA256 `40DF0F731202C7A16192DE8E2AE88844A400F958E25F914EE6A3731025414216`，版本 1.4.2。公開資產驗證、禁止路徑檢查、全部來源指紋比對及 Ruff 通過。精確清單見 `20260921-candidate.json`、`20260921-candidate-files.json`、`20260921-candidate-source.json`。這是待驗證建置，不是已凍結交付。
- EXE 在 `D:/Temp/stocktool-workflow-candidate-smoke-20260921` 空白 runtime 啟動於 loopback 8501；金鑰及 LOCALAPPDATA 隔離，未使用真實持股。後續將既有公開 JPM／合成持股工作階段作為測試 fixture 保存至此 runtime，不算瀏覽器上傳還原。
- 上次 final2-rerun 剩兩項：Excel 5.108 秒超過 5 秒；privacy 掃到執行者放在 docs 的 pytest fixture。已將本輪自行產生的 `final2/pytest-temp` 內容移至 `D:/Temp/stocktool-final2-artifacts-archive-20260921` 及 `D:/Temp/stocktool-final2-artifacts-remainder-20260921`，保留原 log/json，沒有改掃描規則。兩項帶 coverage 定向重測 `2 passed in 8.86s`，見 `20260921-two-failures-targeted.log`。
- 最終完整回歸 exit 0：**1767 passed、2 skipped、2 warnings，219.23 秒**，含 CDP，沒有排除失敗測試；coverage **83.143683191427286%**，通過既定 82.71 門檻。見 `20260921-final-regression.log`、`20260921-final-coverage.json`。全部 basetemp 與二進位 coverage 留在系統 TEMP。CDP 畫面／鍵盤／console 證據另存 `20260921-final-cdp`；console error/warning 皆零。
- 使用者重新連接後，Chrome 畫面操作恢復。已在候選 EXE 研究庫讀取 JPM 中文草稿、未知文件日期、分開的請求／完成／模型建立時間及四個引用；見 `20260921-exe-saved-ai-dom.txt`。另存問題 `EXE_0921`，停止並重啟同一 EXE 後，新版本 `28f157fe` 的問題、身分與 AI 引用均一致，原版本 `01edbfd4` 仍在；見 `20260921-exe-restart-dom.txt`。
- 檔案上傳 `fileChooser.setFiles` 仍回覆 `Not allowed`，因此正常／損毀備份的實際瀏覽器上傳還原尚未完成。未繞過 Chrome 權限，已保留同一候選研究庫頁供使用者手動選取 `D:/Temp/stocktool-workflow-groq-ct_pyzxr/browser-restore.json`（只有合成持股與公開公司證據）。

### 9/20 限制中斷後接續

- 晚間接續：維持 Chrome sandbox 的 elevated CDP 定向 `2 passed`，證據在 `20260920-cdp-elevated-2db687b9d1c2456e8f7bdd89e6623a15`，覆蓋下方 CDP 尚未通過狀態。完整回歸 final2 為 1764 passed、2 skipped、3 failed：兩項因執行者將 basetemp 放專案而違反 TEMP 契約，一項 Excel 5.017 秒超過 5 秒；未放寬保護或門檻。修正執行環境後的回歸尚待完整結果。已開始獨立 TEMP 建置供檢查，尚非可交付候選；位置記於 `candidate-build-root.txt`。
- 最新 high 核對的八案例同批請求回覆 HTTP 400 `json_validate_failed`；改為符合實際每次 1–4 主張的有界分組，**沒有刪除案例或放寬判定**。`20260920T111151Z-groq-adversarial` 的支持／錯公司／錯單位／錯範圍、`20260920T111255Z-groq-adversarial` 的支持／缺漏推論／無證據因果、`20260920T111341Z-groq-adversarial` 的支持／假反證／日期未知，全部符合預期。此處覆蓋下方「最新八案例尚未重跑成功」的歷史狀態。
- 最新 39 項相關定向測試、10 個新來源檔 mypy、Ruff、compileall、diff check 通過。Black CLI 在 Windows 多程序未正常退出，已停止，改用同版 Black API 的 AST 安全模式格式化本批來源／測試／驗證腳本；未改其它模組。
- CDP `--in-process-gpu` 修正啟動崩潰後，仍在 `Page.enable` 命令逾時；helper 已加 10 秒總等待避免永久卡住。沒有跳過或改寫產品斷言。Edge 隔離啟動亦不可用，未加入覆寫選項。正確認在 Codex sandbox 外執行隔離測試是否解決巢狀程序限制，Chrome 自身 sandbox 維持啟用。
- Chrome 的上傳權限仍未確認；工具也禁止代開 `chrome://extensions/`，未繞過。已提供較簡單的手動方式：在隔離頁選擇 `D:/Temp/stocktool-workflow-groq-ct_pyzxr/browser-restore.json`。此檔只含合成持股與公開公司資料；實際瀏覽器上傳還原仍待完成。

- 9/19 真實 JPM 正向流程 `20260919T133040Z-groq-live` 通過生成、模型引用核對及程式層保存／備份還原；`20260919T133204Z-groq-adversarial` 一個支持案例與七個錯誤案例結果符合預期。這不是模型永遠正確的保證。
- 9/20 增加真正反證正向案例後，發現模型會把「有乙業務，所以不是只有甲業務」誤判；中間失敗、HTTP 400 `json_validate_failed`、逾時均保留在當日 `*-groq-adversarial` 目錄，不挑掉失敗。最終核對使用同一 GPT-OSS 模型的 high 推理，核對輸出上限 8192、網路等待上限 20 秒；生成仍為 4096／10 秒，畫面整體請求期限 30 秒，本機流程不等待。官方參數依據：https://console.groq.com/docs/api-reference 。
- `20260920T021526Z-groq-adversarial`：不支持的排他性主張拒絕、真正反證接受、反向亂推拒絕。另發現本機原判定不應要求普通公司事實也具備反駁關係，新增引用核對收據版本 2：只有 `counter_evidence` 必須通過 `real_counterargument`；其餘六項支持性檢查仍必須全部通過。版本 1 照舊規則重播，舊 invalid 不被改判或原地覆寫。
- 最新完整真實流程 `20260920T021856Z-groq-live` 已為 `model_reviewed`、保存還原一致，約 15 秒，使用公開 JPM 文件及合成持股。這是單次觀察，不是效能保證或所有公司驗證。
- 最新八案例重測 `20260920T021936Z-groq-adversarial` 被 Groq **HTTP 429 / rate_limit_exceeded** 擋下；已停止追加模型請求，未升級付費，不把這次算通過。舊八案例證據仍有效但不冒稱最新 high 設定已重跑成功。
- 真實瀏覽器已保存 `CANARY_BROWSER_0920` 的 JPM 工作階段，停止並重啟隔離 Streamlit 後公司身分與問題仍一致；見 `20260920-library-before-restart.txt`、`20260920-library-after-restart.txt`。另外用最新真實 Groq 保存檔開獨立隔離畫面，中文草稿、四個原文來源、未知文件日期、分開的請求／完成／模型建立時間均可讀；見 `20260920-real-ai-library-dom.txt` 與截圖。這是原始碼 renderer，尚非 EXE。
- 瀏覽器備份上傳 `fileChooser.setFiles` 兩次回覆 `Not allowed`；Chrome 工具要求使用者開啟 ChatGPT 擴充功能的「允許存取檔案網址」。使用者回覆不確定是否開啟，重新測試仍失敗；**瀏覽器上傳還原仍未驗證**，不以程式 restore 替代該項。
- 首輪完整回歸：1764 passed、2 skipped、2 failed，coverage 83.000743%；Ruff、canonical focused mypy 63 檔通過。此輪早於後續語意修正，不是最終回歸。兩項失敗：舊二進位 coverage 產物被掃描當文字、Chrome GPU 程序崩潰致 CDP 無法啟動。
- 舊 `20260914-coverage-data` 已核對為完整 coverage SQLite，移到 `D:/Temp/stocktool-workflow-coverage-archive/20260914-coverage-data`，SHA256 保持 `260CEBE8C045820BB964CD2D2CA673D81C4C7ED2AA8FD0585F60E726F495358F`；沒有放寬隱私掃描，四項 release readiness 重測通過。可讀 coverage JSON 留在證據目錄。
- CDP helper 最小修正由 Luna worker 處理：隔離 Chrome 加 `--in-process-gpu`，保留 stderr 與退出碼，不用 `--no-sandbox`、不跳過產品斷言。尚待本輪定向結果與最終完整回歸。

下一步：完成 CDP 定向與最終工程檢查，補上實際瀏覽器上傳還原；latest high 八案例已由上方有界分組完成，不再無故重跑外部 AI。所有門檻完成才建置並凍結唯一交付候選，交 Sol 獨立驗收。

## 最新狀態：2026-09-19（下方 9/14 記錄為歷史，不代表現況）

整批仍未完成、未建置候選、未發布，未修改真實持股。使用者已建立 StockTool 專用 DPAPI 金鑰並確認 Groq Free；已以該金鑰完成真實請求，無付費升級或備援。金鑰不再是阻擋。

- `local_credentials.py` 只讀取專用 DPAPI 檔，延遲於請求執行緒解密，不回傳或記錄金鑰。UI 必須明確確認免費帳號及送出，沒有渲染時自動呼叫。
- `LocalGroqTransport` 每次最多生成與引用語意核對各一次，無自動重試；HTTP 端點固定且拒絕轉址。語意核對依公司、範圍、數字／單位／日期、條件、缺漏推論及真實反證逐項判定。通過只標示模型核對草稿，不宣稱人工核實。
- 保留供應商產生時間與本機完成時間；工作階段保存完整本機證據、實際外送選取及回應／核對收據。舊工作階段與選取版本走版本分支，不改寫 Research Library v1/v2。
- 真實 JPM 公開資料測試位於 `research-workflow-evidence/20260919T131506Z-groq-live`、`20260919T131705Z-groq-live`、`20260919T131956Z-groq-live`、`20260919T132141Z-groq-live`。所有失敗保留，不挑選成功結果掩蓋。最後一次仍因模型補寫來源未支持的營收敘述被拒絕，**不能宣稱真實 AI 研究品質通過**。
- 實測發現證據只選業務標題會缺上下文，新增選取 V2：只加入同文件緊鄰的原文說明，留下原文座標；仍經私密內容排除。數字前置檢查修正 `80 million` 與 `8000 萬` 的等值辨識，不取消後續單位／期間語意檢查。
- 修正模型日期／核對 JSON 損壞造成 controller 例外：保存 invalid 並丟棄不可接受原文，重複輪詢狀態一致。生成與核對兩個 HTTP body 已用替身攔截確認公開 payload／answer 精確一致，私密問題 canary 與金鑰不進 body；這是程式邊界測試，不冒稱供應商端稽核。
- 最新八檔定向測試 90 passed（pytest exit 0，2026-09-19）；包含 Groq transport、controller、UI AppTest、語意核對、AI 保存、public request、work session 與 citation preflight。完整回歸、候選 EXE／隱私掃描尚未重跑，不能引用舊數字封口。
- 社群五篇（重複去除）、可見留言及一手 README 的取捨已記入 `social-reference-review-2026-09-19.md`；Roan 附件尚未完整讀完、Threads 專案未復原，明確保留限制。不因此擴張本批功能。

接續優先：選取版本相容／相鄰私密內容測試；取得有實際證據支持且新手能讀的真實 AI 正向流程，另做真實語意反例；完成隔離瀏覽器保存／重啟／備份還原及 CDP 問題；最後完整回歸、品質門檻、建置一個候選交 Sol。外部 AI 失敗不應阻塞本機研究。

2026-09-14。使用者已核准整批，Astra 實作、最後 Sol 獨立驗收。A 本機主要流程已有證據，仍未封口；B 已準備不付費的請求／引用前置邊界，尚未整合成可用外部 AI。整批未完成、未建置候選、未發布／更新桌面、未修改真實資料。正式範圍見 `next-research-workflow-plan.md`。

## 2026-09-14 接續實作

### 本日第二輪（仍不可交付完整候選）

- `request_controller.py` 與畫面已串接明確送出、請求去重、非阻塞 fragment 輪詢、切換／無公司證據時丟棄舊回應、保存失效紀錄。正常呼叫者未傳入 transport，故不會自行啟用外部服務。
- `groq_transport.py` 已備妥但未接正式設定：固定官方端點、禁止轉址、明確免費帳號確認、指定模型、回應大小與網路等待上限、安全錯誤、無重試及工具呼叫。依據 https://console.groq.com/docs/openai 與 https://console.groq.com/docs/structured-outputs；只以替身驗證，不代表帳號免費狀態或模型可用性已證實。
- 使用者明確回覆尚未建立專用金鑰；本輪未讀取任何憑證，未呼叫外部 AI。
- `20260914-targeted-final.log`：98 passed in 7.34s；含實際 Streamlit AppTest 的送出與失效呈現，以及未設定／ETF 不提供送出。這不是瀏覽器 E2E。
- `20260914-full-tests.log`：1719 passed、2 skipped、1 failed，coverage 82.98%；唯一失敗仍為 CDP 連線。這輪早於新增 Groq 與 AppTest 測試，不能當最終交付回歸。
- 全 src/tests Ruff 通過；既定 focused_mypy 63 檔通過，記錄 `20260914-focused-mypy.log`。額外全 src mypy 有 111 個既有型別／缺 stubs 錯誤，並非本專案既定 focused 門檻，不宣稱全 src mypy 通過。
- 實際瀏覽器已載入暫存隔離 UI 並展開公開預覽；點擊離線固定回應按鈕兩次均被自動核准審查因模型滿載拒絕，未繞過。因此瀏覽器送出／保存／上傳還原不能標通過。暫存位置索引 `20260914-ui-runtime.json`，服務已停止。
- 核心未完工項：真正引用支持／反證語意判定與有效結論路徑、供應商的明確設定啟用與真實模型／canary、瀏覽器保存還原與 CDP、最後完整候選品質門檻。金鑰不是唯一缺口，不可只補金鑰就宣称可驗收。

- 新增 `research/ai_attempt.py`：保存實際公開輸入、選取清單、供應商／模型、請求及完成時間、失效或未驗證原文；讀取時重新核對快照和前置引用狀態，禁止把保存標籤改成 valid。完成時間不冒充模型產生時間。
- 非空 AI 紀錄使用工作階段版本 2；純本機版本 1 不改寫。這兩種工作階段版本與既有 Research Library v1/v2 是不同格式。備份／還原沿用完整性核對。
- 研究庫新增純文字診斷呈現，明示不是有效結論；另存接續版本保留原請求與證據绑定。
- 本輪定向驗證：AI 保存／工作階段／請求／引用前置共 60 項通過；研究庫與持股回歸 31 項通過。Ruff、三個變更來源檔 mypy、diff check 通過。尚未對新增紀錄作真實瀏覽器驗證或最終完整回歸。
- 尚待：非阻塞送出 UI、供應商接入、真正語意核對與有效結果路徑、真實零費用模型／canary、瀏覽器還原與 CDP 問題。不得將本輪保存功能當成 B 完成。

## 已實作

- `research/work_session.py`：市場＋代號＋類型嚴格組合、雙快照指紋、分項日期、完整公司文件；新增不可覆寫的版本化工作階段、完整依賴保存與備份／還原，不改寫 Research Library v1/v2。
- `research/public_selection.py`：從空物件建立公開證據白名單及選取清單。自由文字研究問題只留本機；外送問題改選公開公司問題。未建立外部呼叫，不把持股或本機路徑送出去。
- `dashboard/components/work_session.py`：組合內容、保存、研究庫重開／另存接續、備份與只新增的還原、公開傳送預覽。
- 持股分析與研究入口共用一個選擇；舊持股摘要強制保持本機模式。公司研究表單依完成切換的身分同步；排除泛談 AI 就業的風險段落。
- 公司研究 profile 新增經來源身分匹配才接受的標的類型。舊 profile 未確認類型時拒絕組合，不能猜成股票。
- 修正銀行部門 `and`／`&` 同義寫法；收緊損毀身分、行情來源與中文解釋格式的拒絕，Windows Python 3.11 以 reparse 屬性拒絕連結目錄。
- `research/public_request.py`：只接受重新核對後的公開請求，非阻塞輪詢、逾時與換標的丟棄、截斷拒絕、安全錯誤與本機請求收據；只測 transport 替身，尚未接網路與 UI。
- `research/citation_preflight.py`：原文、ID、數字缺失與條件語氣等可判定錯誤會拒絕；其餘全部未驗證，**沒有有效結論的通過路徑**。這只是前置檢查，不等於單位／期間／公司歸屬／反證語意驗證。

## 已驗證與限制

- 最新十個相關檔案定向測試 **158 passed in 10.06s**，記錄 `research-workflow-evidence/targeted-current.log`。含工作階段、public request、citation preflight、持股／研究／研究庫、公司資料及解釋。
- 一輪完整回歸 **1698 passed／2 skipped／1 failed**（由原始進度符號計數；設定雙 quiet 未印總數摘要），coverage **82.72498851754789%**。唯一失敗為既有 `test_browser_e2e_cdp` 無法連線至自行啟動的 CDP browser，未進入產品操作。記錄 `full-tests-a.log`、`coverage-a.json`；不宣稱全套通過。這輪收集在 citation_preflight 的 12 個測試新增前，故不代表最終整批版本。
- 新模組 Ruff、mypy 已分批通過；`git diff --check` 通過。初次 fixture 問題已修正；company deadline 測試隔離 Yahoo 快取設定。
- 真實瀏覽器在合成資料頁完成選擇 3006、保存問題、研究庫重開；可讀完整公司說明與本機問題，00935 維持基金說明。加入合成 USD/TWD 後，頁面總值 TWD 4,620、JPM 原幣市值 USD 70、集中度 48.5%，均為合成數據，不代表市場價格。
- 乾淨程序已確認 JPM 持股→研究→返回身分一致，搜尋欄 JPM／US；重啟後重開 3006 保存版本仍是 3006。先前開發熱重載的 class 混用未在乾淨程序重現。瀏覽器觀察與 DOM 放在 `research-workflow-evidence/a-browser-observations.md` 和 `a-restarted-library-dom.txt`。
- 最新合成頁選定 3006 到 DOM 確認身分、業務與結論限制的觀察上限 32.325 秒，含工具往返；不是渲染效能百分位。完整瀏覽器還原上傳尚未測。
- EXE、候選隱私掃描、最終完整回歸與獨立驗收尚未完成，不能宣布整批通過。

## 外部 AI

使用者最新明確指定：**先維持零額外費用；免費服務也先確認可用性**。已核對 Groq Free 與 Gemini 免費層官方文件，推薦先評估 Groq Free；尚無帳號層／可用模型／StockTool 專用 key 的實測。詳見 `research-workflow-evidence/free-ai-options.md`。沒有啟用計費、建立帳號或呼叫外部模型，不讀取其他工具憑證。

B 的實際模型、真正引用語意及送出 UI 工作仍未完成；不得用本機摘要或前置檢查取代。`ResearchWorkSession` 已支援非空失效／未驗證 AI 紀錄的版本化保存，但沒有有效結論路徑，畫面仍沒有外部送出按鈕。不能為了通過而只驗證 ID 或把未驗證文字當有效結論。

## 接續位置

合成 UI 驗證腳本：`scripts/research_workflow_review_app.py`，只允許 `%TEMP%` 下名稱以 `stocktool-workflow-` 開頭的 runtime，且 AI 金鑰必須空白。現用 `%TEMP%/stocktool-workflow-a-review-20260913`、localhost 8516，使用 `--server.fileWatcherType none` 避免中途換類別造成開發狀態混用。這是原始碼 renderer 驗證，不是 EXE 驗證。

本輪驗證程序已由原 exec session 停止；完整與定向測試程序均已結束。接續時不要假定 8516 仍在運作。此次新增 B 模組尚未接入畫面，不能直接建置交付。

下一步：取得可確認零費用的 StockTool 專用外部服務設定後，實作與實測真正語意核對、版本化 AI 收據／結果保存、非阻塞 UI 及真實傳送 canary；補 A 的瀏覽器還原上傳。CDP 環境失敗保留，不修改測試假通過。最後再執行整批必要回歸與候選品質門檻，只建置一個完整候選交 Sol，不更新舊驗收證據目錄。
