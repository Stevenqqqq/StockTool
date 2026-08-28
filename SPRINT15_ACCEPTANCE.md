# Sprint 15 Acceptance Record

**Status:** Implementation complete and ready for independent CTO acceptance review.

## Scope

Sprint 15 delivers Portfolio Risk v2 as one deterministic, serializable application contract, and adds a local fail-closed quality gate. It does not change scoring, trading semantics, backtesting, providers, portfolio valuation formulas, ledger accounting formulas, or the formal `release\StockTool` release.

## Implementation

### Modified and added files

- `src/stock_tool/application/portfolio_risk.py` (new): bounded `PortfolioRiskService` and serializable result contract.
- `src/stock_tool/dashboard/app.py`: renders the Portfolio Risk v2 summary within the existing portfolio management workflow and reads only already-cached company classification evidence.
- `src/stock_tool/quality_gate.py` (new): local, deterministic, fail-closed validation sequence.
- `quality_gate.bat` (new): Windows entrypoint for the local gate.
- `src/stock_tool/release_archive.py`: includes `quality_gate.bat` in the explicit source archive allowlist.
- `tests/test_portfolio_risk.py` (new), `tests/test_quality_gate.py` (new), `tests/test_dashboard.py`, `tests/test_release_archive.py`.

### Portfolio Risk v2 contract

`PortfolioRiskService.assess()` composes caller-provided `PortfolioValuationResult`, `PortfolioHealthResult`, optional `LedgerSnapshot`, market-qualified prices, and explicit company-research classification rows. It returns immutable `PortfolioRiskResult` data with:

- total market value, realized and unrealized P&L when supported by existing evidence;
- position and top-three concentration;
- market and currency exposure;
- sector and industry exposure only where the exact `(symbol, market)` has a source-backed classification;
- explicit unclassified weight without re-normalizing the classified subset;
- factor exposure as `unknown` when no evidence-backed factor model exists;
- deterministic stress scenarios: all holdings `-10%` / `-20%`, largest holding `-25%`, TWSE/TPEX/US `-15%`, and USD/TWD `+/-5%` / `+/-10%`;
- coverage, structured missing data, sanitized warnings, assumptions, provenance/evidence, calculation time, and latest applicable price date.

The service reuses `PortfolioStressService`; it does not recalculate stress formulas. It does not mutate the input portfolio, prices, valuation, ledger snapshot, or health result. Sensitive warning text is passed through the existing provider-text sanitizer before serialization.

### UI integration

The existing portfolio workflow now renders **投資組合風險中心** before the pre-existing detailed valuation and interactive stress controls. It presents concentration, coverage, exposure, missing-data state, evidence-backed classification state, and the deterministic preset stresses. The dashboard classification bridge consumes only cached company research profiles with explicit source metadata; it does not infer sector or industry from ticker/name and does not issue a network request.

The existing Serenity entrypoint and the six-workspace navigation remain unchanged. The pre-existing dashboard/AppTest and Serenity regression suite are included in the Sprint 15 quality gate.

### Local quality gate

`quality_gate.bat` invokes `python -m stock_tool.quality_gate`. Its fixed, fail-closed order is:

1. Sprint 15 targeted tests.
2. Full pytest.
3. Branch coverage gate from `pyproject.toml` (`>=78.50%`).
4. Black and Ruff over the explicit Sprint 15 changed-file scope.
5. Focused mypy.
6. `compileall`.
7. Source-allowlist privacy scan.
8. Public release-source asset validation.
9. Dashboard shell, Serenity, and ledger regression baseline.

It intentionally has no build, publish, Git, or network step. The project has existing unrelated whole-project Black debt (31 files in the observed check); the gate records its formatting/lint scope explicitly rather than hiding that debt or reformatting unrelated modules.

## Tests and quality checks

Executed from the project root using `.venv\Scripts\python.exe`.

| Check | Actual result |
| --- | --- |
| `cmd /c quality_gate.bat` | Passed, fail-closed sequence completed. |
| Sprint 15 targeted suite | Passed via the quality gate: risk, quality gate, portfolio health, valuation, analytics, dashboard, shell, and Serenity regression tests. |
| Full pytest | `651 passed` |
| Branch coverage | `81.48%` (gate `78.50%`) |
| Black | Passed for the explicit eight-file Sprint 15 scope. |
| Ruff | Passed for the explicit eight-file Sprint 15 scope. |
| Focused mypy | `Success: no issues found in 7 source files` |
| Python compile | Passed (`python -m compileall -q src`). |
| Source privacy/release-layout checks | Passed: `privacy violations: 0`; public release source assets valid. |

