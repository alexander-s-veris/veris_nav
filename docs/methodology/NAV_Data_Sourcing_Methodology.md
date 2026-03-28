# Veris Capital AMC - NAV Data Sourcing Methodology

**ISIN**: LI1536896288<br/>
**Reference**: Valuation Policy v1.0 (effective 1 April 2026)<br/>
**Prepared by**: Investment Manager (ZEUS Anstalt)<br/>
**For review by**: Calculation Agent (Bank Frick AG)

This document describes the data sourcing and processing methodology used to produce the NAV calculation file for each Valuation Date. It is a supplementary document to the calculation file and should be read in conjunction with the Valuation Policy.

## 1. General Principles

1. All on-chain data is queried at the **Valuation Block** - the block on each chain with timestamp closest to but not exceeding 15:00 UTC (16:00 CET) on the Valuation Date.
2. All prices from off-chain sources (oracles, APIs, exchange prices) are obtained at or as close as practicable to the **Valuation Time** (16:00 CET).
3. Financial calculations use `decimal.Decimal` precision throughout. Final NAV per Product rounded to 2 decimal places.
4. Every query is logged with the following fields:
    - contract address
    - function called
    - block number
    - raw result
    - timestamp
5. The script produces two output files consumed by the NAV workbook:
    - A JSON output with a `_methodology` header block and a `positions` array
    - A CSV with per-position detail

## 2. Data Retrieval Infrastructure

| Chain | RPC Provider | Balance Query Method |
|-------|-------------|---------------------|
| Ethereum | Alchemy | `alchemy_getTokenBalances` + `balanceOf` fallback |
| Arbitrum | Alchemy | `alchemy_getTokenBalances` + `balanceOf` fallback |
| Base | Alchemy | `alchemy_getTokenBalances` + `balanceOf` fallback |
| Avalanche | Alchemy | `alchemy_getTokenBalances` + `balanceOf` fallback |
| HyperEVM | Alchemy | `alchemy_getTokenBalances` + `balanceOf` fallback |
| Plasma | Etherscan V2 API | `account/balance` + `account/addresstokenbalance` |
| Solana | Alchemy | `getTokenAccountsByOwner` (SPL) + `getBalance` (native) |

**EVM balanceOf fallback**: Alchemy's token indexer may not cover all tokens. For any token registered in the token registry but not returned by Alchemy, a direct ERC-20 `balanceOf` contract call is made to ensure complete coverage.

**Token registry**: Only tokens pre-registered in `config/tokens.json` are included in the output. Unregistered tokens (spam, airdrops, unsolicited deposits) are excluded. The registry defines the category, decimals, and pricing configuration for each token on each chain.

## 3. Pricing Methodology by Category

### 3.1 Category A1: On-Chain Yield-Bearing Tokens (Section 6.1)

**Methodology**: Query the protocol's smart contract at the Valuation Block to obtain the token's exchange rate relative to the underlying asset. Multiply by the token balance to derive value in the underlying stablecoin, then price the underlying per Category E.

**Data source**: Direct RPC call to the protocol's smart contract.

| Token | Chain | Exchange Rate Method | Underlying | Pricing |
|-------|-------|---------------------|------------|---------|
| eUSX | Solana | Total USX in vault / total eUSX supply | USX | Pyth |
| sUSDe | Ethereum, Plasma | `convertToAssets()` on sUSDe contract | USDe | Category E |
| Credit Coop Vault | Ethereum | `convertToAssets()` on vault (ERC-4626/7540) | USDC | Par |
| Morpho vault shares (bbqSUDCreservoir, steakUSDT, CSUSDC) | Ethereum, Base | `convertToAssets()` on vault contract | USDC/USDT | Category E |
| Euler vault shares (esyrupUSDC) | Arbitrum | `convertToAssets()` on vault (sub-account XOR) | syrupUSDC | Category A2 |
| Avantis (avUSDC) | Base | `convertToAssets()` on vault contract | USDC | Category E |
| Aave aTokens (supply-only) | Base, Plasma | `balanceOf()` on aToken (auto-accruing) | Various | Per underlying |
| Yearn V3 (yvvbUSDC) | Katana | `convertToAssets()` on vault contract | USDC | Category E |

**eUSX exchange rate detail**: The eUSX vault account (USX token account owned by eUSX mint authority) holds the total USX backing. The rate is calculated as:

`total_usx_in_vault / total_eusx_supply`

**Includes**: Accrued but unclaimed lending/supply interest. Protocol incentive rewards excluded (captured under Category F).

### 3.2 Category A2: Off-Chain Yield-Bearing Tokens (Section 6.2)

**Methodology**: Obtain the token price from the highest-priority available source in the oracle hierarchy. Cross-reference where both oracle and issuer NAV exist.

**Source hierarchy** (in order of priority):

1. On-chain oracle:
    - (a) Chainlink
    - (b) Pyth Network
    - (c) Redstone
2. Issuer-published NAV or price feed
3. Secondary market price (DEX TWAP - last resort)

