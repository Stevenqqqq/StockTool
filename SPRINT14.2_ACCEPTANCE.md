# Sprint 14.2 Acceptance

## Status

Implementation complete and ready for independent CTO acceptance review.

本文件只記錄 Sprint 14.2 的 repository、application bridge 與交付驗證。本 Sprint 未開始 Sprint 14.3 或 Sprint 15，也未進行正式 release promotion。

## 目標與範圍

Sprint 14.2 將已通過驗收的 immutable Portfolio Ledger 建立為可重新啟動讀取的本機持久化邊界：

- 以專用 SQLite repository 保存 `LedgerEntry`。
- 保持 append-only、可稽核、可重播與 deterministic ordering。
- 透過 `PortfolioLedgerService` 提供 application boundary。
- 保留 legacy portfolio CSV 的 read-only preview 與明確觸發 bootstrap。
- 不接 Dashboard transaction-entry UI，不自動遷移真實 `portfolio.csv`，不變更會計 replay 語意。

## 修改與新增檔案

核心修改：

- `src/stock_tool/portfolio/ledger_repository.py`：新增 append-only SQLite repository、schema version、payload hash、transaction rollback 與 fail-closed validation。
- `src/stock_tool/application/portfolio.py`：新增 repository application bridge、persisted replay、read-only legacy preview 與 explicit bootstrap。
- `src/stock_tool/runtime_paths.py`：新增 canonical `data/ledger/portfolio_ledger.sqlite` 路徑與隔離 runtime directory。
- `src/stock_tool/portfolio/__init__.py`：匯出 repository API。
- `src/stock_tool/application/__init__.py`：匯出 `LedgerBootstrapOutcome` 與既有 portfolio service API。

測試：

- `tests/test_portfolio_ledger_repository.py`
- `tests/test_portfolio_ledger_application.py`

`src/stock_tool/portfolio/ledger.py` 的 domain validation、FX fee 公式與 `replay_ledger()` 未被本 Sprint 重寫。

## Repository 契約

### Schema

- Database：dedicated SQLite file。
- Schema table：`ledger_schema`。
- Schema version：`1`，以 `schema_key='version'` 與 `schema_version` 保存。
- Entry table：`portfolio_ledger_entries`。
- Replay index/order：`effective_at ASC, sequence ASC, entry_id ASC`。
- 未支援、較新或結構不完整的 schema 會以 `LedgerSchemaError` / `LedgerRepositoryError` fail closed；不會靜默建立替代 schema，也不會刪除未知 table 或欄位。

### Exact payload and identity

- Decimal 來自 `LedgerEntry.to_dict()` 的文字表示，未轉成 float。
- datetime 以 UTC ISO-8601 儲存。
- Symbol 另存 canonical `symbol_code` 與 `symbol_market`，payload 亦由既有 `Symbol` domain model 序列化。
- metadata 由既有 LedgerEntry 正規化後，以 sorted-key、固定 separators 的 JSON 保存。
- `payload_sha256` 由 canonical serialized payload 計算，不使用 Python `repr()`。
- 讀取時重新 `json.loads()`、`LedgerEntry.from_dict()`，並核對 payload、hash 與 identity columns；損毀 JSON、非法 enum、identity mismatch 或 hash mismatch 都不會被忽略。
- 所有資料值透過 SQLite parameters 傳入；沒有以字串拼接資料值的查詢。

### Append-only / atomic / idempotent / conflict

- 新 `entry_id`：插入一筆 immutable entry。
- 相同 `entry_id` 且完整 canonical payload 相同：idempotent no-op，回傳 `inserted=0, unchanged=1`。
- 相同 `entry_id` 但 payload 不同：拋出 `LedgerAccountingConflictError`。
- batch 使用單一 `BEGIN IMMEDIATE` transaction；任何一筆衝突或 SQL failure 都 rollback 整批，先前同批新增不會留下。
- repository 沒有 update、delete 或 replace/upsert 覆寫 API。
- 相同 FX conversion 的 target currency、fee 與 cash legs 由既有 `LedgerEntry` 在 repository 寫入前驗證；非法空白 `target_currency` 在建構階段即拒絕。

## Application Bridge

`PortfolioLedgerService` 提供以下邊界：

- `append_entries(entries)`：明確寫入 immutable entries。
- `load_entries()`：讀取並驗證 repository entries。
- `replay_persisted()`：載入後交由既有 `replay_ledger()` 計算。
- `preview_legacy_frame(frame)` / `preview_legacy_csv(path)`：完全唯讀，不初始化或寫入 repository。
- `bootstrap_legacy_entries(frame)`：只有呼叫者明確執行時才寫入；使用既有 deterministic legacy entry IDs，重複執行為 idempotent。
- `from_runtime_paths(paths)`：明確建立 canonical runtime repository boundary；module import 不建立 database。

不完整 legacy row 仍保留 `MissingData` / import warning，不會編造成本、現金、幣別或歷史交易。原始 CSV 的 bytes 在測試中保持不變。

In-memory `replay(entries)` 與 persisted `replay_persisted()` 對同一批 canonical entries 的 snapshot 相等，包含 FX fee、cash legs 與 target currency 結果。

## Runtime 與資料保護

Canonical runtime database path：

