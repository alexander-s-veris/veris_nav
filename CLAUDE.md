# Veris Capital AMC — NAV Data Collection System

## Session Start Checklist

At the start of each new conversation, before working on any tasks:

**1. Read all project docs:**
- `CLAUDE.md` (this file — rules and context)
- `README.md`
- `plans/*.md` — current and future implementation plans
- `docs/internal/*.md`:
  - `architecture.md` — system design, module responsibilities, "Adding New Components" table
  - `valuation_methodology.md` — category A1–F valuation rules
  - `protocol_sourcing.md` — how to read positions from each protocol
  - `portfolio_positions.md` — current positions by category
  - `data_sources.md` — oracle feeds, APIs, RPC endpoints
  - `nav_output_spec.md` — output format, methodology log, NAV formula
- `docs/methodology/*.md`:
  - `NAV_Data_Sourcing_Methodology.md` — complete technical spec for Bank Frick (pricing categories, data sources, verification). Must be regenerated as PDF before each NAV date using `claude_code_formatting_prompt.md`
  - `falconx_accrual_analysis.md` — A3 position methodology and verification
- `docs/reference/valuation_policy_v1.0.md` — Valuation Policy (the authoritative legal document)
- `.claude/skills/*/SKILL.md` — operational skills

**2. Review the codebase:**
- Scan `config/*.json` for existing patterns, dependencies, single source of truth
- Scan `src/*.py` and `src/*/` for interfaces, helpers, integration points
- Check `docs/internal/architecture.md` "Adding New Components" table

Do NOT rely on memory alone — always re-read. Do this silently — never announce "let me read the codebase" mid-conversation. If you find yourself saying "let me check X first", you skipped this step.

---

## Mandatory Workflow: Before Any Implementation

⚠️ KNOWN FAILURE PATTERN: You have repeatedly skipped this workflow when the task "feels simple" — then produced code with hardcoded values, missed dependencies, or architecture violations that required full rewrites. There are no simple tasks in this codebase. Every change touches config, handlers, adapters, or valuation logic that you WILL get wrong without the review step. Treat every task as complex.

Before writing or modifying ANY code, you MUST complete all four steps below AND print the output. If you have not printed a dependency list and a plan summary, you are not allowed to write code.

