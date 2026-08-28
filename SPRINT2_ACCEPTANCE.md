# Sprint 2 Acceptance

驗收日期：2026-07-10  
依據：`PRODUCT_EXECUTION_PLAN.md`、`SPRINT1.1_ACCEPTANCE.md`  
執行環境：Windows 10、Python 3.11.9、PyInstaller 6.21.0。

## Acceptance Verdict

**Sprint 2：Accepted with documented Git constraint。**

本 Sprint 只完成統一 Domain 與 Provider 契約。Sprint1.1 已驗收行為未改，70%
coverage gate 未降低，完整 pytest 從 181 增加為 217 且全部通過。沒有建立
application service、ingestion run、storage migration 或新 UI，因此沒有開始
Sprint3。

環境仍找不到 `git` executable。使用者在已驗證 Sprint1.1 immutable archive 後
明確指示開始 Sprint2；本次沒有自行安裝 Git，也不把 ZIP 描述成真正的 commit、
tag 或 merge history。

## 1. Entry Gate

- Sprint1.1 archive：`release/baseline/stocktool-sprint1.1-20260710-source.zip`
- Sprint1.1 SHA-256：
  `C2F2B6520E960CE9DC8DD2ABF74D241190E6532D8F03B1CA258D129234FB8446`
- Checksum revalidation：passed。
- Sprint1.1 baseline tests：`2 passed`。
- Sprint2 開始前完整 suite：`181 passed`。

## 2. Delivered Contracts

### Canonical Domain

- `Market`：`TWSE`、`TPEX`、`US`、`AUTO`、`CUSTOM`。
- `Symbol`：canonical `code + market`，已知 `.TW`/`.TWO` suffix 只留在
  provider metadata。
- `MissingDataState`：`missing`、`unknown`、`not_applicable`、`stale`。
- `MissingData`：field、state、reason 可穩定 JSON round trip。

### Provider Boundary

- `ProviderResult[T]`：`success`、`partial`、`empty`、`error`。
- `DataSourceMetadata`：provider、來源類型、requested/resolved symbol、provider
  symbol、日期、interval、cache path 與 point-in-time universe 預留欄位。
- `QualityReport`：input/output rows、missing required/optional columns、duplicate
  columns、extra columns、null counts 與 structured issues。
- `ProviderError`：empty dataset、schema mismatch、validation failure、provider
  failure。
- `ProviderAttemptRecord`：保留 provider/fallback 嘗試順序與結果。

外部 DataFrame 先深拷貝，再重用現有 `clean_price_data()` 驗證。缺少
`adjusted_close` 時只建立 null 欄位並回報 partial，不以 close 或其他數值製造
看似完整資料。重複標準欄名直接回傳 structured schema error，不讓 pandas
例外外洩。

## 3. Compatibility And Rollback

- 既有 `fetch_prices()`、CSV/Excel providers、cleaner 與 storage schema 未改行為。
- `fetch_prices_result()` 是新增 wrapper，預設由
  `provider_contracts_enabled=False` 關閉。
- `LegacyPriceDataProviderAdapter` 包裝舊 provider，不取代舊 protocol。
- `adapt_legacy_fetch_result()` 保留來源、requested/resolved symbol、cache、
  interval 與去敏後的 warnings／attempts。
- 本機 legacy provider exception 轉成 generic typed message，不把原始 token/path
  內容放進 contract。
- Rollback：保持 flag 關閉並移除新 consumer；不需要 database rollback。

## 4. Sprint1.1 Protection Evidence

與 Sprint1.1 archive 逐檔 SHA-256 比對：

| Protected artifact | 結果 |
|---|---|
| `tests/test_regression_baseline.py` | identical |
| `tests/fixtures/sprint1_baseline.json` | identical |
| `sample_tw_prices_for_indicators.csv` | identical |
| `sample_fundamental_scores.csv` | identical |

既有 production source 只有事前揭露的四個加法式差異：

- `src/stock_tool/config.py`
- `src/stock_tool/data/__init__.py`
- `src/stock_tool/data/auto_fetch.py`
- `src/stock_tool/data/providers.py`

沒有修改 indicators、scoring、backtest、risk、portfolio、reports、dashboard、
cleaner 或 storage。

## 5. Tests And Quality Gates

