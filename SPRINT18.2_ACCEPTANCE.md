# StockTool Sprint 18.2 — Unsigned Internal-Test Installer Evidence

Date: 2026-07-28 (Asia/Taipei)

## Scope

Sprint 18.2 only. No signing, publishing, promotion, formal-release overwrite,
Sprint 19 work, reset/clean, or Git reconstruction occurred. All lifecycle data
used isolated `STOCK_TOOL_USER_DATA_DIR` paths.

## Inno Setup supply chain

| Item | Evidence |
| --- | --- |
| winget source | `winget` (`https://cdn.winget.microsoft.com/cache`) |
| package/version | `JRSoftware.InnoSetup` 6.7.3 |
| metadata publisher | `jrsoftware.org` |
| install | approved exact winget command, exit 0 |
| ISCC | `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe` |
| ISCC SHA-256 | `0A8757031B33777E4C9CBFFEE40F11A5062B36D25CBE144C1DB73B6102B80AD7` |
| ISCC Authenticode | `Valid`, `CN=Pyrsys B.V.` |

ISCC is a regular non-reparse file. Official jrsoftware.org documentation states
that `Pyrsys B.V.` is the expected Authenticode publisher for Inno Setup 6.

## Installer and manifest

- `STOCK_TOOL_STAGING_PARENT=release\staging-sprint18.2 build_exe.bat`: exit 0.
- Staging trust/privacy/output validation: passed.
- `build_installer.bat` using actual ISCC: exit 0.
- Artifact-bound manifest validation against the physical installer: passed.

| Artifact | Value |
| --- | --- |
| installer | `artifacts\sprint18.2\installer\StockTool-Setup-1.2.2-internal-test.exe` |
| size | 69,004,649 bytes |
| SHA-256 | `5C05D661339F17B6C86B8FC6FE114DB7EE66AF5784C310F79931D7F6B0C14EA6` |
| Authenticode | `NotSigned` — deliberate internal-test-only artifact |
| manifest | filename, size, SHA exactly match; channel `internal-test`; version `1.2.2` |
| candidate EXE SHA-256 | `256F20E26979CC69A99D87C810B7153823D363CD9E7CC1DB7AA5AC718B3B985A` |

## Host-isolated lifecycle

No existing Sandbox/VM was available. Host preflight found no fixed-AppId
uninstall entry, no default StockTool install directory, and no process.
All test targets were under `artifacts\sprint18.2\lifecycle-host-retry`.

| Check | Result |
| --- | --- |
| silent first install | exit 0; EXE and `_internal` present |
| installed version | `--version`, FileVersion, ProductVersion all `1.2.2` |
| child no-browser health/homepage | `ok`, HTTP 200 |
| 8501 occupied fallback | selected 8502; homepage HTTP 200 |
| browser safety | explicit `STOCK_TOOL_NO_BROWSER=1` test opt-in |
| repair install | exit 0 |
| synthetic 1.2.3 upgrade / 1.2.1 downgrade | both exit 0; payload remained canonical `1.2.2` |
| both ports occupied | exit 1, fail closed |
| uninstall | exit 0; program directory and uninstall registry removed |
| isolated sentinel/settings/test data | preserved after uninstall, then test root cleaned |
| leftover processes/listeners | 0 / 0 |

Synthetic fixture installers are isolated under
`artifacts\sprint18.2\synthetic-lifecycle`, carry no manifest, and do not mix
with the canonical candidate. The initial harness observed Inno Setup deferred
directory removal after uninstaller return; its retry waited for completion and
passed. The initial isolated root was removed.

## Quality and preservation

| Check | Result |
| --- | --- |
| final quality gate | passed all stages |
| full pytest | 928 passed, 2 skipped, 2 intentional duplicate-entry warnings |
| branch coverage | 82.48% (gate 78.50%) |
| Black/Ruff/focused mypy/compile | passed |
| privacy/release scan | passed; `privacy violations: 0` |
| source archive SHA-256 | `BCDCACBA08E23AF163829146047C04BC8C4C644993BCB9E1FFF23F1BCF78117D` |
| archive verify | missing `()`, forbidden `()`, mismatches `()`, duplicates `()` |
| formal EXE | unchanged `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |
| real portfolio | unchanged: 131 bytes, `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| real watchlist/ledger/settings | absent before and after |

## Limitations

- The installer and application are deliberately unsigned; no signing occurred.
- Abrupt/interrupted installation rollback was not simulated on the host, so it
  is not claimed as passed.

This is implementation evidence only. It does **not** claim CTO acceptance,
complete Sprint 18 acceptance, release approval, or authorization for Sprint 19.
