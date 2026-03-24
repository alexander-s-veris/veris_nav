# Veris Capital AMC — NAV Data Collection System

## Project Overview

This project builds a Python-based data collection system for the Veris Capital AMC (ISIN: LI1536896288), an open-ended Actively Managed Certificate issued by 10C PCC / 10C Cell 11 PC. The system collects on-chain positions, oracle prices, and market data to produce a canonical NAV snapshot file that feeds into the NAV workbook (Excel).

**Product**: USD-denominated stablecoin yield fund deployed across DeFi protocols on Ethereum, Arbitrum, Base, Avalanche, Plasma, Solana, and HyperEVM.

**Parties**: Bank Frick AG (Calculation Agent / Paying Agent / Custodian), ZEUS Anstalt (Investment Manager), Vistra (Administrator), ForDefi (on-chain custodian), Kraken (additional custodian), Grant Thornton (Auditor).

**Valuation frequency**: Monthly (last calendar day), with Valuation Time 16:00 CET (= 15:00 UTC year-round, no daylight saving adjustment).

**First NAV date**: 30 April 2026.

---

## What This Script Must Produce

A timestamped snapshot file (CSV and/or JSON) containing every position balance and every price, with metadata about the data source, block number, and timestamp. The Excel NAV workbook consumes this file. Bank Frick must be able to read the script and verify that it queries the correct contracts.

Output format per row:
```
timestamp_utc, chain, protocol, wallet, position_type, token, balance_raw, balance_human, price_source, price_usd, value_usd, block_number, tx_or_query_ref, category, notes
```

---

## Wallet Addresses

| Chain | Wallet | Description |
|-------|--------|-------------|
| Solana | ASQ4kYjSYGUYbbYtsaLhUeJS6RtrN4Uwp4XbF4gDifvr | Main Solana wallet |
| Ethereum | 0xa33e1f748754d2d624638ab335100d92fcbe62a2 | Open Market Positions |
| Ethereum | 0x6691005cd97656d488b72594c42cae987264e0e7 | Open Market Positions 2 |
| Ethereum | 0x0c1644d7af63df4a3b15423dbe04a1927c00a4f4 | Credit Positions |
| Ethereum | 0xec0b3a9321a5a0a0492bbe20c4d9cd908b10e21a | Credit Positions 2 |
| Ethereum | 0xaca2ef22f720ae3f622b9ce3065848c4333687ae | Multi-chain wallet |
| Ethereum | 0x80559941c1a741bc435cb6782b6f161d5772ac4b | Multi-chain wallet |

All EVM wallets are also used on Arbitrum, Base, Avalanche, Plasma, and HyperEVM as applicable.

---

## Asset Classification Framework

Every position falls into one of these categories. The category determines the valuation methodology.

| Category | Description | Primary Valuation Source |
|----------|-------------|------------------------|
| **A1** | On-chain yield-bearing tokens (deterministic smart contract exchange rate) | Smart contract query (e.g. convertToAssets, exchangeRate) |
| **A2** | Off-chain yield-bearing tokens (oracle/issuer NAV) | Oracle feed or issuer-published NAV |
| **A3** | Private credit vault tokens (manual accrual on contractual terms) | Principal + accrued interest from loan agreements |
| **B** | PT tokens (zero-coupon bond, linear amortisation to maturity) | Linear amortisation per individual lot |
| **C** | LP positions (AMM pool decomposition) | Decompose into constituent tokens, price each per its category |
| **D** | Leveraged positions (looping) | Net = Collateral value − Debt value |
| **E** | Stablecoins & cash | Par value (USDC-pegged) or oracle price (non-USDC-pegged) |
| **F** | Other / bespoke (governance tokens, dust, YT, rewards) | CoinGecko or DEX TWAP; de minimis (<$100) valued at zero |

---

## Price Feed Hierarchy (per Valuation Policy)

For each token, try sources in this order:

1. **Chainlink on-chain Data Feed** (free contract call via `latestRoundData()`)
2. **Pyth Network** (free REST API via Hermes: `hermes.pyth.network/v2/updates/price/latest`)
3. **Issuer oracle or on-chain exchange rate** (e.g. Midas mF-ONE oracle, ERC-4626 convertToAssets)
4. **CoinGecko API** (aggregated market price)
5. **DEX TWAP** (last resort)

The script must log which source was used for each token.

### Known Chainlink Feeds (free on-chain Data Feeds)

| Token | Feed Type | Contract / ENS | Chain |
|-------|-----------|---------------|-------|
| USCC NAV per share | NAVLink (SmartData) | `uscc-nav.data.eth` / `0xAfFd...00d9` | Ethereum |
| USDT/USD | Price Feed | `0x3E7d1eAB13ad0104d2750B8863b489D65364e32D` | Ethereum |
| USDC/USD | Price Feed | `0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6` | Ethereum |
| DAI/USD | Price Feed | `0xAed0c38402a5d19df6E4c03F4E2DceD6e29c1ee9` | Ethereum |
| mF-ONE/USD | Chainlink-style oracle (Midas) | `0x8D51DBC85cEef637c97D02bdaAbb5E274850e68C` | Ethereum |

