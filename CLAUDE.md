# Veris Capital AMC — NAV Data Collection System

## Session Start Checklist

At the start of each new conversation, before working on any tasks:

1. **Read all project docs** — silently, never announce it:
   - `CLAUDE.md` (this file), `README.md`, `plans/*.md`
   - All files in `docs/internal/`, `docs/methodology/`, `docs/reference/`
   - `.claude/skills/*/SKILL.md`
2. **Scan the codebase**: `config/*.json` for patterns and dependencies, `src/*.py` and `src/*/` for interfaces and integration points.

Do NOT rely on memory alone — always re-read.

---

## Mandatory Workflow: Before Any Implementation

1. **Check dependencies.** Read all config and src files the change touches or could affect. Check `architecture.md` "Adding New Components" table.
2. **Check the Valuation Policy** (`docs/reference/valuation_policy_v1.0.md`) if the change affects pricing, valuation, or verification.
3. **After writing, review the diff** against the Architecture Principles below.

---

## Research & Data Fetching Rules

- **Never use WebFetch to explore or guess URLs.** Use `gh` CLI for GitHub repos, or ask Alex to research it in Claude.ai first.
- **One failed fetch = stop and switch strategy.** Do not retry WebFetch with URL variations. Switch tool (`gh`, `curl`, known API) or ask Alex.
- **GitHub content: always `gh` CLI** — `gh repo clone`, `gh api repos/.../contents/path`, `gh repo view`.
- **Blockchain/DeFi research (oracle feeds, contract addresses, API endpoints): ask Alex first.** Claude.ai has web search. You don't. Don't guess endpoints or scrape SPAs.
- **SPA dashboards (app.maple.finance, app.onre.finance, etc.) return empty HTML.** Use the protocol's API, GraphQL, or on-chain calls instead.

---

## Decision Making

- **If the answer is in the project's own docs (Valuation Policy, methodology, config specs), implement it. Don't ask "want me to do X?"** Citing the policy and then asking permission to follow it wastes a turn.
- **Only ask when there's genuine ambiguity** — policies conflict, docs are silent, or the change has significant side effects outside scope.
- **After fixing something, don't narrate the before/after math.** Confirm what changed and move on.
- **Don't self-deprecate or narrate mistakes.** Just correct course.

---

## Architecture Principles

All code must follow these. No exceptions. Full detail in `docs/internal/architecture.md`.

1. **Config-driven, not code-driven.** New positions, chains, tokens, protocols, verification sources = config changes only. Code implements patterns; config declares instances.
2. **No hardcoded values.** Addresses, RPC URLs, feed IDs, chain IDs, decimals, thresholds — all in config. Only structural constants (Anchor discriminators, ERC-4626 signatures) acceptable in code.
3. **Single source of truth.** Each piece of data defined in exactly one place. Never duplicate.
4. **Category-driven valuation.** Category (A1–F) determines methodology. Pricing routes through `pricing.py` → `pricing_policy.json`.
5. **Separation of concerns.** Each module owns one responsibility. See `architecture.md` for module map.
6. **Library modules, not standalone scripts.** Core modules have no `main()`. Only `collect.py` is an entry point. `src/tools/` and `src/falconx/` may be standalone.
7. **`decimal.Decimal` for all financial calculations.** Never `float` or `math.pow()`.
8. **Log every query.** Contract address, function called, block number, result.
9. **Comments explaining "why"**, not "what". Non-obvious logic gets a business-reason comment.
10. **Tests updated with every change.** A feature is not complete until its tests pass: `python -m unittest discover -s tests -v`.
11. **Timestamps in UTC**: `dd/mm/yyyy hh:mm:ss` (e.g. `23/03/2026 19:21:35`).

---

## Pre-Commit Checklist (Mandatory)

Before EVERY commit and push, run this full audit autonomously — do not wait to be asked:

### 1. Code Consistency
- Scan `src/**/*.py` for hardcoded values (addresses, chain IDs, feed IDs, URLs, decimals) — must be in config.
- Check for unused imports, dead functions, orphaned adapters/handlers.

### 2. Config Integrity
- Every token in `tokens.json` with an oracle feed → has entry in `price_feeds.json`.
- Every protocol in `wallets.json` → has `_query_type` in `contracts.json` → has handler in `HANDLER_REGISTRY`.
- Every source in `verification.json` → has working verifier in `src/verifiers/`.
- `solana_protocols.json` entries match what `solana_client.py` actually queries.
- No config references (addresses, feed IDs, program IDs) living in code instead of config files.

### 3. Doc Sync
- `README.md`: test count, position count, net NAV, feature list, project structure, verifiers list.
- `docs/internal/architecture.md`: new modules/handlers/adapters/verifiers in "Adding New Components" table.
- `docs/internal/protocol_sourcing.md`, `data_sources.md`, `portfolio_positions.md`: if anything changed.

### 4. Tests
- `python -m unittest discover -s tests -v` — all pass.
- New config/handler/adapter/verifier → corresponding test exists.

### 5. Final Sanity
- `python src/collect.py` (no --date) — no runtime errors.
- Check for warnings, zero-value positions, or $1.00 fallback prices. Investigate before committing.

Only after all 5 pass: `git add -A && git commit && git push`.

---

## Maintenance Rules

**Memory**: Update `.claude/projects/.../memory/` every hour during long sessions and after every significant milestone.

**Doc updates are part of implementation, not a follow-up.** A feature is not complete until all affected docs are updated in the same pass. Check: `architecture.md`, `protocol_sourcing.md`, `data_sources.md`, `portfolio_positions.md`, `nav_output_spec.md`, `valuation_methodology.md`. Before each NAV date, regenerate `NAV_Data_Sourcing_Methodology.pdf` using `claude_code_formatting_prompt.md`.

**Config data** (addresses, ABIs, feeds, chain IDs, RPC URLs) belongs in `config/*.json`, never in docs or CLAUDE.md. Docs explain *how* and *why*, not *what*. No subjective assessments about position sizes — state facts only.

See `README.md` for project overview, parties, valuation schedule, asset categories, and output format.
