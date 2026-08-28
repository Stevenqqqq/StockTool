# Sprint 16.1.1.1 Acceptance

Status: **Implementation complete and ready for independent CTO acceptance review.**

This is a trust-boundary correction only. Sprint 17 was not started, formal
release promotion was not performed, and `release/StockTool` was not modified.

## Scope and Root Cause

The Sprint 16.1.1 policy recognized a bounded set of complete advice phrases,
but did not cover concrete recommendation wording such as `Buy MU now`,
`I recommend buying MU today`, or the equivalent Traditional Chinese forms.
It also normalized Unicode without removing format characters, allowing a
zero-width character to split a sensitive phrase.

`AIResearchNote.from_dict()` also accepted `bool` coverage values because
Python booleans are subclasses of integers. It did not reject non-finite,
out-of-range numeric values.

## RED Evidence

Before the implementation change, the new regression suite reproduced **11
failures**: five concrete trading recommendations were accepted as `ai`, and
six invalid coverage values were accepted by the cache parser. A dedicated
zero-width-only guarantee case was then isolated in the regression suite and
passed only after the format-character normalization was implemented.

## Implementation

Modified files:

- `src/stock_tool/research/citations.py`
- `src/stock_tool/research/assistant.py`
- `tests/test_ai_fallback.py`

### Trading safety policy

Claim text is normalized with Unicode NFKC and `casefold()`, then Unicode
format characters (`Cf`, including zero-width characters) are removed before
matching. The policy now uses bounded, structured patterns for:

- recommendation words combined with buy/sell actions;
- immediate, now, today, and equivalent Chinese time words combined with
  trading actions, allowing only a small intervening text window;
- English `buy`/`sell` followed by a symbol and `now`/`today`/`immediately`;
- `recommend buying` / `recommend selling`; and
- guaranteed-profit wording in Traditional and Simplified Chinese.

Research descriptions remain allowed, including庫藏股買回、賣方研究、買盤力道、賣壓、
股票回購 and historical descriptions of past purchases. Any violating claim
still rejects the complete model response, returns `local_rules`, preserves no
partial AI claims, and does not create or overwrite the AI cache.

### Strict coverage validation

Cache coverage now accepts only `null` or a finite `int`/`float` in the closed
range `0.0` through `1.0`. Booleans, strings, NaN, Infinity, negative values,
and values above `1.0` are rejected. Invalid cache data falls back to
`local_rules` with a safe warning; valid AI cache reuse remains unchanged.

## Tests

Added regression coverage includes:

- Traditional Chinese recommendation and immediate-action wording;
- English symbol/time recommendation forms;
- zero-width guarantee text;
- Simplified Chinese guarantee/action wording;
- legal research descriptions that must not be blocked;
- `coverage=True`, `False`, NaN, Infinity, negative, and above-range values;
- valid coverage `0`, `0.5`, `1.0`, and `null`;
- invalid cache fallback without AI mode; and
- preservation of legal AI cache reuse.

Commands and final results:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_research_assistant.py tests\test_ai_citation_policy.py tests\test_ai_fallback.py tests\test_ai_provider_contract.py tests\test_research_assistant_dashboard.py tests\test_dashboard_shell.py
.\.venv\Scripts\python.exe -m pytest --cov --cov-branch --cov-report=term
.\.venv\Scripts\python.exe -m black --check src\stock_tool\research\assistant.py src\stock_tool\research\citations.py tests\test_ai_fallback.py tests\test_ai_citation_policy.py tests\test_ai_provider_contract.py
.\.venv\Scripts\python.exe -m ruff check src\stock_tool\research\assistant.py src\stock_tool\research\citations.py tests\test_ai_fallback.py tests\test_ai_citation_policy.py tests\test_ai_provider_contract.py
.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\research\assistant.py src\stock_tool\research\citations.py
```

- Sprint 16.1.1.1 targeted tests: **97 passed**.
- Full pytest: **762 passed**.
- Branch coverage: **82.30%**; current gate **78.50%** passed.
- Black: all five focused files unchanged after formatting.
- Ruff: all focused checks passed.
- Focused mypy: no issues found in two source files.

## Staging Candidate

Only this new staging directory was built:

- EXE: `release/staging-sprint16.1.1.1/StockTool/StockTool.exe`
- Size: `24,191,607` bytes
- Modified UTC: `2026-07-27T04:53:10.1034007Z`
- SHA-256: `78E43460CFBD012CBDF3BDCC35CCEEA0A2EE8B9FC4E18A606F3F3BE1F648780F`

Isolated `STOCK_TOOL_USER_DATA_DIR` smoke result:

- `/_stcore/health`: HTTP 200, body `ok`.
- `/`: HTTP 200.
- `reports`, `logs`, `data/cache`, and `data/ai_research`: writable.
- Runtime directory removed after the test using an exact validated temporary
  path.
- Remaining `StockTool` processes: `0`.
- Remaining listeners on ports 8501/8502: `0`.

## Privacy and User Data

- Staging required release assets: valid.
- Staging forbidden private-file count: `0`.
- Source privacy scan: `0` violations.
- The broader bundled third-party text scan reports five lexical credential-key
  references in vendored `jsonschema` benchmark data and Streamlit reference
  documentation. It reported only path/line/category and no value. These are
  third-party package assets, not StockTool runtime credentials; removing them
  is outside this narrowly scoped correction.
- Formal EXE was not modified. SHA-256 remains:
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.

Read-only real-user-data comparison remained unchanged:

- `portfolio.csv`: exists, 4 rows, 131 bytes,
  SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
- `watchlist.csv`: absent.
- `stock_data.sqlite`: exists, 716,800 bytes,
  SHA-256 `FD563A543FE847FA09AB61CEBA947BBFCE04272836EDB46B5FE714CB337E1293`.
- `settings.json`: absent.

## Source Archive

- Archive: `release/baseline/stocktool-sprint16.1.1.1-20260727-source.zip`
- Entries: `278`.
- Size: `2,352,886` bytes.
- SHA-256: `4A6E473226F8B9E418AEAEED0C8F6D461CAA078BF3BB1505B17C8078FD718735`.
- SHA-256 sidecar: present and matched.
- Extracted verification: required inputs missing `0`, forbidden entries `0`,
  content mismatches `0`.

## Rollback and Limitations

No formal release promotion occurred. The formal EXE and the preserved
Sprint 15.1.3.1 source archive remain the available rollback boundary. The
previous Sprint 15.1.3.1 staging EXE had been overwritten before this work;
its historical executable hash is not claimed as restored.

This correction does not add providers, UI changes, investment advice,
auto-trading, or Sprint 17 work. Final status remains pending independent CTO
acceptance.
