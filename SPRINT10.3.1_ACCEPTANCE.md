# Sprint 10.3.1 Acceptance Record

**Status:** ready for independent CTO acceptance review

## Scope

Sprint 10.3.1 is a corrective pass for the existing Daily Research Loop in
StockTool v1.2.2. It does not begin Sprint 11 and does not add providers, AI,
trading, scoring-formula, backtest, risk, or portfolio features.

## Root Cause And Corrections

### Stable comparison baseline

The prior comparison key included mutable evidence text. An event whose content
changed could therefore be treated as newly absent from the prior snapshot, so
the UI displayed `上次成功檢查未出現` instead of the actual prior value.

`DailyResearchEvent` now separates:

- **event identity:** deterministic JSON of market-qualified identity, event
  code, action, and structured field. It excludes current value, baseline
  value, timestamps, title, and explanatory text.
- **display key:** deterministic identity/action/field key for UI de-duplication.
- **value key:** current evidence, data date, and non-sensitive provenance used
  only to decide whether a stable event changed.

For an existing event whose value changes, the result is `changed`, with the
previous `current_value` as `baseline_value` and the previous successful
snapshot timestamp as `baseline_as_of`. Only a first-seen stable identity uses
`上次成功檢查未出現`.

### Resolved events

Events present in a prior successful snapshot but absent from the current
successful snapshot now produce `resolved`. They show the prior evidence and
prior successful check time, while their current value is
`已不再出現／已解除`. Partial, failed, unavailable, and corrupt snapshots are not
used as successful baselines.

### Duplicate cards and CTAs

The Daily Loop now makes Priority, Persistent, and Repair groups disjoint by
structured `display_key`. Existing Daily Brief attention, priority-issue, and
action-required cards are suppressed only when the same structured identity is
already represented by the Loop. Within the Loop, a repeated destination action
such as `view_holdings` is rendered once, leaving the remaining evidence cards
visible without repeated identical CTA buttons.

### Canonical metrics actually supported

The snapshot compares only existing structured Daily Brief values:

- portfolio risk alert count;
- portfolio price coverage;
- maximum position weight; and
- market-qualified research-continuation coverage.

Existing structured `ActionRequired` records remain the source for fundamental,
research, and composite-score availability repairs. No score, availability, or
data change is inferred from rendered text; absent canonical data is not
calculated or fabricated.

## Modified Files

- `src/stock_tool/application/daily_research_loop.py`
- `src/stock_tool/dashboard/pages/home.py`
- `tests/test_daily_research_loop.py`
- `tests/test_daily_home.py`
- `SPRINT10.3.1_ACCEPTANCE.md`

## Regression Coverage Added

- Existing risk count changing from one item to two retains the prior value and
  prior successful snapshot timestamp.
- Only first-seen identities display `上次成功檢查未出現`.
- Disappearing successful-baseline events create `resolved` evidence.
- Identical input remains `no_change`.
- Partial or failed refreshes do not replace a successful baseline.
- Price-coverage changes are detected from a structured canonical field.
- Legacy snapshots without `baseline_as_of` remain readable.
- A Loop-represented risk issue produces one holdings CTA and does not duplicate
  the legacy risk card.

## Verification

### Targeted tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_daily_brief.py tests\test_daily_research_loop.py tests\test_daily_home.py tests\test_dashboard.py -q
# 69 passed
```

The targeted suite includes isolated AppTest coverage for the Daily Home and a
deterministic recorder check that verifies one visible holdings CTA for the
same risk identity.

### Full suite and branch coverage

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=stock_tool --cov-branch --cov-report=term-missing
# 519 passed in 114.42s
# Total branch coverage: 80.88%
```

The result exceeds the 80.50% Sprint 10.3.1 gate.

### Focused quality checks

```powershell
.\.venv\Scripts\python.exe -m black --check src\stock_tool\application\daily_research_loop.py src\stock_tool\dashboard\pages\home.py tests\test_daily_research_loop.py tests\test_daily_home.py
# 4 files would be left unchanged.

.\.venv\Scripts\python.exe -m ruff check src\stock_tool\application\daily_research_loop.py src\stock_tool\dashboard\pages\home.py tests\test_daily_research_loop.py tests\test_daily_home.py
# All checks passed.

.\.venv\Scripts\python.exe -m mypy --ignore-missing-imports src\stock_tool\application\daily_research_loop.py src\stock_tool\dashboard\pages\home.py
# Success: no issues found in 2 source files.
```

## UI And EXE Smoke

- Isolated Daily Home AppTest and recorder smoke passed, including duplicate
  event/CTA suppression.
- `build_exe.bat` completed using the staging-first flow.
- Staging EXE health returned `ok` on port 8501.
- With port 8501 deliberately occupied, staging EXE selected port 8502 and
  `/_stcore/health` returned `ok`.
- The promoted release was also started with an isolated
  `STOCK_TOOL_USER_DATA_DIR`; port 8501 health returned `ok`.
- Isolated `reports`, `logs`, `data/cache`, and `data/daily_research` were
  verified writable. Test processes and listeners on 8501, 8502, and 8510 were
  stopped, and smoke-runtime directories were removed.

| Item | Value |
| --- | --- |
| EXE path | `release/StockTool/StockTool.exe` |
| Version | `1.2.2` |
| Modified | `2026-07-18 01:32:55 +08:00` |
| Size | `24,010,824` bytes |
| SHA-256 | `7EE0351ABB217B8E5ADBF2CC09A067F02EF7B721DB2FB06A556CA3B980E5F1D7` |

The prior release was preserved before promotion at:
`release/previous/StockTool-pre-sprint10.3.1-promotion-20260718-0134/`.

## Privacy And User Data Integrity

The final release required-asset validation passed. A recursive release scan
found no real `.env`, `secrets.toml`, token/config secret, `portfolio.csv`,
`watchlist.csv`, `stock_data.sqlite`, runtime report, log, or cache file.

Real user data was read only for before/after integrity checks:

| Path | Before | After |
| --- | --- | --- |
| `%LOCALAPPDATA%\StockTool\data\portfolio.csv` | 4 rows; `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6` | unchanged |
| `%LOCALAPPDATA%\StockTool\data\watchlist.csv` | absent | absent |
| `%LOCALAPPDATA%\StockTool\data\processed\stock_data.sqlite` | `71485B3A141654CB08A085EE043871F484DDE52A1765B3CDF9B3F9761D9B914E` | unchanged |

## Source Archive

| Item | Value |
| --- | --- |
| Archive | `release/baseline/stocktool-sprint10.3.1-20260718-source.zip` |
| Entries | 229, including the manifest |
| SHA-256 | `A4EBE193706FD9BF1DD0CC3372BA87846251F7FF0FC25C3C1F036F6C6BB1C8A7` |
| Sidecar | `release/baseline/stocktool-sprint10.3.1-20260718-source.zip.sha256` |

`verify_source_archive(archive_path=..., extracted_root=...)` returned:

- required build inputs missing: 0;
- forbidden entries: 0;
- archive content mismatches: 0; and
- current workspace content mismatches: 0.

The temporary extracted verification directory was removed afterwards.

## Known Limitations

- The Loop is deterministic and compares only currently available local,
  structured evidence; it does not fetch automatically, rank with AI, or issue
  trading recommendations.
- `resolved` means an item is absent from the latest successful local summary;
  it does not prove that a market or business risk has permanently ended.
- Fundamental, research, and composite-score availability are represented only
  when existing structured records expose them. Missing structured values remain
  data limitations rather than inferred changes.
- This implementation is ready for independent CTO acceptance review. Sprint 11
  has not been started.
