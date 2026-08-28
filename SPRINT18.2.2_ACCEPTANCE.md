# Sprint 18.2.2 correction — implementation evidence

Status: implementation evidence only. This is not CTO acceptance, Sprint 18
completion, signing, publication, promotion, or authorization for another sprint.

## Implemented product changes

- `installer/StockTool.iss` now installs the stable `StockTool.exe` at `{app}`
  and payload only at `{app}\versions\{#MyAppVersion}`. Start Menu and
  post-install launch target the stable entry.
- `src/stock_tool/stable_entry.py` validates a strict versioned payload path,
  fails closed for missing/tampered/escaping authority, verifies the payload
  version, and atomically writes `current-version.json` through a temp file and
  `os.replace`.
- `stable_launcher.py` / `StableLauncher.spec` provide the production stable
  entry; it dispatches only the validated authority target and supports
  installer activation with `--activate-version`.
- `StockTool.spec` produces `StockToolPayload.exe`; build staging now places
  that complete onedir payload below `Payload/` and separately builds the
  stable entry.
- The lifecycle harness uses the installed product authority, stable entry,
  Inno logs, authority/directory snapshots, and a post-copy `ssPostInstall`
  fixture. It no longer maintains a harness-only authority file.

## Tests completed

Targeted authority/launcher/installer tests passed:

```text
tests/test_stable_entry.py
tests/test_stable_launcher.py
tests/test_installer_manifest.py
tests/test_release_layout.py
tests/test_user_data_paths.py
```

The actual Inno compiler successfully built the isolated 1.2.1 rollback and
1.2.2 current installers from the side-by-side layout.

## Lifecycle replay evidence and blocker

`artifacts/sprint18.2.2/lifecycle-replay-6` contains exact Inno logs for first
install, post-copy interruption, upgrade, repair, upgrade-again, and uninstall.
The logs show the stable-entry structure and the final uninstaller removing
`versions`, `current-version.json`, and the AppId registry key without touching
external user data.

The post-copy fixture is a real Inno fixture that copies the 1.2.2 payload into
`{app}\versions\1.2.2` and raises at `ssPostInstall`, before authority
activation. The harness checks that authority remains 1.2.1 and launches the
stable entry before proceeding.

However, the background replay wrapper did not write its final
`lifecycle-result.json` after the Inno uninstall completed. The known harness
wrapper issue means this correction does **not** yet have a complete
machine-readable successful replay and therefore is not presented as accepted.
The wrapper was stopped only after confirming it belonged to this isolated
lifecycle run; raw Inno logs were retained.

## Safety state at stop

- Fixed AppId uninstall registry: absent.
- `StockTool` / `StockToolPayload` processes: 0.
- 8501/8502 listeners: 0.
- No signing, publication, promotion, or overwrite of `release/StockTool` was
  performed.

## Remaining required verification

- Repair the lifecycle wrapper completion/result emission, then rerun the full
  replay to completion.
- Run full pytest with branch coverage, Black, Ruff, mypy, compileall, privacy
  scan, source archive verification, candidate hash/manifest verification, and
  before/after formal-release and real-user-data hash comparison after the final
  code state.
