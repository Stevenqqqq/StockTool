# Sprint 3.1 Acceptance

驗收日期：2026-07-11  
執行環境：Windows、Python 3.11.9、PyInstaller 6.21.0

## Verdict

**Accepted.** Sprint 3.1 的 request boundary、structured failure、canonical MissingData、SQLite connection lifecycle、persistence failure 與 migration rollback 公開行為均已完成並驗證。Dashboard 與 CLI 未接入新服務，Sprint 4 未開始。

## 1. 修改檔案

- `src/stock_tool/application/__init__.py`
- `src/stock_tool/application/results.py`
- `src/stock_tool/application/data_hydration.py`
- `src/stock_tool/application/analysis.py`
- `src/stock_tool/data/storage.py`
- `tests/test_application_request_boundary.py`
- `tests/test_application_services.py`
- `tests/test_storage_connection_lifecycle.py`
- `tests/test_ingestion_migration.py`
- `SPRINT3.1_ACCEPTANCE.md`

本輪未修改 Dashboard 導航、CLI、指標公式、基本面公式、股票評分公式、回測、風控或產品功能。

## 2. 公開 Request Boundary

正式 application request model 為 immutable dataclass：

```python
DataHydrationRequest(
    symbol=Symbol("2330", Market.TWSE),
    start_date="2024-01-01",
    end_date="2024-12-31",
    interval="1d",
)

AnalysisRequest(
    data_request=hydration_request,
    include_fundamentals=True,
)
```

正式入口：

```python
snapshot = DataHydrationService(provider_resolver=resolver).hydrate(hydration_request)
result = AnalysisService(hydration_service=service).analyze(analysis_request)
```

- `Symbol`、ISO `start_date`、ISO `end_date` 與 interval 在 application boundary 驗證。
- Resolver 只接收 canonical request 並回傳 `ContractPriceDataProvider`；provider-specific ticker 規則不在 Application Service。
- ProviderResult 的 requested/resolved symbol、日期區間與 interval 必須和 request 一致，不一致時回傳 structured error。
- 預先綁定 provider 與無參數 `hydrate()` / `analyze()` 暫時保留，僅供舊呼叫端過渡相容。

## 3. Structured Failure 行為

- Contract provider 意外 raise 時，原始例外不會穿透；系統回傳 `ProviderStatus.ERROR`、structured `ProviderError` 與一般使用者可理解的訊息。
- Provider exception 的 token、API key、authorization、password、secret 與敏感 URL query 會套用既有 redaction policy；安全 log 不保存 raw secret 或 raw stack trace。
- Provider metadata 與 request 不一致時，資料不會進入後續分析。
- Indicator 失敗時回傳 partial result，不產生技術指標或 composite score。
- Fundamental 失敗時保留可用的價格與技術分析，並回傳 partial result。
- Stock scorer 失敗時回傳 partial result、safe warning 與 limitation；`stock_score` 為 `None`，不產生假分數。
- `save_price_data()` 或 `record_ingestion_run()` 失敗不會丟棄已取得的 validated frame；lineage persistence failure 會使 `ingestion_persisted=False`。

## 4. MissingData 語意

| Field | 情況 | State |
|---|---|---|
| `technical_indicators` | calculator 未設定 | `not_applicable` |
| `technical_indicators` | calculator 執行失敗或無法判定 | `unknown` |
| `composite_score` | scorer 未設定或因前置分析未執行 | `not_applicable` |
| `composite_score` | scorer 執行失敗 | `unknown` |
| `fundamental_data` | 未要求基本面 | `not_applicable` |
| `fundamental_data` | loader/scorer 未設定或無資料 | `missing` |
| `fundamental_data` | loader/scorer 執行失敗 | `unknown` |
| `price_data` | provider 回傳空資料 | `missing` |
| `price_data` | provider 執行失敗 | `unknown` |
| `price_data` | 超過明確 freshness policy | `stale` |

## 5. SQLite Connection Lifecycle

- 所有 `SQLitePriceStorage` 公開方法統一使用 `_connection()` / `_connection_at()` context manager。
- 成功路徑明確 commit；例外路徑明確 rollback；兩條路徑最後都在 `finally` close connection。
- Windows 相容測試確認正常操作後資料庫可重新命名與刪除。
- SQL binding 例外後同樣可以重新命名與刪除，證明失敗路徑沒有留下 file lock。
- 既有 `prices` schema 與資料內容未變更。

## 6. Migration Rollback 行為