Focused mypy command:

```powershell
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports `
  src/stock_tool/application/portfolio_risk.py `
  src/stock_tool/quality_gate.py `
  src/stock_tool/dashboard/app.py `
  src/stock_tool/release_archive.py `
  tests/test_portfolio_risk.py `
  tests/test_quality_gate.py `
  tests/test_release_archive.py
```

The new regression coverage includes market-qualified identity isolation, incomplete price/FX refusal without weight re-normalization, deterministic stress output without valuation mutation, source-backed classification only, factor unknown state, warning redaction, ledger realized P&L with explicit FX evidence, and quality-gate fail-closed behavior.

## Staging EXE verification

`build_exe.bat` completed using the staging-first process. The formal release was not changed.

| Artifact | Value |
| --- | --- |
| Staging EXE | `release\staging\StockTool\StockTool.exe` |
| Size | `24,137,830` bytes |
| Modified UTC | `2026-07-26T04:37:54.3692004Z` |
| SHA-256 | `CD0353E6D699501C90DD86708B73AD353F7558DE2F07BE0F76EFC4B2E082F513` |
| Formal release EXE SHA-256 | `1FD70CB3610C7F1CAE64E7D16B082556E5D879C94B10E9F8F35CB88B18B2EBC4` (unchanged) |

Isolated runtime smoke checks used fresh `%TEMP%\stocktool-sprint15-*` directories via `STOCK_TOOL_USER_DATA_DIR`:

- Normal launch: `http://localhost:8501/_stcore/health` returned HTTP `200`, body `ok`; homepage returned HTTP `200`.
- Busy-port fallback: a temporary listener held `8501`; the staging launcher selected `8502`, whose health endpoint returned HTTP `200`, body `ok`.
- `reports`, `logs`, `data\cache`, and `data\daily_research` were writable only inside the isolated runtime.
- All smoke-test `StockTool` processes and `8501`/`8502` listeners were closed. Isolated runtime and archive-extraction directories were removed after verification.

## Privacy and user-data integrity

The staging release scan found zero forbidden runtime/private files: no `.env`, `secrets*.toml`, `portfolio.csv`, `watchlist.csv`, `stock_data.sqlite`, embedded runtime reports/logs/cache, or other smoke artifacts.

Real user data was read only before and after validation:

| Path | Before and after |
| --- | --- |
| `%LOCALAPPDATA%\StockTool\data\portfolio.csv` | Exists, 4 rows, 131 bytes, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `%LOCALAPPDATA%\StockTool\data\watchlist.csv` | Absent |
| `%LOCALAPPDATA%\StockTool\data\processed\stock_data.sqlite` | Exists, 339,968 bytes, SHA-256 `2A2FA20A7A6F01FA3B22A942B82D6056A70755824FEF4FF6E8176ED24317CDF7` |
| `%LOCALAPPDATA%\StockTool\settings.json` | Absent |

All observed existence states, sizes, modification times, row count, and hashes were unchanged.

## Source archive and rollback

| Artifact | Value |
| --- | --- |
| Source archive | `release\baseline\stocktool-sprint15-20260726-source.zip` |
| Size | `2,311,539` bytes |
| Entries | `267` |
| SHA-256 | `33B73065A9A312C9D57F7782E5DBF7D160F18494D8EC3B1AA1BB651E43987E3C` |
| Sidecar | `release\baseline\stocktool-sprint15-20260726-source.zip.sha256` |

`verify_source_archive(archive_path=..., extracted_root=...)` reported `missing_required_inputs=0`, `forbidden_entries=0`, and `content_mismatches=0`; the sidecar matched the ZIP hash. Rollback is unchanged: retain the current formal `release\StockTool` and use its existing approved rollback baseline. Sprint 15 remains staging-only.

## Known limitations

- Portfolio Risk v2 is research/risk analysis only. It does not issue trading instructions, predict prices, calculate VaR, or place orders.
- Factor exposure remains explicitly unknown until a source-backed factor model is separately approved.
- Sector and industry results remain partial/unknown until market-qualified, sourced company classification exists in the cached research profile.
- Realized P&L is shown only when the existing ledger and explicit conversion evidence can support it; no ledger is auto-created from CSV holdings.
- The integration preserves the existing dashboard visual system. Independent CTO acceptance should include a final interactive review of the populated portfolio page in Light/Dark/System themes.
- Formal release promotion is intentionally not part of this Sprint.

No Sprint 16 work was started.
