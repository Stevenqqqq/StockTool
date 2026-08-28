# Sprint 9 Implementation Handoff

Status: Implementation complete and ready for independent acceptance review.

## Scope

Sprint 9 implements the approved industry-chain, concept, and document-evidence scope only. It does not change scoring formulas, backtest execution, risk management, portfolio formulas, provider behavior, or introduce Sprint 10 functionality.

## Delivered Architecture

- Added `003_concept_evidence.sql`, an additive migration for concept aliases, dataset version, relation confidence, verification date, and an evidence lookup index. Existing canonical concept/relation tables remain in place.
- Added `ConceptRepository`, backed by the existing `ResearchRepository`, with exact alias resolution, canonical `symbol + market` identity, relation-type validation, idempotent bundled-dataset seeding, and provenance-aware confidence caps.
- Added shipped, versioned concept seed data at `data/sample/concepts/`. It is explicitly marked `manual_seed`; no relation is presented as externally verified merely because it is a bundled hint.
- Added five canonical relation categories: `core_manufacturing`, `equipment_materials`, `design_platform`, `downstream_demand`, and `indirect_beneficiary`.
- Updated Company Research and Serenity research paths to consume canonical relations when supplied. Legacy rule hints remain compatibility-only and are visibly limited as unverified.
- Added page-aware PDF extraction and summary citations. UI rendering exposes page number, offset, and a bounded original-text excerpt without persisting raw PDF content.
- Added the Discovery component within the existing Explore / concept lookup path. It uses exact canonical key or alias resolution only; it does not promote fuzzy text matching into verified evidence.

## Modified and Added Files

- `src/stock_tool/concept_repository.py`
- `src/stock_tool/data/repositories.py`
- `src/stock_tool/data/migrations/003_concept_evidence.sql`
- `src/stock_tool/company_research.py`
- `src/stock_tool/serenity_agent.py`
- `src/stock_tool/research_reports.py`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/dashboard/pages/discovery.py`
- `data/sample/concepts/concepts.json`
- `data/sample/concepts/relations.json`
- `tests/test_concept_relations.py`
- `tests/test_discovery.py`
- `tests/test_report_citations.py`
- `tests/test_dashboard.py`
- `tests/test_database_migrations.py`
- `tests/test_ingestion_migration.py`
- `tests/fixtures/concepts/concepts.json`
- `tests/fixtures/concepts/relations.json`
- `tests/fixtures/reports/fixture.pdf`
- `README.md`

## Evidence and Safety Semantics

- Canonical relations always use market-qualified identity. The same ticker in different markets does not match or overwrite another market's relation.
- Relation confidence is capped below `0.75` when evidence, a source URL, or a non-manual source is absent.
- `manual_seed` is an explicit source type, not external confirmation. Bundled data is seeded only into an empty canonical concept store and does not overwrite an existing store.
- PDF citations identify the source document, page number, local character offset, and a bounded excerpt. Claims without an extractable page are treated as unavailable rather than fabricated.
- The Discovery UI separates source and verification status from research interpretation. It is research support, not a trade instruction.

## Test Results

Commands were executed with an isolated `STOCK_TOOL_USER_DATA_DIR` for the final suite.

| Check | Command / scope | Result |
| --- | --- | --- |
| Sprint 9 targeted tests | `tests/test_dashboard.py tests/test_concept_relations.py tests/test_discovery.py tests/test_report_citations.py` | `43 passed` |
| Full pytest with branch coverage | `python -m pytest -o addopts='' --cov=stock_tool --cov-branch --cov-report=term -q` | `436 passed` |
| Branch coverage | Full suite | `80.05%` (gate: `79.80%`) |
| Black | 13 changed Python files | Passed; `13 files would be left unchanged` |
| Ruff | Same 13 changed Python files | `All checks passed!` |
| mypy | 9 focused typed source/test files with `--ignore-missing-imports` | `Success: no issues found in 9 source files` |

The SQL migration was intentionally excluded from Black/Ruff because those tools parse Python, not SQL.

## EXE Build and Smoke Test

Build used `build_exe.bat` and the existing staging-first flow. After smoke validation, the staging directory was manually promoted into `release/StockTool`; the pre-existing `release/previous/StockTool` was first preserved as `release/previous/StockTool-pre-sprint9-20260715-063923`.

| Item | Value |
| --- | --- |
| EXE | `release/StockTool/StockTool.exe` |
| Version | `1.1.0` |
| Modified | `2026-07-15 06:35:18 +08:00` |
| Size | `23,925,400` bytes |
| SHA-256 | `052CEF978EB8668B65E2300BBD6F89BE062A56CDAE4E715D663628F7B945846A` |
| Health smoke | `8501`: HTTP 200 / `ok` |
| Fallback smoke | With 8501 held, launcher used `8502`: HTTP 200 / `ok` |
| Runtime writes | Isolated `reports`, `logs`, and `data/cache` directories writable |
| Cleanup | No StockTool process or listener on 8501, 8502, or 8510 remained |

## Release Privacy Scan

- Required public assets are present: EXE, README, `.env.example`, simple usage guide, launch batch file, and the bundled sample concept dataset.
- The release contains `.streamlit/config.toml` only; no `secrets*.toml` was found.
- No true `.env`, token-named file, API-key-named file, `portfolio.csv`, `watchlist.csv`, runtime reports, logs, or cache was found.
- The first broad extension scan encountered `_internal/certifi/cacert.pem`. This is the public Certifi CA bundle, not a private key; the final policy scan excluded that known public dependency and found zero forbidden entries.

## User Data Integrity

The real portfolio and watchlist were read only for verification:

| Item | Before / after |
| --- | --- |
| `%LOCALAPPDATA%/StockTool/data/portfolio.csv` | Present; 4 data rows; SHA-256 unchanged: `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `%LOCALAPPDATA%/StockTool/data/watchlist.csv` | Absent before and after |

