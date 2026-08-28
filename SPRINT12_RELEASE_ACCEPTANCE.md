# Sprint 12 Release Acceptance

## Status

Sprint 12 正式候選已發布，等待 CTO 獨立 Release Acceptance。

## Release Scope

This release promotion did not modify Python product logic, strategy behavior, backtest semantics, UI behavior, or real user data. The only implementation change is the rollback-first Windows promotion procedure and its focused release-layout regression test.

Modified files:

- publish_release.bat
- tests/test_release_layout.py
- AGENTS.md
- README.md
- CHANGELOG.md
- SPRINT12_RELEASE_ACCEPTANCE.md

No Sprint 13 work was started.

## Pre-release Artifact Verification

Accepted staging artifact before promotion:

- Staging path: release/staging/StockTool/StockTool.exe
- Size: 24,063,733 bytes
- Last write UTC: 2026-07-18T14:30:41.9396264Z
- SHA-256: AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F

Pre-release formal artifact:

- Formal path: release/StockTool/StockTool.exe
- Size: 24,038,929 bytes
- Last write UTC: 2026-07-18T09:31:24.9739830Z
- SHA-256: 4CA2C7675DD9C3E9DA6DD8E807D425F494243EF74D677B0271927EC4C2FF76FA

Accepted Sprint 12 source archive:

- Path: release/baseline/stocktool-sprint12-20260718-source.zip
- SHA-256: D209A8357523D0ABC8FA4C481E284B9684EE67D97900C1D30E8425044257E357
- SHA-256 sidecar matched the archive before promotion.

The staging EXE and source archive matched the values recorded in SPRINT12_ACCEPTANCE.md. There were no StockTool processes and no 8501/8502 listener before promotion.

## Rollback-first Promotion

The former promotion script depended on the fixed release/previous/StockTool path. Because that path already existed, it could not safely serve as this release's rollback destination.

The updated promotion flow:

1. validates the public assets in staging and the current formal release;
2. calculates the current formal and staging EXE hashes;
3. creates a unique timestamp rollback directory with robocopy;
4. validates the rollback public assets and confirms its EXE hash equals the pre-release formal EXE hash;
5. moves the old formal directory into a unique non-destructive promotion hold;
6. moves staging into release/StockTool;
7. validates public assets and compares the promoted EXE hash to the staging EXE hash;
8. automatically returns the candidate to staging and restores the held formal directory if the promotion asset or hash validation fails.

Collision policy: a pre-existing rollback or promotion-hold destination stops promotion without overwriting any existing folder.

Rollback backup:

- Path: release/rollback/StockTool-pre-sprint12-release-20260719-233024
- Rollback EXE SHA-256: 4CA2C7675DD9C3E9DA6DD8E807D425F494243EF74D677B0271927EC4C2FF76FA
- Required release assets: validated
- Additional promotion hold retained: release/promotion-hold/StockTool-pre-sprint12-release-20260719-233024

Actual promotion command:

    cmd /c publish_release.bat

## Formal Release Result

- Formal path: release/StockTool/StockTool.exe
- Version: 1.2.2
- Size: 24,063,733 bytes
- Last write UTC: 2026-07-18T14:30:41.9396264Z
- SHA-256: AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F
- Matches accepted staging EXE: yes

The formal release contains the required public files and data/sample directory. It was promoted as a full directory, not as a single EXE overwrite.

## Focused Release Tests and Quality

Commands:

    .\.venv\Scripts\python.exe -m pytest tests/test_release_layout.py tests/test_release_assets.py tests/test_launcher.py -q
    .\.venv\Scripts\python.exe -m black --check tests/test_release_layout.py
    .\.venv\Scripts\python.exe -m ruff check tests/test_release_layout.py
    .\.venv\Scripts\python.exe -m mypy --ignore-missing-imports tests/test_release_layout.py

Results:

- focused release tests: 12 passed
- Black: passed
- Ruff: passed
- mypy: Success: no issues found in 1 source file

The test verifies the new unique rollback destination, collision check, rollback copy, non-destructive promotion hold, recovery branch, and isolated post-promotion smoke hook. Full pytest and EXE build were not repeated because this was a release-only script/documentation patch and the accepted Sprint 12 implementation artifact was reused unchanged.

## Formal EXE Smoke Test

The formal EXE was started with a new isolated STOCK_TOOL_USER_DATA_DIR.

- EXE launched successfully.
- Version command returned 1.2.2.
- http://localhost:8501/_stcore/health returned HTTP 200 with body ok.
- Homepage returned HTTP 200.
- Isolated reports/, logs/, and data/cache/ were writable.
- The bundled registry reports six strategies; the tested Strategy Health renderer remains present through the Sprint 12 targeted regression tests.
- The full StockTool process tree was terminated after testing.
- Remaining StockTool process count: 0.
- Remaining 8501/8502 listener count: 0.
- The isolated smoke runtime directory was removed.

## Privacy Scan

The formal release scan found:

- forbidden file/runtime paths: 0
- real .env, secrets TOML, portfolio.csv, watchlist.csv, stock_data.sqlite: none
- root-level reports/, logs/, and data/cache/: none
- high-confidence private-key, AWS key, GitHub token, OpenAI key, and Bearer credential patterns: 0
- packaged Streamlit configuration: only _internal/.streamlit/config.toml
- .env.example contains only the approved public path defaults and blank optional provider settings.

The scan reports paths and pattern categories only; it does not output possible secret values.

