# Sprint 18 Phase A — Windows Installer Foundation Evidence

Date: 2026-07-28

Scope: approved Sprint 18 **Phase A only**. This implementation adds an unsigned internal-test, per-user installer foundation. It does not sign, publish, promote, integrate twstock, or start Sprint 19.

## Entry gate

- `git status --short --branch`: healthy `main` worktree before changes.
- `git rev-parse --show-toplevel`: resolved to this project root.
- `git fsck --no-dangling`: exit 0.
- No Git repair, initialization, reset, clean, history rewrite, commit, push, tag, or PR action was performed.

## Delivered Phase A foundation

- `installer/StockTool.iss`
  - Fixed `AppId` (`{7ABF2B4C-4D79-4E74-B66C-9AF7E9E06568`).
  - `PrivilegesRequired=lowest` and install target `{localappdata}\Programs\StockTool`.
  - Copies only the verified PyInstaller onedir staging tree into `{app}`.
  - Start-menu and launch entries use `{app}` as `WorkingDir`.
  - Contains no `[UninstallDelete]` section and never targets `%LOCALAPPDATA%\StockTool` runtime data.
- `installer/version_info.txt` and `StockTool.spec`
  - Windows EXE version resource now provides ProductName `StockTool`, FileVersion/ProductVersion `1.2.2`, CompanyName `StockTool Internal Test`, and OriginalFilename `StockTool.exe`.
  - `build_exe.bat` builds the single `StockTool.spec` packaging definition, avoiding divergent CLI and spec metadata.
- `src/stock_tool/release_manifest.py`
  - Generates/verifies public-only update metadata: schema, product/version, internal-test channel, artifact filename/size/SHA-256/timestamp, user-data compatibility, and rollback fields.
  - Fails closed for production channels, publishers other than `StockTool Internal Test`, invalid hashes, paths in artifact filenames, and malformed rollback/compatibility metadata.
- `src/stock_tool/installer_build.py` and `build_installer.bat`
  - Compile only an unsigned internal-test installer from verified staging.
  - Output is limited to `artifacts/sprint18-phase-a/installer`.
  - Fails closed when Inno Setup `ISCC.exe` is absent; it does not download tools, sign, or fabricate an installer.
- `installer/update_manifest.json`
  - Documents the generated-manifest schema/template. Generated manifests are written only alongside actual installer artifacts.
- `src/stock_tool/release_archive.py`
  - Source archives now include `installer/` and `build_installer.bat` as rebuild inputs.
- `src/stock_tool/quality_gate.py`
  - Replaces the stale Sprint 15 changed-file scope with the explicit Sprint 18 Phase A source/test scope. It still contains no build, installer compile, signing, publish, or promotion step.

## Test and quality evidence

| Check | Result |
| --- | --- |
| Sprint 18 targeted suite | `pytest tests/test_installer_manifest.py tests/test_user_data_paths.py tests/test_release_layout.py tests/test_runtime_paths.py tests/test_release_assets.py tests/test_exe_smoke.py tests/test_launcher.py tests/test_quality_gate.py -q` — **52 passed** |
| Final full pytest + branch coverage | `python -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing` — **877 passed, 1 existing duplicate-ZIP warning, 82.53%** (threshold 78.50%) |
| Changed-file Black | pass (10 Phase A changed Python files) |
| Ruff | `ruff check src tests` — pass |
| Focused mypy | Phase A source/tests — pass |
| Compile | `compileall -q src` — pass |
| Diff check | `git diff --check` — pass |
| Project privacy scan | `project_privacy_violations(Path('.'))` — `()` |

The aggregate `python -m stock_tool.quality_gate` command was also started, but the host command time limit interrupted it after 124 seconds while it was rerunning its already-passing full-test/coverage steps. The required individual checks above completed successfully. Full-repository Black remains outside Phase A scope because 30 pre-existing files would be reformatted; no unrelated reformatting was applied.

## Staging EXE evidence

- Candidate: `release/staging-sprint18-phase-a/StockTool/StockTool.exe`
- `build_exe.bat` with `STOCK_TOOL_STAGING_PARENT=release\staging-sprint18-phase-a`: exit 0.
- `--version`: `1.2.2`.
- Windows version resource: ProductName `StockTool`; FileVersion/ProductVersion `1.2.2`; CompanyName `StockTool Internal Test`; OriginalFilename `StockTool.exe`.
- With `STOCK_TOOL_USER_DATA_DIR=artifacts/sprint18-phase-a/user-data`:
  - `/_stcore/health` on 8501: HTTP 200.
  - homepage on 8501: HTTP 200.
- Unit regression verifies the 8501-to-8502 launcher fallback. An attempted additional real-process port-occupancy smoke was rejected by the host shell safety policy before process creation; no fallback result was fabricated.
- Final process audit: StockTool processes = 0; 8501/8502 listeners = 0.

## Installer status and known limitations

- Inno Setup 6 `ISCC.exe` is not installed at the configured/common Windows locations. `build_installer.bat` was executed and failed closed with `FileNotFoundError: Inno Setup 6 ISCC.exe is required for installer compilation.`
- Therefore no installer EXE, generated installer manifest, install/uninstall smoke, or installer SHA-256 exists for this machine. This is an environment prerequisite, not a replacement with a fake artifact.
- Authenticode signing and all production signing/promotion actions remain deliberately out of scope for Phase A.

## Privacy, archive, hashes, and rollback

- Candidate forbidden/private-file scan (`.env`, portfolio, watchlist, settings, ledger, research document metadata, cache): 0 files.
- Source archive: `release/staging-sprint18-phase-a-source.zip`
  - SHA-256: `7C7EFEFB35D746046F5E665D62D506DF7CD9A5B3B45E671AFA2D8DA51C15C239`
  - Verification: no missing build inputs, forbidden entries, or content mismatches.
- Candidate EXE SHA-256: `D171725A44E8900FF66CEEECF1A90A60E0D97E006DCCD349A42E205874CDDE1B`.
- Formal release EXE remains unchanged: `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- Before/after real user-data fingerprint is unchanged:
  - `C:\Users\steve\AppData\Local\StockTool\data\portfolio.csv`: exists, 131 bytes, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
  - watchlist, ledger SQLite, and settings were absent before and after.
- All execution writes used the Phase A staging/artifacts and isolated user-data paths. No real user data was moved, overwritten, or deleted.
- Rollback: keep the unchanged `release/StockTool` formal release; remove only the Phase A staging/archive/artifact directories if this candidate is rejected. No promotion occurred.

## Handoff

This file records implementer evidence only. It does **not** declare CTO acceptance, formal release readiness, or promotion approval. Independent CTO review remains required.
