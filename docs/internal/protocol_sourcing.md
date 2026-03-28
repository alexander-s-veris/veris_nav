# Protocol Sourcing Reference

How to read balances and positions from each protocol encountered in the portfolio. Use this to avoid re-researching protocol mechanics.

For current positions and balances, see `portfolio_positions.md` (in this folder). For contract addresses and market IDs, see the config files referenced below.

---

## Adding a New Position (Quick Reference)

The system is **config-driven**. For standard protocol patterns, adding a new position requires **no code changes** — only config edits:

| Pattern | Config files to edit |
|---------|---------------------|
| New ERC-4626 vault | `contracts.json` (add vault entry with `abi: "erc4626"` under a section with `_query_type: "erc4626"`), `wallets.json` (add `"erc4626_vaults": true` to wallet if not already), `tokens.json` (add share token if needed for pricing) |
| New Morpho market | `morpho_markets.json` (add market entry with market_id, tokens, wallets) |
| New Aave deployment | `contracts.json` (add aToken + debt token entries under `_aave` section), `wallets.json` (add `"aave": true`) |
| New Midas token | `contracts.json` (add token + oracle entry under `_midas` section), `wallets.json` (add `"midas": true`) |
| New Kamino obligation | `solana_protocols.json` (add to kamino.obligations), `wallets.json` (add `"kamino": true`) |
| New Exponent market | `solana_protocols.json` (add to exponent.markets with sy/pt/yt sub-objects) |
| New PT lot | `pt_lots.json` (add lot details) |
| New token for pricing | `tokens.json` (add with appropriate pricing method/feed IDs) |

Protocol dispatch is driven by `wallets.json` protocol registrations → `PROTOCOL_TO_HANDLER` mapping → `HANDLER_REGISTRY` in `protocol_queries.py`.

---

## Data Sourcing Method

**All position data is sourced via RPC endpoints** (Alchemy) as configured in `config/chains.json`. This is the primary and only method for reading on-chain balances and positions.

Balance method per chain is configured in `config/chains.json` → `token_balance_method`:
- `alchemy` (default): `alchemy_getTokenBalances` + direct `balanceOf` fallback
- `etherscan_v2`: Etherscan V2 API `addresstokenbalance` endpoint
- `balance_of`: Direct `balanceOf` per registry token
- Solana: `getTokenAccountsByOwner` via Alchemy RPC

**Performance**: `src/block_utils.py` provides reusable concurrency utilities:
- `estimate_blocks()` pre-computes block numbers from a single reference (no per-row RPC)
- `concurrent_query()` / `concurrent_query_batched()` fire queries in parallel via ThreadPoolExecutor
- Hourly data collection: 10 workers, ~22 queries/s (10.6x faster). See `plans/falconx_position_flow.md`.
- Balance scanner: two-level parallelism (chains + wallets within each chain), ~120s → ~45s (2.7x)
- Pricing: CoinGecko batched into 1 API call + concurrent Chainlink/Kraken/Pyth queries

**DeBank is NOT used for data sourcing.** DeBank is a verification source only (per Valuation Policy Section 7) — used to cross-check aggregate portfolio value against our independently sourced data.

**Workflow for walking through wallet positions:**
1. Query token balances via RPC (Alchemy `alchemy_getTokenBalances` or direct `balanceOf`)
2. For protocol positions (Morpho markets, Aave lending, etc.): query the protocol's smart contracts directly at the relevant block
3. Price each position per its category methodology
4. Record all query details (contract, function, block number, result) for the methodology log

---

## Morpho (Ethereum, Arbitrum, Base)

Morpho has two product types. Both use the same core contract per chain.

**Config**: Core contract addresses per chain are in `contracts.json` under `_morpho` sections.

### Morpho Markets (Category D — Leveraged Positions)

Isolated lending markets. Each market has a unique `market_id` (bytes32). A position in a market has collateral (supplied) and debt (borrowed). All markets on a given chain share the same Morpho Core contract — the only thing that changes per market is the `market_id`.

