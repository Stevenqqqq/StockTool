# Sprint 32.1 implementation evidence

## 狀態

Implementation evidence only; independent CTO/Sol acceptance is pending. 本輪未宣稱正式發布。

## 範圍與修正

- 每個有效 run 對 TWSE/TPEX 官方市場資料只呼叫一次 refresh。
- 同一 MarketRefreshResult／snapshot fingerprint 傳入 brief、change、Prediction Lab、Inbox 與 notification。
- 六階段 manifest 使用核心實際 stage result，不由 overall status 推算。
- 只有 fresh、ready、日期一致的本次市場 snapshot 才允許 Prediction Lab registration。
- 保留 partial、unavailable、skipped 與通知失敗的真實狀態；不覆寫上一份成功成果。

## Fresh verification

- Checkpoint/build method: 從隔離的 source snapshot 建置 `release/staging-sprint32.1-final`；沒有把 dirty worktree 宣稱為 clean checkout，也沒有提交或發布。
- Targeted command: `.venv\\Scripts\\python.exe -m pytest tests/test_daily_research_runner.py tests/test_daily_research_scheduler.py -q`；結果通過。
- Full command: `.venv\\Scripts\\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing`；結果 1418 passed, 2 skipped。
- Quality command: `.venv\\Scripts\\python.exe -m stock_tool.quality_gate`；exit 0。
- Dependency commands: `.venv\\Scripts\\python.exe -m pip check` 與 UTF-8 `pip_audit --format json`；均 exit 0。
- Performance command: `scripts/measure_performance.py --stable-entry release/staging-sprint32.1-final/StockTool/StockTool.exe`；三次 cold run 全部納入。
- Hash command: `scripts/verify_artifact_hash_index.py artifacts/sprint32.1/artifact-hash-index.json`；entry_count=237、missing/extra/mismatch=0。
- Cleanup command: `git diff --check`；正式 task query 回傳 not found；StockTool/StockToolPayload=0、8501/8502 listeners=0。
- Full pytest: 1418 passed, 2 skipped.
- Coverage: 82.54%（branch）。
- Quality gate: exit 0 / PASSED.
- pip check: exit 0.
- pip-audit: exit 0, no known vulnerabilities; UTF-8 artifact `artifacts/sprint32.1/pip-audit-final.json`.
- Performance: `performance-final-candidate.json`, three cold health-ready runs, max 2.5232672 seconds <= 5.0.
- Stable/payload version: 1.3.0; formal release hash unchanged.

## Browser / EXE evidence

- Final candidate: `release/staging-sprint32.1-final/StockTool/StockTool.exe`.
- Same-session partial browser evidence: `artifacts/sprint32.1/final-evidence/browser-partial/`, guard passed, harness exit 0, active console errors 0, cleanup verified.
- Same-session no-target browser evidence: `artifacts/sprint32.1/final-evidence/browser-no-target/`, guard passed, harness exit 0, active console errors 0, cleanup verified.
- Final online headless attempt returned partial=10, so success=0 is explicitly blocked; it is not represented as success.
- Native Chrome 100%/125%/150% remains deferred_to_formal_release.

## Data protection

Real-user-data manifests are `real-data-before-final.json`, `real-data-after-final.json`, `real-data-current-final.json`, `real-data-diff-final.json`; final diff is zero. Formal and installed EXE were read-only checked and unchanged. No formal task was modified.

## Candidate hashes

See `candidate-hash-binding.json`; exact size and SHA-256 are hash-bound. Source archive verification reports zero missing, forbidden, content mismatch and duplicate entries.

- stable 1.3.0: `1BD230310CC3865534ADD4714D11C6D6A2874D3C8176FFAB3BA2F1473A99EF25`（7,111,653 bytes）。
- payload 1.3.0: `E2C9257DA8A2B6B2842DE83C192EB2B63871679CDA8050A44A4D6FCB4AF15C6B`（24,047,165 bytes）。
- source ZIP: `9E06A59FC379E27C35734DE8D1C17CE4D38D9063A039E68E9078A0E1462D4449`（2,723,748 bytes）。
- formal v1.2.2: `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`（24,145,141 bytes），未變更。
- installed v1.3.0：`7D3E99C2376F31A813CA39A1CC02763018378E80A3BAA100923F88A96F4A0A6F`（7,112,147 bytes），未變更。

## Known limitation

External official TWSE/TPEX refresh was partial/date-inconsistent in this run, so a truthful full success journey with Prediction Lab sample creation could not be produced. The implementation and all deterministic/partial/no-target evidence remain available for independent verification.
