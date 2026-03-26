# FalconX / Pareto — Position Collection Flow

## Overview

This position produces two sheets in `outputs/falconx_position.xlsx`:
- **Gauntlet_LeveredX**: Veris's indirect exposure via the Gauntlet vault (gpAAFalconX shares)
- **Direct Accrual**: Veris's direct holding of AA_FalconXUSDC tokens (in wallet or as Morpho collateral)

The values in **"Veris share"** (Gauntlet_LeveredX col R) and **"Running Balance (USD)"** (Direct Accrual col H) are the NAV figures.

---

## Execution Flow

### Step 0 — Determine what to update

Read the last row of each sheet. If a sheet has data, the last timestamp is the cut-off. Only query and append rows **after** the cut-off. Do NOT re-query from inception.

### Step 1 — Check current balances

Query at the current block (or target valuation block):

| Query                            | Contract                  | Function                                      | Purpose                      |
|----------------------------------|---------------------------|-----------------------------------------------|------------------------------|
| gpAAFalconX balance              | Gauntlet `0x0000...aF44`  | `balanceOf(veris_wallet)`                     | Veris shares in Gauntlet     |
| gpAAFalconX total supply         | Gauntlet                  | `totalSupply()`                               | For Veris % calculation      |
| AA_FalconXUSDC in wallet         | AA tranche `0xC26A...`    | `balanceOf(veris_wallet)`                     | Direct holding               |
| AA_FalconXUSDC as Morpho coll.   | Morpho Core `0xBBBB...`   | `position(AA_USDC_market_id, veris_wallet)`   | Direct Morpho position       |
| Gauntlet Morpho position        | Morpho Core               | `position(market_id, gauntlet_vault)`         | Vault collateral + borrow    |
| Morpho market state             | Morpho Core               | `market(market_id)`                           | Convert borrow shares → USDC |
| Tranche price                   | Pareto vault `0x433d...`  | `tranchePrice(AA_tranche)`                    | Current TP                   |

### Step 2 — Determine which sheets are active

- **Gauntlet_LeveredX** is active when `balanceOf(veris_wallet)` on Gauntlet vault > 0
- **Direct Accrual** is active when `balanceOf(veris_wallet)` on AA tranche > 0 OR `position(AA_USDC_market, veris_wallet).collateral` > 0

If a sheet was active and balance drops to zero → stop appending rows.
If a sheet was inactive and balance becomes non-zero → start appending rows (new section).

### Step 3 — Check for deposits/withdrawals since last cut-off

Query Etherscan for ERC-20 transfers of:
- **gpAAFalconX** to/from `veris_wallet` (Gauntlet deposits/withdrawals)
- **AA_FalconXUSDC** to/from `veris_wallet` (direct deposits/withdrawals)

Any new deposit increases the **Opening Value (USD)** at the deposit timestamp:
```
Additional deposit (USDC) = delta_tokens × tranche_price_at_deposit_block
```

Any withdrawal reduces the position proportionally.

### Step 4 — Get applicable net rate

Look up the loan notice for the current period from `docs/reference/loans/`.

```
Net rate = Gross rate × 0.90
```

Rate changes at the loan notice period boundary (not at the TP update date). The gross rate can be verified on-chain via `lastEpochApr()` on the Pareto vault at the most recent TP update block.

### Step 5 — Check for tranche price updates since last cut-off

Query Etherscan for transactions to the Pareto vault (`0x433d...`) with method `0xb4ecd47f` since the last cut-off block, or simply compare `tranchePrice()` at current block vs last known value.

When a TP update is found:
- Record the new TP in **column J (Tranche Price)** at the exact update timestamp
- The TP remains constant until the next update

**Important**: The TP is updated when the Pareto epoch ends, NOT at the loan notice period boundary. These are different dates.

### Step 6 — Append hourly rows

For each hour from last cut-off to current, make one Multicall3 call batching `position()`, `market()`, `totalSupply()`, and `tranchePrice()`.

#### Gauntlet_LeveredX columns (18 columns):

| Col | Name                         | Source / Formula                                                     |
|-----|------------------------------|----------------------------------------------------------------------|
| A   | Timestamp (UTC)              | Hourly increment                                                     |
| B   | Block                        | Estimated (~300 blocks/hour from prior)                              |
| C   | Collateral (AA_FalconXUSDC)  | Morpho `position()` for Gauntlet vault — collateral field            |
| D   | Borrow (USDC)                | Morpho `position()` borrow shares × `market()` conversion            |
| E   | Vault Total Supply           | Gauntlet `totalSupply()`                                             |
| F   | Veris Balance                | gpAAFalconX balance (update only on deposit/withdrawal)              |
| G   | Veris %                      | `= F / E`                                                           |
| H   | Net Rate (p.a.)              | From loan notice schedule, matched by timestamp                      |
| I   | Veris AA_FalconXUSDC         | Token count (update only on deposit)                                 |
| J   | Tranche Price                | On-chain `tranchePrice()`. Constant between epoch updates.           |
| K   | Period (days)                | `= A_current - A_prior`                                             |
| L   | Opening Value (USD)          | First row: handoff from Direct Accrual. Subsequent: `= N_prior`     |
| M   | Interest                     | `= L × H × K / 365`                                                 |
| N   | Running Balance (USD)        | `= L + M` (+ additional deposits if any)                            |
| O   | TP (re-engineered)           | `= N / I` — accrual-implied per-token price                         |
| P   | Collateral (USD)             | `= C × O` — uses **re-engineered TP**, NOT stale on-chain TP        |
| Q   | Net                          | `= P - D`                                                           |
| R   | Veris share                  | `= Q × G` — **this is the NAV figure**                              |

