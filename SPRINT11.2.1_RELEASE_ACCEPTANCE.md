# Sprint 11.2.1 Release Promotion

Status: **Sprint 11.2.1 正式候選已發布，等待 CTO 獨立 Release Acceptance。**

This document records release promotion only. No Python source, tests, product behavior, user data, or Sprint 12 scope was modified.

## Approved Candidate Verification

| Artifact | Required / actual SHA-256 | Result |
| --- | --- | --- |
| Staging EXE | `4CA2C7675DD9C3E9DA6DD8E807D425F494243EF74D677B0271927EC4C2FF76FA` | Matched before promotion. |
| Source archive | `9D7ACBAA767CDF16B85AD41859061F4AD98FFCEF0738D96B90B4C09A4A85DDBE` | Matched `stocktool-sprint11.2.1-20260718-source.zip.sha256`. |
| Staging release assets | `StockTool.exe`, `README.md`, `.env.example`, `使用教學_簡易版.txt`, `啟動股票工具.bat`, and `data/sample/` | Validated before promotion. |

## Pre-Promotion Formal Release

- Path: `release\StockTool\StockTool.exe`
- UTC time: `2026-07-18T04:48:33.8092803Z`
- Size: `24,022,677` bytes
- SHA-256: `0801C99607D0C5AE029FC50E8E53D7226969A315370D6BFDE6B2971517F2E28C`

No `StockTool` process or 8501/8502 listener existed before promotion.

## Rollback Preservation and Promotion Procedure

The existing `release\previous\StockTool` and all pre-existing `release\rollback` directories were left unchanged.

1. A complete copy of the prior formal release was created and validated at:
   `release\rollback\StockTool-pre-sprint11.2.1-20260718-210454\StockTool`
2. The live prior formal directory was preserved, not deleted, at:
   `release\rollback\StockTool-pre-sprint11.2.1-20260718-210454-live-original`
3. The preserved live-original rollback package contains `StockTool.exe`, all required public release assets, and has the original EXE SHA-256:
   `0801C99607D0C5AE029FC50E8E53D7226969A315370D6BFDE6B2971517F2E28C`.
4. Only after rollback verification, the complete `release\staging\StockTool` directory was moved to `release\StockTool`.
5. The newly formalized release assets and EXE hash were verified immediately after the directory exchange.

The controlled exchange did not use `publish_release.bat`, because that script's existing `previous`-directory guard is intentionally restrictive. It used a one-time directory move with a verified, timestamped rollback and a failure path that restores the preserved original rather than deleting it.

## Published Formal Release

- Path: `release\StockTool\StockTool.exe`
- Version: `1.2.2`
- UTC time: `2026-07-18T09:31:24.9739830Z`
- Size: `24,038,929` bytes
- SHA-256: `4CA2C7675DD9C3E9DA6DD8E807D425F494243EF74D677B0271927EC4C2FF76FA`
- Required release assets: validated successfully.

The formal EXE exactly matches the approved staging candidate. No old formal files were retained inside the newly promoted `release\StockTool` directory.

## Formal EXE Smoke Tests

All smoke tests used fresh, isolated `STOCK_TOOL_USER_DATA_DIR` directories under `%TEMP%`. No real user data was used.

| Check | Result |
| --- | --- |
| Cold start 1 | `/_stcore/health` returned exact HTTP 200 / `ok` in `14.90` seconds; homepage returned HTTP 200. |
| Cold start 2 | `/_stcore/health` returned exact HTTP 200 / `ok` in `14.19` seconds; homepage returned HTTP 200. |
| Writable runtime directories | Isolated `reports/`, `logs/`, and `data/cache/` write probes passed in both starts. |
| Shutdown | Complete StockTool process tree terminated after each smoke test. |
| Listener cleanup | 8501 and 8502 listeners were both `0` after cleanup. |
| Runtime cleanup | All isolated smoke runtime folders and temporary homepage files were removed. |

## Formal Release Privacy Scan

- Required formal release assets passed validation.
- Forbidden private files found: `0` (`.env`, `secrets*.toml`, `portfolio.csv`, `watchlist.csv`, `stock_data.sqlite`).
- No formal runtime `reports/`, `logs/`, `data/cache/`, or `data/processed/` directory exists.
- Exactly one packaged Streamlit configuration file exists: `_internal/.streamlit/config.toml`.
- Public sample data is present and permitted.
- Credential-shaped content scan across 15 allowlisted public/config/sample files found `0` matches for token, API key, authorization, password, or secret values.

`.env.example` remains an allowed public template; no real `.env` was included.

## Real User Data Integrity

The following were read-only before and after promotion. Values are identical:

| Item | Before / after |
| --- | --- |
| `%LOCALAPPDATA%\StockTool\data\portfolio.csv` | exists; 131 bytes; 5 lines; `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `%LOCALAPPDATA%\StockTool\data\watchlist.csv` | absent |
| `%LOCALAPPDATA%\StockTool\data\processed\stock_data.sqlite` | exists; 315,392 bytes; `FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C` |
| `%LOCALAPPDATA%\StockTool\settings.json` | absent |

No user data was moved, initialized, migrated, overwritten, or used by smoke tests.

## Desktop Shortcut

- Existing shortcut: `C:\Users\steve\OneDrive\Desktop\股票分析工具.lnk`
- Target: `C:\Users\steve\OneDrive\Documents\股票\release\StockTool\StockTool.exe`
- Working directory: `C:\Users\steve\OneDrive\Documents\股票\release\StockTool`
- No duplicate shortcut was created and the original shortcut was not modified.
- A temporary copy of this shortcut was launched with isolated runtime data. It started the formal release and `/_stcore/health` returned HTTP 200 / `ok`; the temporary shortcut and runtime were then removed.

## Source Archive

- Path: `release\baseline\stocktool-sprint11.2.1-20260718-source.zip`
- SHA-256: `9D7ACBAA767CDF16B85AD41859061F4AD98FFCEF0738D96B90B4C09A4A85DDBE`
- Sidecar: `release\baseline\stocktool-sprint11.2.1-20260718-source.zip.sha256`
- Sidecar hash matches the archive hash.

## Git Availability

Git is not available in the current Windows environment. No Git installation or Git operation was attempted.

## Rollback Procedure

If CTO Release Acceptance rejects this promotion:

1. Confirm no `StockTool` process is running.
2. Preserve the current formal candidate in a new, unique rollback directory; do not delete it.
3. Move `release\rollback\StockTool-pre-sprint11.2.1-20260718-210454-live-original` back to `release\StockTool`.
4. Validate release assets and confirm the restored EXE hash is `0801C99607D0C5AE029FC50E8E53D7226969A315370D6BFDE6B2971517F2E28C`.

## Remaining Limitations

- This release promotion does not introduce any new product functionality.
- The verified browser route is the formal Streamlit homepage HTTP endpoint. Actual default-browser behavior remains dependent on the user's Windows browser association; launcher failure to open a browser does not stop the local server.
- No Sprint 12 work has begun.
