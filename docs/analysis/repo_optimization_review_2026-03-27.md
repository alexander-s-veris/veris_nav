# Repository review: optimisation, scalability, and protocol/chain/token agnosticism

Date: 2026-03-27

## Executive summary

The current architecture is already in a strong place for low-change growth: config-driven protocol registration (`wallets.json` + `contracts.json` + handler dispatch) and category-based valuation are solid foundations.

The biggest opportunities are:

1. **Move from single-process/threaded IO to bounded async + provider-aware rate limits** for better throughput and fewer intermittent RPC/API failures.
2. **Formalise config schemas + plugin contracts** so adding a new chain/protocol/token is deterministic and validated pre-run.
3. **Introduce a canonical asset identity layer** (`asset_id`) to reduce symbol/address special-casing across modules.
4. **Improve resilience and determinism** (strict retries, timeout budget, stale price gates, idempotent snapshots).
5. **Split collection/valuation/output into independently runnable stages** to scale to more wallets/chains without touching core logic.

## What is already working well

- **Config-first extensibility is implemented**: the system maps protocol sections to query handlers via `_query_type` and registry-style dispatch, reducing code edits for many new positions.
- **Category-driven valuation is separated from extraction**, which keeps pricing policy changes isolated from protocol query code.
- **Concurrent query helper exists** and is used across the codebase.
- **Output model is audit-friendly** (positions + summary + leverage/PT/LP detail artifacts).

These are exactly the right primitives for scale.

## Key bottlenecks and risk points

### 1) Concurrency model will become fragile as chains/providers increase

Today, concurrency is thread-based and generic. This works now, but with more chains/providers it tends to fail via:
- heterogeneous provider limits,
- bursty request patterns,
- hard-to-debug partial failures.

### 2) Chain/protocol support is config-driven but not fully schema-governed

Config validation exists but is permissive and prints warnings. As registries grow, you want hard validation with CI fail-fast behavior.

### 3) Token identity is still symbol/address-centric in several places

As more wrappers and bridged assets are added, symbol collisions and chain-specific aliases become operational risk.

### 4) Pricing resiliency needs stronger policy enforcement

There are useful fallbacks (Chainlink/Pyth/Kraken/CoinGecko), but production NAV usually benefits from explicit freshness/staleness rules and source quorum/priority controls per category.

### 5) End-to-end run is monolithic

`collect.py` currently orchestrates all phases in one flow. This is simple, but can become expensive when retries/re-runs are needed for one subsystem (e.g., one chain RPC outage).

## Recommended improvements (low-change first)

## Phase 1 (1-2 weeks): harden reliability with minimal architecture change

1. **Provider profiles in `chains.json`**
   - Add per-provider limits: `max_qps`, `burst`, `timeout_ms`, `max_retries`, `backoff`.
   - Update `concurrent_query` caller sites to use chain-specific worker budgets instead of global `max_workers=len(chains)` patterns.

2. **Strict config validation mode**
   - Add `--strict-config` (default on in CI) to raise on invalid config instead of warning.
   - Add JSON Schema or Pydantic validation for `chains.json`, `tokens.json`, `contracts.json`, `wallets.json`, `solana_protocols.json`.

3. **Pricing freshness gates**
   - Per category/token define `max_price_age_seconds` and reject stale oracle reads.
   - Persist `price_timestamp_utc` and `price_age_seconds` for every priced position.

4. **Fix uncovered dispatcher edge cases early**
   - Ensure all price-dispatch fallback paths are safe when optional fields are missing.

## Phase 2 (2-4 weeks): improve agnosticism and onboarding speed

1. **Introduce `asset_id` canonical identity**
   - Suggested format: `namespace:chain:address_or_mint` (e.g., `evm:base:0x...`, `solana:mainnet:...`).
   - Keep symbol as display-only metadata.

2. **Protocol plugin contract**
   - Define a small handler interface (`discover_positions`, `query_balances`, optional `decompose`).
   - Map `_query_type` to plugin modules via registry, but require each plugin to declare supported chains and required config fields.

3. **Declarative pricing policy table**
   - Move fallback order and stale thresholds to config (not implicit code paths).
   - Example: `pricing_policy[category=A2] = [chainlink@30m, pyth@15m, coingecko@5m]`.

4. **Position schema versioning**
   - Add `schema_version` to output files to decouple downstream Excel ingestion from internal representation changes.

## Phase 3 (4-8 weeks): scale operating model

1. **Stage the pipeline**
   - `extract` -> `normalize` -> `value` -> `publish` with persisted intermediate artifacts.
   - Re-run one failed stage without recomputing all upstream chain calls.

2. **Add change-data-capture / incremental mode**
   - On non-valuation days, query only positions likely changed (event/log driven where possible).
   - Keep full snapshot mode for official valuation date.

3. **Observability**
   - Emit per-chain/per-provider metrics: latency, success rate, stale price count, fallback usage, critical path duration.
   - Add structured logs with run_id and correlation IDs.

## Concrete examples of “low-change extensibility” you can target

- New ERC-4626 strategy on existing chain: config-only if ABI/query type already covered.
- New EVM chain with existing protocol patterns: chain profile + token registry + contract sections, no valuation logic edits.
- New token with known pricing source: add token entry + pricing config, no handler edits.

To keep that promise reliable at scale, the missing pieces are mostly validation, identity normalization, and provider-aware execution controls.

## Suggested success metrics

- **Lead time to onboard new position** (PR open to first successful run).
- **Percent config-only onboardings** (no Python code changes).
- **Run success rate** and **median run duration** on valuation date.
- **Fallback pricing rate** by category (should be explainable and bounded).
- **Stale price incidents** (target: zero on official NAV runs).

## Immediate next steps

1. Add strict config schema validation in CI.
2. Add provider budgets to `chains.json` and wire them into concurrency choices.
3. Add `asset_id` to output rows while preserving current fields for compatibility.
4. Add freshness metadata to pricing outputs and block NAV finalization on stale-critical assets.

These four steps will materially improve optimisation, scalability, and chain/token agnosticism without a major rewrite.
