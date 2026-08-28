# Sprint 11.2.1 Acceptance Handoff

Status: **Implementation complete and ready for independent acceptance review.**

Sprint 11.2.1 is a focused correction to USD/TWD freshness and cache semantics only. It does not start Sprint 12 and does not promote `release\staging\StockTool` to `release\StockTool`.

## Root Cause and Corrected Semantics

The prior implementation treated `effective_at` as both the market observation date and cache age. This made a normal Friday quote retrieved on Saturday appear valid online, but could make the exact same cached quote expire based on its Friday market date. The dashboard also returned a stored `FxResolution` without checking whether its retrieval had exceeded the cache TTL.

The two time meanings are now distinct:

| Field | Meaning | Policy |
| --- | --- | --- |
| `fetched_at` | When StockTool retrieved the quote or wrote it to runtime cache. | The only timestamp used by the 24-hour cache TTL. |
| `effective_at` | Date/time of the underlying market observation. | Kept unchanged for display and evaluated against a separate conservative market-data freshness policy. |

The first implementation uses a configurable seven-day market-data age policy because the product has no reliable FX exchange calendar in this Sprint. It tolerates ordinary weekends and short holidays, but an obviously old online observation is marked stale and is not presented as current online data. The UI now labels market-data date separately from download/cache time.

## Modified Files

- `src/stock_tool/portfolio_fx.py`
- `src/stock_tool/portfolio_valuation.py`
- `src/stock_tool/dashboard/app.py`
- `tests/test_portfolio_fx.py`
- `tests/test_dashboard.py`
- `README.md`

## Behavior Delivered

- `JsonFxQuoteCache` and `CachedFxRateProvider` validate TTL from `fetched_at`, never `effective_at`.
- `YFinanceUsdTwdProvider` retains the real market `effective_at`, evaluates it with the independent policy, and emits a clear warning when it is too old.
- A fresh cache can preserve a stale market-data flag; it is not mislabeled as current market data.
- `_stored_portfolio_fx_resolution()` reuses a session quote only while its `fetched_at` remains inside the TTL. An expired session quote follows the established `online -> cache -> manual -> unavailable` resolution chain and replaces only the session-derived resolution.
- Reciprocal USD/TWD conversion and the existing no-`1.0` missing-rate policy are unchanged.
- `portfolio.csv`, watchlist data, runtime SQLite, and settings are not read for mutation or used for tests.

## New Regression Coverage

- Friday market data retrieved on Saturday keeps Friday as `effective_at`, Saturday as `fetched_at`, and remains valid under the seven-day market-data policy.
- Cache validity is based on retrieval time; the same Saturday retrieval is available within 24 hours and expires only after its retrieval TTL elapses.
- An obviously old online market observation is marked stale and, with no valid fallback, resolves to structured unavailable rather than current online data.
- An expired session `FxResolution` invokes the normal resolver instead of being reused indefinitely.
- Existing reciprocal conversion and `online -> cache -> manual -> unavailable` tests remain covered.

## Validation Results

| Check | Actual command / result |
| --- | --- |
| Sprint 11.2.1 targeted tests | `.venv\Scripts\python.exe -m pytest tests\test_portfolio_fx.py tests\test_portfolio_valuation.py tests\test_sprint32_portfolio.py tests\test_portfolio_refresh.py tests\test_dashboard.py -q` -> **66 passed**. |
| Full pytest | `.venv\Scripts\python.exe -m pytest -o addopts=""` -> **551 passed in 54.99s**. |
| Branch coverage | `.venv\Scripts\python.exe -m coverage erase`; `.venv\Scripts\python.exe -m coverage run -m pytest -q`; `.venv\Scripts\python.exe -m coverage report --format=total` -> **81%**. This is above both the 81% Sprint requirement and the `pyproject.toml` 78.50% gate. |
| Black | `.venv\Scripts\python.exe -m black --check src\stock_tool\portfolio_fx.py src\stock_tool\portfolio_valuation.py src\stock_tool\dashboard\app.py tests\test_portfolio_fx.py tests\test_dashboard.py` -> passed. |
| Ruff | `.venv\Scripts\python.exe -m ruff check src\stock_tool\portfolio_fx.py src\stock_tool\portfolio_valuation.py src\stock_tool\dashboard\app.py tests\test_portfolio_fx.py tests\test_dashboard.py` -> passed. |
| mypy | `.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\portfolio_fx.py src\stock_tool\portfolio_valuation.py src\stock_tool\dashboard\app.py` -> `Success: no issues found in 3 source files`. |

