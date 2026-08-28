# Sprint 4.1 Acceptance

Date: 2026-07-12

## Verdict

**Accepted.** Sprint 4.1 is a bounded acceptance repair for Sprint 4. It fixes search retry
semantics, first-open home counts, workspace guidance, Shell responsibility placement, source
archive correctness, and responsive visual validation. Sprint 5 was not started.

## Baseline

- Sprint 4 EXE SHA-256: `84A60FC2EFAAB2BFC370FA5632A21A54B014B2A65CFD9FAEBF2A23B30BD28789`
- Sprint 4 coverage baseline: `74.96%` with 300 tests.
- `app.py` before Sprint 4.1: 3,199 lines.
- Real `%LOCALAPPDATA%\StockTool\data\portfolio.csv` before and after: 4 rows, SHA-256
  `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.

## Acceptance Fixes

### 1. Same search request can now be retried

**Root cause:** `dashboard_consumed_search_signature` treated the query identity and the user
submission identity as the same thing. A completed or failed `AAPL/US` request therefore blocked
the next deliberate `AAPL/US` submission.

**Fix:** `dashboard_submission_sequence`, `dashboard_pending_submission_id`, and
`dashboard_consumed_submission_id` now track each user submission separately. The query remains
the same immutable `SearchRequest`, but each active submit receives a new sequence number.
`should_execute_pending_search()` clears both pending values when consuming the request.

**Result:** one submission executes once across reruns; an error can transition through
`error -> loading -> ready/partial/error` on the next user submit; workspace switching does not
repeat a completed request.

### 2. Home summary reads canonical local data safely

**Root cause:** the home screen counted uninitialized `session_state.portfolio` and
`session_state.watchlist`, causing existing user files to display as zero on first open.

**Fix:** `dashboard/home_data.py` uses the existing `load_portfolio_result()` and
`load_watchlist()` loaders in read-only mode. It caches only counts by file state
(`mtime_ns`/size/existence), so unchanged reruns do not reread disk. Existing data shows its true
count; an actual empty CSV shows `0`; absent or unreadable files show `資料不足` with a safe
explanation. The home screen never renders private rows.

### 3. Six-workspace overview is action-oriented

**Root cause:** explore, strategy, holdings, library, and settings only exposed a secondary
selectbox, offering little guidance and leaving large unused space.

**Fix:** `dashboard/workspace_overview.py` defines fixed native Streamlit action cards. Each card
states purpose, prerequisite data, and an explicit action. The action opens the existing legacy
renderer; it does not fabricate prices, research reports, alerts, or scores. Secondary navigation
is retained as a compact quick switcher.

Coverage includes:

- Explore: concept lookup, screener, watchlist.
- Strategy: backtest with benchmark, cost, slippage, and risk-gate wording.
- Holdings: management, health, cross-currency valuation, and stress-test wording.
- Library: research-report summary and report download.
- Settings: import, automatic fetch, and explicit Legacy diagnostic mode.

### 4. Sprint 4 Shell responsibility moved out of `app.py`

**Root cause:** Sprint 4 Shell routing, home adaptation, search orchestration, settings behaviour,
and secondary-navigation orchestration remained in the large legacy application module.

**Fix:** `dashboard/shell.py` contains the new Shell controller and accepts a
`DashboardShellDependencies` object with callbacks to `_ensure_symbol_data` and the retained
legacy renderer. It has no circular import and does not duplicate provider or legacy page logic.

- `app.py` after Sprint 4.1: **3,032** lines, below the pre-Sprint-4 3,035-line baseline.
- `shell.py`: 236 lines of narrowly scoped Shell orchestration.

The shell also isolates an exception from a retained legacy renderer: detailed exception data is
logged, while the UI receives a clear generic error and existing data remains unmodified. The
underlying portfolio-health evidence-edge case is not redesigned in this Sprint.

### 5. Source archive is now clean and verified

**Root cause:** the Sprint 4 archive copied source trees recursively and included `__pycache__`
and bytecode despite the acceptance document claiming otherwise.

**Fix:** Sprint 4.1 creates the archive from allowlisted source trees and root files, copying files
individually while excluding `__pycache__`, `.pyc`, `.pyo`, `.coverage`, tool caches, build/dist,
release payloads, virtual environments, runtime cache/log/report directories, real `.env`, and
portfolio/watchlist data. ZIP entry names are scanned after creation; any forbidden entry fails
the delivery.

## Modified Files

- `src/stock_tool/dashboard/state.py`
- `src/stock_tool/dashboard/home_data.py`
- `src/stock_tool/dashboard/workspace_overview.py`
- `src/stock_tool/dashboard/shell.py`
- `src/stock_tool/dashboard/components/search.py`
- `src/stock_tool/dashboard/pages/home.py`
- `src/stock_tool/dashboard/styles.py`
- `src/stock_tool/dashboard/app.py`
- `tests/test_dashboard_state.py`
- `tests/test_dashboard_home_data.py`
- `tests/test_dashboard_workspace_overview.py`
- `tests/test_dashboard_shell.py`
- `tests/test_dashboard_navigation.py`
- `README.md`
- `docs/acceptance/sprint4.1/*.png`

## Tests and Quality Gates

Commands executed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_dashboard_state.py tests/test_dashboard_home_data.py tests/test_dashboard_workspace_overview.py tests/test_dashboard_shell.py tests/test_dashboard_navigation.py tests/test_dashboard.py -q
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-report=term --cov-fail-under=74.96
.\.venv\Scripts\python.exe -m black --check <13 Sprint 4.1 changed Python files>
.\.venv\Scripts\python.exe -m ruff check <13 Sprint 4.1 changed Python files>
.\.venv\Scripts\python.exe -m mypy --follow-imports=skip --ignore-missing-imports src/stock_tool/dashboard/app.py src/stock_tool/dashboard/shell.py src/stock_tool/dashboard/home_data.py src/stock_tool/dashboard/workspace_overview.py src/stock_tool/dashboard/state.py src/stock_tool/dashboard/styles.py src/stock_tool/dashboard/components src/stock_tool/dashboard/pages
```

| Gate | Result |
| --- | --- |
| Sprint 4.1 targeted tests | 41 passed |
| Complete pytest | 311 passed |
| Coverage | 76.62%, above 74.96% gate |
| Black / Ruff | Passed for 13 changed Python files |
| mypy | Passed, 12 source files checked with no issues |
| Streamlit AppTest | Passed through dashboard navigation tests |
| Retry controller regression | Passed: error then same `AAPL/US` retry reaches ready without duplicate execution |

## Browser and Visual Validation

Playwright ran a real browser against an isolated source-runtime on `127.0.0.1:8501`:

- All six primary workspaces opened.
- Each non-home workspace exposed its required action-card entry.
- 1920, 1366, and 900 px home screens rendered.
- All action-card workspaces passed 900 px root-overflow checks.
- The form screenshot was taken only after the native `開始研究` submit button was visible.

Evidence:

- `docs/acceptance/sprint4.1/home-1920x1080.png`
- `docs/acceptance/sprint4.1/home-1366x768.png`
- `docs/acceptance/sprint4.1/home-900x900.png`
- `docs/acceptance/sprint4.1/explore-1920x1080.png`
- `docs/acceptance/sprint4.1/strategy-1920x1080.png`
- `docs/acceptance/sprint4.1/holdings-1920x1080.png`
- `docs/acceptance/sprint4.1/library-1920x1080.png`
- `docs/acceptance/sprint4.1/settings-1920x1080.png`

The static styling adds a 1,440 px main-content maximum width, consistent card borders and
spacing, dark `color-scheme`, and visible focus states. No external CDN, JavaScript, large UI
dependency, user-controlled unsafe HTML, or generated-DOM test selector was added.

## EXE Delivery

- Build command: `cmd /c build_exe.bat`
- EXE: `release/StockTool/StockTool.exe`
- Build time: `2026-07-12 07:53:56` local time
- Size: `23,777,612` bytes
- SHA-256: `2268847420B52A8A0A4451FD64F695274F80E5DFB77EA371C60C853D2C9A6F74`

The final EXE was launched with an isolated `STOCK_TOOL_USER_DATA_DIR`. Its
`/_stcore/health` endpoint returned `ok`; write probes for `reports/`, `logs/`, and `data/cache/`
all passed. The process tree, test runtime, and 8501/8502 listeners were removed afterwards.

## User Data and Release Privacy

- Real portfolio remained 4 rows with the baseline SHA-256 shown above.
- Release files scanned: 2,798.
- Real `.env`, `portfolio.csv`, `watchlist.csv`, `error.log` matches: 0.
- Runtime `reports`, `logs`, and `cache` directories in the release payload: 0.
- Allowed `.env.example`: 1; bundled sample files: 7.

## Clean Source Archive

- Archive: `release/baseline/stocktool-sprint4.1-20260712-source.zip`
- SHA-256 sidecar: `release/baseline/stocktool-sprint4.1-20260712-source.zip.sha256`
- ZIP entries: 163
- Forbidden entry matches: 0
- Size: 1,662,133 bytes
- SHA-256: `E122AAEBAAE683C0987A9381F427B977EC8E2980AD21FFDA9996EF523E435D16`

The archive intentionally excludes this final acceptance document to avoid a self-referential
hash. It contains allowlisted source, tests, documentation available at archive time, examples,
scripts, sample data, and `.streamlit` configuration only.

## Remaining Limits

- Sprint 4.1 retains existing legacy function implementations. It does not redesign portfolio
  health, provider contracts, backtests, financial scoring, or data storage.
- The Shell catches a retained page exception to keep the dashboard usable; the underlying
  portfolio-health evidence-edge case should be handled as a separately approved core fix.
- Research Workspace consolidation remains Sprint 5 work and was not started.
