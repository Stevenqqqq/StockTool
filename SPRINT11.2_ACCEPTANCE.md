# Sprint 11.2 Acceptance Handoff

Status: **Implementation complete and ready for independent acceptance review.**

Sprint 11.2 implements a user-triggered portfolio refresh and analysis workflow only. It does not start Sprint 12 and does not promote the staging package to the formal release directory.

## Scope Delivered

The portfolio page now provides one primary action, **「更新並分析持股」**. A single user action processes each market-qualified holding independently through the existing price and fundamentals hydration path, then refreshes the existing technical indicators, fundamental scores, composite scores, valuation, risk inputs, health assessment, and local deterministic research brief.

The workflow does not modify `portfolio.csv`: quantity, average cost, note, row count, and user-entered market identity remain user-owned data. A failed holding is recorded independently and does not stop other holdings. `CUSTOM`, `AUTO`, or otherwise unconfirmed markets are not guessed; the result is `manual_required` with an explicit explanation.

## Automatic and Manual Fields

| Category | Fields |
| --- | --- |
| Automatically retrieved | Market-qualified price/history, price provenance, best-effort fundamentals, USD/TWD quote, provider/query symbol, data dates, and update timestamps. |
| Automatically calculated | Existing technical indicators, fundamental/composite scores when input coverage exists, currency-aware valuation, risk inputs, health, coverage, and deterministic local research brief. |
| User preference | Base display currency, force-cache-refresh option, stress scenario and magnitude, strategy/cost assumptions. |
| Explicitly manual | Holding quantity, average cost, note, `CUSTOM` currency/market identity, and the optional manual USD/TWD fallback. |

## FX Resolution

`UsdTwdFxResolutionService` reuses the existing `FxRateProvider`, `CachedFxRateProvider`, `FxQuote`, and `PortfolioValuationService` boundaries.

1. Online yfinance `TWD=X` (USD per TWD direction is explicit).
2. Valid JSON runtime cache in `STOCK_TOOL_USER_DATA_DIR/data/cache/usd_twd_fx.json`.
3. User-provided manual USD/TWD fallback from the advanced expander.
4. Structured unavailable state.

The cache uses schema version `1`, atomic replacement, TTL validation, a corruption warning, and never substitutes `1.0`. A USD base valuation consumes the reciprocal quote through the existing valuation provider interface. Provider diagnostics are sanitized with the established provider-text redaction helper.

## Modified Files

- `src/stock_tool/portfolio_valuation.py`
- `src/stock_tool/portfolio_fx.py` (new)
- `src/stock_tool/portfolio_refresh.py` (new)
- `src/stock_tool/dashboard/app.py`
- `tests/test_portfolio_fx.py` (new)
- `tests/test_portfolio_refresh.py` (new)
- `tests/test_dashboard.py`
- `README.md`

## Regression Coverage

New/updated tests cover:

- yfinance USD/TWD conversion and reciprocal conversion for USD-base valuation;
- rejection of empty, zero, negative, and NaN FX rates;
- online, fresh-cache, manual, and unavailable fallback order;
- expired/corrupt cache handling without a fabricated rate;
- independent per-holding refresh failure, identity de-duplication, force-refresh forwarding, and non-mutation of holdings;
- redaction of sensitive provider diagnostics;
- one-click dashboard orchestration, including an automatic FX result and `CUSTOM` market refusal;
- stale detection only when explicit `checked_at` provenance exists, while legacy price rows remain non-network-forcing.

## Validation Results

