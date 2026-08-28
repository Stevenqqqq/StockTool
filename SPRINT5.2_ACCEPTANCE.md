# Sprint 5.2 Acceptance

Date: 2026-07-13

## Scope

Sprint 5.2 improves the beginner usability of existing strategy backtests and
the actionability of portfolio data-gap messages. It does not start Sprint 6.
No provider fallback, strategy formula, T+1 execution semantics, Broker cost
formula, sell-only tax behavior, slippage behavior, portfolio-health formula,
or real user data was changed.

`AGENTS.md` now names Sprint 5.1 as the accepted baseline before this Sprint.

## UI Behavior

The retained `策略回測` page now follows these visible steps:

1. Select instrument and inspect canonical market, date range, data rows, and source.
2. Select one existing strategy.
3. Set the existing strategy parameters and its actual `target_percent` allocation.
4. Set initial cash, a market cost preset, the existing max-position cap, and optional trailing stop.
5. Review deterministic preflight validation and the exact effective parameters.
6. Run only through `使用以上設定執行回測` after validation passes.
7. Read an explicit historical-result summary, including a neutral no-trade state.

The page states that it is historical research only, does not place orders, and
is independent from portfolio risk analysis. Trailing stop is explained in
Traditional Chinese; the conservative daily/T+1 technical model remains in an
expandable detail section.

`策略投入比例` is the existing strategy `target_percent`; `單一持股上限` is
still passed independently to the existing engine and broker. Preflight blocks
an allocation above the max-position cap, invalid MA short/long windows,
insufficient rows, absent fundamental data for the fundamental strategy,
negative costs, invalid trailing values, and unconfirmed UNKNOWN markets.

## Cost Assumptions and Percent Conversion

New pure helpers are in `stock_tool.dashboard.backtest_ui`:

- `BacktestCostPreset`
- `BacktestFormValues`
- `BacktestValidationResult`
- `percent_to_rate()` and `rate_to_percent()`
- `resolve_backtest_currency()` and `resolve_cost_preset()`
- `validate_backtest_form()`
- `build_backtest_summary()`

UI input is percent-based and converts only at the boundary to the unchanged
engine rate. Examples: `40% -> 0.40`, `0.1425% -> 0.001425`, and
`0.3000% -> 0.003`.

| Canonical market | Preset | Commission | Sell tax | Slippage | Currency |
|---|---|---:|---:|---:|---|
| TWSE / TPEX | Taiwan stock | 0.1425% | 0.3000% | 0.1000% | TWD |
| US | US stock | 0.1000% | 0.0000% | 0.1000% | USD |
| UNKNOWN | Custom | user confirmation required | user confirmation required | user confirmation required | not guessed |

Direct cost edits become `custom` and persist across Streamlit reruns and
market changes. No cross-currency conversion is introduced. The existing
Broker continues to apply commission on both sides, tax only on sell orders,
and slippage using the existing next-open model.

## Portfolio Guidance

`stock_tool.dashboard.portfolio_guidance` maps canonical `MissingData` fields
to Chinese next steps without modifying holdings, prices, risk inputs, or
health-score formulas. The portfolio page now states that it does not require
a backtest, shows actionable guidance for missing price, FX, historical price,
fundamental, composite score, or identity inputs, and keeps the technical
reason in an expander.

## Modified Files

- `AGENTS.md`
- `README.md`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/dashboard/backtest_ui.py` (new)
- `src/stock_tool/dashboard/portfolio_guidance.py` (new)
- `tests/test_sprint52_backtest_usability.py` (new)

## Tests and Quality Checks

Targeted regression command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_sprint52_backtest_usability.py tests\test_dashboard.py tests\test_backtest.py tests\test_strategies.py tests\test_portfolio_analytics.py tests\test_portfolio_health.py tests\test_portfolio_research.py
```

Result: `83 passed`.

Full suite:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Result: `358 passed`.

