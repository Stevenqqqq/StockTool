# Sprint 6 Acceptance Record: v1.1 Stabilization, E2E, and Windows Release

## Status

`implementation complete and ready for independent acceptance review`

This is an implementation handoff. It is not a declaration of independent
acceptance or release-owner approval.

## Scope and implementation

Sprint 6 stopped feature development and delivered release hardening only:

- One canonical version source: `stock_tool.__version__ = "1.1.0"`.
- Dynamic package metadata, CLI `--version`, launcher `--version`, and visible
  Dashboard sidebar version all read that source.
- A staging-first onedir build. `build_exe.bat` only replaces
  `release\staging\StockTool`; `publish_release.bat` migrates legacy release
  data before preserving the old release under `release\previous\StockTool`.
- Deterministic, provider-double Research Journey integration coverage for
  2330/TWSE, 6488/TPEX, AAPL/US, partial data, cache fallback, transparent
  provider failure, T+1 execution, configured trading costs, benchmark, and
  report generation.
- Launcher fallback from 8501 to 8502, plus a readable
  `launcher_*_error.log` when neither port is available.
- v1.1 release, rollback, privacy, and Windows manual-acceptance documentation.

## Modified and added files

- `AGENTS.md`
- `pyproject.toml`
- `src/stock_tool/__init__.py`
- `src/stock_tool/dashboard/shell.py`
- `src/stock_tool/release_archive.py`
- `launcher.py`
- `build_exe.bat`, `clean_build.bat`, `publish_release.bat`
- `README.md`, `使用教學_簡易版.txt`, `CHANGELOG.md`
- `docs/release/v1.1-checklist.md`, `docs/release/acceptance-v1.1.md`
- `tests/e2e/test_research_journey.py`, `tests/test_release_layout.py`,
  `tests/test_exe_smoke.py`, and focused regression updates in CLI, runtime,
  archive, dashboard-navigation, and baseline fixture tests.

## Version consistency

- Canonical version: `1.1.0` in `src/stock_tool/__init__.py`.
- `pyproject.toml` uses setuptools dynamic metadata from that attribute.
- Installed editable metadata, `stock-tool --version` behavior, launcher
  `--version`, and Dashboard sidebar visibility are covered by tests.

## Automated verification

| Check | Actual result |
| --- | --- |
| Sprint 6 targeted tests | `40 passed in 14.54s` |
| Full pytest | `385 passed in 24.00s` |
| Branch coverage | `78.80%` in `45.23s`; configured gate is `78.50%` |
| Focused Black | Passed for 11 Sprint 6 source/test files |
| Focused Ruff | Passed for the same 11 files |
| Focused mypy | `Success: no issues found in 11 source files` |

Automated integration coverage is explicitly application integration, not
browser E2E. It uses deterministic provider doubles and versioned sample data;
it does not call an external market provider.

## Packaged Windows verification

The onedir package was built to `release\staging\StockTool`, copied to an
unrelated temporary staging path, and launched with an isolated
`STOCK_TOOL_USER_DATA_DIR` and `PATH=C:\Windows\System32` only. It did not
depend on the repository or `.venv` at runtime.

- 8501 primary health smoke: HTTP 200, body `ok`.
- With 8501 deliberately occupied, the launcher selected 8502 and health was
  HTTP 200, body `ok`.
- With both 8501 and 8502 occupied, the launcher exited with code 1 and wrote
  a readable isolated-runtime `launcher_*_error.log` naming both ports.
- Isolated `reports`, `logs`, and `data\cache` accepted write markers.
- Official-release smoke: `StockTool.exe --version` returned `1.1.0`; health
  returned HTTP 200 / `ok`; write markers succeeded.
- After smoke cleanup: zero StockTool processes and zero listeners on 8501,
  8502, and 8510.

The formal release was promoted only after staging verification. The preserved
previous executable hashes to the accepted Sprint 5.2.2 baseline.

## Release artifact

- EXE: `release\StockTool\StockTool.exe`
- Last write: `2026-07-14 13:06:49 +08:00`
- Size: `23,862,402` bytes
- SHA-256: `1339A1A88F2740797D270C1A9B4F23143FDF204B888B1B5EF986CCA4D5CCF192`
- Sidecar: `release\StockTool\StockTool.exe.sha256`
- The only packaged Streamlit user configuration is
  `_internal\.streamlit\config.toml`; no `secrets.toml` was found.

## Privacy and user-data integrity

Release privacy scan of `release\StockTool` found zero prohibited `.env`,
`secrets*.toml`, credentials, portfolio/watchlist CSVs, runtime logs, reports,
cache, `.coverage`, bytecode cache, private test token marker, or project
absolute-path strings. The packaged `_internal\streamlit\runtime\secrets.py`
module is third-party Streamlit code, not a `secrets.toml` credential file.

Real user data was read only:

- `%LOCALAPPDATA%\StockTool\data\portfolio.csv`: `4` rows,
  SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`
  before and after Sprint 6.
- `%LOCALAPPDATA%\StockTool\data\watchlist.csv`: absent before and after.

All smoke runtime directories were isolated below `%TEMP%` and removed after
verification.

## Rollback and source archive

- Rollback package:
  `release\baseline\stocktool-sprint5.2.2-20260713-rollback.zip`
- Rollback SHA-256:
  `CA8A167179551A04511A94C58BC132A05C8F3B02878047D20C52A02EE87881C6`
- Preserved previous release EXE SHA-256:
  `37F2B5827D4685FE49F049CFDB5490E574FCA2CF101D38F7C1998065FFC638EB`
- Sprint 6 source archive:
  `release\baseline\stocktool-sprint6-20260714-source.zip`
- Source SHA-256:
  `C14065C112C4F0CA7DF7D33CDAB3E075DAF720F1DEF137F8AC99D5FCDA477200`
- Source archive sidecar:
  `release\baseline\stocktool-sprint6-20260714-source.zip.sha256`
- Archive verification: 192 entries, 115 required build inputs, zero missing
  inputs, zero forbidden entries, and zero workspace-content mismatches.

## Known limitations and independent acceptance items

- No clean Windows VM or Windows Sandbox was available. The separate manual
  checklist in `docs/release/v1.1-checklist.md` must be completed by an
  independent reviewer on a machine without the repository, `.venv`, or Python
  on `PATH`.
- External free providers can be unavailable, delayed, incomplete, or stale.
  The UI distinguishes online, cache, sample, SQLite, partial, and stale data;
  it does not promise complete coverage.
- Historical research and backtest output does not represent future returns.
  StockTool does not auto-trade or provide personalized investment advice.

## Rollback procedure

Follow `docs/release/v1.1-checklist.md`: stop all StockTool processes, preserve
the current release for investigation, validate the rollback sidecar, restore
the approved prior release folder, and recheck the real user-data hashes. Do
not copy runtime data into the release folder.
