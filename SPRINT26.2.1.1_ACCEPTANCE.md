# Sprint 26.2.1.1 implementation evidence

STATUS: IMPLEMENTATION EVIDENCE COMPLETE - PENDING INDEPENDENT CTO ACCEPTANCE

This correction did not modify source, the formal EXE, the installer, the
version, the signature, or the production Task Scheduler task. No candidate
rebuild was required because the recorded candidate hashes were rechecked and
unchanged.

## Diagnosis and replay

The previous final-candidate `partial=10` was caused by the isolated input
having no valid prior evidence-chain brief. The normal provider refresh was
attempted, but yfinance returned an empty payload and the existing cache was
used. Without a valid local research continuation, the normal loop emitted a
repair event and the schema-v2 brief correctly became partial. This was not a
product success-path defect.

The new replay fixture contains only market-qualified portfolio/watchlist
inputs, the validated provider cache, and a valid schema-v2 prior brief. It is
isolated under a new TEMP root and is consumed by the ordinary
`fetch_prices_result -> _refresh_existing_provider -> DailyResearchBriefApplicationService -> DailyResearchBriefStore` path. Production defaults are unchanged.

Provider replay evidence:

- `artifacts/sprint26.2.1.1/provider-replay/provider-replay-manifest.json`
  SHA-256 `1009CC8F46C76CA75E5A7CD257B2C331507CA28DE750831B7A5D80FC455D9E85`
- Formal parser result: yfinance attempts failed with empty data, FinMind was
  skipped because the optional credential was absent, and the validated cache
  fallback returned 484 rows through the provider contract.
- Cache payload SHA-256 `FC57DC439285650F3E8F4A0E05109A7462405B9CE626BB46A5C3A10BCC229A2A`;
  metadata SHA-256 `848A28FCB9BA920A6EE1356FF9D2D1098E6765043CD3DA656C9950FAE40CE078`.
- A durable eight-file replay copy is kept under
  `artifacts/sprint26.2.1.1/provider-replay/fixture/`; its fixture manifest
  SHA-256 is `927037C3EC48C607D7B52E8EDA6493138769B9A4999FD48DC98AF8059556E8AF`.

## Current success evidence

Command used the stable staging entry through `scripts/evidence_launcher.py`,
with a new isolated data root and `--daily-research-run --trigger manual`.

- observed exit code `0`
- run record status `success`, exit code `0`
- brief schema version `2`, status `success`
- latest projection, history projection, immutable `run-*.json`, JSON brief,
  and HTML projection all reloaded successfully
- four evidence reference IDs all resolved
- harness exit code `0`
- guard status `passed`
- cleanup verified; candidate processes `[]`; listeners `0`
- real-data diff: `added=[]`, `removed=[]`, `changed=[]`, `zero_diff=true`
- Redacted machine-readable diff:
  `artifacts/sprint26.2.1.1/real-data-diff.json` SHA-256
  `55151754F70F9356C9AC6DF2B98EEF26420A0944BDC2D1EABEC7078975850F1C`.

Evidence:

- `artifacts/sprint26.2.1.1/headless-success-final2/`
- `artifacts/sprint26.2.1.1/success-validation.json`
  SHA-256 `3176D1FD2D3E9C7B961708C678E9C4C27BCBC115E950ED3E99C9BFDE446ACEB1`

## Exit-code matrix

The current-candidate matrix is bound in
`artifacts/sprint26.2.1.1/browser-result.json`:

| scenario | expected/observed | status |
|---|---:|---|
| success | 0 / 0 | passed |
| partial | 10 / 10 | passed |
| skipped | 20 / 20 | passed |
| already-running | 30 / 30 | passed |
| failed | 40 / 40 | passed |

The former blocked success attempt remains preserved as
`historical_blocked_success`; it is not reused as current success evidence.

`browser-result.json` SHA-256 `6B9D32C8D60E11C3065EA5F58081AD156999D45DE753CCCFD40C55E2B82B7176`,
`overall_passed=true`, active console errors `0`, daily schedule visible
`true`. The existing live settings/home session is reused only because the
source and candidate hashes are unchanged; it is explicitly marked as the
same-candidate hash-bound session. Native Chrome zoom remains
`deferred_to_formal_release`.

Recursive guard history is preserved in
`artifacts/sprint26.2.1.1/browser-history-index.json` (105 guards: 80 passed,
25 failed), SHA-256
`EA38B54685C11F3E69801505910230BF8BBC91F0B34E979B2A6CF3B6FA9E5ED1`.

## Hash and quality preservation

- Stable: `DF11F90299F37E7860721C6F2C3E682E8089A598D6AFC45E7A79B7A52CB08630`
- Payload: `6E40D8EF5532B7246E42AE2C1C231C4A1FD0F74AABAF3596CE2E078641C421EC`
- Source ZIP: `B660F45BCC79D7BED1ED36CA78D5DF54596EB163BB3947CF84E413E70C01585E`
- Formal EXE unchanged: `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`
- `candidate-hash-unchanged.json` records every size and SHA match.
- Existing quality evidence remains valid because no source changed: targeted
  40 passed; full pytest 1170 passed, 2 skipped; branch coverage 82.47%;
  quality gate exit 0; pip check exit 0; official pip-audit exit 0 with zero
  known vulnerabilities; performance gate passed.

The explicitly requested untracked `v/cache/nodeids` was removed. No other
user file was touched.

## Cleanup and limitations

StockTool/StockToolPayload processes are `0`; listeners 8501/8502 are `0`;
production and temporary Task Scheduler tasks are absent. Formal release and
real user data were not modified. Independent CTO acceptance is still pending;
native Chrome zoom remains deferred.
