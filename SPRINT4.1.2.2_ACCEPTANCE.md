# Sprint 4.1.2.2 Acceptance

**Scope:** security acceptance repair only. Sprint 5 was not started.

## Root Cause

`release_archive.py` treated the entire `.streamlit` directory as an archive
tree root. In parallel, `build_exe.bat` passed the directory to PyInstaller.
Both behaviours could include a future local Streamlit secrets file even though
the current workspace did not contain one.

## Changes

- `src/stock_tool/release_archive.py`
  - Replaced recursive `.streamlit` collection with an explicit
    `.streamlit/config.toml` allowlist entry.
  - Added defence-in-depth validation: every other `.streamlit` archive entry
    is forbidden.
  - `required_build_inputs()` includes the config file only when it exists;
    private Streamlit files are never required build inputs.
- `build_exe.bat`
  - PyInstaller now receives
    `--add-data ".streamlit\config.toml;.streamlit"` rather than the entire
    `.streamlit` directory. The bundled target path remains
    `.streamlit/config.toml`.
- `tests/test_release_archive.py`
  - Added an isolated fake-project regression test containing `config.toml`,
    `secrets.toml`, a wildcard `secrets.*.toml`, and private Streamlit TOML
    files. It verifies that only config is in the ZIP; private file names and
    fixture content are absent from ZIP contents and sidecar; and required
    build inputs omit secrets.
  - Existing manifest, ZIP-slip, hash, forbidden-entry, and build-input
    verification tests remain active.
- `tests/test_dashboard_navigation.py`
  - Updated the packaging metadata assertion to require the config-only
    PyInstaller argument.

No financial analysis, provider, portfolio, scoring, backtest, or risk logic
was changed. No local secrets file was read, moved, or deleted.

## `.streamlit` Allowlist

The only archive and EXE input permitted below `.streamlit` is:

```text
.streamlit/config.toml
```

All other entries below `.streamlit`, including `secrets.toml`, wildcard
`secrets.*.toml`, credential TOML, and private settings, are rejected from the
source archive. Real `.env`, private keys/tokens, portfolio/watchlist data,
reports, logs, runtime cache, bytecode, and build artefacts remain excluded by
the existing archive rules.

## Validation

### Tests

| Check | Command / scope | Result |
|---|---|---|
| Sprint 4.1.2.2 targeted | `pytest tests/test_release_archive.py tests/test_dashboard_navigation.py::test_streamlit_config_disables_implicit_multipage_sidebar_navigation tests/test_portfolio_analytics.py -q` | 12 passed |
| Full suite | `python -m pytest` | 322 passed in 20.80s |
| Branch coverage | `pytest --cov=stock_tool --cov-branch --cov-report=term` followed by `coverage report --precision=2 --fail-under=77.31` | 77.35%, passed |

### Focused Quality Checks

| Tool | Actual scope | Result |
|---|---|---|
| Black | `src/stock_tool/release_archive.py`, `tests/test_release_archive.py`, `tests/test_dashboard_navigation.py` | passed |
| Ruff | same Python files | passed |
| mypy | `src/stock_tool/release_archive.py` with `--ignore-missing-imports` | passed, 1 source file |

`build_exe.bat` is not a Python input to Black, Ruff, or mypy; its exact
config-only `--add-data` argument is covered by the regression test above.

## EXE Delivery

- EXE: `release\\StockTool\\StockTool.exe`
- Built with: `cmd /c build_exe.bat`
- Timestamp: 2026-07-12 22:44:33 +08:00
- Size: 23,786,559 bytes
- SHA-256: `75A91A12E2DD181BC82231175015427FE8C621CE911A7AE301A17257EDC5C026`
- Smoke test: launched the rebuilt EXE and received `HTTP 200`, body `ok`,
  from `http://127.0.0.1:8501/_stcore/health`.
- Writable runtime locations: confirmed `reports`, `logs`, and `data/cache`.
  Test probes were removed afterward.
- Cleanup: no `StockTool` process and no listener on ports 8501 or 8502
  remained after the smoke test.

The EXE release scan found zero exact real `.env`, `portfolio.csv`,
`watchlist.csv`, Streamlit/private credential TOML files, or test-secret
marker matches under `release\\StockTool`. Its packaged Streamlit content is
only `_internal\\.streamlit\\config.toml`.

## Source Archive

- Archive: `release\\baseline\\stocktool-sprint4.1.2.2-20260712-source.zip`
- SHA-256 sidecar: `release\\baseline\\stocktool-sprint4.1.2.2-20260712-source.zip.sha256`
- Entries: 169
- Size: 1,671,803 bytes
- SHA-256: `B60D8CE86274342E6D44BF8C484342DA3D66C3E473B12F9C0B6307857F6BF038`
- Streamlit ZIP entries: exactly `.streamlit/config.toml`
- Temporary extraction verification: required build inputs missing `()`,
  forbidden entries `()`, content mismatches `()`.

## User Data Safety

The real user portfolio was not modified by build or smoke testing:

| Check | Before | After |
|---|---:|---:|
| `portfolio.csv` rows | 4 | 4 |
| SHA-256 | `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` | `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |

## Known Limitations

- The allowlist intentionally packages only the project-wide Streamlit config.
  Runtime credentials must remain outside release artefacts and be supplied by
  the user through the supported local runtime configuration path.
- This sprint does not provide secret scanning for arbitrary binary payloads;
  it prevents the identified inclusion path with explicit source and package
  allowlists plus regression tests.

Sprint 4.1.2.2 is complete. Sprint 5 has not started.