**How to read positions**:
1. Call `position(bytes32 marketId, address wallet)` on the Morpho Core contract
   - Returns: `(uint256 supplyShares, uint128 borrowShares, uint128 collateral)`
   - `collateral` is the raw token amount (no shares conversion needed)
   - `supplyShares` and `borrowShares` need conversion to assets
2. Call `market(bytes32 marketId)` to get market state
   - Returns: `(uint128 totalSupplyAssets, uint128 totalSupplyShares, uint128 totalBorrowAssets, uint128 totalBorrowShares, uint128 lastUpdate, uint128 fee)`
   - Convert: `supplyAssets = supplyShares × totalSupplyAssets / totalSupplyShares`
   - Convert: `borrowAssets = borrowShares × totalBorrowAssets / totalBorrowShares`

**ABI**: `config/abis.json` → `morpho_core` (functions: `position`, `market`)

**Config**: `config/morpho_markets.json` — one entry per market with market_id, loan token, collateral token, wallets. Includes both active and closed markets (closed kept for audit trail). Handler: `morpho_leverage` in `HANDLER_REGISTRY`.

**Classification**: Category D. Net value = collateral value − debt value. Collateral priced per its own token category (A2, A3, etc.), debt (loan token) priced per Category E.

### Morpho Vaults / MetaMorpho (Category A1 — Yield-Bearing)

ERC-4626 vaults that allocate deposits across multiple Morpho markets. User deposits one token, receives vault shares. All MetaMorpho vaults implement the same ERC-4626 interface — no protocol-specific logic needed.

**How to read**:
1. `balanceOf(wallet)` on the vault contract → shares held
2. `convertToAssets(shares)` on the vault contract → underlying token amount
3. Price the underlying per its own category (E for stablecoins)

**Config**: Vaults are in `config/contracts.json` under sections with `_query_type: "erc4626"`. Share tokens in `config/tokens.json` with `"method": "a1_exchange_rate"`. Handler: `erc4626` in `HANDLER_REGISTRY`.

**Classification**: Category A1. Value = convertToAssets(shares) × underlying token price.

### Adding a new Morpho position

**New market (D)**: Only need the `market_id` — add entry to `morpho_markets.json` with loan/collateral token details and wallet. The read logic is identical for all markets.

**New vault (A1)**: Only need the vault contract address — add to `contracts.json` and `tokens.json`. Read via standard ERC-4626 `convertToAssets`.

---

## Midas

Tokenised fund shares. Each product has a token + a Chainlink-style oracle. Deployed across multiple chains (Ethereum, Plasma, Monad, Katana — varies per product). Contract addresses: `docs.midas.app/resources/smart-contracts-registry`.

**How to read**:
- Balance: `balanceOf(wallet)` on the token contract
- Price: `latestRoundData()` on the oracle contract → `answer` scaled by `decimals()`

**Classification**: Category A2. Value = balance × oracle price.

**No vault involvement for valuation** — if tokens are in the wallet, just read balanceOf and price via oracle. Midas deposit/redemption vaults are subscription/redemption mechanisms, not relevant for NAV purposes.

**Config**: Token addresses and oracles are in `contracts.json` under `_midas` sections per chain (with `_query_type: "midas_oracle"`). Handler: `midas_oracle` in `HANDLER_REGISTRY`. Adding a new Midas token = add entry to the `_midas` section with address, symbol, decimals, oracle, oracle_chain.

**Issuer fallback (tier 2)**: Midas publishes daily PDF reports. Issuer NAV URLs are in `config/price_feeds.json` per feed entry (`issuer_nav_url`, `issuer_nav_reports` fields).

**Verification**: Midas Attestation Engine publishes PoR via LlamaRisk API. Per-token verification price = attested total NAV / totalSupply (summed across all deployment chains). Config in `verification.json`.

---

## Aave (Ethereum, Base, Plasma)

Lending protocol. Positions tracked via aTokens (supply) and variable debt tokens (borrow). Each aToken/debt token is specific to a pool + reserve combination — so the same underlying asset on different pools has different aToken addresses.

### How positions work

