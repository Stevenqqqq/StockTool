# Sprint 31.1 Implementation Evidence

## Status

`BLOCKED — Chrome 原生 100%／125%／150% 縮放等待 CTO 驗證。`

本文件只記錄 Sprint 31.1 implementation evidence，不代表 Sol／CTO acceptance，
也不代表正式發布。自動化 viewport 證據沒有被當成瀏覽器原生 zoom 證據。

## Scope and product result

- 首頁第一屏已由固定同寬區塊改為 workspace header、資料狀態、研究 command
  panel 與緊湊摘要的研究工作台結構。
- 移除首頁與 sidebar 的重複開發術語，保留既有導航、widget key、搜尋、refresh、
  Research handoff、下載與 warning 行為。
- 新增可重用的狀態 badge、section header、state panel、statistic group 與 outcome
  matrix；所有動態文字先經 `html.escape(..., quote=True)`。
- Prediction Lab 不再使用固定五欄；樣本進度、Top／Middle／Bottom 與 5 日／20 日
  outcome 以不同層級和響應式 grid 呈現。warning 保持可見，limitation 可展開。
- `.streamlit/config.toml` 改為單一有效深色 theme，移除不受目前 Streamlit 支援的
  `[theme.light]` 與 `[theme.dark]`。

本輪修改：

- `.streamlit/config.toml`
- `PRODUCT_EXECUTION_PLAN.md`
- `src/stock_tool/dashboard/__init__.py`
- `src/stock_tool/dashboard/components/layout.py`
- `src/stock_tool/dashboard/components/ui_primitives.py`
- `src/stock_tool/dashboard/pages/home.py`
- `src/stock_tool/dashboard/shell.py`
- `src/stock_tool/dashboard/styles.py`
- `tests/test_daily_home.py`
- `tests/test_dashboard_navigation.py`
- `tests/test_ui_primitives.py`
- `SPRINT31.1_IMPLEMENTATION_EVIDENCE.md`

其餘 dirty working tree 內容為既有成果，未 reset、clean、restore、checkout、stash、
commit 或回退。

## Automated verification

| Gate | Command / scope | Result |
|---|---|---|
| RED contract | new UI contract before implementation | expected collection failure; preserved as `artifacts/sprint31.1/red-targeted.xml` |
| Focused GREEN | new primitives and affected Home/navigation | 44 passed |
| Sprint targeted | `test_ui_primitives.py`, `test_daily_home.py`, `test_dashboard_shell.py`, `test_dashboard_navigation.py`, `test_prediction_lab.py`, `test_dashboard.py` | 145 passed |
| Full pytest + branch coverage | `pytest --cov=stock_tool --cov-branch` | 1411 passed, 2 skipped; 82.59% |
| Ruff | `python -m ruff check src tests` | exit 0 |
| Compile | `python -m compileall -q src` | exit 0 |
| Formal focused mypy gate | existing project gate scope | exit 0 |
| Formal Black gate | existing project gate scope | exit 0 |
| Quality wrapper | `python -m stock_tool.quality_gate` | exit 0; all steps completed; internal branch coverage 82.56%; privacy violations 0 |
| Streamlit theme contract | config parse/startup regression | exit 0; no invalid `theme.light.base` / `theme.dark.base` warning |

Durable test evidence：

- `artifacts/sprint31.1/targeted-final.xml`
- `artifacts/sprint31.1/full-results.xml`
- `artifacts/sprint31.1/coverage.json`

Diagnostic only：直接擴張到 repository 全部 `black --check src tests` 仍指出 28 個
既有非 Sprint 31.1 檔案；直接 `mypy src` 仍有 72 個既有檔案的 110 項錯誤（主要為
既有 stub／型別債務）。本輪未跨 application/domain/data 範圍改寫它們；正式 Black
與 focused mypy gate 均為 exit 0。

## Candidate and EXE smoke

| Artifact | Size | SHA-256 |
|---|---:|---|
| Sprint 31.1 stable EXE | 7,111,560 | `32ACF11B24B7456DB14813CD90CA7AD7DC12348D1AA65DEC31B3246273BC81F3` |
| Sprint 31.1 payload EXE | 24,030,205 | `D174E4940F1A56E4562708F0FF3CA16868527A262D277D1B480EC2A9FA070E13` |
| Formal v1.2.2 EXE | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |
| Installed v1.3.0 EXE | 7,112,147 | `7D3E99C2376F31A813CA39A1CC02763018378E80A3BAA100923F88A96F4A0A6F` |

