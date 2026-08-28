# Sprint 26.1.1.1 Implementation Evidence

狀態：implementation evidence complete，等待獨立驗收；不代表 CTO acceptance。

## Browser timeout 修正

逾時根因是外層 `evidence_launcher.py --timeout-seconds` 與 harness 的
`--duration-seconds` 相等，候選清理仍在進行時外層先終止 harness。修正流程為
使用明確較長 timeout（本次 8 秒 duration／30 秒 timeout），未修改產品或正式
候選。最終 online guard：
`artifacts/sprint26.1.1.1/browser/online/guard-result.json`，status=passed、
harness_exit_code=0、cleanup verified=true、candidate_processes_remaining=[]、
listeners_remaining=0。

## Browser / EXE evidence

- online：首頁與 significant-change brief 均保存 PNG、DOM、active console、transport、launch、cleanup、guard；active console error=0。
- offline：`browser/offline/launch.json` mode=offline，guard passed。
- partial：`browser/partial/launch.json` mode=partial，guard passed。
- `artifacts/sprint26.1.1.1/browser-result.json` 已綁定所有候選 hashes，`overall_passed=true`。
- 原生 100%／125%／150% zoom 維持 `deferred_to_formal_release`，未使用 viewport resize 冒充。

## History / data protection

- `browser-history-index.json` 遞迴掃描 46 筆 guard，保留 8 筆歷史 failed guards；失敗路徑、原因與 cleanup 均依實際檔案記錄，未刪除或隱藏。
- `real-data-before.json`、`real-data-after.json`、`real-data-diff.json`：191→191，added=[]、removed=[]、changed=[]、zero_diff=true。
- formal EXE 未變：`4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`。

## Quality / artifacts

- targeted：daily research brief/home 31 passed。
- full quality gate：1128 passed、2 skipped；branch coverage 83.14%；exit 0，Black/Ruff/mypy/compile/privacy/release layout/regression baseline 全通過。
- pip check exit 0；官方 pip-audit exit 0、0 vulnerabilities，UTF-8 JSON 可解析。
- performance gate passed：`artifacts/sprint26.1.1.1/performance.json`。
- source ZIP：`artifacts/sprint26.1.1.1/sprint26.1.1.1-source.zip` — `23A21E1F8D31180E8B2747D966B599D59132B80A2A91407C0A6D1E83E353E834`；獨立驗證 missing/forbidden/content mismatch/duplicate 均為 0。
- stable：`DB2B688EE9F1FE4F01C810A3FCD4E27DF7F7F8BF5BA793491A175865311E3EDC`。
- payload：`7EA271B5BD893976FE6C67A9D5939024E0469263BD6EEF5D5AD7A0776226BBC7`。
- 本輪 JSON/log 全以 UTF-8 產生；`pip-check.log` 無 UTF-16 BOM。

## Governance / limitations

未修改正式 EXE、installer 或真實使用者資料；未發布、簽章、commit、tag、push，未開始 Sprint 26.2。原生 Chrome zoom 仍 deferred，交由正式驗收補證。