| Token | Primary Source | Feed Reference | Fallback |
|-------|---------------|----------------|----------|
| USCC | Pyth | Pyth price feed | CoinGecko (`superstate-uscc`) |
| mF-ONE | Chainlink (Midas oracle) | `0x8D51DBC8...e68C` | Issuer PDF report |
| msyrupUSDp | Chainlink (Midas oracle) | `0x337d914f...5241` | Issuer report |
| ONyc | Pyth | Pyth price feed | Issuer weekly NAV |
| syrupUSDC | Pyth | Pyth price feed | CoinGecko (`syrup-usdc`) |
| RLP | Pyth | Pyth price feed | CoinGecko (`resolv-rlp`) |
| mHYPER | Chainlink (Midas oracle) | `0xfC3E47c4...e1A0` (Plasma) | Issuer report |

**Staleness check**: Price is flagged if not updated for more than 2x the expected update interval. If primary source is stale, the next available source is used with a note in the output.

### 3.3 Category A3: Private Credit Vault Tokens (Section 6.3)

**Methodology**: Manual accrual - principal + accrued interest from contractual terms. No automated price feed.

**Data sources**:

1. Principal balance: read from on-chain vault smart contract at Valuation Block
2. Interest rate: from current loan agreement or term sheet (provided by Investment Manager)
3. Accrual calculation: `principal x rate x (days_in_period / 365)`

| Position | Rate Source | Cross-reference |
|----------|-----------|----------------|
| FalconX / Pareto (Gauntlet + Direct) | Loan notice (8.325% net = 9.25% gross x 0.90) | On-chain tranche price |

Note: Credit Coop / Rain was **reclassified from A3 to A1** - see Section 3.1. Its `convertToAssets` is authoritative.

**Rate resets**: If the rate changes between Valuation Dates, accrued interest is weighted by days at each rate.

**On-chain tranche price** (e.g. Pareto `tranchePrice`) is used as a retrospective cross-reference only, NOT as the primary valuation source.

### 3.4 Category B: PT Tokens (Section 6.4)

**Methodology**: Linear amortisation from purchase price to par at maturity. Each purchase lot tracked individually.

**Formula**:

`PT value = Underlying Value / (1 + Implied Rate at Purchase x (Days to Maturity / 365))`

**Data sources**:

1. Underlying value: priced per applicable category (A1, A2, or E)
2. Implied rate at purchase: from trade log maintained by Investment Manager
3. Days to maturity: calculated from Valuation Date to maturity date

| Token | Protocol | Chain | Maturity |
|-------|----------|-------|----------|
| PT-USX | Exponent | Solana | 01-Jun-2026 |
| PT-eUSX | Exponent | Solana | 01-Jun-2026 |
| PT-ONyc | Exponent | Solana | 13-May-2026 |

**Scope**: Linear amortisation applies only to PTs held directly or as collateral. PTs inside LP positions are priced using the protocol's AMM implied rate (see Category C).

**AMM cross-reference**: The protocol's AMM-implied price may be obtained as informational cross-reference but does not replace linear amortisation.

### 3.5 Category C: LP Positions (Section 6.5)

**Methodology**: Decompose the LP position into its constituent token balances at the Valuation Block, then price each constituent per its own category.

**Data source**: Query pool smart contract for reserves, total LP supply, and Product's LP balance to derive pro-rata share.

**Yield-splitting protocol LPs** (Exponent, Pendle):

1. PT component: priced using protocol's current implied rate at Valuation Block (NOT linear amortisation)
2. Exponent formula:
    `PT Price = Underlying Price x EXP(-last_ln_implied_rate x Days to Maturity / 365)`
    Note: The Valuation Policy text references 365.25. However, the Exponent on-chain smart contract uses exactly 365 days (31,536,000 seconds). We match the on-chain calculation to ensure independently reproducible results.
3. SY component: priced per underlying token's category (A1 or A2)

| LP Position | Constituents | PT Pricing |
|-------------|-------------|-----------|
| Exponent ONyc-13MAY26 LP | ONyc + PT-ONyc | Exponent implied rate |
| Exponent eUSX-01JUN26 LP | eUSX + PT-eUSX | Exponent implied rate |

**YT tokens** encountered in LP positions: priced per Category F methodology.

**Includes**: Accrued but unclaimed trading fees. Protocol incentive rewards excluded (Category F).

### 3.6 Category D: Leveraged Positions (Section 6.6)

**Methodology**: Decompose into collateral and debt components, value each independently, and net.

**Formula**:

`Net Position Value = Value of Collateral - Value of Debt Outstanding`

**Data sources**:

1. Collateral balance: read from lending protocol smart contract at Valuation Block (inclusive of accrued supply interest)
2. Debt balance: read from lending protocol smart contract at Valuation Block (inclusive of accrued borrow interest)

