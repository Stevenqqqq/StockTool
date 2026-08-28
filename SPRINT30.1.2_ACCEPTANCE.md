# Sprint 30.1.2 implementation evidence

狀態：`CTO acceptance：通過`（2026-08-20）。

本文件區分 implementation evidence 與已記錄的 CTO acceptance；不代表正式發布或
release approval。

## CTO 後續人工 Windows 驗證（2026-08-20）

產品擁有者／CTO 以可見 Windows Chrome 原生介面完成最終人工驗證：

- Chrome 原生縮放 100%：通過。
- Chrome 原生縮放 125%：通過。
- Chrome 原生縮放 150%：通過。

這三項是產品擁有者／CTO 的人工 Windows 驗證結論，不是實作者自動化控制、
AppTest、viewport resize、CDP 或合成截圖證據。先前本文件所記錄的自動控制
無法取得 Chrome 原生選單百分比，保留作為歷史紀錄，並由本節人工決定取代其
驗收阻擋地位；原始自動化失敗證據未刪除或改寫。

## 範圍與工作樹

- 保留 dirty worktree；沒有 reset、clean、checkout、commit、tag、push 或正式發布。
- 移除錯誤 staged deletions 與 Sprint 4.1 PNG 的 index staging；未刪除任何工作樹檔案。
- 未 staged 的既有使用者變更仍保留。`artifacts_sprint25_1_1_quality.log`、`scratch/` 與其他 artifacts 未加入 index。
- 本輪 staged 內容只包含：
  - `scripts/verify_evidence_bundle.py`
  - `tests/test_evidence_bundle_verifier.py`
- `git diff --check` 與 `git diff --cached --check`：通過。
- 實際 staged patch：`artifacts/sprint30.1.2/checkpoint/staged-diff.patch`，41,420 bytes，SHA-256 `64E2F3629ACB624D4A2B375B602A5DCBD3B794DF7A2B0DDE4C605C2F2E1C31B1`；不是空檔。
- status 快照：`artifacts/sprint30.1.2/checkpoint/status-before-staging.txt`、`status-after-staging.txt`。

## Evidence verifier 與頁面證據

- 新增 strict page contract：home、changes、brief、settings 必須各自有 scene-bound DOM、console、PNG 與頁面語意 assertion；重複 physical path、alias、raw bytes、尺寸不一致均 fail closed。
- 新增 launch binding：candidate absolute path／SHA-256、PID/process tree、health endpoint、listener、isolated data root、session 與 launch→cleanup 時間窗。
- canonical verifier：
  - 命令：`python scripts/verify_evidence_bundle.py artifacts/sprint30.1.2/evidence-bundle --workspace-root . --stable-candidate release/staging-sprint30-correction-r3/StockTool/StockTool.exe --payload-candidate release/staging-sprint30-correction-r3/StockTool/versions/1.2.2/StockToolPayload.exe --source-zip release/staging-sprint30.1.2-source.zip --formal-exe release/StockTool/StockTool.exe`
  - 結果：`passed=true`、`errors=[]`、checked captures 17。
- `capture-session-manifest.json` 7612 bytes，SHA-256 `876A25AF6FD1F3116EA5502ACB2C76435973DF8661001C73C4EE4818C5A6C185`；`evidence-hash-index.json` 4392 bytes，SHA-256 `B8B31978DA30F0FA3AAEF00921F2EDB807548E86AFEA35BC9643E713F5C3A53B`；verifier raw output：`artifacts/sprint30.1.2/canonical-verifier-result.json`。
- 最終同 session：`s30-1-2-final3-20260820`；隔離 root id `stocktool-evidence-9f8d79b685a54d2da00a5e4e9867a477`。
- 原始 live capture 保留於 `artifacts/sprint30.1.2/final-session-3/`；四張畫面已親自開啟檢查。最終 verifier bundle 為 `artifacts/sprint30.1.2/evidence-bundle/`。
- 連線瀏覽器 API 的原始 session screenshot bytes 以 JPEG 編碼回傳並原樣保留；為符合本輪 PNG 契約，final bundle 由同一 live capture 直接編碼為 PNG，未修改原始 session 檔。
- 四張畫面皆為 1862×901，active console error count=0：
  - `home.png`（331,018 bytes）SHA-256 `50D91B726C22A028BBB7E882D06DF840025CFCC1B1DF766DBA89C9856CDC1631`
  - `changes.png`（416,985 bytes）SHA-256 `2296E00E3FF6B89855A0266F08083E6A3E717FFE60081F96816DD66CEF3D6D09`
  - `brief.png`（375,683 bytes）SHA-256 `EF1FBC02DA5B27FD6471E1E07AA894E78C6EBB43B791E0CED1B68AD7A8DCAD66`
  - `settings.png`（332,390 bytes）SHA-256 `13374E1031E50CADAFA04CD6FEF2659A5C7E96313622A1830E8D0343B6154E65`

