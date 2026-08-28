# Sprint 15.1 Acceptance Record

**Status:** Implementation complete and ready for independent CTO acceptance review.

## Scope

Sprint 15.1 is a corrective patch for Portfolio Risk v2, the local quality gate, and the Windows launcher. It does not change scoring, backtesting, provider contracts, trading semantics, portfolio valuation formulas, or the formal `release\StockTool` product.

## Root Causes and Fixes

### Portfolio Risk scenarios

Sprint 15 only exposed deterministic price/FX scenarios. It had no explicit contract for volatility or interest-rate shocks, so a later caller could have been tempted to infer beta, duration, or interest sensitivity.

`PortfolioRiskService` now returns two additional `EvidenceStressResult` entries: `volatility_spike` and `interest_rate_shock`. Each is `available` only when every valued `(symbol, market)` has one explicit, finite `shock_pct`, `sensitivity`, and `source` record. Missing, duplicate, invalid, or incomplete evidence returns structured `unknown` with `MissingData`; the service never invents beta, duration, rate sensitivity, or a substitute parameter. Existing all-holdings, largest-holding, market-decline, and USD/TWD scenarios remain unchanged. Every scenario states that it is a deterministic assumption, not a forecast, VaR estimate, or trading instruction.

### Per-holding price dates

The previous `data_as_of` implementation selected the maximum date in all matched price rows. This could report current data when one holding was stale or missing.

`PriceDataStatus` now records each market-qualified holding's last price date, missing identities, and stale identities. `PortfolioRiskResult.data_as_of` is the oldest last-available price date among current holdings. Any missing holding produces `partial` or `unknown`, and any stale holding is explicit; it is not presented as a complete latest portfolio view.

### Classification conflicts

The prior classification index sorted sources and silently selected the first record. It now aggregates explicit source-backed values per `(symbol, market)`. A unique value is usable; multiple sector or industry values become `conflict` evidence, are excluded from classified weights, and create structured `unknown` missing data. The dashboard renders the conflicting identity and source list rather than choosing a winner. There is no new source-priority, `available_at`, or inference policy in this Sprint.

### Content-aware quality gate

The existing source privacy scan only examined forbidden filenames. It now also scans archive-candidate production/configuration text for non-placeholder API-key/token/password/secret assignments, authorization credentials, and URLs embedding credentials. Findings contain only `path:line:category`, never the matched value. Empty or template values in `.env.example` are allowed. Regression tests inject a fake secret into an isolated temporary source tree and verify fail-closed behavior without exposing the value.

### IPv4 loopback consistency

`launcher.py` previously used `localhost` for probing, bind, readiness, and browser URLs. Windows can resolve that name differently across IPv4/IPv6. The launcher now consistently uses explicit `127.0.0.1` for the port probe, Streamlit bind address, health endpoint, and browser URL. The health request continues to bypass proxies. Regression tests cover normal selection, IPv4 busy fallback to `8502`, and an IPv6-only `::1:8501` listener that must not be mistaken for the IPv4 service.

## Modified Files

