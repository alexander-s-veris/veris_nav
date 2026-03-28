# Valuation Policy -- Veris Capital AMC

> **Note:** Markdown transcription of the PDF. Refer to the PDF for the authoritative version.

**ISIN:** LI1536896288

Issued by 10C PCC acting on behalf of 10C Cell 11 PC pursuant to the Structured Products and Certificates Program

| Field | Value |
|-------|-------|
| Document Version | 1.0 |
| Effective Date | 1 April 2026 |
| Approved By | [Calculation Agent / Investment Manager] |
| Review Frequency | Annual, or upon material change |
| Classification | Confidential |

---

## Table of Contents

1. Purpose and Scope
2. Definitions
3. Roles and Responsibilities
4. Fund Profile and Asset Universe
5. Asset Classification Framework
6. Valuation Methodology by Asset Class
7. Independent Verification
8. Fallback Valuation Source
9. Special Valuation Provisions
10. NAV Calculation
11. Valuation Governance and Dispute Resolution
12. Record Keeping and Reporting
13. Policy Review and Amendment
- Appendix A: Reference Sources Guide
- Appendix B: Divergence Tolerance Thresholds
- Appendix C: Version History

---

## 1. Purpose and Scope

This Valuation Policy (the "Policy") sets out the principles, methodologies, and governance framework for the valuation of all assets held within the Basket of the Veris Capital AMC (ISIN: LI1536896288), issued by 10C PCC acting in respect of 10C Cell 11 PC (the "Issuer").

This Policy is referenced in the Final Terms dated 06.03.2026 and forms an integral part of the valuation framework applicable to the Product. It should be read in conjunction with the Base Prospectus dated 19.12.2025 (prolongation of the initial Base Prospectus dated 20.12.2023) and the Final Terms.

The Policy applies to all assets held across all custodians appointed under the Program, including Bank Frick AG (general custodian), ForDefi AG (custodian for on-chain assets), and Payward Ltd. / Kraken (additional custodian). Assets held at Kraken shall be valued using the market prices as reported by Kraken, as specified in the Final Terms. Assets held at ForDefi shall be valued using the methodologies set out in Section 6 of this Policy. Assets held at Bank Frick (including fiat cash balances) shall be valued at face value per Section 6.7.

**Guiding Principles:**

- Every position shall be priced using the most direct and verifiable data source available for that asset type.
- All valuations shall be independently cross-referenced against at least one independent DeFi portfolio aggregation software (e.g. DeBank, Octav).
- Where judgement is exercised, it shall be done in good faith, and the rationale shall be documented in the NAV report.
- The methodology shall be sufficiently flexible to accommodate new asset types without requiring amendment to the Final Terms and shall be amended as the investment strategy evolves.

## 2. Definitions

| Term | Definition |
|------|-----------|
| Authorized Offerors | The financial intermediaries authorized to use the Base Prospectus and Final Terms for the distribution of the Product, as defined in the Final Terms. |
| Base Currency | USD, as specified in the Final Terms. |
| Basket | The actively managed portfolio of assets and cash constituting the Underlying of the Product, as defined in the Final Terms. The assets within the Basket constitute the Collateral for the Product. |
| Collateral | The assets within the Basket that are credited to the Collateral Account pursuant to the Collateral Agreement with the Security Agent, securing the Issuer's payment obligations under the Product. |
| Calculation Agent | Bank Frick AG, in its capacity as Calculation Agent under the Program. |
| DEX TWAP | The time-weighted average price of the token derived from decentralized exchange trading activity over a defined observation period. |
| Divergence Tolerance | The maximum acceptable percentage difference between Primary and Verification Sources before manual review is triggered. See Appendix B. |
| Fallback Source | ForDefi AG's portfolio valuation engine, which aggregates and prices on-chain positions held in the ForDefi custodial wallets. Used only when the Primary Valuation Source (e.g. oracle downtime, smart contract unresponsiveness, RPC failure), and Verification Source for a given asset are unavailable, or when both Primary and Verification Sources produce materially unreliable or conflicting results, or during a Market Disruption Event. See Section 8. |
| Investment Manager | ZEUS Anstalt fuer Vermoegensverwaltung, as appointed under the Final Terms. |
| Looping / Money Market Borrowing | A leveraged yield strategy executed via on-chain money market protocols whereby collateral (which may be a yield-bearing token, PT token, LP token, or stablecoin) is deposited into a lending pool; stablecoins (typically USDC or USDT) are borrowed against it; and the borrowed proceeds are redeployed into additional yield-bearing positions. This cycle may be repeated multiple times to incrementally increase exposure and amplify net yield earned on the original capital. The resulting position is valued on a net basis: Value of Collateral (inclusive of accrued interest) minus Value of Debt Outstanding (inclusive of accrued borrow interest). See Section 6.6. |
| Market Disruption Event | An event that, in the reasonable determination of the Calculation Agent, materially impairs the ability to price one or more assets. See Section 9.7 for full provisions. |
| NAV | The Net Asset Value of the Product, calculated on each Valuation Date as (Total Assets -- Total Fees) / Total Outstanding Products, in accordance with Section 10 and the Final Terms. |
| NAV Report | The report produced by the Investment Manager on each Valuation Date documenting the NAV calculation, sources used, and any discretionary determinations. |
| Off-Chain Yield-Bearing Token | A token whose underlying value is derived wholly or primarily from assets that exist outside the blockchain (e.g. U.S. Treasury bills, money market fund shares, basis trades, traditional credit facilities, or other real-world assets). The token's on-chain balance or exchange rate does not reflect the real-time performance of these off-chain assets; instead, the token's price is published periodically by an authorized oracle, price feed, fund administrator, or off-chain NAV calculation, introducing a dependency on the accuracy and timeliness of this external attestation. Examples include tokenised treasuries, tokenized yield products, institutional lending tokens, and similar instruments. Valued per Section 6.2 (Category A2). |
| On-Chain Yield-Bearing Token | A token whose value accrues over time through a deterministic smart contract mechanism, such as increasing exchange rate, rebasing token balance, or accrued interest counter. The token's current value relative to its underlying asset can be fully and independently derived from on-chain state by querying the protocol's smart contract (e.g. exchange rate functions, share-price lookups, or normalised income reads) without reliance on any off-chain data source or attestation. Examples include receipt tokens from lending protocols (Aave aTokens, Compound cTokens, Morpho vault shares, Fluid fTokens), saving wrappers (e.g. sDAI, sUSDS, sUSDe), and similar instruments. Valued per Section 6.1 (Category A1). |
| Oracle | A data feed mechanism that publishes asset prices on-chain, sourced from off-chain data providers or on-chain computations. Used as the primary pricing source for Category A2 assets. See Section 6.2 for the oracle priority hierarchy. |
| Primary Valuation Source | The most direct data source for a given asset type, as defined in Section 6 for each asset category. The Primary Valuation Source takes precedence over Verification and Fallback Sources unless a Special Valuation Provision under Section 9 applies. |
| Private Credit Vault Token | A token representing a deposit into a structured credit facility or lending arrangement where yield is generated from off-chain or hybrid lending activities (e.g. prime brokerage credit lines, overcollateralised working capital loans). The token's value accrues through a combination of on-chain smart contract state and off-chain interest calculations and may require manual accrual adjustments based on contractually agreed terms. |
| PT Token | A Principal Token issued by a yield-splitting protocol (e.g. Pendle), that separates a yield-bearing asset into a principal component (PT) and a yield component (YT). The PT represents a fixed claim on the principal amount of an underlying yield-bearing asset at maturity, analogous to a zero-coupon bond. It is acquired at a discount to the underlying's current value, with the discount reflecting the implied fixed yield to maturity. The PT converges to par value (1:1 with the underlying) at maturity. |
| SY Token | A Standardised Yield token issued by Pendle or an equivalent yield-splitting protocol, representing a wrapped version of an underlying yield-bearing asset. Used in the decomposition of Pendle LP positions per Section 6.5. |
| Valuation Block | For on-chain assets, the block on the respective blockchain with the timestamp closest to but not exceeding the Valuation Time (15:00 UTC, corresponding to 16:00 CET). CET (UTC+1) applies year-round regardless of daylight-saving adjustments. |
| Valuation Date | The last calendar day of each month, on which the NAV is determined. Where a Market Disruption Event has occurred, the Valuation Date may be postponed in accordance with Section 9.7. |
| Valuation Time | 16:00 CET on the Valuation Date, as specified in the Final Terms. |
| Vault Aggregator Token | A token representing a deposit into a vault that deploys capital across multiple underlying DeFi strategies or protocols. The vault's exchange rate is reported by the aggregator's smart contract and reflects the blended performance of its underlying allocations. |
| Verification Source | An independent DeFi portfolio aggregation software used to cross-reference the aggregate portfolio valuation derived from Primary Valuation Sources (e.g. DeBank, Octav). The Verification Source provides an independent estimate of portfolio value by reading on-chain positions and applying its own pricing methodology. The Calculation Agent may add or remove approved Verification Sources in consultation with the Investment Manager, documented as a Policy amendment. |

## 3. Roles and Responsibilities

### 3.1. Calculation Agent (Bank Frick AG)

