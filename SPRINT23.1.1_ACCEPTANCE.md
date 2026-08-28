# Sprint 23.1.1 implementation evidence

狀態：implementation evidence ready for independent CTO review；不代表 CTO acceptance、發布或 Sprint 24 核准。

## 事件與資料基線

- `artifacts/sprint23.1.1/incident-record.json` 記錄了 Sprint 23.1 期間未套用隔離 `STOCK_TOOL_USER_DATA_DIR` 的事件；185→188 是真實非零差異，`removed=[]`、`changed=[]`，沒有資料遺失或正式 EXE 覆寫。
- 產品負責人保留以下三個檔案，實作者未刪除、修改或移動：
  - `%LOCALAPPDATA%/StockTool/backups/legacy-migration-20260803_001635_072959.json` — `7764CE825A2FA9677DB0E0CFB554CF60F74A1D2337C85324A8781D5A6D64888A`
  - `%LOCALAPPDATA%/StockTool/logs/streamlit_20260803_001635.log` — `72B838D46EA9DAF705222E804DF43C0A7274A6A5877A3CA7E436DEB50EB81AA1`
  - `%LOCALAPPDATA%/StockTool/logs/streamlit_20260803_001635_error.log` — `3E0DC93EFF56111A552B7DE3CC1704812DDE08CE0762F4E94C6EB8839133852A`
- 事件後只讀基線為 188 檔：`artifacts/sprint23.1.1/real-data-baseline-188.json`。

## Isolation guard

- `scripts/evidence_launcher.py` 會拒絕空白、相對、既存、workspace/release/artifacts、正式 `%LOCALAPPDATA%/StockTool` 及其子目錄，並只建立全新 `%TEMP%` root。
- 啟動只透過既有 `scripts/browser_transport_harness.py`；候選 process tree、8501/8502 listener、before/after manifest 與 timeout cleanup 均由 guard 驗證。
- `tests/test_evidence_launcher.py` targeted：12 passed，包含 path rejection、fresh temp、exception/timeout cleanup、manifest added-file fail-closed。
- 通過 run：`artifacts/sprint23.1.1/guard-browser-final/guard-result.json`；before=188、after=188、`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`、cleanup verified。
- 性能三次 EXE health 也只透過 guard；結果：`artifacts/sprint23.1.1/performance-result-final.json`。

## Candidate 與 source archive

- staging：`release/staging-sprint23.1.1/StockTool`。
- stable EXE `--version`：1.2.2，exit 0；SHA-256 `CDC8B2B6146EFC9A8810180C185CA52827BB69D828F3058C3576EB4275AA2CDE`。
- payload `--version`：1.2.2，exit 0；SHA-256 `9DA62A62BFA0F946D6C3A13DB9E30C5C5800BFBF8E1B37BD6D974AD17B64BAE4`。
- source archive：`artifacts/sprint23.1.1/staging-sprint23.1.1-source-final.zip`；SHA-256 `C13CFAA79398AC5ADCE76F051BCE12C2FF08F07B1EF0441EF8EB265FBA3FB44C`。
- `source-archive-verification-final.json`：missing required inputs=0、forbidden=0、content mismatches=0、duplicates=0；archive 內含 evidence launcher 與 browser harness。
- `artifacts/sprint23.1.1/candidate-hashes.json` 綁定上述 final hashes。
- 正式 `release/StockTool/StockTool.exe` 未變，SHA-256 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。

## Quality and safety

`cmd /c quality_gate.bat` exit 0（`artifacts/sprint23.1.1/quality-gate-final.log`）：

- 1049 passed、2 skipped；branch coverage 83.15%（門檻 78.5%）。
- Black、Ruff、focused mypy、compileall、project privacy、release layout、regression baseline 全部通過。
- `pip check` exit 0；官方 `.venv` `pip-audit` exit 0，JSON `artifacts/sprint23.1.1/pip-audit-final.json`，已知漏洞 0。
- performance hard gate：五項均通過；`artifacts/sprint23.1.1/performance-result-final.json`。
- EXE health：`artifacts/sprint23.1.1/health-smoke-final.json`，guard health ready=true。

## Browser evidence

- Chrome extension 不可用；改用隔離候選與外部 Chrome 的 OS-level zoom menu 控制，沒有 viewport resize 或系統縮放。
- authoritative screenshots：
  - 100%：`artifacts/sprint23.1.1/chrome-zoom-100.png` — `1D421C9AB03F8A53B3FD8F905285CE668624D2ABB53033EFAA27C36A1645CB91`
  - 125%：`artifacts/sprint23.1.1/chrome-zoom-125-authoritative.png` — `8F004C3AAEF337398E7B6F807B8FEE7E8296ED8AED39DF0D008F277A789BCACE`
  - 150%：`artifacts/sprint23.1.1/chrome-zoom-150-authoritative.png` — `FF7EBCC3A638A60AEF55641FB32B02FE71D6FF3DDBEA277917B7332892B7B577`
- 設定頁由 CUA 導航；點擊「下載隱私安全診斷 manifest」後再點擊「開啟診斷模式」，成功進入 Legacy 診斷頁。該次候選由 guard 啟動（`guard-browser-controls3/launch.json`）；證據：`artifacts/sprint23.1.1/browser/settings-controls-legacy.png`、`settings-controls-legacy-dom.txt`、`settings-controls-console.json`（active console error count=0）。
- 彙總：`artifacts/sprint23.1.1/browser-result.json`。

## 修改檔案

- `scripts/evidence_launcher.py`
- `scripts/__init__.py`
- `scripts/browser_transport_harness.py`
- `scripts/measure_performance.py`
- `scripts/sprint20_evidence.py`
- `src/stock_tool/quality_gate.py`
- `tests/test_evidence_launcher.py`
- `artifacts/sprint23.1.1/incident-record.json` 及本文件與 machine-readable evidence。

## 收尾

- 最終 `artifacts/sprint23.1.1/cleanup-final.json`：StockTool/StockToolPayload process=0，8501/8502 listener=0。
- 最終 after manifest `artifacts/sprint23.1.1/real-data-after-final.json` 與 188-file baseline 的比對 `artifacts/sprint23.1.1/real-data-compare-final2.json` 為零差異；三個事件檔案仍在且雜湊不變。
- 未修改 installer、正式 release、登錄、system proxy/firewall；未 commit、tag、push、發布或開始 Sprint 24。