Branch coverage:

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term --cov-fail-under=78.50
```

Result: `358 passed`, `78.76%`; gate `78.50%` passed.

Focused quality checks:

```powershell
.\.venv\Scripts\python.exe -m black --check src\stock_tool\dashboard\app.py src\stock_tool\dashboard\backtest_ui.py src\stock_tool\dashboard\portfolio_guidance.py tests\test_sprint52_backtest_usability.py
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\dashboard\app.py src\stock_tool\dashboard\backtest_ui.py src\stock_tool\dashboard\portfolio_guidance.py tests\test_sprint52_backtest_usability.py
.\.venv\Scripts\python.exe -m mypy --follow-imports=skip src\stock_tool\dashboard\backtest_ui.py src\stock_tool\dashboard\portfolio_guidance.py
```

Result: Black, Ruff, and focused mypy passed.

The Sprint 5.2 tests cover percent/rate conversion, TWSE and US presets,
UNKNOWN behavior, custom-rerun retention, invalid allocation, invalid MA
windows, insufficient data, fundamental strategy blocking, actual
`BrokerConfig` values, neutral zero-trade messaging, retained strategy target
parameters, independent risk/backtest notices, and portfolio missing-data
guidance. Existing broker tests retain sell-only tax behavior and the existing
T+1 regression tests remain green.

## UI Validation

An isolated source runtime passed `/_stcore/health` with `HTTP 200 ok` on port
8510. Automated browser inspection at 1366x768, 1920x1080, and 480x900 found
no horizontal overflow in the Dashboard shell. The Strategy workspace opened
the new backtest page and rendered the required research-only notice. The
isolated runtime intentionally had no imported price data, so it correctly
displayed the existing "尚未匯入股價資料" state rather than inventing a result.

The fixed scenario checks are deterministic unit tests: MU/US uses the US
preset, 2330/TWSE uses the Taiwan preset, UNKNOWN remains custom, 60% target
with 50% max position is blocked, MA 60/20 is blocked, a zero-trade result is
neutral, and portfolio price/FX/indicator/fundamental/composite-score gaps
produce Chinese next steps.

## EXE and Runtime Validation

Build command:

```powershell
cmd /c build_exe.bat
```

The wrapping command reached its 124-second tool limit while PyInstaller was
still running, but the child build completed successfully and produced a new
EXE. The prior Sprint 5.1 EXE SHA-256 was
`2E2767981B2B9FD110C9B5723B71401AF7047C1D385F0F9F9796A9AB1BB6609D`.

New artifact:

- Path: `C:\Users\steve\OneDrive\Documents\股票\release\StockTool\StockTool.exe`
- Last write: `2026-07-13 17:39:38 +08:00`
- Size: `23,856,994` bytes
- SHA-256: `7CBC7BE3FA5B79900399822754AF76EEB55F83B2D5D4FB275A0A31AC58A3EE01`

The new EXE was launched with an isolated `STOCK_TOOL_USER_DATA_DIR`:

- `/_stcore/health`: `HTTP 200 ok`
- `reports/`, `logs/`, and `data/cache/`: write checks passed
- All smoke-test StockTool processes and listeners on ports 8501, 8502, and
  8510 were stopped.
- The isolated smoke runtime was deleted after verification.

## Privacy and User Data

Release privacy scan passed:

- no real `.env`
- no `secrets.toml` or `secrets.*.toml`
- no token, portfolio, watchlist, reports, logs, or runtime cache files
- the only Streamlit release configuration is `_internal/.streamlit/config.toml`
- `.env.example` contains no non-empty sensitive value

Real user data was not opened for writing. The real portfolio was verified
before and after validation:

- `%LOCALAPPDATA%\StockTool\data\portfolio.csv`
- rows: `4`
- SHA-256: `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`

`watchlist.csv` was absent before and after this Sprint.

## Source Archive

- Path: `release/baseline/stocktool-sprint5.2-20260713-source.zip`
- Entries: `184`
- SHA-256: `DA2838DDB59F6CFEE6BDE169615612A4B501D0DDFDAD76FEF363DBEFB775CB75`
- Sidecar: `release/baseline/stocktool-sprint5.2-20260713-source.zip.sha256`

The archive was extracted into a temporary directory and validated through the
existing allowlisted archive verifier:

- missing required build inputs: `0`
- forbidden entries: `0`
- content hash mismatches: `0`
- `.streamlit` entries: only `.streamlit/config.toml`

## Known Limits and Rollback

- Cost presets are research assumptions, not broker-specific quotes. They do
  not model every minimum charge, regulatory fee, FX conversion, or liquidity
  constraint.
- The page does not add strategies, data providers, AI output, or order
  submission.
- A no-trade result remains a data/strategy observation, not a success or
  failure conclusion.
- Roll back by restoring the accepted Sprint 5.1 source archive and rebuilding
  with its `build_exe.bat`; real user data remains in `%LOCALAPPDATA%\StockTool`
  and must not be replaced by a release folder.

Sprint 6 was not started.
