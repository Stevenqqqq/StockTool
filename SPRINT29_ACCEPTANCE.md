# Sprint 29 implementation evidence

狀態：**BLOCKED — ready for independent CTO review only**。本文件不代表 CTO 驗收、正式發布或 release approval。

## 範圍與實作

- 新增 `src/stock_tool/application/macro_snapshot.py`：schema-versioned、immutable/fingerprint-bound 的總經快照、FRED 官方 CSV provider、原子 latest/history 儲存、規則式訊號與 evidence reference closure。
- 接入 `RuntimePaths`、`DailyResearchBrief`、Home 與 Dashboard shell。首頁只讀快照；只有「更新總經資料」明確動作才呼叫 provider。
- 每日簡報保留宏觀 context、來源、日期、引用與限制；不產生預測、目標價、買賣指令或投資建議。
- 更新 `PRODUCT_EXECUTION_PLAN.md`，記錄 Sprint 29 scope、non-goals、失敗降級、rollback 與 pending independent CTO acceptance。

## 驗證

| 項目 | 命令/結果 |
|---|---|
| targeted | `pytest -q tests/test_macro_snapshot.py tests/test_daily_home.py tests/test_daily_research_brief.py tests/test_dashboard_shell.py`，exit 0 |
| full/quality gate | `cmd /c quality_gate.bat`，exit 0；1283 passed、2 skipped；log：`artifacts/sprint29/quality-gate.log` |
| branch coverage | 82.37%（gate 78.50%） |
| Black/Ruff/mypy/compile | quality gate 全部通過；`src/stock_tool/application/macro_snapshot.py` 等變更檔已檢查 |
| pip check | exit 0，No broken requirements |
| pip-audit | exit 0，No known vulnerabilities；`artifacts/sprint29/pip-audit-final.json`（UTF-8、無 BOM） |
| source archive | missing=0、forbidden=0、content mismatch=0、duplicate=0；`artifacts/sprint29/source-verification-final.json` |
| performance | `artifacts/sprint29/performance-canonical.json`；三次量測，所有門檻通過，EXE readiness max 2.5216s |
| diff/privacy | `git diff --check` 通過；quality gate privacy violations=0 |

## 候選與正式成品雜湊

- stable staging：`release/staging-sprint29/StockTool/StockTool.exe`，7,112,505 bytes，SHA-256 `CC3C863638751F9921D91F9A68BBBA47580C3BF97CB1110B17976ECA82BB5F2E`
- payload：`release/staging-sprint29/StockTool/versions/1.2.2/StockToolPayload.exe`，23,965,918 bytes，SHA-256 `AC1D724C46BD41E0E93181344FCD5F778A9F2532159AC8B7AB5D3867C154FA00`
- source ZIP：`release/staging-sprint29-source.zip`，2,632,230 bytes，SHA-256 `BC78C14FA51EEC6C857B03788D7D009F358140E1434A5FD62011AF718AB0D9A2`
- formal：`release/StockTool/StockTool.exe`，24,145,141 bytes，SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`（未變更）
- exact binding/verifier：`artifacts/sprint29/candidate-hash-binding.json`、`candidate-hash-verifier.json`，四項 size/hash exact match。

## EXE 與瀏覽器證據

- EXE smoke 僅經 `scripts/evidence_launcher.py`，online/offline 均 health ready、harness exit 0、zero real-data diff、cleanup verified、listener 0：`artifacts/sprint29/exe-smoke-summary.json`。
- live browser session：`artifacts/sprint29/browser-session/`。同一候選、同一 session 取得 `home.png`、`macro.png`、DOM、console、launch、guard、cleanup；capture manifest SHA-256 `B3834794ECBC0EDAA8A2851631F60F416FE1759DFD8CFFF39F75FEDC5DC98807`。
- 最終同 session 的簡報產生證據：`artifacts/sprint29/browser-session-final4/`；pre-click 首頁與 post-click `brief.png`、DOM、console 均由 session `sprint29-live-brief4` 擷取，manifest SHA-256 `47414F6E08F35D1BCC7E46FCF0E5E26C8D75C67C2EB60C174431D31444FD02C7`，guard/cleanup/zero-diff 均通過。
- `home.png` 與 `macro.png` 已實際開啟檢查；不是空白畫面或舊檔複製。active console error/warning count=0。
- guard：`status=passed`、`harness_exit_code=0`、`cleanup_verified=true`、candidate process/listener=0、data diff zero。
- Browser 結果：`artifacts/sprint29/browser-result.json` 為 `status=blocked`、`overall_passed=false`。FRED 線上端點在本環境不可用，畫面誠實顯示 partial/unavailable/insufficient_data；未以 cache 或 fixture 冒充 fresh official data。此為唯一瀏覽器硬限制。
- 原生 Chrome 100%/125%/150% 保留 `deferred_to_formal_release`，未以 viewport resize 冒充。

## 真實資料與清理

- `artifacts/sprint29/real-data-before.json`、`real-data-after.json`、`real-data-diff.json`：檔案數 191→191，`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。
- EXE smoke 與 live browser guard 均未修改正式 `%LOCALAPPDATA%\\StockTool`；候選程序與 8501/8502 listener 均已清理。
- 未建立/修改正式排程、未修改 formal EXE、未簽章、未發布、未 commit/tag/push、未開始 Sprint 30。

## 證據衛生與限制

- `artifacts/sprint29/evidence-hash-index.json` 重新遞迴索引本輪全部 raw evidence；missing/extra/mismatch/duplicate=0，UTF-8/no-BOM/JSON parse checks 通過。`browser-session-final2`（home 標籤錯置）及 `browser-session-final3`（與另一候選並行、readiness=0.003）均保留並標為 `superseded_invalid`，未被目前結果引用。
- FRED provider 是本輪新增的官方資料讀取能力，但本次 live 網路不可用，因此「官方線上 fresh 總經內容」仍 BLOCKED，需 CTO 在可用網路環境獨立重跑。
- 未建立 installer、未簽章、未覆蓋 `release/StockTool`；本候選僅供隔離驗證。
