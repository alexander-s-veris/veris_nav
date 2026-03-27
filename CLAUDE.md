# Veris Capital AMC — NAV Data Collection System

## Session Start Checklist

At the start of each new conversation, before working on any tasks, read through all project `.md` files to refresh context:
- `CLAUDE.md` (this file)
- `protocol_sourcing.md` — how to read positions from each protocol
- `README.md`
- `plans/*.md` — current and future plans
- `docs/methodology/*.md` — NAV methodology
- `docs/analysis/*.md` — spreadsheet analysis, token registry
- `.claude/skills/*/SKILL.md` — operational skills (e.g. safe file organization)

Do NOT rely on memory alone — always re-read the docs.

---

## Project Overview

This project builds a Python-based data collection system for the Veris Capital AMC (ISIN: LI1536896288), an open-ended Actively Managed Certificate issued by 10C PCC / 10C Cell 11 PC. The system collects on-chain positions, oracle prices, and market data to produce a canonical NAV snapshot file that feeds into the NAV workbook (Excel).

**Product**: USD-denominated stablecoin yield fund deployed across DeFi protocols on Ethereum, Arbitrum, Base, Avalanche, Plasma, Solana, and HyperEVM. The Basket does NOT hold volatile spot tokens (BTC, ETH, SOL) as directional positions, native staking/LST positions, or speculative exchange-traded tokens. Any derivatives/hedging positions not covered by existing categories are classified under Category F.

**Parties**: Bank Frick AG (Calculation Agent / Paying Agent / Custodian), ZEUS Anstalt (Investment Manager), Vistra (Administrator), ForDefi (on-chain custodian), Kraken (additional custodian), Grant Thornton (Auditor).

**Valuation frequency**: Monthly (last calendar day), with Valuation Time 16:00 CET (= 15:00 UTC year-round, no daylight saving adjustment).

**Valuation Block**: The block on each blockchain with timestamp closest to but NOT exceeding 15:00 UTC on the Valuation Date. All on-chain queries must be made at this block, not "latest".

**First NAV date**: 30 April 2026.

**NAV Report deadline**: Within 7 business days of the Valuation Date.

---

## What This Script Must Produce

Two outputs that together form the basis of the NAV Report submitted to the Calculation Agent (Bank Frick). The Calculation Agent must be able to reconstruct every number independently using the data provided.

### 1. NAV Snapshot File (CSV and/or JSON)

Consumed by the Excel NAV workbook. One row per position.

Output format per row:
```
timestamp_utc, chain, protocol, wallet, position_type, token, balance_raw, balance_human, price_source, price_usd, value_usd, block_number, tx_or_query_ref, category, notes
```

### 2. NAV Methodology Log

A structured report documenting the full data sourcing and processing flow, per the Valuation Policy (Section 12.1). This is what the Calculation Agent reviews to verify the NAV was determined correctly. Must include:

**Step 1 — Valuation Block & Time**
- The specific block number used on each chain as the reference point
- Block timestamps confirming they are at or near 15:00 UTC on the Valuation Date
- For off-chain sources (oracles, issuer APIs, Kraken): the timestamp of the data point used

**Step 2 — Position Inventory**
- Complete list of all positions across all custodians (ForDefi, Kraken, Bank Frick)
- Each position classified by asset category (A1–F) per Section 5 of the Valuation Policy
- Wallet address, chain, protocol, token, and raw balance for each position

**Step 3 — Position Valuation (per position)**
For each position, document:
- Category and methodology reference (e.g. "Category A2, Section 6.2, source tier 1: Chainlink oracle")
- Data source used: contract address, oracle address, API endpoint, or manual input
- Query details: block number, function called, raw result returned
- Price or exchange rate obtained, with source update timestamp
- Staleness check for A2 tokens: was the source updated within the expected interval? Flag if >2× expected update cycle
- Calculation: balance × price = USD value
- Cross-references performed and their results (e.g. oracle vs. issuer NAV comparison)

**Step 4 — Verification (per Section 7)**
- Total on-chain portfolio value from at least one approved Verification Source (DeBank and/or Octav)
- Percentage divergence between Primary valuation and Verification Source
- List of positions NOT captured by the Verification Source, with confirmation they were valued using Primary methodology
- For Kraken-held assets: Kraken reported prices used
- For Bank Frick fiat balances: balances confirmed against custody records

