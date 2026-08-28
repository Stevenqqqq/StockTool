# Sprint 24 implementation evidence

## Status

**BLOCKED — not CTO acceptance.** The Research Context implementation and automated
quality gates are complete, but this evidence run cannot be reported as complete:

1. A direct candidate launch was made before the isolation guard was used. It created
   three additional real-user-data files at `03:49:20`; they are preserved and are
   recorded in `artifacts/sprint24/incident-real-data-launch.json`. This is not rewritten
   as zero-diff history.
2. The browser screenshots were captured before the final source-bound rebuild, so
   `artifacts/sprint24/browser/browser-result.json` marks them as non-final-candidate
   evidence. Native zoom and reliable Tab/Shift+Tab evidence remain unavailable.

## Phase A checkpoint

- Checkpoint commit: `2687519bda723bd75488283fcb431edc14929ff5`
- Annotated tag: `sprint23-accepted-2026-08-03`
- The checkpoint contains the previously accepted Sprint 23 source/docs/tests and
  normalized user-supplied Chrome evidence; no push or PR was made.
- The Sprint 24 worktree changes remain uncommitted as required.

## Sprint 24 changes

- `src/stock_tool/application/research_context.py`: immutable canonical
  market-qualified context, strict route/action validation, deterministic serialization,
  and one-shot FIFO queue.
- `src/stock_tool/application/__init__.py`: application exports.
- `src/stock_tool/dashboard/state.py`: centralized queue initialization, enqueue/peek/
  consume helpers and malformed-state reset.
- `src/stock_tool/dashboard/shell.py`: typed Explore/Library/Research/Strategy/Holdings
  routes, destination-scoped consumption, identity and snapshot/as-of fail-closed checks,
  and no-fetch/no-mutation handoff behavior.
- `src/stock_tool/dashboard/pages/research.py`: explicit Strategy/Holdings/Library
  handoff controls.
- `src/stock_tool/dashboard/pages/library.py`: typed current-data callback with legacy
  compatibility fallback.
- `src/stock_tool/dashboard/pages/strategy_workspace.py`: typed return-to-research action
  and navigation helper use.
- `src/stock_tool/dashboard/pages/portfolio_workspace.py`: non-mutating research focus
  action for a selected market-qualified holding.
- `src/stock_tool/quality_gate.py`: Sprint 24 source and targeted tests included in the
  existing Black/Ruff/quality-gate scope.
- `PRODUCT_EXECUTION_PLAN.md`: Sprint 24 extension outside the historical fenced diagram,
  pending independent CTO acceptance; Sprint 20–22 local validation and Sprint 23 pending
  acceptance are explicitly not public release claims.
- `tests/test_research_context.py`, `tests/test_research_handoff.py`, and roadmap tests.

## Automated verification

- Sprint24 targeted context/handoff/dashboard regressions: passed.
- Full pytest: **1071 passed, 2 skipped**, 2 expected warnings.
- Branch coverage: **83.04%** (configured gate 78.50%).
- `cmd /c quality_gate.bat`: exit 0; all ten steps passed.
- Black: passed.
- Ruff: passed.
- Focused mypy: passed for 9 Sprint24 source modules.
- `compileall`: exit 0.
- `pip check`: no broken requirements.
- Official `.venv` `pip-audit --format=json`: exit 0; no known vulnerabilities.
- Project privacy scan: 0 violations.
- Release source-layout validation: passed.
- `git diff --check`: passed.
- Performance hard gate: passed; `artifacts/sprint24/performance-result-final.json`.

## Candidate and source evidence

- Stable candidate: `release/staging-sprint24/StockTool/StockTool.exe`
  - SHA-256 `8898F404D642D1B3A06B5C396220F665111485756D60DC2E2BF7B2CD125ED92D`
  - version `1.2.2`
- Versioned payload: `release/staging-sprint24/StockTool/versions/1.2.2/StockToolPayload.exe`
  - SHA-256 `02C915DD7E373EE21D58B75394F76B17B95F0DFEE3C77A852D62FAAC1AEC0297`
  - version `1.2.2`
- Source archive: `artifacts/sprint24/sprint24-source.zip`
  - SHA-256 `8F2EDED045510D5FAEE98A31E1919CB504E47CA30B471A2E41A99E51CBF8CE9E`
  - independent verification: missing 0, forbidden 0, content mismatches 0, duplicates 0.
- Hash binding: `artifacts/sprint24/candidate-hashes.json` and its source sidecar.
- Formal `release/StockTool/StockTool.exe` remained SHA-256
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- Guarded final EXE health smoke: `artifacts/sprint24/exe-smoke-final/guard-result.json`;
  status passed, health ready, cleanup verified, no 8501/8502 listeners.

## Browser best effort

- A real in-app browser loaded `http://127.0.0.1:8501/` under a guard-created data root.
- Explore and Strategy DOM/screenshot captures exist under `artifacts/sprint24/browser/`;
  active console error count was 0.
- The radio control was not reliably operable through the available browser surface for
  the remaining routes; native zoom and Tab/Shift+Tab were not proven.
- `artifacts/sprint24/browser/browser-result.json` is explicitly partial and binds the
  capture hashes separately from the final candidate hashes. It does not claim acceptance.

## Real-data preservation

- Current read-only state is 191 files. Guarded online, final candidate, and browser runs
  each recorded 191 → 191 with `added=[]`, `removed=[]`, `changed=[]`, `zero_diff=true`.
- Full after manifest: `artifacts/sprint24/real-data-after.json`.
- The pre-existing 185-file manifest and later six-file history are described in
  `artifacts/sprint24/real-data-comparison.json`; no real file was deleted, moved, or edited.
- The three previously recorded incident files retain their supplied hashes; the new
  03:49:20 event files are also preserved and disclosed in the incident record.
- Final process/listener audit: StockTool/StockToolPayload 0; listeners 8501/8502 0.

## Rollback and limits

No installer, formal release, version, signing, push, tag, or real-user-data rollback
was performed. Sprint 24 remains implementation evidence with the two blockers above;
independent CTO review must decide whether the incident and missing final browser evidence
are acceptable before any future work proceeds.
