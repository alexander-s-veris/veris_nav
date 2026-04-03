# Valuation Methodology by Category

Per Valuation Policy v1.0. Pricing is **category-driven, not a single waterfall**. The category determines the methodology; individual tokens within a category may use different specific sources. The script must log which source was used for each token.

**Layered methodology**: Reading a position's balance and pricing that position may use different categories. For example, a leveraged position (D) reads collateral balance via a smart contract call (A1-style query), but the collateral token itself (e.g. syrupUSDC) is priced via Category A2.

---

## A1: On-Chain Yield-Bearing Tokens
- **Source**: Smart contract query at the Valuation Block (e.g. ERC-4626 `convertToAssets`, protocol-specific exchange rate functions)
- **Result**: Exchange rate × token balance = value in underlying stablecoin
- **Then**: Price the underlying stablecoin per Category E
- **Includes**: Accrued but unclaimed lending/supply interest. Governance rewards excluded (→ Category F)
- **Examples**: sUSDe (Ethena), Morpho vault shares, Euler vaults, Upshift vaults, Credit Coop/Rain vault (reclassified from A3 — on-chain exchange rate is authoritative despite underlying private credit)

## A2: Off-Chain Yield-Bearing Tokens
- **Source hierarchy** (use highest-priority available):
  1. On-chain oracle feed: (a) Chainlink, (b) Pyth, (c) Redstone, (d) other reputable oracles
  2. Issuer-published NAV or price feed (fund admin NAV, issuer API)
  3. Secondary market price (DefiLlama aggregated — last resort)
- **Cross-reference**: Where both oracle and issuer NAV exist, cross-reference. Investigate if divergence exceeds tolerance (Appendix B of policy)
- **Staleness**: Flag if not updated for >2× the expected update interval. If primary is stale, use next available source and note in NAV report
- **Examples**: USCC (Chainlink NAVLink), mF-ONE (Midas oracle), syrupUSDC (Pyth), ONyc (Pyth + OnRe issuer NAV), RLP (Resolv AggregatorV3Interface)

