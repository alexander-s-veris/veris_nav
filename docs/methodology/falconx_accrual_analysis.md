# FalconX / Pareto — NAV Valuation Methodology

## Position Summary

Veris holds exposure to the FalconX private credit facility through two paths:

1. **Direct (Jul-Sep 2025)**: Veris wallet `0x0c16` held AA_FalconXUSDC tokens directly
2. **Gauntlet (Sep 2025 onward)**: Veris holds gpAAFalconX shares in the Gauntlet Levered FalconX Vault, which deploys AA_FalconXUSDC as Morpho collateral and borrows USDC (leverage)

**Classification**: Category A3 (private credit). Primary valuation = manual accrual. On-chain tranche price = cross-reference.

**NAV output**: The values in column **"Running Balance (USD)"** on Direct Accrual sheet and column **"Veris share"** on Hourly Data sheet of `outputs/falconx_position.xlsx` are the NAV figures for this position.

---

## Contracts

| Contract                          | Address                                      | ABI Key              |
|-----------------------------------|----------------------------------------------|----------------------|
| Pareto Credit Vault               | `0x433d5b175148da32ffe1e1a37a939e1b7e79be4d` | `pareto_credit_vault`|
| Pareto Implementation             | `0x8016E6f35a4B32a5Ea4c3919418039C7DaffCcaf` | (same via proxy)     |
| AA_FalconXUSDC Tranche Token      | `0xC26A6Fa2C37b38E549a4a1807543801Db684f99C` | `erc20`              |
| Gauntlet Levered FalconX Vault    | `0x00000000d8f3d6c5DFeB2D2b5ED2276095f3aF44` | `erc20`              |
| Morpho Core (Ethereum)            | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` | `morpho_core`        |
| Morpho Market ID                  | `0xe83d72fa5b00dcd46d9e0e860d95aa540d5ec106da5833108a9f826f21f36f52` | — |
| Veris Wallet                      | `0x0c1644d7af63df4a3b15423dbe04a1927c00a4f4` | — |

---

## Loan Notice Schedule

Source: Falcon Labs Ltd monthly loan notices at `docs/reference/loans/`

| Period   | Gross Rate | Net Rate (×0.90) | Start       | End         | Days |
|----------|------------|------------------|-------------|-------------|------|
| Jul 2025 | 11.25%     | 10.125%          | Jun 30      | Jul 31      | 31   |
| Aug 2025 | 11.25%     | 10.125%          | Jul 31      | Sep 1       | 32   |
| Sep 2025 | 12.00%     | 10.800%          | Sep 1       | Sep 30      | 29   |
| Oct 2025 | 12.00%     | 10.800%          | Oct 1       | Oct 31      | 30   |
| Nov 2025 | 12.00%     | 10.800%          | Nov 1       | Nov 30      | 30   |
| Dec 2025 | 11.50%     | 10.350%          | Dec 1       | Dec 31      | 30   |
| Jan 2026 | 10.50%     | 9.450%           | Jan 1       | Jan 31      | 31   |
| Feb 2026 | 10.00%     | 9.000%           | Feb 1       | Mar 3       | 30   |
| Mar 2026 | 9.25%      | 8.325%           | Mar 3       | Apr 1       | 29   |
| Apr 2026 | (pending)  | (pending)        | Apr 1       | (pending)   | —    |

**Net rate** = Gross rate × 0.90 (10% pool-level performance fee deducted before tranche price update).

The gross rate is also available on-chain via `lastEpochApr()` on the Pareto Credit Vault contract, queried at each tranche price update block.

---

## Tranche Price History

Source: `src/temp/query_pareto_tranche_history.py` → `outputs/pareto_tranche_price_history.json`

| TP Update Date (UTC)  | Block    | TP       | Epoch End (UTC)          | Last Epoch APR | Last Epoch Interest | Contract Value   |
|-----------------------|----------|----------|--------------------------|----------------|---------------------|------------------|
| 2025-06-18 14:48:11   | 22732061 | 1.000000 | 2025-06-13 14:48:11      | 0%             | $0                  | $0               |
| 2025-07-31 13:25:35   | 23039369 | 1.005784 | 2025-07-31 06:35:46      | 11.25%         | $57,853             | $10,058,846      |
| 2025-09-03 15:36:47   | 23283522 | 1.014729 | 2025-09-01 14:46:11      | 11.25%         | $125,491            | $14,235,063      |
| 2025-09-30 15:17:11   | 23476643 | 1.023747 | 2025-09-30 12:11:11      | 13.66%         | $342,148            | $38,842,241      |
| 2025-10-31 09:02:59   | 23696317 | 1.033092 | 2025-10-31 08:49:59      | 12.00%         | $345,705            | $38,217,771      |
| 2025-12-01 12:54:11   | 23918757 | 1.042583 | 2025-12-01 12:45:47      | 12.00%         | $459,113            | $50,431,143      |
| 2026-01-02 15:39:59   | 24147904 | 1.052037 | 2026-01-02 12:21:23      | 11.50%         | $553,519            | $61,592,368      |
| 2026-01-30 09:07:11   | 24346680 | 1.059607 | 2026-01-30 08:29:23      | 10.50%         | $620,125            | $86,809,084      |
| 2026-03-03 15:11:23   | 24577738 | 1.067961 | 2026-03-03 12:51:11      | 10.00%         | $819,452            | $106,205,903     |

Contract Value, Last Epoch APR, Last Epoch Interest, and Epoch End Date are queried from the Pareto Credit Vault at each TP update block using `getContractValue()`, `lastEpochApr()`, `lastEpochInterest()`, and `epochEndDate()`.

---

## Veris Investment History

| Date                  | Event                                       | AA_FalconXUSDC Tokens | gpAAFalconX Shares |
|-----------------------|---------------------------------------------|-----------------------|--------------------|
| 2025-07-31 15:03:59   | First USDC deployed to Pareto (direct)       | +1,988,498.5245       | —                  |
| 2025-09-03 17:56:35   | Received gpAAFalconX shares                  | —                     | +2,017,888.0087    |
| 2025-09-03 18:54:35   | Gauntlet first supply to Morpho              | —                     | —                  |
| 2025-10-31 09:33:35   | Additional AA_FalconXUSDC (tx `0x48d1...`)   | +484,570.3014         | —                  |
| 2025-10-31 ~15:44     | Additional gpAAFalconX shares                | —                     | +489,226.7758      |
| 2026-03-06 12:06:35   | Period 3: received AA_FalconXUSDC (28.07)    | +28.0739              | —                  |
| 2026-03-06 12:26:11   | Period 3: received AA_FalconXUSDC (main)     | +1,894,941.7856       | —                  |
| 2026-03-06 12:48:35   | Supplied to Morpho as collateral             | (→ Morpho)            | —                  |
| 2026-03-22 18:10:59   | Withdrew from Morpho to wallet               | (← Morpho)            | —                  |

Veris gpAAFalconX balance: **2,017,888.0087** (Sep 3 – Oct 31), then **2,507,114.7845** (Oct 31 onward, constant through Mar 2026).

Veris AA_FalconXUSDC tokens (for Gauntlet column I): **1,988,498.5245** (Sep 3 – Oct 31 09:33), then **2,473,068.8259** (Oct 31 09:34 onward).

Veris AA_FalconXUSDC tokens (Direct Accrual Period 3): **1,894,969.8595** (Mar 6 onward). Deposited $2,024,989.23 USDC total (effective deposit TP = 1.068613, higher than stale on-chain TP of 1.067961 due to ~3 days of accrued interest since last epoch end).

---

## Accrual Formula

```
Interest = Opening_Value × Net_Rate × Days / 365
Net_Rate = Gross_Rate × 0.90
```

Verified against on-chain tranche price updates: < 0.1% divergence in clean periods (no collateral changes, TP update aligns with accrual period).

## Key Assumptions

1. **Net rate = Gross rate × 0.90**: Pool-level performance fee ~10%. Verified by comparing accrual vs successive tranche price updates across 8 epochs.
2. **Interest accrues continuously** on the running balance. Deposits add to the base at **actual USDC deposited**, not at the stale on-chain tranche price. The effective deposit TP (= USDC / tokens) is more accurate because the on-chain TP is only updated at epoch end (~monthly) and does not reflect interest accrued since the last update.
3. **Tranche price** updates ~monthly (31-day vault cycle via `epochDuration()`). Between updates, on-chain TP is stale — the accrual captures interest that the TP has not yet reflected.
4. **Morpho borrow interest** accrues continuously on-chain, reducing the Gauntlet vault net position between epochs.
5. **Cross-reference** (`convertUnitsToToken` on PriceFeeCalculator) is valid only at epoch end, NOT at NAV date. It serves as post-facto verification that the accrual was correct.
6. **Collateral valuation** uses the re-engineered tranche price from accrual (= Running Balance / token count), not the stale on-chain TP.

## Tranche Price Verification Results

For each loan notice period: expected TP = `Open_TP × (1 + Gross_Rate × 0.90 × Days / 365)`, compared to actual next TP update.

| Notice   | Rate   | Days | Open TP  | Expected TP | Actual TP | Diff %  |
|----------|--------|------|----------|-------------|-----------|---------|
| Aug 2025 | 11.25% | 32   | 1.005784 | 1.014712    | 1.014729  | +0.002% |
| Sep 2025 | 12.00% | 29   | 1.014729 | 1.023436    | 1.023747  | +0.031% |
| Oct 2025 | 12.00% | 30   | 1.023747 | 1.032835    | 1.033092  | +0.025% |
| Nov 2025 | 12.00% | 30   | 1.033092 | 1.042262    | 1.042583  | +0.031% |
| Dec 2025 | 11.50% | 30   | 1.042583 | 1.051452    | 1.052037  | +0.056% |
| Jan 2026 | 10.50% | 31   | 1.052037 | 1.060481    | 1.059607  | -0.083% |
| Feb 2026 | 10.00% | 30   | 1.059607 | 1.067445    | 1.067961  | +0.049% |
| Mar 2026 | 9.25%  | 29   | 1.067961 | (pending)   | (pending) | —       |

All within 0.1% except Jan (-0.083%, TP update on Jan 30 before period end) and Dec (+0.056%, TP update on Jan 2 covers extra days).

---

## Related Files

| File                                                  | Purpose                                         |
|-------------------------------------------------------|------------------------------------------------|
| `outputs/falconx_position.xlsx`                       | NAV workbook (Gauntlet_LeveredX + Direct Accrual) |
| `outputs/pareto_tranche_price_history.json`           | All TP updates with on-chain epoch metadata     |
| `docs/reference/loans/`                               | Monthly loan notices (PNG/PDF)                  |
| `plans/falconx_position_flow.md`                      | Position calculation flow & incremental update spec |
| `plans/output_schema_plan.md`                         | How A3 positions feed into the NAV output       |
