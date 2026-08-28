# Sprint 19.1 — Implementation Evidence — Pending Independent CTO Acceptance

## Status: BLOCKED

This is implementation evidence only. It is not CTO acceptance, release
approval, a promotion, signing authorization, or authorization for Sprint 20.

## Scope and preservation

- Work was restricted to `release/staging-sprint19.1`, `artifacts/sprint19.1`,
  source/tests/docs, and the isolated lifecycle directories below the candidate
  artifact root.
- `release/StockTool/StockTool.exe` SHA-256 after the work remained
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- The final read-only real-user-data snapshot is
  `artifacts/sprint19.1/real-user-data-after.json`: 182 files, 4,680,340 bytes.
  No real-user-data path was used as a test target.
- Final host cleanup: StockTool/StockToolPayload processes 0; listeners 8501/8502
  0; fixed-AppId uninstall entry absent; default installation directory absent.

## Implemented corrections and evidence

### Candidate layout, installer, and manifest

- `release/staging-sprint19.1/StockTool/` contains the stable `StockTool.exe`,
  `current-version.json`, `Payload/StockToolPayload.exe`, and the matching
  `versions/1.2.2/` payload. The staging validator verifies the versioned copy
  byte-for-byte against Payload and preserves the existing privacy boundary.
- `src/stock_tool/release_manifest.py` supports a schema-2 manifest for this
  candidate. It binds stable entry and payload relative path, size, SHA-256 and
  `side-by-side-v1` layout, while retaining schema-1 verification for old
  artifacts. Tampered staging metadata or a changed payload fails closed.
- `artifacts/sprint19.1/installer/StockTool-Setup-1.2.2-internal-test.exe`:
  75,199,077 bytes; SHA-256
  `D502879E6D44C67B1AA68F91C66E9B85413206E261FAA1B05DFA0997C33BA4C0`;
  Authenticode `NotSigned`; FileVersion/ProductVersion 1.2.2.
- `artifacts/sprint19.1/installer/update_manifest.json` was revalidated against
  this installer, the preserved genuine rollback installer, and the actual
  19.1 staging directory.
- Preserved genuine v1.2.1 rollback installer:
  `artifacts/sprint18.2.2/rollback-installer/StockTool-Setup-1.2.1-internal-test.exe`,
  SHA-256 `C6FE8F9A3B203C48D5A51974401B4287B7FF9D110D4FB3C08734FE2CFDEC96C0`.

### Fresh lifecycle replay

- New evidence is at
  `artifacts/sprint19.1/lifecycle-replay-2/lifecycle-result.json`, not Replay 7.
- Result: `passed`, 19,051 bytes, 17 commands, 5 authority/version-directory
  snapshots, and cleanup all true.
- Exact Inno logs are retained for first install 1.2.1, post-copy/pre-switch
  interruption, upgrade, repair, upgrade-again, and uninstall.
- The post-copy interruption evidence records the expected marker, completed
  payload copy, and unchanged authority before stable-entry health recovery.
- Stable-entry candidate smoke also succeeded with an isolated
  `STOCK_TOOL_USER_DATA_DIR`: `--version` 1.2.2 and health `200/ok` on 8501;
  cleanup left no process or listener.

### Product/readiness code

- Empty OHLC rows are discarded before the Vega candlestick layer is constructed,
  preventing the empty-layer infinite-extent warning without inventing chart
  data.
- `PRIVACY.md` now distinguishes market-data fields from explicitly triggered
  external-AI EvidenceBundle use and explicitly excludes private-document
  content/paths and local-rule calls.
- `scripts/generate_sbom.py` generates a valid UUID CycloneDX 1.5 SBOM from the
  installed closure of `pyproject.toml` runtime dependencies, excluding arbitrary
  developer/audit packages in the virtual environment.
- `quality_gate.py` is now scoped as Sprint 19.1 and includes the new release,
  security, performance, E2E, stable-entry, chart, SBOM, and document files;
  it includes no build, publish, network, or real-user-data step.

## Verification completed

- Relevant targeted pytest: pass (installer/manifest, stable entry/launcher,
  security readiness, research chart/workspace, quality-gate, performance
  contracts).
- Full pytest: `957 passed, 2 skipped, 2 warnings`, exit 0.
- Branch coverage: `82.54%`, above the configured 78.50% gate, exit 0.
- Black check, Ruff, focused mypy, and compileall: exit 0.
- Staging privacy validation: pass.
- Source archive:
  `release/staging-sprint19.1-source.zip`, SHA-256
  `0077DD6E8CE30ACD19647877CD7F83F5FCBE645B2C16C99E3B2B12E9274BE77F`.
  Verification reported missing required inputs 0, forbidden entries 0, content
  mismatches 0, duplicate entries 0.
- Runtime-closure artifacts:
  `artifacts/sprint19.1/security/stocktool-runtime-sbom.cdx.json`,
  `runtime-closure-requirements.txt`, and `pip-audit-runtime-closure.json`.

## Blocking and incomplete evidence

1. `pip-audit` for the actual runtime closure exited 1 and reported 28 known
   vulnerabilities across 2 packages. No dependency upgrade was performed:
   the authorization permitted only installing pip-audit in `.venv`, not
   runtime dependency changes. This is a release-readiness blocker.
2. Browser-driven candidate E2E evidence for keyboard navigation, all requested
   zoom levels, three-market online/offline cache behavior, screenshots, DOM and
   console capture was not completed in this correction. Streamlit/fixture
   coverage is not represented as that browser evidence.
3. A three-run performance hard-gate report covering indicators, export, cached
   workflow, allocation, and baseline-regression thresholds was not completed.
   `artifacts/sprint19.1/performance-entry-baseline.json` is only an entry
   timing baseline and must not be used as the requested hard-gate result.
4. The aggregate quality-gate wrapper was started but exceeded the command host
   time limit before it could emit one combined result. Its constituent targeted,
   full, coverage, Black, Ruff, mypy, compileall, privacy/layout and archive
   checks above were run separately where recorded; this does not substitute for
   the blocked security or incomplete browser/performance gates.

## Files changed for this correction

- `src/stock_tool/installer_build.py`
- `src/stock_tool/release_manifest.py`
- `src/stock_tool/quality_gate.py`
- `src/stock_tool/dashboard/components/research_chart.py`
- `installer/StockTool.iss`, `installer/update_manifest.json`
- `scripts/verify_installer_lifecycle.ps1`, `scripts/generate_sbom.py`
- `PRIVACY.md`
- `tests/test_installer_manifest.py`, `tests/test_quality_gate.py`,
  `tests/test_research_workspace.py`, `tests/security/test_release_readiness.py`

No signing, release publication, promotion, formal-release overwrite, Git reset,
Git clean, commit, push, pull request, Sprint 20 work, or CTO acceptance was
performed.
