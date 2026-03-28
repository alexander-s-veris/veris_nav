# Output Schema Plan for Veris NAV Data Collection

## Context

The system currently has `collect_balances.py` covering wallet-level token balances (Categories E and F, plus some A1/A2 tokens held in wallets). The next step is collecting protocol-level positions (A1 vaults, A2 oracle-priced tokens, A3 private credit accruals, B PT lot amortisation, C LP decomposition, D leveraged positions). After analysing the existing Excel workbook, we need an output schema that:
- Replaces the spreadsheet's Power Queries and manual calc sheets with a single automated pipeline
- Produces audit-ready output for Bank Frick (Calculation Agent) and Grant Thornton (Auditor)
- Supports historical snapshots (one folder per Valuation Date)
- Handles the structural differences between categories (leveraged positions need collateral+debt rows, LPs need constituent rows, PTs need per-lot rows, A3 needs accrual+cross-reference)

## File Structure

Each run creates a date-stamped folder. Existing `wallet_balances.*` files remain for standalone balance checks.

```
outputs/
  nav_20260430/
    positions.json          # Master snapshot with _methodology header
    positions.csv           # Flat CSV of all positions
    query_log.json          # Every on-chain/API call with raw results
    query_log.csv           # Same, flat
    nav_summary.json        # Aggregation, fees, verification, flags
    pt_lots.csv             # Category B individual lot amortisation detail
    a3_accruals.csv         # Category A3 private credit accrual detail
    lp_decomposition.csv    # Category C LP constituent breakdown
    leverage_detail.csv     # Category D collateral/debt pairs
  wallet_balances.json      # Existing (standalone balance scanner)
  wallet_balances.csv       # Existing
```

## Master Position Schema (positions.csv / positions.json)

One row per valued position. All categories share common columns. Category-specific columns are empty/null when not applicable.

### Common Columns (all rows)

- `position_id` — unique key, format: `{chain}_{protocol}_{wallet_short}_{token}_{category}_{qualifier}`
- `valuation_date` — dd/mm/yyyy
- `timestamp_utc` — block timestamp, dd/mm/yyyy hh:mm:ss
- `chain` — ethereum, arbitrum, base, avalanche, plasma, hyperevm, solana
- `protocol` — morpho, kamino, exponent, aave, fluid, credit_coop, pareto, wallet, etc.
- `wallet` — full address
- `position_label` — human-readable name (e.g. "Morpho syrupUSDC/USDT")
- `category` — A1, A2, A3, B, C, D, E, F
- `position_type` — token_balance, vault_share, oracle_priced, manual_accrual, pt_lot, lp_position, lp_constituent, collateral, debt, reward
- `token_symbol` — token ticker
- `token_name` — full name
- `token_contract` — contract address or mint
- `balance_raw` — raw on-chain value (uint256 string)
- `balance_human` — scaled balance (Decimal string)
- `price_usd` — Decimal string
- `price_source` — par, chainlink, pyth, kraken, coingecko, a1_exchange_rate, manual_accrual, linear_amortisation
- `price_source_detail` — specific feed/contract/endpoint
- `oracle_updated_at` — timestamp of oracle data point (or null)
- `value_usd` — balance_human x price_usd (Decimal string)
- `block_number` — block/slot used
- `block_timestamp_utc` — dd/mm/yyyy hh:mm:ss
- `depeg_flag` — none, minor_X.XX%, material_X.XX%
- `staleness_flag` — ok, stale_Xh
- `methodology_ref` — Valuation Policy section reference
- `notes` — free text
- `run_timestamp_cet` — script execution time

### Category-Specific Columns

**A1 (vault shares)**: `exchange_rate`, `exchange_rate_contract`, `exchange_rate_function`, `underlying_token`, `underlying_price_usd`

**A2 (oracle-priced)**: `cross_ref_price_usd`, `cross_ref_source`, `cross_ref_divergence_pct`, `expected_update_freq_hours`

**A3 (private credit)**: `accrual_principal`, `accrual_rate_pct`, `accrual_start_date`, `accrual_end_date`, `accrued_interest_usd`, `cross_ref_price_usd`, `cross_ref_source`, `cross_ref_divergence_pct`