**Step 5 — Flags & Exceptions**
- Any stale prices (A2 tokens not updated within 2× expected interval)
- Any stablecoin de-peg events (Category E tokens deviating beyond ±0.5% of par)
- Any Special Valuation Provisions triggered (per Section 9: protocol failure, liquidation, PT default, de-peg, impairment, market disruption)
- Any positions where judgement was exercised or an alternative/fallback source was used, with written rationale

**Step 6 — Proposed Total Assets**
- Aggregate value of all positions across all custodians, pre-fee deduction
- The Calculation Agent then applies fees per the fee schedule and determines final NAV per Product

### NAV Formula (per Section 10 of Valuation Policy)

```
NAV = (Total Assets − Total Fees) ÷ Total Outstanding Products
```

**Total Assets**: Aggregate value of all positions across all custodians (ForDefi, Kraken, Bank Frick), inclusive of accrued but unclaimed interest, lending income, and trading fees.

**Fee Schedule** (accrued and deducted by the Calculation Agent):
- Management Fee: 0.15% p.a. of aggregate Basket value (pro-rated between Valuation Dates)
- Administration Fee: USD 10,000 p.a. (pro-rated daily)
- Service Fee: 0.15% p.a., minimum USD 15,000 (pro-rated between Valuation Dates)
- Performance Fee: 0%, with High Watermark (calculated and accrued monthly)
- Extra NAV fee: USD 500 per additional NAV calculation, if applicable

**Rounding**: NAV per Product rounded to 2 decimal places (USD 0.01). Intermediate calculations at full precision.

### Divergence Tolerance Thresholds (Appendix B of Valuation Policy)

Maximum divergence between Primary and Verification Sources before investigation is required:

| Category | Tolerance | Rationale |
|----------|-----------|-----------|
| A1 | 2% | Deterministic on-chain state; timing/accrual differences |
| A2 | 3% | Oracle update frequency varies; sources may use different pricing |
| A3 | 5% | Manual accrual; verification sources may not capture or may lag |
| B | 6% | Linear amortisation diverges structurally from market pricing near maturity |
| C | 5% | Decomposition methods differ; constituent pricing and fee treatment vary |
| D (net) | 5% | Small differences amplify in net calculation (collateral minus debt) |
| E | 0.5% | Should be at par; exceeding this triggers de-peg provisions |
| F | 10% | Illiquid/complex; verification sources may not capture at all |

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
| **A1** | On-chain yield-bearing tokens (deterministic smart contract exchange rate). Note: sUSDe is A1 because its on-chain exchange rate is authoritative, even though underlying yield is off-chain | Smart contract query (e.g. convertToAssets, exchangeRate) |
| **A2** | Off-chain yield-bearing tokens (oracle/issuer NAV) | Oracle feed or issuer-published NAV |
| **A3** | Private credit vault tokens (manual accrual on contractual terms) | Principal + accrued interest from loan agreements |
| **B** | PT tokens (zero-coupon bond, linear amortisation to maturity) | Linear amortisation per individual lot |
| **C** | LP positions (AMM pool decomposition) | Decompose into constituent tokens, price each per its category |
| **D** | Leveraged positions (looping) | Net = Collateral value − Debt value |
| **E** | Stablecoins & cash | Par value (USDC-pegged) or oracle price (non-USDC-pegged) |
| **F** | Other / bespoke (governance tokens, YT, rewards) | Kraken price → CoinGecko → DEX TWAP |

---

## Valuation Methodology by Category (per Valuation Policy v1.0)

Pricing is **category-driven, not a single waterfall**. The category determines the methodology; individual tokens within a category may use different specific sources. The script must log which source was used for each token.

**Layered methodology**: Reading a position's balance and pricing that position may use different categories. For example, a leveraged position (D) reads collateral balance via a smart contract call (A1-style query), but the collateral token itself (e.g. syrupUSDC) is priced via Category A2.

### A1: On-Chain Yield-Bearing Tokens
- **Source**: Smart contract query at the Valuation Block (e.g. ERC-4626 `convertToAssets`, protocol-specific exchange rate functions)
- **Result**: Exchange rate × token balance = value in underlying stablecoin
- **Then**: Price the underlying stablecoin per Category E
- **Includes**: Accrued but unclaimed lending/supply interest. Governance rewards excluded (→ Category F)
- **Examples**: sUSDe (Ethena), Morpho vault shares, Euler vaults, Upshift vaults, Credit Coop/Rain vault (reclassified from A3 — on-chain exchange rate is authoritative despite underlying private credit)

