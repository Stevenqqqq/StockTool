# Sprint 4 Acceptance

Date: 2026-07-12

## Verdict

**Accepted.** Sprint 4 delivers the Dashboard Shell, six-workspace navigation, centralized UI state, market-qualified search, responsive dark styling, Legacy diagnostic rollback, tests, and a Windows EXE release. Sprint 5 was not started.

## Baseline and Data Safety

- Sprint 3.2.1 source baseline: `release/baseline/stocktool-sprint3.2.1-20260711-source.zip`
  - SHA-256: `3C0E6CE2ABEE4EB50DCB37A866B65574F2C36E6F8E260E084315C987EA1FFAF4`
- Sprint 4 pre-change archive: `release/baseline/stocktool-sprint4-20260712-prechange-source.zip`
  - SHA-256: `340443CC0066843C030380FCF210ECB1A6000B976F291460FA9957BA60882DA8`
- Baseline: 291 tests and 73.83% coverage.
- Real user portfolio: unchanged, 4 rows, SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` before and after Sprint 4.

## Modified Files

| File group | Purpose |
| --- | --- |
| `.streamlit/config.toml` | Stable dark theme and disabled implicit Streamlit multipage sidebar. |
| `src/stock_tool/dashboard/navigation.py` | Declarative six-workspace navigation and legacy mapping. |
| `src/stock_tool/dashboard/state.py` | Immutable search intent and explicit UI-state lifecycle. |
| `src/stock_tool/dashboard/styles.py` | Static design tokens and focus treatment. |
| `src/stock_tool/dashboard/components/*` | Shell, search form, and safe status primitives. |
| `src/stock_tool/dashboard/pages/home.py` | First-use and returning-user research home. |
| `src/stock_tool/dashboard/app.py` | Shell adapter, Legacy rollback, and type-safe home counts. |
| `tests/test_dashboard_navigation.py` | Navigation, compatibility, config, and AppTest coverage. |
| `tests/test_dashboard_state.py` | Search and state-machine coverage. |
| `build_exe.bat` | Packages `.streamlit` configuration. |
| `README.md` | Documents navigation, search, states, and rollback. |
| `docs/acceptance/sprint4/*.png` | Visual validation evidence. |

No provider, backtest, risk, portfolio calculation, report calculation, or user-data storage logic was redesigned.

## Navigation and Compatibility

Default sidebar order:

1. `研究首頁`
2. `探索`
3. `策略`
4. `持倉`
5. `研究庫`
6. `設定`

| Workspace | Retained functions |
| --- | --- |
| 研究首頁 | 首頁儀表板、單檔股票分析、技術指標、AI 分析與評分、基本面評分 |
| 探索 | 產業 / 概念股查詢、股票篩選器、自選股清單 |
| 策略 | 策略回測 |
| 持倉 | 投資組合管理、投資組合風險 |
| 研究庫 | 研究報告摘要、報表下載 |
| 設定 | 資料匯入、自動抓資料 |

`legacy_dashboard` defaults to `false`. The explicit **Legacy dashboard／診斷模式** control in `設定` opens the previous full page list only for compatibility diagnosis, with an explicit return to the new Shell. There is no hidden automatic fallback.

## UI State, Search, and Design

- Defined states: `first_use`, `loading`, `partial`, `ready`, `stale`, and `error`.
- `SearchRequest` is immutable and requires a non-empty symbol plus explicit `TWSE`, `TPEX`, or `US` market.
- The form supports Enter submission and consumes a request once per rerun; navigation does not repeat a completed request.
- Provider and exception internals stay in logs. The UI shows generic safe Chinese errors and retains existing data after a refresh failure.
- Static dark design tokens use no external CDN/font, user-controlled HTML, or fragile generated-DOM selector. Inputs have visible focus treatment and state-specific copy.
- Applicable `web-design-guidelines` criteria were checked for labels, focus, empty/error states, dark contrast, and responsive layout.
- Manual 900 px check: `clientWidth == scrollWidth == 900`; no root horizontal overflow.

Visual evidence:

- `docs/acceptance/sprint4/home-1920x1080.png`
- `docs/acceptance/sprint4/home-1366x768.png`
- `docs/acceptance/sprint4/home-900x900.png`
- `docs/acceptance/sprint4/explore-1920x1080.png`
- `docs/acceptance/sprint4/strategy-1920x1080.png`
- `docs/acceptance/sprint4/holdings-1920x1080.png`
- `docs/acceptance/sprint4/library-1920x1080.png`
- `docs/acceptance/sprint4/settings-1920x1080.png`

## Validation

| Gate | Result |
| --- | --- |
| Targeted dashboard tests | 30 passed |
| Complete pytest | 300 passed |
| Coverage | 74.96%, above 73.83% gate |
| Black / Ruff | Passed for Sprint 4 changed Python files |
| mypy | Passed, 10 source files checked with no issues |
| EXE smoke | `/_stcore/health` returned `ok` |
| Runtime writes | Isolated `reports/`, `logs/`, and `data/cache/` probes passed |
| Cleanup | Test process tree removed; 8501 and 8502 had no listeners |

Actual validation commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_dashboard_navigation.py tests/test_dashboard_state.py tests/test_dashboard.py -q
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-report=term --cov-fail-under=73.83
.\.venv\Scripts\python.exe -m black --check <Sprint 4 changed Python files>
.\.venv\Scripts\python.exe -m ruff check <Sprint 4 changed Python files>
.\.venv\Scripts\python.exe -m mypy --follow-imports=skip --ignore-missing-imports src/stock_tool/dashboard/app.py src/stock_tool/dashboard/navigation.py src/stock_tool/dashboard/state.py src/stock_tool/dashboard/styles.py src/stock_tool/dashboard/components src/stock_tool/dashboard/pages
cmd /c build_exe.bat
```

## EXE and Release Privacy

- EXE: `release/StockTool/StockTool.exe`
- Build time: `2026-07-12 03:40:39` local time
- Size: `23,769,159` bytes
- SHA-256: `84A60FC2EFAAB2BFC370FA5632A21A54B014B2A65CFD9FAEBF2A23B30BD28789`

The release scan checked 2,798 files. It found zero real `.env`, `portfolio.csv`, `watchlist.csv`, `error.log`, or runtime `reports`, `logs`, and `cache` directories. It contains one permitted `.env.example` and seven sample files. A narrow text scan only matched empty `STOCK_TOOL_DATA_API_KEY=` in `.env.example` and an OpenAI-key example in bundled Streamlit documentation; neither is a project secret.

## Final Source Archive

- Archive: `release/baseline/stocktool-sprint4-20260712-source.zip`
- SHA-256 sidecar: `release/baseline/stocktool-sprint4-20260712-source.zip.sha256`
- ZIP readability: passed, 317 entries
- Size: `1,664,346` bytes
- SHA-256: `68C3E36FB87623D97E34391E562AB32622E20DBE5CBD4D014FE39B7B874047BE`

The archive contains source, tests, documents, scripts, Streamlit configuration, and sample data. It excludes real `.env`, portfolio/watchlist data, caches, reports, logs, virtual environments, build output, and release payloads.

## Known Limits

- The Shell deliberately hosts retained pages through contextual secondary navigation until the dedicated Research Workspace consolidation planned for Sprint 5. No legacy financial function was removed or reimplemented.
- Sprint 4 adds no new provider, live-market guarantee, scoring logic, automated trading, external generative AI, mobile-native app, or changed backtest/risk semantics.

Sprint 4 is complete. No Sprint 5 work was started.