`%LOCALAPPDATA%\StockTool\data\ledger\portfolio_ledger.sqlite`

測試使用 `tmp_path` 或隔離的 `STOCK_TOOL_USER_DATA_DIR`。本 Sprint 沒有對真實 runtime SQLite 執行 migration、bootstrap 或 repository write；真實 `portfolio.csv` 與 `stock_data.sqlite` 僅做唯讀完整性確認。

## 測試與品質結果

以下數字採用本 Sprint 已獨立驗證的實際結果：

- Sprint 14.2 targeted tests：`39 passed`。
- 完整 pytest：`633 passed`。
- Branch coverage：`81.49%`。
- Coverage gate：`78.50%`，通過。
- Focused Black：通過。
- Focused Ruff：通過。
- Focused mypy：通過。

Targeted coverage 範圍包含：

- 所有主要 LedgerEntry types roundtrip。
- Decimal precision、UTC datetime、market-qualified Symbol 與 deterministic metadata。
- ordering、reopen、persisted/in-memory replay reconciliation。
- duplicate no-op、conflicting ID、batch rollback。
- corrupt payload、非法 enum、unsupported schema fail closed。
- read-only legacy preview、explicit bootstrap、bootstrap idempotence 與原始 CSV 不變。
- FX fee、target currency、cash legs 與 blank target currency validation。
- parameterized query regression。

## Staging EXE 驗證

Staging package：

- Path：`release\staging\StockTool\StockTool.exe`
- Size：`24,119,946` bytes
- Last write time (UTC)：`2026-07-22T07:28:48.6141525Z`
- SHA-256：`2C49524FA2A04C727179C678AE175A3328A0F133E2FC223B35D1ED083D25BBA8`

已獨立驗證：

- `/_stcore/health`：HTTP `200`，body `ok`。
- 首頁：HTTP `200`。
- 隔離 runtime 的 `reports/`、`logs/`、`data/cache/` 與 `data/ledger/` 可寫入。
- repository 可在隔離 runtime 建立、append、重新開啟與 replay。
- Smoke 後 StockTool process：`0`。
- Smoke 後 `8501/8502` listener：`0`。

正式 release 未修改：

- Path：`release\StockTool\StockTool.exe`
- SHA-256：`AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F`

本 Sprint 未 promotion staging，也未重新建置或替換正式 release。

## Source archive

- Path：`release\baseline\stocktool-sprint14.2-20260722-source.zip`
- Entries：`262`，包含 `SOURCE_ARCHIVE_MANIFEST.json`。
- SHA-256：`0332EEDE65F29B9F3C758A972DBDA636905ADF4E369A601BAF002C5D3132F9DE`。
- Sidecar：`release\baseline\stocktool-sprint14.2-20260722-source.zip.sha256`。
- Sidecar 內容與實際 archive hash 一致。
- Required build inputs missing：`0`。
- Forbidden entries：`0`。
- Archive content mismatches：`0`。
- Archive 已確認包含 `src/stock_tool/portfolio/ledger_repository.py` 與 `tests/test_portfolio_ledger_application.py`，且 manifest 存在。

本輪只讀確認 archive 與 sidecar，沒有重新產生 archive。

## Privacy 與使用者資料完整性

Staging privacy forbidden-file count：`0`。發行成品未包含真實 `.env`、token、私人資料、portfolio、watchlist、真實 SQLite、ledger runtime database、WAL/SHM、runtime reports、logs 或 cache。

唯讀完整性確認：

- `%LOCALAPPDATA%\StockTool\data\portfolio.csv`：存在，131 bytes，SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`。
- `%LOCALAPPDATA%\StockTool\data\processed\stock_data.sqlite`：存在，315,392 bytes，SHA-256 `FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C`。
- `%LOCALAPPDATA%\StockTool\data\ledger\portfolio_ledger.sqlite`：仍不存在。

上述真實資料未被修改、移動或覆寫；本 Sprint 沒有讀取其內容建立 fixture。`portfolio.csv` 與 `stock_data.sqlite` 的前後完整性均維持不變。

## 已知限制與 rollback

- Ledger repository 尚未接到 Dashboard transaction-entry workflow。
- 沒有自動遷移真實 `portfolio.csv` 或真實 runtime SQLite。
- 尚未接入 broker import、FIFO/tax lots、corporate-action ledger integration、風控情境或 UI。
- 沒有正式發布到 `release\StockTool`。
- Git 仍不可用；本 Sprint 沒有自行安裝 Git。
- SQLite schema version 1 目前只接受既有 supported schema；較新或損毀 schema 會 fail closed，尚未做後續 additive migration。
- 尚未開始 Sprint 15。

Rollback 方式：保留既有正式 `release\StockTool` 與 Sprint 14.1.1 / v1.2.2 baseline；本 Sprint 沒有執行正式 release promotion，因此不需要恢復正式成品。若要撤回本 Sprint 原始碼，可使用前一版 source archive 與正式 EXE，不接觸真實 user-data path。

## Final delivery judgment

Sprint 14.2 的核准實作與交付證據已整理完成，文件狀態為：

**Implementation complete and ready for independent CTO acceptance review.**

完成後停止，等待 CTO 獨立驗收；不開始 Sprint 14.3 或 Sprint 15。
