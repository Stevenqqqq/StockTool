# Sprint 18.2.2.1.1 packaging closure — implementation evidence

Status: implementation evidence only. This is not CTO acceptance, Sprint 18
completion, release approval, signing, publication, promotion, or authorization
for Sprint 18.3/Sprint 19.

## Scoped change

Only `src/stock_tool/installer_build.py` was reformatted with Black. No product
logic, installer lifecycle structure, stable authority behavior, release build,
candidate artifact, manifest, stable launcher, payload, or lifecycle harness was
changed in this closure.

## Quality gate

`quality_gate.bat` was restarted from the beginning after the Black format and
completed with exit code 0. Its retained output is
`artifacts/sprint18.2.2/quality-gate-18.2.2.1.1-run2.stdout.log`.

| Step | Result |
| --- | --- |
| targeted pytest | pass |
| full pytest | pass |
| branch coverage | 82.43% (gate 78.50%) |
| Black | pass |
| Ruff | pass |
| focused mypy | pass |
| compile | pass |
| privacy | 0 violations |
| release layout | pass |
| regression baseline | pass |

The gate reports 941 passed, 2 skipped for the coverage execution.

## Replay 7 evidence

Existing verified Replay 7 is retained without re-running host lifecycle:

- `artifacts/sprint18.2.2/lifecycle-replay-7/lifecycle-result.json`
- size: **19,108 bytes**
- status: **passed**
- commands: **17**
- snapshots: **5**
- cleanup: registry absent, StockTool process count 0, 8501/8502 listener count
  0, program directory absent, user-data sentinel present.

No candidate/lifecycle-affecting file was changed by this packaging-only closure,
so the existing replay remains applicable.

## Final source archive

- archive: `release/staging-sprint18.2.2.1-source.zip`
- SHA-256: `83C71DCE486A60CF7E67ADAB6C07DF37011CB9FEE77EB1CC07015832259B7345`
- sidecar: `release/staging-sprint18.2.2.1-source.zip.sha256`
- missing required inputs: 0
- forbidden entries: 0
- content mismatches: 0
- duplicate entries: 0
- workspace missing: 0
- workspace mismatches: 0
- required inputs include `stable_launcher.py` and `StableLauncher.spec`.

## Artifact and preservation checks

| Item | SHA-256 |
| --- | --- |
| current 1.2.2 installer | `5AEECFAA3199471F1C855A5CA25E46428DF69AF5C8CBDB1749CFCF72E529CB55` |
| rollback 1.2.1 installer | `C6FE8F9A3B203C48D5A51974401B4287B7FF9D110D4FB3C08734FE2CFDEC96C0` |
| formal `release/StockTool/StockTool.exe` | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

The pre-existing true-user-data baseline still matches: one existing StockTool
user-data file, `portfolio.csv`, SHA-256
`A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`;
no baseline differences were found.

Final zero-residue check: `StockTool`/`StockToolPayload` processes 0,
8501/8502 listeners 0, fixed-AppId uninstall registry absent, and the default
`%LOCALAPPDATA%\Programs\StockTool` directory absent.
