# Sprint 18.2.2.1 correction — implementation evidence

Status: implementation evidence only. No CTO acceptance, Sprint 18 completion,
signing, publication, promotion, or next-sprint authorization is claimed.

## Implemented corrections

- The lifecycle harness now reads authority files using
  `[IO.File]::ReadAllText`, preserving `authority_json` and authority snapshots
  as plain JSON strings rather than PowerShell provider objects.
- It serializes a bounded (< 1 MB) result, rereads it immediately, and requires
  `status`, `commands`, `snapshots`, `cleanup`, and `completed_utc`.
- The interruption fixture is again compiled directly from
  `installer/StockTool.iss` with `MyFailAfterPayloadCopy=1`; the harness fails
  closed unless the exact Inno marker, copied 1.2.2 payload, and unchanged 1.2.1
  authority are all observed and recorded as boolean evidence.
- Quality scope now includes the stable entry, stable launcher, release-assets
  flow, relevant tests, installer, lifecycle harness, and build inputs.
- Payload asset tests cover `--copy-payload-and-validate` semantics.
- Source archive inputs now explicitly include `stable_launcher.py` and
  `StableLauncher.spec`.

## Completed verification

- Targeted lifecycle/authority/asset/archive/quality tests: pass.
- Full pytest with branch coverage: **941 passed, 2 skipped**, **82.48%**.
- Source archive:
  `release/staging-sprint18.2.2.1-source.zip`
  SHA-256 `E20383A1465B5D1C5937E95B88F1BEBFD66056FF5DBA5AEBEE1B965D6C6D280E`.
  Verification returned zero missing inputs, forbidden entries, content
  mismatches, and duplicate entries.

## Lifecycle evidence status

A fresh replay root, `artifacts/sprint18.2.2/lifecycle-replay-7`, was started
with the current and genuine rollback installers. At this document update it
has retained exact Inno logs through first install, post-copy interruption, and
upgrade. The final lifecycle result and cleanup audit were not yet present, so
this document deliberately does not claim lifecycle completion.

## Remaining completion work

- Wait for or diagnose the replay wrapper until it emits the small validated
  `lifecycle-result.json`; then verify the remaining repair, rollback,
  upgrade-again, uninstall, and zero-residue evidence.
- Rerun final Black/Ruff after the quality-scope import cleanup, privacy/staging
  scans, and before/after formal EXE/real-user-data hash evidence.
