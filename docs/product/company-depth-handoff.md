# 公司研究深度改版交接

2026-09-11。Astra 實作；Sol 獨立驗收。狀態：開發端驗證完成，待 Sol 驗收，未發布、未安裝，沒有更新桌面捷徑或操作真實持股。使用者核准的是所有公司共用的深入研究能力，3006 為驗證案例，不是只替 3006 填固定介紹。

最終候選 EXE SHA256：`AAE6C19E331D4E0BA96E4EDA1401D8FF88941C712F142330C81152101B9A4F06`。完整 payload 共 2,831 檔，私密路徑掃描通過、無 symlink。此雜湊取代前兩版 `25DE0906...`、`E76452C6...`。

開發端最終完整回歸：**1,651 passed、2 skipped、2 warnings**，175.57 秒；branch coverage **82.8264609578778%**，通過 82.71 門檻。研究摘要／研究庫針對性 36 passed；Black、Ruff、focused mypy、六個研究模組 mypy、compileall、project privacy、release layout、git diff --check 通過。完整日誌與精確結果在 `company-depth-evidence/`。

## 改了什麼

- 原本只用公司簡介匹配通用產業規則；現在從身份已確認的公司官網讀取產品、規格、應用、營運與公司揭露風險，逐項附原文、URL、內容日期與取得時間。
- 產品列示、規劃、送樣、來源提及量產分開。產品存在不等於營收重要，也不因 DDR／AI 字樣推導 HBM 受惠。
- 研究首頁使用完整寬度顯示公司資料，產品與應用、營運與風險、來源與缺口分開。產業研究問題明確標為待查問題。
- 公司資料與 AI 證據共用 dossier；公司資料變更會改變研究指紋。重新讀取只刷新目前公司的文件，保留已載入行情及其他公司的快取。
- 實際 EXE 操作發現兩個整合問題並修正：刷新後原畫面仍使用舊快照；公司證據超過 32 項時，本機摘要截斷但引用未截斷，導致研究庫拒絕保存。前者同步 UI／AI 快照，後者保留下一步欄位並由實際保留的摘要產生引用。

主要位置：`company_documents.py`（取得邊界）、`company_dossier.py`（抽取與快取）、`company_research.py`（身份整合）、`dashboard/components/company_dossier.py`（共用畫面）、`dashboard/app.py`／`shell.py`／`pages/research.py`（流程）、`research/evidence.py`／`assistant.py`（證據與保存一致性）。以 evidence/source-hashes.json 核對本次原始碼。

## 資料供應與底線

| 資料 | 來源／取得條件 | 更新／失敗 | 限制 |
| --- | --- | --- | --- |
| 公司身份、官網、產業 | 現有 Yahoo 公司 metadata；回傳代號吻合且 EQUITY | 原身份流程；不能確認就不猜官網 | 台股上市／上櫃、美股走同一入口；ETF 不套公司 dossier |
| 產品、技術、應用 | 已確認官網的 HTTPS HTML 與同網域連結 | 快取一天；可手動重新讀取 | 每次最多 14 頁／90 秒、每頁最多 2MB；不是全站或完整年報 |
| 營運、收入、風險 | 官網報告頁及明確公司敘述 | 每項保留自己的日期；缺內容就列缺口 | 不把產品廣告、合作方收入或資安產品當公司財務／風險 |
| 日期 | 網頁發布 metadata 與實際取得時間分開 | 未標示就明說；不以取得日冒充發布日 | 不從 URL 年份或無關 time 元素推斷 |
| AI | 原有證據整理入口 | 無模型時本機規則；舊文件為警告證據 | 外部 AI 未實測；不能補造缺失事實 |

公開可讀不等於已取得再散布授權。本次為本機研究、有限摘錄及原文連結，沒有新增商業資料契約或外部發布；各公司授權條款並未逐站完成審查。

下載限制：拒絕 IP／本機／私有網路、跨公司網域及不安全重新導向；DNS 位址驗證後固定連線位址，TLS 驗證保留。不執行網頁指令、JavaScript，不帶登入 cookie，不繞過 403。PDF 及需 JS 的資料目前不自動解析。

全部刷新失敗時保留舊文件與舊取得日並標過期，不能顯示成新成功。部分頁面失敗保留缺口。快取核對身份、網域、結構及日期；不是為本機惡意修改提供密碼學來源認證。

## 實際使用證據與限制

3006 的隔離 EXE 能取得 DDR4、4Gb／8Gb、3200Mbps 及官網量產原句，另有 DDR I／II／III、NOR／NAND、PSRAM、KGD／MCP。該公告未提供可確認的發布 metadata，畫面明確標示日期未確認，不能當成最新量產消息。刷新前後收盤仍為 TWD 312.00，公司文件取得時間從約 13:34 UTC 推進到 13:35 UTC。

最終保存修正版在全新 runtime 查 3006 後，UI 顯示「已儲存研究庫版本 1」。另以新 Python 程序讀回研究庫，37 項證據中含 16 項公司原文，本機摘要 32 項、mode=local_rules、下一步保留；DDR4 原文及自己的來源日期仍在。參見 `exe-final-save.txt`、`saved-bundle-check.json`。

