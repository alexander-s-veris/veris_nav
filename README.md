# Veris Capital AMC — NAV Data Collection System

Automated data collection system for the monthly NAV calculation of the Veris Capital AMC (ISIN: LI1536896288), an open-ended Actively Managed Certificate issued by 10C PCC / 10C Cell 11 PC.

Queries on-chain positions, oracle prices, and market data across Ethereum, Arbitrum, Base, Avalanche, Plasma, HyperEVM, Katana, and Solana to produce a canonical NAV snapshot consumed by the Excel NAV workbook.

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env` and add your API keys:
```
ALCHEMY_API_KEY=your_key
ETHERSCAN_API_KEY=your_key
COINGECKO_API_KEY=your_key
KATANA_RPC_URL=https://rpc.katana.network
SOLSCAN_API_KEY=your_key
```

## Usage

### NAV Collection (production)

```bash
# Latest block (development/testing)
python src/collect.py

# Pinned to Valuation Block at 15:00 UTC on a specific date (production)
python src/collect.py --date 2026-03-31

# Enforce strict config validation (recommended in CI)
python src/collect.py --date 2026-03-31 --strict-config
```

When `--date` is provided, all on-chain queries are pinned to the block/slot closest to but not exceeding 15:00 UTC on that date, per the Valuation Policy. Without `--date`, queries run at latest block.

### Snapshot Diff (pre-submission check)

```bash
# Compare the two most recent snapshots
python src/diff_snapshots.py --latest

# Compare specific snapshots
python src/diff_snapshots.py outputs/nav_20260228 outputs/nav_20260331

# Output as JSON
python src/diff_snapshots.py --latest --json
```

Flags: new/disappeared positions, zero-value positions, value changes >10%, price source changes, balance changes >50%. Returns exit code 1 if critical issues found.

### Supporting scripts

```bash
# Wallet balance scanner (standalone quick check, ~45s)
python src/collect_balances.py

# FalconX/Pareto A3 hourly accrual updater (run before collect.py)
python src/temp/update_falconx_optimized.py
```

## Current Status

**Production NAV collection** (`src/collect.py`) is operational. Queries all protocol positions + wallet balances across 7 EVM chains + Solana, values per category methodology, and outputs to `outputs/nav_YYYYMMDD/`. Runs in ~95 seconds. 107 positions, ~$26M net.

**All protocol positions are registered:**

| Wallet | Description | Positions Registered |
|--------|-------------|---------------------|
| 0xa33e | Open Market Positions | Morpho D (3 active, 1 closed), Steakhouse USDC A1, Steakhouse USDT A1, Euler A1, Aave Base A1, mF-ONE A2, mHYPER A2, Ethena cooldown, Uniswap V4 LP |
| 0x6691 | Private Deal Positions | msyrupUSDp A2, Aave Plasma A1, Avantis A1, Yearn Katana A1, ARMA proxy, Curve LP |
| 0x0c16 | Credit Positions | Gauntlet/FalconX A3 (indirect via vault + direct AA_FalconXUSDC), Morpho AA_FalconXUSDC closed |
| 0xeC0B | Credit Positions 2 | CreditCoop A1, Hyperithm A1, Ethena cooldown |
| 0xaca2 | Open Market Positions 3 | ARMA proxy (Arbitrum) |
| 0x8055 | Open Market Positions 2 | Aave Horizon D, Clearstar A1, mHYPER A2 |
| ASQ4... | Solana Vault 1 | Kamino D (2 obligations: USCC/USDC + PT-USX/PT-eUSX/USX), PT-USX B (7 lots), PT-eUSX B (1 lot), Exponent C (2 LPs: ONyc + eUSX), Exponent F (2 YTs: ONyc + eUSX), farming rewards F |

## Architecture

The system uses a **config-driven handler registry** pattern. Adding a new position for a standard protocol pattern requires only config changes, no code:

1. `wallets.json` declares which protocols each wallet uses on each chain
2. `contracts.json` defines protocol contracts with `_query_type` fields
3. `protocol_queries.py` dispatches via `HANDLER_REGISTRY` based on protocol type
4. `solana_protocols.json` configures Solana positions (Kamino, Exponent)
5. `tokens.json` defines pricing config per token (method, feed IDs, fallback sources)
6. `valuation.py` builds pricing indices from config at init — no hardcoded prices or feed IDs

See `protocol_sourcing.md` for the "Adding a New Position" quick reference table.

## Project Structure

```
src/
  collect.py               # Production orchestrator with --date valuation block pinning
  protocol_queries.py      # Config-driven handler registry for protocol position queries
  valuation.py             # Category-specific valuation with config-driven pricing indices
  pricing.py               # Price adapters (Chainlink, Pyth, Kraken, CoinGecko, par+depeg)
  evm.py                   # Shared EVM utilities (cached Web3, find_valuation_block)
  block_utils.py           # Block estimation + concurrent RPC utilities
  solana_client.py         # Solana RPC helpers (balances, eUSX rate, find_valuation_slot)
  pt_valuation.py          # PT token lot-based valuation (Category B linear amortisation)
  collect_balances.py      # Standalone wallet balance scanner (~45s)
  diff_snapshots.py        # Snapshot diff tool — compares NAV snapshots for changes/errors
  output.py                # NAV snapshot writer (positions, leverage detail, PT lots, LP decomposition, summary)
  cache_xlsx.py            # Cache xlsx sheets as CSVs for fast access
  temp/                    # Supporting scripts (production, not temporary)
    update_falconx_optimized.py  # FalconX/Pareto A3 hourly data updater
    query_pareto_tranche_history.py  # Pareto tranche price history
