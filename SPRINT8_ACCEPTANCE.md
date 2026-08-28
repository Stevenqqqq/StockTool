# Sprint 8 Acceptance Evidence

Status: **Implementation complete and ready for independent acceptance review.**

## Scope

Sprint 8 adds provider reliability evidence to the existing price-fetch flow.
It does not add a provider, change scoring, backtesting, portfolio, risk,
database migration, AI, or trade-execution behavior.

## Changes

- `src/stock_tool/data/registry.py`
  - Immutable provider capability registry with deterministic compatible order.
  - `yfinance` supports TWSE/TPEX/US; FinMind is declared Taiwan-only and
    credential-requiring. Credentials are never stored in the registry.
- `src/stock_tool/data/policies.py`
  - Bounded, injectable retry/backoff policy; timeout, connection, 408/429/5xx
    retry classifications; permanent HTTP, credential, schema, unsupported,
    and invalid-symbol paths do not retry.
  - Runtime-only Provider Health snapshots retain only safe category, timing,
    failure count, and source/cache state. Restart resets this evidence.
- `src/stock_tool/data/cache.py`
  - Atomic CSV and JSON-sidecar replacement.
  - Explicit `fresh`, `stale`, `expired`, `corrupt`, and `missing` cache states.
  - Sidecar provenance records provider, symbol, market, range, interval,
    fetched time, and last data date. Legacy cache without metadata is stale.
- `src/stock_tool/data/auto_fetch.py` and `contracts.py`
  - Existing `fetch_prices()` now uses the registry and retry policy while
    retaining its public API and legacy contract adapter.
  - `FetchResult` and `DataSourceMetadata` retain actual source, cache state,
    age, fetched time, and last data date. Forced refresh tries online first;
    a stale cache is clearly labelled only when used as fallback.
- `src/stock_tool/dashboard/app.py`, `shell.py`,
  `dashboard/pages/library.py`, and `dashboard/components/data_quality.py`
  - The existing sixth `research library` workspace now renders a Data and
    Evidence Centre. It shows requested and provider query symbols, source,
    provider, dates, rows, quality, cache state, safe attempts, runtime health,
    warnings, next step, and a force-refresh action.
  - No seventh primary navigation item was added. Sample and user-upload
    provenance remains distinct from online/cache provenance.
- `README.md`
  - Documents registry order, cache lifecycle, provenance distinctions, and the
    Data and Evidence Centre.

## Tests Added

- `tests/test_provider_registry.py`: deterministic provider capability order,
  bounded retry, 429 Retry-After, no permanent-HTTP retry, and redaction.
- `tests/test_provider_policies.py`: fresh/stale/expired/corrupt cache states,
  forced online refresh with stale fallback, corrupt-cache rejection, and
  actual online provenance.
- `tests/test_data_evidence_center.py`: safe cache provenance, attempt
  redaction, sample/upload source distinction, and insufficient-data display.

## Verification

| Check | Command or method | Actual result |
| --- | --- | --- |
| Sprint 8 targeted tests | `.venv\\Scripts\\python.exe -m pytest tests/test_provider_registry.py tests/test_provider_policies.py tests/test_data_evidence_center.py -q` | `12 passed` |
| Full test suite | `.venv\\Scripts\\python.exe -m pytest -q` | `418 passed` |
| Branch coverage | `.venv\\Scripts\\python.exe -m pytest --cov=stock_tool --cov-report=term-missing -q` | `79.29%`, above `78.50%` gate |
| Black | `.venv\\Scripts\\python.exe -m black --check` on the 12 Sprint 8 source/test files | Passed |
| Ruff | `.venv\\Scripts\\python.exe -m ruff check` on the same files | `All checks passed!` |
| Mypy | `.venv\\Scripts\\python.exe -m mypy --ignore-missing-imports` on the same 12 files | `Success: no issues found in 12 source files` |

## Release Evidence

- Staging-first build: `cmd /c build_exe.bat`, then required-assets validation,
  isolated smoke, and `publish_release.bat` promotion.
- Public release EXE:
  `release/StockTool/StockTool.exe`
  - Version: `1.1.0`
  - Last write UTC: `2026-07-14T10:50:33.1167399Z`
  - Size: `23,908,026` bytes
  - SHA-256:
    `E9F33C9A223B4852BD6007850CD42AE628AA4D163EFFF887E06371D1317A997E`
- Isolated EXE smoke using `STOCK_TOOL_USER_DATA_DIR`:
  - `/_stcore/health`: HTTP `200`, body `ok` on port `8501`.
  - With `8501` occupied: HTTP `200`, body `ok` on fallback port `8502`.
  - With both `8501` and `8502` occupied: safe exit code `1` and an isolated
    launcher error log.
  - Isolated `reports`, `logs`, and `data/cache` directories were writable.
  - Cleanup completed: zero StockTool processes and zero `8501/8502/8510`
    test listeners remained.
- Release required-assets validation passed. Privacy file-name scan found zero
  `.env`, `secrets*.toml`, `portfolio.csv`, `watchlist.csv`, runtime cache,
  logs, or reports in `release/StockTool`. `.env.example` and sample data are
  allowlisted public assets.

## User Data Integrity

Read-only before/after verification of `%LOCALAPPDATA%\\StockTool`:

- `data/portfolio.csv`: exists, `4` rows, SHA-256
  `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`
  before and after Sprint 8.
- `data/watchlist.csv`: absent before and after Sprint 8.

During promotion, a batch-environment override did not propagate and created a
single migration manifest in the LocalAppData backups directory. The manifest
did not alter portfolio or watchlist data and was removed immediately. All
subsequent EXE smoke runs used an explicitly injected isolated environment.

## Source Archive

- Archive:
  `release/baseline/stocktool-sprint8-20260714-source.zip`
- SHA-256:
  `1F3CA78D15DFE6A37B58D39DE6EB14A50F2F2AB782BAB16A9B576047A8310C0D`
- Sidecar:
  `release/baseline/stocktool-sprint8-20260714-source.zip.sha256`
- Entries: `205`
- Extraction verification: required build inputs missing `0`; forbidden entries
  `0`; archived content mismatches `0`; current workspace mismatches `0`.

## Rollback

The preceding public release was retained under
`release/baseline/stocktool-sprint7.1.1-release-backup-20260714/` before
promotion. Sprint 7.1.1 source baseline remains at
`release/baseline/stocktool-sprint7.1.1-20260714-source.zip` with its existing
SHA-256 sidecar. Runtime user data remains outside the release folder.

## Known Limitations

- Provider Health is runtime-only and deliberately resets after restart.
- Cache TTL values are policy defaults, not Dashboard configuration controls.
- FinMind still requires an externally supplied `FINMIND_TOKEN`; no token is
  stored in source, release, cache metadata, or user-visible errors.
- A launcher wait-timeout message can be written before a slow Streamlit child
  becomes reachable; direct health verification succeeded. This launcher timing
  behavior is recorded for follow-up and was not changed in Sprint 8.
- The Sprint 8 evidence UI was validated by component and integration tests;
  no browser screenshot artifact was added in this scope.

Sprint 9 was not started.
