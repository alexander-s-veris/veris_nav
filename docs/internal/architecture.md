# System Architecture

This document defines the architectural principles and patterns of the NAV collection system. All new code must follow these conventions.

---

## Core Principles

1. **Config-driven, not code-driven.** Adding a new position, chain, token, or protocol should require only config changes (JSON files in `config/`), not code changes. Code implements patterns; config declares instances.

2. **No hardcoded values.** Contract addresses, wallet addresses, token symbols, RPC URLs, API endpoints, oracle feed IDs, chain IDs, program IDs, and native token metadata all live in config files. Code reads from config. The only acceptable "hardcoded" values are structural constants (e.g. Anchor discriminator byte patterns, ERC-4626 function signatures) that define protocol mechanics rather than deployment specifics.

3. **Single source of truth.** Each piece of data is defined in exactly one place:
   - Chain metadata (RPC URLs, chain IDs, native token, block times, Etherscan base URL) --> `config/chains.json`
   - Wallet addresses and protocol registrations --> `config/wallets.json`
   - Token registry (symbols, decimals, categories, pricing config) --> `config/tokens.json`
   - Protocol contracts and query types --> `config/contracts.json`
   - Morpho market IDs --> `config/morpho_markets.json`
   - Solana protocol accounts --> `config/solana_protocols.json`
   - Price feed definitions --> `config/price_feeds.json`
   - Pricing hierarchy rules --> `config/pricing_policy.json`
   - Verification sources --> `config/verification.json`
   - PT lot details --> `config/pt_lots.json`
   - ABIs --> `config/abis.json`
   - Shared constants (timestamp format, CET timezone) --> `src/evm.py`

4. **Category-driven valuation.** Every position is classified into a category (A1-F). The category determines the valuation methodology. `valuation.py` dispatches to category-specific functions. Pricing routes through `pricing.py` which reads the hierarchy from `pricing_policy.json`.

5. **Separation of concerns.** Each module owns one responsibility:
   - `collect.py` -- orchestration (what to query, in what order, output)
   - `collect_balances.py` -- balance scanning functions (how to read token balances per chain)
   - `protocol_queries.py` -- protocol dispatch (which handler to call for each wallet/chain combo)
   - `handlers/*.py` -- protocol-specific position reading (how to read each protocol)
   - `valuation.py` -- pricing and valuation (how to price each category)
   - `pricing.py` + `adapters/*.py` -- price feed adapters (how to query each oracle/API)
   - `verifiers/*.py` -- independent verification (how to cross-check prices per Section 7)
   - `output.py` -- snapshot writing (how to format and write results)

6. **Library modules, not standalone scripts.** Core modules (`collect_balances.py`, `protocol_queries.py`, `valuation.py`, `pricing.py`) are libraries imported by `collect.py`. They do not have standalone `main()` functions. Only `collect.py` is an entry point.

---

## Handler Registry Pattern

### EVM (protocol_queries.py)

The system uses a two-level dispatch:

1. `wallets.json` declares which protocols each wallet uses on each chain (e.g. `"morpho": true`)
2. `PROTOCOL_TO_HANDLER` maps protocol keys to handler keys
3. `HANDLER_REGISTRY` maps handler keys to handler functions imported from `handlers/`
4. The orchestrator reads the wallet's protocols, looks up the handler, and calls it

**EVM handlers** (in `HANDLER_REGISTRY`):
- `erc4626` -- generic ERC-4626 vault (balanceOf + convertToAssets)
- `morpho_leverage` -- Morpho markets via morpho_markets.json
- `aave_leverage` -- Aave aToken + debt token pairs
- `euler_erc4626` -- ERC-4626 with sub-account scan
- `midas_oracle` -- ERC-20 balance + oracle price
- `manual_accrual_gauntlet` / `manual_accrual_direct` -- FalconX workbook
- `credit_coop` -- ERC-4626 + sub-strategy breakdown
- `ethena_cooldown` -- sUSDe pending unstakes
- `nft_lp` -- Uniswap V4 NFT position

### Solana (protocol_queries.py)

Same pattern via `SOLANA_HANDLER_REGISTRY`:

- `kamino` -- Kamino obligations (getAccountInfo + binary deserialization)
- `exponent` -- Exponent LP positions + YT positions
- `pt_lots` -- PT lot-based linear amortisation from config

Both registries read wallet protocol registrations from `wallets.json`. Adding a new protocol = add handler function + registry entry + config.

---

## Balance Scanning (collect_balances.py)

Balance scanners are per-chain-method functions. The method is declared in `chains.json` per chain (`token_balance_method`):

| Method | Function | Used by |
|--------|----------|---------|
| `alchemy` (default) | `query_balances_alchemy()` | Ethereum, Arbitrum, Base, Avalanche, HyperEVM |
| `etherscan_v2` | `query_balances_etherscan()` | Plasma (Alchemy not available) |
| `balance_of` | (no-op, handled by protocol queries) | Katana |
| (Solana) | `query_balances_solana()` | Solana |