config/
  chains.json              # Chain configs (RPC URLs, chain IDs, explorers)
  wallets.json             # Wallet addresses per chain with protocol registrations
  tokens.json              # Token registry (whitelist per chain with pricing config)
  contracts.json           # Protocol contracts with _query_type for handler dispatch
  solana_protocols.json    # Solana protocol configs (Kamino obligations, Exponent markets)
  abis.json                # Minimal ABIs for all contract interactions
  morpho_markets.json      # Morpho market IDs and position configs
  pt_lots.json             # PT token individual lot details for linear amortisation
protocol_sourcing.md       # Protocol-by-protocol position reading guide
```

## Configuration Files

- `config/chains.json` — RPC endpoints per chain, including `token_balance_method` (default=Alchemy, `etherscan_v2` for Plasma, `balance_of` for Katana)
- `config/wallets.json` — Wallet addresses per chain with per-wallet protocol registrations. Used by the handler dispatch to determine which protocols to query for each wallet.
- `config/tokens.json` — Token registry per chain with category (A1-F) and pricing config (method, feed IDs, fallback sources). Pricing indices are built from this at init.
- `config/contracts.json` — Protocol contracts grouped by chain and protocol, with `_query_type` fields that map to handlers in `HANDLER_REGISTRY`
- `config/solana_protocols.json` — Solana protocol position configs (Kamino obligations with reserve mappings, Exponent markets with SY/PT/YT details)
- `config/abis.json` — Minimal ABIs for all contract interactions (ERC-20, ERC-4626, Morpho, Chainlink, Aave, Pareto, Ethena)
- `config/morpho_markets.json` — Morpho leveraged position market IDs with collateral/loan token details
- `config/pt_lots.json` — PT token individual lot details for linear amortisation

## Asset Categories

| Category | Description | Pricing Method |
|----------|-------------|---------------|
| A1 | On-chain yield-bearing (ERC-4626 vaults, sUSDe, eUSX) | Smart contract `convertToAssets` |
| A2 | Off-chain yield-bearing (mF-ONE, USCC, syrupUSDC, ONyc) | Oracle (Chainlink/Pyth) or issuer NAV |
| A3 | Private credit (FalconX/Pareto) | Manual accrual from contractual terms |
| B | PT tokens (zero-coupon, hold-to-maturity) | Linear amortisation per lot |
| C | LP positions (Curve, Uniswap, Exponent) | Decompose into constituents |
| D | Leveraged positions (Morpho, Aave, Kamino, Fluid) | Net = Collateral - Debt |
| E | Stablecoins and cash | Par ($1.00) for USDC-pegged; oracle for non-USDC-pegged |
| F | Governance tokens, rewards, other | Kraken/CoinGecko/DEX TWAP |

## Output Format

Each NAV run produces a date-stamped folder in `outputs/nav_YYYYMMDD/` containing:
- `positions.json` / `positions.csv` — One row per position with full audit trail
- `nav_summary.json` — Aggregated NAV by category and wallet, with valuation block metadata
- `leverage_detail.csv` — Category D collateral/debt breakdown
- `pt_lots.csv` — Per-lot PT linear amortisation detail
- `lp_decomposition.csv` — Category C LP constituent breakdown
- `diff_report.json` — Snapshot diff (when run via diff_snapshots.py --json)

## Reference

See `CLAUDE.md` for full project context, valuation methodology, and asset classification framework.

See `docs/reference/` for the Valuation Policy and NAV workbook.

See `protocol_sourcing.md` for detailed protocol-by-protocol position reading guide.