### Data-safety exception requiring independent review

During an earlier failed full-test run, before the dashboard regression test was isolated from `DEFAULT_DATABASE`, bundled concept seeding wrote to the real runtime SQLite database at `%LOCALAPPDATA%/StockTool/data/processed/stock_data.sqlite`. A subsequent read-only inspection observed 4 concept rows and 6 relation rows. The test was then corrected to use a temporary database for all later runs.

No portfolio or watchlist content changed. This runtime SQLite write was not automatically removed or restored because this Sprint must not modify real user data. Independent acceptance must decide whether those seeded rows should be retained or explicitly reverted with the user's approval.

## Source Archive

| Item | Value |
| --- | --- |
| Archive | `release/baseline/stocktool-sprint9-20260715-source.zip` |
| Sidecar | `release/baseline/stocktool-sprint9-20260715-source.zip.sha256` |
| Entries | `217` |
| SHA-256 | `9F1359B777E28249DAF17C76A794334214A46DBF15B163B25B847A12F0E6B245` |
| Required build inputs missing | `0` |
| Forbidden archive entries | `0` |
| Extracted content mismatches | `0` |

The archive includes the required source, migrations, tests, sample concept data, build inputs, and allowlisted `.streamlit/config.toml`; it excludes release artifacts, runtime data, caches, logs, reports, `.env`, secrets, portfolio, watchlist, bytecode, and tool caches.

## Known Limitations

- Concept seed data is intentionally a small, manually maintained research dataset. It is not a complete industry universe or a live third-party classification feed.
- A relation's confidence and citation quality depend on its stored source metadata. The system correctly distinguishes seed knowledge from externally supported evidence but does not yet provide a document-ingestion workflow for bulk evidence curation.
- The Discovery UI uses exact key/alias matching to preserve precision. Broader semantic search remains out of scope.
- The runtime SQLite seed incident documented above requires an explicit user-approved cleanup decision before a strict data-safety sign-off.
- Sprint 10 has not started.