### A2 Expected Update Frequencies
The Investment Manager must maintain a record of the expected update frequency for each A2 token (based on issuer's published schedule or observed historical cadence). This is needed for the staleness check — flag if >2× expected interval.

## A3: Private Credit Vault Tokens
- **Source**: Manual accrual — principal + accrued interest from contractual terms
- **No price feed** — depends on loan agreements provided by Investment Manager
- **On-chain tranche price** (e.g. Pareto `convertToAssets`) used as cross-reference only, NOT as primary
- **Impairment**: If credit event occurs, mark to estimated recovery value (may be zero)
- **Examples**: FalconX/Pareto vault (Gauntlet gpAAFalconX and direct AA_FalconXUSDC)

### A3 Rate Resets
If the contractual interest rate changes between Valuation Dates (e.g. monthly rate reset), the accrued interest calculation must reflect the applicable rate for each sub-period, weighted by the number of days at each rate.

## B: PT Tokens (hold-to-maturity)
- **Formula**: `PT value = Underlying Value / (1 + Implied Rate at Purchase × (Days to Maturity / 365))`
- **Individual lot tracking**: Each purchase tracked separately with its own implied rate from the trade log
- **Underlying value**: Priced per its applicable category (A1, A2, or E)
- **No mark-to-market**: AMM price used as cross-reference only, does not replace linear amortisation
- **Scope**: Applies to PTs held directly or as collateral. PTs inside LP positions use AMM implied rate instead (see Category C)
- **Examples**: PT-USX, PT-eUSX, PT-ONyc (all Exponent/Solana)

## C: LP Positions
- **Source**: Decompose LP into constituent tokens at the Valuation Block, price each per its own category
- **Yield-splitting LPs** (Pendle, Exponent): PT component priced using protocol's current implied rate (NOT linear amortisation), SY component priced per A1/A2
- **Exponent PT-in-LP formula**: `PT Price = Underlying Price × EXP(-last_ln_implied_rate × Days to Maturity / 365)` (Note: Valuation Policy text says 365.25 but Exponent on-chain uses exactly 365 days / 31,536,000 seconds. We match on-chain to ensure reproducibility.)
- **Includes**: Accrued but unclaimed trading fees. Governance rewards excluded (→ Category F)
- **YT tokens** encountered in LPs: Priced per Category F methodology
- **Examples**: Exponent ONyc-13MAY26 LP, Exponent eUSX-01JUN26 LP

### Concentrated Liquidity (Uniswap V3 style)
For concentrated liquidity LP positions: value reflects actual token amounts within the position's active range at the Valuation Block, NOT full-range notional. If price is outside the position's range, the position holds only one token and is valued at that single-token exposure.

## D: Leveraged Positions (Looping)
- **Formula**: `Net Position Value = Value of Collateral − Value of Debt Outstanding`
- **Collateral**: Balance read from lending protocol (inclusive of accrued supply interest), then priced per collateral token's own category (A1/A2/A3/B/E)
- **Debt**: Balance read from lending protocol (inclusive of accrued borrow interest), priced per Category E
- **Examples**: Kamino USCC/USDC, Morpho syrupUSDC/USDT0, Aave Horizon USCC/RLUSD

## E: Stablecoins & Cash
- **USDC-pegged** (USDC, USDS, DAI, PYUSD): Valued at **par ($1.00)** if within ±0.5% of peg
- **Non-USDC-pegged** (USDT, USX, USDG, others): Valued at oracle price using A2 oracle hierarchy (Chainlink → Pyth → Redstone)
- **Fiat at Bank Frick**: Face value in USD. Non-USD converted at ECB reference rate
- **De-peg rules**:
  - Minor (0.5–2%): Price at actual traded value (CEX price or DefiLlama aggregated), note in NAV report
  - Material (>2%): Price at actual traded value, notify investors within 2 business days
  - For debt in leveraged positions: de-pegged stablecoin debt valued at de-pegged price (may result in net gain)

## F: Other / Bespoke
- **YT Tokens**: `YT Price = Underlying Price × (1 − PT Price Ratio)`. Near-expiry illiquid YTs may be marked to zero
- **Governance tokens** (MORPHO, ARB, PENDLE, KMNO, etc.) — source hierarchy:
  1. **Kraken reported price** (if listed — Kraken is an approved custodian and reference source)
  2. **CoinGecko** (volume-weighted aggregated price)
  3. **DefiLlama aggregated price** (last resort)
- **Airdrop claims / protocol points**: Valued at zero until token is confirmed, claimable, and has liquid markets
- **Unregistered tokens**: Tokens not in the token registry (spam, airdrops, unsolicited deposits) are excluded from the snapshot. All whitelisted tokens with balance >$0 are included regardless of value.

---

## Cross-Cutting Rules

### Kraken-Held Assets (special rule)
Assets held at Kraken are priced using **Kraken's reported market price** regardless of their category classification. The category-specific methodology does NOT apply to Kraken-held assets. When assets transfer between Kraken and other custodians, the applicable methodology changes upon settlement.

### Accrued Interest & Rewards Rules
- **A1 positions**: Include accrued but unclaimed lending/supply interest in valuation. Protocol incentive rewards (governance tokens) are excluded and captured under Category F
- **C positions (LP)**: Include accrued but unclaimed trading fees. Protocol incentive rewards excluded (→ F)
- **D positions**: Collateral balance inclusive of accrued supply interest. Debt balance inclusive of accrued borrow interest
- **F unclaimed rewards**: Only include if claimable at the Valuation Block (can execute claim tx without further conditions). Vested, locked, or future-unlock rewards valued at zero
- **F airdrops/points**: Zero until token is confirmed, has a contract address, is claimable, AND has liquid markets

### Verification Requirements
- **Asset-level (Section 7.3)**: Tokens with verification sources in `config/verification.json` are cross-checked automatically. Verifiers derive an independent per-token price (e.g. Midas attestation total NAV / totalSupply) and compare against the primary oracle price. Divergence exceeding category thresholds (`pricing_policy.json` → `divergence_tolerances`) is flagged. Results in `verification.csv`.
- **Portfolio-level (Section 7.1)**: Aggregate portfolio valuation must be cross-referenced against at least one independent DeFi portfolio aggregator: **DeBank** (EVM only) or **Octav** (paid subscription, broader coverage)
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
| Protocol AMMs (Pendle, Exponent, Curve) | B cross-reference, F YT pricing |
| DefiLlama (aggregated DEX + CEX) | Last-resort fallback for A2, E, F tokens |
| Verification Sources (DeBank, Octav) | Portfolio-level cross-referencing (Section 7.1) |
| Verification Sources (Attestation, Issuer NAV) | Asset-level cross-referencing (Section 7.3), config in `verification.json` |
| Fallback Source (ForDefi) | When Primary + Verification unavailable (Section 8) |
| ECB Reference Rates | E fiat currency conversion |
| Contractual Documentation | A3 (primary) |