**Critical**: Column P uses the re-engineered TP (column O), not the stale on-chain TP (column J). This ensures the collateral value reflects continuous interest accrual.

#### Direct Accrual columns (9 columns):

| Col | Name                    | Source / Formula                                                        |
|-----|-------------------------|-------------------------------------------------------------------------|
| A   | Timestamp (UTC)         | Hourly increment                                                        |
| B   | Token Balance           | `balanceOf(veris)` on AA tranche + `position(market, veris).collateral` |
| C   | Tranche Price           | On-chain `tranchePrice()`. Updates when Pareto epoch ends.              |
| D   | Opening Value (USD)     | First row: `B × C`. Subsequent: `= H_prior`                            |
| E   | Net Rate (p.a.)         | From loan notice schedule                                               |
| F   | Period (days)           | `= A_current - A_prior`                                                |
| G   | Interest                | `= D × E × F / 365`                                                    |
| H   | Running Balance (USD)   | `= D + G` — **this is the NAV figure**                                 |
| I   | TP (re-engineered)      | `= H / B`                                                              |

### Step 7 — Verification (post-facto, not at NAV date)

After the next epoch ends and TP updates:
- Call `convertUnitsToToken(vault, USDC, veris_balance)` on PriceFeeCalculator (`0x8F3F...`)
- Compare against column R (Veris share) at the epoch end timestamp
- Divergence should be < 5% (A3 tolerance per Valuation Policy Appendix B)

This verification is logged in the NAV Methodology Report but does NOT change the NAV value.

---

## Data Sources

| Data                              | Source                                             | Frequency                  |
|-----------------------------------|----------------------------------------------------|----------------------------|
| Morpho position (coll, borrow)    | RPC: Multicall3 `position()` + `market()`          | Hourly                     |
| Vault total supply                | RPC: `totalSupply()` on Gauntlet vault             | Hourly                     |
| Tranche price                     | RPC: `tranchePrice()` on Pareto vault              | Hourly (changes ~monthly)  |
| Veris gpAAFalconX balance         | Etherscan transfer events                          | On change only             |
| Veris AA_FalconXUSDC balance      | Etherscan + Morpho `position()` for veris wallet   | On change only             |
| Net rate                          | Loan notices at `docs/reference/loans/`             | Monthly                    |
| Gross rate verification           | RPC: `lastEpochApr()` on Pareto vault              | At epoch end               |
| Verification                      | RPC: `convertUnitsToToken()` on PriceFeeCalculator | Post-facto at epoch end    |

---

## Position Lifecycle

### Period 1: Direct Accrual (Jul 31 – Sep 3 2025)
- Veris held AA_FalconXUSDC directly in wallet
- Accrued at loan notice net rate
- Ended when tokens moved to Gauntlet vault

### Period 2: Gauntlet (Sep 3 2025 – ongoing)
- Veris holds gpAAFalconX shares
- Gauntlet vault holds AA_FalconXUSDC as Morpho collateral, borrows USDC
- Veris share = (collateral × re-engineered TP − debt) × veris %

### Period 3: Direct Accrual revival (Mar 2026)
- Veris supplied AA_FalconXUSDC directly as Morpho collateral (separate from Gauntlet)
- Then withdrew before month end
- Treatment: same Direct Accrual methodology, token balance = wallet balance + Morpho collateral

---

## Incremental Update Logic

```
1. Load falconx_position.xlsx
2. Find last timestamp on each sheet
3. For each sheet:
   a. Check current balance (gpAAFalconX or AA_FalconXUSDC)
   b. If zero and was active → stop (position exited)
   c. If non-zero and was inactive → start new section
   d. If non-zero and was active → continue appending
4. Check Etherscan for deposits/withdrawals since last cut-off
5. Get applicable net rate from loan notice
6. Check if tranche price changed since last cut-off
7. Query hourly on-chain data (Multicall3) from last cut-off to now
8. Append rows with formulas
9. Save
```

---

## File References

| File                                                  | Purpose                                         |
|-------------------------------------------------------|------------------------------------------------|
| `outputs/falconx_position.xlsx`                       | NAV workbook (two sheets)                      |
| `docs/methodology/falconx_accrual_analysis.md`        | Methodology validation & audit evidence        |
| `docs/reference/loans/`                               | Monthly loan notices                           |
| `config/contracts.json` → `_gauntlet_pareto`          | All contract addresses                         |
| `config/abis.json` → `pareto_credit_vault`, `morpho_core`, `erc20` | ABIs                             |
| `src/temp/hourly_data_multicall.py`                   | Initial data collection (to be absorbed into collect.py) |
| `src/temp/append_hourly_data.py`                      | Incremental append (to be absorbed into collect.py) |
