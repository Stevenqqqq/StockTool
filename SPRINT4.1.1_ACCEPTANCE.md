# Sprint 4.1.1 Acceptance

Date: 2026-07-12

## Scope and Verdict

**Accepted.** This is an artifact and visual-evidence correction only. No Python, CSS, provider,
backtest, risk, portfolio, data-storage, or EXE logic was modified. Sprint 5 was not started.

## Source Archive Correction

**Root cause:** `examples/` was omitted from the Sprint 4.1 source archive while the acceptance
document stated that examples were included.

**Fix:** created a new allowlisted archive with `examples/` explicitly included. The archive build
copies individual permitted files, preventing recursive inclusion of bytecode or runtime data.

- Archive: `release/baseline/stocktool-sprint4.1.1-20260712-source.zip`
- SHA-256 sidecar: `release/baseline/stocktool-sprint4.1.1-20260712-source.zip.sha256`
- Size: `1,669,339` bytes
- File entries: `166`
- SHA-256: `064E9602AB1AED54883CEA00008700057BC38F46C1A32206C71DC7AAB54D1050`

Required ZIP entries were present and matched the current workspace byte-for-byte:

| ZIP entry | SHA-256 |
| --- | --- |
| `examples/indicator_usage.py` | `0440DEDA78687271D056A8F21FD2B8124FCAE77BAEDDFEE055056CD3C33115C2` |
| `examples/report_usage.py` | `3FFCAC338E5F4201C9CC8AD62AA9D015A12FE4725AE669CA7C735A461EEE19AF` |
| `examples/strategy_usage.py` | `F8F5EE85D09B31377A53D168D578395DB45CC9457C6791B20D2446F12A93CA48` |

Validation expanded the ZIP to an isolated directory and compared every archived file with its
current workspace counterpart. Content mismatches: `0`.

Forbidden ZIP entries scanned: `0`. The scan excludes `__pycache__`, `.pyc`, `.pyo`, `.coverage`,
pytest/mypy/ruff caches, `release`, `build`, `dist`, `.venv`, runtime cache/log/report paths,
real `.env`, `portfolio.csv`, `watchlist.csv`, and other private runtime data.

## Settings Visual Evidence Correction

The prior Settings capture was replaced with a stable isolated-source-runtime capture:

- Screenshot: `docs/acceptance/sprint4.1/settings-1920x1080.png`
- Capture time: `2026-07-12 12:35:07` local time
- Size: `144,364` bytes

The browser test waited for the Settings heading, all three action-card CTA buttons, all six
visible primary-navigation labels, a 1,200 ms stability period, and a 1920 px root-width check
before capturing. It confirmed:

- 研究首頁、探索、策略、持倉、研究庫、設定 are fully visible.
- The sidebar has no observed text clipping.
- 資料匯入、自動抓資料、Legacy dashboard／診斷模式 action cards are fully rendered.
- No horizontal overflow, loading state, or partial transition state was captured.

No CSS correction was needed.

## Validation

- Complete pytest: `311 passed`.
- Collected tests: `311` across 40 test-file groups.
- Existing EXE was not rebuilt because no product code changed.
- Existing EXE: `release/StockTool/StockTool.exe`
  - Build time: `2026-07-12 07:53:56` local time
  - Size: `23,777,612` bytes
  - SHA-256 unchanged: `2268847420B52A8A0A4451FD64F695274F80E5DFB77EA371C60C853D2C9A6F74`

## User Data and Cleanup

- Real portfolio: 4 rows, SHA-256 unchanged:
  `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
- No local watchlist file existed before or after this artifact-only task.
- Isolated browser runtime, temporary Playwright script, archive staging and extraction folders,
  and test-result folders were removed.
- Ports 8501 and 8502 had no listener after completion.

Sprint 4.1.1 is complete. Sprint 5 was not started.
