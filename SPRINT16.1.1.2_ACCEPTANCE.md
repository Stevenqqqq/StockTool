# Sprint 16.1.1.2 Acceptance

Status: **Implementation complete and ready for independent CTO acceptance review.**

This is a narrow Sprint 16.1.1 trust-boundary correction. Sprint 17 was not
started. `release/StockTool` was not modified or promoted.

## Root Cause and Correction

The previous safety policy rejected immediate actions and a limited set of
recommendation phrases, but did not recognize direct standalone trade commands
with a concrete target, nor `should` / `recommend` forms that insert a subject
between the recommendation verb and the trade action. Consequently, model text
such as `Buy MU.` could be accepted as `ai` mode and cached.

`src/stock_tool/research/citations.py` now applies a deliberately narrow
additional policy after the existing Unicode NFKC, `casefold`, and format
character normalization:

- Direct English commands must be an independent sentence beginning with
  `buy` / `sell` and name an explicit target (`MU`, `this stock`, or `the
  position`).
- Direct Traditional/Simplified Chinese actions must be an independent
  sentence and name a ticker, the stock, or a position.
- English `you/we should [consider]` and `I/we recommend [that]
  you/investors` patterns are rejected only when followed by a concrete trade
  action and target.

This does not broadly block research context. Existing and new tests retain
sentences about buy signals, analyst ratings, historical purchases, buying or
selling pressure, treasury-stock repurchases, sell-side research, and company
repurchase announcements.

Any violating claim continues to reject the **entire** provider response. The
assistant returns `local_rules`, accepts no partial AI claims, and neither
creates nor overwrites an AI cache entry. The regression test also verifies
that a prior valid AI cache remains unchanged after an unsafe forced
regeneration attempt.

## Modified Files

- `src/stock_tool/research/citations.py`
- `tests/test_ai_fallback.py`

No provider, EvidenceBundle, UI, portfolio, watchlist, backtest, or formal
release code was changed.

## TDD Evidence

Before the implementation, the new direct-command regression group produced
13 failures: direct English and Chinese commands plus explicit English
recommendations were incorrectly returned as `mode="ai"`. Three already-covered
forms were rejected by the existing policy. After the minimal policy change,
the complete AI fallback test module passed.

Added coverage includes all approved rejection examples:

- `Buy MU.`, `Sell MU.`, `Buy this stock.`, `Sell the position.`
- `買進 MU。`, `買入這檔股票。`, `賣出 MU。`, `出清持股。`, `加碼 MU。`, `減碼 MU。`
- `You should buy MU.`, `You should consider selling MU.`
- `I recommend that you buy MU.`, `We recommend investors sell MU.`
- `建議投資人買進 MU。`, `應該考慮賣出 MU。`

The targeted suite also re-executed the prior Unicode format-character,
guaranteed-profit, immediate-action, cache-reuse, cache-tampering, and
coverage-type/range checks.

## Verification

Commands executed from the project root using `.venv\\Scripts\\python.exe`:

```text
python -m pytest tests/test_ai_fallback.py -q                 # RED: 13 failures
python -m pytest tests/test_ai_fallback.py -q                 # GREEN: passed
python -m pytest tests/test_ai_fallback.py tests/test_ai_citation_policy.py tests/test_research_assistant.py -q
python -m pytest -q
python -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing -q
python -m black --check src/stock_tool/research/citations.py tests/test_ai_fallback.py
python -m ruff check src/stock_tool/research/citations.py tests/test_ai_fallback.py
python -m mypy src/stock_tool/research/citations.py src/stock_tool/research/assistant.py
```

Results:

- Sprint 16.1.1.2 targeted tests: **95 passed**.
- Full pytest: **passed**; the final collection contained **790 tests**.
- Branch coverage: **82.30%**; required gate **78.50%** passed.
- Black: **2 files would be left unchanged**.
- Ruff: **All checks passed**.
- Focused mypy: **Success: no issues found in 2 source files**.

## Staging EXE

Only a new versioned staging candidate was built. The formal release was left
untouched.

- Candidate: `release/staging-sprint16.1.1.2/StockTool/StockTool.exe`
- Version: `1.2.2`
- Size: `24,192,082` bytes
- Modified UTC: `2026-07-27T05:17:27.9667903Z`
- SHA-256: `8DE7D8EF537D2353AF9267F4B4CFABCECC1A29F0B2ABC3F2372B7CE9EFFF9983`

`build_exe.bat` was invoked with the versioned
`STOCK_TOOL_STAGING_PARENT` override and completed the PyInstaller candidate
build. Its existing batch-variable expansion leaves `STAGING_DIR` at the
default `release/staging/StockTool` during its final asset-copy check, so that
invocation exited non-zero after PyInstaller completed. No build script was
modified in this narrowly scoped trust-boundary patch. The generated versioned
candidate was then completed with the existing
`copy_release_assets()` and `validate_release_assets()` allowlist functions;
asset validation passed. This is a build-script limitation to retain for
independent review, not a claim that the overridden bat invocation succeeded
end-to-end.

An isolated `STOCK_TOOL_USER_DATA_DIR` smoke test verified:

- `http://127.0.0.1:8501/_stcore/health` returned HTTP `200` with `ok`.
- `/` returned HTTP `200`.
- `reports`, `logs`, `data/cache`, and `data/ai_research` were writable only
  under the isolated runtime root.
- The candidate process tree was terminated. Remaining `StockTool` processes:
  `0`; listeners on 8501/8502: `0`.
- The isolated smoke and archive-verification temporary directories were
  removed after verification.

## Privacy and User Data Integrity

- Candidate release allowlisted assets: valid.
- Candidate forbidden private-file count (`.env`, `secrets*.toml`, portfolio,
  watchlist, SQLite, reports, logs, cache): **0**.
- Source rebuild-boundary privacy scan: **0 violations**.
- The formal EXE remains unchanged:
  `release/StockTool/StockTool.exe` SHA-256
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.
- Real user runtime data was read only and was identical before/after:
  - `portfolio.csv`: exists, 4 rows, 131 bytes,
    `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`.
  - `watchlist.csv`: absent before and after.
  - `stock_data.sqlite`: 716,800 bytes,
    `FD563A543FE847FA09AB61CEBA947BBFCE04272836EDB46B5FE714CB337E1293`.
  - `settings.json`: absent before and after.

## Source Archive and Rollback

- Archive: `release/baseline/stocktool-sprint16.1.1.2-20260727-source.zip`
- Size: `2,353,760` bytes
- Entries: `278`
- SHA-256: `ADA68655447915223D37E624B580A46954D47553F73797A1D1280E80754E0FAD`
- Standard sidecar was created and matches the ZIP.
- Extraction verification: required build inputs missing `0`, forbidden entries
  `0`, content mismatches `0`.

Rollback remains the unchanged formal EXE above plus the preserved existing
Sprint 15.1.3.1 source archive. No formal promotion was attempted.

## Known Limitations

- This is a bounded text-policy correction, not a general natural-language
  investment-advice classifier.
- The current `build_exe.bat` versioned-staging override has the documented
  delayed-expansion asset-copy limitation; this sprint did not alter it.
- Sprint 17 was not started.
