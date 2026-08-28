# Sprint 20.1 implementation evidence

狀態：BLOCKED — 真實瀏覽器控制面不可用，待獨立 CTO 驗收。

本次只修正 Sprint 20 驗收指出的 Explore 來源狀態與自選股串接；沒有新增 provider、dependency、前端框架或儲存系統。

## 修改檔案

- `src/stock_tool/application/explore.py`
  - 本機 concept index 統一回報 `source_state=local_index`。
  - mtime 只作索引檔更新時間；非 `manual_seed` 亦須通過七日索引新鮮度判定，不能由 source 字串單獨判定 fresh。
  - 新增 canonical `remove_from_watchlist`、`current_watchlist`、`is_in_watchlist`。
- `src/stock_tool/dashboard/pages/discovery.py`
  - 顯示「本機索引」及「索引檔更新時間」。
  - 依既有 watchlist repository 顯示「加入自選股／移除自選股」，操作後同步 session state 並 rerun。
- `tests/test_explore_application.py`
  - local_index、missing、partial、stale/fresh mtime 與 TWSE/TPEX/US add/remove idempotency regression。
- `tests/test_dashboard_navigation.py`
  - 實際 Streamlit AppTest 驗證加入、移除與預載 watchlist 的 UI 狀態。

## 測試與品質

- Targeted：`pytest tests/test_explore_application.py tests/test_dashboard_navigation.py::test_explore_watchlist_toggle_updates_persisted_state_and_session tests/test_dashboard_navigation.py::test_explore_watchlist_preloaded_identity_starts_as_remove -q` → 10 passed。
- 完整 `cmd /c quality_gate.bat` → exit 0；`982 passed, 2 skipped`，branch coverage `83.10%`（門檻 78.5%）。
- quality gate 內含 targeted、full pytest、branch coverage、Black、Ruff、focused mypy、compile、project privacy、release layout、regression baseline；結果全通過，詳見 `artifacts/sprint20.1/quality-gate.log`。
- `pip-audit --format json` → exit 0，無已知漏洞；結果 `artifacts/sprint20.1/pip-audit.json`。
- `git diff --check` → exit 0。

## 候選與隱私

- staging：`release/staging-sprint20.1/StockTool`，`build_exe.bat` exit 0。
- stable EXE SHA-256：`33FA8BCDA9B50B170632692E434A989B182D6892C34522C839FFEEC9643882F4`。
- payload EXE SHA-256：`CF07D62266DC40C7064F9F0E083826A66FAD57737A0387321FA907909503BD0B`。
- 候選 hash manifest：`artifacts/sprint20.1/candidate-hashes.json`。
- 候選 `--version`：`1.2.2`；候選 payload/staging privacy validation 通過，project privacy violations `0`。
- performance hard gate：通過，`artifacts/sprint20.1/performance-result.json`。
- source archive：`artifacts/sprint20.1/staging-sprint20.1-source.zip`，SHA-256 `B77AE49277FB06D7A4ACE6A513E41AA221EC3F656B1FD9384E00A2FA89F6E5B1`；獨立解壓驗證 missing/forbidden/content mismatch/duplicate 全為 0，且包含 stable launcher 與 StableLauncher.spec。

## 隔離執行與資料保全

- process-scoped transport harness online/offline/partial 三次均 exit 0；證據位於 `artifacts/sprint20.1/transport-*`，每次使用獨立資料根目錄。
- 真實資料僅讀 manifest：`artifacts/sprint20.1/real-user-data-before.json` 與 `real-user-data-after.json`，185 → 185；`real-user-data-diff.json` 為零新增、零刪除、零內容變更。
- 正式 `release/StockTool/StockTool.exe` SHA-256 前後均為 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。
- 收尾 `StockTool`／`StockToolPayload` process、8501/8502 listener 均為 0。

## 瀏覽器證據與限制

已依瀏覽器控制技能重新嘗試連線，但目前回報 `No browser is available`。因此沒有以 AppTest、fixture、假 JSON 或舊截圖冒充真實瀏覽器驗收；九個情境結果均誠實標為 BLOCKED，見 `artifacts/sprint20.1/browser/browser-result.json`。該結果缺少每一旅程的 screenshot、DOM、active console、transport/provider metadata，故不能宣稱 Sprint 20.1 完成。

下一個具體動作：在可用的真實瀏覽器控制面，以本候選 hash 重新完成 2330/TWSE、6488/TPEX、AAPL/US 的 online、offline/cache、partial 九個旅程，以及 Tab、Shift+Tab、焦點與 100/125/150% 縮放證據，再交由獨立 CTO 驗收。

本文件只記錄 implementation evidence，不代表 CTO acceptance、release approval 或下一 Sprint 核准。