| Position | Protocol | Chain | Collateral | Debt |
|----------|----------|-------|-----------|------|
| USCC/USDC | Kamino (Superstate Opening Bell) | Solana | USCC (A2) | USDC (E) |
| PT-USX+PT-eUSX/USX | Kamino (Solstice) | Solana | PT-USX + PT-eUSX (B) | USX (E) |
| syrupUSDC/USDT0 | Morpho | Arbitrum | syrupUSDC (A2) | USDT0 (E) |
| syrupUSDC/AUSD | Morpho | Ethereum | syrupUSDC (A2) | AUSD (E) |
| syrupUSDC/RLUSD | Morpho | Ethereum | syrupUSDC (A2) | RLUSD (E) |
| USCC/RLUSD | Aave Horizon | Ethereum | USCC (A2) | RLUSD (E) |
| sUSDe/USDe | Aave V3 | Plasma | sUSDe (A1) | USDe (E) |

### 3.7 Category E: Stablecoins and Cash (Section 6.7)

**Methodology**:

1. **USDC-pegged** (USDC, USDS, DAI, PYUSD): Valued at par ($1.00). Chainlink oracle on Ethereum queried for de-peg check.
2. **Non-USDC-pegged** (USDT, USX, USDG, USDD, AUSD, RLUSD): Valued at oracle price per source hierarchy:
    - Chainlink
    - Pyth
    - CoinGecko
3. **Fiat at Bank Frick**: Face value in USD. Non-USD converted at ECB reference rate.

**De-peg check** (Section 9.4):

1. Deviation 0.5% or less: price at par, no flag
2. Deviation 0.5-2% (minor): price at actual oracle value, noted in report
3. Deviation over 2% (material): price at actual oracle value, investor notification required within 2 business days

| Token | Method | Chainlink Feed | Pyth Feed |
|-------|--------|---------------|-----------|
| USDC | Par + de-peg | `0x8fFfFfd4...818f6` | - |
| DAI | Par + de-peg | `0xAed0c384...1ee9` | - |
| PYUSD | Par | - | - |
| USDT | Chainlink | `0x3E7d1eAB...e32D` | - |
| USDD | Pyth | - | `0x6d2021...52a6` |
| USX | Pyth | - | `0x85d11b...926b` |

### 3.8 Category F: Other / Bespoke (Section 6.8)

**Methodology**: Best available price source per the following hierarchy.

**Governance tokens** - source hierarchy:

1. Kraken reported price (if listed - Kraken is an approved custodian and reference source per Final Terms)
2. CoinGecko aggregated price (Pro API)
3. DEX TWAP (last resort)

| Token | Source | Kraken Pair | CoinGecko ID |
|-------|--------|-------------|-------------|
| ETH | Kraken | ETHUSD | ethereum |
| MORPHO | Kraken | MORPHOUSD | morpho |
| PENDLE | Kraken | PENDLEUSD | pendle |
| ARB | Kraken | ARBUSD | arbitrum |
| SOL | Kraken | SOLUSD | solana |
| AVAX | Kraken | AVAXUSD | avalanche-2 |
| XPL / WXPL | Kraken | XPLUSD | plasma |
| HYPE | Kraken | HYPEUSD | hyperliquid |
| GIZA | CoinGecko | - | giza |
| DAM | CoinGecko | - | reservoir |

**YT Tokens**:

`YT Price = Underlying Price x (1 - PT Price Ratio)`

Near-expiry illiquid YTs may be marked to zero.

**Airdrop claims / protocol points**: Valued at zero until token is confirmed, claimable, and has liquid markets.

**Unregistered tokens**: Tokens not in the token registry (spam, airdrops, unsolicited deposits) are excluded from the snapshot entirely.

## 4. Kraken-Held Assets (Special Rule)

Assets held at Kraken are priced using **Kraken's reported market price** regardless of their category classification. The category-specific methodology described above does NOT apply to Kraken-held assets. When assets transfer between Kraken and other custodians, the applicable methodology changes upon settlement.

## 5. Verification

Per Section 7 of the Valuation Policy:

1. Aggregate on-chain portfolio valuation is cross-referenced against at least one approved Verification Source:
    - **DeBank** (EVM only)
    - **Octav** (paid subscription, broader coverage)
2. Divergence exceeding the tolerance thresholds in Appendix B triggers investigation before NAV is finalised.
3. Kraken-held assets verified against Kraken's publicly available market data.
4. Bank Frick fiat balances verified against custody records.
5. **Fallback source**: ForDefi portfolio valuation engine (used only when Primary + Verification sources are unavailable).

## 6. Output Format

Each NAV calculation produces two files:

1. **JSON file** with:
    - `_methodology` header block (run parameters, pricing rules applied, chains and wallets queried)
    - `positions` array with per-position detail
2. **CSV file** with one row per position containing the following fields:
    ```
    wallet, chain, token_contract, token_symbol,
    token_name, category, balance, price_usd,
    price_source, value_usd, depeg_flag, notes,
    block_number, block_timestamp_utc, run_timestamp_cet
    ```

Every row includes the `price_source` field documenting which source was used (par, chainlink, pyth, kraken, coingecko, a1_exchange_rate), satisfying the Section 12.1 requirement that the NAV Report identifies the data source for each position.
