# Sprint 10.2.1 Acceptance Record

**Status:** ready for independent acceptance review

## Scope and Root Cause

Sprint 10.2.1 corrects only the Daily Research Home restart path. The legacy
`prices` SQLite table identifies a row by `date` and `symbol`, with no market
or source freshness metadata. `_persist_price_data()` therefore persisted the
OHLCV rows but discarded the market-qualified identity and provenance. A new
session could read those rows only as `UNKNOWN`, and portfolio valuation
correctly refused to use them. This produced a contradictory home state: the
portfolio was readable, but every holding was reported without a price.

No existing `prices` schema was altered. No market is inferred from a ticker.

## Implementation

### Persistent market-qualified companion index

`SQLitePriceStorage` now maintains an additive JSON sidecar next to a runtime
SQLite database: `stock_data.price_identity.json`. It stores separate records
by canonical `market + symbol`, together with explicit per-identity metadata:

- provider and provider symbol;
- source type;
- last market data date;
- fetched/check time; and
- the market-qualified OHLCV records.

The base SQLite table remains unchanged for compatibility. On restart, known
sidecar identities are loaded first. Legacy SQLite-only prices remain
`UNKNOWN`; they are not silently assigned to a portfolio market and cannot be
used for valuation. A corrupt or unsupported sidecar produces a safe warning
and falls back only to those unresolved legacy rows.

Freshness uses persisted `checked_at` or `fetched_at`; it never substitutes
the current clock for a market-data timestamp. Missing metadata produces the
explicit `price_freshness` data gap rather than a claim that data is current.

### Legacy portfolio market codes

The home summary and Daily Brief use the existing domain `Market.parse`
normalization. Safe legacy codes such as `TW` are recognized consistently;
unparseable rows are excluded from the resolved count and reported with their
specific row/market value. The summary no longer claims that the whole
portfolio file is unreadable when only one row is unresolved.

## Modified Files

- `src/stock_tool/data/storage.py`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/application/daily_brief.py`
- `src/stock_tool/dashboard/home_data.py`
- `tests/test_price_identity_persistence.py` (new)
- `SPRINT10.2_ACCEPTANCE.md` (evidence correction only)
- `SPRINT10.2.1_ACCEPTANCE.md` (this record)

No backtest, scoring, RiskManager, provider contract, trading semantics, or
SQLite `prices` schema was changed. Package version remains `1.2.1`.

## Regression Coverage

The new isolated-runtime tests cover:

- full close/restart display of 2330/TWSE, 6488/TPEX, and AAPL/US;
- an actual Streamlit `AppTest` home restart with `3/3` price coverage;
- same ticker in distinct markets without collision;
- unknown legacy rows excluded from valuation;
- corrupt sidecar metadata rejected without a silent market guess;
- stale data still reported after restart;
- missing freshness metadata reported as indeterminate;
- consistent home and Daily Brief resolved portfolio counts; and
- precise warnings for an invalid portfolio market code.

All test data used temporary, isolated runtime roots. The test suite does not
read or write the real portfolio, watchlist, cache, or SQLite database.

## Verification Results

| Check | Actual command / result |
| --- | --- |
| Sprint 10.2.1 targeted tests | `python -m pytest -o addopts='' tests/test_price_identity_persistence.py tests/test_storage.py tests/test_dashboard.py tests/test_daily_brief.py tests/test_daily_home.py tests/test_sprint81_auto_fetch_evidence.py -q` -> `57 passed in 7.86s` |
| Full pytest | `python -m pytest -q` -> `495 collected`, all passed |
| Branch coverage | `python -m pytest --cov=stock_tool --cov-branch --cov-report=term -q` -> `80.63%`, above the `80.50%` gate |
| Black | `python -m black --check` on the five changed source/test files -> passed |
| Ruff | `python -m ruff check` on the same five files -> passed |
| mypy | `python -m mypy --ignore-missing-imports src/stock_tool/data/storage.py src/stock_tool/dashboard/app.py src/stock_tool/application/daily_brief.py src/stock_tool/dashboard/home_data.py` -> `Success: no issues found in 4 source files` |

## EXE Build and Smoke Test

The existing staging-first process rebuilt and promoted the v1.2.1 release.
The previous release was retained under `release/previous/StockTool`; its prior
occupant was preserved using a timestamped directory before promotion.

| Item | Value |
| --- | --- |
| EXE | `release/StockTool/StockTool.exe` |
| Version | `1.2.1` |
| Modified | `2026-07-16T00:43:22.5613155+08:00` |
| Size | `23,987,789` bytes |
| SHA-256 | `09F90906C1E984FE7389D24CDCE708A25539A155C9CC5F085C3BC54CE3C4C1B9` |
| Normal smoke | isolated runtime: `http://localhost:8501/_stcore/health` returned `ok` |
| Fallback smoke | 8501 occupied: `http://localhost:8502/_stcore/health` returned `ok` |
| Runtime writes | isolated `reports`, `logs`, and `data/cache` write checks passed |
| Cleanup | no StockTool process and no 8501, 8502, or 8510 listener remained |

The formal release asset validator passed after promotion.

## Privacy and User Data Integrity

The release privacy scan inspected 2,802 release files. It found zero
forbidden `.env`, `secrets*.toml`, portfolio, watchlist, runtime SQLite,
reports, logs, or cache files. The only packaged Streamlit configuration is
`_internal/.streamlit/config.toml`.

Real user data was read only for before/after verification:

- `portfolio.csv`: exists, 4 rows, 131 bytes, unchanged SHA-256
  `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
- `watchlist.csv`: absent before and after.
- `stock_data.sqlite`: exists at
  `%LOCALAPPDATA%\\StockTool\\data\\processed\\stock_data.sqlite`, 249,856 bytes,
  unchanged SHA-256
  `71485B3A141654CB08A085EE043871F484DDE52A1765B3CDF9B3F9761D9B914E`.

`publish_release.bat` created a legacy-release migration check manifest under
the user runtime backup directory. It did not overwrite, move, initialize, or
migrate the portfolio, watchlist, or SQLite database.

## Source Archive

| Item | Value |
| --- | --- |
| Archive | `release/baseline/stocktool-sprint10.2.1-20260716-source.zip` |
| ZIP entries | 227 total: 226 source entries plus `SOURCE_ARCHIVE_MANIFEST.json` |
| SHA-256 | `F1933372932148987272B4893189DA0B85BA4E4BC09675B7AF0A220908AE12DB` |
| Sidecar | `release/baseline/stocktool-sprint10.2.1-20260716-source.zip.sha256` |
| Verification | required build inputs missing: 0; forbidden entries: 0; archive content mismatches: 0; workspace content mismatches: 0 |

Verification used the keyword-only contract:
`verify_source_archive(archive_path=..., extracted_root=...)`, then compared
the extracted manifest hashes to the current workspace before removing the
temporary extraction directory.

## Known Limitations and Rollback

- The companion index is intentionally additive. Existing SQLite-only prices
  without trustworthy market identity remain unavailable for market-qualified
  valuation until they are obtained again through a market-qualified path.
- The sidecar does not upgrade or rewrite legacy prices rows.
- No network refresh occurs automatically on the Daily Research Home.
- Roll back by restoring the preserved `release/previous/StockTool` directory
  through the existing staging-first promotion process. User runtime data is
  intentionally outside the release directory and was not modified.

Sprint 11 was not started.