All scanners return standardised row dicts via `_build_row()`. All read token metadata from the registry (`tokens.json`), not from on-chain metadata calls. Native token decimals come from `chains.json`.

ARMA smart account proxies are scanned as regular wallets with a `parent_wallet` annotation -- no special handler needed.

---

## Valuation Block Pinning

When run with `--date YYYY-MM-DD`, collect.py pins all queries to 15:00 UTC on that date:
- EVM: `find_valuation_block()` in evm.py finds the block closest to but not exceeding the target timestamp
- Solana: `find_valuation_slot()` in solana_client.py binary-searches for the correct slot
- All balance queries and protocol queries receive the pinned block/slot
- Without `--date`, queries run at latest block (for development/testing)

---

## Pricing Architecture (Three-File Separation)

Pricing configuration is split into three files, each owning one concern:

1. **`config/price_feeds.json`** -- Registry of all available feeds (Chainlink, Pyth, Redstone, Kraken, CoinGecko). Each feed defined once with type and connection details. ~58 entries.
2. **`config/pricing_policy.json`** -- Per-category hierarchy rules encoding Valuation Policy Section 6. Fallback order, staleness multiplier, depeg thresholds, divergence tolerances.
3. **`config/tokens.json`** -- Tokens reference feeds by key (`pricing.feeds`) and declare their policy (`pricing.policy`). No embedded feed IDs.

`pricing.py` uses a generic hierarchy walker (`_price_with_hierarchy`) that reads the fallback order from `pricing_policy.json` and resolves feeds from `price_feeds.json`. Individual adapters in `src/adapters/` implement each feed type.

`valuation.py` routes all pricing through `pricing.get_price()` -- including par-priced stablecoins, which must pass through the depeg check (Policy Section 9.4). Price results carry `depeg_flag`, `depeg_deviation_pct`, `stale_flag`, and `staleness_hours` which are propagated to every position dict via `_apply_price_result()`.

**Chain-agnostic pricing rule**: The same token on different chains must have identical pricing config (same feeds, same hierarchy). Oracles are cross-chain — a Chainlink feed on Ethereum prices USDT on all chains. When adding a token that already exists on another chain, copy the pricing config from the existing entry. The only acceptable difference is a chain-specific DEX TWAP fallback (last resort, only where a liquid pool exists). The price cache is keyed by `(symbol, policy, first_feed)`, ensuring one price per symbol regardless of chain.

---

## Verification Architecture (Section 7)

Independent verification is a separate concern from pricing. While adapters provide primary prices (Section 6), verifiers cross-check those prices against independent sources (Section 7).

**Config**: `config/verification.json` maps token symbols to verification sources with source-specific parameters (API proof IDs, token addresses, etc.). API base URLs live in the `_api_endpoints` section. Divergence thresholds come from `pricing_policy.json` `divergence_tolerances`.

**Verifier registry** (`src/verifiers/__init__.py`): Maps verification type names to verifier functions. `run_asset_verifications()` matches each valued position against verification config and dispatches to the matching verifier.

**Verifier interface**: Each verifier module exports a `verify(config, primary_price, api_base)` function returning a result dict with `verified_price_usd`, `divergence_pct`, `source`, and `details`.

**Current verifiers**:
- `midas_attestation` -- Queries LlamaRisk API for attested total fund NAV, divides by on-chain totalSupply() to derive per-token price. Covers mHYPER.
- `midas_pdf_report` -- Downloads issuer PDF reports from Google Drive (via service account), OCRs the image-based PDF (Tesseract), parses Total assets / Issued tokens to derive per-token price. Covers msyrupUSDp and mF-ONE. Reports saved locally for audit trail. Staleness flagged if report date exceeds configured max age.
- `superstate_nav_api` -- Queries Superstate REST API (`/v1/funds/{id}/nav-daily`) for the latest daily NAV per share. Covers USCC. No auth required.
- `onre_onchain_nav` -- Reads ONyc NAV from OnRe Offer PDA on Solana. Computes price from APR-based discrete step vectors. Config in `solana_protocols.json`.

**Flow**: Runs after valuation (Step 4.5 in collect.py). Results written to `verification.csv` and included in `nav_summary.json`.

---

## Collect.py Pipeline

```
Step 1+2 (concurrent):
  Step 1: Balance scanning (all chains + Solana + ARMA proxies)
  Step 2: Protocol positions (EVM handler dispatch + Solana handler dispatch)

Step 3: Deduplication
  Protocol positions override wallet token balances for the same (chain, wallet, contract)

Step 4: Valuation
  ALL positions (wallet balances + protocol) go through value_position()
  Category dispatch: A1/A2/A3/B/C/D/E/F each have dedicated valuation functions

Step 4.5: Independent Verification (Section 7.3)
  Asset-level cross-checks: verifiers compare primary oracle prices against
  independent sources (issuer attestations, NAV reports). Results written to
  verification.csv and included in nav_summary.json.

Step 5: Output
  positions.csv/json, leverage_detail.csv, pt_lots.csv, lp_decomposition.csv,
  verification.csv, nav_summary.json

Step 6: Summary
  Chain health report, category breakdown, total assets/debt/net
```

