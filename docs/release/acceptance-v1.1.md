# v1.1 Acceptance Checklist

## Scope

v1.1 is the trusted local research release. This checklist is intentionally
stricter than "the dashboard opens" and should be completed only after Sprints
1 through 6 are finished.

## Sprint 1 Baseline

- [x] `tests/test_regression_baseline.py` passes (`2 passed`).
- [x] The golden path starts from versioned files under `data/sample/`.
- [x] 2330/TWSE, 6488/TPEx, and AAPL/US have deterministic offline symbol
  acceptance records.
- [x] The complete pytest suite passes on Python 3.11.9 (`181 passed in 7.98s`).
- [x] Coverage has an enforced 70% gate; measured total coverage is 70.21%.
- [x] `docs/architecture/contracts.md` matches the active fixture.
- [x] An immutable source/archive baseline and SHA-256 checksum exist.
- [x] Rollback instructions are documented and the archive was restored in an
  isolated non-production staging directory.

### Sprint 1 Evidence

- Source archive: `release/baseline/stocktool-sprint1.1-20260710-source.zip`
- Detached SHA-256 file:
  `release/baseline/stocktool-sprint1.1-20260710-source.zip.sha256`
- EXE SHA-256:
  `4D6125FA55A4D08D3207AA788BD751BAE6EF4E42C111368E72DCDEF14F98EC7E`
- EXE smoke test: `http://localhost:8501` returned HTTP 200; `reports/` was
  writable; release README matched the repository README; `.env.example` and
  sample data were present.
- Git executable: unavailable. It was not installed during Sprint 1.1, so no
  Git merge baseline was created; the release archive is an interim fallback.

### Sprint 1 Known Release Limitation

The current `build_exe.bat` still copies `data/processed` and `data/cache`
into the release directory. This makes the current artifact unsuitable as a
clean public release because runtime data may be included. The limitation is
documented here and intentionally not fixed in Sprint 1; release-data
separation remains a later release-hardening task.

## Sprint 2 Domain And Provider Contracts

- [x] Canonical `Market` and provider-independent `Symbol` models exist.
- [x] `missing`, `unknown`, `not_applicable`, and `stale` serialize explicitly.
- [x] `ProviderResult`, `DataSourceMetadata`, `QualityReport`, attempts, and
  structured errors have stable contracts.
- [x] Success, empty, missing schema, duplicate schema, extra columns, partial
  rows, fallback, and legacy file-provider adapters have deterministic tests.
- [x] Quality validation reuses the existing cleaner, does not mutate input,
  and does not invent `adjusted_close`.
- [x] The new fetch wrapper is additive and default-off; dashboard and CLI use
  the unchanged legacy path.
- [x] Sprint 1.1 golden test, fixture, and sample files match the immutable
  archive byte-for-byte.
- [x] Complete pytest passes on Python 3.11.9 (`217 passed in 8.14s`).
- [x] Coverage gate remains 70%; measured total coverage is 71.39%.
- [x] Sprint 2 changed-file/focused Black, Ruff, and mypy checks pass. This is
  not a claim that the entire repository is lint- and format-clean; pre-existing
  global debt is tracked outside the Sprint 2 scope.
- [x] Final onedir EXE starts and serves HTTP 200.

### Sprint 2 Evidence

- Acceptance: `SPRINT2_ACCEPTANCE.md`
- Source archive: `release/baseline/stocktool-sprint2-20260710-source.zip`
- Detached SHA-256 file:
  `release/baseline/stocktool-sprint2-20260710-source.zip.sha256`
- EXE SHA-256:
  `863B18A17878BCA7B7662A7915B7F2B91858ECC30184D30F4D15AB74E39B4FA2`
- EXE smoke: `http://localhost:8501` returned HTTP 200; `reports/` and
  `logs/` were writable; release README matched the repository README;
  sample data and `.env.example` were present; no StockTool process or
  8501/8502 listener remained after cleanup.

### Sprint 2 Migration Posture

The current environment still has no `git` executable. The user explicitly
authorized Sprint 2 after the immutable Sprint 1.1 source archive was
reverified; Git was not installed by this task. The new contract remains
default-off and has no dashboard, storage migration, or application-service
consumer. Sprint 3 must not be represented as started by this acceptance.

## Product Acceptance

- [ ] A user can search a TWSE, TPEx, or US symbol without first importing a
  file.
- [ ] The first research screen shows company context, score coverage, major
  risks, and source status.
- [ ] Partial data is labeled clearly and offers a usable recovery action.
- [ ] No full score is shown when mandatory score components are unavailable.
- [ ] A backtest keeps the T+1 execution rule and includes configured costs.
- [ ] A report includes sources, data period, parameters, risk disclosures,
  and historical-performance disclaimer.

## Windows Acceptance

- [ ] The onedir release starts from a clean Windows 11 test machine.
- [ ] The launcher selects port 8501 or 8502 and reports a clear failure if
  neither is usable.
- [ ] `reports/`, `logs/`, and the user-data directory are writable.
- [ ] The release contains no real `.env`, API token, personal cache, portfolio,
  or private research document.
- [ ] The EXE, README, sample data, and `.env.example` are present in the
  release layout.

## Required Verification Commands

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-report=term-missing
.\build_exe.bat
Test-Path .\release\StockTool\StockTool.exe
Get-FileHash .\release\StockTool\StockTool.exe -Algorithm SHA256
```

## Release Decision

Release only when all applicable checks are complete, all known High issues are
resolved or explicitly accepted by the release owner, and the rollback package
has been preserved.

## Sprint 6 v1.1.0 Release Candidate

Sprint 6 records the staging-first onedir build, deterministic Research Workspace
integration checks, isolated-runtime smoke tests, privacy scan, source archive,
and rollback evidence in `SPRINT6_ACCEPTANCE.md`. Its implementation status is
`implementation complete and ready for independent acceptance review`; this
checklist does not replace independent acceptance by the product owner and CTO.

The reproducible source package must include only `.streamlit/config.toml` as
Streamlit configuration. Runtime data belongs under `%LOCALAPPDATA%\StockTool`,
not under `release\StockTool`.
