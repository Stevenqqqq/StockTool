# Sprint 23.1 implementation evidence
狀態：**BLOCKED — pending independent CTO acceptance**

本文件只記錄 Sprint 23.1 implementation evidence，不代表 CTO acceptance、正式發布或 rollout。

## 修正內容

- `PRODUCT_EXECUTION_PLAN.md`：修復 Sprint 1–19 dependency diagram closing fence，將 Sprint 20–23 extension 移出 fenced code block；Sprint 20–22 標為本機產品化／獨立驗證完成，Sprint 23 保持 implementation evidence pending acceptance。
- `tests/test_roadmap_structure.py`：新增 Markdown fence 與 extension 結構回歸測試。
- `src/stock_tool/application/settings_workspace.py`：optional provider credential 只記錄 presence；未設定不降低本機資料健康度、不列入 gaps/warnings。
- `tests/test_settings_workspace.py`：空 environment healthy fixture、credential privacy、SQLite close/exception/移動回歸測試。
- SQLite read-only inspection 使用明確 close，保留 `mode=ro` 且不存在資料庫不建立檔案。

## 自動化驗證

| 檢查 | 結果 |
|---|---|
| Sprint 23.1 targeted tests | 82 passed |
| quality_gate.bat | exit 0 |
| full pytest | 1037 passed, 2 skipped |
| branch coverage | 83.15%（門檻 83.14%） |
| Black | passed |
| Ruff | passed |
| focused mypy | passed |
| compileall | passed |
| project privacy scan | 0 violations |
| release layout / staging validation | passed |
| git diff --check | exit 0 |
| pip check | no broken requirements |
| official pip-audit | exit 0; no known vulnerabilities |
| performance hard gate | passed；五項固定資料測量皆於原門檻內 |

Performance evidence: `artifacts/sprint23.1/performance-result.json`。
Quality log: `artifacts/sprint23.1/quality-gate.log`。

## Candidate / source evidence

- Staging: `release/staging-sprint23.1/StockTool`
- Stable EXE SHA-256: `42EA401C72E8AD1297ADB77EC379A65A34D425DC4CC84C6630E0EE4DA42CFFB6`
- Payload EXE SHA-256: `EBC01CE626E7E54A037DE70E98FBE7BCA7D22E8757906C5577C9AD9B76A68BF9`
- Source ZIP: `artifacts/sprint23.1/staging-sprint23.1-source.zip`
- Source ZIP SHA-256: `051CDABFDE3511250C0AFD909DEF567ACA72294E3C92F0788DA4B545BEFAA0D8`
- Stable/payload `--version`: `1.2.2`
- Final hash assertion: `artifacts/sprint23.1/final-hash-assertion.json` (`binding_ok: true`)
- Source archive verification: `artifacts/sprint23.1/source-archive-verification.json` (missing/forbidden/content mismatch/duplicate all 0)
- Formal EXE SHA-256 remained `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.

## Browser evidence

Evidence root: `artifacts/sprint23.1/browser/`.

- Healthy local fixture with no optional token: passed; UI displayed `整體資料健康度：健康` and `Provider／外部 AI：未設定；需要時由使用者明確啟用。`.
- Partial fixture: passed; missing Portfolio was shown as `部分可用` with an explicit gap.
- Corrupt fixture: passed; invalid settings were shown as `錯誤` with a recoverable diagnostic.
- Active console: `console-active.json`, error count 0.
- Separate teardown evidence: `console-teardown.json`, no StockTool process or 8501/8502 listener remained.
- DOM and screenshots for the three scenarios are retained beside `browser-result.json`.

Hard browser blocker: Chrome extension control was unavailable. The in-app browser accepted CUA Ctrl+0/Ctrl+plus keypresses but `innerWidth`, `devicePixelRatio`, and `scrollWidth` remained unchanged for 100/125/150 attempts. Therefore real 125%/150% zoom cannot be proven; `browser-result.json` is explicitly `BLOCKED` and does not substitute viewport resizing or AppTest evidence.

## Real-data preservation

Before/after manifests: `artifacts/sprint23.1/real-data-before.json`, `real-data-after.json`, `real-data-compare.json`.

The compare is **not zero-diff**. A non-isolated candidate launch created these additional real-user files:

- `backups/legacy-migration-20260803_001635_072959.json`
- `logs/streamlit_20260803_001635.log`
- `logs/streamlit_20260803_001635_error.log`

They were not deleted, modified, or moved. This is a hard governance blocker and must be independently reviewed; no claim of real-data preservation is made.

## Governance

- Sprint 22 checkpoint commit/tag were not modified or rebuilt.
- No commit, tag, push, signing, publication, promotion, formal release overwrite, or Sprint 24 work was performed.
- Candidate processes and 8501/8502 listeners were cleaned up; teardown evidence is retained.
