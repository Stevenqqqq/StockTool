# Sprint 16 Acceptance

**Status:** Implementation complete, with a staging-baseline preservation issue requiring independent CTO review before acceptance or any release decision.

## Scope

Sprint 16 adds an evidence-linked daily research brief to the Research Home. It is limited to a bounded OpenAI-compatible provider contract, a deterministic local fallback, citations, latest-successful-AI-note caching, and Home integration. It does not place orders, generate buy/sell instructions, predict returns, change deterministic metrics, change the portfolio or watchlist, or promote the formal release.

## Contracts and Design

- `EvidenceRecord` and immutable `EvidenceBundle` are market-qualified (`symbol + market`) and have deterministic fingerprints.
- `Citation` is copied only from an evidence record. A model cannot introduce a new evidence ID, URL, excerpt, or source.
- `ResearchClaim` distinguishes `FACT`, `CALCULATION`, `INFERENCE`, `MISSING`, and `WARNING`.
- `FACT` requires a citation and must reproduce the cited evidence text exactly. Unsourced or paraphrased model output is rejected rather than being presented as a fact.
- `AIResearchNote` is a bounded, serializable structured result. `ResearchAssistantResult` is represented by the validated note plus explicit mode and warnings.
- `OpenAICompatibleProvider` reads only `STOCK_TOOL_AI_BASE_URL`, `STOCK_TOOL_AI_API_KEY`, and `STOCK_TOOL_AI_MODEL` from the process environment. The key is never serialized, logged, cached, reported, or packaged.
- `AIResearchAssistant` falls back to deterministic local rules for absent configuration, offline failures, timeouts, HTTP 429/500 responses, invalid JSON, invalid schemas, invented citations, prompt-injection content, or unsupported claim semantics.
- `ResearchAssistantCache` uses runtime `data/ai_research/`, schema version `1`, atomic JSON writes, one latest successful **AI** note per canonical identity, and a snapshot/evidence fingerprint. Local fallback output cannot overwrite a successful cached AI note.
- `DailyResearchAssistantService` selects at most three explicit Daily Brief candidates and only uses already-built snapshots, cached notes, and existing Daily Brief items. It performs no provider fetch and never mutates holdings or watchlists.

## UI Behavior

Research Home now includes **今日 AI 研究簡報**. It shows generation time, mode, coverage, citation count, confidence, bounded report sections, limitations, citations, a full-research CTA, and an explicit regenerate control.

When no AI provider is configured, the UI states that it is using **本機規則模式** and does not imply that the local rules are AI-generated. The displayed wording remains research-only and contains no buy/sell instruction, target price, or return forecast.

## Modified and Added Files

- `src/stock_tool/research/__init__.py`
- `src/stock_tool/research/evidence.py`
- `src/stock_tool/research/citations.py`
- `src/stock_tool/research/assistant.py`
- `src/stock_tool/dashboard/components/research_assistant.py`
- `src/stock_tool/dashboard/pages/home.py`
- `src/stock_tool/dashboard/state.py`
- `src/stock_tool/dashboard/shell.py`
- `src/stock_tool/dashboard/app.py`
- `src/stock_tool/runtime_paths.py`
- `build_exe.bat`
- `.env.example`
- `README.md`
- `tests/test_research_assistant.py`
- `tests/test_ai_citation_policy.py`
- `tests/test_ai_fallback.py`
- `tests/test_research_assistant_dashboard.py`
- `tests/test_dashboard_shell.py`

## Tests and Quality Checks

The initial RED proof was collection failure for the new test modules before `stock_tool.research` existed. Final commands used the project virtual environment.

| Check | Command / scope | Result |
| --- | --- | --- |
| Sprint 16 targeted | `python -m pytest tests/test_research_assistant.py tests/test_ai_citation_policy.py tests/test_ai_fallback.py tests/test_research_assistant_dashboard.py tests/test_dashboard_shell.py tests/test_dashboard_navigation.py tests/test_daily_brief.py tests/test_daily_home.py tests/test_daily_research_loop.py tests/test_research_workspace.py tests/test_serenity_agent.py tests/test_release_layout.py tests/test_release_assets.py tests/test_runtime_paths.py -q` | `118 passed` |
| Focused assistant/dashboard target | `python -m pytest tests/test_research_assistant.py tests/test_ai_citation_policy.py tests/test_ai_fallback.py tests/test_research_assistant_dashboard.py tests/test_dashboard_shell.py -q` | `34 passed` |
| Full suite | `python -m pytest -q` | `699 passed` |
| Branch coverage | `python -m pytest --cov --cov-branch --cov-report=term-missing` | `699 passed`; `82.14%` total, above the `78.50%` gate |
| Black | `python -m black --check` on 15 changed Sprint 16 source/test files | Passed; `15 files would be left unchanged` |
| Ruff | `python -m ruff check` on the same 15 files | `All checks passed!` |
| Mypy | `python -m mypy --ignore-missing-imports` on the nine changed production source files | `Success: no issues found in 9 source files` |
| Compile | `python -m compileall -q src/stock_tool` | Passed |