When you supply an asset to Aave, you receive aTokens that represent your deposit. The aToken balance **automatically increases over time** as interest accrues — no need to call `convertToAssets`, just `balanceOf` gives you the current value in underlying terms.

When you borrow, a variable debt token is minted. Its `balanceOf` also increases automatically as borrow interest accrues.

### How to read positions

**Per-token approach (preferred for NAV — gives exact breakdown)**:
1. Supply balance: `balanceOf(wallet)` on the aToken contract → amount in underlying terms (includes accrued interest)
2. Debt balance: `balanceOf(wallet)` on the variable debt token contract → amount owed in underlying terms (includes accrued interest)
3. Price each underlying per its own category

**Aggregate approach (useful for quick cross-check)**:
- `getUserAccountData(wallet)` on the Pool contract
- Returns: `(totalCollateralBase, totalDebtBase, availableBorrowsBase, currentLiquidationThreshold, ltv, healthFactor)`
- Values in base currency (USD, 8 decimals)

**ABI**: `config/abis.json` → `erc20` (for aToken/debt token `balanceOf`) and `aave_pool` (for `getUserAccountData`)

### Classification

- **Supply-only** (no debt token balance): Category A1 — value = aToken balanceOf × underlying price
- **With debt** (leveraged): Category D — net = collateral value − debt value. Each side priced per its own token category.

### Important: Aave Horizon vs standard Aave V3

Aave Horizon is a **separate RWA-only pool** with its own Pool contract and its own aTokens/debt tokens. Do NOT mix up Horizon aTokens with standard V3 aTokens — they are different contracts even for the same underlying asset.

**Config**: Pool contracts, aTokens, and debt tokens are in `contracts.json` under `_aave` sections per chain. Each entry specifies the pool variant, underlying token, and type (supply/debt).

### Adding a new Aave position