> 上述四個 PNG hash 以 `evidence-hash-index.json` 為權威；交付前 verifier 會再次讀取實體 bytes。頁面專屬語意與實際 hash 請以 bundle 的 index 為準。

- settings 畫面實際顯示「目前狀態：未安裝」與「週一至週五 18:30（Asia/Taipei）」；沒有顯示「錯誤」。
- keyboard verifier 的 before/after DOM/value invariant 與 adversarial tests 保留；本輪新 live session 未重做鍵盤情境。
- `artifacts/sprint30.1.2/native-zoom-status.json` 記錄以可見頁面 CUA 送出 Ctrl+0／Ctrl++ 的嘗試；未取得 Chrome 原生選單的 authoritative percentage，devicePixelRatio/viewport 未改變，沒有使用 CDP、PageScaleFactor、DeviceScaleFactor、viewport resize 或 device emulation。原生 zoom 因此維持 blocker/deferred，未冒充通過。

## Candidate、source ZIP 與 formal baseline

| artifact | path | size | SHA-256 |
|---|---|---:|---|
| stable | `release/staging-sprint30-correction-r3/StockTool/StockTool.exe` | 7,108,703 | `A979B12F9F70948EBF96985D8B99A96E363D3FF76F18D9CC1078479924614719` |
| payload | `release/staging-sprint30-correction-r3/StockTool/versions/1.2.2/StockToolPayload.exe` | 24,019,506 | `CD9FF41F65BBCA74D517D36C7D9A9C0D499307467C89E03D572AF89E24A12FB3` |
| source ZIP | `release/staging-sprint30.1.2-source.zip` | 2,673,935 | `1BFF78E876C225E76E42C40FEDDADC1898AB21A4E7EC481A6C0F73D44094227B` |
| formal EXE | `release/StockTool/StockTool.exe` | 24,145,141 | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

stable/payload product bytes were unchanged; therefore no new PyInstaller candidate was created. The source ZIP was rebuilt after verifier/test changes and independently expanded/verified with missing, forbidden, content mismatch and duplicate counts all zero. Stable and payload `--version` each returned `1.2.2` with exit 0. Formal EXE hash is unchanged.

## Lifecycle logs

Raw install/repair/upgrade/uninstall logs were copied byte-for-byte from the existing accepted lifecycle replay into `artifacts/sprint30.1.2/installer-lifecycle/logs/`; they are indexed by `installer-log-index.json` and `installer-log-index.sha256`. No installer was executed or modified in this correction, and no formal task, registry, Start Menu or install directory was touched.

## Automated verification

- Verifier targeted: `35 passed`.
- Additional verifier/archive/CLI targeted: `46 passed, 1 warning`.
- Security/release archive targeted: `10 passed, 1 warning`.
- `cmd /c quality_gate.bat`: exit 0 / PASSED; full pytest `1372 passed, 2 skipped, 2 warnings`; total branch coverage `82.49%` (gate 78.50%); Black, Ruff, focused mypy, compile, privacy, release layout and regression baseline passed.
- `pip check`: exit 0, no broken requirements.
- official `.venv` `pip-audit --format=json`: exit 0, no known vulnerabilities; JSON is UTF-8 without BOM (`artifacts/sprint30.1.2/quality/pip-audit.json`).
- performance hard gate: `artifacts/sprint30.1.2/quality/performance-canonical-bound.json` (raw measurement retained as `performance-canonical.json`), 3 runs per measurement, all passed; `exe_health_ready` 2.5278413 / 2.5361528 / 2.5119531 seconds, max 2.5361528 ≤ 5.0 seconds; bound to the stable/payload/source hashes above.
- source archive verification: zero missing, forbidden, content mismatch and duplicate entries.

## Data and cleanup

- Live guard result: `artifacts/sprint30.1.2/final-session-3/guard-result.json`; harness exit 0, status passed, cleanup verified, candidate process residue 0, listeners 0.
- `real-data-before.json`, `real-data-after.json`, `real-data-current.json`, `real-data-diff.json`: 191→191, added/removed/changed all empty, zero diff true.
- No formal `StockTool` EXE, formal installer, production task, user portfolio/watchlist/database or settings was changed.

## Remaining limitation

實作者自動化控制仍未能擷取 Chrome 原生選單百分比；上述人工 Windows 驗證已由
產品擁有者／CTO 於 2026-08-20 完成，故不再是 Sprint 30.1.2 的驗收阻擋。
自動化歷史證據仍保留，沒有以 viewport 或合成縮放冒充人工結論。

本輪沒有重新執行會觸碰 registry／安裝目錄的 installer lifecycle；只封存既有 accepted replay 的 install、repair、upgrade、uninstall 原始 logs 並做 byte/hash 驗證。因此 installer lifecycle 不是本輪 fresh replay 證據。
