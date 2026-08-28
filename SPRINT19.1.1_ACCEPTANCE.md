# Sprint 19.1.1 — Implementation Evidence — Pending Independent CTO Acceptance

## Status: BLOCKED

This document records implementation evidence only. It is not CTO acceptance,
release approval, signing authorization, promotion, or authorization for
Sprint 20.

## Scope and preservation

- Only project `.venv`, source/tests/docs, `release/staging-sprint19.1.1`, and
  `artifacts/sprint19.1.1` were used for this correction.
- No formal `release/StockTool` content was overwritten. Formal EXE SHA-256 was
  identical before/after:
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- Read-only snapshots `artifacts/sprint19.1.1/preservation-before.json` and
  `preservation-after.json` compare identical for all real-user-data files:
  182 files and 4,680,340 bytes.
- Existing genuine v1.2.1 rollback installer was preserved unchanged:
  `artifacts/sprint18.2.2/rollback-installer/StockTool-Setup-1.2.1-internal-test.exe`,
  SHA-256 `C6FE8F9A3B203C48D5A51974401B4287B7FF9D110D4FB3C08734FE2CFDEC96C0`.
- Final cleanup was zero StockTool/StockToolPayload processes, zero 8501/8502
  listeners, no fixed-AppId uninstall entry, and no default StockTool install.

## Dependency remediation

Commands executed in the project `.venv` only:

```text
.venv\Scripts\python.exe -m pip install "GitPython>=3.1.55,<4" "Pillow>=12.3.0,<13"
.venv\Scripts\python.exe -m pip check
```

- GitPython changed from 3.1.50 to 3.1.57.
- Pillow changed from 12.2.0 to 12.3.0.
- No other runtime package was requested for upgrade; `pip check` exit 0.
- Reproducible build constraints are in
  `requirements/stocktool-runtime-constraints.txt`; `build_exe.bat` supplies
  that file to its editable build dependency install.
- Runtime closure evidence:
  `artifacts/sprint19.1.1/security/stocktool-runtime-sbom.cdx.json`,
  `runtime-closure-requirements.txt`, and `pip-audit-runtime-closure.json`.
  `pip-audit` exit 0, zero known vulnerabilities; no ignore/skip/allowlist was used.

## Candidate build, manifest, and smoke

- `build_exe.bat` with `STOCK_TOOL_STAGING_PARENT=release/staging-sprint19.1.1`
  exited 0 and produced the side-by-side candidate layout.
- Stable entry SHA-256:
  `F22118A584A7AB353372136D2C42B66E2D89CCD204CC25D5D992DA252E45F0D8`.
- Payload SHA-256:
  `0A5C40F9E2BC5F4C96B2B48D10FBEEFAAC9E9E5A436ED8A6DAB9B725891FDC25`.
- Candidate installer:
  `artifacts/sprint19.1.1/installer/StockTool-Setup-1.2.2-internal-test.exe`,
  75,213,175 bytes, SHA-256
  `AA6137AE7E186E85E000A19AB4627B54F3AA8489F315D64805ABE88B997EA5E6`,
  Authenticode `NotSigned`.
- `update_manifest.json` was revalidated against the actual current installer,
  preserved rollback installer, stable entry/payload staging hashes, sizes and
  side-by-side authority layout.
- Isolated stable-entry smoke reached `--version` 1.2.2 and health `200/ok`.

## Fresh installer lifecycle evidence

- New replay, not reused from 19.1:
  `artifacts/sprint19.1.1/lifecycle-replay-2/lifecycle-result.json`.
- Result: `passed`, 19,106 bytes, 17 commands and 5 snapshots.
- The replay covers first install 1.2.1, stable health, payload-copied/
  authority-unchanged interruption, recovery on 1.2.1, upgrade 1.2.2, repair,
  rollback 1.2.1, upgrade again, uninstall and cleanup.
- Exact Inno logs are retained in that replay root. Cleanup reports registry
  absent, program directory absent, StockTool process count 0, listener count 0,
  and isolated sentinel retained.

## Quality and archive evidence

- Targeted pytest after the Optional assertion correction: exit 0.
- Full quality wrapper: `quality_gate.bat` exit 0, recorded in
  `artifacts/sprint19.1.1/quality-gate-final.stdout.log` and
  `quality-gate-final.exitcode.txt`.
- Wrapper results: full pytest `957 passed, 2 skipped, 2 warnings`; branch
  coverage `82.50%` (configured gate 78.50%); Black, Ruff, focused mypy,
  compileall, privacy scan, release-layout, and regression baseline all passed.
- `git diff --check`: exit 0.
- Source archive:
  `release/staging-sprint19.1.1-source.zip`, SHA-256
  `855CAEF3AB6AD0ACF853738032EE598F11341BD13EFF7291524DF5AF1193701D`.
  Independent extraction verification: missing 0, forbidden 0, mismatches 0,
  duplicate entries 0.

## Performance hard gate

`scripts/measure_performance.py` executes every fixed workload three times and
writes `artifacts/sprint19.1.1/performance-result.json` with every duration,
median, maximum, threshold, allocation peak and pass/fail status.

- Indicators + scoring: max 0.347s / threshold 2s, pass.
- Excel export: max 5.004s / threshold 5s, **fail**.
- Cached research: max 0.008s / threshold 5s, pass.
- Portfolio allocation/risk: max 0.121s / threshold 1s, pass.
- Candidate EXE health: max 3.356s / threshold 5s, pass.
- Allocation peak: 12,092,373 bytes / threshold 536,870,912 bytes, pass.

The threshold was not changed after measurement. This single real overrun keeps
the performance hard gate blocked. The Sprint 19.1 entry baseline was a pytest
duration baseline, not an EXE-health baseline; it cannot substantiate the
requested health median comparison and is also BLOCKED for that reason.

## Browser acceptance

- Candidate EXE was opened with isolated user-data. Health was `200/ok`.
- 1280×720 screenshot and DOM snapshot are retained at
  `artifacts/sprint19.1.1/browser/home-1280x720.png` and `home.dom.txt`.
- An active-page console sample was empty before teardown. The retained final
  `console.json` also records expected Streamlit health-request errors after
  the candidate process was deliberately stopped; it contains no Vega
  `Infinite extent` message. It is not sufficient to certify a clean complete
  browser journey.
- `navigation-attempt.json` records an actual keyboard attempt on the visible
  primary navigation. The browser control surface left `研究首頁` selected after
  ArrowDown; it did not demonstrate the required six-entry keyboard activation.

Therefore 125%/150% zoom, complete six-entry Tab/Shift+Tab/Enter/Space/arrow
proof, three-market online-first/offline-cache/partial-failure proof, and their
complete screenshot/DOM/console series are **not complete**. They are not
replaced by unit or Streamlit tests.

## Files changed

- `requirements/stocktool-runtime-constraints.txt`
- `build_exe.bat`
- `src/stock_tool/release_archive.py`
- `src/stock_tool/quality_gate.py`
- `scripts/measure_performance.py`
- `scripts/verify_installer_lifecycle.ps1`
- `tests/test_research_workspace.py`
- `tests/test_release_archive.py`
- `tests/test_quality_gate.py`
- `tests/test_installer_manifest.py`
- `tests/performance/test_large_dataset.py`

No signing, publication, promotion, formal-release overwrite, real-user-data
mutation, Git reset/clean/init, commit, push, PR, CTO acceptance, or Sprint 20
work was performed.