**B (PT lots)**: `pt_lot_id`, `pt_purchase_date`, `pt_implied_rate`, `pt_maturity_date`, `pt_days_to_maturity`, `pt_amortised_value`, `underlying_token`, `underlying_price_usd`, `cross_ref_price_usd`, `cross_ref_source`, `cross_ref_divergence_pct`

**C (LP)**: `lp_pool_address`, `lp_total_shares`, `lp_constituent_index`, `lp_constituent_token`, `lp_constituent_amount`, `lp_implied_rate`, `underlying_token`, `underlying_price_usd`

**D (leverage)**: `leverage_market_id`, `leverage_side` (collateral/debt), `leverage_counterpart_token`, `leverage_net_value_usd`

**Linking**: `parent_position_id` — links debt to collateral, LP constituent to LP parent, PT lot to PT aggregate

### How Each Category Appears

- **A1**: One row per vault position. `position_type = vault_share`. Exchange rate from `convertToAssets` or protocol-specific function.
- **A2**: One row per token. `position_type = oracle_priced`. Primary price from oracle hierarchy, cross-reference against issuer NAV where available.
- **A3**: One row per position. `position_type = manual_accrual`. Value is read from the position's supporting workbook at the valuation timestamp (see A3 flow below). Cross-reference is post-facto only (verified at next on-chain price update, not at NAV date).
- **B**: One row per lot. `position_type = pt_lot`. Formula: `underlying_price / (1 + implied_rate * days_to_maturity / 365)`. AMM price as cross-reference only. Lots linked via `parent_position_id` to an aggregate row.
- **C**: One parent row (`position_type = lp_position`) with total value, plus one row per constituent (`position_type = lp_constituent`). PT constituents in yield-splitting LPs use Exponent formula with `last_ln_implied_rate`, not linear amortisation.
- **D**: Two rows per position: `position_type = collateral` (positive value) and `position_type = debt` (negative value). Collateral row carries `leverage_net_value_usd`. Both linked via `parent_position_id`.
- **E/F**: One row per holding. `position_type = token_balance` or `reward`. Same as current `collect_balances.py` output, extended with the new common columns.

## Query Audit Log (query_log.csv / query_log.json)

Every on-chain call and API request, in execution order.

Columns: `query_id`, `timestamp_utc`, `chain`, `query_type` (rpc_call/rest_api/contract_call/computation), `target` (contract address or URL), `method` (function name), `params` (JSON string), `block_number`, `raw_result` (truncated to 500 chars), `decoded_result`, `used_for` (position_id), `notes`

## NAV Summary (nav_summary.json)

Single JSON with:
- `valuation_blocks` — block number and timestamp per chain
- `by_category` — count and value per category (with collateral/debt/net breakdown for D)
- `by_wallet` — count and value per wallet
- `by_custodian` — ForDefi, Kraken, Bank Frick
- `total_assets_usd` — aggregate pre-fee value
- `fees` — management, administration, service, performance, extra NAV (pro-rated)
- `nav_calculation` — total assets, total fees, net assets, outstanding products, NAV per product
- `flags` — stale prices, depeg events, special valuation triggers, judgement exercised
- `verification` — DeBank/Octav totals, divergence %, missing positions

## Supplementary Detail CSVs

These provide deeper breakdowns consumed by the corresponding Excel calc sheets:

- **pt_lots.csv**: lot_id, token_symbol, chain, protocol, purchase_date, purchase_price, implied_rate, maturity_date, underlying_token, underlying_price_usd, quantity, days_total, days_elapsed, days_to_maturity, amortised_price_per_unit, value_usd, amm_cross_ref_price, amm_divergence_pct
- **a3_accruals.csv**: position_id, vault_name, protocol, wallet, rate_pct, rate_period_start, rate_period_end, days_in_period, accrued_interest_usd, total_value_usd, supporting_workbook, supporting_sheet, supporting_column, impairment_flag, notes
- **lp_decomposition.csv**: parent_position_id, lp_name, pool_address, total_lp_shares, constituent_index, constituent_token, constituent_category, constituent_amount, constituent_price_usd, constituent_value_usd, constituent_price_source, lp_implied_rate, accrued_fees_usd
- **leverage_detail.csv**: parent_position_id, protocol, market_id, wallet, chain, side, token_symbol, token_category, balance_human, price_usd, price_source, value_usd, accrued_interest_usd, net_value_usd

## Config Extensions Needed

