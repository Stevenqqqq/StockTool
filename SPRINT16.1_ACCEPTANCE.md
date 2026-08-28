# Sprint 16.1 Acceptance

Status: Implementation complete and ready for independent CTO acceptance review.

## Scope and Trust Boundary

Sprint 16.1 corrects the trust boundary for the Sprint 16 evidence-linked AI
research brief. It does not begin Sprint 17, promote a formal release, alter
the formal `release\StockTool` candidate, or modify real user data.

The formal EXE remains the rollback executable:

- `release\StockTool\StockTool.exe`
- SHA-256: `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`

The retained Sprint 15.1.3.1 source archive remains the other rollback
boundary:

- `release\baseline\stocktool-sprint15.1.3.1-20260726-source.zip`
- SHA-256: `7667BB98B0F22E38B5D9E4D29EFAD596C05F77A48959ECA8D83E8F75DEB773F3`

The earlier Sprint 15.1.3.1 staging EXE had already been overwritten before
this Sprint. It was not recreated or represented as having its original hash.

## Root Causes and Fixes

1. Model claim validation previously filtered invalid claims, which allowed a
   mixed valid/invalid response to retain and cache selected model content.
   Model output and cached AI notes now use strict validation: any unsafe,
   uncited, unknown-citation, unsupported-schema, deterministic-evidence
   rewrite, missing-evidence-as-fact, trading-instruction, guarantee, prompt
   injection, or script/URL injection claim rejects the complete response.
   The result is deterministic local-rules fallback and no new AI cache write.
2. AI cache records were parsed before reuse but their semantic citations were
   not revalidated against the current immutable `EvidenceBundle`. Cache reuse
   now requires exact symbol, market, fingerprint, claim safety, and canonical
   citation metadata equality. A forged URL, excerpt, provider, source, or
   evidence identity is ignored with a safe warning. Fallback never overwrites
   the last valid AI-mode cache.
3. The OpenAI-compatible HTTP contract did not have a complete mocked boundary
   test suite. It now validates endpoint/request/response behavior, bounded
   response size, safe error behavior, and endpoint security. Remote API-key
   calls require HTTPS; explicitly local `localhost`, `127.0.0.1`, and `::1`
   HTTP endpoints remain supported for compatible local services.

## Modified Files

- `src/stock_tool/research/assistant.py`
- `src/stock_tool/research/citations.py`
- `tests/test_ai_fallback.py`
- `tests/test_ai_citation_policy.py`
- `tests/test_ai_provider_contract.py` (new)

## Contract Summary

- `validate_research_claims(..., fail_closed=True)` is mandatory at the model
  and AI-cache boundary. A single invalid claim raises a structured validation
  failure; it is never silently removed while other model claims are accepted.
- FACT and CALCULATION claims require known, non-MISSING bundle evidence and
  exact normalized evidence text. INFERENCE may remain inference but cannot
  contain prompt-injection, HTML/script, trading-instruction, or guarantee
  content.
- Cache citations are reconstructed from the current evidence registry. Cached
  metadata cannot supply or override source, URL, publisher, excerpt, symbol,
  market, field, or timing data.
- Provider exceptions are normalized to `AI provider request failed.` and do
  not serialize Authorization values, API keys, or raw request content.
- Local-rules output remains explicitly labelled as local rules, not external
  AI output.

## Regression Coverage

New and updated tests cover:

- valid claim plus prompt injection, unknown citation, trading instruction,
  missing evidence fact, or script injection rejecting the whole model reply;
- no AI cache write on invalid model response;
- forged cached citation URL, excerpt, and provider metadata being rejected;
- valid AI cache reuse and provider-failure preservation of valid AI cache;
- mocked HTTP endpoint, request JSON, response parsing, timeout, HTTP error,
  invalid JSON/envelope, and maximum response size;
- HTTPS enforcement for remote key-bearing endpoints and explicit local HTTP
  compatibility;
- no secret value in provider-facing failures or serialized cache output.

## Verification

Commands and actual results:

```text
.\.venv\Scripts\python.exe -m pytest --disable-warnings \
  tests\test_research_assistant.py \
  tests\test_ai_citation_policy.py \
  tests\test_ai_fallback.py \
  tests\test_ai_provider_contract.py \
  tests\test_research_assistant_dashboard.py \
  tests\test_dashboard_shell.py
57 passed in 1.74s

.\.venv\Scripts\python.exe -m pytest --cov --cov-branch --cov-report=term-missing
722 passed in 67.05s
Total branch coverage: 82.24% (gate: 78.50%)

.\.venv\Scripts\python.exe -m black --check [five changed files]
5 files would be left unchanged.

.\.venv\Scripts\python.exe -m ruff check [five changed files]
All checks passed.

.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports \
  src\stock_tool\research\assistant.py \
  src\stock_tool\research\citations.py
Success: no issues found in 2 source files.
```

## Staging EXE and Smoke Test

Only the new isolated candidate was built:

- `release\staging-sprint16.1\StockTool\StockTool.exe`
- Size: `24,189,290` bytes
- Last write: `2026-07-27T02:58:49.1327061+08:00`
- SHA-256: `B2A87E0295244BC40AD85BEAF880AA428AAD858E2DCEB6CB43F200ED17A3198E`

With a fresh isolated `STOCK_TOOL_USER_DATA_DIR`:

- `/_stcore/health` returned HTTP 200 with body `ok`.
- The homepage returned HTTP 200.
- Research Home, 2330/TWSE Research Workspace, return-to-home, local-rules
  brief generation, and explicit regeneration were exercised.
- The brief visibly showed `目前使用：本機規則模式`; it was not represented as
  external AI output.
- All six main navigation controls rendered. Existing dashboard state tests
  cover navigation behavior; this smoke did not use a real paid AI provider.
- Isolated `reports`, `logs`, `data/cache`, and `data/ai_research` directories
  were writable.
- Smoke cleanup left `0` StockTool processes and `0` listeners on ports 8501
  and 8502.

## Privacy and User Data Integrity

- Candidate release asset validation passed.
- Candidate forbidden filename count: `0`.
- Workspace allowlisted source privacy scan: `0` violations.
- The formal EXE SHA-256 remained
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- Real user data was read only and unchanged before/after:
  - `portfolio.csv`: 4 rows, 131 bytes,
    `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`
  - `watchlist.csv`: absent both before and after.
  - `stock_data.sqlite`: 716,800 bytes,
    `FD563A543FE847FA09AB61CEBA947BBFCE04272836EDB46B5FE714CB337E1293`
  - `settings.json`: absent both before and after.

## Source Archive

- `release\baseline\stocktool-sprint16.1-20260727-source.zip`
- Entries: `278`
- SHA-256: `BC64168C8411F67B2D2AE961E817ECFFE297123BA4D967A59495E3CE000D2E52`
- Sidecar: `stocktool-sprint16.1-20260727-source.zip.sha256`
- Temporary extraction verification: required build inputs missing `0`,
  forbidden entries `0`, content mismatches `0`.

## Known Limits

- No paid or external AI service was contacted during tests or staging smoke;
  the HTTP contract is covered through mocks and local-rules mode is fully
  operational without an API key.
- This Sprint does not restore the old overwritten Sprint 15.1.3.1 staging
  binary, create a Research Library, or begin Sprint 17.
- `release\StockTool` was not replaced or promoted.