| 驗證 | 結果 |
|---|---|
| Sprint2 domain/provider tests | 36 passed |
| Sprint2 + Sprint1 baseline targeted tests | 38 passed |
| Full pytest | `217 passed in 8.14s` |
| Coverage pytest | `217 passed in 15.21s` |
| Coverage | `71.39%`，required 70.0% reached |
| Black（Sprint 2 changed-file／focused check） | passed |
| Ruff（Sprint 2 changed-file／focused check） | passed |
| Focused mypy：domain/contracts/providers/config | passed，0 issues |

本表的 Black/Ruff 結果只代表 Sprint 2 changed-file／focused checks，並不宣稱
全專案格式或 lint 已完全清除。全專案仍有既有格式與 lint debt；其中 source、tests
與 examples 的歷史檢查問題，以及根目錄掃描納入 `release/` 的 PyInstaller bundled
dependencies，均不屬於本 Sprint 的範圍。本 Sprint 沒有為了清除既有靜態警告而修改
Sprint1 runtime signatures。

## 6. Security And Data Integrity Review

- 沒有新增外部 API、dependency、database schema、token 或 secret。
- Provider payload 視為不可信：檢查 empty、missing、duplicate、extra、partial 與
  invalid OHLCV。
- Quality contract 不修改原始 DataFrame。
- Raw provider exception 不進入新 local-file adapter 的 user-facing error。
- Provider warnings、fallback reasons 與 structured error messages 都應遵守同一個
  credential redaction policy；Sprint 2.1 補上 legacy adapter 回歸測試。
- `ProviderResult.to_dict()` 不序列化 raw DataFrame。
- 沒有新增自動下單、AI 預測或投資保證語句。

## 7. Windows EXE Evidence

- Build：`cmd /c build_exe.bat`，passed。
- EXE：`release/StockTool/StockTool.exe`
- EXE SHA-256：
  `863B18A17878BCA7B7662A7915B7F2B91858ECC30184D30F4D15AB74E39B4FA2`
- HTTP smoke：`http://localhost:8501` 回傳 200。
- `reports/` write probe：passed。
- `logs/` write probe：passed。
- 根目錄/release README：SHA-256 identical。
- Sample files：7 個。
- `.env.example`：存在。
- Final startup log：Uvicorn 正常啟動，無 import/runtime error。
- Cleanup：0 StockTool process；8501/8502 listeners 均為 0。

## 8. Source Snapshot

所有 source、tests、coverage、EXE、smoke 與 acceptance 完成後，最後建立：

- `release/baseline/stocktool-sprint2-20260710-source.zip`
- `release/baseline/stocktool-sprint2-20260710-source.zip.sha256`

Snapshot 排除 `.venv`、`build`、`release` 內容、runtime reports/logs、
`data/cache`、`data/processed`、`__pycache__`、`.pyc` 與真正 `.env`，並在隔離
暫存目錄完成必要檔案與 hash 還原驗證。

## 9. Files

新增：

- `src/stock_tool/domain/__init__.py`
- `src/stock_tool/domain/models.py`
- `src/stock_tool/data/contracts.py`
- `tests/test_domain_models.py`
- `tests/test_provider_contracts.py`
- `SPRINT2_ACCEPTANCE.md`

加法式修改：

- `src/stock_tool/config.py`
- `src/stock_tool/data/__init__.py`
- `src/stock_tool/data/auto_fetch.py`
- `src/stock_tool/data/providers.py`
- `README.md`
- `docs/architecture/contracts.md`
- `docs/release/acceptance-v1.1.md`

## 10. Known Constraints

1. Git 不可用且未安裝，沒有真正 merge baseline；ZIP 只提供可恢復 snapshot。
2. 新 provider contract 預設關閉，尚未由 dashboard 使用，這是 Sprint2 的 rollback
   邊界，不是宣稱已完成 Sprint3 integration。
3. `build_exe.bat` 仍複製 `data/processed` 與 `data/cache`，屬既有 release debt，
   本 Sprint 未擴張範圍修正。
4. PyInstaller 仍有既有 `pycparser.lextab/yacctab` hidden-import warnings；最終 EXE
   啟動與 HTTP smoke 均通過，未觀察到 runtime failure。

## 11. Exit Gate

- [x] Sprint1.1 protected artifacts 未變。
- [x] Coverage 不低於 70%。
- [x] 217 pytest 全通過。
- [x] 沒有新增 dependency、storage migration 或 runtime coupling。
- [x] EXE build 與 smoke 通過。
- [x] Acceptance 與 rollback 已記錄。
- [x] 未開始 Sprint3。
