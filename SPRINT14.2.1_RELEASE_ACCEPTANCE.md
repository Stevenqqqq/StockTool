# Sprint 14.2.1 Release Acceptance

## 狀態

Sprint 14.2.1 正式候選已發布，等待 CTO 獨立 Release Acceptance。

本次只進行 staging-to-formal promotion；沒有修改 Python 程式、測試或產品功能，也沒有開始下一個 Sprint。

## 發布前與核准候選

- staging：`release\\staging\\StockTool\\StockTool.exe`
- staging size：`24,119,950` bytes
- staging modified time UTC：`2026-07-22T14:34:52.6482750Z`
- staging SHA-256：`1FD70CB3610C7F1CAE64E7D16B082556E5D879C94B10E9F8F35CB88B18B2EBC4`
- staging version：`1.2.2`
- pre-release formal SHA-256：`AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F`
- pre-release process/listener：StockTool `0`、8501/8502 `0`

執行的發布指令：

```text
$env:STOCK_TOOL_USER_DATA_DIR = <isolated TEMP directory>
cmd /c publish_release.bat
```

既有 `publish_release.bat` 的 rollback-first 流程已執行成功；legacy user-data migration 也在隔離 runtime 內執行，未使用真實 `%LOCALAPPDATA%\\StockTool`。

## Rollback

- 本次 rollback：`release\\rollback\\StockTool-pre-sprint12-release-20260722-230107`
- rollback EXE SHA-256：`AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F`
- rollback assets：通過 `validate_release_assets`
- 既有 `release\\previous\\StockTool` 與其他 rollback 目錄：保留未覆寫
- rollback 方法：停止 StockTool，將正式候選移至 staging/hold，再將本 rollback 目錄移回 `release\\StockTool`，驗證資產與 EXE hash

## 正式發布結果

- formal path：`C:\\Users\\steve\\OneDrive\\Documents\\股票\\release\\StockTool\\StockTool.exe`
- formal size：`24,119,950` bytes
- formal modified time UTC：`2026-07-22T14:34:52.6482750Z`
- formal SHA-256：`1FD70CB3610C7F1CAE64E7D16B082556E5D879C94B10E9F8F35CB88B18B2EBC4`
- formal version：`1.2.2`
- staging/formal hash：完全一致
- required public release assets：通過

## 正式 EXE Smoke

使用全新隔離 `STOCK_TOOL_USER_DATA_DIR` 啟動正式 EXE：

- `/_stcore/health`：HTTP 200，body `ok`
- 首頁：HTTP 200
- `reports`：可寫
- `logs`：可寫
- `data\\cache`：可寫
- 測試後 StockTool process：`0`
- 測試後 8501/8502 listener：`0`

發布腳本內建的 post-promotion smoke 亦已完成並成功返回；正式 EXE 的獨立 smoke 結果如上。

### UI journey

本次程式修正的導覽契約已由 Sprint 14.2.1 驗收中的 deterministic shell regression 覆蓋，引用結果為：targeted 34 passed、完整 pytest 636 passed、branch coverage 82%。其驗證的流程為：

1. 首頁進入研究搜尋。
2. 成功搜尋建立 MU snapshot 後明確顯示 Research Workspace。
3. 按返回後旗標為 `False`，snapshot 保留，首頁 rerun 不會自動重開 MU。
4. 使用者明確要求繼續研究時，保留的 snapshot 仍可重新開啟。

正式 EXE 本次另外完成 health／首頁／runtime writable smoke；沒有把不可由目前 shell 工具直接執行的瀏覽器滑鼠點擊結果冒充成 packaged-browser E2E。

## Privacy scan

對 `release\\StockTool` 執行 allowlist 與隱私掃描：

- `.env`、`secrets*.toml`、`portfolio.csv`、`watchlist.csv`、runtime SQLite、reports、logs、cache：`0`
- 私鑰檔名：`0`
- 文字檔 private-key marker：`0`
- `.env.example`：存在且允許
- `certifi\\cacert.pem`：公開 CA bundle，非私鑰
- release required assets：通過

## 真實使用者資料完整性

以下資料只做唯讀 metadata/hash 比對，發布前後一致，未讀取內容或執行 migration：

| 路徑 | 發布前 | 發布後 |
|---|---|---|
| `%LOCALAPPDATA%\\StockTool\\data\\portfolio.csv` | exists，131 bytes，modified `2026-07-11T08:36:17.7361265Z`，SHA `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` | 完全一致 |
| `%LOCALAPPDATA%\\StockTool\\data\\watchlist.csv` | absent | absent |
| `%LOCALAPPDATA%\\StockTool\\data\\processed\\stock_data.sqlite` | exists，319,488 bytes，modified `2026-07-22T14:00:58.5183791Z`，SHA `CF40B073EE2378F752A0499075F156F3F28DD34CB8747BDEF8D6C99608F2058F` | 完全一致 |
| `%LOCALAPPDATA%\\StockTool\\settings.json` | absent | absent |

發布使用的 migration 與 smoke 均設定隔離 runtime；真實使用者資料沒有任何差異。

## 桌面捷徑

既有捷徑：`C:\\Users\\steve\\OneDrive\\Desktop\\股票分析工具.lnk`

- TargetPath：`C:\\Users\\steve\\OneDrive\\Documents\\股票\\release\\StockTool\\StockTool.exe`
- WorkingDirectory：`C:\\Users\\steve\\OneDrive\\Documents\\股票\\release\\StockTool`
- 未建立重複捷徑

## 已驗收測試與 source archive

本次未重新執行核心 pytest；沿用已驗收 Sprint 14.2.1 結果：targeted 34 passed、完整 pytest 636 passed、branch coverage 82%，高於 `78.50%` gate。

已驗收 source archive：

- `release\\baseline\\stocktool-sprint14.2.1-20260722-source.zip`
- SHA-256：`C4E8F65700E02B114F523645B24AE743E849FDF916D96FF14898C2D9D041652E`

## 已知限制

- 正式 release 已發布，但仍等待 CTO 獨立 Release Acceptance，不在本文件自行宣告通過。
- 目前 publish script 的 rollback 目錄前綴仍沿用既有 `sprint12` 命名；路徑具唯一時間戳且實際 rollback hash／資產已驗證。
- 本輪未開始下一個 Sprint。