Note: USX/USD, SyrupUSDC/USDC, eUSX/USX, RLP/USD etc. appear on Chainlink but are **Data Streams** (paid), NOT free Data Feeds. Do not attempt to query these via contract call.

### Pyth Hermes API

Free REST endpoint, no API key needed:
```
GET https://hermes.pyth.network/v2/updates/price/latest?ids[]=<price_feed_id>
```
Check https://docs.pyth.network/price-feeds/price-feeds for available feed IDs.

### CoinGecko API

Free tier, no API key needed for basic queries:
```
GET https://api.coingecko.com/api/v3/simple/price?ids=<coin_id>&vs_currencies=usd
```
The NAV spreadsheet already uses CoinGecko via a helper table `tbl_Helper_CoinIds` with these mappings:
- usd-coin → USDC
- usdt0 → USDT0
- resolv-wstusr → wstUSR
- superstate-uscc → USCC
- ripple-usd → RLUSD
- giza → GIZA
- resolv-rlp → RLP
- And ~20 more

---

## Key Contract Addresses

| Chain | Protocol | Contract | Address |
|-------|----------|----------|---------|
| Ethereum | Midas | mF-ONE Token | 0x238a700eD6165261Cf8b2e544ba797BC11e466Ba |
| Ethereum | Midas | mF-ONE/USD Oracle | 0x8D51DBC85cEef637c97D02bdaAbb5E274850e68C |
| Ethereum | Morpho | Morpho Core | 0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb |
| Ethereum | Credit Coop | Veris Credit Vault | 0xb21eAFB126cEf15CB99fe2D23989b58e40097919 |
| Ethereum | Gauntlet | Levered FalconX Vault | 0x00000000d8f3d6c5DFeB2D2b5ED2276095f3aF44 |
| Ethereum | Gauntlet | Levered FalconX Provisioner | 0x21994912f1D286995c4d4961303cBB8E44939944 |
| Ethereum | Gauntlet | FalconX Price Fee Calculator | 0x8F3FfA11CD5915f0E869192663b905504A2Ef4a5 |
| Ethereum | Pareto | Tranche Price Contract | 0x433d5b175148da32ffe1e1a37a939e1b7e79be4d |
| Ethereum | Pareto | FalconX Tranche | 0xC26A6Fa2C37b38E549a4a1807543801Db684f99C |
| Ethereum | Fluid | Vault (syrupUSDC/USDC) | 0xbc345229c1b52e4c30530c614bb487323ba38da5 |
| Solana | Exponent | Program ID | ExponentnaRg3CQbW6dqQNZKXp7gtZ9DGMp1cwC4HAS7 |

---

## Current Portfolio Positions (as of March 2026)

### A2 Positions (Off-chain yield-bearing)
- **USCC (Superstate Crypto Carry Fund)**: ~738K USCC as collateral on Kamino Solstice (Solana), ~177K USCC on Aave Horizon (Ethereum). NAV ~$11.51/share. **Use Chainlink NAVLink feed as primary.**
- **mF-ONE (Midas Fasanara)**: ~3.85M tokens in wallet 0xa33e. Oracle price ~$1.067. **Use Midas Chainlink-style oracle.**
- **syrupUSDC (Maple)**: Large positions across Morpho loops (Ethereum, Arbitrum). CG price ~$1.12.
- **ONyc (OnRe reinsurance)**: On Solana (Exponent LPs + standalone). Weekly NAV updates.
- **mHYPER (Midas Hyperithm)**: Small positions.

### A3 Positions (Private credit)
- **FalconX / Pareto**: Gauntlet vault exposure. Manual accrual at ~9.62%. On-chain tranche price (1.067961) used as cross-reference only.
- **Credit Coop / Rain**: ~$3.85M in Veris Credit Vault. 13.99% rate + 5% incentive.

### B Positions (PT tokens)
- **PT-USX (Exponent, Solana)**: 7 tranches totaling 1,802,168 PT-USX, maturity 01-Jun-2026. Individual lot tracking with linear amortisation.
- **PT-eUSX (Exponent, Solana)**: 77,840 tokens in Kamino Solstice.
- **PT-ONyc-13MAY26 (Exponent, Solana)**: In LP position.

### C Positions (LP)
- **Exponent ONyc-13MAY26 LP**: 1,063,938 ONyc + 709,406 PT-ONyc. PT priced using Exponent formula: `underlying_price × EXP(-last_ln_implied_rate × days/365.25)`.
- **Exponent eUSX-01JUN26 LP**: 195,927 eUSX + 41,422 PT-eUSX.

### D Positions (Leveraged / Looping)
- **Kamino USCC/USDC Solstice**: 737,994 USCC collateral, -6,790,572 USDC debt (largest position)
- **Morpho syrupUSDC/USDT (Arbitrum)**: 10.46M syrupUSDC collateral, -9.85M USDT0 debt
- **Morpho syrupUSDC/PYUSD**: 778,640 syrupUSDC, -724,736 PYUSD debt
- **Morpho syrupUSDC/AUSD**: 483,000 syrupUSDC, -450,479 AUSD debt
- **Morpho syrupUSDC/RLUSD**: 267,000 syrupUSDC, -250,166 RLUSD debt
- **Aave Horizon USCC/RLUSD**: 176,845 USCC collateral, -1,622,969 RLUSD debt
- **Aave Plasma sUSDe/USDe**: Small position

