# Sprint 6.1 Acceptance Evidence

**Status:** Implementation complete and ready for independent acceptance review.

## Scope

Sprint 6.1 is an evidence and release-artifact correction only. It does not add
product functionality, rebuild the executable, or change financial analysis,
data download, scoring, backtesting, portfolio, or dashboard runtime logic.

## Modified Files

- `tests/test_runtime_paths.py`
  - Stored `result.item("portfolio")` in `portfolio_item` and asserted it is
    not `None` before reading `status`. This fixes the actual `Optional` type
    issue without `type: ignore`.
- `release/baseline/stocktool-sprint5.2.2-20260713-rollback.zip.sha256`
  - Rewritten as a standard ASCII SHA-256 sidecar with two spaces before the
    file name and a real trailing LF. The rollback ZIP was not modified.
- `release/baseline/stocktool-sprint6.1-20260714-source.zip`
- `release/baseline/stocktool-sprint6.1-20260714-source.zip.sha256`
- `SPRINT6.1_ACCEPTANCE.md`

## Focused Mypy Reproducibility

The focused, fixed 11-file command is:

```powershell
.\.venv\Scripts\python.exe -m mypy --follow-imports=skip --ignore-missing-imports launcher.py src\stock_tool\__init__.py src\stock_tool\dashboard\shell.py src\stock_tool\release_archive.py tests\test_cli.py tests\test_runtime_paths.py tests\test_release_layout.py tests\test_release_archive.py tests\test_exe_smoke.py tests\test_dashboard_navigation.py tests\e2e\test_research_journey.py
```

Actual output:

```text
Success: no issues found in 11 source files
```

`--ignore-missing-imports` is deliberately included for the focused test files
that import pandas in an environment without pandas type stubs. This is a
narrow verification command, not a claim of strict whole-repository mypy.

## Test and Quality Results

| Check | Command / scope | Result |
| --- | --- | --- |
| Sprint 6.1 targeted tests | `pytest` over Sprint 6 E2E, release, runtime-path, CLI, and dashboard-shell test files | `40 passed in 29.86s` |
| Full pytest | `.\.venv\Scripts\python.exe -m pytest -q` | `385 passed` |
| Branch coverage | `.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing -q` | `385 passed`; `78.80%` (gate: `78.50%`) |
| Focused Black | `black --check` on the fixed 11 files | `11 files would be left unchanged` |
| Focused Ruff | `ruff check` on the fixed 11 files | `All checks passed` |
| Focused mypy | Exact command above | `Success: no issues found in 11 source files` |

## Rollback Sidecar Verification

- Rollback ZIP: `release/baseline/stocktool-sprint5.2.2-20260713-rollback.zip`
- Rollback ZIP size: `91,084,616` bytes.
- ZIP SHA-256 before and after sidecar correction:
  `CA8A167179551A04511A94C58BC132A05C8F3B02878047D20C52A02EE87881C6`
- Sidecar exact semantic content:

```text
CA8A167179551A04511A94C58BC132A05C8F3B02878047D20C52A02EE87881C6  stocktool-sprint5.2.2-20260713-rollback.zip
```

- Verification confirmed a real trailing LF, no literal `\\n`, and equality
  with `Get-FileHash`.
- ZIP privacy scan found `0` forbidden entries for portfolio, watchlist, real
  environment files, Streamlit secrets, runtime cache, logs, reports, tokens,
  API keys, authorization values, passwords, and private keys. `.env.example`
  remains an allowed non-secret template.

## Existing EXE Verification

The packaged runtime source was not changed, so `build_exe.bat` was not run.
The existing Sprint 6 executable was reverified and its hash remained unchanged.

- EXE: `release/StockTool/StockTool.exe`
- Version: `1.1.0` from `StockTool.exe --version`
- Last write: `2026-07-14 13:06:49 +08:00`
- Size: `23,862,402` bytes
- SHA-256:
  `1339A1A88F2740797D270C1A9B4F23143FDF204B888B1B5EF986CCA4D5CCF192`

Smoke test used an isolated `STOCK_TOOL_USER_DATA_DIR` under `%TEMP%`:

- `http://127.0.0.1:8501/_stcore/health` returned HTTP `200` with body `ok`.
- With port `8501` deliberately occupied, the launcher served health on port
  `8502` with HTTP `200` and body `ok`.
- Isolated `reports/`, `logs/`, and `data/cache/` were writable.
- Smoke-test processes were terminated, the isolated runtime directory was
  removed, and no `StockTool` process or `8501`/`8502` listener remained.

## Release Privacy Scan

`release/StockTool` contains the required
`_internal/.streamlit/config.toml` and no `secrets*.toml` files. The final
scan found:

- `0` real `.env`, `portfolio.csv`, `watchlist.csv`, credential, or log files.
- `0` runtime `reports`, `logs`, or `cache` directories.
- `0` packaged Streamlit secrets files.

## User Data Integrity

No real user data was written, moved, or overwritten.

| File | Before | After |
| --- | --- | --- |
| `%LOCALAPPDATA%/StockTool/data/portfolio.csv` | `4` rows; `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` | Identical: `4` rows and identical SHA-256 |
| `%LOCALAPPDATA%/StockTool/data/watchlist.csv` | Absent | Still absent |

## Sprint 6.1 Source Archive

- Archive: `release/baseline/stocktool-sprint6.1-20260714-source.zip`
- Size: `2,098,118` bytes
- Entries: `192`
- SHA-256:
  `D769DED1851B3DCFC6C94EC9FBE27A6A92FDC4B2FF0B41D24447F79680CCE2CF`
- Standard sidecar:
  `release/baseline/stocktool-sprint6.1-20260714-source.zip.sha256`

The archive was extracted into a temporary directory and checked against its
manifest and the current workspace:

- Missing required build inputs: `0`
- Forbidden entries: `0`
- Extracted archive content mismatches: `0`
- Workspace content mismatches: `0`

The temporary extraction directory was removed after verification.

## Known Limitations

- The focused mypy command intentionally validates the documented 11-file
  Sprint 6 surface only; it does not convert the whole repository to strict
  mypy or install third-party pandas stubs.
- This Sprint did not redo visual UI acceptance or rebuild the executable,
  because packaged runtime source did not change.
- Formal acceptance remains the responsibility of the independent ChatGPT CTO
  review.