### A2: Off-Chain Yield-Bearing Tokens
- **Source hierarchy** (use highest-priority available):
  1. On-chain oracle feed: (a) Chainlink, (b) Pyth, (c) Redstone, (d) other reputable oracles
  2. Issuer-published NAV or price feed (fund admin NAV, issuer API)
  3. Secondary market price (DEX TWAP — last resort)
- **Cross-reference**: Where both oracle and issuer NAV exist, cross-reference. Investigate if divergence exceeds tolerance (Appendix B of policy)
- **Staleness**: Flag if not updated for >2× the expected update interval. If primary is stale, use next available source and note in NAV report
- **Examples**: USCC (Chainlink NAVLink), mF-ONE (Midas oracle), syrupUSDC (CoinGecko), BUIDL, ONyc (issuer API)

### A3: Private Credit Vault Tokens
- **Source**: Manual accrual — principal + accrued interest from contractual terms
- **No price feed** — depends on loan agreements provided by Investment Manager
- **On-chain tranche price** (e.g. Pareto `convertToAssets`) used as cross-reference only, NOT as primary
- **Impairment**: If credit event occurs, mark to estimated recovery value (may be zero)
- **Examples**: FalconX/Pareto vault (Gauntlet gpAAFalconX and direct AA_FalconXUSDC)

### B: PT Tokens (hold-to-maturity)
- **Formula**: `PT value = Underlying Value / (1 + Implied Rate at Purchase × (Days to Maturity / 365))`
- **Individual lot tracking**: Each purchase tracked separately with its own implied rate from the trade log
- **Underlying value**: Priced per its applicable category (A1, A2, or E)
- **No mark-to-market**: AMM price used as cross-reference only, does not replace linear amortisation
- **Scope**: Applies to PTs held directly or as collateral. PTs inside LP positions use AMM implied rate instead (see Category C)
- **Examples**: PT-USX, PT-eUSX, PT-ONyc (all Exponent/Solana)

### C: LP Positions
- **Source**: Decompose LP into constituent tokens at the Valuation Block, price each per its own category
- **Yield-splitting LPs** (Pendle, Exponent): PT component priced using protocol's current implied rate (NOT linear amortisation), SY component priced per A1/A2
- **Exponent PT-in-LP formula**: `PT Price = Underlying Price × EXP(-last_ln_implied_rate × Days to Maturity / 365)`
- **Includes**: Accrued but unclaimed trading fees. Governance rewards excluded (→ Category F)
- **YT tokens** encountered in LPs: Priced per Category F methodology
- **Examples**: Exponent ONyc-13MAY26 LP, Exponent eUSX-01JUN26 LP

### D: Leveraged Positions (Looping)
- **Formula**: `Net Position Value = Value of Collateral − Value of Debt Outstanding`
- **Collateral**: Balance read from lending protocol (inclusive of accrued supply interest), then priced per collateral token's own category (A1/A2/A3/B/E)
- **Debt**: Balance read from lending protocol (inclusive of accrued borrow interest), priced per Category E
- **Examples**: Kamino USCC/USDC, Morpho syrupUSDC/USDT, Aave Horizon USCC/RLUSD

### E: Stablecoins & Cash
- **USDC-pegged** (USDC, USDS, DAI, PYUSD): Valued at **par ($1.00)** if within ±0.5% of peg
- **Non-USDC-pegged** (USDT, USX, USDG, others): Valued at oracle price using A2 oracle hierarchy (Chainlink → Pyth → Redstone)
- **Fiat at Bank Frick**: Face value in USD. Non-USD converted at ECB reference rate
- **De-peg rules**:
  - Minor (0.5–2%): Price at actual traded value (CEX price or DEX TWAP), note in NAV report
  - Material (>2%): Price at actual traded value, notify investors within 2 business days
  - For debt in leveraged positions: de-pegged stablecoin debt valued at de-pegged price (may result in net gain)

