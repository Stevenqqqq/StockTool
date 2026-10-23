# Accepted local source synchronization — 2026-10-11

## What this branch represents

This branch synchronizes completed, independently reviewed local source into GitHub for consultant review. It is not a release, installation, merge authorization, or new product acceptance run. Product Owner relayed Sol's independent acceptance in the project conversation; the latest source-import acceptance reports **1931 passed, exit 0**, with source/evidence hashes unchanged.

Remote main at preparation: `11ee8d7438e9a06115d3ab75a99d088d4ef55d13` (accepted MU fixes). Local committed base: `f683f32d585b06d4d592f1152869a24f7fad5a59`. The original five unsynchronized local commits were reproduced by feature using their exact accepted source/test bytes; machine-specific build scripts and raw handoff artifacts were not imported into new commit history. Original commit identities are mapped in `accepted-source-sync-20261011.json`.

## Included scope and acceptance boundaries

| Feature | Scope and evidence basis |
|---|---|
| Research Integrity Gate v1 | Corporate-action discontinuity safety, strict point-in-time fundamentals, preflight invalidation of stale results. Product Owner relayed final independent acceptance. Original commits `3890f1a`, `d0129f0`. |
| Backtest Evidence v1 | Closed round trips vs fills; net trade quality and MFE/MAE; unavailable statistics remain unavailable rather than false 0% wins. Independent acceptance including same-batch reporting fix. Original commits `19422a9`, `2af2348`. |
| Scenario Research v1 | Accepted **synthetic console workflow only**: qualification gate, lifecycle, OOS state isolation, sizing/full exit, case evidence, versioned persistence and deterministic replay. Original commit `f683f32`. No production UI or real-data research authorization. |
| Daily holdings r3 | Refresh, summary, persistence/deduplication, research navigation, failure retention and restart accepted. Historical independent full suite: 1817 passed. Scheduler closeout was formatting-only, with AST/bytecode-equivalence evidence; no claim that the old EXE contains later source formatting. |
| Official instrument names | Listed/OTC/ETF sources remain distinct; market+symbol identity, shared names, last valid cache and honest unknown state. Sol's names-r2 review passed these sub-scopes, including actual TPEx acquisition; its initial first-screen issue was fixed in the subsequent header batch. |
| Research first screen | Independent header review dated 2026-10-05 passed the scoped readability fix. Business summary, price/date, next question and key gaps remain visible. Independent fresh screenshot capture limitation remains, despite successful interaction/DOM checks. |
| Fixed-period TWSE calendar | Only TWSE/3006 2025-02-24 through 2025-06-30 calendar correction accepted: 86 dates, including 2025-04-07. Public official holiday response is a required test fixture. This does not establish security tradability or full corporate-action coverage. |
| Research chart r3 | Candles/close line, SMA20/60, volume, period/tab/symbol changes, gaps, table fallback and narrow width independently passed. Chart EXE/source hashes accepted. The initial independent CDP Home failure was separately diagnosed and fixed below. |
| Source import isolation | Source entrypoint prioritizes the current source and checks actual loaded module/package origins. Already loaded stale modules fail clearly rather than being silently replaced. CDP child pins its own source path. Five new regression cases; original CDP passed; independent full suite 1931 passed, exit 0. |

All included product Python changes match the frozen chart source manifest plus the subsequently accepted source-import manifest. Calendar files additionally match the accepted calendar source index. `accepted-source-sync-20261011.json` records SHA-256 for the 60 synchronized source/test/fixture/helper files. Final bytes match the original local working tree; no application formulas or behavior were developed during synchronization.

## Verification status — historical, not rerun by this synchronization

- Latest local source full pytest: **1931 passed, 2 warnings**, total coverage **83.37%**; source-import change independently confirmed by Sol.
- These are results for the reviewed local workspace, which also contains separate offline-model experiment tests intentionally not uploaded here. They are not a claim that this curated branch has just run exactly 1931 tests.
- Source-import regressions: 5 passed; original CDP alone: 1 passed. The previously empty Home H1 came from mixing current source with an installed older package, not a timeout. Assertions were retained.
- Existing project Black failures remain in `tests/test_daily_home.py` and `tests/test_daily_research_loop.py`; no formatting fixes or threshold changes were made here.
- Other scope-specific historical limitations are not retroactively erased by a later green suite.
- This synchronization performs only file/history allowlisting, source/hash comparison, diff checks and sensitive-content review. It does not rerun acceptance, build EXEs, install, publish, or merge main.

## Binary and real-data boundaries

The formal local delivery reference remains **v1.4.3 with itemized acceptance**, including the existing guest lifecycle waiver and other installation limitations. Later candidate acceptance did not promote it to an unconditional formal product pass.

Chart r3 payload SHA-256: `b015a7321225183166ebdd10a45b2447ca581fb94c59757d6ed32059d5fa3ff7`. That EXE **does not contain the later source-import correction**. No binary is uploaded or newly built by this PR.

Real-data Scenario Research qualification remains **incomplete / formal research NO-GO**. Initial security state, cross-boundary events, MOPS completeness, missing TWT85U days and wider calendar discrepancies remain unresolved. Synthetic fixtures and a calendar-only pass are not verified real-data coverage, and no 3006/6669/6933 strategy efficacy claim is made.

## Kept local / not synchronized

- Runtime directories, actual holdings, research databases, backups, credentials/DPAPI, environment files, caches, browser profiles, screenshots, EXEs and candidate binary manifests.
- Raw company/social/article acquisition and qualification acquisition dumps; no paid source material. The one public official holiday fixture is deliberately included because the calendar test hashes and parses it.
- Machine-specific historical build scripts, absolute local-path handoffs and bulk logs. Their acceptance scope is summarized here without publishing personal machine paths.
- Offline Laya/local-model experiments and their two test modules: the comparison was closed without product integration gain; they are not required for the product source under review.
- Proposed-only architecture/roadmap work is not represented as implemented. The approved Scenario design is supplied as a historical design reference; its future UI/real-data portions remain gated.
- No local unaccepted changes were promoted merely because a later candidate contained them. The original working tree and local evidence remain untouched for future review.

## Reviewer navigation

Start with the feature table and commit history. Key implementation modules are `application/strategy_workspace.py`, `backtest/trade_evidence.py`, `application/scenario_research.py`, `application/scenario_store.py`, `application/daily_holdings.py`, `application/instrument_names.py`, and `dashboard/components/research_chart.py`. Corresponding deterministic tests are included beside existing tests. The JSON ledger maps original local commits, grouped synchronization commits and final file hashes.

Acceptance and release remain separate roles. This PR is for source review only; do not merge or publish without Product Owner approval.