## Staging EXE and Smoke Test

- Staging path: `release\staging\StockTool\StockTool.exe`
- Version: `1.2.2`
- UTC build time: `2026-07-18T09:31:24.9739830Z`
- Size: `24,038,929` bytes
- SHA-256: `4CA2C7675DD9C3E9DA6DD8E807D425F494243EF74D677B0271927EC4C2FF76FA`
- Build command: `cmd /c build_exe.bat`

The staging EXE was started with an isolated `STOCK_TOOL_USER_DATA_DIR`:

- `http://localhost:8501/_stcore/health` returned exact `HTTP 200 / ok`.
- Isolated `reports/`, `logs/`, and `data/cache/` write probes succeeded.
- The complete StockTool process tree was terminated after the smoke check.
- No StockTool process and no 8501/8502 listener remained.
- The temporary smoke runtime directory was removed after verification.

The formal release was not replaced. Its current EXE SHA-256 remains `0801C99607D0C5AE029FC50E8E53D7226969A315370D6BFDE6B2971517F2E28C`.

## Release Privacy Scan

The staging package contains no `.env`, `secrets*.toml`, `portfolio.csv`, `watchlist.csv`, `stock_data.sqlite`, runtime `reports/`, `logs/`, `data/cache/`, or `data/processed/` files. It packages exactly one Streamlit configuration file: `_internal/.streamlit/config.toml`, and includes 10 bundled sample-data files.

The public release files, bundled samples, and packaged Streamlit config were also scanned for credential-shaped values. Result: **0** matches. The scan examined 15 allowlisted public files and did not treat third-party packaged dependency source names as user secrets.

## Real User Data Integrity

All values below were read-only checks before and after validation:

| Item | Before / after |
| --- | --- |
| `%LOCALAPPDATA%\StockTool\data\portfolio.csv` | 5 lines; `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` (unchanged) |
| `%LOCALAPPDATA%\StockTool\data\watchlist.csv` | absent before and after |
| `%LOCALAPPDATA%\StockTool\data\processed\stock_data.sqlite` | `FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C` (unchanged) |
| `%LOCALAPPDATA%\StockTool\settings.json` | absent before and after |

## Source Archive

- Path: `release\baseline\stocktool-sprint11.2.1-20260718-source.zip`
- Entries: `240`, including `SOURCE_ARCHIVE_MANIFEST.json`
- SHA-256: `9D7ACBAA767CDF16B85AD41859061F4AD98FFCEF0738D96B90B4C09A4A85DDBE`
- Sidecar: `release\baseline\stocktool-sprint11.2.1-20260718-source.zip.sha256`

Archive verification used the keyword-only `verify_source_archive(archive_path=..., extracted_root=...)` API and returned:

- Required build inputs missing: `0`
- Forbidden entries: `0`
- Content mismatches: `0`

## Known Limitations and Rollback

- The seven-day market-data freshness policy is intentionally conservative. Without an approved exchange calendar, it cannot identify every market holiday precisely; the UI shows the actual market-data date and warning rather than pretending precision.
- yfinance availability remains external. A failed online request can use only a retrieval-fresh cache, an explicit manual fallback, or structured unavailable state.
- This patch does not alter valuation formulas, holdings, research scoring, providers beyond USD/TWD freshness handling, or the formal release.
- To roll back the candidate, discard `release\staging\StockTool` and retain the formal release plus prior baseline archives. No real user data migration or rollback is necessary.
