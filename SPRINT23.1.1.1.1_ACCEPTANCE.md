# Sprint 23.1.1.1.1 implementation evidence

狀態：`BLOCKED`。本次只補 browser zoom evidence，沒有修改程式碼、候選、installer、正式 release 或真實資料。

## 候選綁定

- Stable EXE：`release/staging-sprint23.1.1.1/StockTool/StockTool.exe`
  SHA-256 `CB4F48E70F08178D6D6ACB87DC188B00E1A6788DBCD61397A8AC9B6D34E6C61D`
- Payload：`release/staging-sprint23.1.1.1/StockTool/versions/1.2.2/StockToolPayload.exe`
  SHA-256 `C20EDF00EBB8399B9FB73F0EFDAB6252852D04925F7AFD18C554FA8CC9C2DABA`
- Source ZIP：`artifacts/sprint23.1.1.1/staging-sprint23.1.1.1-source.zip`
  SHA-256 `C4CD587634A35366628D576BB6497C70599296167056D5BECF9FEA31A642B0A2`
- 正式 EXE 未變：`4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`
- 完整核對：`artifacts/sprint23.1.1.1.1/hash-binding.json`

## Guard 與資料保全

候選由 `scripts/evidence_launcher.py` 委派 `scripts/browser_transport_harness.py` 啟動；隔離根目錄與啟動程序樹記錄於 `artifacts/sprint23.1.1.1.1/guard-browser/launch.json`。事件後 188-file baseline 的比較為 `artifacts/sprint23.1.1.1.1/real-data-compare.json`：`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。

三個事件檔案未修改，雜湊與既有紀錄一致；正式使用者資料未被測試寫入：

- `backups/legacy-migration-20260803_001635_072959.json`: `7764CE825A2FA9677DB0E0CFB554CF60F74A1D2337C85324A8781D5A6D64888A`
- `logs/streamlit_20260803_001635.log`: `72B838D46EA9DAF705222E804DF43C0A7274A6A5877A3CA7E436DEB50EB81AA1`
- `logs/streamlit_20260803_001635_error.log`: `3E0DC93EFF56111A552B7DE3CC1704812DDE08CE0762F4E94C6EB8839133852A`

## Browser zoom 結果

Chrome 頁面可載入 `http://127.0.0.1:8501`，但 Windows UI 控制在切換到 Chrome 原生視窗時無法可靠確認目前網址。依要求不使用 viewport resize、Playwright keyboard、系統縮放或舊候選截圖替代；因此 100%、125%、150% 三張同時含候選頁、原生選單及實際百分比的 authoritative screenshot 均未取得，三項皆為 `BLOCKED`。詳細 machine-readable 結果：`artifacts/sprint23.1.1.1.1/browser-result.json`。

## Cleanup

`artifacts/sprint23.1.1.1.1/cleanup-final.json` 記錄 `StockTool/StockToolPayload process_count=0`、8501/8502 `listener_count=0`。瀏覽器分頁已結束；證據檔保留。

## 結論

必要的真實原生瀏覽器 zoom 證據缺失，故不能聲稱完成；需在可可靠控制外部 Chrome/Edge 原生選單的環境重新取得三個比例後再驗證。

## CTO 後續驗收決定

CTO 根據使用者親自提供的三張 Chrome 原生縮放畫面完成後續驗收；這不是實作者自行驗收，也不是自動化 browser evidence。原始人工證據已唯讀核對並保存至 `artifacts/sprint23.1.1.1.1/manual-browser/`，machine-readable index 為 `artifacts/sprint23.1.1.1.1/manual-browser/evidence-index.json`。

- 100%：`zoom-100-user-supplied.png`，SHA-256 `092D8293FBEC0E03210EC05DE354831939EC31E06CB59072589D4EEA9C71544A`
- 125%：`zoom-125-user-supplied.png`，SHA-256 `1A716FCE73FDE2F61F36AB5253A603B1A7DDD1FCAE9BBA78A90245AFEED024AB`
- 150%：`zoom-150-user-supplied.png`，SHA-256 `0B5B4FCE79A94B274C09C5FE662046D9E41AEAAEBA11060A54E0796DE4F1E890`

三張畫面均包含 Chrome 原生縮放比例、`http://127.0.0.1:8501` StockTool 研究首頁主要內容，且無可見水平溢位。先前自動控制失敗的歷史紀錄與 `BLOCKED` machine result 保留不變；本節只記錄 CTO 後續人工判定。
