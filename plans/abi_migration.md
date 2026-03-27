# ABI Migration Plan

## Status: Partially done

`protocol_queries.py` loads all ABIs from `config/abis.json` via `_get_abi()`. No inline ABIs in the new production modules. Remaining: `collect_balances.py` and `evm.py` still have inline ABIs (working, low priority to migrate).

## Problem

ABIs are currently duplicated across multiple scripts:
- `src/evm.py` — Chainlink AggregatorV3 ABI
- `src/temp/query_positions.py` — Morpho, ERC-4626, ERC-20, Pareto, CreditCoop ABIs
- `src/collect_balances.py` — ERC-20 ABI

The canonical source is now `config/abis.json`, but existing scripts haven't been migrated yet.

## What to do

When building the final `src/collect.py` orchestrator:

1. Import all ABIs from `config/abis.json` — write a helper function in `src/evm.py`:
   ```python
   def load_abi(abi_type: str) -> list:
       """Load ABI from config/abis.json by type key."""
   ```

2. Remove inline ABI definitions from `src/evm.py` and `src/collect_balances.py`

3. The temp scripts in `src/temp/` don't need migration — they'll be deleted once the final schema is built

## ABIs available in config/abis.json

- `erc20` — balanceOf, totalSupply, decimals, name, symbol
- `erc4626` — ERC-20 + convertToAssets, totalAssets, asset
- `morpho_core` — position, market
- `chainlink_aggregator_v3` — latestRoundData, decimals, description
- `aave_pool` — getUserAccountData
- `pareto_credit_vault` — tranchePrice, getApr, getContractValue, epoch info, defaulted
- `ethena_cooldown` — cooldowns(address)
- `credit_coop_vault` — balanceOf, convertToAssets