### config/a3_positions.json (new)
Maps each A3 position to its supporting workbook, accrual methodology, and on-chain query details:
```json
{
  "falconx_gauntlet": {
    "workbook": "outputs/falconx_position.xlsx",
    "sheet": "Gauntlet_LeveredX",
    "nav_column": "Veris share",
    "methodology": "plans/falconx_position_flow.md",
    "rate_source": "docs/reference/loans/",
    "rate_net_factor": 0.90,
    "on_chain_queries": {
      "morpho_position": {"contract": "morpho_core", "market_id": "0xe83d..."},
      "vault_share": {"contract": "erc20", "address": "0x0000...aF44"},
      "tranche_price": {"contract": "pareto_credit_vault", "address": "0x433d..."}
    },
    "verification": {
      "method": "convertUnitsToToken on PriceFeeCalculator (0x8F3F...)",
      "timing": "post-facto at next epoch end, NOT at NAV date"
    }
  },
  "falconx_direct": {
    "workbook": "outputs/falconx_position.xlsx",
    "sheet": "Direct Accrual",
    "nav_column": "Running Balance (USD)",
    "methodology": "plans/falconx_position_flow.md",
    "on_chain_queries": {
      "balance": "balanceOf(veris) on AA_FalconXUSDC + position(market, veris).collateral on Morpho"
    }
  }
}
```
Other A3 positions (CreditCoop, Giza, Resolv) will follow a similar pattern — each with its own supporting workbook, rate source, and on-chain queries.

### config/protocol_positions.json (new)
Maps wallets to protocol positions for D and C categories: protocol name, chain, wallet, market/pool ID, collateral/debt tokens, query method.

### config/pt_lots.json (extend existing)
Populate the empty `lots` arrays with per-lot data: purchase_date, quantity, implied_rate, tx_ref.

### config/contracts.json — DONE
Already restructured by chain and protocol, with ABI references. Includes Morpho markets in `config/morpho_markets.json`.

### config/abis.json — DONE
All ABIs centralised: erc20, erc4626, morpho_core, chainlink, aave_pool, pareto_credit_vault, ethena_cooldown, credit_coop_vault.

## Integration with Existing Code

### Performance infrastructure — DONE

`src/block_utils.py` provides two optimizations used across all collection scripts:

1. **`estimate_blocks()`** — Pre-compute block numbers from a single (block, timestamp) reference. Eliminates iterative block-finding RPC calls. Accuracy: ±25 min at 100h distance, ±36s near reference. For the Valuation Block (exact alignment required), use `refine_block()`.

2. **`concurrent_query()` / `concurrent_query_batched()`** — ThreadPoolExecutor-based concurrent RPC. 10 workers optimal for Alchemy (~22 queries/s, 10.6x faster than serial). No new dependencies (stdlib `concurrent.futures`).

| Script | Optimization | Status |
|--------|-------------|--------|
| `collect_balances.py` | Concurrent chain scanning + parallel wallets within each chain | DONE |
| `pricing.py` | CoinGecko batch API (N tokens in 1 call) + concurrent oracle queries | DONE |
| `update_falconx_optimized.py` | Block pre-computation + concurrent Multicall | DONE |
| `collect.py` (planned) | Will use both for protocol position queries | Planned |

### Chain balance methods (`config/chains.json`)

Each chain has a `token_balance_method` that determines how `collect_balances.py` queries balances:

| Method | Chains | How it works |
|--------|--------|-------------|
| (default/none) | Ethereum, Arbitrum, Base, Avalanche, HyperEVM | Alchemy `alchemy_getTokenBalances` + direct `balanceOf` fallback |
| `etherscan_v2` | Plasma | Etherscan V2 API `addresstokenbalance` endpoint |
| `balance_of` | Katana | Direct `balanceOf` per registry token (no Alchemy) |

### Module changes

1. **collect_balances.py** — DONE: Production wallet balance scanner. Two-level concurrency (chains + wallets). ~45s standalone, ~80s when called from collect.py.

2. **pricing.py** — DONE: Chainlink (multi-chain), Pyth, Kraken, CoinGecko, par+depeg, Curve virtual_price, sUSDe convertToAssets. Still needed: staleness checking for A2 tokens.

3. **evm.py** + **block_utils.py** — DONE: Block estimation, refinement, concurrent queries. ABIs loaded from config/abis.json in protocol_queries.py.

