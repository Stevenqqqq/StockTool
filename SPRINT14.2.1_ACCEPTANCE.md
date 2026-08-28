# Sprint 14.2.1 Acceptance

## 狀態

Implementation complete and ready for independent CTO acceptance review.

本輪只修正 Research Workspace 返回 Daily Research Home 的導覽狀態；沒有替換正式 `release\\StockTool`，也沒有開始 Sprint 15。

## 重現與根因

重現流程：從研究首頁搜尋 `MU`，進入 Micron Technology Research Workspace，按「返回今天先看這些」，再觀察下一次 Streamlit rerun。

根因是 `_render_home_workspace()` 在首頁流程尾端只要看見非空 `research_snapshot` 就重新設定 `dashboard_show_research_workspace=True`。返回按鈕雖然先將旗標設為 `False` 並 rerun，但有效 snapshot 仍被保留，因此下一次 rerun 又強制開啟同一個研究頁。

## 修正與狀態契約

修改採最小範圍：

- `src/stock_tool/dashboard/shell.py`
  - 新研究搜尋成功建立 snapshot 時，明確設定 `dashboard_show_research_workspace=True`。
  - 首頁 rerun 只有在既有旗標已為 `True` 時才進入研究頁；snapshot 本身不再代表使用者想立即開啟研究頁。
  - 返回按鈕維持 `dashboard_show_research_workspace=False`、`st.rerun()` 與 snapshot 保留行為。
- `tests/test_dashboard_shell.py`
  - 新增返回後 rerun、成功搜尋、明確重新開啟既有 snapshot、失敗搜尋保留首頁狀態的回歸測試。
- `release/staging/StockTool/StockTool.exe`
  - 由既有 `build_exe.bat` staging 流程重建；未提升至正式 release。
- `release/baseline/stocktool-sprint14.2.1-20260722-source.zip` 及 `.sha256`
  - 以現有安全 allowlist 建立本 Sprint source archive。

狀態規則如下：

| 情境 | `research_snapshot` | `dashboard_show_research_workspace` |
|---|---|---|
| 新搜尋成功並建立 snapshot | 保留新 snapshot | `True` |
| 返回 Daily Research Home | 保留原 snapshot | `False` |
| 返回後一般 rerun | 保留原 snapshot | 維持 `False` |
| 使用者明確繼續／開啟最近研究 | 保留 snapshot | 由明確流程設為 `True` |
| 新搜尋失敗 | 保留上一份有效 snapshot | 不因失敗搜尋強制設為 `True` |

## 測試

先以 TDD 新增 RED 測試，現況確實重現了「返回後旗標被改回 True」及成功搜尋未明確設定旗標；完成最小修正後執行：

```text
.venv\\Scripts\\python.exe -m pytest tests/test_dashboard_shell.py -q
5 passed

.venv\\Scripts\\python.exe -m pytest tests/test_dashboard_shell.py tests/test_dashboard_state.py tests/test_dashboard_navigation.py tests/test_daily_home.py tests/e2e/test_research_journey.py -o addopts='' -q
34 passed in 15.03s

.venv\\Scripts\\python.exe -m coverage erase
.venv\\Scripts\\python.exe -m coverage run --branch -m pytest
.venv\\Scripts\\python.exe -m coverage report
636 passed in 96.04s
TOTAL branch coverage: 82%
```

現行 `pyproject.toml` coverage gate 為 `78.50%`，本次實測未降低門檻。

品質檢查：

```text
.venv\\Scripts\\python.exe -m black --check src/stock_tool/dashboard/shell.py tests/test_dashboard_shell.py
2 files would be left unchanged.

.venv\\Scripts\\python.exe -m ruff check src/stock_tool/dashboard/shell.py tests/test_dashboard_shell.py
All checks passed!

.venv\\Scripts\\python.exe -m mypy --ignore-missing-imports src/stock_tool/dashboard/shell.py tests/test_dashboard_shell.py
Success: no issues found in 2 source files
```

