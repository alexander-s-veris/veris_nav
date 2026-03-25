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
```

## Current Status

**Wallet balance scanner** (`src/collect_balances.py`) is production-ready, covering 7 wallets across 7 EVM chains + Solana. Scans wallet-level token balances (Categories E and F), prices via Chainlink, Pyth, Kraken, and CoinGecko, and outputs to JSON + CSV.

**Protocol position collection** is in progress. The output schema is defined (see `plans/output_schema_plan.md`) and position configs are being registered wallet by wallet:

| Wallet | Description | Positions Registered |
|--------|-------------|---------------------|
| 0xa33e | Open Market Positions | Morpho D (4 markets), Steakhouse A1, Euler A1, Aave Base A1, mHYPER A2, Ethena cooldown, Uniswap V4 LP |
| 0x6691 | Private Deal Positions | msyrupUSDp A2, Aave Plasma A1, Avantis A1, Yearn Katana A1, ARMA proxy, Curve LP |
| 0x0c16 | Credit Positions | Pending |
| 0xeC0B | Credit Positions 2 | Pending |
| 0xaca2 | Open Market Positions 3 | ARMA proxy (Arbitrum) |
| 0x8055 | Open Market Positions 2 | Aave Horizon D, Clearstar A1, mHYPER A2 |
| ASQ4... | Solana Vault 1 | Pending |

## Project Structure

```
src/
  evm.py                  # Shared EVM utilities (cached Web3, block queries)
  solana_client.py         # Solana RPC helpers (balances, eUSX exchange rate)
  pricing.py               # Price adapters (Chainlink, Pyth, Kraken, CoinGecko, par+depeg)
  collect_balances.py      # Production wallet balance scanner (Cat E + F + A1/A2)
  collect.py               # [Planned] Main orchestrator for full NAV collection
  valuation.py             # [Planned] Category-specific valuation logic (A1-D)
  output.py                # [Planned] NAV snapshot and methodology log writer
config/
  chains.json              # Chain configs (RPC URLs, chain IDs, explorers)
  wallets.json             # Wallet addresses per chain + ARMA proxy wallets
  tokens.json              # Token registry (whitelist per chain with pricing config)
  contracts.json           # Protocol contract addresses (Aave, Morpho, Midas, etc.)
  morpho_markets.json      # Morpho market configs (market IDs, collateral/loan tokens)
  pt_lots.json             # PT token individual lot details for linear amortisation
outputs/
  wallet_balances.json     # Latest wallet balance snapshot
  wallet_balances.csv      # Same data in CSV
  nav_YYYYMMDD/            # [Planned] Date-stamped NAV snapshots
plans/
  output_schema_plan.md    # Approved output schema design
docs/
  spreadsheet_analysis.md  # Analysis of existing NAV Excel workbook
```

## Configuration Files

- `config/chains.json` — RPC endpoints per chain (Ethereum, Arbitrum, Base, Avalanche, Plasma, HyperEVM, Katana, Solana)
- `config/wallets.json` — Wallet addresses per chain, plus ARMA smart account proxy addresses
- `config/tokens.json` — Token registry per chain with category (A1-F) and pricing config
- `config/contracts.json` — Protocol contract addresses (Aave pools, Morpho core, Midas oracles, Ethena, Uniswap, etc.)
- `config/morpho_markets.json` — Morpho leveraged position market IDs with collateral/loan token details
- `config/pt_lots.json` — PT token individual lot details for linear amortisation

## Asset Categories

| Category | Description | Pricing Method |
|----------|-------------|---------------|
| A1 | On-chain yield-bearing (ERC-4626 vaults, sUSDe, eUSX) | Smart contract `convertToAssets` |
| A2 | Off-chain yield-bearing (mF-ONE, USCC, syrupUSDC, ONyc) | Oracle (Chainlink/Pyth) or issuer NAV |
| A3 | Private credit (FalconX, CreditCoop, Giza, Resolv) | Manual accrual from contractual terms |
| B | PT tokens (zero-coupon, hold-to-maturity) | Linear amortisation per lot |
| C | LP positions (Curve, Uniswap, Exponent) | Decompose into constituents |
| D | Leveraged positions (Morpho, Aave, Kamino, Fluid) | Net = Collateral - Debt |
| E | Stablecoins and cash | Par ($1.00) or oracle for non-USDC-pegged |
| F | Governance tokens, rewards, other | Kraken/CoinGecko/DEX TWAP |

## Output Format

Each NAV run produces a date-stamped folder in `outputs/nav_YYYYMMDD/` containing:
- `positions.json` / `positions.csv` — One row per position with full audit trail
- `query_log.json` / `query_log.csv` — Every on-chain/API call made during collection
- `nav_summary.json` — Aggregated NAV by category, wallet, and custodian
- Detail CSVs for PT lots, A3 accruals, LP decomposition, and leverage pairs

See `plans/output_schema_plan.md` for the complete schema specification.

## Reference

See `CLAUDE.md` for full project context, valuation methodology, and asset classification framework.

See `docs/` for the Valuation Policy governing how all positions are priced.
