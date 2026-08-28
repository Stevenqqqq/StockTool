# Sprint 15.1.3 Release Acceptance

**狀態：Sprint 15.1.3 正式候選已發布，等待 CTO 獨立 Release Acceptance。**

本輪只執行正式發布與發布驗證，沒有修改 scanner、Python 核心程式、測試或正式產品功能，也沒有開始 Sprint 16。

## 發布前資訊

實際執行：

```text
cmd /c publish_release.bat
```

| Artifact | Size | Modified UTC | SHA-256 |
| --- | ---: | --- | --- |
| 發布前正式 `release\\StockTool\\StockTool.exe` | 24,119,950 bytes | 2026-07-22T14:34:52.6482750Z | `1FD70CB3610C7F1CAE64E7D16B082556E5D879C94B10E9F8F35CB88B18B2EBC4` |
| 已驗證 staging `release\\staging\\StockTool\\StockTool.exe` | 24,145,141 bytes | 2026-07-26T11:19:29.8887655Z | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

發布腳本先驗證 staging/current release assets，再建立 rollback、驗證 rollback EXE hash、執行既有 legacy user-data migration，最後交換正式目錄。腳本輸出 `Release promotion completed` 且退出碼為 0；末尾另出現 Windows 子程序訊息 `ERROR: Input redirection is not supported, exiting the process immediately.`，因此已另外完成下列獨立 smoke 驗證。

## Rollback

本次唯一時間戳 rollback：

`release\\rollback\\StockTool-pre-sprint12-release-20260726-194205\\`

驗證結果：

- rollback `StockTool.exe` 存在。
- rollback EXE size：24,119,950 bytes。
- rollback EXE SHA-256：`1FD70CB3610C7F1CAE64E7D16B082556E5D879C94B10E9F8F35CB88B18B2EBC4`，與發布前正式版一致。
- `release\\promotion-hold\\StockTool-pre-sprint12-release-20260726-194205\\` 保留存在。
- 既有 rollback/previous 內容未覆寫。

若需回復，停止 StockTool 後先將目前 `release\\StockTool` 保留至隔離位置，再將上述 rollback 目錄複製／移回 `release\\StockTool`，並重新驗證 required assets 與 EXE hash。未執行回復操作。

## 發布後正式版本

正式路徑：`release\\StockTool\\StockTool.exe`

| Item | Actual |
| --- | --- |
| Size | 24,145,141 bytes |
| Modified UTC | 2026-07-26T11:19:29.8887655Z |
| SHA-256 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |
| Staging/formal hash identical | Yes |
| Staging directory after promotion | Absent; staging directory was promoted |

正式 release required public assets validation：通過。正式 release runtime/privacy filename scan：禁止檔案 0；允許的 `.streamlit\\config.toml`：1。

未發現以下項目：`.env`、`secrets*.toml`、token、API key、password、authorization、private key、portfolio、watchlist、SQLite、reports、logs、cache 或私人資料。

## EXE Smoke 與 Port Fallback

兩次 smoke 均使用全新隔離的 `STOCK_TOOL_USER_DATA_DIR`，未使用真實使用者 runtime：

- 正常案例：8501 health HTTP 200、body `ok`；首頁 HTTP 200；`reports`、`logs`、`data/cache` 可寫。
- 8501 被 IPv4 listener 占用：launcher 使用 8502；health HTTP 200、body `ok`；首頁 HTTP 200；隔離 runtime 可寫。
- smoke 後 `StockTool` process：0。
- smoke 後 8501/8502 listener：0。

## 真實使用者資料完整性

只讀記錄發布前後，未讀取或輸出持股內容：

| File | Before | After | Result |
| --- | --- | --- | --- |
| `%LOCALAPPDATA%\\StockTool\\data\\portfolio.csv` | 131 bytes, 4 rows, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` | 相同 | unchanged |
| `%LOCALAPPDATA%\\StockTool\\data\\processed\\stock_data.sqlite` | 339,968 bytes, SHA-256 `2A2FA20A7A6F01FA3B22A942B82D6056A70755824FEF4FF6E8176ED24317CDF7` | 相同 | unchanged |
| `%LOCALAPPDATA%\\StockTool\\data\\watchlist.csv` | absent | absent | unchanged |
| `%LOCALAPPDATA%\\StockTool\\settings.json` | absent | absent | unchanged |

發布腳本依既有安全流程產生了 migration manifest：`%LOCALAPPDATA%\\StockTool\\backups\\legacy-migration-20260726_194211_619418.json`。沒有覆寫上述 canonical portfolio、SQLite、watchlist 或 settings 檔案。

## Desktop Shortcut

已找到唯一符合的捷徑：

`C:\Users\steve\OneDrive\Desktop\\股票分析工具.lnk`

- Target：`C:\Users\steve\OneDrive\Documents\股票\\release\\StockTool\\StockTool.exe`
- Working Directory：`C:\Users\steve\OneDrive\Documents\股票\\release\\StockTool`
- 未建立重複捷徑。

## Source Archive

- Archive：`release\\baseline\\stocktool-sprint15.1.3-20260726-source.zip`
- SHA-256：`F686E60FD79EF6B8598E6F82D0A40ADD3200C1BDAB11DF2C6B708A1C42CFC4F8`
- Sidecar：存在且與 ZIP hash 一致。
- required build inputs missing：0。
- forbidden entries：0。
- archive content mismatches：0。
- workspace content mismatches：0。

## Coverage Reference

本次發布未重新執行測試。Sprint 15.1.3 驗收文件已校正為 CTO 獨立 quality gate 實測 coverage **81.75%**；正式 coverage gate 為 **78.5%**，已通過。文件未宣稱 coverage 不低於 81.76%。

## 限制

- 本次只完成正式 promotion 與發布驗證，未重新 build staging。
- 正式 release promotion 已完成，但仍等待 CTO 獨立 Release Acceptance。
- Sprint 16 未開始。