4. **New files** — ALL IMPLEMENTED:
   - `src/collect.py` — Production orchestrator. Parallel Steps 1+2, deduplication, valuation, 6 output files. ~95s.
   - `src/protocol_queries.py` — Config-driven queries for all protocols (Morpho, ERC-4626, Euler, Aave, Midas, FalconX, CreditCoop, Kamino, Exponent, Uniswap V4, Ethena cooldowns).
   - `src/valuation.py` — Category-specific: value_position() dispatches to _value_a1 through _value_ef. A3 reads from falconx_position.xlsx.
   - `src/output.py` — Writes positions.csv/json, leverage_detail.csv, pt_lots.csv, lp_decomposition.csv, nav_summary.json.
   - `src/pt_valuation.py` — PT lot discovery + linear amortisation (Category B).
   - `src/solana_client.py` — Kamino obligation parsing, Exponent market/LP/YT, eUSX exchange rate.

5. **Deduplication rule**: IMPLEMENTED in collect.py. Protocol positions override wallet token balances by (chain, wallet, token_contract) key.

5. **Deduplication rule**: tokens appearing in both wallet balances AND protocol positions get the protocol-level row (richer metadata). E.g., USCC held as Kamino collateral appears as a D-collateral row, not an E token_balance row.

## A3 Position Flow (Category-Specific)

A3 positions differ from all others: they require a **supporting workbook** with continuous accrual calculations, not just a point-in-time query.

### collect.py flow for A3:

```
1. Read config/a3_positions.json → get workbook path, sheet, NAV column
2. Open the supporting workbook (e.g. outputs/falconx_position.xlsx)
3. Check if data covers the valuation date:
   a. If yes → read the NAV value at the valuation timestamp
   b. If no → append hourly rows from last timestamp to valuation date:
      - Query on-chain data (Multicall3) per docs/internal/protocol_sourcing.md
      - Apply loan notice net rate for interest calculation
      - Detect deposits/withdrawals via Etherscan
      - Write formula-based rows
4. Read the NAV column value at the valuation row
5. Write ONE row to positions.csv with:
   - value_usd = NAV column value
   - price_source = manual_accrual
   - accrual_rate_pct = current net rate
   - No cross_ref at NAV date (stale mid-epoch)
6. Write detail to a3_accruals.csv with supporting workbook reference
```

### Cross-reference (post-facto, NOT at NAV date):

A3 cross-reference is verified AFTER the NAV date, when the next on-chain price update occurs:
- For FalconX: `convertUnitsToToken()` on PriceFeeCalculator at the next epoch end
- For CreditCoop: `convertToAssets()` on the vault at any time (real-time)
- Divergence threshold: 5% (Appendix B)

This verification is logged in the NAV Methodology Report but does NOT change the NAV value.

### Supporting workbooks by position:

| Position             | Workbook                        | Sheet              | NAV Column          | Methodology                        |
|----------------------|---------------------------------|--------------------|---------------------|------------------------------------|
| FalconX (Gauntlet)   | `outputs/falconx_position.xlsx` | Gauntlet_LeveredX  | Veris share         | `plans/falconx_position_flow.md`   |
| FalconX (Direct)     | `outputs/falconx_position.xlsx` | Direct Accrual     | Running Balance     | `plans/falconx_position_flow.md`   |
| CreditCoop           | TBD                             | TBD                | TBD                 | TBD                                |
| Giza                 | TBD                             | TBD                | TBD                 | TBD                                |
| Resolv               | TBD                             | TBD                | TBD                 | TBD                                |

## Verification

After implementation, test by:
1. Run `collect.py` with a specific valuation date (use a recent past date)
2. Verify all output files are created in `outputs/nav_YYYYMMDD/`
3. Check `positions.csv` imports cleanly into Excel
4. Cross-reference D positions: collateral value - debt value = leverage_net_value_usd
5. Cross-reference B positions: manual amortisation calculation matches formula
6. Cross-reference A3 positions: accrual value matches supporting workbook at valuation timestamp
7. Verify `nav_summary.json` totals match sum of `positions.csv` values
8. Compare output against last known NAV from spreadsheet (14 March 2026) for sanity check
9. For A3: after next epoch/price update, verify cross-reference divergence < 5%
