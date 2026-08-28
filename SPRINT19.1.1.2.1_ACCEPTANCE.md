# Sprint 19.1.1.2.1.1 implementation evidence

## Status

**NON-MANUAL IMPLEMENTATION EVIDENCE COMPLETE — WAITING FOR FRESH MANUAL
PRODUCT-OWNER VERIFICATION.** This record is not CTO acceptance, release
approval, signing approval, publishing approval, or permission to start another
Sprint.

The formal `release/StockTool/StockTool.exe` was not modified. No real user
data was modified.

## Implemented offline-wait correction

- Company-profile and fundamentals lookups now have bounded total remote-call
  deadlines, with a visible, safe limitation instead of an indefinite wait.
- When the price layer has already fallen back to local cache after a provider
  failure, the dashboard does not make a second fundamentals request; company
  research likewise suppresses optional remote metadata in that state.
- Unknown legacy research concepts no longer cause a fallback domain lookup
  failure.
- The external browser harness now shuts down the complete candidate process
  tree and records a clean listener outcome. The CDP evidence runner creates a
  fresh browser target for every journey, preventing old-tab console messages
  from contaminating the result.
- Lifecycle fixture paths are absolute, and generated installer fixture output
  is excluded from source archives.

## Automated quality and security evidence

| Gate | Result |
| --- | --- |
| Offline-regression targeted tests | `63 passed` |
| Full quality gate | passed |
| Full pytest | `970 passed, 2 skipped` |
| Branch coverage | `82.67%` (threshold `78.5%`) |
| Black, Ruff, focused mypy, compileall | passed |
| Project privacy scan | `0` violations |
| `pip-audit` | no known vulnerabilities (`artifacts/sprint19.1.1.2.1.1/pip-audit-offline-fix-final.json`) |

The harmless duplicate-entry warnings are test fixtures that assert archive and
backup rejection behavior; the quality gate completed successfully.

## Candidate and lifecycle evidence

| Artifact | SHA-256 |
| --- | --- |
| staging stable EXE | `6645908EE03A7283644935A6D7F368848F74E8753AECF7A3E03341C047B0D4D3` |
| staging payload EXE | `1B214A439221ECE9314A8173C6E3A06EFAB75AEC4BC542495A5AA7C5528C5387` |
| unsigned internal test installer | `6D67AEB46814E11E8D3051E64F64F5A6B755E48E1EDAB3EE8591099165CECE51` |
| preserved formal EXE | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |
| rollback installer (1.2.1) | `C6FE8F9A3B203C48D5A51974401B4287B7FF9D110D4FB3C08734FE2CFDEC96C0` |

`artifacts/sprint19.1.1.2.1.1/lifecycle-offline-fix-final-2/lifecycle-result.json`
has status `passed`: 17 commands and 5 snapshots cover first install,
post-copy/pre-switch interruption, upgrade, repair, authority rollback,
re-upgrade, and uninstall. Cleanup records no registry entry, no StockTool
process, no 8501/8502 listener, no isolated program directory, and a preserved
isolated-data sentinel.

## Fresh browser evidence: 9/9

Every row uses the current staging candidate, a new CDP page target, isolated
data, candidate SHA-256 metadata, PNG, DOM text, console capture, transport
log, and cleanup record. All nine console captures have **0 errors**; cleanup
left **0** listeners on ports 8501/8502.

| Market / symbol | Network condition | Evidence directory | Blocked provider events |
| --- | --- | --- | --- |
| Taiwan / 2330 | online | `browser-final-offline-fix/2330-online-clean-r2` | 0 |
| Taiwan / 2330 | offline | `browser-final-offline-fix/2330-offline-clean-r1` | 2 |
| Taiwan / 2330 | partial | `browser-final-offline-fix/2330-partial-clean` | 2 |
| Taiwan OTC / 6488 | online | `browser-final-offline-fix/6488-online-clean-r2` | 0 |
| Taiwan OTC / 6488 | offline | `browser-final-offline-fix/6488-offline-clean` | 2 |
| Taiwan OTC / 6488 | partial | `browser-final-offline-fix/6488-partial-clean` | 2 |
| US / AAPL | online | `browser-final-offline-fix/AAPL-online-clean-r2` | 0 |
| US / AAPL | offline | `browser-final-offline-fix/AAPL-offline-clean` | 1 |
| US / AAPL | partial | `browser-final-offline-fix/AAPL-partial-clean` | 1 |

Directories above are under `artifacts/sprint19.1.1.2.1.1/`. Offline and
partial cases used a process-scoped local verification proxy only; their
transport logs show the listed blocked Yahoo-provider calls. They did not
change the system proxy, firewall, formal release, or real user-data root.

## Privacy and source reproducibility

- Read-only before/after manifests for
  `C:\Users\steve\AppData\Local\StockTool` are byte-for-byte equal: **185
  files, 4,683,263 bytes** in each. See
  `real-user-data-before-offline-fix.json` and
  `real-user-data-after-offline-fix.json`.
- Final source archive:
  `artifacts/sprint19.1.1.2.1.1/source-archive-offline-fix/StockTool-source-final-v3.zip`
  — SHA-256
  `E29634BBCAA0FDAE87DA430BDB54421AFFF954D25138A46ED4ECC375DFFEE48B`.
  Extraction verification found no missing build inputs, forbidden entries,
  content mismatches, or duplicate entries.

## Required manual verification before independent acceptance

The candidate changed after earlier manual observations. The product owner
must therefore repeat the following against the current staging candidate:

1. Keyboard-only navigation, including `Shift+Tab` focus order.
2. Browser zoom at 100%, 125%, and 150%.

After those observations are recorded, the CTO/reviewer can perform independent
acceptance. Until then, this Sprint remains awaiting manual verification; no
release, signing, promotion, or next Sprint is authorized.
