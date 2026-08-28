# Sprint 19.1.1.2 — Browser Journey Evidence

## Status

**BLOCKED**

This is implementation evidence only. It is not CTO acceptance, release approval, or authority to start another Sprint.

## Scope and changes

No file under `src/stock_tool`, no candidate executable, installer, payload, or
formal `release/StockTool` artifact was changed. New evidence is under
`artifacts/sprint19.1.1.2/`; this acceptance record is the only repository
document change.

The product owner's 2026-07-30 keyboard and 100%/125%/150% zoom observations
are recorded in `browser-result.json` as manual observations only. No automated
key events, screenshots, or browser-result field substitutes for those manual
observations.

## Frozen artifacts

| Artifact | Required and observed SHA-256 |
| --- | --- |
| Candidate stable EXE | `F22118A584A7AB353372136D2C42B66E2D89CCD204CC25D5D992DA252E45F0D8` |
| Candidate payload EXE | `0A5C40F9E2BC5F4C96B2B48D10FBEEFAAC9E9E5A436ED8A6DAB9B725891FDC25` |
| Internal-test installer | `AA6137AE7E186E85E000A19AB4627B54F3AA8489F315D64805ABE88B997EA5E6` |
| Formal release EXE | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

The before and after candidate/formal hash checks match. See
`artifacts/sprint19.1.1.2/artifact-hashes-after.json`.

## Visible-browser online journeys

The frozen stable EXE was launched with
`STOCK_TOOL_USER_DATA_DIR=artifacts/sprint19.1.1.2/browser-user-data` and the
visible StockTool browser page was exercised for each market. Active console
was captured before process teardown; teardown console is separate.

| Scenario | Observed result | Status | Evidence |
| --- | --- | --- | --- |
| Online 2330 / TWSE | `2330.TW`, yfinance online, Taiwan Semiconductor Manufacturing Company Limited, close 2280.00, date 2026-07-28, coverage 100% | BLOCKED | `browser/2330-online-result.png`, `.dom.txt`, `-console-active.json` |
| Online 6488 / TPEX | `6488.TWO`, yfinance online, GlobalWafers Co., Ltd., close 959.00, date 2026-07-28, coverage 100% | BLOCKED | `browser/6488-online-result.png`, `.dom.txt`, `-console-active.json` |
| Online AAPL / US | `AAPL`, yfinance online, Apple Inc., close 341.48, date 2026-07-29, coverage 100% | BLOCKED | `browser/aapl-online-result.png`, `.dom.txt`, `-console-active.json` |
| Offline cache, all three markets | No reliable candidate-child-only online failure was established; cache fallback is not claimed | BLOCKED | `browser-result.json` |
| Partial failure, all three markets | The frozen EXE had no reliable external partial-failure harness; no hidden production hook was added | BLOCKED | `browser-result.json` |

## Blocking observations

1. The active browser console contains `WARN Infinite extent for field "date"`.
   This is visible in each online console artifact and prevents a clean active
   console result.
2. The 6488 page identifies GlobalWafers but renders NAND Flash/SSD/storage
   company-context statements inconsistent with that company.
3. Returning to the research home renders literal `上次研究：None` for the
   just-created entries (`browser/between-2330-6488.dom.txt`).
4. Offline-cache and partial-failure cannot be evidenced reliably without a
   controlled candidate-only transport/failure mechanism. No fixture was used
   to impersonate a browser journey and no product code was modified.
5. The existing `artifacts/sprint19.1.1/lifecycle-replay-2/lifecycle-result.json`
   reports `passed`, 17 commands, and five snapshots, but it does not contain
   the frozen stable/payload/installer hashes. It is therefore not reused as
   hash-bound lifecycle evidence here.
6. The current real-data manifest is not equal to the prior 19.1.1 preservation
   baseline: 185 files / 4,683,263 bytes versus 182 files / 4,680,340 bytes.
   The three additional files are a legacy-migration backup and two Streamlit
   logs dated 20260730_010511. They were not deleted, moved, altered, or
   restored. This prevents a real-user-data preservation assertion.

## Preservation and cleanup

`release/StockTool/StockTool.exe` remains at the required formal SHA-256 above.
Read-only data manifests are `artifacts/sprint19.1.1/preservation-after.json`
and `artifacts/sprint19.1.1.2/real-user-data-after.json`.

After the evidence capture, only this run's candidate process tree was
terminated. `artifacts/sprint19.1.1.2/processes-after.json` and
`listeners-after.json` record zero StockTool/StockToolPayload processes and no
8501/8502 listener.

## Quality and lifecycle gates

Per the evidence-only Sprint boundary, work stopped on the real product and
data-preservation blockers above. Targeted/full pytest, coverage, Black, Ruff,
mypy, compileall, performance hard gate, pip-audit, privacy scan, and source
archive verification were **not rerun** for this blocked evidence pass. No
previous quality or lifecycle verdict is presented as a replacement.

Primary machine-readable evidence:
`artifacts/sprint19.1.1.2/browser-result.json`.