1. Identify the Pool contract for that chain/pool variant
2. Find the aToken address for the supplied asset (check Pool's `getReserveData(asset)`)
3. If leveraged, also find the variable debt token address
4. Add contracts to `contracts.json`, tokens to `tokens.json`
5. Read: `balanceOf(wallet)` on aToken and/or debt token — that's it

---

## Euler V2 (Arbitrum)

ERC-4626 vaults with a sub-account system. Each wallet can have up to 256 sub-accounts within a vault.

### Sub-account system

Euler V2 uses a XOR-based addressing scheme for sub-accounts:
- Sub-account address = `wallet_address XOR sub_account_id` (where id = 0..255)
- This only affects the **last byte** of the address
- Sub-account 0 = the wallet itself (XOR 0 = no change)
- You must **scan all 256 sub-accounts** to discover which ones have balances — there's no registry or event to query

**Discovery script pattern**:
```python
wallet_int = int(wallet_address, 16)
for i in range(256):
    sub_addr = hex(wallet_int ^ i)
    shares = vault.balanceOf(sub_addr)
    if shares > 0:
        print(f"Sub-account {i}: {shares}")
```

**Important**: Sub-account IDs are NOT stable across wallets. Wallet A might use sub-account 1, wallet B might use sub-account 42. Always scan when encountering a new wallet on Euler.

### How to read (once sub-account is found)

Standard ERC-4626:
1. `balanceOf(sub_account_address)` on vault contract → shares
2. `convertToAssets(shares)` → underlying token amount

**Classification**: Category A1. Value = convertToAssets(shares) × underlying token price.

**Config**: Vaults and active sub-account IDs are in `contracts.json` under `_euler` sections.

### Adding a new Euler position

1. Get the vault contract address
2. Scan all 256 sub-accounts for the wallet to find which ones have balances
3. Record the active sub-account ID in contracts.json
4. Read via standard ERC-4626 `balanceOf(sub_addr)` + `convertToAssets`

---

## Avantis (Base)

ERC-4626 USDC vault.

**How to read**: Standard ERC-4626 — `balanceOf` + `convertToAssets`.

**Classification**: Category A1.

**Config**: Vault address in `contracts.json`.

---

## Ethena (Ethereum)

sUSDe is an ERC-4626 vault (staked USDe).

**How to read**:
- Balance: `balanceOf(wallet)` on sUSDe contract
- Value: `convertToAssets(shares)` → USDe amount
- **Pending unstakes**: `cooldowns(wallet)` returns `(cooldownEnd, underlyingAmount)` — these are NOT visible via balanceOf

**Classification**: A1 (sUSDe has deterministic on-chain exchange rate). Underlying USDe is Category E.

---

## Gauntlet / Pareto / FalconX (Ethereum)

Multi-layered private credit position. Veris has exposure through two paths, both using Pareto's AA_FalconXUSDC tranche token as the underlying credit instrument.

### Architecture

```
Pareto issues AA_FalconXUSDC tranche tokens (credit to FalconX)
  ↓
Two paths of exposure:

Path 1 (indirect): Gauntlet vault holds AA_FalconXUSDC as Morpho collateral
  → borrows USDC against it (leveraged)
  → Veris holds gpAAFalconX shares = pro-rata claim on vault's net exposure

Path 2 (direct): Wallet holds AA_FalconXUSDC directly
```

### Classification

**Category A3** (private credit). Primary valuation is **manual accrual** from supporting workbook (`outputs/falconx_position.xlsx`). On-chain tranche price is cross-reference only (and only valid at epoch end, not at NAV date).

Full methodology: `docs/methodology/falconx_accrual_analysis.md`
Position collection flow: `plans/falconx_position_flow.md`

**Config**: Contract addresses in `contracts.json` under `_gauntlet` and `_pareto` sections. ABI in `config/abis.json` → `pareto_credit_vault`.

### Pareto Credit Vault — on-chain functions

| Function                    | Returns              | Description                                                      |
|-----------------------------|----------------------|------------------------------------------------------------------|
| `tranchePrice(tranche)`     | uint256 (6 dec)      | Current price per AA_FalconXUSDC token. Updates ~monthly at epoch end. |
| `lastEpochApr()`            | uint256 (18 dec)     | Gross rate of last completed epoch (matches loan notice)         |
| `lastEpochInterest()`       | uint256 (6 dec)      | Interest distributed at last epoch end                           |
| `getContractValue()`        | uint256 (6 dec)      | Total pool value in USDC (matches loan notice principal)         |
| `epochEndDate()`            | uint256 (unix ts)    | Scheduled end of current epoch                                   |
| `epochDuration()`           | uint256 (seconds)    | Epoch length (~2,468,880 sec = ~28.6 days)                       |
| `isEpochRunning()`          | bool                 | Whether an epoch is currently active                             |
| `defaulted()`               | bool                 | Whether a default has occurred                                   |
| `getApr(tranche)`           | uint256 (18 dec)     | Current net investor APR                                         |

**Epoch cycle**: ~31 days. At epoch end, `stopEpoch()` updates the tranche price. Between epochs, TP is stale. TP update method signature: `0xb4ecd47f`.

### How to read — on-chain queries

**Hourly data collection** (via Multicall3, for supporting workbook):

1. `position(market_id, gauntlet_vault)` on Morpho Core → collateral tokens + borrow shares
2. `market(market_id)` on Morpho Core → convert borrow shares to USDC
3. `totalSupply()` on Gauntlet vault → for Veris % calculation
4. `tranchePrice(AA_tranche)` on Pareto vault → current TP

**Post-facto verification** (at epoch end only):
- `convertUnitsToToken(vault, USDC, veris_balance)` on PriceFeeCalculator

### Primary valuation — accrual

```
Interest = Opening_Value × Net_Rate × Days / 365
Net_Rate = Gross_Rate × 0.90 (10% pool fee)
```

- Gross rate from monthly loan notices at `docs/reference/loans/`
- Also verifiable on-chain via `lastEpochApr()` at each TP update block
- Supporting workbook: `outputs/falconx_position.xlsx` (two sheets: Gauntlet_LeveredX, Direct Accrual)
- NAV figure: column R ("Veris share") for Gauntlet, column H ("Running Balance") for Direct Accrual
- Collateral value in Gauntlet uses **re-engineered TP** from accrual, not stale on-chain TP

---

## Credit Coop / Rain (Ethereum)

ERC-4626/7540 vault that deploys capital into two sub-strategies: a Rain credit line (private credit) and a Gauntlet USDC Core vault (liquid reserve).

**Reclassified A3 → A1**: The vault's `convertToAssets` is deterministic and authoritative — it reflects collected + uncollected interest from Rain, yield from the liquid strategy, and performance fee deductions. Analogous to sUSDe being A1 despite off-chain underlying yield.

**Config**: All contract addresses in `contracts.json` under `_credit_coop` section.

### How to read — primary valuation (A1)

1. `balanceOf(wallet)` on vault → shares (6 decimals)
2. `convertToAssets(shares)` on vault → USDC value (6 decimals)
3. Underlying is USDC → Category E at par

### How to read — sub-allocation breakdown (for methodology log)

For the NAV methodology log, document the breakdown:

1. **Vault level**: `totalAssets()` → total USDC across all strategies. `totalLiquidAssets()` → liquid portion only.
2. **Credit strategy**: `totalActiveCredit()` on CreditStrategy → principal + uncollected interest in Rain credit line. For granular breakdown: `numCreditPositions()` then `tokenIds(i)` → `creditTokenIdToLine(tokenId)` → `getPositionActiveCredit(line, tokenId)` returns `(deposit, interest)`.
3. **Liquid strategy**: `totalAssets()` on LiquidStrategy → amount in Gauntlet USDC Core.
4. **Cash**: USDC `balanceOf` on credit strategy address (undeployed cash) + USDC `balanceOf` on vault address (undeployed in vault).

Interest on the Rain credit line accrues on-chain and is periodically collected by the vault, which reinvests it into the liquid strategy. The share price (`convertToAssets`) automatically reflects all of this.

**Classification**: Category A1. Value = `convertToAssets(shares)` (USDC, at par).

**Implementation**: `src/protocol_queries.py` → `query_creditcoop()` (handler: `credit_coop` in `HANDLER_REGISTRY`). Reads all contract addresses from `contracts.json` `_credit_coop` section. Queries aggregate `convertToAssets` + sub-strategy breakdown (`totalActiveCredit`, `totalAssets` on LiquidStrategy, USDC cash). Breakdown included in position notes for the methodology log.

---

## Fluid (Ethereum) — POSITION CLOSED

Uses NFT positions, not fungible shares. Each position is an NFT with its own collateral/debt state. **Veris position closed — no active holdings.**

**How to read** (for reference): Query by NFT ID via Fluid vault resolver contract.

**Classification**: Category D (if leveraged) or A1 (if supply-only).

---

## Curve (Ethereum)

LP token represents share of AMM pool.

**How to read**:
- Balance: `balanceOf(wallet)` on LP token contract
- Decompose: Pool contract `calc_withdraw_one_coin` or read virtual price + token composition

**Classification**: Category C (LP decomposition).

---

## Uniswap V4 (Ethereum)

NFT-based concentrated liquidity positions.

**How to read**: Query Position Manager contract with NFT ID. Returns token0/token1 amounts within the active range.

**Classification**: Category C. Value reflects actual token amounts in range, not full-range notional.

---

## Yearn V3 (Katana)

ERC-4626 vault.

**How to read**: Standard `balanceOf` + `convertToAssets`.

**Classification**: Category A1.

---

## ARMA / Giza Smart Accounts (Base, Arbitrum)

ARMA is an autonomous yield agent by Giza. It uses ERC-4337 smart account proxies (EIP-1167 minimal clones) to move capital between lending protocols (Aave, Morpho, Compound, Moonwell, etc.) autonomously via session keys.

**NOT a protocol position** — the proxy address itself holds the assets (USDC, aTokens, lending positions). There is no vault token or `convertToAssets`. Treat the proxy as a regular wallet.

**How to read**: Scan the proxy address the same way as any other wallet (token balances via `balanceOf` or Alchemy batch call). The proxy can hold positions across multiple protocols simultaneously — check for aTokens, Morpho vault shares, etc.

**Config**: Proxies listed in `wallets.json` under `arma_proxies`, each with `parent_wallet` linking back to the controlling EOA.

---

## Kamino Lend (Solana)

Isolated lending markets on Solana. Each market has its own reserves (tokens) and obligations (user positions with collateral + debt). All markets share the same program.

**Program ID**: `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD`

### Architecture

Markets like "Solstice", "Superstate Opening Bell", etc. are just separate lending markets under the same program — not different program types. An obligation is a PDA that holds a user's collateral deposits and borrows within a specific market.

### How to read — on-chain (preferred for Valuation Block)

Query the obligation account via `getAccountInfo` at the Valuation Block slot, then deserialize the binary data:

**Obligation account layout** (after 8-byte Anchor discriminator):
- `tag` (u64, 8 bytes): Obligation type (0=Vanilla, 1=Multiply, 2=Lending, 3=Leverage)
- `lastUpdate` (16 bytes): slot(u64) + stale(u8) + priceStatus(u8) + placeholder(6 bytes)
- `lendingMarket` (Pubkey, 32 bytes)
- `owner` (Pubkey, 32 bytes)
- `deposits` (array of 8 `ObligationCollateral`, 136 bytes each):
  - `depositReserve` (Pubkey, 32 bytes) — zero pubkey = empty slot
  - `depositedAmount` (u64, 8 bytes) — raw token amount in lamports
  - `marketValueSf` (u128, 16 bytes) — USD value (stale, do NOT use for NAV)
  - `borrowedAmountAgainstThisCollateralInElevationGroup` (u64, 8 bytes)
  - `padding` (9 × u64, 72 bytes)
- `lowestReserveDepositLiquidationLtv` (u64, 8 bytes)
- `depositedValueSf` (u128, 16 bytes) — total deposit USD (stale)
- `borrows` (array of 5 `ObligationLiquidity`, 200 bytes each):
  - `borrowReserve` (Pubkey, 32 bytes) — zero pubkey = empty slot
  - `cumulativeBorrowRateBsf` (48 bytes): BigFractionBytes
  - `lastBorrowedAtTimestamp` (u64, 8 bytes)
  - `borrowedAmountSf` (u128, 16 bytes) — amount with accrued interest, divide by 2^60
  - `marketValueSf` (u128, 16 bytes) — USD value (stale)
  - remaining fields (88 bytes)

**Key**: Use `depositedAmount` (raw token balance) and `borrowedAmountSf / 2^60` (debt with interest) — these are always accurate. The `marketValueSf` fields are stale unless the obligation was recently refreshed on-chain. Apply our own pricing per Valuation Policy.

**Implementation**: `src/solana_client.py` → `parse_kamino_obligation()` and `get_kamino_obligation()`

### How to read — REST API (for discovery and cross-referencing)

Base URL: `https://api.kamino.finance`

- **User obligations**: `GET /kamino-market/{market}/users/{user}/obligations` — returns all obligations with refreshed USD values
- **Metrics/history**: `GET /v2/kamino-market/{market}/obligations/{obligation}/metrics/history?start=YYYY-MM-DD&end=YYYY-MM-DD` — hourly snapshots with per-deposit/borrow mint addresses and USD values
- **All markets**: `GET /v2/kamino-market` — list all market pubkeys with names

The API refreshes `marketValueSf` before returning (unlike on-chain), so API USD values are more current. Use for cross-referencing against our own valuations.

### Reserve-to-token mapping

Reserves are identified by pubkey. The metrics/history endpoint returns `mintAddress` per deposit/borrow, which maps to the actual token.

**Config**: Obligation pubkeys, market pubkeys, reserve-to-token mappings, and deposit/borrow details are all in `config/solana_protocols.json` under `kamino.obligations`.

**Classification**: Category D. Net value = collateral value − debt value. Collateral priced per its own token category, debt per Category E.

### Farming / Rewards

Kamino farming rewards accrue to obligations via a separate Farms program. Claimable rewards are included in NAV per Category F rules.

**How to read**: `GET /farms/users/{wallet}/transactions` returns claim history. For current unclaimed balances, use the klend-sdk `Farms.getAllFarmsForUser()` or query farm user state accounts on-chain.

**Config**: Farm pubkeys and reward token mints are in `config/solana_protocols.json` under `kamino.farms`.

**KMNO season rewards** (claimable from kamino.com/season4): Excluded from NAV — airdrop/points mechanism, not standard farming.

### Adding a new Kamino position

1. Find the market pubkey (`GET /v2/kamino-market`)
2. Query user obligations in that market (`GET /kamino-market/{market}/users/{user}/obligations`)
3. Note the obligation pubkey, deposit reserves (collateral), and borrow reserves (debt)
4. Use metrics/history to get the mint addresses for each reserve
5. Add the obligation to `config/solana_protocols.json` under `kamino.obligations` — include market_name, obligation_pubkey, deposits (reserve, symbol, decimals, category), borrows
6. Add `"kamino": true` to the wallet's protocols in `wallets.json` if not already present
7. For on-chain reads: `get_kamino_obligation()` in `solana_client.py` is called automatically via the handler

---

## Exponent Finance (Solana)

Yield-splitting protocol on Solana. Wraps yield-bearing positions into SY (Standardized Yield) tokens, then splits into PT (Principal Token) and YT (Yield Token). Markets are AMM pools trading SY against PT.

**Program ID**: `ExponentnaRg3CQbW6dqQNZKXp7gtZ9DGMp1cwC4HAS7`
**No REST API, no SDK** — all data read from on-chain accounts via RPC.
**Source code**: `github.com/exponent-finance/exponent-core` (Anchor program, open source)

### Key account types

| Account | Discriminator | Seeds | Contains |
|---------|--------------|-------|----------|
| MarketTwo | `[212,4,132,126,169,121,121,20]` | `["market", vault, seed_id]` | Pool state, `MarketFinancials` (implied rate, PT/SY balances) |
| LpPosition | `[105,241,37,200,224,2,252,90]` | `["lp_position", market, owner]` | User's LP balance for a market |
| YieldTokenPosition | `[227,92,146,49,29,85,71,94]` | `["yield_position", vault, owner]` | User's YT balance and accrued yield |
| Vault | (keypair-based) | N/A | PT/YT/SY mints, exchange rate, maturity |

PT and SY are standard SPL tokens (readable via `getTokenAccountsByOwner`). LP and YT positions are PDA accounts — must use `getProgramAccounts` with discriminator + owner filter to discover.

### MarketTwo layout (MarketFinancials at offset 364)

Pubkeys at offset 8 (32 bytes each):
- idx 0: authority PDA
- idx 1-2: token mints (ordering may vary per market — verify against protocol UI)
- idx 3: vault
- idx 4: LP mint
- idx 5+: token accounts, fee receiver, admin, etc.
- **Note**: Do not assume idx 1 = SY and idx 2 = PT. Use `getTokenSupply` + protocol UI to identify mints.

`MarketFinancials` starts at byte offset **364**:
```
offset 364: expiration_ts     (u64, 8 bytes) — maturity as unix timestamp
offset 372: pt_balance        (u64, 8 bytes) — PT tokens in AMM pool
offset 380: sy_balance        (u64, 8 bytes) — SY tokens in AMM pool
offset 388: ln_fee_rate_root  (f64, 8 bytes)
offset 396: last_ln_implied_rate (f64, 8 bytes) — natural log of implied APY
offset 404: rate_scalar_root  (f64, 8 bytes)
```

### PT pricing within LPs (Category C)

Uses the AMM implied rate, NOT linear amortisation (which is for held-to-maturity lots):
```
exchange_rate = exp(last_ln_implied_rate × seconds_remaining / 31,536,000)
pt_price = underlying_price / exchange_rate
```
Note: on-chain uses exactly 365 days (31,536,000 seconds), not 365.25.

### LP decomposition (Category C)

```
user_sy = pool_sy_balance × user_lp_balance / total_lp_supply
user_pt = pool_pt_balance × user_lp_balance / total_lp_supply
```

Total LP supply: query `getTokenSupply` on the LP mint (idx 4 in MarketTwo).

Value = `user_sy × sy_price + user_pt × pt_price_from_amm`

### YT pricing (Category F)

```
yt_price = underlying_price × (1 − 1/exchange_rate)
```

Near-expiry illiquid YTs may be marked to zero per Valuation Policy.

### How to read positions

1. **Discovery** (one-time): `getProgramAccounts` on public RPC with discriminator + owner filters to find all LpPosition and YieldTokenPosition accounts
2. **LP valuation**: Read MarketTwo for pool state → decompose LP → price SY per its category, PT via AMM implied rate
3. **YT valuation**: Read YT balance from YieldTokenPosition, price using formula above
4. **Valuation Block**: Use `getAccountInfo` at specific slot on Alchemy for both MarketTwo and position accounts

**Implementation**: `src/solana_client.py` → `parse_exponent_market()`, `get_exponent_lp_positions()`, `get_exponent_yt_positions()`

**Production note**: Discovery (`getProgramAccounts`) is slow and rate-limited on Alchemy. For NAV runs, use the known account pubkeys from config with `getAccountInfo` only — no discovery step needed. Only re-run discovery when onboarding new positions. No `time.sleep()` needed between Alchemy `getAccountInfo` calls.

**Config**: Market pubkeys, vault pubkeys, LP/YT position accounts, and LP mint addresses are all in `config/solana_protocols.json` under `exponent.markets`.

---

## General Patterns

### EVM

| Protocol Type | Read Method | Category |
|---------------|------------|----------|
| ERC-4626 vault | `balanceOf` + `convertToAssets` | A1 |
| Midas tokenised fund | `balanceOf` + oracle `latestRoundData` | A2 |
| Morpho market (leveraged) | `position(market_id, wallet)` on core contract | D |
| Aave (leveraged) | aToken balance − debt token balance | D |
| Aave (supply only) | aToken `balanceOf` | A1 |
| LP token | `balanceOf` + pool decomposition | C |
| NFT position (Uni V4, Fluid) | Query by NFT ID | C or D |
| Smart account proxy | Scan as wallet | — |
| Plain token in wallet | `balanceOf` + price per token category | per token |

### Solana

| Protocol Type | Read Method | Category | Implementation |
|---------------|-------------|----------|----------------|
| Kamino obligation (leveraged) | `getAccountInfo` → deserialize obligation binary data | D | `solana_client.get_kamino_obligation()` |
| Kamino farming rewards | REST API `/farms/users/{wallet}/transactions` | F | Manual / API |
| PT token (hold-to-maturity) | Lot discovery via token account tx history, then linear amortisation from config | B | `pt_valuation.discover_pt_lots()` + `value_pt_from_config()` |
| eUSX exchange rate | `total USX in vault / total eUSX supply` on-chain | A1 | `solana_client.get_eusx_exchange_rate()` |
| Exponent LP | `getProgramAccounts` (LpPosition) → decompose via MarketTwo pool state | C | `solana_client.get_exponent_lp_positions()` + `decompose_exponent_lp()` |
| Exponent YT | `getProgramAccounts` (YieldTokenPosition) → price via `1 - 1/exchange_rate` | F | `solana_client.get_exponent_yt_positions()` |
| Plain SPL token | `getTokenAccountsByOwner` | per token | `collect_balances.query_balances_solana()` |

### Solana sourcing approach (3 paths)

1. **REST API** — for discovery and cross-referencing. Not sufficient for NAV (no slot queries, protocol's oracles not ours).
2. **Direct RPC** (`getAccountInfo` at Valuation Block slot) — authoritative for NAV. Read raw token amounts, apply our own pricing.
3. **Transaction history** (`getSignaturesForAddress` on token account) — for lot-based tracking (PT purchases, LP events). Discover once, save to config. Also the definitive fallback for **token identity verification** — when struct field analysis is ambiguous about what a mint is (SY vs PT vs LP), parsing token balance changes in swap/LP withdrawal transactions shows exactly what each mint represents.
