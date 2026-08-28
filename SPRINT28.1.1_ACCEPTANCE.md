# Sprint 28.1.1 implementation evidence

本文件只記錄實作與可重播證據，交由獨立 CTO 驗收；不代表正式發布或 Sprint 29 核准。

## 修正範圍

- `scripts/verify_evidence_bundle.py` 現在對 captures、supporting files 與 bundle 實體檔案採精確 allowlist；evidence index 不能授權額外檔案。
- capture descriptor 必須使用 canonical bundle path，並以解析後、大小寫不敏感的 physical path 做一對一 alias 檢查。
- stable、payload、source ZIP、formal 的角色路徑由 verifier 外部合約決定；bundle 自稱的 path 不得選擇任意 workspace 檔案。CLI 可傳入四個完整角色路徑，但仍必須與核准的 Sprint 28.1.1 mapping 完全相等。
- `tests/test_evidence_bundle_verifier.py` 新增三個 adversarial cases，並保留既有 hash、session、timestamp、BOM/CRLF、real-data、task、candidate mutation 測試。

## Targeted／完整驗證

- 新增三個 adversarial cases：`3 passed, 13 deselected`。
- verifier 與 Daily Research 相關 targeted suite：`166 passed`。
- `quality_gate.bat`：exit code 0，`1273 passed, 2 skipped`，branch coverage `82.62%`，Black、Ruff、mypy、compile、privacy、release layout、regression 全部通過。
- `pip check`：`No broken requirements found.`
- `.venv` 官方 `pip-audit --format json`：exit code 0；UTF-8、無 BOM、JSON 可解析，沒有已知漏洞；本機專案套件因不在 PyPI 而由 pip-audit 記為 skip_reason，未使用 ignore/skip 白名單。Artifact 為 [pip-audit.json](artifacts/sprint28.1.1/pip-audit.json)。
- `git diff --check`：通過。

## Candidate／source hash binding

| role | path | size | SHA-256 |
| --- | --- | ---: | --- |
| stable | `release/staging-sprint28.1.1/StockTool/StockTool.exe` | 7,111,371 | `06A87045FAC6F2E64E5752280F38A4BA4A8E2BA070162996876F851D39868AEC` |
| payload | `release/staging-sprint28.1.1/StockTool/versions/1.2.2/StockToolPayload.exe` | 23,940,439 | `483F13E6F2CB235CB6710ADB8800E2B4DAD8D6EE1ED615F887DCF373986B6D00` |
| source ZIP | `release/staging-sprint28.1.1-source.zip` | 2,617,626 | `64FA7FD5C3E834564DD46ED44D872A2AF0CB36D3A829687753F693A9F0785703` |
| formal | `release/StockTool/StockTool.exe` | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

`artifacts/sprint28.1.1/candidate-hash-verifier.json` records exact size/hash equality for all four roles. Source archive verification returned `missing_required_inputs=0`, `forbidden_entries=0`, `content_mismatches=0`, `duplicate_entries=0`; its sidecar matches the hash above.

## Fresh browser／EXE evidence

- Final same-session bundle: [artifacts/sprint28.1.1/evidence-bundle-final](artifacts/sprint28.1.1/evidence-bundle-final)
- Session: `sprint28.1.1-final-6f936f46`.
- `scripts/evidence_launcher.py` guard：`status=passed`、`harness_exit_code=0`、`cleanup_verified=true`、candidate processes `[]`、listeners `0`、real-data diff zero。
- Strict verifier command used the four explicit trusted candidate paths and returned `passed=true` with no errors.
- `home.png` is a non-empty StockTool home screen; `brief.png` is a non-empty rendered每日證據鏈研究簡報 screen; settings DOM contains `目前狀態：未安裝`; all active console files report `errors=[]`.
- Raw capture files were not rewritten after capture. `capture-session-manifest.json`, `browser-result.json`, candidate binding, index and sidecar were rebuilt from on-disk bytes after the final source ZIP rebuild. `browser-result` is bound to the final source hash above.
- Isolated EXE smoke via `evidence_launcher.py` passed for online, offline and partial modes at `artifacts/sprint28.1.1/exe-smoke-online-20260812b`, `exe-smoke-offline-20260812`, and `exe-smoke-partial-20260812`.
- Historical browser evidence remains visible in [browser-evidence-history-index.json](artifacts/sprint28.1.1/browser-evidence-history-index.json); earlier failed/superseded bundles were not deleted or rewritten.

## Privacy／cleanup／限制

- Real `%LOCALAPPDATA%\\StockTool` was read-only snapshotted: before/after/current `191` files, `added=[]`, `removed=[]`, `changed=[]`, `zero_diff=true`.
- Formal EXE hash is unchanged. No production task, installer, registry, Start Menu, commit, tag, push or release operation was performed.
- Final cleanup checks: StockTool and StockToolPayload processes `0`; ports 8501/8502 listeners `0`; production task absent.
- The first `build_exe.bat` invocation returned `Access is denied` while moving the completed PyInstaller payload directory. PyInstaller completed and the staged payload was then moved and validated explicitly; this transient batch issue is retained as a known build-process limitation, not hidden as a successful batch exit.
- Native Chrome 100%/125%/150% zoom remains deferred to formal release verification; no viewport resize is claimed as proof.