- `src/stock_tool/application/portfolio_risk.py`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/quality_gate.py`
- `launcher.py`
- `tests/test_portfolio_risk.py`
- `tests/test_portfolio_risk_ui.py` (new isolated Streamlit `AppTest`)
- `tests/test_quality_gate.py`
- `tests/test_launcher.py`
- `tests/test_sprint91_evidence_safety.py` (updates the established launcher URL expectation to the new explicit IPv4 contract)

## Tests and Quality Checks

Commands were executed from the project root with `.venv\Scripts\python.exe` on Python 3.11.9.

| Check | Actual result |
| --- | --- |
| Sprint 15.1 targeted suite | `94 passed` |
| Full pytest | `661 passed` |
| Branch coverage | `81.74%` (gate `78.50%`) |
| Fail-closed `quality_gate.bat` | Passed, including source privacy scan and release-layout validation |
| Black | Passed for the explicit 12-file Sprint 15.1 changed-file scope |
| Ruff | Passed for the same explicit scope |
| Focused mypy | Passed: manual Sprint 15.1 scope reported `Success: no issues found in 9 source files`; the fixed quality-gate scope (which also retains the release-archive checks) reported `Success: no issues found in 11 source files`. |
| `compileall` | Passed: `python -m compileall -q src` |

Focused quality commands:

```powershell
.\.venv\Scripts\python.exe -m black --check src/stock_tool/application/portfolio_risk.py src/stock_tool/quality_gate.py src/stock_tool/dashboard/app.py launcher.py tests/test_portfolio_risk.py tests/test_portfolio_risk_ui.py tests/test_quality_gate.py tests/test_launcher.py tests/test_sprint91_evidence_safety.py
.\.venv\Scripts\python.exe -m ruff check src/stock_tool/application/portfolio_risk.py src/stock_tool/quality_gate.py src/stock_tool/dashboard/app.py launcher.py tests/test_portfolio_risk.py tests/test_portfolio_risk_ui.py tests/test_quality_gate.py tests/test_launcher.py tests/test_sprint91_evidence_safety.py
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src/stock_tool/application/portfolio_risk.py src/stock_tool/quality_gate.py src/stock_tool/dashboard/app.py launcher.py tests/test_portfolio_risk.py tests/test_portfolio_risk_ui.py tests/test_quality_gate.py tests/test_launcher.py tests/test_sprint91_evidence_safety.py
```

The new isolated AppTest renders the Portfolio Risk Center with concentration, market/currency/industry exposure, a structured unknown factor state, stale price warning, and deterministic-scenario disclaimer. It uses a temporary `STOCK_TOOL_USER_DATA_DIR` and does not access real user data.

## Staging EXE and Smoke Results

The staging-only build completed. Formal `release\StockTool` was not promoted or modified.

| Artifact | Value |
| --- | --- |
| Staging EXE | `release\staging\StockTool\StockTool.exe` |
| Size | `24,145,141` bytes |
| Modified UTC | `2026-07-26T05:32:21.6036354Z` |
| SHA-256 | `9616A70EB92CDAA45F8BACABB405E517480EE55DBDAD425E90A1763501509EFF` |
| Formal release EXE SHA-256 | `1FD70CB3610C7F1CAE64E7D16B082556E5D879C94B10E9F8F35CB88B18B2EBC4` (unchanged) |

All EXE checks used new isolated `%TEMP%\stocktool-sprint151-*` `STOCK_TOOL_USER_DATA_DIR` locations:

- Normal launch: `http://127.0.0.1:8501/_stcore/health` returned `200` / `ok`; homepage returned HTTP `200`.
- IPv4 busy port: a temporary `127.0.0.1:8501` holder caused the launcher to select `8502`; health returned `200` / `ok`.
- IPv6 busy port: an IPv6-only `::1:8501` holder did not interfere with the IPv4 strategy; `127.0.0.1:8501` health returned `200` / `ok`.
- `reports`, `logs`, and `data\cache` were writable inside the isolated runtime.
- All smoke-test `StockTool` processes and `8501`/`8502` listeners were closed. The verified direct `%TEMP%` child directories were removed.

## Privacy and User-Data Integrity

The staging release privacy scan reported `forbidden_count=0`: no `.env`, `secrets*.toml`, credential-bearing text, portfolio/watchlist CSV, `stock_data.sqlite`, reports, logs, or runtime cache were packaged.

The new content-aware project scan also completed with `privacy violations: 0`. It scans production/configuration archive candidates; regression test fixture text remains isolated under `tests/` and is exercised separately by a temporary non-test source tree.

Real user data was read only before and after all validation:

| Path | Before / after |
| --- | --- |
| `%LOCALAPPDATA%\StockTool\data\portfolio.csv` | Exists; 4 rows; 131 bytes; `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `%LOCALAPPDATA%\StockTool\data\watchlist.csv` | Absent |
| `%LOCALAPPDATA%\StockTool\data\processed\stock_data.sqlite` | Exists; 339,968 bytes; `2A2FA20A7A6F01FA3B22A942B82D6056A70755824FEF4FF6E8176ED24317CDF7` |
| `%LOCALAPPDATA%\StockTool\settings.json` | Absent |

Existence states, sizes, row count, modified timestamps, and SHA-256 values were unchanged.

## Source Archive

| Artifact | Value |
| --- | --- |
| Source archive | `release\baseline\stocktool-sprint15.1-20260726-source.zip` |
| Size | `2,317,789` bytes |
| Entries | `268` |
| SHA-256 | `91FE6159E8E0683FEAC30927B90174531EF397DA91C70EE374E38E8A6064B00A` |
| Sidecar | `release\baseline\stocktool-sprint15.1-20260726-source.zip.sha256` |

`verify_source_archive(archive_path=..., extracted_root=...)` completed with `missing_required_inputs=0`, `forbidden_entries=0`, and `content_mismatches=0`. The SHA-256 sidecar matches the ZIP.

## Known Limitations

- Volatility and interest-rate stress remain unavailable unless an approved caller supplies explicit market-qualified sensitivity evidence; no stock parameter is inferred.
- Classification conflicts remain unresolved until an explicit source-priority or time-validity policy is approved.
- The content scanner is a conservative local quality control, not a complete DLP system; it reports only paths, line numbers, and categories.
- The formal release has not been promoted. Rollback remains the unchanged formal `release\StockTool` artifact and its existing rollback baselines.
- Git metadata is unavailable in this workspace; no Git installation or repository initialization was attempted.

No Sprint 16 work was started.
