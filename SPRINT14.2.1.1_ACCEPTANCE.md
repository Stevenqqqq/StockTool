# Sprint 14.2.1.1 Acceptance

## Status

Implementation complete and ready for independent CTO re-review. This document records the final merge cleanup only. Formal release promotion was not performed, and Sprint 15 was not started.

## Scope And Change

The only source change in this cleanup was:

- `src/stock_tool/dashboard/shell.py`: removed the unreachable legacy Daily Refresh rendering block after the unconditional `return` in `_handle_home_action()`.

The reachable refresh path, session-state cleanup, rerun behavior, and `_render_daily_refresh_result()` were preserved. No data contracts, providers, backtest, scoring, portfolio, risk, or formal-release files were changed.

## Verification

Targeted command:

```text
.venv\Scripts\python.exe -m pytest tests/test_dashboard_navigation.py tests/test_dashboard_shell.py tests/test_runtime_paths.py tests/test_daily_home.py tests/test_dashboard.py tests/test_price_identity_persistence.py tests/test_sprint51_research_integrity.py tests/test_sprint91_evidence_safety.py -o addopts=''
```

Result: **92 passed**.

Full command:

```text
.venv\Scripts\python.exe -m pytest --cov=src/stock_tool --cov-branch --cov-report=term
```

Result: **641 passed**; branch coverage **81.77%**; configured gate **78.5%**, passed.

Focused quality commands:

```text
.venv\Scripts\python.exe -m black --check src/stock_tool/dashboard/shell.py
.venv\Scripts\python.exe -m ruff check src/stock_tool/dashboard/shell.py
.venv\Scripts\python.exe -m mypy --ignore-missing-imports src/stock_tool/dashboard/shell.py
```

All passed. `py_compile` for `shell.py` also passed.

## Staging EXE

- Path: `release\staging\StockTool\StockTool.exe`
- Version probe: `1.2.2`
- Size: `24,121,162` bytes
- Modified UTC: `2026-07-26T03:30:02.7798807Z`
- SHA-256: `2960B34B18481DB5DC921128A5AD502A601792F6C11AEED8D3F2D6106E250466`
- Formal release was not replaced; `release\StockTool\StockTool.exe` remains SHA-256 `1FD70CB3610C7F1CAE64E7D16B082556E5D879C94B10E9F8F35CB88B18B2EBC4`.

Isolated staging smoke used `STOCK_TOOL_USER_DATA_DIR` under `%TEMP%` and verified:

- `/_stcore/health`: HTTP 200, body `ok`.
- Home page: HTTP 200.
- Light theme computed styles: body background `rgb(255, 255, 255)`, app text `rgb(49, 51, 63)`, title text `rgb(49, 51, 63)`, root color scheme `normal`.
- Dark theme computed styles: body background `rgb(14, 17, 23)`, app text `rgb(250, 250, 250)`, title text `rgb(250, 250, 250)`, root color scheme `normal`.
- Empty isolated refresh: Daily Research Home remained visible and displayed `目前沒有可更新的持股或自選股。`; no research workspace was opened by the refresh.
- Isolated `reports`, `logs`, and `data\cache` directories were writable.
- After cleanup: StockTool processes `0`; listeners on 8501 and 8502 `0`.

## Release Privacy Scan

Staging scan result:

- Files scanned: `2,803`.
- Forbidden user/runtime files: `0`.
- `.env`: `0`.
- `secrets*.toml`: `0`.
- `portfolio.csv`, `watchlist.csv`, runtime SQLite: `0`.
- Runtime `logs`, `reports`, and cache entries: `0`.

Only allowlisted public release assets and sample data were present. The staging EXE was not promoted.

## Real User Data Integrity

All checks were read-only and used the real runtime only for metadata and SHA-256 comparison. The current cleanup-run before/after values were identical:

| Path | Before | After |
|---|---|---|
| `%LOCALAPPDATA%\StockTool\data\portfolio.csv` | exists, 131 bytes, SHA `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` | identical |
| `%LOCALAPPDATA%\StockTool\data\watchlist.csv` | absent | absent |
| `%LOCALAPPDATA%\StockTool\data\processed\stock_data.sqlite` | exists, 339,968 bytes, SHA `2A2FA20A7A6F01FA3B22A942B82D6056A70755824FEF4FF6E8176ED24317CDF7` | identical |
| `%LOCALAPPDATA%\StockTool\settings.json` | absent | absent |

The cleanup did not initialize, migrate, move, overwrite, or delete user data. A previously recorded historical SQLite baseline differs from the current observed SQLite hash; this cleanup introduced no additional delta and does not claim to resolve that historical provenance discrepancy.

## Source Archive

- Path: `release\baseline\stocktool-sprint14.2.1.1-20260726-source.zip`
- Entries: `262` (including `SOURCE_ARCHIVE_MANIFEST.json`)
- SHA-256: `F7390B5A7BF42E5147333CBF8A4617386D9F1311607A8B14683CCBFE7E07197B`
- Sidecar: `release\baseline\stocktool-sprint14.2.1.1-20260726-source.zip.sha256`
- Sidecar matches the archive hash.
- Keyword-only verification: `verify_source_archive(archive_path=..., extracted_root=...)`.
- Required build inputs missing: `0`.
- Forbidden entries: `0`.
- Content mismatches: `0`.
- Temporary extraction directory was removed after verification.

## Rollback And Release Boundary

The formal release remains unchanged and is the rollback baseline. The new staging package can be independently reviewed and promoted only through the approved rollback-first release procedure. No formal release promotion occurred in this cleanup.

Known limitation: this cleanup removes dead code and revalidates the staging artifact; it does not investigate or alter the historical SQLite provenance discrepancy recorded in earlier acceptance material.

**Stop condition:** Sprint 15 was not started. Await independent CTO re-review.