---

## RPC Optimization (Multicall3 + Concurrency)

The system minimizes RPC calls and wall-clock time through three strategies:

### Multicall3 Batching (`src/multicall.py`)

Multicall3 aggregates multiple `eth_call` operations into a single RPC call via the standard `aggregate3()` contract (deployed at `0xcA11bde05977b3631167028862bE2a173976CA11` on all major EVM chains). The address is configured per chain in `chains.json` under the `multicall3` key.

Used in:
- **Balance fallback** (`collect_balances.py`): Registry tokens not found by Alchemy's `alchemy_getTokenBalances` are batch-queried via one multicall per wallet per chain instead of sequential `balanceOf` calls.
- **Chainlink price pre-fetch** (`pricing.py`): All Chainlink feeds are batch-queried per chain (2 sub-calls per feed: `decimals()` + `latestRoundData()`) before individual pricing runs.

Fallback: Chains without `multicall3` in config gracefully degrade to individual `eth_call` per item.

### Concurrent Execution

| Level | Where | Parallelism |
|-------|-------|-------------|
| Steps 1+2 | `collect.py` | Balance scanning + protocol queries run as 2 concurrent threads |
| Chains (Step 1) | `collect.py` | All EVM chains scanned in parallel via `concurrent_query()` |
| Wallets (Step 2) | `collect.py` | All wallets on each chain queried in parallel |
| Handlers | `protocol_queries.py` | Protocol handlers for a single wallet-chain pair run concurrently |
| Pricing | `pricing.py` | CoinGecko batch, Chainlink batch, then remaining tokens via `concurrent_query()` |

### Block Refinement

- **EVM** (`block_utils.py:refine_block`): Binary search with 30s tolerance, ~12 iterations max. Converges in O(log n) instead of linear adjustment.
- **Solana** (`solana_client.py:find_valuation_slot`): Binary search over 20K slot range, 12 iterations, 3 offset tries per iteration for skipped slots.

### Euler Sub-Account Scan

Euler V2 uses XOR-based sub-accounts. The scan range is limited to sub-accounts 0–31 (covers all known positions) instead of 0–255 to reduce worst-case RPC calls from 256 to 32 per vault.

---

## Robustness Features

- **Config validation**: `_validate_config()` checks required fields in contracts.json, morpho_markets.json, and solana_protocols.json before making RPC calls. Called lazily on first query.
- **Price cache**: Keyed by `(symbol, method, feed)` not just symbol -- prevents cross-chain cache collisions for same-named tokens with different pricing configs.
- **Handler retry**: All protocol handlers (EVM and Solana) retry once with 2s backoff on failure, preventing transient RPC timeouts from causing material position gaps.
- **Depeg propagation**: Every price result carries depeg fields that are propagated to the position dict, ensuring the NAV report documents de-peg status per Policy Section 9.4 / 12.1.
- **Staleness checking**: A2 tokens have `expected_update_freq_hours` in tokens.json. Prices older than 2x the expected frequency are flagged and fall through to the next source in the hierarchy.
- **Fallback warnings**: If a price lookup fails and a $1.00 fallback is used (for PT underlying or LP constituents), a WARNING note is added to the position so it's visible in the output.
- **Output schema versioning**: `SCHEMA_VERSION` in positions.json and nav_summary.json for downstream consumer compatibility detection.
- **Compliance tests**: 46 automated tests validate config against the Valuation Policy v1.0.

---

## Adding New Components

| Adding... | Config files | Code changes |
|-----------|-------------|--------------|
| New EVM chain | `chains.json` (chain entry with RPC, chain_id, native token) | None |
| New wallet | `wallets.json` (address + protocol registrations) | None |
| New token | `tokens.json` (symbol, decimals, category, pricing config) | None |
| New ERC-4626 vault | `contracts.json` + `tokens.json` | None |
| New Morpho market | `morpho_markets.json` | None |
| New Aave position | `contracts.json` (aToken + debt token entries) | None |
| New Midas token | `contracts.json` (token + oracle entry) | None |
| New Kamino obligation | `solana_protocols.json` | None |
| New Exponent market | `solana_protocols.json` | None |
| New PT lot | `pt_lots.json` | None |
| New price feed | `price_feeds.json` + `tokens.json` (reference the feed) | None |
| New pricing tier | `pricing_policy.json` (add to hierarchy) | None |
| New verification source | `verification.json` (entry for token) | None |
| New verification type | `src/verifiers/new_type.py` + registry in `verifiers/__init__.py` | Verifier function |
| New protocol type | `handlers/new_protocol.py` + registry entry in `protocol_queries.py` | Handler function |
| New price adapter | `src/adapters/new_adapter.py` + import in `pricing.py` | Adapter function |
| New EVM chain with Multicall3 | `chains.json` (add `multicall3` address) | None |
