# Architecture Contracts

## Scope

This document records the immutable Sprint 1 public-behavior baseline and the
additive Sprint 2 domain/provider contracts. Sprint 2 does not replace the
legacy runtime path, alter provider behavior, or refactor the dashboard.

## Baseline Version

- Package version: `0.1.0`
- Baseline fixture: `tests/fixtures/sprint1_baseline.json`
- Regression guard: `tests/test_regression_baseline.py`
- Baseline policy: expected values may change only with an approved behavior
  change, an updated test, and an entry in the release notes.

## Public Behavior That Is Frozen

### Research score

- The score keeps the published four-component weighting: technical 30%,
  fundamental 30%, valuation 20%, and risk 20%.
- A complete total score is unavailable when required components are missing.
- The returned result includes available coverage, missing data, strengths,
  weaknesses, and research-only risk notes.

### Backtest execution

- A signal generated on date `T` cannot fill before the next available bar.
- Cash, commission, tax, and slippage remain part of the simulated cash flow.
- Missing next-bar data leaves an order pending rather than manufacturing a
  fill.
- RiskManager rejection remains visible in the result instead of being silently
  ignored.

### Reports

- Research reports include the historical-performance disclaimer.
- Reports warn about survivorship bias when no point-in-time universe is
  provided.
- Reports preserve a trade-log section and show insufficient data when the
  required inputs are unavailable.

### Data integrity

- Price cleaning continues to reject invalid OHLCV input and warns about
  missing data rather than fabricating values.
- Free-provider, cache, uploaded, and sample data must not be presented as the
  same source.

## Sprint 1 Feature-Flag Declaration

`stock_tool.config.DEFAULT_FEATURE_FLAGS` records the migration posture only:

- `legacy_dashboard_enabled=True`
- `research_workspace_enabled=False`

The declaration has no runtime consumers in Sprint 1. Wiring it into UI or
services belongs to later migration work and is explicitly out of scope here.

## Change Control

1. Add or update a focused test before changing a frozen behavior.
2. Run the targeted regression test and the complete pytest suite.
3. Record the intentional baseline delta in release notes.
4. Keep compatibility adapters until the replacement has an approved rollback
   plan.

## Version-Control Prerequisite

Every implementation Sprint requires an immutable source baseline. The current
environment does not expose the `git` executable, so Sprint 1 uses the JSON
fixture, acceptance checklist, and a dated release archive as an interim
guard. The user explicitly authorized Sprint 2 after the Sprint 1.1 archive
and checksum were reverified. Git remains required before a real merge or
public release; the archive is not represented as version-control history.

## Sprint 1 Verification Record

- Targeted sample baseline and market acceptance tests: `2 passed`.
- Complete test suite: `181 passed in 7.98s` on Python 3.11.9.
- Coverage gate: minimum 70%; measured total branch coverage: 70.21%.
- Final source archive:
  `release/baseline/stocktool-sprint1.1-20260710-source.zip`.
- Detached source archive checksum:
  `release/baseline/stocktool-sprint1.1-20260710-source.zip.sha256`.
- EXE SHA-256:
  `4D6125FA55A4D08D3207AA788BD751BAE6EF4E42C111368E72DCDEF14F98EC7E`.

Sprint 1.1 uses the versioned files under `data/sample/` for its golden
research path and records offline symbol contracts for 2330/TWSE,
6488/TPEx, and AAPL/US. The source archive is created only after pytest,
coverage, EXE, smoke, and README verification finish. It is restored to an
isolated staging directory and checked for required files and forbidden
runtime/private paths. Git is not available in this environment and was not
installed; the archive and checksum remain an interim baseline, not a full
replacement for version control.

## Sprint 2 Canonical Domain

The provider-independent models live in `stock_tool.domain.models`:

| Model | Contract |
|---|---|
| `Market` | Canonical `TWSE`, `TPEX`, `US`, `AUTO`, or `CUSTOM` value |
| `Symbol` | Uppercase provider-independent code plus canonical market |
| `MissingDataState` | `missing`, `unknown`, `not_applicable`, or `stale` |
| `MissingData` | Field, explicit state, and non-empty reason |

Known `.TW` and `.TWO` suffixes are removed from canonical `Symbol.code` and
validated against the selected market. Provider-specific query symbols stay
in source metadata instead of leaking into domain identity.

## Sprint 2 Provider Contract

`stock_tool.data.contracts` defines the new boundary:

```text
Untrusted provider payload
  -> canonical cleaner
  -> QualityReport
  -> ProviderResult[data]
       |-> DataSourceMetadata
       |-> ProviderAttemptRecord[]
       |-> warnings[]
       |-> ProviderError or validated data
```

Provider statuses are `success`, `partial`, `empty`, and `error`. Quality
statuses are `not_evaluated`, `empty`, `valid`, `partial`, and `invalid`.
Missing or duplicate required schema is an error; unknown extra columns,
missing optional `adjusted_close`, or rejected rows produce an explicit
partial result. Null `adjusted_close` stays null and is never replaced with
fabricated data.

The contract copies incoming DataFrames before validation and returns a second
deep copy, so quality checks and downstream mutation cannot modify provider
input. `ProviderResult.to_dict()` serializes metadata and quality evidence but
does not embed the raw DataFrame. User-visible provider warnings, fallback
reasons, and error messages use a common redaction policy for credential-like
values, while retaining non-sensitive diagnostic context. Each public contract
dataclass applies its own field-level sanitization at construction time, so
direct construction and legacy adaptation share the same stable, idempotent
`[REDACTED]` marker.

## Sprint 2 Compatibility And Rollback

- `fetch_prices()` and all existing callers remain unchanged.
- `fetch_prices_result()` is additive and default-off through
  `provider_contracts_enabled=False`.
- `LegacyPriceDataProviderAdapter` wraps current file providers without
  changing `PriceDataProvider.load_price_data()`.
- Legacy `FetchResult` can be converted by `adapt_legacy_fetch_result()`;
  source type, requested/resolved symbol, cache path, sanitized warnings, and
  sanitized fallback attempts remain visible.
- Provider exceptions crossing the new local-file adapter are converted to a
  generic typed error; raw exception text is not exposed through the contract.
- Rollback consists of keeping the flag off and removing new consumers. No
  database or stored data requires migration.

Sprint 2 intentionally does not modify cleaner rules or storage schema. The
canonical contract reuses the cleaner, while ingestion runs, repositories,
and provenance persistence remain Sprint 3 work.