`*-probe*.json` 是開發過程的線上診斷，不代表最後分類結果；`source-before-refresh.txt` 亦為歷史。`exe-before-refresh.txt`、`exe-after-refresh.txt`、`exe-3006-*` 來自保存修正前候選，證明當時相同公司取得／刷新程式的行為；`exe-saved-research.txt` 保留當時的保存失敗。`exe-final-3006.txt`、`exe-final-save.txt` 與 saved-bundle-check.json 來自保存修正版 E76452C6；最後 AAE6C19E 候選另以 `exe-final-bank-*` 及 `exe-final-restart-library.txt` 核對跨產業與重啟保存。JPM-final-replay.json 是同一批公開文件的離線分類重播，非新線上抓取。 官網原文是公司主張，不是獨立查核財務結論。

不能承諾每家公司同樣完整：2330 官網探測遇到 403；部分美股財報需 JS／PDF。英文原文仍保留英文，沒有新增自動中文翻譯。既有完整研究分數、情境區間與通用風險文字未在這批重設。這一版改善的是可追溯公司細節，尚非完整中文投資研究報告。

## Sol 重跑五項任務

最後 EXE 實測補充：JPM 官網角色為金融服務公司，業務包含消費／社區銀行、商業／投資銀行、資產／財富管理；營運頁可見年報的收入及淨利原句。使用 9/10 隔離快取，取得時間仍為 9/10，沒有偽裝成 9/11 新抓取。重啟後「研究庫 → 3006 版本 1 → 查看保存版本」可讀到 DDR4、來源引用與本機模式說明。

請 Sol 特別判斷產品品質而非只看測試：銀行風險摘錄仍偏管理層對監管／壓力測試的評論，不等於完整風險排序；年報可能同列 2025 與歷史年度原文；英文仍多。操作中也觀察到搜尋區重複／舊控制殘留，已記錄在 DOM，未擴大重寫首頁。這些限制意味著不能宣称「所有公司研究已完整」或「三分鐘中文重點已達標」，是否阻擋本次產品驗收由 Sol 提出證據、使用者決定。

1. 全新隔離 runtime 查 3006/TWSE：三分鐘內指出 DDR 世代、容量／速度、產品狀態，能打開來源核對；分得清未標示日期與最新資料，不能把列示產品當營收占比。
2. 查不同產業（如 JPM/US、MSFT/US）及來源拒絕案例（如 2330）：顯示相應業務／產品與研究問題，不能套記憶體模板；讀不到要明示，不猜補。
3. 按重新讀取公司資料：文件取得時間推進、行情不重抓；UI／AI 證據同份更新。模擬網路失敗或過期／混入其他公司快取後，不得把舊／外來內容當新事實。
4. 儲存詳細公司研究、重啟並讀回：產品來源與各自日期保留；本機摘要／引用一致、沒有冒充模型。特別測超過 32 項證據情境。
5. 回歸原持股功能：MU／台股／ETF 身份與估值、個人輸入保存、不可信價格阻擋仍有效。只用假資料。外部 AI、CDP、舊 Excel、正式安裝／發布若未操作，維持未驗證。

## 隔離啟動

使用 evidence/candidate.json 指定的完整 payload 及 SHA256，不只複製 EXE。先確認 8501 未被其他服務佔用，於新的 PowerShell 執行：

```powershell
$candidatePath = Join-Path $env:TEMP 'stocktool-company-depth-candidate/StockToolPayload'
$reviewRuntime = Join-Path $env:TEMP ('stocktool-sol-company-' + [guid]::NewGuid().ToString('N'))
$env:STOCK_TOOL_USER_DATA_DIR = $reviewRuntime
$env:LOCALAPPDATA = Join-Path $reviewRuntime 'local-app-data'
$env:STOCK_TOOL_NO_BROWSER = '1'
$env:STOCK_TOOL_AI_API_KEY = ''
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:REQUESTS_CA_BUNDLE = Join-Path $candidatePath '_internal/certifi/cacert.pem'
& (Join-Path $candidatePath 'StockToolPayload.exe')
```

開 http://127.0.0.1:8501。不要沿用真實 runtime，也不要預先建立 Yahoo DB。測試結束只停止自己的候選程序。

回歸命令（另一個 shell，代理設定不可帶進線上 EXE）：

```powershell
$env:PYTHONPATH = 'src'
$env:STOCK_TOOL_USER_DATA_DIR = Join-Path $env:TEMP 'stocktool-sol-company-tests'
$env:HTTP_PROXY = 'http://127.0.0.1:9'
$env:HTTPS_PROXY = 'http://127.0.0.1:9'
.venv/Scripts/python.exe -X utf8 -B -m pytest -o addopts='' -q --ignore=tests/test_browser_e2e_cdp.py --cov=stock_tool --cov-report=term:skip-covered --tb=short -ra
```

不可用本機代理使既有排程測試意外外連快速失敗，沒有額外排除排程案例。Windows symlink 權限跳過與 CDP 排除須如實報告；單元測試通過不能取代上述實際操作。
