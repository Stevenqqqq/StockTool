# Sprint 22 implementation evidence

本文件只記錄 Sprint 22 implementation evidence，未代表 CTO acceptance、release approval 或 Sprint 23 核准。

## Checkpoint evidence

- branch：`main`
- Sprint 21.1 checkpoint commit：`43de40bd626d7ed785f7450fc527820fed7acee5`
- annotated tag：`sprint21.1-accepted-2026-08-02`
- tag object：`62193a13cb94002c56070ece546fc5b10ff19551`
- tag peeled commit：`43de40bd626d7ed785f7450fc527820fed7acee5`
- checkpoint 訊息：`chore: complete accepted sprint 21.1 checkpoint`
- checkpoint evidence：`artifacts/sprint22/checkpoint-before-sprint22.json`
- Sprint 22 沒有 commit；工作樹保留本 Sprint diff。既有未追蹤 `installer/artifacts/` 未納入 checkpoint，也未刪除。
- checkpoint 前已執行 `git diff --check`、project privacy scan 與 source/layout validation，均為 0。

## 修改檔案與產品能力

- `src/stock_tool/application/portfolio_workspace.py`：新增不依賴 Streamlit 的持倉工作區 application service；注入持倉與 ledger 路徑，支援 market-qualified identity 的載入、驗證、增加、更新、移除、重新載入、估值、FX、健康度、風險、壓力測試與 read-only ledger evidence。
- `src/stock_tool/dashboard/pages/portfolio_workspace.py`：新增原生持倉／風險頁；第一屏摘要、資料狀態、持股管理、估值、曝險、健康度、缺口、假設壓力測試與 privacy-safe manifest 下載。
- `src/stock_tool/dashboard/shell.py`：持倉主導航改接原生工作區；只有明確更新動作才呼叫既有 refresh callback，legacy 頁仍保留為次要診斷入口。
- `src/stock_tool/application/__init__.py`：公開新的 workspace service/model。
- `src/stock_tool/quality_gate.py`：納入 Sprint 22 source、targeted tests 與 focused mypy。
- `tests/test_portfolio_workspace.py`：deterministic service、資料缺口、FX、ledger、manifest/stale、stress 與 Streamlit AppTest。
- `tests/test_dashboard_navigation.py`、`tests/test_dashboard_shell.py`：原生導航、注入 service、refresh/error、legacy fallback 與 shell 狀態回歸測試。

核心邊界：相同代號不同市場不碰撞；CUSTOM 必須明確幣別；缺價格／FX 不產生假總市值或權重；ledger 不存在時不自動建立；manifest 不包含 note 原文、私人絕對路徑或 credential；持股、價格、FX、base currency、stress 設定變更會使既有分析過期。

## Automated verification

- targeted：
  `.venv\\Scripts\\python.exe -m pytest tests/test_portfolio_workspace.py tests/test_dashboard_navigation.py tests/test_dashboard_shell.py -q`；通過（新增 workspace/AppTest 與 shell regression）。
- 完整命令：`cmd /c quality_gate.bat`；exit code **0**。
- 完整 pytest：**1023 passed, 2 skipped**（2 warnings，皆為既有 duplicate ZIP test 的預期 warning）。
- branch coverage：**83.19%**（final JSON：`artifacts/sprint22/coverage-final.json`；quality gate configured fail-under 78.50%，亦達 Sprint 22 要求的既有 83.15% 基準）。
- Black：exit 0，32 files unchanged。
- Ruff：exit 0，30 source files。
- focused mypy：exit 0。
- compile：exit 0。
- project privacy scan：`privacy violations: 0`。
- release layout、regression baseline：exit 0。
- `git diff --check`：exit 0。
- `pip check`：exit 0，`No broken requirements found.`
- 官方 `.venv` pip-audit：exit 0，`No known vulnerabilities found`；JSON：`artifacts/sprint22/pip-audit-final.json`。
- performance hard gate：`artifacts/sprint22/performance-result.json`；每項 3 次，indicators/scoring、Excel export、cached research、allocation/risk、EXE health ready 均 passed，allocation peak 亦 passed。

## Candidate build and hashes

候選建置使用 `STOCK_TOOL_STAGING_PARENT=release\\staging-sprint22 cmd /c build_exe.bat`，exit 0；未覆寫 `release/StockTool`。

| artifact | path | size | SHA-256 |
|---|---|---:|---|
| stable EXE | `release/staging-sprint22/StockTool/StockTool.exe` | 7,110,610 | `2B92EA570708FDFF97164D1A9735B8C7CDDAB11AD3833D48C2DC3E2EEB066A86` |
| payload EXE | `release/staging-sprint22/StockTool/versions/1.2.2/StockToolPayload.exe` | 23,683,552 | `89544D3618C9465CFCFB4929ABE4BCE3A4D125C8E3B3C69283AD87708528C9C3` |
| final source ZIP | `artifacts/sprint22/staging-sprint22-source.zip` | 2,475,962 | `4AEDF6147C79FF5054775CADEFACC505A358AAAB039F79BC4E6875C58EDC6C66` |
| formal EXE | `release/StockTool/StockTool.exe` | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

Hash record：`artifacts/sprint22/candidate-hashes.json`。Stable 與 payload `--version` 均輸出 `1.2.2`、exit 0；`artifacts/sprint22/version-smoke.json`。

Source archive 以 `.venv\\Scripts\\python.exe -m stock_tool.release_archive --root . --output artifacts\\sprint22\\staging-sprint22-source.zip` 重建，獨立解壓驗證結果：`missing_required_inputs=0`、`forbidden_entries=0`、`content_mismatches=0`、`duplicate_entries=0`；stable launcher 與 `StableLauncher.spec` 仍為 required build inputs。

## EXE、資料與清理

- EXE smoke 使用候選 staging 與隔離資料；版本、health、process/listener evidence 位於 `artifacts/sprint22/exe-smoke-final.json`，效能細節位於 `artifacts/sprint22/performance-result.json`。
- `%LOCALAPPDATA%\\StockTool` 只讀建立 baseline/after manifest，未作為測試資料根目錄。
- baseline 與 after 均為 **185 files**；`artifacts/sprint22/real-data-compare.json`：`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`。已知三個新增真實檔案未刪除或修改。
- 正式 EXE before/after 維持上述 `4BBE...70CE`。
- 收尾：`StockTool`／`StockToolPayload` process count **0**；8501/8502 listener count **0**。

## Browser best-effort

`artifacts/sprint22/browser-result.json` 保留隔離候選 browser evidence，9 個場景均誠實標記 `BLOCKED`，原因是目前 browser control surface unavailable；沒有以 AppTest、fixture 或假截圖冒充真實瀏覽器證據。這是 best-effort limitation，不阻擋本 Sprint 的 automated implementation evidence，但仍待獨立驗收與必要的瀏覽器人工／工具驗證。

## 未完成與治理狀態

- 未簽章、未發布、未 promotion、未 push、未建立 PR、未覆寫正式 release。
- Sprint 22 仍未建立 commit；僅 Sprint 21.1 checkpoint 已 commit/tag。
- 需要獨立 CTO acceptance；本文件不宣告正式驗收通過。