## User Data Integrity

The following real paths were inspected read-only before and after promotion:

| Item | Status before and after |
| --- | --- |
| portfolio.csv | exists, 4 data rows, 131 bytes, SHA-256 A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6 |
| watchlist.csv | absent |
| stock_data.sqlite | exists, 315,392 bytes, SHA-256 FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C |
| settings.json | absent |

All before/after states are identical. No real portfolio, watchlist, SQLite, settings, cache, report, or log content was opened, migrated, moved, overwritten, or used by smoke tests.

## Desktop Shortcut

- Path: C:/Users/steve/OneDrive/Desktop/股票分析工具.lnk
- TargetPath: C:/Users/steve/OneDrive/Documents/股票/release/StockTool/StockTool.exe
- WorkingDirectory: C:/Users/steve/OneDrive/Documents/股票/release/StockTool
- Target and working directory verification: passed
- A duplicate shortcut was not created.

## Rollback

To return to the pre-Sprint 12 formal release, after ensuring StockTool is closed, preserve the current release directory and restore:

    release/rollback/StockTool-pre-sprint12-release-20260719-233024

back to:

    release/StockTool

The rollback copy has the validated pre-release EXE hash shown above. The separate promotion-hold directory is retained as an additional non-destructive recovery copy. Existing release/previous, release/rollback, and baseline history were not removed or overwritten.

## Known Limitations

- The promotion script now invokes an isolated post-promotion HTTP/writeability smoke and routes a failure to the same automatic restoration branch. The formal promotion completed before this final script guard was added; its equivalent isolated smoke was separately executed and passed. Future promotions use the script-owned guard.
- No code signing or antivirus reputation workflow is included.
- The accepted Sprint 12 source archive remains the implementation baseline. This release record and the rollback-first script/documentation update are release-governance artifacts, not a rebuilt product candidate.

## Release.1 Corrective Patch

### Status

Sprint 12 Release.1 implementation is complete and waiting for CTO re-acceptance. Sprint 13 was not started.

### Root Cause and Fix

The rollback-first promotion update omitted the existing legacy release user-data migration call. A legacy portfolio, watchlist, processed database, cache, report, or log still located under the old formal release could therefore be moved into the promotion-hold directory before `StockTool` had created its migration manifest in canonical user-data storage.

`publish_release.bat` now calls:

```text
prepare_release_user_data_migration(legacy_root=Path(r'%RELEASE_DIR%'))
```

only after rollback assets and the rollback EXE hash have been validated, and before:

```text
move "%RELEASE_DIR%" "%PROMOTION_HOLD%"
```

The call is fail closed. A migration error, invalid legacy item, failed validation, or missing manifest returns a non-zero Python exit code; the batch script exits before moving the formal release or promoting staging. The runtime migration already preserves non-empty canonical user-data targets as `skipped_existing`, so existing user data is not overwritten.

Modified files for Release.1:

- `publish_release.bat`
- `tests/test_runtime_paths.py`
- `SPRINT12_RELEASE_ACCEPTANCE.md`

The obsolete `%PREVIOUS_DIR%` ordering assertion was replaced with `%PROMOTION_HOLD%`. The regression also verifies that rollback verification precedes migration, migration precedes the formal-release move, migration failure is fail closed, and the fixed `release/previous/StockTool` rollback path is not reintroduced. Existing runtime-path migration tests continue to prove that canonical portfolio data is not overwritten and that invalid legacy data blocks cleanup.

### Re-verified Tests and Quality Checks

Commands executed:

```text
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_paths.py tests/test_release_layout.py tests/test_release_assets.py tests/test_launcher.py -q
.\.venv\Scripts\python.exe -m pytest -o addopts='' --disable-warnings
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing -q
.\.venv\Scripts\python.exe -m black --check tests/test_runtime_paths.py
.\.venv\Scripts\python.exe -m ruff check tests/test_runtime_paths.py
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports tests/test_runtime_paths.py
```

Results:

- release and runtime migration focused tests: 20 passed
- full pytest: 573 passed in 61.75s
- branch coverage: 81.18% (configured gate: 78.50%)
- Black: passed
- Ruff: passed
- mypy: `Success: no issues found in 1 source file`

The migration and promotion tests use temporary paths only. `publish_release.bat` was not executed during this corrective patch, so no real user-data migration, EXE promotion, or formal-release directory exchange occurred.

### Formal EXE and User-data Integrity

No EXE was rebuilt or replaced.

- Formal EXE: `release/StockTool/StockTool.exe`
- Size: 24,063,733 bytes
- Last write UTC: 2026-07-18T14:30:41.9396264Z
- SHA-256 before and after: `AD23B297EBDADF2247F80C8346FF080C7DFBBFC12BFC46FB5B128E4087546F5F`

Read-only before/after verification of real user data:

| Item | Result |
| --- | --- |
| `portfolio.csv` | exists; 4 data rows; 131 bytes; SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `watchlist.csv` | absent before and after |
| `stock_data.sqlite` | exists; 315,392 bytes; SHA-256 `FDF103AD3131A4A136211913B662C0C4D2EF8E90A28C9A0DAB4483538A47F30C` |
| `settings.json` | absent before and after |

All recorded states are identical. No real user portfolio, watchlist, SQLite database, settings, cache, reports, or logs were opened for mutation, migrated, moved, overwritten, or deleted. No rollback, promotion-hold, previous, baseline, staging, or formal release directory was deleted or replaced.
