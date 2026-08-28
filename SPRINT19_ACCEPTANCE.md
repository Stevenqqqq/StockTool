# Sprint 19 — Implementation Evidence — Pending Independent CTO Acceptance

## Final status

**BLOCKED.** This is implementation evidence only. It does not claim CTO
acceptance, Sprint 19 acceptance, release approval, production readiness,
signing, publication, promotion, or authorization for Sprint 20.

The product/readiness work below is retained for independent review. The Sprint
cannot be declared complete because the required pre-change performance
baseline was not captured before the browser-found UI correction, the
dependency-vulnerability scanner is not installed (and no tool was installed or
downloaded), and the new lifecycle replay was externally interrupted before it
could emit a new `lifecycle-result.json`. The existing valid Sprint 18 Replay 7
is preserved but is not presented as a new Sprint 19 replay.

## Entry gate and preservation

- Read governance, Product Vision, execution plan, Whitepaper, Sprint 16/17/18
  records, and the latest `SPRINT18.2.2.1.1_ACCEPTANCE.md`.
- Git: branch `main`; HEAD `f47f42b38e99af6fbbb6b1c096b6cfb3efc302a7`;
  pre-existing Sprint 18 working-tree changes were retained without reset,
  clean, checkout, commit, push, or PR.
- Formal EXE before/after SHA-256:
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- Existing installer hashes remained unchanged: current 1.2.2
  `5AEECFAA3199471F1C855A5CA25E46428DF69AF5C8CBDB1749CFCF72E529CB55`;
  rollback 1.2.1
  `C6FE8F9A3B203C48D5A51974401B4287B7FF9D110D4FB3C08734FE2CFDEC96C0`.
- Existing Sprint 18 source archive remained
  `83C71DCE486A60CF7E67ADAB6C07DF37011CB9FEE77EB1CC07015832259B7345`.
- The only real user-data baseline file, `%LOCALAPPDATA%\StockTool\data\portfolio.csv`,
  remained 131 bytes with SHA-256
  `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
  Watchlist, SQLite, and settings baseline files remain absent.

## Changed files and rationale

- `src/stock_tool/dashboard/pages/research.py`: moved optional save/local
  document-reference controls below the research overview. Browser evidence
  showed the old position displaced the company, score, source, and risk
  evidence from the first screen at 1280×720.
- `tests/test_research_document_workspace.py`: regression test proves core
  research renders before optional save controls.
- `tests/e2e/test_product_acceptance.py`: deterministic product-journey
  contracts for first use, six navigation entries, three markets, immutable
  saved research, missing-price honesty, and strategy/export dependencies.
- `tests/performance/test_large_dataset.py`: deterministic large-data indicator
  and reproducible Excel export fixtures.
- `tests/security/test_release_readiness.py`, `scripts/generate_sbom.py`,
  `SECURITY.md`, `PRIVACY.md`, `THIRD_PARTY_LICENSES.md`, and
  `docs/release/v3-checklist.md`: local metadata SBOM, privacy/release
  contracts, and explicit non-release gates.
- `docs/product/social-reference-backlog.md`: recovered social-link backlog;
  all post content remains UNVERIFIED and no product feature was inferred.

## Product journey evidence

| Core ability | Evidence | Result |
| --- | --- | --- |
| First research | browser first-use CTA and deterministic test | pass |
| Six fixed entry points | browser DOM and navigation contract | pass |
| TWSE/TPEX/US | deterministic fixture journey | pass |
| Company/price/score/coverage/risk/source/limits | browser workspace plus snapshot tests | pass |
| Cache/offline/partial failure honesty | controlled provider journey | pass |
| Exploration handoff | existing dashboard navigation regression suite | pass |
| Strategy T+1/cost/benchmark/risk | deterministic journey/export contract | pass |
| Missing holding price honesty | valuation regression | pass |
| Saved library version provider-free | library dashboard regression | pass |
| Reproducible export/gaps/risk | deterministic Excel report journey | pass |

## Browser, usability, and candidate EXE

- New candidate: `release/staging-sprint19/StockTool/Payload/StockToolPayload.exe`;
  SHA-256 `8B1D3BA3898F27275ABC9FA153CEC9A6DC056624032DA65B7204CA69689EB05A`.
- Isolated `STOCK_TOOL_USER_DATA_DIR` candidate health returned `200`, `ok`.
- Actual in-app browser at 1280×720 opened the first-use UI and selected
  `研究 2330`. The returned workspace exposed company, current price, data date,
  full score, coverage, provider/source identity, and risk before the optional
  document expander.
- Screenshots retained in `artifacts/sprint19/`:
  `browser-home-1280x720.png`, `browser-candidate-research-1280x720.png`, and
  `browser-candidate-research-top-1280x720.png`.
- The optional document section was the browser-found blocker and was fixed.
- Keyboard navigation across all controls and verified 125%/150% browser zoom
  remain **not completed**: the Streamlit sidebar radio could not be activated
  by the browser automation surface. This contributes to the BLOCKED status.

## Tests and quality evidence

| Command | Result |
| --- | --- |
| Sprint 19 targeted product/security/performance/document tests | 25 passed |
| `python -m pytest --cov=stock_tool --cov-branch --cov-report=term -q` | exit 0; 2 expected duplicate-entry warnings; total branch coverage 82.53% |
| Black changed scope | pass |
| Ruff changed scope | pass |
| focused mypy (`research.py`, `generate_sbom.py`) | pass |
| `compileall -q src scripts tests` | pass |
| project privacy scan | 0 violations |

`pip_audit` is not installed (`No module named pip_audit`). No scanner was
installed or downloaded, so High/Critical vulnerability status is **unverified**.

## SBOM, archive, and release safety

- Generated metadata-backed SBOM: `artifacts/sprint19/sbom.cdx.json`.
- New source archive: `release/staging-sprint19-source.zip`; SHA-256
  `3CA33FBB134BEE075A93C1FAF51EA916DAEE3AA91D4AC181215F7CC27C177697`.
- Archive verification: missing required inputs `0`; forbidden entries `0`;
  content mismatches `0`; duplicate entries `0`.
- v3 checklist explicitly marks signing, public release, and rollout as
  `DEFERRED BY PRODUCT OWNER / NOT EXECUTED`.

## Installer lifecycle

- Preserved valid evidence: `artifacts/sprint18.2.2/lifecycle-replay-7/lifecycle-result.json`
  (19,108 bytes; `status: passed`; 17 commands; 5 snapshots; cleanup passed).
- A fresh isolated replay root,
  `artifacts/sprint18.2.2/lifecycle-sprint19`, started and completed the first
  1.2.1 installation, but the execution host timed out the parent process
  before final result emission. Its exact first-install Inno log and the forced
  isolated cleanup log are retained. The targeted isolated uninstaller exited
  0; program directory, fixed-AppId registry, StockTool processes, and 8501/8502
  listeners were verified absent afterward.
- The fresh replay is therefore **incomplete**, not a passing lifecycle claim.
  No clean Windows 10/11 VM was available; clean-machine acceptance is also not
  executed.

## Rollback and remaining gates

Rollback for the UI-only change is removal of the bounded research-page change;
the stable launcher, version authority, installers, and formal release were not
modified. Before independent acceptance, rerun a fresh lifecycle harness to a
valid result JSON, perform keyboard plus 125%/150% browser checks, capture a
pre-change performance baseline for an approved follow-up correction, and run
an approved dependency vulnerability scan that reports zero High/Critical
issues. No formal release action is authorized.
