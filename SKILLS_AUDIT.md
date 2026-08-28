# User-managed Skills Audit

Date: 2026-07-12

## Scope

Read-only audit only. Included user-managed Skills under `C:\Users\steve\.codex\skills`.
Excluded `.system`, plugin cache/bundled Skills, missing project/Agents skill roots, and the
four Deep Memory Skills already moved to `C:\Users\steve\.codex\disabled-skills`.

First-pass method: directory file list, `SKILL.md` frontmatter/description, size, named dependency
files, and script filenames. Only Serenity, World Cup, and Vercel manifests/scripts were sampled
where their trigger or execution behavior needed clarification. No Skill script was executed.

Classifications are recommendations only. No non-memory Skill was moved, disabled, deleted, or
modified.

| Skill / path | Function and trigger | Misfire / StockTool relevance | Shell/tools and dependencies | Duplication / context cost | Recommendation |
|---|---|---|---|---|---|
| `code-review-and-quality`<br>`~/.codex/skills/code-review-and-quality` | Multi-axis code review before merge or formal review. | Low accidental trigger risk; directly supports Sprint review and acceptance. | Guidance only; no bundled script or declared dependency. | Complements debugging/TDD; 18 KiB, low. | **建議保留**: aligns with governance and independent review. |
| `debugging-and-error-recovery`<br>`~/.codex/skills/debugging-and-error-recovery` | Root-cause debugging for failures, broken builds, or mismatched behavior. | Low; directly useful for pytest, EXE, provider, and Windows failures. | Guidance only; no declared dependency. | Complements TDD rather than duplicates it; 10 KiB, low. | **建議保留**. |
| `security-and-hardening`<br>`~/.codex/skills/security-and-hardening` | Security review for inputs, storage, and third-party integrations. | Low; directly relevant to API tokens, local user data, providers, and EXE release scans. | Guidance only; no declared dependency. | Distinct from code review; 18 KiB, low. | **建議保留**. |
| `test-driven-development`<br>`~/.codex/skills/test-driven-development` | Test-first implementation and regression proof. | Moderate broad trigger, but directly useful whenever behavior changes. | Guidance only; no declared dependency. | Complements debugging and QA; 15 KiB, low. | **建議保留**. |
| `web-design-guidelines`<br>`~/.codex/skills/web-design-guidelines` | UI/UX and accessibility audit for web interfaces. | Triggered mainly by explicit UI review; relevant to Streamlit Dashboard. | Guidance only; no declared dependency. | Different from React implementation patterns; 1 KiB, low. | **建議保留**. |
| `writing-guidelines`<br>`~/.codex/skills/writing-guidelines` | Documentation/prose quality audit. | Can trigger broadly on documentation requests; relevant to README and acceptance reports. | Guidance only; no declared dependency. | Separate from code review; 1 KiB, low. | **建議改成手動使用**: invoke for explicit document audits. |
| `Serenity-aleabitoreddit-skill`<br>`~/.codex/skills/Serenity-aleabitoreddit-skill` | Evidence-conscious chokepoint thesis for AI/semi supply chains, catalysts, valuation mismatch, and risk. | Moderate; highly relevant to the stock research product, but should be explicit so it does not override normal analysis. | Reference Markdown only; no executable script or declared package dependency. | Overlaps strongly with `serenity-skill`; 83 KiB, medium. | **建議與其他 Skill 合併**: retain this as the evidence/guardrail reference if one Serenity skill is kept. |
| `serenity-skill`<br>`~/.codex/skills/serenity-skill` | Broad live-source supply-chain bottleneck research, theme scans, screening, and thesis stress tests. | High accidental cost: its default asks for deep research, potentially 20 companies and 25 sources. Relevant to the product domain, but not routine coding. | Local Python scorecard/validator; web/search/filing/browser and optional Python are expected. | Strongly overlaps the other Serenity skill; 64 KiB, medium. | **建議與其他 Skill 合併**: keep only one canonical Serenity workflow after user review; until then use manually and do not auto-trigger. |
| `composition-patterns`<br>`~/.codex/skills/composition-patterns` | React component composition and React 19 API patterns. | Low for current Streamlit Python UI; useful only if a future React frontend exists. | Guidance/reference only; no declared dependency. | Overlaps React best-practices; 49 KiB, medium. | **建議改成手動使用**. |
| `react-best-practices`<br>`~/.codex/skills/react-best-practices` | React/Next.js rendering, data fetching, and bundle performance. | Low for present Streamlit + Windows EXE product. | Guidance/reference only; no declared dependency. | Overlaps composition/transitions; 225 KiB, high. | **建議隔離觀察**: retain only for a confirmed React migration. |
| `react-native-skills`<br>`~/.codex/skills/react-native-skills` | React Native/Expo mobile performance and native modules. | Very low relevance: product has no mobile app or React Native code. | Guidance/reference only; no declared dependency. | No meaningful overlap with current Streamlit work; 155 KiB, high. | **建議隔離觀察**: retain for a future mobile decision, not automatic use. |
| `react-view-transitions`<br>`~/.codex/skills/react-view-transitions` | React view-transition implementation. | Very low relevance to Streamlit and Windows EXE today. | Guidance/reference only; no declared dependency. | Narrow React-only overlap; 76 KiB, medium. | **建議隔離觀察**. |
| `deploy-to-vercel`<br>`~/.codex/skills/deploy-to-vercel` | Vercel preview/production deployment workflow. | Low unless the product is intentionally deployed as a web application; not needed for onedir EXE. | Shell scripts call Git/Vercel CLI and can create deployment activity; network/account context required. | Overlaps Vercel CLI token skill; 40 KiB, medium. | **建議改成手動使用**. |
| `vercel-cli-with-tokens`<br>`~/.codex/skills/vercel-cli-with-tokens` | Token-based Vercel deployment and management. | Higher safety risk: instructions inspect environment and `.env` for tokens. Not relevant to current EXE release. | Uses Vercel CLI and token/`.env` discovery; network/account access required. | Overlaps deploy-to-vercel; 10 KiB, low. | **建議隔離觀察**: do not auto-trigger around this local product. |
| `vercel-optimize`<br>`~/.codex/skills/vercel-optimize` | Metric-led Vercel cost and performance audit. | Very low current relevance; needs deployed linked app and observability signals. | Node 20+, Vercel CLI v53+, authenticated linked project, possibly Observability Plus. | Overlaps Vercel deploy tools; 808 KiB, high. | **建議隔離觀察**. |
| `worldcup-predictor`<br>`~/.codex/skills/worldcup-predictor` | Deterministic World Cup match/tournament/lottery analysis from audited offline snapshots. | Narrow trigger; unrelated to StockTool but serves an independent user purpose and is globally routed in `~/.codex/instructions.md`. | Node.js 20+; local `.mjs` CLI and tests; offline bundled data. | No overlap with stock tools; 805 KiB, high. | **建議保留**: keep as a separate, explicit-purpose Skill. |

## Key Conclusions

1. **Serenity overlap:** the two Serenity Skills should not both be broad defaults. The
   `Serenity-aleabitoreddit-skill` is the more focused evidence/guardrail reference; the
   broader `serenity-skill` has a more expensive default live-research workflow. A future
   consolidation should preserve source hierarchy, risk controls, and the local scorecard, then
   expose one explicit trigger. No merge was performed here.
2. **React and React Native:** none are required by the current Python/Streamlit/Windows EXE
   architecture. Keep only as manually invoked future-platform references; React Native is the
   least relevant today.
3. **Vercel:** Vercel deployment, token, and optimization Skills do not support the present local
   EXE delivery path. They should remain opt-in only. The token-oriented Skill deserves extra
   caution because it proposes `.env` and environment inspection.
4. **Core engineering Skills:** code review, debugging, security, TDD, and web design are all
   directly valuable to the current project and should remain available.
5. **World Cup:** it is a legitimate separate-purpose Skill. Lack of StockTool relevance is not a
   reason to remove it.
