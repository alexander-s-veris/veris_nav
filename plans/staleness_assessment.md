# Staleness Assessment Plan

## Policy Requirement

Per Valuation Policy Section 6.2 and CLAUDE.md:
- A2 tokens: flag if price source not updated for >2× the expected update interval
- If primary source is stale, use next available source and note in NAV report
- The Investment Manager must maintain a record of expected update frequency per A2 token
- Category E de-peg: >0.5% deviation from par triggers market pricing; >2% triggers investor notification

## Staleness Criteria by Token

### Category A2 — Off-chain yield-bearing tokens

| Token | Source | Expected Update Freq | Stale Threshold (2×) | Observed Pattern | Notes |
|-------|--------|---------------------|---------------------|-----------------|-------|
| **mF-ONE** | Midas Chainlink oracle (`0x8D51...`) | ~24h (daily) | 48h | Round IDs increment daily; UpdatedAt shows 1-2 day gaps | Observed rounds 167-173 from 12-20 Mar, ~daily updates |
| **msyrupUSDp** | Midas Chainlink oracle (`0x337d...`) | ~168h (weekly) | 336h (14 days) | Weekly NAV updates per Midas schedule | Per memory note from previous session |
| **mHYPER** | Midas Chainlink oracle on Plasma (`0xfC3E...`) | ~168h (weekly) | 336h (14 days) | Same Midas update cadence as msyrupUSDp | Small position (~$726) |
| **USCC** | Pyth feed (primary), Chainlink NAVLink (cross-ref) | ~24h (daily) | 48h | Superstate publishes daily NAV | Cross-ref: `uscc-nav.data.eth` |
| **syrupUSDC** | Pyth feed (primary), CoinGecko (fallback) | ~24h (daily) | 48h | Maple updates daily; Pyth aggregates from market | Present on Ethereum, Arbitrum, Base, Solana |
| **ONyc** | Pyth feed | ~168h (weekly) | 336h (14 days) | OnRe publishes weekly NAV updates | Solana only |

### Category A3 — Private credit (on-chain cross-reference staleness)

A3 primary valuation is manual accrual — the on-chain price is cross-reference only. But staleness of the cross-reference should still be flagged.

| Token | Source | Expected Update Freq | Stale Threshold | Observed Pattern | Notes |
|-------|--------|---------------------|-----------------|-----------------|-------|
| **AA_FalconXUSDC** (Pareto tranche) | `tranchePrice()` on `0x433d...` | ~31 days (epoch cycle) | 45 days | 9 updates since Jun 2025. Update method: `0xb4ecd47f`. Epoch end date available on-chain via `epochEndDate()`. | See below and `outputs/pareto_tranche_price_history.json` |
| **gpAAFalconX** (Gauntlet vault) | balanceOf/totalSupply | Real-time (on-chain) | N/A | Share count changes only on deposits/withdrawals | Veris % changes when other investors deposit/withdraw |
| **CreditCoop vault** | `convertToAssets()` on `0xb21e...` | Real-time (on-chain) | N/A | ERC-4626 exchange rate updates with each state change | Cross-reference only |

### Category A1 — On-chain yield-bearing (no staleness concern)

A1 tokens use deterministic smart contract exchange rates (`convertToAssets`). These are computed on-chain at query time — no external update dependency, so staleness does not apply.

Tokens: sUSDe, bbqSUDCreservoir, steakUSDT, avUSDC, esyrupUSDC, aBassyrupUSDC, CSUSDC, Yearn yvvbUSDC.

### Category E — Stablecoins (de-peg monitoring, not staleness)