- Determines the NAV on each Valuation Date in accordance with this Policy and Section 10.
- Reviews the NAV Report prepared by the Investment Manager, verifies the methodologies applied, and either confirms or adjusts the proposed NAV.
- For assets held at ForDefi, verifies that the Primary Valuation Sources per Section 6 have been correctly applied. For assets held at Kraken, verifies that the market price as reported by Kraken has been used as the Reference Source, as specified in the Final Terms.
- Performs independent verification by cross-referencing the aggregate portfolio valuation against at least one Verification Source, as described in Section 7.
- Verifies that all applicable fees have been correctly deducted in accordance with the fee structure set out in the Final Terms.
- Maintains final authority over the NAV determination and is responsible for its accuracy vis-a-vis investors, the Paying Agent and the Authorized Offerors.

### 3.2. Investment Manager (ZEUS Anstalt)

- Provides the Calculation Agent with a complete position inventory across all custodians at or prior to each Valuation Date. The inventory shall include, at minimum, wallet addresses, position types, token balances, and the custodian at which each position is held.
- Classifies each position per the Asset Classification Framework in Section 5 and applies the appropriate valuation methodology per Section 6.
- For assets held at Kraken, obtains and includes the market price as reported by Kraken at or near the Valuation Time.
- Documents all valuation determinations, source selections, and discretionary judgments in the NAV Report.
- Notifies the Calculation Agent promptly of any material events (protocol exploits, de-pegs, lockups, liquidations, migrations, etc.).
- Retains the right to challenge any NAV determination in accordance with Section 11.
- Proposes updates to this Policy as asset types, custodial arrangements, or market infrastructure evolve.

### 3.3. Administrator (Vistra Fund Services Limited)

- Maintains records of all NAV Reports and valuation documentation and retains such records for a minimum of 10 years in accordance with Section 12.
- Ensures this Policy is made available to the auditor (Grant Thornton AG) upon request.

### 3.4. Paying Agent (Bank Frick AG)

- Processes subscriptions and redemptions based on the NAV as determined by the Calculation Agent.
- Communicates the NAV to investors and Authorized Offerors.
- Notifies investors of material events as required under this Policy, including but not limited to material stablecoin de-pegs (Section 9.4) and fee increases as stipulated in the Final Terms.
- Bank Frick AG's concurrent roles as Paying Agent, Calculation Agent, and general custodian are acknowledged. Conflict of interest mitigation measures are set out in Section 11.3.

## 4. Fund Profile and Asset Universe

The Veris Capital AMC is a USD-denominated, actively managed certificate structured as a debt instrument issued under the Program. The Product's Base Currency is USD, and the Basket is primarily composed of USD-denominated stablecoin positions deployed into on-chain yield strategies across decentralised finance (DeFi) protocols.

The Basket does currently not hold:

- Volatile spot tokens (BTC, ETH, SOL, etc.) as directional positions.
- Native staking positions or liquid staking tokens as standalone holdings.
- Exchange-traded tokens for speculative purposes.

The Product's core strategies include:

- Deploying stablecoins into on-chain lending protocols and yield vaults to earn variable yield in the form of yield-bearing receipt tokens (Category A1) or off-chain-backed yield tokens (Category A2).
- Depositing into structured credit vaults and private lending facilities that provide yield from hybrid on-chain / off-chain credit activities (e.g. prime brokerage lending, overcollateralized working capital financing).
- Purchasing Principal Tokens (PTs) at a discount to the underlying asset, locking in a fixed rate of return upon maturity (Category B).
- Providing liquidity to automated market maker (AMM) pools, typically composed of stablecoins and/or yield-bearing tokens, earning trading fees and protocol incentives (Category C).
- Applying leverage via on-chain money market borrowing (looping) to amplify net yield on collateralised positions (Category D).

The Product may additionally employ derivatives and hedging strategies within the DeFi ecosystem to manage risk or optimise returns, as permitted under the Final Terms.

Consequently, the valuation framework is designed around five core asset categories plus a framework for leveraged overlays, rather than a broad taxonomy of crypto asset types.

Where the Product enters derivative or hedging positions not covered by the existing categories, such positions shall be classified under Category F and valued per Section 6.8 until a specific methodology is established and incorporated into this Policy.

The Product's strategies are highly dynamic in nature. The Investment Manager reserves the right to request the addition of new custodians, service providers, or execution venues (including but not limited to prime brokers and derivatives platforms), and to propose corresponding amendments to this Policy to accommodate pricing methodologies of new classes of assets. Such changes shall be subject to the approval of the Calculation Agent and documented per Section 13.

## 5. Asset Classification Framework

On each Valuation Date, every position in the Basket shall be classified into one of the following categories. Each category has a corresponding valuation methodology defined in Section 6.

| Category | Description | Examples |
|----------|-------------|----------|
| **A1: On-Chain Yield-Bearing Tokens** | Tokens whose value accrues through a deterministic smart contract mechanism. The token's value related to its underlying asset can be fully and independently derived from on-chain state by querying the protocol's smart contract, without reliance on any off-chain data source. Includes vault aggregator tokens where the vault's exchange rate is computed and reported by the aggregator's smart contract. | aTokens (AAVE), steakUSDC/gtUSDC (Morpho vault shares), cTokens (Compound), DAI (MakerDAO), fTokens (Fluid), USDS (Sky), sUSDe [^1] (Ethena). |
| **A2: Off-Chain Yield-Bearing Tokens** | Tokens backed by off-chain or hybrid assets whose value is determined via an oracle feed, issuer-published NAV, or off-chain attestation. The token's price reflects the performance of non-digital-native underlying assets and cannot be independently derived from on-chain state alone. | BUIDL (BlackRock Securitize), OUSG/USDY (Ondo), bIB01 (Backed), syrupUSDC (Maple), USDM (Mountain), USCC (Superstate Crypto Carry Fund) |
| **A3: Private Credit Vault Tokens** | Tokens representing deposits into structured credit facilities or private lending arrangements where yield is generated from off-chain or hybrid lending activities. The token's value accrues through a combination of on-chain smart contract state and off-chain interest calculations based on contractually agreed terms. Yield accrual may require manual adjustment based on periodic interest rate agreements or issuer-reported performance. | Pareto / FalconX USDC vault (prime brokerage credit facility), Credit Coop / Rain Veris Credit Vault (overcollateralised working capital lending) |
| **B: PT Tokens** | Principal Tokens from yield-splitting protocols. Trade at a discount to the underlying asset and converge linearly to par value at maturity, analogous to zero-coupon bonds. Valued on a hold-to-maturity basis. | Pendle (Ethereum): PT-sUSDe, PT-aUSDC, PT-sDAI, Spectra PTs. Exponent (Solana): PT-USX, PT-eUSX, PT-Onyc. |
| **C: LP Positions** | Positions in automated market maker (AMM) pools. The LP token or NFT position represents a pro-rata claim on the pool's reserves, which are typically composed of assets from Categories A1, A2, A3, B, and/or E. Value is derived by decomposing the LP into its constituent token balances at the Valuation Block and pricing each constituent per its applicable category methodology. | Curve stablecoin pools, Uniswap V3 stablecoin pairs, Aerodrome, Balancer stable pools, Pendle LP, Exponent LP (Solana) |
| **D: Leveraged Positions** | Composite positions created via money market borrowing (looping), where collateral is deposited into a lending protocol and stablecoins are borrowed against it. Not a standalone asset but an overlay structure: the position is decomposed into its collateral component and debt component, each valued individually per the applicable category methodology, and netted to derive the position value. Net Position Value = Value of Collateral (inclusive of accrued supply interest) -- Value of Debt outstanding (inclusive of accrued borrow interest). | Morpho debt positions (syrupUSDC collateral / USDC debt, sUSDe collateral / USDC debt). AAVE debt positions (PT-sUSDe collateral / USDC debt, USCC collateral / USDC debt). Kamino debt positions (PT-USX + PT-eUSX collateral / USX debt, ONyc collateral / USDG debt). |
| **E: Stablecoins & Cash** | Undeployed stablecoins held on-chain across any custodian wallet, or fiat currency balances held at Bank Frick. These constitute the Basket's base denomination and primary settlement currency. | USDC, USDT, DAI, PYUSD, USDG, USX, USD fiat at Bank Frick |
| **F: Other / Bespoke** | Any position not fitting Categories A1-E, including tokens acquired incidentally through Product's yield strategies rather than through deliberate investment decisions. This category includes governance token rewards, airdrop claims, YT tokens, protocol-specific tokens, and incidental or dust positions of negligible value deposited unsolicited into the Product's wallets. YT tokens are the yield component counterpart to PT tokens (Category B), issued by the same yield-splitting protocols. | Pendle YT tokens, Exponent YT tokens, governance token rewards i.e. MORPHO/ARB/OP, unclaimed airdrops, protocol points, dust and spam tokens. |

[^1]: Ethena's sUSDe is classified under Category A1 because its on-chain exchange rate, reported by the sUSDe smart contract, is the authoritative and sufficient pricing source for valuation purposes. The classification is determined by the verifiability of the pricing source (deterministic on-chain exchange rate), not by the nature of the underlying yield generation strategy (which involves off-chain delta-neutral basis trading). Should the sUSDe exchange rate mechanism change such that it no longer reflects a deterministic on-chain value, the token shall be reclassified to Category A2.

