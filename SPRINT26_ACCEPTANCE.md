# Sprint 26 implementation evidence

Status: implementation evidence ready for independent CTO acceptance. This file does not
declare CTO acceptance, release approval, signing, promotion, or a new Sprint.

## Checkpoint and scope

- Sprint 25.1.1.1 checkpoint commit: `5ff8e6e4a84b9d41dde3e613925d63879fb092cb`
- Annotated tag: `sprint25.1.1.1-accepted-2026-08-08`
- Sprint 26 implementation uses the existing DailyBrief, DailyRefresh, DailyResearchLoop,
  DailyResearchAssistant and MarketMonitor services. No new provider, dependency, scheduler,
  background poller, or formal release was added.
- The pre-existing root `artifacts_sprint25_1_1_quality.log` remains untracked and is excluded
  from the source archive and checkpoint; it was not deleted or modified.

## Product implementation

- Added `src/stock_tool/application/daily_research_brief.py` with bounded,
  market-qualified portfolio/watchlist deduplication, deterministic evidence-chain items,
  fact/inference/risk separation, citation checks, stable content fingerprint, schema-versioned
  manifest, atomic JSON/HTML storage, corrupt-cache rejection, and deterministic fallback when
  the assistant is unavailable.
- Added private runtime paths for the latest JSON evidence and HTML report.
- Added the explicit Home action `產生今日研究簡報`; render is read-only and the action is the
  only path that generates or refreshes the brief. JSON and HTML downloads are private-runtime
  exports and are escaped/privacy-safe.
- Integrated typed Home/Shell dependencies without duplicating provider or research-loop logic.
- Updated the roadmap with Sprint 26 scope, non-goals, rollback and Sprint 26.1 scheduling direction.

## Automated verification

The complete `cmd /c quality_gate.bat` replay finished with exit code 0. The canonical output is
`artifacts/sprint26/quality-gate-final2.log`; the Sprint 26 targeted replay is
`artifacts/sprint26/targeted-tests-final.log`.

- Targeted daily brief/Home/Shell/assistant tests: passed.
- Full pytest: **1116 passed, 2 skipped, 2 warnings**.
- Branch coverage: **83.13%** (gate 78.5%).
- Black: passed; Ruff: passed; focused mypy: passed; compileall: passed.
- Project privacy scan: **0 violations**; release layout and regression baseline: passed.
- `pip check`: exit 0, no broken requirements.
- Official `.venv` `pip-audit`: exit 0, no known vulnerabilities; no ignore/skip list was used.
- Performance hard gate: `artifacts/sprint26/performance-final-candidate.json`, three runs per
  measurement, passed. The canonical history at
  `artifacts/sprint26/performance-canonical.json` retains the historical Excel 6.444-second
  failure and points `canonical_current` to `sprint26-final-candidate-replay`.
- `git diff --check`: passed.

## Candidate and source artifacts

The candidate was built only in `release/staging-sprint26`; formal `release/StockTool` was not
written. Hash binding is in `artifacts/sprint26/candidate-hash-binding.json`, guarded EXE
health/version evidence is in `artifacts/sprint26/exe-smoke-summary.json`, and browser binding
is in `artifacts/sprint26/browser-result.json`.

| Artifact | SHA-256 |
|---|---|
| staging stable EXE | `95FDF602CE3140FCC938B2853B57759546A86048E8EF1B732C52610FDAC691C5` |
| staging 1.2.2 payload | `EC975777B80F25C0A7F462055FFE95DF8F7FBEA0F6C3D4D095C3268CCAA3F233` |
| Sprint 26 source ZIP | `6F642A65A7A285D27EE21176B9E0ADE9D9BCDD4AA9727FBB13552B91EE96BFAE` |
| formal `release/StockTool/StockTool.exe` | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

Source archive verification (`artifacts/sprint26/source-extracted-final`): missing required inputs 0,
forbidden entries 0, content mismatches 0, duplicate entries 0. The forbidden root quality log
is absent from the ZIP. Candidate version checks reported `1.2.2`; guarded health smoke reported
ready and HTTP health success for the isolated candidate.

## Browser evidence

`artifacts/sprint26/browser-result.json` binds all evidence to the final stable, payload and source
hashes. Four in-app browser scenarios were captured through the candidate started by
`scripts/evidence_launcher.py` and `browser_transport_harness.py`:

- first brief/no previous snapshot: screenshot, DOM, active console and transport evidence;
- isolated portfolio/watchlist change: market-qualified holdings and missing-data explanations;
- offline update: safe partial fallback and no render-time network request;
- partial provider failure: blocked Yahoo endpoints, preserved content and explicit update-failed
  explanation.

All four guard results passed with real-data file count 191 before/after, zero diff, and verified
candidate process/listener cleanup. Active console error count was 0 in every captured scenario.
Screenshot SHA-256 values are recorded per scenario in `browser-result.json`.

CUA keyboard best-effort evidence sent eight `TAB` and three `SHIFT+TAB` events; the evidence is
`artifacts/sprint26/browser/keyboard-focus.json` with its guarded cleanup result. The Streamlit
shell did not expose a stable focused element in the DOM snapshot, so no focus pass is claimed.

Native Chrome 100%/125%/150% zoom was not replayed by the available in-app control and is therefore
explicitly `deferred_to_formal_release`; no viewport resize or synthetic zoom evidence was used.

## Real-data preservation and cleanup

- Read-only manifests: `artifacts/sprint26/real-data-before.json` and
  `artifacts/sprint26/real-data-after.json` (real-root label redacted); comparison:
  `artifacts/sprint26/real-data-diff.json`.
- Result: file count **191 -> 191**, `added=[]`, `removed=[]`, `changed=[]`, `zero_diff=true`.
- Candidate guard results independently report the same zero-diff result for every browser and
  performance run.
- After evidence: StockTool/StockToolPayload process count 0 and TCP listeners 8501/8502 count 0.
- No formal EXE, installer, signing state, user data, portfolio, watchlist, research library or
  report was modified. No Sprint 26 commit/tag, push, PR or publication was created.

## Known limitations / rollback

- Native browser zoom remains deferred as stated above; this is not substituted with an AppTest or
  resized viewport.
- AI/provider unavailability is intentionally represented by deterministic rule-based output and
  partial/unavailable status. A failed generation leaves the last successful stored brief intact.
- Rollback is removal of the isolated Sprint 26 candidate and its private runtime directory; the
  formal v1.2.2 release and the Sprint 25.1.1.1 checkpoint remain untouched.