| Token | Method | Check | Threshold |
|-------|--------|-------|-----------|
| USDC | Par ($1.00) | Chainlink USDC/USD feed `0x8fFf...` | ±0.5% from par |
| DAI | Par ($1.00) | Chainlink DAI/USD feed `0xAed0...` | ±0.5% from par |
| PYUSD | Par ($1.00) | No Chainlink feed registered | ±0.5% from par |
| USDT | Chainlink oracle | Chainlink USDT/USD feed `0x3E7d...` | ±0.5% from $1.00 |
| USX | Par ($1.00) | Pyth feed | ±0.5% from par |
| AUSD | Par ($1.00) | No feed registered | ±0.5% from par |
| RLUSD | Oracle price | Pyth/CoinGecko | ±0.5% from $1.00 |
| USDe | Chainlink oracle | Chainlink on Plasma, Pyth on Ethereum | ±0.5% from $1.00 |

**De-peg rules:**
- Minor (0.5–2%): Price at actual traded value, note in NAV report
- Material (>2%): Price at actual traded value, notify investors within 2 business days
- For debt in leveraged positions: de-pegged stablecoin debt valued at de-pegged price

### Category F — Governance tokens / Other

F tokens use market prices (Kraken → CoinGecko → DEX TWAP). Staleness applies to the price source:

| Source | Expected Freshness | Stale Threshold |
|--------|-------------------|-----------------|
| Kraken | Real-time (market) | N/A — always fresh if listed |
| CoinGecko | Aggregated, ~5min delay | Flag if >1h stale |
| DEX TWAP | On-chain, block-level | N/A |

### Pareto Tranche Price — Historical Update Pattern

Full history (9 updates since inception):

| Date | Price | Period Change | Days Since Prior | Ann. Rate (from inception) |
|------|-------|--------------|-----------------|---------------------------|
| 2025-06-18 | 1.000000 | — | — | — |
| 2025-07-31 | 1.005784 | +0.005784 | 43 | 5.03% |
| 2025-09-03 | 1.014729 | +0.008945 | 34 | 6.98% |
| 2025-09-30 | 1.023747 | +0.009018 | 27 | 8.33% |
| 2025-10-31 | 1.033092 | +0.009345 | 31 | 9.01% |
| 2025-12-01 | 1.042583 | +0.009491 | 31 | 9.42% |
| 2026-01-02 | 1.052037 | +0.009454 | 32 | 9.59% |
| 2026-01-30 | 1.059607 | +0.007570 | 28 | 9.67% |
| 2026-03-03 | 1.067961 | +0.008354 | 32 | 9.61% |

**Pattern**: ~31-day vault cycle (epoch duration ~2,468,880 seconds). Updates happen when `stopEpoch()` is called after the epoch ends. There is a 6-hour buffer period (`bufferPeriod` = 21,600 sec) after the scheduled `epochEndDate` during which the update transaction is submitted.

**On-chain staleness detection**:
- `epochEndDate()` on Pareto vault (`0x433d...`) returns the scheduled end of the current epoch as a Unix timestamp
- If `block.timestamp > epochEndDate + bufferPeriod` and `isEpochRunning()` is still True → the update is late
- `lastEpochApr()` gives the gross rate of the last completed epoch (should match loan notice)
- `lastEpochInterest()` gives the actual interest distributed at last update
- `getContractValue()` gives the total pool value (should match loan notice aggregate principal)

**Staleness threshold**: 45 days since last `tranchePrice()` change → flag for investigation.

**How to detect updates**: Either query Etherscan for txs to `0x433d...` with method `0xb4ecd47f`, or simply compare `tranchePrice()` at current block vs prior known value.

**Query method for full history**: `src/temp/query_pareto_tranche_history.py` → `outputs/pareto_tranche_price_history.json`.

## Implementation

When building the staleness checker in `src/valuation.py`:

1. Add `expected_update_freq_hours` field to each A2 token in `config/tokens.json`
2. For Chainlink-style oracles: use `updatedAt` from `latestRoundData()` and compare to valuation block timestamp
3. For Pyth: use `publishTime` from the price update and compare
4. For Pareto tranche: track days since last price change (requires historical query or cached history)
5. For Category E de-peg: compare oracle price to $1.00, flag if >0.5% deviation
6. Log staleness status per position in the NAV methodology report (Section 5 — Flags & Exceptions)
