# StockTool Sprint 18.1.1 Correction — Implementation Evidence

Date: 2026-07-28 (Asia/Taipei)

## Scope boundary

Sprint 18.1.1 correction only. No Sprint 19, signing, publishing, promotion,
formal-release overwrite, reset/clean, `.git` rebuild, or real-user-data access
was performed. Existing uncommitted Sprint 18/18.1 work was preserved.

## Correction implementation

- `src/stock_tool/installer_build.py`: staging permits only expected top-level
  structure (`StockTool.exe`, `_internal`, `data/sample`, and public assets).
  It rejects `.env`/`.env.*` except exact `.env.example`, private names/stems
  regardless of extension, private key containers, unexpected top-level items,
  symlink/junction/reparse/path escape, and output/staging mutual containment.
- The only third-party private-name/container exceptions are precise relative
  paths: Certifi `cacert.pem`, PyArrow `tz_private.h`, and Streamlit
  `credentials.py`/`secrets.py`; there is no suffix-wide exception.
- `src/stock_tool/release_manifest.py`: strict SemVer parser; rollback version
  must be lower than canonical `1.2.2`; rollback path, name, and SHA must differ
  from current artifact; boolean `size_bytes` is rejected.
- `build_installer.bat` targets only `staging-sprint18.1.1` and its staging
  artifact directory.
- Tests updated: `tests/test_installer_manifest.py`,
  `tests/test_user_data_paths.py`.

## Adversarial evidence

The targeted suite includes `.env.local`, `.env.production`, `settings.toml`,
`portfolio.xlsx`, `watchlist.json`, `api_token.pem`, `signing_private.key`,
`credentials.csv`, unexpected top-level input, nested/containing output paths,
`01.2.3`, `1.2.2-..`, `9.9.9`, current version, same artifact path, same hash
under another filename, and boolean `size_bytes`.

## Validation results

| Check | Result |
| --- | --- |
| final `quality_gate.bat` | passed all configured stages |
| full pytest | 927 passed, 2 skipped, 2 intentional duplicate-entry warnings |
| configured branch coverage | 82.48% (gate 78.50%) |
| Black, Ruff, focused mypy, compileall | passed in final gate |
| privacy/release scans | passed; `privacy violations: 0` |
| staging candidate build | `STOCK_TOOL_STAGING_PARENT=release\staging-sprint18.1.1 build_exe.bat`: exit 0 |
| actual staging boundary | passed |
| isolated candidate EXE smoke | version 1.2.2; health `ok`; homepage HTTP 200; process/listeners then 0 |
| source archive create/verify | missing `()`, forbidden `()`, mismatches `()`, duplicates `()` |
| installer build | fail closed: Inno Setup `ISCC.exe` unavailable |

## Artifact hashes

| Artifact | SHA-256 |
| --- | --- |
| `release/staging-sprint18.1.1/StockTool/StockTool.exe` (24,237,195 bytes) | `25D6D3F71557682F408F13A7780A8615B15C2B3A07DF45B147D158042B8010BE` |
| `release/staging-sprint18.1.1-source.zip` | `7091C1232C0B25F554E664C73A84F20FC108A8FBD67D7DD844CFBE3F4DC5FD5E` |
| formal `release/StockTool/StockTool.exe` (unmodified) | `4BBE4175C4F07A43582D58BDABE060A0552B2B45816B865F50012154F5D370CE` |

## Prerequisite and data-preservation evidence

- Inno Setup `ISCC.exe`, `signtool`, and signing certificate are unavailable.
  Nothing was downloaded, installed, faked, or signed; installer lifecycle is
  therefore prerequisite-blocked and not claimed as passed.
- Before/after `%LOCALAPPDATA%\StockTool` is unchanged: portfolio exists at
  131 bytes with SHA-256 `A4D05D021C6FFF6EC4C561A6B4186D53782722F5244B702F3B507F953E285BF6`;
  watchlist, ledger SQLite, and settings remain absent.
- All smoke/gate work used fresh isolated `STOCK_TOOL_USER_DATA_DIR` locations.
  Final StockTool process count and 8501/8502 listener count are zero.

## Acceptance boundary

This is correction implementation evidence only. It does **not** claim CTO
acceptance, complete Sprint 18 acceptance, release approval, or authorization
to start Sprint 19.