- `rollback_ingestion_runs_migration()` 保留 `prices` 資料並寫入 rollback marker。
- 後續 `initialize()` 不會靜默重新套用已 rollback 的 migration。
- rollback 後 `list_ingestion_runs()` 穩定回傳空清單，不會拋出 raw `sqlite3.OperationalError`。
- `record_ingestion_run()` 在 lineage migration 被 rollback 時回傳明確 domain-level `RuntimeError`；DataHydrationService 會隔離此錯誤並回傳可用 hydration result。
- `backup_database()` / `restore_database()` 仍是重新啟用 lineage schema 的保守回復方式。

## 7. 測試與品質驗證

Sprint 3.1 targeted tests：`76 passed`。

實際指令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_application_request_boundary.py tests\test_application_services.py tests\test_storage_connection_lifecycle.py tests\test_ingestion_migration.py tests\test_provider_contracts.py tests\test_data_providers.py tests\test_regression_baseline.py tests\test_cli.py tests\test_dashboard.py -q
```

完整 pytest：`252 passed in 10.21s`。

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Coverage：`72.63%`，高於要求的 `72.35%`；`252 passed in 18.33s`。

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing
```

Focused Black：passed，9 files unchanged。

```powershell
.\.venv\Scripts\python.exe -m black --check src\stock_tool\application src\stock_tool\data\storage.py tests\test_application_request_boundary.py tests\test_application_services.py tests\test_storage_connection_lifecycle.py tests\test_ingestion_migration.py
```

Focused Ruff：passed。

```powershell
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\application src\stock_tool\data\storage.py tests\test_application_request_boundary.py tests\test_application_services.py tests\test_storage_connection_lifecycle.py tests\test_ingestion_migration.py
```

Focused mypy：passed，0 issues in 5 source files。

```powershell
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\application src\stock_tool\data\storage.py
```

Whole-project 既有 Black/Ruff debt 不屬於 Sprint 3.1，且未被描述為已通過。

## 8. EXE 與 Smoke Test

- 完整路徑：`C:\Users\steve\OneDrive\Documents\股票\release\StockTool\StockTool.exe`
- 建置時間：`2026-07-11T15:11:04.7745882+08:00`
- 大小：`23,691,709 bytes`
- SHA-256：`52D7DC39A681AB64CDA3586CDFF0FD9AB0343AD1CCD3563771C9A93E08730CA0`
- `http://localhost:8501/_stcore/health`：HTTP `200`，body `ok`
- `reports/`、`logs/`、`data/cache/`：存在且寫入 probe 通過
- migration SQL 已包含於 `_internal/stock_tool/data/migrations/`
- smoke test 後 StockTool process：`0`
- smoke test 後 8501/8502 listener：`0`
- smoke test 產生的 reports、logs、cache 檔案均已清理，三個目錄 file count 均為 `0`

Release scan：未發現真實 `.env`、`data/processed`、舊 cache、runtime reports/logs 或私人資料；保留 `.env.example`、7 個版本化 sample data 檔與空的可寫 runtime 目錄。

## 9. Source Archive

- Archive：`C:\Users\steve\OneDrive\Documents\股票\release\baseline\stocktool-sprint3.1-20260711-source.zip`
- Sidecar：`C:\Users\steve\OneDrive\Documents\股票\release\baseline\stocktool-sprint3.1-20260711-source.zip.sha256`
- Archive 大小：`404,450 bytes`
- SHA-256：`DBFA3DA16189AE66C03F08D468801D26B1D8655E9F584E2B59D4F902087838A2`
- 隔離解壓驗證：必要檔案缺少 `0`，禁止的 runtime/private 檔案 `0`

## 10. 已知限制與 Sprint 4 Gate

1. 新 request boundary 尚未接入 Dashboard 或 CLI；這是刻意保留給 Sprint 4 的工作，不是 Sprint 3.1 遺漏。
2. 正式 provider registry / resolver implementation 尚未建立；Sprint 3.1 只定義 request-aware resolver protocol 與相容 adapter 邊界。
3. Redaction 是已測試的 targeted safeguard，不是完整 DLP 系統。
4. Freshness 只有在 caller 明確提供 policy 時判定，不會自行臆測市場交易日。
5. PyInstaller 仍會顯示既有 `pycparser.lextab/yacctab` hidden-import warning，但新 EXE 已通過 health、寫入與 release scan。

**目前沒有已知的 Sprint 3.1 阻擋問題。是否開始 Sprint 4 仍需另行確認；本輪未開始 Sprint 4。**
