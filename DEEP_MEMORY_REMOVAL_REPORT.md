# Deep Memory Removal Report

Date: 2026-07-12

## Scope and Project Safety

This task did not modify StockTool product code, tests, build output, release assets, or user
portfolio data. The only project files added are `AGENTS.md` and this removal/audit documentation.
No Sprint was started. Sprint 3.2.1 remains the formal acceptance baseline.

## Governance Preservation

Read before removal:

- `PROJECT_WHITEPAPER.md`
- `PRODUCT_VISION.md`
- `PRODUCT_EXECUTION_PLAN.md`
- `SPRINT3.2.1_ACCEPTANCE.md`
- `C:\Users\steve\.deep-memory\knowledge-base\project-collaboration.md`

Created `AGENTS.md` with only the durable governance rules: user decision authority, ChatGPT CTO
and acceptance role, Codex Terra delivery scope, single-Sprint sequencing, review/implementation
separation, required verification, user-data protection, Sprint 3.2.1 baseline, and roadmap
authority.

## Read-only Inventory Findings

- User skill root: `C:\Users\steve\.codex\skills`
- No `~/.agents/skills`, project `.codex/skills`, or project `.agents/skills` directory exists.
- No relevant project `AGENTS.override.md`, global `AGENTS.override.md`, or local skill path exists.
- No reparse point was found in the preserved Deep Memory content tree.
- `DEEP_MEMORY_WORKSPACE` was unset in Process, User, and Machine scopes before removal.

## Preservation Backup

The following non-rebuildable content was copied before any cache removal:

- `knowledge-base/` Markdown and JSON index files
- `experience/` Markdown and JSON index files
- `cold-notes/` JSONL content

Artifacts:

- ZIP: `C:\Users\steve\.codex\backups\deep-memory-removal\deep-memory-preservation-20260712-024923.zip`
- Manifest: `C:\Users\steve\.codex\backups\deep-memory-removal\deep-memory-preservation-20260712-024923.manifest.json`
- SHA-256 sidecar: `C:\Users\steve\.codex\backups\deep-memory-removal\deep-memory-preservation-20260712-024923.zip.sha256`
- SHA-256: `0EC0304E20156C8AD5D8831930EC3D5FA101AAE67ED521F657C2D8BD6947F0E8`
- Source files: 11
- Source size: 84,331 bytes
- ZIP entries: 12, including `backup-manifest.json`

The ZIP was opened with `System.IO.Compression.ZipFile::OpenRead` and every entry stream was
opened successfully. The backup is outside `~/.deep-memory`.

## Disable and Removal Actions

1. Removed the complete `Task Launch Protocol (Mandatory)` block from
   `C:\Users\steve\.codex\instructions.md`.
   - The unrelated World Cup routing rule was retained.
2. Cleared `DEEP_MEMORY_WORKSPACE` in Process and User scopes.
   - The Machine scope is empty. A no-op write attempt was denied because the current session has
     no administrator registry permission; no configured Machine value remains.
3. Moved, rather than deleted, the four Skills to:
   `C:\Users\steve\.codex\disabled-skills\deep-memory-removal-20260712-025050\`
   - `deep-memory`
   - `chroma-hybrid-search`
   - `memory-backup`
   - `memory-import`
4. Removed only rebuildable Deep Memory runtime artifacts after backup verification:
   - `C:\Users\steve\.deep-memory\.venv`
   - `C:\Users\steve\.deep-memory\chroma_hybrid_db`
5. Retained the original `knowledge-base`, `experience`, and `cold-notes` directories as an
   additional local preservation copy. No isolated Skill or backup ZIP was deleted.

An empty `deep-memory-removal-20260712-025017` directory exists from the aborted Machine-scope
permission check. It contains no Skill and is outside all Skills discovery paths.

## Final Validation

- The active `~/.codex/skills` list contains none of the four memory Skills.
- `instructions.md` contains no `Task Launch Protocol`, `deep-memory`,
  `chroma-hybrid-search`, `memory-backup`, `memory-import`, or `DEEP_MEMORY_WORKSPACE` reference.
- Project `AGENTS.md` is readable and contains no Deep Memory reference.
- Process, User, and Machine `DEEP_MEMORY_WORKSPACE` values are empty.
- No invalid active Skill path was found.
- `.system`, plugin cache, bundled Skills, other Python environments, StockTool core code, and
  real user data were not removed or modified.
- Full pytest and EXE rebuild were intentionally not run because no product code changed.

See `SKILLS_AUDIT.md` for the read-only audit of other user-managed Skills.
