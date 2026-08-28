# Sprint 15.1.3.1 Acceptance

**Status:** Implementation complete and ready for independent CTO acceptance review.

## Scope

This hotfix is limited to Daily Research Home navigation and effective watchlist behaviour. It does not promote the staging release, change financial-analysis logic, or begin Sprint 16.

## Root Cause and Fix

### Home navigation

Home CTA actions changed the legacy page state after the primary Streamlit radio widget had already been instantiated. On the next rerun, the radio could retain its previous value and override the intended destination.

`navigate_to_workspace()` now records an explicit pending destination containing the primary workspace and direct legacy child page. `apply_pending_workspace_navigation()` consumes that pending destination before the primary radio is rendered on the next rerun. This keeps a user action distinct from widget persistence:

- `查看持倉` / `前往持倉管理` routes to `持倉` then `投資組合管理`.
- `管理自選股` / `查看自選股` routes to `探索` then `自選股清單`.
- The pending destination is consumed once, so the action causes one stable rerun rather than a navigation loop.

### Effective watchlist

The manual watchlist remains the only persisted `data/watchlist.csv` source. `build_effective_watchlist()` creates a non-mutating in-memory union of manual items and market-qualified holdings.

- Only explicit `TWSE`, `TPEX`, and `US` holdings are automatically tracked.
- Identity is canonical `symbol + market`; unknown or custom markets are not guessed.
- A manual note is retained on an overlap.
- Labels are `手動自選`, `持股自動追蹤`, and `手動自選＋持股`.
- Removing a manual item that is still held leaves the derived tracking item. Derived items are never written to `watchlist.csv`.
- A missing manual watchlist file is normal first-use state. With no holdings and no manual item, Home displays: `尚未建立追蹤清單，可加入自選股或先建立持股。`

Home summaries, Daily Brief construction, daily-refresh identities, and the watchlist page now use this same effective union.

## Modified Files

- `src/stock_tool/dashboard/state.py`
- `src/stock_tool/dashboard/shell.py`
- `src/stock_tool/dashboard/pages/home.py`
- `src/stock_tool/dashboard/home_data.py`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/watchlist.py`
- `tests/test_dashboard_shell.py`
- `tests/test_dashboard_home_data.py`
- `tests/test_dashboard_navigation.py`
- `tests/test_watchlist.py`
- `tests/test_daily_home.py`

## Tests and Quality Checks

| Check | Command / scope | Result |
| --- | --- | --- |
| Sprint targeted tests | `python -m pytest tests/test_dashboard_shell.py tests/test_dashboard_home_data.py tests/test_dashboard_navigation.py tests/test_watchlist.py tests/test_daily_home.py` | `42 passed in 12.42s` |
| Full suite | `python -m pytest` | `676 passed in 51.68s` |
| Branch coverage | `python -m coverage erase; python -m coverage run -m pytest -q; python -m coverage report --precision=2` | `82.34%` total; above the 81.75% independent quality gate and 78.50% formal gate |
| Black | `python -m black --check` on the 11 changed source/test files | Passed; `11 files would be left unchanged` |
| Ruff | `python -m ruff check` on the same 11 files | Passed; `All checks passed!` |
| Mypy | `python -m mypy --ignore-missing-imports` on the six changed source files | Passed; `Success: no issues found in 6 source files` |

The focused mypy scope intentionally covers changed production source only. The existing test doubles are not part of this focused type-check command.

## UI and Runtime Smoke

The newly built staging executable was used with isolated `STOCK_TOOL_USER_DATA_DIR` directories only.

- Home with four isolated holdings displayed an effective watchlist count of four without requiring a manual `watchlist.csv`.
- Browser journey passed: Home `查看持倉` opened primary `持倉` with direct child `投資組合管理`; after returning Home, `查看自選股` opened primary `探索` with direct child `自選股清單`.
- The watchlist page displayed the derived-tracking notice and accepted an isolated manual item. Source-label, overlap-note, removal, and no-persistence rules are regression tested through the effective-watchlist contract.
- Normal staging health: `http://127.0.0.1:8501/_stcore/health` returned HTTP 200 with body `ok`; homepage returned HTTP 200.
- With an isolated IPv4 listener reserving 8501, the launcher started on 8502; `http://127.0.0.1:8502/_stcore/health` returned HTTP 200 with body `ok`; homepage returned HTTP 200.
- Isolated `reports/`, `logs/`, and `data/cache/` accepted writes.
- Browser tabs, StockTool process trees, and 8501/8502 listeners were closed after smoke tests.

## Staging Artifact

- Path: `release/staging/StockTool/StockTool.exe`
- Size: `24,148,751` bytes
- Modified UTC: `2026-07-26T12:38:50.232255+00:00`
- SHA-256: `D6768755523E3040330CBF04B0BCA0BBB5B639D923C252FFD953A5C3853C2E03`

The formal executable was not changed:

- Path: `release/StockTool/StockTool.exe`
- Size: `24,145,141` bytes
- Modified UTC: `2026-07-26T11:19:29.888766+00:00`
- SHA-256: `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`

## Privacy and User Data Integrity

The staging release scan found zero forbidden runtime files (`.env`, `secrets*.toml`, portfolio/watchlist CSV, SQLite, logs, reports, or cache) and `project_privacy_violations()` returned zero content findings. Public `.env.example`, sample data, and packaged implementation files remain allowed.

No real user data was used by tests or smoke tests. Before and after validation, the real runtime state was unchanged:

| Item | State |
| --- | --- |
| `portfolio.csv` | Exists; 4 rows; 131 bytes; modified UTC `2026-07-11T08:36:17.736126+00:00`; SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `watchlist.csv` | Does not exist |
| `stock_data.sqlite` | Exists; 339,968 bytes; modified UTC `2026-07-26T12:04:17.753552+00:00`; SHA-256 `99550D52C8A95A612505D704433D718C9B13AC2024618E3E728182E25B335866` |
| `settings.json` | Does not exist |

## Source Archive

- Path: `release/baseline/stocktool-sprint15.1.3.1-20260726-source.zip`
- Entries: `268`
- Size: `2,322,986` bytes
- Modified UTC: `2026-07-26T12:56:16.273301+00:00`
- SHA-256: `7667BB98B0F22E38B5D9E4D29EFAD596C05F77A48959ECA8D83E8F75DEB773F3`
- Sidecar: `release/baseline/stocktool-sprint15.1.3.1-20260726-source.zip.sha256` matches the ZIP hash.
- Keyword-only archive verification: required build inputs missing `0`, forbidden entries `0`, content mismatches `0`.

## Rollback and Known Limits

- No formal release was promoted. Rollback is to discard `release/staging/StockTool` and retain the existing formal `release/StockTool` artifact unchanged.
- Holdings-derived tracking is intentionally in-memory; it is not a second persisted watchlist file.
- `AUTO`, `CUSTOM`, and unresolved markets are intentionally excluded from automatic tracking until reliable canonical market identity exists.
- Sprint 16 has not started.
