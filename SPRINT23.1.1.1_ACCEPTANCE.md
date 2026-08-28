# Sprint 23.1.1.1 acceptance evidence

狀態：BLOCKED — implementation evidence 已完成，但新候選的 100%／125%／150% 真實 browser zoom 尚未取得 authoritative browser UI 證據；不宣稱 CTO acceptance、發布或 Sprint 24。

## 修正內容

- `scripts/measure_performance.py` 已移除 `STOCK_TOOL_EVIDENCE_GUARD` opt-in、所有 direct candidate `subprocess.Popen` fallback、舊的自行 health polling；三次 EXE readiness 無條件呼叫 `scripts.evidence_launcher.run_evidence()`。
- `scripts/evidence_launcher.py` 先檢查原始資料根目錄是否 absolute，再 resolve；要求 `real_user_root` 嚴格等於 canonical `%LOCALAPPDATA%/StockTool`；cleanup 先終止 candidate tree、等待 8501/8502 listener=0，再建立 after manifest，cleanup 後任何資料差異均 fail closed。
- `tests/test_evidence_launcher.py` 新增 relative path、canonical root mismatch、post-cleanup manifest diff、正常 188→188 guarded run、performance 無 direct Popen fallback 等 regression tests。
- 其餘既有產品功能、installer、正式 release 與事件檔案未修改。

## 測試與品質

- targeted：`python -m pytest -q tests/test_evidence_launcher.py` — 17 passed。
- `cmd /c quality_gate.bat` — exit 0；full pytest 1054 passed、2 skipped；branch coverage 83.15%；Black、Ruff、focused mypy、compileall、privacy、release layout、regression 全部通過。完整輸出：`artifacts/sprint23.1.1.1/quality-gate.log`。
- performance：`artifacts/sprint23.1.1.1/performance-result.json` — 五項 hard gate 全部通過，EXE readiness 三次均由 guard 執行，最大約 2.52 秒。
- `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8` 下 `pip check` exit 0；官方 `.venv` pip-audit exit 0，98 dependencies、0 vulnerabilities：`artifacts/sprint23.1.1.1/pip-audit.json`。

## Candidate 與 source archive

- build command：`STOCK_TOOL_STAGING_PARENT=release/staging-sprint23.1.1.1 cmd /c build_exe.bat`；首次 exit 1（Windows Access denied），立即重跑 exit 0；logs：`artifacts/sprint23.1.1/build-sprint23.1.1.1.log`、`artifacts/sprint23.1.1/build-sprint23.1.1.1-rerun.log`。
- staging：`release/staging-sprint23.1.1.1/StockTool`；stable/payload `--version` 均為 1.2.2。
- stable SHA-256：`CB4F48E70F08178D6D6ACB87DC188B00E1A6788DBCD61397A8AC9B6D34E6C61D`。
- payload SHA-256：`C20EDF00EBB8399B9FB73F0EFDAB6252852D04925F7AFD18C554FA8CC9C2DABA`。
- source ZIP：`artifacts/sprint23.1.1.1/staging-sprint23.1.1.1-source.zip`；SHA-256 `C4CD587634A35366628D576BB6497C70599296167056D5BECF9FEA31A642B0A2`。
- `source-archive-verification.json`：missing required inputs=0、forbidden=0、content mismatches=0、duplicates=0。
- `candidate-hashes.json` 綁定上述 stable、payload、source archive 與正式 EXE hash。
- 正式 `release/StockTool/StockTool.exe` SHA-256 維持 `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。

## Guard 與資料保全

- `guard-health/guard-result.json`、`guard-final/guard-result.json`、`guard-browser-zoom/guard-result.json` 均為 passed：before=188、after=188、`added=[]`、`removed=[]`、`changed=[]`、`zero_diff=true`、candidate cleanup verified。
- `real-data-before-188.json` 與 `real-data-after-188.json` 對 188-file baseline 的 `real-data-compare.json` 為零差異。
- 事件檔案仍保留且 SHA-256 完全不變：
  - `backups/legacy-migration-20260803_001635_072959.json` — `7764CE825A2FA9677DB0E0CFB554CF60F74A1D2337C85324A8781D5A6D64888A`
  - `logs/streamlit_20260803_001635.log` — `72B838D46EA9DAF705222E804DF43C0A7274A6A5877A3CA7E436DEB50EB81AA1`
  - `logs/streamlit_20260803_001635_error.log` — `3E0DC93EFF56111A552B7DE3CC1704812DDE08CE0762F4E94C6EB8839133852A`
- 最終 `cleanup-final.json`：StockTool/StockToolPayload process=0，8501/8502 listener=0。

## Browser evidence 與 blocker

- 新候選已由 guard 啟動並完成首頁、設定頁、Legacy 診斷頁的 screenshot、DOM、active console；彙總：`artifacts/sprint23.1.1.1/browser-result.json`。active console error count=0。
- 因 stable/payload SHA-256 已不同於 Sprint 23.1.1，舊 100/125/150 screenshots 沒有沿用。
- Playwright 真實鍵盤 `Ctrl+0`、`Ctrl++`、`Ctrl++` 沒有產生可核對的 browser zoom 變化（metadata 均維持 1280×720、dpr≈1）；外部 Chrome authoritative menu 控制面未能取得。因此 100%／125%／150% zoom evidence 為 BLOCKED，未以 viewport resize 或舊畫面冒充。

## 變更與治理

- 修改：`scripts/evidence_launcher.py`、`scripts/measure_performance.py`、`tests/test_evidence_launcher.py`；新增本 acceptance 文件與 `artifacts/sprint23.1.1.1` 證據。
- 未修改既有 installer、正式 release 或真實使用者資料；未 commit、tag、push、發布或開始 Sprint 24。

### 下一個具體修正動作

以可證明的 OS-level Chrome/Edge zoom 控制取得同一新候選的 100%、125%、150% authoritative menu screenshot，更新 `browser-result.json` 與本文件後再交 CTO 驗收。
