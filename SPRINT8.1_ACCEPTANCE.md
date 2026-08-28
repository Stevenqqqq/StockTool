# Sprint 8.1 Acceptance Evidence

Status: Implementation complete and ready for independent acceptance review.

## Scope

Sprint 8.1 repairs the legacy **自動抓資料** Dashboard route so it preserves the
Sprint 8 provider-health and data-evidence contract. No Sprint 9 work was
started. This patch does not alter providers, scoring, backtesting, portfolio,
risk, AI, schema, or trading logic.

## Root Cause And Fix

`_page_auto_fetch()` previously called `fetch_prices()` without the session
`ProviderHealthTracker`, then reconstructed only a subset of provenance from a
`from_cache` boolean. As a result, the legacy route could discard the actual
provider, query symbol, timestamps, cache metadata, attempts, and row count;
it could also label the source incorrectly.

The route now:

- passes `st.session_state.get("provider_health_tracker")` into `fetch_prices()`;
- passes the actual `FetchResult` evidence through `_set_price_data()`:
  `source_type`, `provider`, user/query symbol, market, date range,
  `cache_file`, `fetched_at`, `last_data_date`, `cache_state`,
  `cache_age_seconds`, attempts, and row count;
- uses `result.source_type` directly rather than inferring source type from
  `from_cache`;
- applies existing provider-text redaction when displaying warnings, attempts,
  and exceptions.

Existing download, SQLite persistence, error handling, and page flow remain in
place.

## Modified Files

- `src/stock_tool/dashboard/app.py`
- `tests/test_sprint81_auto_fetch_evidence.py` (new)
- `SPRINT8.1_ACCEPTANCE.md` (this evidence document)

## Regression Coverage

`tests/test_sprint81_auto_fetch_evidence.py` uses a fake Streamlit surface and
a mocked `fetch_prices()` result; it does not use the network, real cache,
SQLite runtime data, portfolio, or watchlist.

It verifies:

- the session `ProviderHealthTracker` is forwarded to `fetch_prices()`;
- all Sprint 8 evidence fields are retained in session state;
- the evidence-center model exposes provider, query symbol, fetch time, last
  data date, cache state, row count, and attempts;
- provider health represents success, timeout/failure, and unknown states;
- warning and attempt diagnostics redact API-key and token values.

## Validation Results

### Targeted Tests

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' tests/test_sprint81_auto_fetch_evidence.py tests/test_provider_registry.py tests/test_provider_policies.py tests/test_data_evidence_center.py -q
```

Result: `14 passed in 2.15s`.

### Full Test Suite And Coverage

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' --cov=stock_tool --cov-branch --cov-report=term-missing
```

Result: `420 passed in 50.80s`.

Branch coverage: `79.80%` (required gate: `78.50%`).

### Focused Quality Checks

Commands:

```powershell
.\.venv\Scripts\python.exe -m black --check src/stock_tool/dashboard/app.py tests/test_sprint81_auto_fetch_evidence.py
.\.venv\Scripts\python.exe -m ruff check src/stock_tool/dashboard/app.py tests/test_sprint81_auto_fetch_evidence.py
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src/stock_tool/dashboard/app.py tests/test_sprint81_auto_fetch_evidence.py
```

Results:

- Black: `All done! 2 files would be left unchanged.`
- Ruff: `All checks passed!`
- mypy: `Success: no issues found in 2 source files`

## EXE Build And Smoke Test

`build_exe.bat` rebuilt a staging onedir package, passed staging validation,
then `publish_release.bat` promoted it only after required-asset and privacy
checks. Promotion used an isolated `STOCK_TOOL_USER_DATA_DIR`; no real user
data was used for migration validation.

- EXE: `release\\StockTool\\StockTool.exe`
- Last write: `2026-07-14 19:31:35 +08:00`
- Size: `23,908,273` bytes
- SHA-256: `805B0A0A399C30F9C78DBB673225DE6F91E5957C4C81B0AED726CBC310FB7B50`
- `StockTool.exe --version`: `1.1.0`
- Health smoke: 8501 returned HTTP 200 with body `ok`.
- Fallback smoke: with 8501 occupied, 8502 returned HTTP 200 with body `ok`.
- Isolated `reports`, `logs`, and `data\\cache` write checks: passed.
- Post-smoke cleanup: no `StockTool.exe` process and no listener on 8501, 8502,
  or 8510.

## Release Privacy Scan

- Required public release assets: passed.
- Forbidden release runtime/private entries (`.env`, Streamlit secrets,
  `portfolio.csv`, `watchlist.csv`, `logs`, `reports`, and runtime `cache`): 0.
- Known secret regression markers: 0.
- The release packaging rule continues to include only
  `.streamlit/config.toml`, not the full `.streamlit` directory.

## User Data Integrity

Only read-only checks were performed against `%LOCALAPPDATA%\\StockTool`.

| File | Before | After |
| --- | --- | --- |
| `data\\portfolio.csv` | 4 rows; `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` | 4 rows; `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `data\\watchlist.csv` | absent | absent |

## Source Archive

- Archive: `release\\baseline\\stocktool-sprint8.1-20260714-source.zip`
- Sidecar: `release\\baseline\\stocktool-sprint8.1-20260714-source.zip.sha256`
- Size: `2,134,359` bytes
- Entries: `206`
- SHA-256: `5E856AABDBF4BE2EB699657DC6C1FD31D0EB569C51251371A72507CC862E7FBE`
- Sidecar matches the ZIP SHA-256: passed.
- Extraction verification: required build inputs missing `0`; forbidden entries
  `0`; archived content mismatches `0`.

## Known Limitations

- Provider availability and live-data freshness remain dependent on external
  sources; this Sprint only preserves their factual result metadata.
- UI regression tests use controlled provider responses. They do not make the
  release acceptance dependent on live network access.
- This implementation is ready for independent acceptance review; it does not
  constitute a declaration that Sprint 8.1 has been independently accepted.