Assets held at Kraken shall be classified into the applicable category based on asset type (typically Category E for stablecoins or fiat-equivalent balances). However, regardless of category classification, the valuation source for all assets held at Kraken shall be the market price as reported by Kraken at or near the Valuation Time, as specified in the Final Terms. The category-specific Primary Valuation Source defined in Section 6 does not apply to Kraken-held assets. Where assets are transferred between Kraken and other custodians, the applicable valuation methodology changes accordingly upon settlement of the transfer.

## 6. Valuation Methodology by Asset Class

The following methodologies define the Primary Valuation Source for each asset category established in Section 5. The Calculation Agent shall apply these methodologies in the ordinary course unless a Special Valuation Provision (Section 9) applies.

**Valuation timing:** All valuations are determined as at the Valuation Block (for on-chain assets) or the Valuation Time (for off-chain data sources such as oracle feeds, issuer NAVs, and exchange prices). Where an off-chain data source does not publish a value at the exact Valuation Time, the most recent value available prior to the Valuation Time shall be used, subject to the staleness thresholds defined in each subsection below.

**Layered methodologies:** The valuation of a single position may require the application of multiple methodologies from different asset categories. Reading the balance of a position (determining how many tokens the Product holds) and pricing that position (determining what each token is worth) may involve different sections of this Policy.

For example, a leveraged position (Category D) held on a money market protocol requires an on-chain smart contract query (as described in Section 6.1) to read the collateral and debt balances from the protocol's lending contract. However, the collateral tokens themselves -- which may be off-chain yield-bearing tokens such as BUIDL, syrupUSDC, USCC, or bIB01 -- are then priced using the Category A2 methodology (Section 6.2), not the Category A1 methodology used to read the balance.

Similarly, an LP position (Category C) is decomposed into its constituent tokens using on-chain pool queries, but each constituent token is then priced per its own applicable category (A1, A2, B, or E).

The category assigned to a position in Section 5 determines the overall valuation approach. The categories of its underlying components determine how each component within that position is priced.

### 6.1. Category A1: On-Chain Yield-Bearing Tokens

**Primary Source: Smart Contract Query**

The value of each on-chain yield-bearing token shall be determined by querying the issuing protocol's smart contract at the Valuation Block to obtain the token's exchange rate, share price, or accrued balance relative to the underlying asset. This is the most reliable valuation method available for this asset category, as the data is read directly from the blockchain without intermediaries, and the result is independently reproducible by any party with access to a blockchain node.

**Methodology:**

- Query the protocol's on-chain exchange rate or token balance at the Valuation Block. Many DeFi protocols implement a common vault standard known as ERC-4626, which provides a uniform interface for querying a token's exchange rate using the function `convertToAssets` (which returns the underlying asset value for a given number of vault shares). Protocols adhering to this standard include Morpho vaults, Euler vaults, Ethena sUSDe, Upshift vaults, and more. Other protocols implement their own query functions, as detailed under Data Source below.
- For vault aggregator tokens -- the aggregator's smart contract exchange rate shall be used as the Primary Valuation Source. This exchange rate reflects the blended performance of all underlying strategy allocations within the vault and is treated as equivalent to a single-protocol exchange rate for valuation purposes.
- Multiply the token balance held by the Product by the exchange rate to derive the value denominated in the underlying asset (typically a stablecoin).
- Price the underlying asset per the Category E methodology.
- Include accrued but unclaimed lending and supply interest (i.e. yield that has been earned by the protocol but not yet withdrawn or claimed by the Product). Protocol incentive rewards (governance tokens) -- whether distributed directly by the lending protocol or via external reward distribution platforms (e.g. Merkl) -- are excluded from Category A1 valuation and captured separately under Category F.

**Data source:** The data is obtained via a direct query to a blockchain node (known as an RPC call [^2]). The query is made to the relevant protocol's smart contract or data account on whichever blockchain the position is held.

[^2]: A remote procedure call that reads the current state of a smart contract or on-chain account without modifying it or executing a transaction on the blockchain.

The technical method for reading on-chain data varies by blockchain architecture. The Product currently holds positions across multiple blockchain families, and the Investment Manager may deploy into additional blockchains as the strategy evolves. Regardless of the blockchain architecture, the principle remains the same: the exchange rate or token balance must be read directly from the protocol's on-chain state at the Valuation Block, producing a result that is independently reproducible by any party without access to a node on that blockchain.

The two principal blockchain architectures currently used by the Product are described below for reference. Should positions be deployed on blockchains following a different architecture, the Investment Manager shall document the applicable data retrieval method and provide it to the Calculation Agent for verification.

- **EVM-compatible blockchains:** Smart contracts on these blockchains expose callable functions that return a token's exchange rate, balance, or position data. The standard method is to submit a read-only call to the relevant smart contract, which returns the requested data without executing a transaction on the blockchain. Where a protocol does not adhere to the ERC-4626 standard -- including protocols that represent positions as non-fungible tokens (NFTs) or that report balances in internal share units requiring conversion -- the NAV work file submitted by the Investment Manager shall contain sufficient detail for the Calculation Agent to identify and reproduce the queries used.
- **Solana:** Solana follows a fundamentally different data model. Rather than calling functions on a smart contract, data is read from on-chain accounts -- dedicated data storage structures associated with each protocol and user position. Each protocol defines its own data layout (known as an IDL -- Interface Description Language), and reading position data requires protocol-specific decoding of the relevant accounts. Token balances are queried separately using Solana's native token account lookup.

### 6.2. Category A2: Off-Chain Yield-Bearing Tokens

**Primary Source: Oracle Price Feed**

Off-chain yield-bearing tokens are backed by assets that reside wholly or primarily outside the blockchain (e.g. U.S. Treasury bills, basis trades, traditional credit facilities, other). Their token price does not reflect a deterministic on-chain exchange rate derived from smart contract state, like A1 tokens. Instead, the price is published periodically by an on-chain oracle, an issuer-designated price feed, or an off-chain NAV calculation performed by the token issuer or its appointed fund administrator.

**Methodology:**

- Identify the highest-priority pricing source available for specific token, per the source hierarchy defined below.
- Obtain the token price from that source at or as close as practicable to the Valuation Time.
- Assess data freshness per the staleness provisions below. If the primary source is stale, the next available source in the hierarchy may be used, provided its price is more recent. The use of an alternative source shall be noted in the NAV Report.
- Where both an oracle feed and an issuer-published NAV exist for the same token, cross-reference one against the other. If the two sources diverge by more than the tolerance in Appendix B, the cause shall be investigated before the valuation is finalised.

**Data source -- Priority hierarchy**

The pricing source for each A2 token shall be selected based on the following hierarchy, applied in order of priority. The highest-priority source that is available and current for the specific token shall be used.

1. **On-chain oracle feed** -- a price published on-chain by a recognized, third party oracle network. Applied in order of reputation: (1) Chainlink, (2) Pyth Network, (3) Redstone, (4) other reputable oracle providers. The oracle's update timestamp (readable from the oracle contract) is used to verify freshness.
2. **Issuer-published NAV or price feed** -- a price calculated and published by the token issuer, its appointed fund administrator, or its designated API. This includes NAVs published by fund administrators (e.g. for tokenised fund shares), prices published via issuer APIs (e.g. for tokenised reinsurance or structured credit products), and prices attested by the issuer on a periodic schedule.
3. **Secondary market price** -- the token's traded price on a decentralised exchange (DEX), calculated as a time-weighted average price (TWAP) over a reasonable period. Used only as a last resort where sources 1-2 are unavailable.

**Staleness Assessment**

The price is considered stale if it has not been updated within a period that materially exceeds the token's expected update cycle. The Investment Manager shall maintain a record of the expected update frequency for each A2 token in the portfolio, based on the issuer's published update schedule or observed historical cadence. The price shall be flagged as potentially stale if it has not been updated for more than twice the expected update interval at the Valuation Time. The Investment Manager shall note in the NAV Report the date and time of the most recent source update for each A2 position.

