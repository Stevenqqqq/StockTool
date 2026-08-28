# Sprint 18.2.1 correction — implementation evidence

Status: implementation evidence only. This document does **not** claim CTO
acceptance, Sprint 18 completion, signing, publication, promotion, or approval
to start Sprint 18.3/Sprint 19.

## Scope and changed files

- `scripts/verify_installer_lifecycle.ps1`: explicit `-AllowHostLifecycleTest`
  harness, host fail-closed preflight, exact Inno `/LOG` files, JSON result,
  side-by-side authority, synthetic interrupted-update fixture, and finally
  cleanup audit.
- `installer/StockTool.iss`: `MyDisableShellIntegration` switch prevents
  Start Menu and post-install launch side effects for isolated internal tests.
- `src/stock_tool/installer_build.py` and `build_installer.bat`: build an
  isolated 18.2.1 candidate, optionally bind rollback metadata, and pass the
  shell-integration switch.
- `src/stock_tool/release_archive.py`: includes `scripts/` in the allowlisted
  source archive and required rebuild inputs.
- `tests/test_installer_manifest.py`, `tests/test_user_data_paths.py`:
  rollback binding, no-shell-integration, lifecycle-harness contract, and
  source-archive coverage.

## Genuine rollback evidence

Trusted source archive used:

- `release/baseline/stocktool-sprint10.2-20260715-source.zip`
- source SHA-256:
  `F73C33EC835D3AFAA2463482271B179E6C9BA319F2E39136708A18A057D500EA`
- archive verification: 226 non-directory entries, no duplicate/path-traversal
  entry, and every embedded `SOURCE_ARCHIVE_MANIFEST.json` hash matched.

The archived canonical source reported `1.2.1`. Its isolated PyInstaller
payload reported all three required values as `1.2.1`:

- `StockTool.exe --version`
- `FileVersion`
- `ProductVersion`

An isolated packaging-only version-resource helper was added after extraction;
it derives its value only from the archived `stock_tool.__version__` and does
not substitute the current 1.2.2 payload.

## Candidate artifacts and manifest

| Artifact | SHA-256 | Authenticode |
| --- | --- | --- |
| `artifacts/sprint18.2.1/installer/StockTool-Setup-1.2.2-internal-test.exe` | `9D33000F8ED92E08864AB3A719AC7CD1A42BEC8D6A8F98D7BCA2E2028EFD81EC` | `NotSigned` |
| `artifacts/sprint18.2.1/rollback-installer/StockTool-Setup-1.2.1-internal-test-rollback.exe` | `B73071D10837EE3E7737237B171D8EF7074A12F21DCBCF17830B074A79F13815` | `NotSigned` |

`artifacts/sprint18.2.1/installer/update_manifest.json` was rebuilt from the
physical current installer and validates against both physical files. Its
rollback record names the 1.2.1 installer, version `1.2.1`, size `68653937`,
and SHA-256 `B73071D10837EE3E7737237B171D8EF7074A12F21DCBCF17830B074A79F13815`.
The current and rollback installers have distinct resolved paths, filenames,
and hashes.

## Reproducible lifecycle evidence

Final successful replay root:
`artifacts/sprint18.2.1/lifecycle-replay-3`.

- Command: `scripts/verify_installer_lifecycle.ps1 -AllowHostLifecycleTest`
  with explicit current installer, rollback installer, ISCC path, and isolated
  lifecycle root.
- Result: `lifecycle-result.json` reports `status: passed`.
- Each install/uninstall used an exact `/LOG=<path>` and the logs are retained
  in `inno-logs/`.
- First install 1.2.1, 1.2.1 version/health, upgrade 1.2.2,
  1.2.2 version/health, repair, synthetic interrupted update (expected exit
  code 7), old-current health recovery, authority switch/verification to real
  1.2.1, 1.2.2 upgrade again, and uninstall all completed.
- The synthetic fixture fails in `PrepareToInstall` before authority switch;
  it does not kill a system process.
- Final cleanup audit reports: uninstall registry absent, `StockTool` process
  count 0, 8501/8502 listener count 0, version directories absent, and the
  isolated user-data sentinel present.

Two earlier replay roots are retained as harness-debug evidence. They failed
before the final replay: the first used unreliable GUI `$LASTEXITCODE` handling,
and the second exposed a synthetic-fixture AppId escaping error. Both defects
were corrected; they are not presented as passing evidence.

## Test and quality results

- Targeted: `pytest tests/test_installer_manifest.py tests/test_release_archive.py tests/test_user_data_paths.py -q` — pass (2 expected skips).
- Full: `pytest --cov=stock_tool --cov-branch --cov-report=term` — **930 passed, 2 skipped**.
- Branch coverage: **82.52%** (configured gate: 78.50%).
- Changed-scope Black: pass.
- Changed-scope Ruff: pass.
- Focused mypy (`installer_build`, `release_manifest`, `release_archive`): pass.
- `compileall -q src tests`: pass.

`black --check src tests` still identifies 30 pre-existing unrelated formatting
differences; those files were not reformatted in this correction to preserve
the existing working tree. This is disclosed rather than treated as a full-tree
Black pass.

## Privacy, archive, and preservation evidence

- Project privacy scan: 0 violations.
- Current staging trust-boundary validation: pass.
- Candidate/rollback artifact scan: no PDF, SQLite/DB, or private-key/container
  files found.
- Source archive:
  `release/staging-sprint18.2.1-source.zip`, SHA-256
  `FD42D42C14A057BC2817C6403A831E3E0863F5D72BAE8D8F283CCACAEBB02387`.
  Verification found zero missing required inputs, forbidden entries, content
  mismatches, and duplicate entries.
- Before/after snapshots are retained in
  `artifacts/sprint18.2.1/preservation-before.json` and
  `artifacts/sprint18.2.1/preservation-after.json`. Portfolio, watchlist,
  SQLite, settings, and formal EXE existence/size/SHA-256 matched exactly.
- Formal `release/StockTool/StockTool.exe` remains SHA-256
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.

## Known limits and rollback

- Candidates are unsigned internal-test artifacts only; no signing,
  publishing, promotion, or formal-release overwrite was performed.
- The lifecycle harness deliberately requires explicit opt-in and refuses any
  existing fixed-AppId registry entry, default install directory, active
  StockTool process, or 8501/8502 listener.
- The side-by-side lifecycle uses test-owned `current-version.json` authority,
  not an OS Start Menu shortcut, so host shell integration is never created.
- Rollback is exercised by returning authority to the still-present verified
  1.2.1 side-by-side payload, then rechecking executable version and health.
  It is not a claim about production rollback policy or CTO acceptance.
