# StockTool Sprint 18.1 Correction — Implementation Evidence

Date: 2026-07-28 (Asia/Taipei)
Scope: Sprint 18.1 correction only.  No Sprint 19 work, signing, publishing,
promotion, official-release replacement, or real-user-data migration was performed.

## Scope and modified files

Sprint 18.1 correction changes:

- `src/stock_tool/release_manifest.py` — artifact-bound manifest validation,
  rollback metadata validation, and actual-file hash/size/name verification.
- `src/stock_tool/installer_build.py` — recursive staging privacy/reparse/escape
  boundary and read-only signing prerequisite discovery.
- `src/stock_tool/version_resource.py` — generated Windows version resource from
  the canonical `stock_tool.__version__` source.
- `StockTool.spec` — consumes only the generated build-time version resource.
- `installer/version_info.txt` — no longer carries a second hard-coded version.
- `installer/update_manifest.json` — documents rollback artifact hash/size fields.
- `build_installer.bat` — uses `release/staging-sprint18.1` and
  `artifacts/sprint18.1/installer` only.
- `src/stock_tool/release_archive.py` — rejects duplicate ZIP entries during
  verification.
- `src/stock_tool/quality_gate.py` — includes the generated version source in
  the focused quality scope.
- `tests/test_installer_manifest.py`, `tests/test_release_archive.py`,
  `tests/test_user_data_paths.py` — adversarial and staging-path regression
  coverage.

Existing uncommitted Sprint 18 Phase A work was retained.  It was neither reset
nor cleaned, and `.git` was not rebuilt.

## Blocker evidence

### 1. Artifact-bound manifest verification

- `validate_update_manifest(payload, artifact_path, ...)` now requires the
  physical candidate installer path and recomputes filename, `size_bytes`, and
  SHA-256.
- Missing files, non-`.exe` files, symlinks/non-regular artifacts, filename
  mismatch, post-manifest EXE changes, size mismatch, and hash mismatch fail
  closed.
- Targeted tests cover manifest creation followed by EXE modification, missing
  and non-executable files, name mismatch, and symlink rejection.

### 2. Rollback metadata safety

- Rollback metadata now contains `artifact_filename`, `version`, `size_bytes`,
  and `sha256`; it is verified against a supplied rollback installer path.
- Filenames must be nonblank basename-only `.exe` names. Absolute paths,
  separators, traversal, and non-EXE values are rejected.
- Rollback versions must match the allowed numeric semantic-version format.
- Targeted tests cover traversal, garbage versions, and rollback hash/size
  tampering.

### 3. Installer staging trust boundary

- `validate_installer_staging()` executes before Inno Setup compilation and
  recursively rejects `.env` (while allowing `.env.example`), credentials/token
  configuration, private TOML, portfolio/watchlist/settings, SQLite/DB files,
  ledger, research documents, cache, logs, reports, backups, symlinks,
  junction/reparse points, and entries escaping the staging root.
- Public vendor headers such as `tz_private.h` are permitted; the `private`
  marker is intentionally limited to configuration/document-like suffixes.
- Adversarial tests cover `.env`, SQLite, private TOML, runtime directories,
  documents, and a real symlink escape.
- Actual candidate staging check: passed.

### 4. Single canonical version

- Canonical source remains `stock_tool.__version__` (`1.2.2`).
- The generated PyInstaller resource, Inno `MyAppVersion`, and manifest version
  all derive from this value. No release version is duplicated in a static
  resource file.
- Candidate `--version`: `1.2.2`; Windows FileVersion/ProductVersion: `1.2.2`.

## Validation commands and results

| Command / check | Result |
| --- | --- |
| `.venv\Scripts\python.exe -m pytest tests\test_installer_manifest.py tests\test_release_archive.py -q` | 45 passed, 2 skipped (intentional duplicate-ZIP test warning) |
| `quality_gate.bat` | Passed all configured stages |
| full pytest inside final gate | 906 passed, 2 skipped, 2 intentional duplicate-entry warnings; exceeds 877-test floor |
| configured branch coverage | 82.53%; gate 78.50% passed |
| Black / Ruff / focused mypy / compileall | Passed in final quality gate |
| project privacy scan | `privacy violations: 0` |
| release layout and regression baseline | Passed |
| `STOCK_TOOL_STAGING_PARENT=release\staging-sprint18.1 build_exe.bat` | Exit 0; candidate only |
| candidate EXE smoke with new `STOCK_TOOL_USER_DATA_DIR` | health `ok`, homepage HTTP 200, then process/listeners 0 |
| candidate release-assets and staging privacy scan | Passed |
| `build_installer.bat` | Correctly failed closed: `Inno Setup 6 ISCC.exe is required for installer compilation.` |
| source archive create + verify | required inputs missing `()`, forbidden `()`, mismatches `()`, duplicate entries `()` |

The full repository-wide `black --check src tests` still reports 30 pre-existing
files outside the focused Sprint 18 quality scope. No unrelated reformatting was
applied. The configured focused Black check passed.

## Artifacts and hashes

| Artifact | SHA-256 |
| --- | --- |
| Candidate EXE `release/staging-sprint18.1/StockTool/StockTool.exe` (24,237,195 bytes) | `170B82FE5B0BC3EA599B8232794F740CC72A736DACA891D11D47EA5F2BAC76C1` |
| Source archive `release/staging-sprint18.1-source.zip` | `7A18493EA0DD7FAFD7D3B1EE896BC21FB187FA449ED294EE42AE58D6419482C9` |
| Formal EXE `release/StockTool/StockTool.exe` (not modified) | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

## Prerequisites and lifecycle evidence

- Read-only discovery found no Inno Setup `ISCC.exe`, no `signtool`, and no
  configured signing certificate. Nothing was downloaded, installed, signed,
  or fabricated.
- Therefore a real installer, first-install/upgrade/downgrade/uninstall/
  rollback lifecycle, standard-user installation, and installer-specific
  no-browser/open-failure scenarios are **blocked by missing prerequisites**;
  they are not claimed as passed.
- Candidate EXE health/homepage smoke ran without invoking a browser through the
  bundled Streamlit child mode.

## Real-user-data and release preservation

Before and after checks of `%LOCALAPPDATA%\StockTool` were identical:

| Item | State |
| --- | --- |
| `data/portfolio.csv` | exists, 131 bytes, `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `data/watchlist.csv` | absent |
| `data/ledger/portfolio_ledger.sqlite` | absent |
| `settings.json` | absent |

All smoke/gate runs used newly created, isolated `STOCK_TOOL_USER_DATA_DIR`
locations. At completion, `StockTool` process count was 0 and 8501/8502 listener
count was 0. The formal release hash above confirms no overwrite.

## Known limitations and rollback

- This is an unsigned internal-test candidate only; it is not a release and is
  not promoted.
- Installer lifecycle acceptance remains prerequisite-blocked until the user
  provides an environment with Inno Setup (and, if signing is later authorized,
  explicit signing credentials).
- Rollback for a future installer requires a separately supplied, verified
  rollback EXE; no rollback artifact was created here.
- Rollback of this code change is a normal source/worktree revert by the user;
  no real user data or formal release artifact needs restoration.

Implementation evidence is complete for CTO independent review. This document
does **not** claim CTO acceptance or formal release approval.