1. **Check dependencies — and print what you found.** Read all `config/` and `src/` files the change touches or could affect. Check for duplications with existing code. Check architecture.md "Adding New Components" table for the correct pattern. Then print:
   - FILES READ: [list every file you opened]
   - EXISTING PATTERNS FOUND: [relevant code/config you'll integrate with]
   - POTENTIAL CONFLICTS: [anything that could break]
   If this list is empty or vague, you skipped the review.
2. **Check the Valuation Policy** if the change affects pricing, valuation, or verification. Verify implementation matches `docs/reference/valuation_policy_v1.0.md`.
3. **After writing, review the diff** against the architecture principles below. Keep code short, clean, and minimal — no over-engineering, no speculative abstractions.
4. **Summarise your plan and STOP.** Before writing any code, output a brief implementation plan: what you'll change, in which files, and how it integrates with existing patterns. Then wait for approval. Do NOT proceed to implementation until the user confirms. The only exception is if the user has explicitly said "go ahead without checking" for this specific task.

---

## Architecture Principles (Gold Standard)

All code must follow these. No exceptions. Defined in `docs/internal/architecture.md`.

1. **Config-driven, not code-driven.** Adding a new position, chain, token, protocol, or verification source requires only config changes. Code implements patterns; config declares instances.
2. **No hardcoded values.** Contract addresses, wallet addresses, token symbols, RPC URLs, API endpoints, oracle feed IDs, chain IDs, program IDs, decimals, thresholds — all in config. Only structural constants (Anchor discriminator patterns, ERC-4626 function signatures) are acceptable in code.
3. **Single source of truth.** Each piece of data defined in exactly one place. Never duplicate across files. Authoritative locations documented in `docs/internal/architecture.md`.
4. **Category-driven valuation.** Category (A1–F) determines methodology. Pricing routes through `pricing.py` → `pricing_policy.json`. Category definitions in `docs/internal/valuation_methodology.md`.
5. **Separation of concerns.** Each module owns one responsibility:
   - `collect.py` — orchestration (the only entry point)
   - `handlers/` — protocol-specific position reading
   - `adapters/` — price feed queries
   - `verifiers/` — independent verification (Section 7)
   - `valuation.py` — category-specific pricing
   - `pricing.py` — price hierarchy walker
   - `output.py` — snapshot writing
   - `src/falconx/` — A3 accrual data pipeline (runs separately before `collect.py`)
   - `src/tools/` — standalone utilities (diff, PDF generation, cache)
6. **Library modules, not standalone scripts.** Core modules have no `main()`. Only `collect.py` is an entry point. `src/tools/` and `src/falconx/` may be standalone.
7. **`decimal.Decimal` for all financial calculations.** Never `float` or `math.pow()` for prices/amounts.
8. **Log every query.** Contract address, function called, block number, result.
9. **Comments explaining "why".** Non-obvious logic gets a comment explaining the business reason.
10. **Tests must be updated with every change.** When adding a new config file, feature, handler, adapter, verifier, or any structural change — update the compliance tests (`tests/test_valuation_policy_compliance.py`). Tests validate cross-referential integrity across all config files and code registries. A feature is not complete until its tests pass. Run: `python -m unittest discover -s tests -v`.

---

## Discipline Rules

These exist because of repeated failures where Claude followed none of the above despite knowing the rules.

1. **Never write code in the same message as reading files.** The review step and the implementation step must be separate messages. Read first, summarise, get approval, then implement.
2. **If you catch yourself thinking "this is a small change, I can skip the review" — that is the signal to do the full review.** Small-seeming changes in this codebase have the highest rate of hidden dependencies.
3. **If you produce code that violates Architecture Principles, the code will be rejected and you will redo the full workflow from step 1.** This is not a threat — it is what actually happens every time.

---

## Project Overview

Python-based data collection system for the Veris Capital AMC (ISIN: LI1536896288), an open-ended Actively Managed Certificate issued by 10C PCC / 10C Cell 11 PC. Collects on-chain positions, oracle prices, and market data to produce a canonical NAV snapshot file for the NAV workbook (Excel).

**Product**: USD-denominated stablecoin yield fund across DeFi protocols on Ethereum, Arbitrum, Base, Avalanche, Plasma, Monad, Solana, Katana, and HyperEVM. No volatile spot tokens (BTC, ETH, SOL) as directional positions. Category F covers anything not in A1–E.

**Parties**: Bank Frick AG (Calculation Agent / Paying Agent / Custodian), ZEUS Anstalt (Investment Manager), Vistra (Administrator), ForDefi (on-chain custodian), Kraken (additional custodian), Grant Thornton (Auditor).

**Valuation**: Monthly (last calendar day). Valuation Time 16:00 CET = 15:00 UTC year-round (no DST). Valuation Block = block closest to but not exceeding 15:00 UTC. NAV Report due within 7 business days. First NAV date: 31 March 2026.

---

## Development Guidelines

- Keep code readable — Bank Frick will review it
- Keep code short and clean — no over-engineering, no speculative abstractions
- Use `.env` for all API keys and RPC URLs
- Output timestamps in UTC: `dd/mm/yyyy hh:mm:ss` (e.g. `23/03/2026 19:21:35`)
- Each function should do one thing clearly
- Run tests after changes: `python -m unittest discover -s tests -v`

---

## Maintenance Rules

**Memory**: Update memory files (`.claude/projects/.../memory/`) every hour during long sessions and after every significant milestone. Memory should reflect the current project state.

**Doc updates are part of implementation, not a follow-up.** A feature is not complete until all affected docs are updated. When implementing a change, update every doc it touches in the same pass — do not create separate tasks or flag docs for later. Affected docs for common changes:
- New/changed architecture → `architecture.md` (including "Adding New Components" table)
- New protocol or data source → `protocol_sourcing.md`, `data_sources.md`
- Position changes → `portfolio_positions.md`
- Verification/output changes → `nav_output_spec.md`, `valuation_methodology.md`
- Before each NAV date → regenerate `NAV_Data_Sourcing_Methodology.pdf` using `claude_code_formatting_prompt.md`

**What belongs in `docs/internal/`**: Methodology, process, reference information, gotchas — things that explain *how* and *why*. Not data that lives in config or code.

**What does NOT belong in `docs/internal/` or `CLAUDE.md`**:
- Contract addresses, wallet addresses, feed addresses → config files (`wallets.json`, `contracts.json`, `price_feeds.json`, `verification.json`)
- ABIs → `abis.json`
- RPC URLs, chain IDs → `chains.json`
- Token lists, pricing config → `tokens.json`
- Project structure → the filesystem
- Test specs → the test files
- Subjective assessments about positions (e.g. "small position", "large allocation") — state facts only. Position sizes change; docs should not need updating because a position grows or shrinks.
