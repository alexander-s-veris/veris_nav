# NAV Output Specification

Two outputs that together form the basis of the NAV Report submitted to the Calculation Agent (Bank Frick). The Calculation Agent must be able to reconstruct every number independently using the data provided.

---

## 1. NAV Snapshot File (CSV and/or JSON)

Consumed by the Excel NAV workbook. One row per position.

Output format per row:
```
timestamp_utc, chain, protocol, wallet, position_type, token, balance_raw, balance_human, price_source, price_usd, value_usd, block_number, tx_or_query_ref, category, notes
```

## 2. NAV Methodology Log

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

---

## NAV Formula (per Section 10 of Valuation Policy)

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

---

## Divergence Tolerance Thresholds (Appendix B of Valuation Policy)

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
