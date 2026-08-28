# Sprint 12 Acceptance Record

## Status

Sprint 12 實作完成，等待 CTO 獨立驗收。

## Scope and Design

Sprint 12 adds a canonical, code-owned strategy registry and an opt-in strategy-health validation layer. It does not change existing BacktestEngine semantics: T-day signals remain eligible no earlier than T+1, and existing broker costs, slippage, portfolio, and risk rules remain in effect.

The registry has six keys: ma_cross, breakout, rsi_reversal, macd_trend, volume_price_breakout, and fundamental_growth. Each definition supplies a stable key, Chinese display name, factory, parameter schema/defaults, minimum data requirement, description, risk notes, fundamental requirement, allowed sensitivity parameters, and forbidden position-sizing inputs. Production dashboard labels, creation, and guidance use the registry rather than a second strategy list.

The separate validation service provides:

- Chronological out-of-sample validation. Signals are calculated only from data available no later than the validation-period end, and only test-period results are retained.
- Bounded expanding or rolling walk-forward folds. Test folds do not overlap and configurations with fewer than two valid folds are rejected.
- Bounded sensitivity checks. Only strategy-specific allowed parameters are accepted; position-sizing parameters are rejected; grids over the configured cap (default 25) are rejected rather than truncated.
- Strict Fundamental Growth validation. Valid available_date data is required. Missing data produces a structured unavailable warning, never a legacy fallback.

Strategy Health is an optional panel below the unchanged single-backtest flow. It does not overwrite session backtest_result, submit orders, or issue buy/sell instructions. It shows preflight, transparent date ranges, fold/grid bounds, warnings, and research-only limitations.

## Files Changed or Added

- src/stock_tool/strategies/registry.py
- src/stock_tool/strategies/__init__.py
- src/stock_tool/backtest/validation.py
- src/stock_tool/backtest/__init__.py
- src/stock_tool/dashboard/pages/strategy.py
- src/stock_tool/dashboard/app.py
- src/stock_tool/dashboard/backtest_ui.py
- tests/test_strategy_registry.py
- tests/test_walk_forward.py
- tests/test_parameter_sensitivity.py
- tests/test_strategy_page.py
- README.md

The initial RED run failed at collection because Registry, Validation, and Strategy Health modules did not exist. Final tests use deterministic synthetic price/fundamental fixtures; no test requires a network provider.

## Verification

### Targeted tests

    .\.venv\Scripts\python.exe -m pytest tests/test_strategy_registry.py tests/test_walk_forward.py tests/test_parameter_sensitivity.py tests/test_strategy_page.py tests/test_strategies.py tests/test_backtest_point_in_time.py tests/test_sprint52_backtest_usability.py -q

Result: 51 passed.

Coverage includes registry completeness and parameter rejection, OOS date boundaries/T+1 execution, walk-forward folds, strict fundamental available-date handling, sensitivity cap/order/forbidden sizing, and fixed-data Strategy Health rendering.

### Full suite and coverage

    .\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing

Result: 572 passed in 93.81s.

Branch coverage: 81.18%. This exceeds the configured 78.50% gate and Sprint 12's 81% target.

### Focused quality checks

    .\.venv\Scripts\python.exe -m black --check src/stock_tool/strategies/registry.py src/stock_tool/backtest/validation.py src/stock_tool/dashboard/pages/strategy.py src/stock_tool/dashboard/app.py src/stock_tool/dashboard/backtest_ui.py tests/test_strategy_registry.py tests/test_walk_forward.py tests/test_parameter_sensitivity.py tests/test_strategy_page.py

    .\.venv\Scripts\python.exe -m ruff check src/stock_tool/strategies/registry.py src/stock_tool/backtest/validation.py src/stock_tool/dashboard/pages/strategy.py src/stock_tool/dashboard/app.py src/stock_tool/dashboard/backtest_ui.py tests/test_strategy_registry.py tests/test_walk_forward.py tests/test_parameter_sensitivity.py tests/test_strategy_page.py

    .\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src/stock_tool/strategies/registry.py src/stock_tool/backtest/validation.py src/stock_tool/dashboard/pages/strategy.py src/stock_tool/dashboard/backtest_ui.py tests/test_strategy_registry.py tests/test_walk_forward.py tests/test_parameter_sensitivity.py tests/test_strategy_page.py

Results: Black reports all nine files unchanged; Ruff reports All checks passed; mypy reports Success: no issues found in 8 source files.

## Staging EXE

build_exe.bat completed through the existing staging-first flow. It rebuilt only release/staging/StockTool and did not promote or modify the formal release.

- Path: release/staging/StockTool/StockTool.exe
- Version: 1.2.2
- Last write (UTC): 2026-07-18T14:30:41.9396264Z
- Size: 24,063,733 bytes
- SHA-256: AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F

Using an isolated STOCK_TOOL_USER_DATA_DIR, http://localhost:8501/_stcore/health returned ok; the homepage returned HTTP 200; and reports/, logs/, and data/cache/ were writable. The complete launch process tree was terminated, 8501/8502 listeners were zero, and the isolated runtime was removed.

The formal release remained unchanged:

- release/StockTool/StockTool.exe
- SHA-256: 4CA2C7675DD9C3E9DA6DD8E807D425F494243EF74D677B0271927EC4C2FF76FA

## Privacy and User Data Integrity

The staging release contains required public assets and sample data. Privacy scanning found no .env, secrets*.toml, portfolio.csv, watchlist.csv, stock_data.sqlite, root-level runtime reports/, logs/, or data/cache/. The package contains only its allowlisted internal .streamlit/config.toml; no Streamlit secrets file was found.

Real user data was inspected read-only before and after all validation:

| Item | Before | After |
| --- | --- | --- |
| portfolio.csv | 4 data rows; A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6 | identical |
| watchlist.csv | absent | absent |
| stock_data.sqlite | FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C | identical |
| settings.json | absent | absent |

No real user data was used for testing, EXE smoke, or cleanup.

## Source Archive

- Path: release/baseline/stocktool-sprint12-20260718-source.zip
- SHA-256: D209A8357523D0ABC8FA4C481E284B9684EE67D97900C1D30E8425044257E357
- Sidecar: release/baseline/stocktool-sprint12-20260718-source.zip.sha256
- Entries: 247, including SOURCE_ARCHIVE_MANIFEST.json

The archive was rebuilt with the existing privacy-safe allowlist and extracted into an isolated temporary directory. Verification result:

- required build inputs missing: 0
- forbidden entries: 0
- archive content mismatches: 0

The temporary extraction directory was removed after verification.

## Rollback and Limits

Sprint 12 has not promoted staging into release/StockTool. Rollback consists of retaining the existing formal release and discarding the staging candidate/archive only after independent acceptance. This Sprint introduced no runtime database migration or user-data mutation.

OOS, walk-forward, and sensitivity are research diagnostics, not evidence of future robustness or a solution to overfitting. The validation layer adds no providers, historical universes, automated trading, or Sprint 13 scope. Fundamental validation remains unavailable when trustworthy available_date data is absent, by design.