### F: Other / Bespoke
- **YT Tokens**: `YT Price = Underlying Price × (1 − PT Price Ratio)`. Near-expiry illiquid YTs may be marked to zero
- **Governance tokens** (MORPHO, ARB, PENDLE, KMNO, etc.) — source hierarchy:
  1. **Kraken reported price** (if listed — Kraken is an approved custodian and reference source)
  2. **CoinGecko** (volume-weighted aggregated price)
  3. **DEX TWAP** (last resort)
- **Airdrop claims / protocol points**: Valued at zero until token is confirmed, claimable, and has liquid markets
- **Unregistered tokens**: Tokens not in the token registry (spam, airdrops, unsolicited deposits) are excluded from the snapshot. All whitelisted tokens with balance >$0 are included regardless of value.

### Kraken-Held Assets (special rule)
Assets held at Kraken are priced using **Kraken's reported market price** regardless of their category classification. The category-specific methodology does NOT apply to Kraken-held assets. When assets transfer between Kraken and other custodians, the applicable methodology changes upon settlement.

### Accrued Interest & Rewards Rules
- **A1 positions**: Include accrued but unclaimed lending/supply interest in valuation. Protocol incentive rewards (governance tokens) are excluded and captured under Category F
- **C positions (LP)**: Include accrued but unclaimed trading fees. Protocol incentive rewards excluded (→ F)
- **D positions**: Collateral balance inclusive of accrued supply interest. Debt balance inclusive of accrued borrow interest
- **F unclaimed rewards**: Only include if claimable at the Valuation Block (can execute claim tx without further conditions). Vested, locked, or future-unlock rewards valued at zero
- **F airdrops/points**: Zero until token is confirmed, has a contract address, is claimable, AND has liquid markets

### Concentrated Liquidity (Uniswap V3 style)
For concentrated liquidity LP positions: value reflects actual token amounts within the position's active range at the Valuation Block, NOT full-range notional. If price is outside the position's range, the position holds only one token and is valued at that single-token exposure.

### A3 Rate Resets
If the contractual interest rate changes between Valuation Dates (e.g. monthly rate reset), the accrued interest calculation must reflect the applicable rate for each sub-period, weighted by the number of days at each rate.