Regression coverage includes deterministic metric immutability, FACT/citation enforcement, unknown citation rejection, stale/conflicting evidence warnings, fallback paths, prompt-injection rejection, no key serialization, fingerprint cache reuse/invalidation, corrupt cache behavior, failure preservation, market-qualified candidate selection, non-mutating portfolio/watchlist behavior, and Home CTA integration.

## Staging EXE and UI Smoke

Candidate staging package:

- Path: `release/staging-sprint16/StockTool/StockTool.exe`
- Size: `24,187,924` bytes
- Modified: `2026-07-27T02:13:04.1285437+08:00`
- SHA-256: `DE140A1CB5BC3041A3DDC48428278773B3586F61A3F3BB0BA7277784488EAFB8`

All smoke work used fresh isolated `STOCK_TOOL_USER_DATA_DIR` folders.

- `/_stcore/health` returned HTTP `200` with body `ok`.
- Home returned HTTP `200`.
- `reports/`, `logs/`, `data/cache/`, and `data/ai_research/` accepted isolated writes.
- Browser journey passed: Home -> `研究 2330` -> Research Workspace -> `返回今天先看這些` -> Home -> `產生今日 AI 研究簡報` -> local-rule cited brief -> `查看完整研究` -> 2330 Research Workspace.
- The generated local brief showed explicit `本機規則模式`, 20 citations, FACT/CALCULATION/INFERENCE/WARNING separation, and no trading instruction.
- The six primary workspaces remained present in the packaged Home navigation: 研究首頁, 探索, 策略, 持倉, 研究庫, 設定.
- All StockTool processes and 8501/8502 listeners were closed after the smoke checks.

The direct `build_exe.bat` invocation generated the PyInstaller candidate but returned a non-zero wrapper status after PyInstaller reported a successful build; allowlisted public assets were then copied and validated using the existing `release_assets` helper. The resulting candidate passes the runtime smoke. This wrapper exit-status inconsistency is recorded for independent review and was not hidden by a release promotion.

## Privacy and Real User Data Integrity

Staging release asset validation passed. The staging scan found zero forbidden runtime files and `project_privacy_violations()` returned zero content findings. Only the packaged `.streamlit/config.toml` was present; no `secrets*.toml` was found.

No real user data was used for tests or smoke work. Before/after values remained unchanged:

| Item | State |
| --- | --- |
| `portfolio.csv` | Exists; 4 rows; 131 bytes; SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` |
| `watchlist.csv` | Does not exist |
| `stock_data.sqlite` | Exists; 716,800 bytes; SHA-256 `FD563A543FE847FA09AB61CEBA947BBFCE04272836EDB46B5FE714CB337E1293` |
| `settings.json` | Does not exist |

The isolated smoke directories could not be deleted automatically because the execution environment rejected the verified cleanup command. They remain under `%TEMP%` only; no real runtime directory was changed.

## Source Archive

- Path: `release/baseline/stocktool-sprint16-20260727-source.zip`
- Entries: `277`
- Size: `2,347,060` bytes
- SHA-256: `C093ECCBB198F3CEE082DC16B97161EB3A127EE5244F5EBB1588A18380C6076A`
- Sidecar: `release/baseline/stocktool-sprint16-20260727-source.zip.sha256`, verified equal to the ZIP hash.
- `verify_source_archive(archive_path=..., extracted_root=...)`: required build inputs missing `0`; forbidden entries `0`; content mismatches `0`.

## Rollback and Formal Release

`release/StockTool/StockTool.exe` was not modified:

- SHA-256: `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`

No formal release promotion was performed. The intended Sprint 15.1.3.1 staging rollback baseline was accidentally overwritten by an earlier misquoted build invocation before the isolated staging override was corrected. Its recorded accepted EXE SHA-256 was `D6768755523E3040330CBF04B0BCA0BBB5B639D923C252FFD953A5C3853C2E03`; no matching local EXE remained after the incident. The pre-existing Sprint 15.1.3.1 source archive was not modified. This is a release-boundary violation: CTO should decide whether to restore that staging binary from external version history or explicitly re-baseline before accepting Sprint 16. It does not affect the untouched formal release.

## Known Limits

- The first version has no automatic scheduler, notifications, full Research Library, vector database, local model installation, or multi-agent orchestration.
- AI availability depends on an explicitly configured compatible endpoint; StockTool remains usable without it through deterministic local rules.
- AI cache stores only the latest successful AI note per market-qualified symbol; fallback summaries are intentionally not persisted as successful AI notes.
- The local rule summary does not create evidence beyond existing structured data and must not be interpreted as external AI analysis.
- The existing build wrapper’s final exit status and the overwritten historic staging baseline must be addressed before an independent acceptance decision or release action.

## Acceptance Position

Sprint 16 implementation and isolated staging functional validation are complete. Formal release remains untouched. Independent CTO review is required, including explicit disposition of the staging-baseline preservation incident. Sprint 17 has not started.
