# Sprint 16.1.1 Acceptance

Status: **Implementation complete and ready for independent CTO acceptance review.**

This is a Sprint 16.1 trust-boundary correction. Sprint 17 was not started.
The formal release at `release/StockTool` was not modified or promoted.

## Scope and Root Cause

Sprint 16.1 validated the overall fail-closed contract, but its text policy did
not normalize Unicode or recognize the approved Traditional Chinese, Simplified
Chinese, and full-width unsafe phrases. Consequently, a model response such as
`保證獲利，立即買進。` could pass as `ai` mode and be cached.

Two further boundary issues were corrected:

- `_claims_from_payload()` coerced malformed fields with `str()`, allowing
  non-JSON-string claim fields into the model-result contract.
- Cache reuse trusted serialized derived fields (`coverage`,
  `confidence_label`, and `missing_data`) instead of recalculating them from
  the current `EvidenceBundle`.

## Changes

Modified files:

- `src/stock_tool/research/citations.py`
- `src/stock_tool/research/assistant.py`
- `tests/test_ai_fallback.py`
- `tests/test_ai_citation_policy.py`

### Multilingual fail-closed policy

All model and cached claim text is normalized with Unicode NFKC and `casefold()`
before security matching. The policy rejects narrowly defined English,
Traditional Chinese, Simplified Chinese, and full-width forms of:

- immediate buy/sell instructions and guaranteed-profit claims;
- prompt-injection instructions, system-prompt/API-key/secret requests;
- shell or PowerShell execution requests; and
- requests to modify portfolio or watchlist data.

The policy deliberately does not reject research descriptions such as
`庫藏股買回` or `賣方研究`. Any violating claim invalidates the entire model
response: the result is `local_rules`, no partial model claims are accepted, and
no new AI cache entry is created or overwritten. `INFERENCE` claims must cite
at least one existing, non-`MISSING` `EvidenceRecord`.

### Strict model schema

Each model claim must contain exactly these fields:

`kind`, `section`, `text`, and `citation_ids`.

`kind`, `section`, and `text` must already be non-empty JSON strings.
`citation_ids` must already be a JSON list of non-empty strings. Unknown or
missing fields, numeric values, tuples, empty citation IDs, and unsupported
kinds or sections invalidate the complete model payload and cause local-rule
fallback.

### Cache revalidation

Before reuse, the assistant validates symbol, market, fingerprint, claims, and
citations against the current `EvidenceBundle`. It additionally recomputes and
compares `coverage`, `confidence_label`, and `missing_data`. A tampered cache
is ignored; it cannot be displayed as AI output and cannot replace the last
valid AI cache. Provider failure continues to preserve the last valid cache.

## TDD and Regression Coverage

The initial focused RED run found 11 failures, including multilingual unsafe
claims accepted as AI, malformed schema coercion, unvalidated derived cache
fields, and uncited inference acceptance.

New or strengthened regression cases cover:

- Traditional Chinese, Simplified Chinese, and full-width unsafe claims;
- prompt-injection and secret/system-prompt requests;
- non-advisory `庫藏股買回` and `賣方研究` text;
- non-string claim fields, invalid citation ID types, empty IDs, and extra
  schema fields;
- tampered `coverage`, `confidence_label`, and `missing_data` cache fields;
- inference cited only by `MISSING` evidence; and
- legal cache reuse and provider-failure cache preservation.

## Verification

Commands executed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_research_assistant.py tests\test_ai_citation_policy.py tests\test_ai_fallback.py tests\test_ai_provider_contract.py tests\test_research_assistant_dashboard.py tests\test_dashboard_shell.py
.\.venv\Scripts\python.exe -m pytest --cov --cov-branch --cov-report=term-missing
.\.venv\Scripts\python.exe -m black --check src\stock_tool\research\assistant.py src\stock_tool\research\citations.py tests\test_ai_fallback.py tests\test_ai_citation_policy.py tests\test_ai_provider_contract.py
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\research\assistant.py src\stock_tool\research\citations.py tests\test_ai_fallback.py tests\test_ai_citation_policy.py tests\test_ai_provider_contract.py
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\research\assistant.py src\stock_tool\research\citations.py
```

Results:

- Sprint 16.1.1 targeted tests: **75 passed**.
- Full pytest with branch coverage: **740 passed**.
- Branch coverage: **82.28%**; required gate **78.50%** passed.
- Black: **5 files would be left unchanged**.
- Ruff: **All checks passed**.
- Focused mypy: **Success: no issues found in 2 source files**.

## Staging EXE and Smoke Test

Only a new staging candidate was built:

- EXE: `release/staging-sprint16.1.1/StockTool/StockTool.exe`
- Size: `24,190,899` bytes
- Modified UTC: `2026-07-27T02:41:10.0932107Z`
- SHA-256: `5E0196B9EF9D9BF8CB2A9743E3DDA7502EABF8F7074A2F12F5E3CB5561A8F679`

The staged release assets passed validation. An isolated
`STOCK_TOOL_USER_DATA_DIR` smoke test verified:

- `/_stcore/health` returned HTTP 200 with body `ok`.
- `/` returned HTTP 200.
- `reports`, `logs`, `data/cache`, and `data/ai_research` were writable only
  under the isolated runtime directory.
- The smoke process tree was terminated; remaining `StockTool` processes: 0;
  listeners on 8501/8502: 0.

## Privacy and User Data Integrity

- Staging release public assets validated; forbidden private-file count: **0**.
- Source rebuild-boundary privacy scan: **0 violations**.
- A broader text-only scan of bundled third-party `_internal` assets reported
  five lexical credential-key findings in vendored `jsonschema` benchmark data
  and Streamlit reference documentation. The scan output was limited to
  path/line/category and no value was disclosed. These are not StockTool
  runtime configuration files; removing third-party package documentation is
  outside this correction scope.
- The formal EXE was not modified. Its SHA-256 remains
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- User data was read only and unchanged before/after:
  - `portfolio.csv`: exists, 4 rows, 131 bytes,
    `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
  - `watchlist.csv`: absent before and after.
  - `stock_data.sqlite`: 716,800 bytes,
    `FD563A543FE847FA09AB61CEBA947BBFCE04272836EDB46B5FE714CB337E1293`.
  - `settings.json`: absent before and after.

## Source Archive

- Archive: `release/baseline/stocktool-sprint16.1.1-20260727-source.zip`
- Size: `2,351,980` bytes
- Entries: `278`
- SHA-256: `51D67CE3C9E4096EC632848965A307AE181C17F808133471D96D3ABE5627A543`
- SHA-256 sidecar: present and matched the ZIP.
- Verification after extraction: required build inputs missing `0`, forbidden
  entries `0`, content mismatches `0`.

## Rollback and Limitations

No formal release promotion occurred. The existing formal EXE and the preserved
Sprint 15.1.3.1 source archive remain the current rollback boundary. The prior
Sprint 15.1.3.1 staging EXE had already been overwritten before this sprint;
this document does not claim that its old executable hash was restored.

This sprint adds no provider, no investment advice, no auto-trading, and no
Sprint 17 work. AI output remains optional; invalid or unavailable model output
falls back to deterministic local rules.