### E Positions (Stablecoins & Cash)
- **Hyperliquid**: ~$1M USDC
- **Various wallet dust**: USDC, USDT, USDG across wallets
- USDC-pegged stablecoins (USDC, USDS, DAI, PYUSD, USX) valued at par within ±0.5%
- Non-USDC-pegged (USDT, USDG) valued at oracle price

### F Positions (Other)
- **MORPHO, PENDLE, ARB, KMNO**: Governance token rewards across wallets
- **GIZA**: 223,251 tokens on Base
- **RLP (Resolv)**: 204,746 tokens
- **YT-ONyc-13MAY26**: ~725,568 tokens
- Dust threshold: <$100 valued at zero

---

## Solana-Specific Notes

- Solana positions cannot be queried via simple RPC calls like EVM. Use:
  - **Kamino REST API** (`api.kamino.finance`) for Kamino Solstice obligations
  - **Anchorpy + Solana RPC** for Exponent Finance (Program ID: ExponentnaRg3CQbW6dqQNZKXp7gtZ9DGMp1cwC4HAS7). MarketFinancials account stores `last_ln_implied_rate` at byte offset 396.
- Exponent PT formula: `PT_price = underlying_price × EXP(-last_ln_implied_rate × days/365.25)`
- Exponent YT formula: `YT_price = underlying_price × (1 - PT_ratio)`

---

## EVM On-Chain Queries

### Common Patterns
- **ERC-4626 vaults** (Morpho, Euler, Ethena sUSDe, Upshift, Lagoon, CreditCoop): `convertToAssets(shares)` returns underlying value
- **Morpho position**: Query `position(marketId, wallet)` on Morpho core contract → returns `(supplyShares, borrowShares, collateral)`
- **Chainlink oracle**: `latestRoundData()` on aggregator contract → returns `(roundId, answer, startedAt, updatedAt, answeredInRound)` + `decimals()` for scaling
- **Fluid**: Uses NFT positions (not fungible shares). Query by NFT ID.
- **Aave**: `getUserAccountData(wallet)` for aggregate, or per-reserve queries.

### ABI for Chainlink AggregatorV3Interface
```json
[
  {"inputs":[],"name":"latestRoundData","outputs":[
    {"name":"roundId","type":"uint80"},
    {"name":"answer","type":"int256"},
    {"name":"startedAt","type":"uint256"},
    {"name":"updatedAt","type":"uint256"},
    {"name":"answeredInRound","type":"uint80"}
  ],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"description","outputs":[{"name":"","type":"string"}],"stateMutability":"view","type":"function"}
]
```

---

## RPC Endpoints Needed

- **Ethereum**: Alchemy or Infura (user has Alchemy)
- **Arbitrum**: Alchemy
- **Base**: Alchemy
- **Avalanche**: Public RPC or Alchemy
- **Plasma**: Etherscan V2 API (chain ID 9745, native token: XPL, explorer: plasmascan.to). Alchemy not available for Plasma.
- **Solana**: Alchemy (`solana-mainnet.g.alchemy.com/v2/API_KEY`)

Store API keys in a `.env` file (never commit to GitHub).

---

## Project Structure

```
veris-nav/
├── CLAUDE.md                  # This file — project context
├── .env                       # API keys (gitignored)
├── .gitignore                 # Ignore .env, __pycache__, outputs
├── requirements.txt           # Python dependencies
├── src/
│   ├── collect.py             # Main entry point — orchestrates collection
│   ├── evm.py                 # EVM chain queries (web3.py)
│   ├── solana_client.py       # Solana queries (Kamino API + anchorpy)
│   ├── pricing.py             # Price feed hierarchy (Chainlink → Pyth → CG)
│   ├── valuation.py           # Category-specific valuation logic
│   └── output.py              # Writes snapshot CSV/JSON
├── config/
│   ├── wallets.json           # Wallet addresses per chain
│   ├── contracts.json         # Contract addresses and ABIs
│   ├── price_feeds.json       # Token → price source mapping
│   └── pt_lots.json           # PT token individual lot details
├── outputs/
│   └── snapshot_YYYYMMDD_HHMM.csv
└── README.md                  # Setup and usage instructions
```

---

## Development Guidelines

- Keep the code readable — Bank Frick will review it
- Log every query: contract address, function called, block number, result
- Use `.env` for all API keys and RPC URLs
- Output timestamps in UTC, formatted as `dd/mm/yyyy hh:mm:ss` (e.g. `23/03/2026 19:21:35`)
- Use `decimal.Decimal` for financial calculations, not float
- Each function should do one thing clearly
- Add comments explaining the "why" for non-obvious logic (e.g. why sUSDe is A1 not A2)