| Check | Command / Result |
| --- | --- |
| Sprint 11.2 targeted tests | `.venv\\Scripts\\python.exe -m pytest tests\\test_portfolio_fx.py tests\\test_portfolio_refresh.py tests\\test_dashboard.py tests\\test_portfolio_valuation.py tests\\test_portfolio_health.py -q` -> **49 passed**. |
| Full pytest | `.venv\\Scripts\\python.exe -m pytest -q` -> **547 passed**. |
| Branch coverage | `.venv\\Scripts\\python.exe -m coverage run -m pytest -q` then `coverage report --format=total` -> **81%**, above the `78.50%` gate. |
| Black | `.venv\\Scripts\\python.exe -m black --check src\\stock_tool\\portfolio_fx.py src\\stock_tool\\portfolio_refresh.py src\\stock_tool\\portfolio_valuation.py src\\stock_tool\\dashboard\\app.py tests\\test_portfolio_fx.py tests\\test_portfolio_refresh.py tests\\test_dashboard.py` -> passed. |
| Ruff | `.venv\\Scripts\\python.exe -m ruff check` over the same seven changed files -> passed. |
| mypy | `.venv\\Scripts\\python.exe -m mypy src\\stock_tool\\portfolio_fx.py src\\stock_tool\\portfolio_refresh.py src\\stock_tool\\portfolio_valuation.py src\\stock_tool\\dashboard\\app.py --ignore-missing-imports` -> `Success: no issues found in 4 source files`. |

## Staging EXE

- Path: `release\\staging\\StockTool\\StockTool.exe`
- Version: `1.2.2`
- UTC build time: `2026-07-18T07:51:48.9288670Z`
- Size: `24,037,652` bytes
- SHA-256: `70D2F1E5102D9A3A6187F9FD9439B0CDF000A71B5C616E24EE5AB0056906FC23`

The package was built with `cmd /c build_exe.bat`, which retains the staging-first workflow. `release\\StockTool` was not replaced.

### EXE Smoke

With an isolated `STOCK_TOOL_USER_DATA_DIR`:

- Normal startup: `http://localhost:8501/_stcore/health` returned HTTP 200 with exact body `ok`.
- 8501 occupied: launcher used 8502; `http://localhost:8502/_stcore/health` returned HTTP 200 with exact body `ok`.
- Isolated `reports/`, `logs/`, and `data/cache/` write probes succeeded.
- The launcher process trees were terminated after both checks. No 8501 or 8502 listener remained.

## Privacy and User Data Integrity

The staging release scan found `0` forbidden release files. It contains public sample data and exactly one packaged Streamlit configuration file, `_internal/.streamlit/config.toml`; it contains no `.env`, `secrets.toml`, token/API-key match, `portfolio.csv`, `watchlist.csv`, runtime SQLite, cache, logs, or reports.

Real user data was read-only verified before and after validation:

| Item | Before / after |
| --- | --- |
| `%LOCALAPPDATA%\\StockTool\\data\\portfolio.csv` | 5 lines; `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` (unchanged) |
| `%LOCALAPPDATA%\\StockTool\\data\\watchlist.csv` | absent before and after |
| `%LOCALAPPDATA%\\StockTool\\data\\processed\\stock_data.sqlite` | `FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C` (unchanged) |
| `%LOCALAPPDATA%\\StockTool\\settings.json` | absent before and after |

All smoke-test runtime directories were isolated under `%TEMP%` and not used as formal release assets.

## Source Archive

- Path: `release\\baseline\\stocktool-sprint11.2-20260718-source.zip`
- Entries: `240`, including the source manifest
- SHA-256: `20FFF8864A550CAF989C1879130758CAF61725720CAE44BB21395E2DC4572C1C`
- Sidecar: `release\\baseline\\stocktool-sprint11.2-20260718-source.zip.sha256`

Archive verification used the keyword-only `verify_source_archive(archive_path=..., extracted_root=...)` API and returned:

- Required build inputs missing: `0`
- Forbidden entries: `0`
- Content mismatches: `0`

## Rollback

Do not promote this staging package until independent acceptance approves it. The existing formal release remains untouched. If the staged candidate is rejected, discard `release\\staging\\StockTool` and retain the previously accepted release and baseline archives; no user runtime data needs rollback because this Sprint never migrated or wrote real user data.

## Known Limitations

- USD/TWD retrieval depends on yfinance availability. The UI labels cache, manual, and unavailable states rather than presenting stale or failed data as current.
- Automatic hydration is intentionally limited to explicit `TWSE`, `TPEX`, and `US` portfolio identities. `AUTO` and `CUSTOM` require user confirmation instead of a ticker-shaped guess.
- The workflow invokes only the existing best-effort fundamentals provider and existing scoring calculations; missing provider data remains missing and can keep health coverage incomplete.
- This Sprint does not add broker integrations, a ledger rewrite, automatic trading, new strategies, AI prediction, or any Sprint 12 work.
