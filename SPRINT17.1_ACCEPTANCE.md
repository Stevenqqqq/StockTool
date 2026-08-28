# Sprint 17.1 Acceptance Record

## Status

Implementation is complete. The candidate is **not yet ready for independent
CTO acceptance** because this execution environment blocked the required
isolated EXE health and UI smoke. No Sprint 18 work or release promotion has
started.

## Scope and root causes corrected

- Persisted Research Library `sources`, `data_as_of`, and
  `snapshot_fingerprint` are now re-derived from the immutable
  `EvidenceBundle` during load. A forged value fails closed rather than being
  displayed.
- Opening a Library item now renders only the immutable saved version. It no
  longer starts the current provider research workflow.
- Saved-version rendering includes identity, version, saved/data-as-of times,
  mode, confidence, coverage, every claim semantic label, citation source,
  provider, excerpt, URL, warnings, and missing-data limitations.
- `DocumentStore.resolve()` now verifies the referenced file's SHA-256 as well
  as its existence. A removed or changed document becomes `broken_reference`;
  it never receives a fabricated URL.
- Backup restore now rejects duplicate ZIP names, directory entries, invalid
  or unexpected manifest fields, mismatched `file_count`, unsafe/unknown
  library paths, invalid size/hash metadata, oversized members, and oversized
  total uncompressed content before the atomic replacement.
- Optional provider metadata keeps JSON `null` as `None`; it is no longer
  rendered or persisted as the literal text `"None"`.

The persisted Research Library schema version remains `1`; no user-data
migration was added or run.

## RED-to-GREEN proof

The initial focused regression run intentionally failed in these cases:

- forged `sources`, `data_as_of`, and `snapshot_fingerprint` were accepted;
- a changed referenced document remained `active`;
- malformed document metadata raised an `AttributeError`/`TypeError` path;
- backup `file_count=999` was not rejected by the test fixture (after fixing
  the fixture import);
- duplicate ZIP entries were accepted.

After the implementation changes, the focused Sprint suite passed:

```text
166 passed, 1 expected duplicate-ZIP construction warning
```

The warning is emitted by Python's `zipfile` while deliberately constructing
the hostile duplicate-entry fixture; restore rejects that archive.

## Verification

- Full pytest with branch coverage: `842 passed`, `1` hostile-fixture warning.
- Branch coverage: `82.3219%` (above the Sprint 17 gate of `82.30%`).
- Focused Black check: passed.
- Focused Ruff check: passed.
- Focused mypy with missing third-party imports ignored: passed for the five
  changed production files.
- `compileall -q src`: passed.
- A full-project Black check still reports 30 pre-existing, unmodified files
  that would be reformatted. They are outside this correction scope.
- The aggregate `stock_tool.quality_gate` wrapper exceeded the host command
  timeout; its constituent pytest, coverage, focused formatting, lint, mypy,
  and compile checks above were run directly.

## Candidate EXE and release integrity

- Candidate: `release\staging-sprint17.1\StockTool\StockTool.exe`
- Candidate `--version`: `1.2.2` (passed).
- Candidate size: `24,217,737` bytes.
- Candidate modified UTC: `2026-07-27T13:51:47.8597394Z`.
- Candidate SHA-256:
  `4C65B0BFFE24CEB1E3AECDCDF0D4246C3A43908DCBCF2311F3875595E2CCBEEB`.
- `build_exe.bat` completed the PyInstaller candidate build but returned a
  non-zero status after the build. The candidate exists; the allowlisted asset
  copy and validation were rerun directly and passed.
- Formal release was not replaced. Its SHA-256 remains
  `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE`.

## EXE smoke blocker

The candidate's required `/_stcore/health` and `/` HTTP smoke remains pending.
The host execution policy rejected background process launch even with a fresh
`STOCK_TOOL_USER_DATA_DIR`. Windows UI control cannot supply the required child
arguments and isolated environment. No production user data was opened or
modified during this attempt.

Before acceptance, run the candidate with a new empty
`STOCK_TOOL_USER_DATA_DIR` and verify:

1. `StockTool.exe --version`;
2. `http://127.0.0.1:8501/_stcore/health` returns `200` and `ok`;
3. `/` returns `200`;
4. saved-version reopen renders claims/citations without provider fetch;
5. backup/restore, tampered backup rejection, and broken-document UI;
6. no StockTool process and no 8501/8502 listener remain after shutdown.

## Privacy, source archive, and rollback

- Source privacy scan: `0` violations.
- Staging runtime/private-file scan: `0` forbidden files.
- Source archive:
  `release\baseline\stocktool-sprint17.1-20260727-source.zip`
- Archive entries: `284`.
- Archive SHA-256:
  `BEB9EB571BE0E9F7ECD624A2D3C81B33FEC49C79ACB38CAB3873F38531D1B21E`.
- Archive verification: `0` missing required inputs, `0` forbidden entries,
  `0` content mismatches.
- Sidecar:
  `release\baseline\stocktool-sprint17.1-20260727-source.zip.sha256`.

Rollback remains the unchanged formal `release\StockTool\StockTool.exe` and
the prior accepted baseline. The Sprint 17.1 candidate is staging-only.

## Known limitations

- There is no OCR, cloud sync, new AI provider, installer work, migration, or
  release promotion in this correction Sprint.
- Document content is never copied into the library; only local metadata and
  hashes are retained.
- Independent acceptance is blocked only by the unexecuted isolated EXE
  health/UI smoke described above.
