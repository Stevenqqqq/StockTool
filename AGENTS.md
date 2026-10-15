# StockTool Governance

- Product Owner owns product direction, scope, implementation approval and release approval.
- Primary Engineer owns approved architecture, implementation, integration and self-test evidence. Roles are not tied to model names.
- Worker executes bounded delegated work; one writer owns each overlapping area. Delegation requires user authorization.
- Acceptance Reviewer independently verifies frozen candidates, compatibility and user workflows. Implementers cannot accept their own work.
- External Reviewer provides advisory findings, not approval or release authority.
- Reviews do not modify code. Implementation and acceptance remain separate.
- Only one Sprint may be active. Complete approved work, then stop for independent acceptance.
- Every Sprint requires targeted tests, full pytest, coverage, quality checks, EXE smoke testing and release privacy scanning. Distinguish failed, skipped, waived and unverified checks.
- Never modify, move or overwrite real user data. Verify with isolated or synthetic runtimes.
- Current local formal installation/delivery reference is v1.4.3, recorded in docs/product/v1.4.3-host-upgrade.md. Acceptance is itemized, not an unconditional product pass: guest lifecycle was waived; empty research library and shortcut double-click limitations remain. Sprint 33.1.1 / v1.4.0 is a historical reference, not the current installed baseline.
- Later MU, daily-holdings, names and research-header candidates retain their individual acceptance status; acceptance does not promote candidates to the formal installation. Research Integrity Gate v1, Backtest Evidence v1, synthetic-only Scenario Research, chart r3 and source-import fixes retain their accepted source scopes; none promotes the formal installed baseline. See docs/product/accepted-source-sync-20261011.md.
- PRODUCT_EXECUTION_PLAN.md preserves the historical roadmap; the Product Owner's latest approved scope controls the active Sprint. The current authorization covers accepted-source synchronization to an isolated GitHub branch and PR only. It does not authorize merging main, new development, rebuilding EXEs, installation or publication.
