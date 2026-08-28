# Git Baseline Recovery Record

- Established: 2026-07-28 (Asia/Taipei)
- Scope: current StockTool workspace
- Branch: `main`
- Git metadata: `%USERPROFILE%\GitMetadata\StockTool.git` (outside OneDrive)
- User authorization: approved creation of a new Git baseline from the current StockTool workspace

## Recovery boundary

This commit starts a new Git history. It does not reconstruct or claim to contain the deleted original Git commits.

The previous `.git` OneDrive reparse-point directory was empty. Before initialization, the current workspace matched all 286 files in the verified Sprint 17.1.3 source archive manifest. The archive SHA-256 was:

`4128492FFCB0587D1AECD2D3136598CFCD7628E786F2BF6D43A30B2366E8957C`

The empty placeholder was retained under `backups/git-baseline-recovery/` and is excluded from Git.

## Safety boundary

Generated builds, releases, caches, local logs/reports, backups, environment secrets, databases, and non-sample data are excluded. Real application user data is not part of this repository.

Five historical acceptance records remain present locally but are ignored because the fail-closed privacy scanner detected credential-like examples in them: `SPRINT2.1_ACCEPTANCE.md`, `SPRINT2.1.1_ACCEPTANCE.md`, `SPRINT15.1.1_ACCEPTANCE.md`, `SPRINT15.1.2_ACCEPTANCE.md`, and `SPRINT15.1.3_ACCEPTANCE.md`. They were not edited or deleted.

During baseline verification, the existing quality gate exposed a test-isolation defect: one price-provenance test allowed a live fundamentals fetch to write one 2330/TWSE row to the real runtime `fundamentals_auto.csv`. The pre-run aggregate user-data fingerprint proves that file changed, but no byte-identical previous copy was available, so the real file was not approximately overwritten. The test now isolates its path and forbids that fetch, and the quality gate redirects all subprocesses to a temporary `STOCK_TOOL_USER_DATA_DIR`.

This Git recovery baseline is not a new Sprint, release promotion, or formal product acceptance decision.