Stable 與 payload `--version` 均為 `1.3.0`。隔離 EXE smoke 位於
`artifacts/sprint31.1/exe-smoke/`：guard passed、harness exit 0、health ready、
cleanup verified、real-data zero diff。

## Browser and responsive evidence

所有候選啟動均透過 `scripts/evidence_launcher.py`，使用全新隔離
`STOCK_TOOL_USER_DATA_DIR`。

- First-use：`artifacts/sprint31.1/browser-first-use/`
  - `sprint31-1-browser-first-use`
  - 首頁 PNG／DOM／active console；console errors/warnings = 0
  - guard passed、harness exit 0、cleanup verified、real-data zero diff
- Populated Prediction Lab：`artifacts/sprint31.1/browser-populated/`
  - `sprint31-1-browser-populated`
  - 同一候選的首頁與 Prediction Lab PNG／DOM／active console
  - 今日樣本 6、Top/Middle/Bottom 各 2，5 日／20 日狀態矩陣可見
  - console errors/warnings = 0；guard passed、harness exit 0、cleanup verified
- Keyboard：`artifacts/sprint31.1/browser-keyboard/`
  - `sprint31-1-browser-keyboard`
  - Tab、Shift+Tab、Space、Enter 均通過；focus-visible 可見
  - Enter 實際觸發主要研究按鈕的安全輸入驗證
  - 操作前後 DOM 與 PNG 均不同；guard passed、harness exit 0、cleanup verified

有效 viewport 量測（不是原生 zoom）：

| Effective viewport | Horizontal overflow | Text/control clipping | Sidebar overlap | Research button |
|---|---|---|---|---|
| 1707×960 | none | none | none | intact |
| 1280×720 | none | none | none | intact |
| 1024×768 | none | none | none | intact |
| 853×768 | none | none | none | intact |

Raw 結果：`artifacts/sprint31.1/browser-populated/responsive-results.json`。
Browser 彙總：`artifacts/sprint31.1/browser-result.json`。

Sprint 31／31.1 等尺寸 before/after：

- `artifacts/sprint31.1/before-after/sprint31-before-1707x960.png`
- `artifacts/sprint31.1/before-after/sprint31.1-after-1707x960.png`
- `artifacts/sprint31.1/before-after/sprint31-vs-sprint31.1.png`
- `artifacts/sprint31.1/before-after/comparison-manifest.json`

新版 raw screenshot 保持 byte-for-byte 不變；對照圖中的新版只為等尺寸視覺比較而
縮放，已明確標示為 comparison projection，不是原生 zoom evidence。

### Native Chrome zoom

- 100%：`PENDING CTO VERIFICATION`
- 125%：`PENDING CTO VERIFICATION`
- 150%：`PENDING CTO VERIFICATION`

目前可用控制面無法可靠證明 Chrome 原生 zoom 與候選 URL 的同一性，因此沒有使用
viewport resize、PageScaleFactor、DeviceScaleFactor 或 Windows 顯示縮放冒充。

## Preservation and cleanup

- `artifacts/sprint31.1/entry-baseline.json`
- `artifacts/sprint31.1/after-baseline.json`
- `artifacts/sprint31.1/integrity-diff.json`

最終比對：

- Formal `release/StockTool`：zero diff。
- Installed v1.3.0 EXE：SHA-256 unchanged。
- `%LOCALAPPDATA%/StockTool`：209 → 209；added/removed/changed 均為空。
- 桌面「股票分析工具」捷徑 bytes、target 與 target hash：unchanged。
- StockTool／StockToolPayload process：0。
- 8501／8502 listener：0。
- 本輪三個 browser runtime root、EXE smoke runtime root 與 source-development
  runtime root：已精確清理。

## Remaining limitation

唯一 Sprint 狀態 blocker 是原生 Chrome 100%／125%／150% zoom 證據仍等待 CTO
驗證；其餘本輪產品、測試、候選、viewport、鍵盤、privacy 與資料保全 evidence 已
完成。未建立 installer、未修改正式或已安裝 EXE、未發布、未 commit，也未開始
Sprint 32。