**Key distinction from A1:** Category A1 tokens can be valued with high confidence from a single on-chain smart contract query, producing the result that is deterministic and independently reproducible. Category A2 tokens require reliance on an off-chain attestation (whether an oracle feed, an issuer API, or a fund administrator's NAV calculation), introducing an additional dependency on the accuracy, timeliness and integrity of the publishing party. This dependency is mitigated by cross-referencing between available sources and applying the staleness assessment above.

### 6.3. Category A3: Private Credit Vault Tokens

**Primary Source: Manual Accrual Based on Contractual Terms**

Private credit vault tokens represent deposits into structured lending arrangements where yield is generated from off-chain or hybrid credit activities -- such as prime brokerage lending, overcollateralised working capital financing, or other bilateral credit facilities. Unlike Category A1 tokens, the vault's exchange rate or share price does not update deterministically through an autonomous smart contract mechanism. Unlike Category A2 tokens, there is no independent oracle or widely published NAV for the underlying credit position. Instead, the yield accrues based on contractually agreed interest rates between the lender and borrower in the vault, and the token's value is derived from the principal deposited plus accrued interest calculated from those terms.

**Methodology:**

- Establish the principal amount: the quantity of tokens (or underlying stablecoins) deposited into the vault, as confirmed by the on-chain deposit transaction and the vault's smart contract balance at the Valuation Block.
- Determine the applicable interest rate: the rate contractually agreed between the vault operator and the borrower for the current accrual period. This rate may be fixed for a defined term or reset periodically (e.g. monthly) based on renegotiation between the parties.
- Calculate accrued interest: apply the applicable interest rate to the principal amount on a pro-rata basis from the start of the current accrual period to the Valuation Date.
- The total position value is the sum of the principal and accrued interest, denominated in the underlying stablecoin and priced per the Category E methodology.
- Where the vault's smart contract reports an exchange rate or tranche price (e.g. via an ERC-4626 `convertToAssets` call or a protocol-specific tranche pricing function), this on-chain value may be used as a retrospective cross-reference. However, because such on-chain prices are typically updated after the NAV calculation rather than before it, they shall not be used as the Primary Valuation Source.

**Documentation Requirements:**

Given the reliance on off-chain contractual terms rather than independently observable market data, the following documentation shall be maintained by the Investment Manager and made available to the Calculation Agent on each Valuation Date:

- The current loan or credit facility agreement (or summary term sheet) specifying the interest rate, accrual basis, payment frequency, and maturity or renewal terms.
- Written confirmation of any rate changes agreed during the current or preceding accrual period.
- A reconciliation showing the principal balance, applicable rate, accrual period, and calculated interest for each A3 position.

Where the contractual terms change between Valuation Dates -- for instance, a monthly rate reset -- the accrued interest calculation shall reflect the applicable rate for each sub-period, weighted by the number of days at each rate.

**Impairment:**

If the Investment Manager becomes aware of a material credit event affecting an A3 position -- including but not limited to borrower default, missed interest payments, margin call failures, or a material deterioration in the borrower's creditworthiness -- the position shall no longer be valued using the accrual methodology. Instead, the position shall be marked to its estimated recovery value in good faith, which may be zero.

**Key distinction from A1 and A2:**

Category A3 tokens occupy a unique position in the valuation framework. The principal balance can be verified on-chain (the deposit is recorded on the blockchain), but the yield component depends entirely on off-chain contractual arrangements that are not observable from public data. This makes A3 the category most reliant on documentation provided by the Investment Manager, and the category where the Calculation Agent's verification role is most critical.

### 6.4. Category B: PT Tokens

**Primary Source: Linear Calculation to Maturity**

PT tokens are issued by yield-splitting protocols (e.g. Pendle, Exponent Finance, Spectra) that separate the yield-bearing asset into a principal component (PT) and a yield component (YT). The PT represents a fixed claim on the principal amount of the underlying asset at maturity, analogous to a zero-coupon bond. It is acquired at a discount to the underlying's current value, with the discount reflecting the implied fixed yield to maturity. The Product's strategy is to hold PT positions to maturity, and the valuation methodology reflects hold-to-maturity assumptions.

**Methodology:**

- At maturity: PT value = par value of the underlying asset (1:1 with the underlying).
- Before maturity: PT value is calculated using linear amortisation from the purchase price to par:

> `PT value = Underlying Value / (1 + Implied Rate at Purchase * (Days to Maturity / 365))`

  where:
  - **Underlying Value** is the current value of the underlying yield-bearing asset, determined per the applicable Category A1, A2 or E methodology.
  - **Implied Rate at Purchase** is the fixed yield implied by the discount at which PT was acquired, as recorded in the trade log at the time of execution.
  - **Days to Maturity** is the number of calendar days remaining from the Valuation Date to the PT's maturity date.

- The calculation assumes linear convergence to par over the remaining term. No mark-to-market adjustment for secondary market trading of the PT is applied in the ordinary course.

**Individual Lot Tracking**

Where the Product has acquired PT tokens of the same series across multiple transactions at different times and implied rates, each purchase lot shall be tracked individually. The trade log maintained by the Investment Manager shall record, for each lot: the purchase date, the quantity of PT tokens acquired, the implied rate at the time of purchase, the maturity date, and the cost basis. The valuation of each lot is calculated separately using its own implied rate, and the total PT position value is the sum of all individual lot valuations.

**Cross-Reference**

The PT's implied price from the protocol's AMM (e.g. Pendle AMM, Exponent Finance market) at the Valuation Block may be obtained as a cross-reference. However, because AMM-implied rates naturally diverge from the rate locked in at a purchase -- particularly as maturity approaches -- the AMM price is not used as a verification source and does not replace or adjust the linear amortisation calculation. Where concerns arise about the creditworthiness of the underlying asset, Section 9.3 applies.

**Scope -- PTs held directly or as collateral only**

This methodology applies only to PT tokens held as standalone positions or deposited as collateral in a lending protocol (Category D). PT tokens held within LP positions (Category C) are not valued using linear amortisation, because the AMM continuously rebalances the pool's composition between PT and underlying yield-bearing token. PTs within LP positions are instead valued as part of the LP decomposition methodology described in Section 6.5.

### 6.5. Category C: LP Positions

**Primary Source: Decomposition into Constituent Tokens**

LP positions represent liquidity provided to an automated market maker (AMM) pool. The LP token or NFT position represents a pro-rata claim on the pool's reserves, which are typically composed of assets from Categories A1, A2, B, and/or E. The position is valued by decomposing it into its underlying token balances and pricing each constituent individually.

**Methodology:**

- Query the pool's smart contract at the Valuation Block to determine the LP position's claim on each underlying token (e.g. `getReserves`, `positions`, `slot0` for concentrated liquidity [^3]). This involves reading the pool's total reserves, the total LP token supply, and the Product's LP token balance, from which the pro-rata share of each constituent token is derived.
- Price each constituent token using its applicable category methodology: A1 for on-chain yield-bearing tokens, A2 for off-chain yield bearing tokens, or E for stablecoins. For LP positions in yield-splitting protocols where one of the constituents is a PT token, the PT pricing methodology described under "Yield-Splitting Protocol LPs" below applies instead of Section 6.4.
- Sum the values of all constituents to arrive at the total LP position value.
- Any impairment loss [^4] is implicitly captured by this methodology, as the decomposition reflects the actual token balances held at the current pool state.

[^3]: Pools where liquidity is allocated within a specific price range rather than across the full price spectrum.

[^4]: The difference in value between holding tokens in the pool versus holding them outside it, caused by price divergence between the pool's constituent tokens.

**Yield-Splitting Protocol LPs (Pendle, Exponent Finance, and equivalents):**

LP positions in yield-splitting protocols represent exposure to both a PT token and the underlying yield-bearing token (wrapped as an SY -- Standardised Yield -- token equivalent). The LP shall be decomposed into its PT and SY components at the Valuation Block.

The PT component within an LP position shall not be valued using the linear amortisation methodology described in Section 6.4. Because the AMM continuously rebalances the pool's composition between PT and the underlying token, the PT balance changes over time in response to market activity. Instead, PT component shall be priced using the protocol's current implied rate at the Valuation Block. For Pendle, this is the AMM's implied rate. For Exponent Finance, this is derived from `last_ln_implied_rate` using the formula:

> `PT Price = Underlying Price * EXP(-last_ln_implied_rate * Days to Maturity / 365.25)`

The SY component shall be priced by reference to the underlying yield-bearing token per its applicable category (A1 or A2).

**Accrued Fees and rewards**

Include accrued but unclaimed trading fees where they are attributable to the LP position and claimable at the Valuation Block. Protocol incentive rewards -- whether distributed directly by the pool or via external reward distribution platforms -- are excluded from the LP valuation and captured separately under Category F.

**Concentrated liquidity positions:** For positions in concentrated liquidity pools (e.g. Uniswap V3 and its derivatives), the valuation shall reflect the actual token amounts held within the position's active range at the Valuation Block, not the full-range notional. If the current pool price has moved outside the position's range, the positions holds only one of the two constituent tokens, and shall be valued at that single-token exposure.

**Note. YT Tokens Encountered in Other Positions**

YT tokens maybe be encountered as a constituent of various position types -- including within yield-splitting protocol LP positions, deposited as collateral in a lending protocol obligation account, or held as standalone tokens in the Product's wallets. Regardless of where they are encountered, YT tokens shall be priced per Category F methodology (Section 6.8). Where a YT token forms part of a composite position (LP decomposition or leveraged position), its value is included in the composite calculation using Category F price.

### 6.6. Category D: Leveraged Positions (Looping / Money Market Borrowing)

**Primary Source: Net Position Decomposition**

Leveraged positions are not a standalone asset class but a composite overlay structure: collateral is deposited into an on-chain lending protocol, stablecoins are borrowed against it, and the borrowed amount is redeployed into yield-bearing position. The process may be repeated to increase exposure. The position is valued by decomposing it into its collateral and debt components, valuing each independently, and netting the two.

> `Net Position Value = Value of Collateral - Value of Debt Outstanding`

#### 6.6.1. Collateral Valuation

The collateral balance is read from the lending protocol's smart contract or obligation account at the Valuation Block, inclusive of any accrued supply interest. The balance read is an infrastructure step -- it determines how many tokens are deposited -- and follows the data retrieval methods described in Section 6.1 regardless of the collateral token's own asset category.

The collateral tokens are then priced per their applicable category methodology:

- On-chain yield-bearing token (e.g. Morpho vault shares): Category A1 (Section 6.1).
- Off-chain yield-bearing token (e.g. syrupUSDC, BUIDL, USCC): Category A2 (Section 6.2).
- Private credit vault tokens: Category A3 (Section 6.3).
- PT tokens: Category B, using linear amortisation (Section 6.4).
- If the collateral is an LP token: Category C, using decomposition (Section 6.5).
- Stablecoins: Category E (Section 6.7).

The collateral balance shall be read from the money market protocol's smart contract at the Valuation Block, inclusive of any interest it has accrued.

#### 6.6.2. Debt Valuation

The debt balance (borrowed amount) is read from the lending pool's smart contract at the Valuation Block, inclusive of all accrued borrow interest.

Since the Product borrows stablecoins (typically USDC, USDT, or others), the debt is valued per the Category E methodology (Section 6.7). In practice, this means the debt is valued at par or at the oracle-reported price, unless the borrowed stablecoin has de-pegged -- in which case the de-peg provision in Section 9.4 apply, and the debt is valued at the de-pegged price (which may result in a net gain to the position if the borrowed stablecoin loses value).

### 6.7. Category E: Stablecoins & Cash

**Primary Source: Par Value / Oracle Price / Face Value**

- **USDC and USDC-pegged stablecoins (USDS, DAI, PYUSD):** Valued at par (1.00 USD), provided the stablecoin maintains its peg within +/-0.5% of par at the Valuation Time. If a stablecoin deviates beyond this threshold, the de-peg provisions in Section 9.4 apply and the stablecoin is priced at its actual traded value.
- **Non-USDC-pegged stablecoins (USDT, USDG, and others):** Valued at the USDT/USD oracle-reported price at the Valuation Time, applying the oracle priority hierarchy defined in Section 6.2 (Chainlink, Pyth, Redstone, other). These stablecoins are not assumed to be at par due to their historically wider peg variance or shorter track record.
- **Fiat currency balances:** Valued at face value in USD. Non-USD balances are converted using the ECB reference exchange rate published on the Valuation Date, or the most recent available rate if the Valuation Date falls on weekend or public holiday.

**Note on wrapped yield-bearing variants**

Certain stablecoins have yield-bearing wrapped versions -- for example, USDS (Category E) can be deposited into the Sky savings contract to receive sUSDS (Category A1). The unwrapped stablecoin is valued under this section; the wrapped yield-bearing token is valued under its applicable category (typically A1) using the smart contract exchange rate per Section 6.1.

### 6.8. Category F: Other / Bespoke

**Primary Source: Best Available**

The Investment Manager shall propose fair value for each F-category position using the most appropriate methodology available, applying the guiding principles in Section 1. The methodology and rationale for each position shall be documented in the NAV report.

- **YT Tokens (Pendle, Exponent Finance and equivalents):** The YT's value is derived from the underlying token price and the PT price ratio:

  > `YT Price = Underlying Price * (1 - PT Price Ratio)`

  where:
  - **Underlying price** is the current value of the underlying yield-bearing asset, determined per its applicable category (A1 or A2).
  - **PT Price Ratio** is the PT's current price expressed as a proportion of the underlying value, derived from the protocol's implied rate at the Valuation Block. For Pendle, this is the AMM's implied fixed rate. For Exponent Finance, this is derived from `last_ln_implied_rate` using the formula: `PT Price Ratio = EXP(-last_ln_implied_rate * Days to Maturity / 365.25)`.

- As YT approaches maturity, its value converges towards zero (assuming the remaining yield to be captured diminishes). If a YT is close to expiry and illiquid, it may be marked to zero with a note in the NAV report.

- **Governance Token Rewards** shall be valued using the following hierarchy:
  1. **Kraken reported price** -- if the token is listed on Kraken, which is an approved custodian and reference source under the Final Terms.
  2. **Aggregated market price from CoinGecko** -- a volume-weighted price aggregated across multiple exchanges.
  3. **DEX TWAP** -- a time-weighted average price on a decentralised exchange, used only where the token has no CEX listing or aggregator coverage.

- **Unclaimed rewards** are included in the valuation only if they are claimable at the Valuation Block -- meaning the Product can execute a claim transaction and receive the tokens without further conditions. Rewards that are vested, locked, or subject to a future unlock event are valued at zero until they become claimable.

- **Airdrop Claims and Protocol Points:** Valued at zero until all the following conditions are met: the token is confirmed and has a defined contract address, the airdrop is claimable by the Product's wallet, and the token has established liquid markets (listed on at least one exchange or DEX with meaningful trading volume). Once all conditions are met, the token is valued per governance token hierarchy above or reclassified to its applicable category if appropriate.

- **Any Other Positions:** For any other position not covered by the above sub-categories, the Investment Manager shall propose a valuation methodology in writing in the NAV report, including the data source, calculation method, and rationale.

## 7. Independent Verification

On each Valuation Date, the aggregate portfolio valuation determined using the Primary Valuation Sources per Section 6 shall be cross-referenced against at least one independent, institutional-grade portfolio aggregation software. The approved Verification Sources are:

- **DeBank** (https://debank.com/) -- on-chain portfolio tracking and position decomposition. DeBank covers EVM-compatible blockchains only and does not track positions on Solana or other non-EVM chains.
- **Octav** (https://octav.fi/) -- DeFi portfolio analytics and valuation. Octav requires a paid subscription, which the Product maintains.

These Verification Sources operate by independently reading on-chain positions and applying their own pricing methodologies. Because they derive their data primarily from blockchain state, they provide a meaningful independent check on the Primary Valuation Sources used in Section 6.

However, **neither source is guaranteed to capture every position in the Basket** -- coverage depends on the Verification Source's protocol integrations and supported blockchains, which may lag behind the Product's deployment of capital into new protocols or chains.

**Scope limitation:** The Verification Sources cover on-chain positions only. They do not capture assets held at Kraken (valued per Kraken's reported market price) or fiat currency balances held at Bank Frick (valued at face value per Section 6.7).

Furthermore, within on-chain positions, coverage may be incomplete -- for instance, positions in newly launched or niche protocols may not be recognised. The verification cross-reference therefore represents a best-efforts independent check on the on-chain portion of the Basket, not a complete independent valuation.

For Kraken-held assets, the Calculation Agent shall verify the reported price against Kraken's publicly available market data. For Bank Frick fiat balances, the Calculation Agent shall verify against Bank Frick's own custody records.

### 7.1. Verification Process

- The Investment Manager calculates the total portfolio value using the Primary Valuation Sources per Section 6 and presents it in the NAV report together with the total on-chain portfolio value as reported by at least one approved Verification Source, the percentage divergence between the two, and identification of any positions not captured by the Verification Source.
- The Calculation Agent reviews the verification data as part of its NAV review. The Calculation Agent may, at its discretion, independently obtain the Verification Source data to confirm the figures presented by the Investment Manager.
- If the difference between the Primary valuation and the Verification Source exceeds the applicable Divergence Tolerance (Appendix B), the cause shall be investigated before finalising the NAV.
- The outcome of the verification -- including the values reported by the Primary and Verification Sources, the percentage divergence, and any investigation findings -- shall be recorded in the NAV Report.

### 7.2. Divergence Resolution

Where a divergence exceeding the applicable tolerance is identified:

- The Calculation Agent shall first verify the accuracy of the Primary data, confirming correct token balances, correct exchange rates or oracle prices, and correct Valuation Block.
- If the Primary data is confirmed to be correct, the Primary valuation shall be used, with the divergence noted in the NAV Report. Common causes of applicable divergence include:
  - Differences in pricing methodology between the Primary Source and the Verification Source (for example, the Verification Source may use a different oracle or a market price rather than a smart contract exchange rate).
  - Timing differences in data retrieval.
  - Differences in how accrued interest or rewards are treated.
  - Incomplete position coverage by the Verification Source, where the source does not recognise or display one or more positions held by the Product.
- Where the divergence is attributable to missing positions in the Verification Source, the NAV report shall identify which positions are not captured and confirm that they have been valued using the Primary methodology.
- If the Primary data appears incorrect or unreliable, the Verification Source data or the Fallback Source (Section 8) shall be used, with the rationale documented in the NAV report.
- If both Primary and Verification Sources appear unreliable, the Fallback Source shall be used.

### 7.3. Asset-level verification

In addition to the aggregate portfolio cross-reference, the Calculation Agent may perform asset-level verification for individual positions -- particularly for positions that represent a material share of the Basket's total value, positions classified under Category A2 or A3 (where pricing depends on off-chain sources), and newly added positions being valued for the first time. Asset-level divergencies exceeding the applicable tolerance in Appendix B shall be investigated on the same basis as aggregate divergencies.

## 8. Fallback Valuation Source

ForDefi's portfolio valuation engine shall serve as the Fallback Valuation Source.

### 8.1. Trigger Conditions

The Fallback Source shall be used only when:

- The Primary and Verification Sources for a given asset are unavailable.
- The Primary and Verification Sources produce materially unreliable results that cannot be resolved through the divergence resolution process in Section 7.2.
- A Market Disruption Event has occurred (Section 9.7).

The Fallback Source is not used as a routine cross-reference and does not replace the Verification Sources described in Section 7.

### 8.2. Scope and limitations

ForDefi's portfolio valuation engine covers on-chain positions custodied at ForDefi. It does not cover assets held at Kraken or fiat balances held at Bank Frick -- for those assets, the custodian-specific verification procedures described in Section 7.1 apply.

As the Product's on-chain custodian, ForDefi has direct visibility into wallet balances and position data. This provides practical reliability but also means the Fallback Source is not fully independent of the custody infrastructure. The Calculation Agent shall take this into account when assessing the reliability of the Fallback Source data.

### 8.3. Documentation

Where the Fallback Source is used, the Calculation Agent shall document in the NAV Report:

- The specific positions for which the Fallback Source was used.
- The reason the Primary and Verification Sources were unavailable or unreliable.
- The value reported by ForDefi for each affected position.
- Any adjustments applied to the ForDefi-reported value and the rationale for such adjustments.

### 8.4. Fallback source unavailability

If the Fallback source is itself unavailable (for instance due to ForDefi platform outage), the Investment Manager may use any commercially reasonable source, documented in the NAV report with written rationale and subject to approval by the Calculation Agent. This provision also applies where all three tiers of sources (Primary, Verification, and Fallback) are simultaneously unavailable, as may occur during a widespread Market Disruption Event (Section 9.7).

## 9. Special Valuation Provisions

The following provisions apply where events or circumstances render the standard valuation methodologies in Section 6 inapplicable or unreliable. Where a Special Valuation Provision is triggered, it takes precedence over the standard methodology for the affected positions until the Calculation Agent determines the normal conditions have resumed.

### 9.1. Protocol or Technical Failure

Where an asset or position is affected by a technical failure in the underlying protocol or blockchain infrastructure -- including but not limited to smart contract exploits, hacks, unauthorised access to protocol funds, smart contract bugs or logic errors, oracle manipulation, bridge failures, protocol governance attacks, unintended consequences of protocol upgrades or migrations, or critical infrastructure failures affecting the protocol's ability to process deposits, withdrawals, or interest accrual:

- The Investment Manager shall notify the Calculation Agent within 24 hours of becoming aware.
- Affected positions shall be marked to the estimated recovery value in good faith. The estimated recovery value should consider any information available at the Valuation Date regarding the protocol's remediation efforts, insurance coverage, or recovery plan.
- If no recovery value can be reasonably estimated, the position shall be marked to zero.
- The valuation shall be reassessed on each subsequent Valuation Date as information becomes available, and the NAV report shall document the current status and any changes to the recovery estimate.

### 9.2. Partial or Full Liquidation of Leveraged Position

If a leveraged position (Category D) is partially or fully liquidated by the lending protocol:

- The remaining collateral (post-liquidation) shall be valued per the applicable methodology in Section 6.
- The remaining debt (post-liquidation) shall be valued per Section 6.7.
- Any liquidation penalty incurred (the difference between the collateral seized and the debt repaid, net of protocol fees) shall be recognised as a realised loss in the NAV calculation.
- The Investment Manager shall notify the Calculation Agent within 24 hours of any liquidation event.

### 9.3. PT Token Default or Underlying Failure

If the underlying asset of a PT token suffers a material impairment (e.g. the underlying yield-bearing token's protocol is exploited, or the underlying stablecoin de-pegs permanently):

- The PT shall no longer be valued using the linear amortisation model (See Section 6.4).
- The PT shall be marked to the estimated recovery value of the underlying, which may be zero.
- If the PT is still trading on the protocol's AMM, the AMM price may be used as a reference point to inform the recovery estimate but is not binding.
- The Investment Manager shall notify the Calculation Agent within 24 hours of becoming aware of a material impairment affecting a PT's underlying asset.

### 9.4. Stablecoin De-Peg

If a stablecoin held in the Basket (whether as a standalone position, as the borrowed asset in a leveraged position, or as a constituent of an LP pool) deviates from its peg:

**Minor de-peg (0.5-2%)**

- The stablecoin shall be priced at its actual traded value using a centralised exchange price or DEX TWAP, rather than at par or the standalone oracle price.
- The Investment Manager shall notify the Calculation Agent.
- The NAV report shall note the de-peg, the source used for actual traded value, and the magnitude of deviation.

**Material de-peg (>2%)**

- The stablecoin shall be priced at its actual traded value.
- The Paying Agent shall notify investors within 2 business days.
- For leveraged positions where the borrowed stablecoin has de-pegged, the debt shall be valued at the de-pegged price. This may result in a net gain to the position if the borrowed stablecoin loses value relative to the collateral.
- If the de-peg persists across two or more consecutive Valuation Dates and shows no signs of recovery, the Calculation Agent may, in consultation with the Investment Manager, determine that the stablecoin should be permanently reclassified and no longer assumed to be at or near par.

### 9.5. Tokenised Fund Share Impairment

Where a tokenised fund share held in the Basket (Category A2) -- such as USCC, BUIDL, OUSG, among others -- experiences one or more of the following events:

- The issuer or fund administrator reports a material decline in the fund's NAV (greater than 3% in a single reporting period, absent a corresponding market-wide event).
- The issuer suspends redemptions or imposes withdrawal gates.
- The issuer fails to publish a NAV update within a period materially exceeding its expected update cycle (per the staleness assessment in Section 6.2).
- The fund is subject to regulatory action, enforcement proceedings, or public disclosure of material operational failures.

The following shall apply:

- The Investment Manager shall notify the Calculation Agent within 24 hours of becoming aware of any such event.
- If the issuer continues to publish a NAV, the published NAV shall be used but shall be flagged in the NAV Report as subject to elevated uncertainty. The Calculation Agent may apply a discretionary discount to the published NAV if there are reasonable grounds to believe the published figure does not reflect realisable value -- for example, if redemptions are suspended and the token trades at a material discount on secondary markets.
- If the issuer has ceased publishing a NAV, the position shall be valued at a secondary market price (DEX or OTC) if available, or at the last published NAV adjusted for any known impairments, or at zero if no reasonable basis for valuation exists.
- Where the affected token is held in the leveraged position (Category D), the impact on the net position value shall be assessed and documented.
- The valuation shall be reassessed on each subsequent Valuation Date until the event is resolved or the position is fully exited.

### 9.6. Private Credit Default or Impairment

Where a private credit vault position (Category A3) experiences a credit event -- including but not limited to:

- The borrower defaults on an interest payment or fails to repay principal at maturity.
- The borrower's creditworthiness materially deteriorates (e.g. insolvency proceedings, covenant breach, significant downgrade by a rating agency if applicable).
- The vault operator notifies depositors of a loss, write-down, or restructuring of the underlying credit facility.

The following shall apply:

- The position shall no longer be valued using the accrual methodology (Section 6.3).
- The position shall be marked to the estimated recovery value in good faith, taking into account any collateral held by the vault, expected recovery rates, and information provided by the vault operator.
- If no recovery value can be reasonably estimated, the position shall be marked to zero.
- The Investment Manager shall notify the Calculation Agent within 24 hours of becoming aware of any credit event and provide all available documentation from the vault operator.
- The valuation shall be reassessed on each subsequent Valuation Date as information becomes available.

### 9.7. Market Disruption Event

A Market Disruption Event is an event or a set of circumstances that, in the reasonable determination of the Calculation Agent, materially impairs the ability to reliably value or assess a significant portion of the Basket. Market Disruption Events include but are not limited to:

- Prolonged unavailability of one or more blockchain networks on which the Product holds material positions, such that on-chain data cannot be reliably read at or near the Valuation Time.
- Widespread oracle failure or data staleness across multiple oracle providers and token feeds simultaneously, as distinct from single-token staleness which is addressed in Section 6.2.
- Failure, insolvency, or suspension of operations of a major centralised exchange, prime broker, or any other major market infrastructure provider on which the Product relies for custody, execution, or pricing -- includes the scenarios where the Product holds assets at the affected institution.
- Failure or exploit of a major DeFi protocol that is systemically important to the broader ecosystem, causing cascading effects across multiple protocols or asset prices, even if the Product does not hold any positions directly in the affected protocol.
- A significant and sudden decline in the value of assets across a broad segment of the market relevant to the Basket (e.g. a systemic stablecoin de-peg event affecting multiple stablecoins simultaneously, or a broad collapse in DeFi protocol token values), where the scale and speed of the decline materially impairs the reliability of standard pricing sources.
- Regulatory action by a governmental or supervisory authority that suspends, restricts, or prohibits trading, custody, or access to one or more asset types, protocols or platforms representing a material portion of the Basket -- including asset freezes, sanctions designations, or emergency orders affecting specific tokens or protocols.
- Force-majeure events -- including but not limited to natural disasters, armed conflict, cyberattacks on critical internet infrastructure, or widespread power outages -- that materially impair the ability of the Investment Manager, Calculation Agent, or custodians to perform their functions.

In such event:

- The Calculation Agent may, at its discretion, postpone the Valuation Date for as long as the Market Disruption Event persists and reliable valuation cannot be performed. The Calculation Agent shall reassess the situation at least every 5 business days and document the basis for continued postponement. If the Valuation Date is postponed to within 5 business days of the next scheduled Valuation Date, the Calculation Agent may, in consultation with the Investment Manager, combine the two valuation periods into a single NAV determination.
- The Paying Agent shall notify investors of any postponement within 2 business days of the decision to postpone and shall provide subsequent updates if the postponement is extended.
- During the postponement period, the Calculation Agent and Investment Manager shall make reasonable efforts to obtain reliable valuations for unaffected portions of the Basket. Where partial valuation is possible -- for example, where the disruption affects only one blockchain or one protocol -- the unaffected positions shall be valued using the standard methodologies, and only the affected positions shall be subject to the fallback provisions.
- For affected positions, the Fallback Source (Section 8) and the commercially reasonable source provision (Section 8.4) may be invoked as appropriate. Where no reliable source is available, the last available reliable data shall be used, adjusted for any known material changes, with the adjustments documented in the NAV Report.
- If the Market Disruption Event results in the permanent loss or inaccessibility of assets, the affected positions shall be valued per Section 9.1.

## 10. NAV Calculation

### 10.1. Formula

The Net Asset Value (NAV) per Product shall be calculated on each Valuation Date using the following formula, as specified in the Final Terms:

> `NAV = (Total Assets - Total Fees) / Total Outstanding Products`

Where:

- **Total Assets** is the aggregate value of all positions in the Basket, determined using the valuation methodologies in Section 6, inclusive of any accrued but unclaimed interest, lending income, and trading fees attributable to the Product's positions. Total Assets includes positions across all custodians (ForDefi, Kraken, and Bank Frick).
- **Total Fees** encompasses all applicable fees and charges associated with the management, operation, and administration of the Product, as specified in the Final Terms. These include:
  - **Management Fee:** 0.15% p.a. of the aggregate value of the Basket
  - **Administration Fee:** USD 10,000 p.a.
  - **Service Fee:** 0.15% p.a., minimum USD 15,000
  - **Performance Fee:** 0%, with High Watermark, calculated and accrued monthly
  - **Extra NAV fee:** USD 500 per additional NAV calculation, if applicable

  Fees that accrue continuously (Management Fee, Service Fee) shall be pro-rated from the previous Valuation Date to the current Valuation Date. Fixed annual fees (Administration Fee) shall be pro-rated on a daily basis.

- **Total Outstanding Products** is the number of Products currently issued and not redeemed as at the Valuation Date.

### 10.2. Process

The NAV determination follows a structured process:

1. **Position inventory.** The Investment Manager compiles a complete inventory of all positions held across all custodians at the Valuation Block / Valuation Time. Each position is classified per Section 5.
2. **Position valuation.** Each position is valued using the applicable methodology per Section 6, including any layered methodologies required for composite positions (Category C, D).
3. **Verification.** The aggregate on-chain portfolio valuation is cross-referenced against the approved Verification Sources per Section 7 and includes the results in the NAV Report.
4. **NAV Report submission.** The Investment Manager prepares the NAV report documenting the complete calculation (see Section 12) and submits it to the Calculation Agent.
5. **Review.** The Calculation Agent reviews the NAV report, verifies the methodologies applied, reviews the verification data, and either confirms the proposed valuation or communicates proposed adjustments to the Investment Manager per Section 11.1.
6. **Fee calculation and NAV determination.** The Calculation Agent calculates all accrued fees per the fee schedule in the Final Terms, applies the NAV formula, and determines the final NAV per Product.
7. **Communication.** The confirmed NAV is communicated to the Paying Agent for investor reporting and redemption processing.

### 10.3. Base Currency

The NAV is denominated in USD, the Product's Base Currency as specified in the Final Terms. All non-USD positions are converted to USD as part of the valuation methodology for each asset category (see Section 6.7 for fiat currency conversion).

### 10.4. Rounding

The NAV per Product shall be rounded to two decimal places (USD 0.01). Intermediate calculations shall be performed with full precision and rounded only at the final NAV per Product level.

## 11. Valuation Governance and Dispute Resolution

### 11.1. Pre-Publication Review

Before the NAV is published or communicated to the Paying Agent, the following process shall apply:

- The Investment Manager submits the NAV Report to the Calculation Agent, including the proposed NAV and all supporting documentation per Section 12.
- The Calculation Agent reviews the NAV Report, including the verification cross-reference provided by the Investment Manager per Section 7, and either confirms the proposed NAV or communicates proposed adjustments to the Investment Manager.
- Where adjustments are proposed, the Calculation Agent shall provide the Investment Manager with the specific positions affected, the adjusted values, and the rationale. The Investment Manager may respond with additional data or analysis within 2 business days.
- Once both parties agree on the NAV, or the Calculation Agent makes the final determination per Section 11.2 below, the confirmed NAV is communicated to the Paying Agent for investor reporting and redemption processing.

### 11.2. NAV Challenge Right

The Investment Manager retains the right to view and challenge any NAV determination before it is published by the Calculation Agent.

- A challenge must be submitted in writing within 2 business days of receiving the Calculation Agent's proposed NAV, specifying the positions in dispute, the alternative valuation proposed, and the support rationale.
- The Calculation Agent shall review the challenge and provide a written response with supporting data within 2 business days.
- If the challenge is upheld in whole or in part, the Calculation Agent shall issue a corrected NAV determination within 2 business days.
- If the challenge is rejected, the Calculation Agent shall provide a written explanation. The Calculation Agent retains final authority over the NAV determination, subject to the escalation procedure in Section 11.3.

### 11.3. Escalation

If a dispute remains unresolved within 5 business days of the initial challenge:

- The dispute shall be referred to an independent valuation expert.
- The expert shall be appointed by mutual agreement of the Calculation Agent and the Investment Manager within 5 business days of the decision to escalate.
- If the parties cannot agree on an expert within this period, each party shall nominate one candidate, and the Administrator (Vistra Fund Services) shall select between them.
- The expert shall provide a binding determination within 10 business days of appointment, based on the documentation and methodologies set out in this Policy.
- The cost of the expert determination shall be borne by the party whose valuation is further from the expert's determination. If both parties' valuations are equidistant, costs shall be shared equally.

### 11.4. NAV During Dispute

While a dispute is pending under Sections 11.2 or 11.3, the Calculation Agent and Investment Manager shall use reasonable efforts to resolve the dispute as promptly as practicable so as not to delay the publication of the NAV. Where a dispute relates to positions that are immaterial to the overall NAV, the Calculation Agent may publish NAV on a provisional basis, with any subsequent correction applied as an adjustment to the next Valuation Date. Where dispute relates to positions that are material to the overall NAV, the Calculation Agent may, at its discretion, delay publication until the dispute is resolved, in which case the Paying Agent shall notify the affected investors.

### 11.5. Conflict of Interest

The Calculation Agent acknowledges its concurrent roles as Paying Agent and general Custodian under the Program. These multiple roles create a potential conflict of interest, as the Calculation Agent is responsible for determining the NAV upon which redemptions it processes (as Paying Agent) are based, using assets it holds (as Custodian). To mitigate this conflict, the following safeguards shall apply:

- **Functional separation.** The custody, payment processing, and valuation functions within Bank Frick shall be performed by separate teams or individuals. Personnel responsible for the NAV determination shall not be involved in redemption processing decision for the same Valuation Date.
- **Audit Trail.** All NAV determinations shall be documented with sufficient detail -- including data sources, methodologies applied, and any discretionary judgements -- to enable independent reconstruction and audit by the Administrator (Vistra Fund Services) or the auditor of the Basket.
- **Access rights.** NAV Reports and all supporting documentation shall be made available to the Administrator and the Auditor upon request, without requiring prior approval from either the Calculation Agent or the Investment Manager.
- **Investment Manager oversight.** The pre-publication review process (Section 11.1) ensures that the Investment Manager -- who has the most detailed knowledge of the portfolio's positions -- reviews and validates the NAV before it is published. This provides an additional layer of scrutiny independent of the Calculation Agent's own review.
- **Annual review.** The effectiveness of the conflict of interest mitigation measures shall be assessed as part of the annual Policy review (Section 13), and any deficiencies identified shall be addressed in a Policy amendment.

## 12. Record Keeping and Reporting

### 12.1. NAV Report

The Investment Manager shall prepare a NAV Report on each Valuation Date and submit it to the Calculation Agent within maximum 7 business days of the Valuation Date. The NAV Report is the primary record of how the NAV was determined and contain at minimum:

**Position inventory:**

- Complete list of all positions held across all custodians (ForDefi, Kraken, Bank Frick) classified by asset category per Section 5.
- Token balances and quantities for each position.

**Valuation detail:**

- Valuation methodology applied to each position, with reference to the applicable subsection of Section 6.
- For Category A1 positions: the exchange rate or share price read from the smart contract, and the Valuation Block number and timestamp used.
- For Category A2 positions: the pricing source used (with reference to the priority hierarchy in Section 6.2), the price obtained, and the date and time of the most recent source update.
- For Category A3 positions: the applicable interest rate, accrual period, principal balance, and calculated accrued interest, together with reference to the supporting contractual documentation.
- For Category B positions (PT tokens held directly): the individual lot detail -- purchase date, quantity, implied rate at purchase, maturity date, cost basis, and current linear amortisation value of each lot.
- For Category C positions (LP): the decomposition into constituent tokens, the quantity and price of each constituent, and the methodology used for any PT components within the LP.
- For Category E positions: confirmation of par value assumption for USDC-pegged stablecoins, or the oracle price used for non-USDC-pegged stablecoins.
- For Category F positions: the methodology and data source used for each material position.

**Verification and cross-referencing:**

- The total portfolio value as reported by at least one approved Verification Source (Section 7).
- The percentage divergence between the Primary valuation and the Verification Source.
- Identification of any positions not captured by the Verification Source and confirmation that they have been valued using the Primary methodology.
- For Kraken-held assets: the Kraken reported price used.
- For Bank Frick fiat balances: the balance confirmed against custody records.

**Discretionary determinations:**

- Any positions where judgement was exercised -- including the use of an alternative pricing source, a Fallback Source, a manual adjustment, or a Special Valuation Provision (Section 9) -- with written rationale for each.

**Proposed Total Assets:**

- The aggregate value of all positions in the Basket as calculated by the Investment Manager, prior to fee deduction. The Calculation Agent applies fees and determines the final NAV per product per Section 10.2.

### 12.2. NAV Workfile

In addition to the NAV Report, the Investment Manager shall retain the NAV workfile (the working spreadsheet or equivalent calculation file) used to produce the NAV. The workfile shall contain sufficient detail for the Calculation Agent to identify data sources, queries, and calculations used for each position, and to reproduce or verify the results independently. The workfile shall be made available to the Calculation Agent, the Administrator, or the Auditor upon request.

### 12.3. Supporting Documentation

The following supporting documentation shall be maintained and made available upon request:

- Trade logs for all PT token purchases (Category B), recording the fields specified in Section 6.4.
- Current loan agreements, term sheets, and rate confirmations for all Category A3 positions, as specified in Section 6.3.
- Records of any rate changes, credit events, or material communications from vault operators for Category A3 positions.
- Notifications submitted under Section 9 (protocol exploits, liquidations, de-pegs, impairments, market disruptions).
- Written challenges and responses under Section 11.2, and expert determination under Section 11.3.
- The record of expected update frequencies for each A2 token, as required by Section 6.2.

### 12.4. Retention

All NAV Reports, NAV workfiles, and supporting documentation shall be retained by the Administrator for a minimum of 10 years from the relevant Valuation Date. Records shall be maintained in electronic format and stored in a manner that permits retrieval and independent audit. The relevant auditor shall have access to all records upon request without requiring prior approval from any other party.

## 13. Policy Review and Amendment

### 13.1. Annual Review

This Policy shall be reviewed at least once per calendar year by the Calculation Agent and the Investment Manager jointly. The review shall assess whether the Policy remains appropriate in light of:

- Changes in the composition of the Basket, including the addition of new asset types, protocols, or blockchains not contemplated at the time of the last review.
- Changes in available data sources, oracle infrastructure, or market infrastructure that affect the reliability or availability of Primary Valuation Sources.
- Changes in the custodian arrangements, including the addition or removal of custodians, or material changes to the services provided by existing custodians.
- Findings from the Auditor or the Administrator relating to valuation practices or record keeping.
- The effectiveness of the conflict of interest safeguards described in Section 11.5.
- Regulatory changes affecting valuation practices applicable to the Product or its underlying assets.
- Any recurring divergencies, disputes, or operational difficulties encountered during the preceding year's NAV determinations.

### 13.2. Ad Hoc Review

Either the Calculation Agent or the Investment Manager may initiate an ad hoc review of this Policy at any time where circumstances warrant. Events that should trigger an ad hoc review include but are not limited to:

- The Product deploying capital into a new asset category not currently covered by Sections 5 and 6.
- A material change in a protocol's smart contract mechanics that alters how a token's value is derived (e.g. migration from a rebasing model to an exchange rate model, or vice versa).
- A Market Disruption Event (Section 9.7) that reveals gaps or ambiguities in the Policy.
- A Special Valuation Provision (Section 9) being invoked for a prolonged period, suggesting the standard methodology may need permanent adaptation.
- The addition or removal of a custodian under the Program.

### 13.3. Amendment Process

Amendments to this Policy require the written agreement of both the Calculation Agent and the Investment Manager. The amendment process is as follows:

- The party proposing the amendment shall submit in writing, specifying the section(s) affected, the proposed new text, and the rationale.
- The other party shall respond in writing within 10 business days, either approving, rejecting with reasons, or proposing modifications.
- Once agreed, the amendment shall be recorded in Appendix C (Version History) with the date, description of the change, and the names of the approving parties.
- **Material amendments** -- defined as changes to valuation methodologies (Section 6), the asset classification framework (Section 5), the NAV calculation formula (Section 10), or the introduction of new asset categories -- shall be communicated to the Paying Agent, who shall notify investors at the next available opportunity.
- **Non-material amendments** -- such as the addition of new protocol examples, updates to the reference sources in Appendix A, or adjustments to divergence tolerance thresholds in Appendix B -- do not require investor notification but shall be recorded in Appendix C.

### 13.4. Effective Date of Amendments

Unless otherwise agreed by both parties, amendments take effect from the next Valuation Date following the date of written agreement. Amendments shall not be applied retroactively to prior NAV determinations.

---

## Appendix A: Reference Sources Guide

| Source Type | Examples | Used For |
|-------------|----------|----------|
| Smart Contract Reads (EVM) | Direct RPC calls (`eth_call`) to protocol contracts; ERC-4626 `convertToAssets` where applicable; protocol-specific functions for non-standard implementations | Category A1 (primary), Category C (decomposition), Category D balance reads, Category A3 tranche price cross-reference |
| Smart Contract Reads (Solana) | `getAccountInfo`, `getMultipleAccounts`, `getTokenAccountsByOwner`; protocol-specific account decoding per IDL | Category A1 (primary), Category B implied rate reads, Category C (decomposition), Category D balance reads |
| On-Chain Oracles | Chainlink, Pyth Network, Redstone, reputable oracle providers | Category A2 (primary, tier 1), Category E non-USDC-pegged stablecoins |
| Issuer-Published NAV / API | Midas (mF-ONE, mHYPER), Superstate (USCC), OnRe (ONyc), BlackRock (BUIDL), Ondo (OUSG / USDY), Backed (bIB01), Mountain (USDM), Maple (syrupUSDC) | Category A2 (primary, tier 2) |
| Market Data Aggregators | CoinGecko, DefiLlama | Category F governance token pricing (tier 2) |
| Centralised Exchange Prices | Kraken | All assets held at Kraken (primary, per Final Terms), Category F governance tokens (tier 1, if listed), Category E de-peg pricing |
| Protocol AMMs | Pendle AMM, Exponent Finance markets, Curve pools, DEX TWAP | Category B cross-reference, Category F YT and governance token pricing (tier 3) |
| Verification Sources | DeBank (EVM chains only), Octav (paid subscription, broader coverage) | Independent cross-referencing per Section 7 |
| Fallback Source | ForDefi portfolio valuation engine | Fallback when Primary and Verification Sources are unavailable, per Section 8 |
| ECB Reference Rates | ECB published exchange rates | Category E fiat currency conversion |
| Contractual Documentation | Loan agreements, term sheets, interest rate confirmation from vault operators | Category A3 (primary) |

The Calculation Agent may add or remove sources in consultation with the Investment Manager, documented as a Policy amendment per Section 13.

## Appendix B: Divergence Tolerance Thresholds

Maximum acceptable divergence between Primary and Verification Sources before investigation is required per Section 7.

| Asset Category | Tolerance | Rationale |
|----------------|-----------|-----------|
| A1: On-Chain Yield-Bearing | 2% | Deterministic smart contract state, but timing differences and accrued investment treatment between sources may cause minor divergence |
| A2: Off-Chain Yield-Bearing | 3% | Oracle and issuer NAV update frequency vary; Verification Sources may use different pricing methods (e.g. DEX price vs oracle) |
| A3: Private Credit Vault | 5% | Manual accrual methodology with limited independent verification; Verification Sources may not capture these positions or may reference a lagging on-chain tranche price |
| B: PT Tokens | 6% | Linear amortisation model structurally diverges from secondary market pricing, particularly as maturity approaches and AMM implied rates compress |
| C: LP Positions | 5% | Decomposition methodologies differ between sources; constituent pricing, fee accrual, and PT component treatment may vary |
| D: Leveraged Positions (net) | 5% | Net value is the difference between two larger numbers; small percentage differences in collateral or debt pricing amplify in net calculations |
| E: Stablecoins & Cash | 0.5% | Should be at or near par; divergence beyond this threshold triggers the de-peg provision in Section 9.4 |
| F: Other / Bespoke | 10% | Illiquid, complex or incidentally acquired positions; Verification Sources may not capture them at all or may use fundamentally different pricing methods |

Thresholds may be adjusted by mutual agreement between the Calculation Agent and Investment Manager, documented per Section 13.

## Appendix C: Version History

| Version | Date | Description | Approved By |
|---------|------|-------------|-------------|
| 1.0 | 1 April 2026 | Initial version | [Calculation Agent / Investment Manager] |

All amendments shall be recorded in this table per Section 13.3, including the date of written agreement, a brief description of the changes, and the approving parties.

---

*End of Document*