### A2 Expected Update Frequencies
The Investment Manager must maintain a record of the expected update frequency for each A2 token (based on issuer's published schedule or observed historical cadence). This is needed for the staleness check — flag if >2× expected interval.

### Verification Requirements
- Aggregate portfolio valuation must be cross-referenced against at least one independent DeFi portfolio aggregator: **DeBank** (EVM only) or **Octav** (paid subscription, broader coverage)
- If divergence exceeds tolerance thresholds (Appendix B of policy), investigate before finalising NAV
- **Fallback source**: ForDefi's portfolio valuation engine (used only when Primary + Verification sources fail)
- DeBank/Octav cover on-chain positions only — they do NOT capture Kraken-held assets or Bank Frick fiat balances
- Coverage may be incomplete for newly launched or niche protocols

### Special Valuation Provisions (Section 9 triggers)
The script should detect and flag these conditions automatically where possible:
- **Protocol/technical failure**: Smart contract exploit, hack, oracle manipulation, bridge failure → mark to estimated recovery or zero
- **Leveraged position liquidation**: Read post-liquidation collateral and debt; recognise liquidation penalty as realised loss
- **PT underlying failure**: If underlying asset is impaired, stop linear amortisation → mark to recovery value
- **Stablecoin de-peg**: >0.5% deviation triggers market pricing; >2% triggers investor notification
- **Tokenised fund impairment**: >3% NAV decline in single period, redemption suspension, stale NAV, regulatory action
- **Private credit default**: Borrower default, missed payments, covenant breach → stop accrual, mark to recovery
- **Market disruption event**: Widespread failure → Calculation Agent may postpone Valuation Date

### Record Retention
All NAV Reports, workfiles, and supporting documentation must be retained for minimum 10 years (maintained by Vistra as Administrator). Records must permit independent reconstruction and audit by Grant Thornton.

### Reference Sources by Category (Appendix A of Valuation Policy)

| Source Type | Used For |
|-------------|----------|
| Smart Contract Reads (EVM) | A1 (primary), C (decomposition), D (balance reads), A3 (cross-reference) |
| Smart Contract Reads (Solana) | A1 (primary), B (implied rate reads), C (decomposition), D (balance reads) |
| On-Chain Oracles (Chainlink, Pyth, Redstone) | A2 (primary, tier 1), E non-USDC-pegged stablecoins |
| Issuer-Published NAV / API | A2 (primary, tier 2) |
| Market Data Aggregators (CoinGecko, DefiLlama) | F governance tokens (tier 2) |
| Centralised Exchange Prices (Kraken) | All Kraken-held assets (primary), F governance tokens (tier 1), E de-peg pricing |
| Protocol AMMs (Pendle, Exponent, Curve, DEX TWAP) | B cross-reference, F YT and governance tokens (tier 3) |
| Verification Sources (DeBank, Octav) | Independent cross-referencing (Section 7) |
| Fallback Source (ForDefi) | When Primary + Verification unavailable (Section 8) |
| ECB Reference Rates | E fiat currency conversion |
| Contractual Documentation | A3 (primary) |

### Known Chainlink Feeds (free on-chain Data Feeds)

| Token | Feed Type | Contract / ENS | Chain |
|-------|-----------|---------------|-------|
| USCC NAV per share | NAVLink (SmartData) | `uscc-nav.data.eth` / `0xAfFd...00d9` | Ethereum | *(cross-reference only — SmartData, not standard AggregatorV3. Primary: Pyth)* |
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

### CoinGecko API (Pro plan)

Using Pro API key with `x-cg-pro-api-key` header:
```
GET https://pro-api.coingecko.com/api/v3/simple/price?ids=<coin_id>&vs_currencies=usd
```
Note: Pro plan uses `pro-api.coingecko.com` base URL (not `api.coingecko.com`). Multiple IDs can be batched in one call (comma-separated).
The NAV spreadsheet already uses CoinGecko via a helper table `tbl_Helper_CoinIds` with these mappings:
- usd-coin → USDC
- usdt0 → USDT0
- resolv-wstusr → wstUSR
- superstate-uscc → USCC
- ripple-usd → RLUSD
- giza → GIZA
- resolv-rlp → RLP
- And ~20 more

### Kraken API

Kraken is an approved custodian and reference price source (per Final Terms). Used as:
- **Primary** for all assets held at Kraken (regardless of category)
- **First source** for governance token pricing (Category F)

Public ticker endpoint (no API key needed):
```
GET https://api.kraken.com/0/public/Ticker?pair=<pair>
```

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
| Solana | Kamino Lend | Program ID | KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD |
| Solana | Kamino | Superstate Opening Bell Market | CF32kn7AY8X1bW7ZkGcHc4X9ZWTxqKGCJk6QwrQkDcdw |
| Solana | Kamino | Solstice Market | 9Y7uwXgQ68mGqRtZfuFaP4hc4fxeJ7cE9zTtqTxVhfGU |
| Solana | Kamino | USCC/USDC Obligation | D2rcayJTqmZvqaoViEyamQh2vw9T1KYwjbySQZSz6fsS |
| Solana | Kamino | PT-USX+PT-eUSX/USX Obligation | HMMc5d9sMrGrAY18wE5yYTPpJNk72nrBrgqz5mtE3yrq |
| Solana | Exponent | Program ID | ExponentnaRg3CQbW6dqQNZKXp7gtZ9DGMp1cwC4HAS7 |

---

## Current Portfolio Positions (as of March 2026)

### A2 Positions (Off-chain yield-bearing)
- **USCC (Superstate Crypto Carry Fund)**: ~738K USCC as collateral on Kamino Superstate Opening Bell market (Solana), ~177K USCC on Aave Horizon (Ethereum). NAV ~$11.51/share. **Primary: Pyth feed. Chainlink NAVLink as cross-reference.**
- **mF-ONE (Midas Fasanara)**: ~3.85M tokens in wallet 0xa33e. Oracle price ~$1.067. **Use Midas Chainlink-style oracle.**
- **syrupUSDC (Maple)**: Large positions across Morpho loops (Ethereum, Arbitrum). CG price ~$1.12.
- **ONyc (OnRe reinsurance)**: On Solana (Exponent LPs + standalone). Weekly NAV updates.
- **mHYPER (Midas Hyperithm)**: Small positions.
- **RLP (Resolv)**: 204,746 tokens. Pyth oracle as primary, CoinGecko as fallback.

### A1 Positions — Credit Coop / Rain
- **Credit Coop / Rain**: ~$3.87M in Veris Credit Vault (0xb21e), wallet 0xec0b. **Reclassified A3 → A1** (rationale below). ERC-4626/7540 vault with deterministic `convertToAssets`. Sub-strategies: Rain credit line ($3.75M principal, 14% rate, 10% perf fee) + Gauntlet USDC Core liquid reserve (~$113K). Interest collected periodically from Rain and reinvested into liquid strategy. Sub-strategy breakdown queried for methodology log: `totalActiveCredit()` on CreditStrategy, `totalAssets()` on LiquidStrategy, USDC cash on vault.
- **Hyperithm USDC Apex**: ~1,152 USDC in MetaMorpho vault (`0x7777...`), wallet 0xec0b. Standard ERC-4626 `convertToAssets`.
- **Reclassification rationale (per Valuation Policy Section 6.1)**: The vault's on-chain exchange rate (`convertToAssets`) is authoritative and deterministic — it reflects both collected and uncollected interest from the Rain credit line, plus yield from the Gauntlet USDC Core liquid reserve, net of performance fees. This is analogous to sUSDe (classified A1 even though underlying yield is off-chain). The credit strategy's `getPositionActiveCredit()` provides granular principal/interest breakdown for the methodology log, but `convertToAssets` is the primary valuation source.

### A3 Positions (Private credit)
- **FalconX / Pareto (Gauntlet)**: gpAAFalconX shares (2,507,115). Gauntlet vault holds 55.56M AA_FalconXUSDC as Morpho collateral, borrows ~$30.9M USDC. Veris share ~9.38%. Manual accrual at 8.325% net (Mar 2026: 9.25% gross × 0.90). On-chain TP (1.067961) is cross-reference only.
- **FalconX / Pareto (Direct)**: 1,894,970 AA_FalconXUSDC held directly in wallet 0x0c16 (since Mar 6 2026). Opening value $2,024,989 (actual USDC deposited). Same accrual rate as Gauntlet.

### B Positions (PT tokens)
- **PT-USX (Exponent, Solana)**: 7 tranches totaling 1,802,168 PT-USX, maturity 01-Jun-2026. Individual lot tracking with linear amortisation.
- **PT-eUSX (Exponent, Solana)**: 77,840 tokens as collateral in Kamino Solstice market.
- **PT-ONyc-13MAY26 (Exponent, Solana)**: In LP position.

### C Positions (LP)
- **Exponent ONyc-13MAY26 LP**: 1,063,938 ONyc + 709,406 PT-ONyc. PT priced using Exponent formula: `underlying_price × EXP(-last_ln_implied_rate × days/365)`.
- **Exponent eUSX-01JUN26 LP**: 195,927 eUSX + 41,422 PT-eUSX.

### D Positions (Leveraged / Looping)
- **Kamino USCC/USDC (Superstate Opening Bell market)**: 737,994 USCC collateral, -6,790,572 USDC debt (largest position)
- **Kamino PT-USX+PT-eUSX/USX (Solstice market)**: 1,802,168 PT-USX + 77,840 PT-eUSX collateral (both B, lot-based), USX debt.
- **Morpho syrupUSDC/USDT (Arbitrum)**: 10.46M syrupUSDC collateral, -9.85M USDT0 debt
- **Morpho syrupUSDC/PYUSD**: 778,640 syrupUSDC, -724,736 PYUSD debt
- **Morpho syrupUSDC/AUSD**: 483,000 syrupUSDC, -450,479 AUSD debt
- **Morpho syrupUSDC/RLUSD**: 267,000 syrupUSDC, -250,166 RLUSD debt
- **Aave Horizon USCC/RLUSD**: 176,845 USCC collateral, -1,622,969 RLUSD debt
- **Aave Plasma sUSDe/USDe**: Small position

### E Positions (Stablecoins & Cash)
- **Hyperliquid**: ~$1M USDC
- **Various small balances**: USDC, USDT, USDG across wallets
- USDC-pegged stablecoins (USDC, USDS, DAI, PYUSD) valued at par within ±0.5%
- Non-USDC-pegged (USDT, USX, USDG) valued at oracle price (Pyth/Chainlink)

### F Positions (Other)
- **MORPHO, PENDLE, ARB, KMNO**: Governance token rewards across wallets
- **GIZA**: 223,251 tokens on Base
- **YT-ONyc-13MAY26**: ~725,568 tokens
- **YT-eUSX-01JUN26**: ~141,771 tokens
- **Kamino farming rewards** (Solana): Unclaimed USDG (~6,035) and USX from farming. Included if claimable at Valuation Block. KMNO season rewards excluded.
- All whitelisted tokens with balance >$0 included in valuation

---

## Solana-Specific Notes

- Solana positions cannot be queried via simple RPC calls like EVM. Three sourcing paths:
  - **REST API** (e.g. `api.kamino.finance`) — for discovery and cross-referencing, not for NAV
  - **Direct RPC** (`getAccountInfo` at Valuation Block slot) — authoritative for NAV. Raw token amounts are always accurate; on-chain USD values may be stale
  - **Transaction history** (`getSignaturesForAddress` on token account) — for PT lot discovery and as token identity fallback
- **Transaction history as fallback** (all chains): When contract probing or struct analysis is ambiguous about what a token is, check transaction history (Etherscan `tokentx` on EVM, `getSignaturesForAddress` on Solana). Token flows in swaps and LP withdrawals definitively identify each token. More reliable than guessing from ABI or struct field ordering.

### Kamino Lend (Solana)

**Program ID**: `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD`

Kamino lending markets are isolated markets under the same program. "Solstice", "Superstate Opening Bell", etc. are just different market pubkeys.

**Veris positions:**

| Market | Market Pubkey | Obligation Pubkey | Position |
|--------|--------------|-------------------|----------|
| Superstate Opening Bell | `CF32kn7AY8X1bW7ZkGcHc4X9ZWTxqKGCJk6QwrQkDcdw` | `D2rcayJTqmZvqaoViEyamQh2vw9T1KYwjbySQZSz6fsS` | USCC collateral / USDC debt |
| Solstice | `9Y7uwXgQ68mGqRtZfuFaP4hc4fxeJ7cE9zTtqTxVhfGU` | `HMMc5d9sMrGrAY18wE5yYTPpJNk72nrBrgqz5mtE3yrq` | PT-USX + PT-eUSX collateral / USX debt |

**REST API endpoints:**
- All markets: `GET /v2/kamino-market`
- User obligations: `GET /kamino-market/{market}/users/{user}/obligations`
- Metrics/history (hourly snapshots): `GET /v2/kamino-market/{market}/obligations/{obligation}/metrics/history?start=YYYY-MM-DD&end=YYYY-MM-DD`
- Transactions: `GET /v2/kamino-market/{market}/obligations/{obligation}/transactions`
- No historical slot support in API — for Valuation Block, query on-chain via `getAccountInfo`

**Obligation PDA derivation**: `seeds = [tag(1b), id(1b), user(32b), market(32b), seed1(32b), seed2(32b)]`
- Tag: 0=Vanilla, 1=Multiply, 2=Lending, 3=Leverage
- On-chain amounts: `depositedAmount` (u64, in cTokens), `borrowedAmountSf` (u128, divide by 2^60)

### Exponent Finance (Solana)

- Exponent PT formula: `PT_price = underlying_price × EXP(-last_ln_implied_rate × days/365)`
- Exponent YT formula: `YT_price = underlying_price × (1 - PT_ratio)`

---

## EVM On-Chain Queries

### Common Patterns
- **ERC-4626 vaults** (Morpho, Euler, Ethena sUSDe, Upshift, Lagoon, CreditCoop): `convertToAssets(shares)` returns underlying value
- **Morpho position**: Query `position(marketId, wallet)` on Morpho core contract → returns `(supplyShares, borrowShares, collateral)`
- **Chainlink oracle**: `latestRoundData()` on aggregator contract → returns `(roundId, answer, startedAt, updatedAt, answeredInRound)` + `decimals()` for scaling
- **Fluid**: Uses NFT positions (not fungible shares). Query by NFT ID.
- **Aave**: `getUserAccountData(wallet)` for aggregate, or per-reserve queries.

### Block Estimation & Concurrent RPC (`src/block_utils.py`)
- **`estimate_blocks(ref_block, ref_ts, targets, chain)`**: Pre-compute block numbers from a single reference. Accuracy: ±25 min at 100h distance, ±36s near reference. Eliminates iterative block-finding RPC calls.
- **`refine_block(w3, est_block, target_ts)`**: 5-iteration binary search for exact block. Use only for Valuation Block.
- **`concurrent_query(fn, items, max_workers)`**: ThreadPoolExecutor-based concurrent RPC. Used for parallel chain scanning, wallet scanning, and pricing.
- **`concurrent_query_batched(fn, items, batch_size, max_workers)`**: Same with batching and progress reporting. 10 workers optimal for Alchemy (~22 queries/s, 10.6x faster than serial).
- Chain-specific block times: Ethereum 12s, Arbitrum 0.25s, Base 2s, Avalanche 2s.

### Balance Query Methods
- **Primary (EVM)**: Alchemy `alchemy_getTokenBalances` — returns all ERC-20 balances for a wallet in one RPC call
- **Fallback (EVM)**: Direct `balanceOf` contract call for each registered token. Used when Alchemy hasn't indexed a token (e.g. GIZA on Base)
- **Plasma**: Etherscan V2 API `addresstokenbalance` endpoint (Alchemy not available)
- **Solana**: Alchemy `getTokenAccountsByOwner` — returns all SPL token accounts
- **Solana A1 (eUSX)**: Exchange rate derived from vault state: `total USX in vault / total eUSX supply`. Vault = USX token account owned by eUSX mint authority (`2aHdm37djj4c21ztMRBmmo4my6RtzN5Nn58Y39rpWbRM`)

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
- **HyperEVM**: Alchemy (chain ID 999, native token: HYPE)
- **Solana**: Alchemy (`solana-mainnet.g.alchemy.com/v2/API_KEY`)

Store API keys in a `.env` file (never commit to GitHub).

---

## Project Structure

```
veris-nav/
├── CLAUDE.md                  # This file — project context
├── .env                       # API keys: Alchemy, Etherscan, CoinGecko Pro (gitignored)
├── .gitignore
├── requirements.txt           # Python dependencies
├── src/
│   ├── evm.py                 # Shared EVM utilities (cached Web3, block queries, constants)
│   ├── block_utils.py         # Block estimation + concurrent RPC (Options 1 & 4)
│   ├── solana_client.py       # Solana RPC helpers (balances, eUSX exchange rate)
│   ├── pricing.py             # Price adapters (Chainlink, Pyth, Kraken, CoinGecko Pro, par+depeg)
│   ├── collect_balances.py    # Production wallet balance scanner (Cat E + F + A1/A2 tokens)
│   ├── cache_xlsx.py          # Cache xlsx sheets as CSVs for fast access
│   ├── temp/                  # Temporary query scripts (deleted after final build)
│   ├── collect.py             # Production orchestrator — queries all positions, values, outputs NAV snapshot
│   ├── protocol_queries.py    # Config-driven position queries (Morpho, Aave, Euler, Kamino, Exponent, CreditCoop)
│   ├── valuation.py           # Category-specific valuation logic (A1-F)
│   └── output.py              # NAV snapshot writer (positions.csv/json, leverage_detail, pt_lots, lp_decomposition, nav_summary)
├── config/
│   ├── chains.json            # Chain configs — RPC URLs, chain IDs, explorers
│   ├── wallets.json           # Wallet addresses per chain
│   ├── tokens.json            # Token registry — whitelist per chain with pricing config
│   ├── contracts.json         # Protocol contracts grouped by chain and protocol
│   ├── abis.json              # Minimal ABIs for all contract interactions
│   ├── morpho_markets.json    # Morpho market IDs and position configs
│   └── pt_lots.json           # PT token individual lot details
├── protocol_sourcing.md       # How to read positions from each protocol
├── plans/                     # Implementation plans
├── cache/                     # Cached xlsx sheets as CSVs (gitignored)
├── outputs/                   # Generated snapshots (gitignored)
│   ├── wallet_balances.json   # Latest wallet balance snapshot with methodology header
│   ├── wallet_balances.csv    # Same data in CSV format
│   ├── falconx_position.xlsx  # FalconX/Pareto A3 accrual workbook
│   └── pareto_tranche_price_history.json  # TP update history
├── docs/                      # Valuation Policy and reference documents
└── README.md
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
