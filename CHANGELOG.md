# Changelog

## 1.4.0 - 2026-08-28

- Added the Prediction Lab with evidence-bound 5/20-session evaluation,
  market-qualified benchmarks, official trading calendars, and reproducible
  saved research outcomes.
- Added fail-closed corporate-action handling so incomplete split or dividend
  evidence cannot silently produce trusted excess-return results.
- Added governed daily research scheduling, runtime isolation, canonical
  artifact indexing, and stronger installer lifecycle verification.
- Preserved the research-only boundary: StockTool does not place orders,
  promise returns, or provide personalized buy/sell instructions.

## 1.3.0 - 2026-08-20 (staging internal test)

- Consolidated the existing accepted StockTool release candidate under the
  canonical v1.3.0 version authority.
- Prepared staging-only release, installer, lifecycle and hash-bound evidence;
  the formal v1.2.2 release remains unchanged until independent acceptance.

## 1.2.2 - 2026-07-19

- Added the canonical strategy registry for the six bundled research strategies.
- Added opt-in out-of-sample, bounded walk-forward, and bounded parameter-sensitivity strategy health diagnostics.
- Promoted the validated StockTool v1.2.2 staging package through a rollback-first Windows release flow.

## 1.2.1 - 2026-07-15

- Reworked the research home into a Daily Research Home with evidence-backed attention items, portfolio and watchlist coverage, recent research continuations, and repairable data gaps.
- Added an explicit, user-triggered daily refresh for up to 20 market-qualified portfolio and watchlist symbols through the existing provider contract and fallback flow.
- Preserved missing-data semantics: the home does not fabricate prices, FX, fundamentals, scores, news, or trading instructions.

## 1.2.0 - 2026-07-15

- Added a strict, date-aligned benchmark contract to reproducible research reports.
- Added a deterministic report manifest with sanitized provenance, input hashes, parameter metadata, and replay verification.
- Added compatible Benchmark, Sources, Data Quality, and Manifest sections to Excel and HTML reports.
- Preserved legacy report exporter entry points for the current compatibility cycle.

## 1.1.0 - 2026-07-14

- Stabilized the Windows onedir release flow with staging-first builds and explicit promotion.
- Added deterministic Research Workspace integration coverage for TWSE, TPEx, US, cache fallback, partial-data, backtest, and report paths.
- Separated release assets from mutable user data under `%LOCALAPPDATA%\StockTool`.
- Added 8501 to 8502 fallback behavior and readable launcher failure logs.
- Added v1.1 release, rollback, privacy, and manual Windows acceptance documentation.

## 1.0.x

- Historical Sprint 1 through Sprint 5.2.2 delivery history is retained in the Sprint acceptance documents.
