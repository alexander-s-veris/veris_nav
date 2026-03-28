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

Step 5: Output
  positions.csv/json, leverage_detail.csv, pt_lots.csv, lp_decomposition.csv, nav_summary.json

Step 6: Summary
  Chain health report, category breakdown, total assets/debt/net
```

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
| New protocol type | `handlers/new_protocol.py` + registry entry in `protocol_queries.py` | Handler function |
| New price adapter | `src/adapters/new_adapter.py` + import in `pricing.py` | Adapter function |