## Staging EXE 驗證

- 路徑：`C:\Users\steve\OneDrive\Documents\股票\release\staging\StockTool\StockTool.exe`
- 版本：`1.2.2`
- 大小：`24,119,950` bytes
- 修改時間（UTC）：`2026-07-22T14:34:52.6482750Z`
- SHA-256：`1FD70CB3610C7F1CAE64E7D16B082556E5D879C94B10E9F8F35CB88B18B2EBC4`

隔離 `STOCK_TOOL_USER_DATA_DIR` smoke 結果：

- `/_stcore/health`：HTTP 200，body `ok`
- 首頁：HTTP 200
- `reports`、`logs`、`data\\cache`：可寫入
- 測試程序已關閉：StockTool process `0`
- 8501/8502 listener：`0`

研究首頁返回流程由 deterministic shell orchestration regression tests 覆蓋；staging EXE 已完成 HTTP health／首頁 smoke。未把瀏覽器點擊結果冒充成已完成的 packaged-browser E2E。

## Privacy 與使用者資料

Staging release 掃描結果：

- 禁止私人檔名（`.env`、`secrets*.toml`、`portfolio.csv`、`watchlist.csv`、runtime SQLite、reports、logs、cache、私鑰檔）：`0`
- 文字檔 private-key marker：`0`
- `.env.example`：允許且存在
- `certifi/cacert.pem`：公開 CA bundle，非私鑰，保留為執行依賴
- source archive：required inputs missing `0`、forbidden entries `0`、content mismatches `0`

真實使用者資料僅以路徑、大小、修改時間與 SHA-256 唯讀驗證，未讀取內容、未執行 migration、未修改：

| 路徑 | 驗證前／後狀態 |
|---|---|
| `%LOCALAPPDATA%\\StockTool\\data\\portfolio.csv` | exists，131 bytes，SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `%LOCALAPPDATA%\\StockTool\\data\\watchlist.csv` | absent |
| `%LOCALAPPDATA%\\StockTool\\data\\processed\\stock_data.sqlite` | exists，319,488 bytes，SHA-256 `CF40B073EE2378F752A0499075F156F3F28DD34CB8747BDEF8D6C99608F2058F` |
| `%LOCALAPPDATA%\\StockTool\\settings.json` | absent |

驗證前後狀態一致。正式 EXE `release\\StockTool\\StockTool.exe` 未修改，SHA-256 仍為 `AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F`。

## Source archive

- 路徑：`release\\baseline\\stocktool-sprint14.2.1-20260722-source.zip`
- entries：`262`（含 `SOURCE_ARCHIVE_MANIFEST.json`）
- SHA-256：`C4E8F65700E02B114F523645B24AE743E849FDF916D96FF14898C2D9D041652E`
- sidecar 與實際 ZIP hash 一致，無字面 `\\n`
- 已使用 keyword-only `verify_source_archive(archive_path=..., extracted_root=...)` 驗證，missing required inputs `0`、forbidden entries `0`、content mismatches `0`
- archive 內確認包含 `src/stock_tool/dashboard/shell.py` 與 `tests/test_dashboard_shell.py`

## 已知限制與 rollback

- 本輪未修改正式 release；需經獨立 CTO acceptance 後才可進行 promotion。
- 直接使用瀏覽器操作 packaged EXE 的完整點擊旅程未被宣稱已完成；目前以 shell orchestration regression 與 staging HTTP smoke 作為可重現驗證。
- 一個本輪隔離 smoke runtime 目錄因目前 PowerShell 安全策略拒絕遞迴刪除，未能以工具刪除；process、listener 與正式使用者資料均已確認安全。該目錄位於 `%TEMP%\\stocktool-s1421-smoke-20260722-01`，不在 workspace、release 或使用者資料目錄。
- rollback：保留目前正式 `release\\StockTool` 不變；若 staging acceptance 不通過，繼續使用既有正式版本，不執行 promotion。

本 Sprint 完成後停止，未開始 Sprint 15。
