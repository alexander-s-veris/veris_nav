# Protocol Sourcing Reference

How to read balances and positions from each protocol encountered in the portfolio. Use this to avoid re-researching protocol mechanics.

---

## Data Sourcing Method

**All position data is sourced via RPC endpoints** (Alchemy) as configured in `config/chains.json`. This is the primary and only method for reading on-chain balances and positions.

- **EVM chains (Alchemy)**: Ethereum, Arbitrum, Base, Avalanche, HyperEVM — uses `alchemy_getTokenBalances` + direct `balanceOf` fallback
- **Plasma**: Etherscan V2 API `addresstokenbalance` endpoint (Alchemy `alchemy_getTokenBalances` not available)
- **Katana**: Direct `balanceOf` per registry token (`config/chains.json` → `token_balance_method: "balance_of"`)
- **Solana**: Alchemy Solana RPC `getTokenAccountsByOwner`

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

### Core Contracts

| Chain | Morpho Core Address |
|-------|---------------------|
| Ethereum | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` |
| Arbitrum | `0x6c247b1F6182318877311737BaC0844bAa518F5e` |
| Base | `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` (same as Ethereum) |

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

**Config**: `config/morpho_markets.json` — one entry per market with market_id, loan token, collateral token, wallets.

**Classification**: Category D. Net value = collateral value − debt value. Collateral priced per its own token category (A2, A3, etc.), debt (loan token) priced per Category E.

**Known active markets**:
| Market | Market ID | Collateral | Loan | Chain | Wallets |
|--------|-----------|------------|------|-------|---------|
| syrupUSDC/AUSD | `0xab31...0056` | syrupUSDC (A2) | AUSD (E) | Ethereum | 0xa33e |
| syrupUSDC/RLUSD | `0xc0ae...0394` | syrupUSDC (A2) | RLUSD (E) | Ethereum | 0xa33e |
| syrupUSDC/USDT0 | `0x571c...2af4` | syrupUSDC (A2) | USDT0 (E) | Arbitrum | 0xa33e |

**Closed markets** (keep in config for audit trail):
| Market | Closed | Notes |
|--------|--------|-------|
| mF-ONE/USDC | 26 Mar 2026 | Collateral moved to wallet |
| AA_FalconXUSDC/USDC (Veris direct) | 22 Mar 2026 | Veris 0x0c16 withdrew collateral, repaid debt. Gauntlet vault's position in same market remains active. |

### Morpho Vaults / MetaMorpho (Category A1 — Yield-Bearing)

ERC-4626 vaults that allocate deposits across multiple Morpho markets. User deposits one token, receives vault shares. All MetaMorpho vaults implement the same ERC-4626 interface — no protocol-specific logic needed.

**How to read**:
1. `balanceOf(wallet)` on the vault contract → shares held
2. `convertToAssets(shares)` on the vault contract → underlying token amount
3. Price the underlying per its own category (E for stablecoins)

**Config**: Add vault to `config/contracts.json` and share token to `config/tokens.json` with `"method": "a1_exchange_rate"`.

**Classification**: Category A1. Value = convertToAssets(shares) × underlying token price.

**Known vaults**:
| Vault | Address | Deposit Token | Chain | Wallet |
|-------|---------|---------------|-------|--------|
| Steakhouse Reservoir USDC (bbqSUDCreservoir) | `0xBEeFF047C03714965a54b671A37C18beF6b96210` | USDC | Ethereum | 0xa33e |
| Steakhouse USDT (steakUSDT) | `0xbEef047a543E45807105E51A8BBEFCc5950fcfBa` | USDT | Ethereum | 0xa33e |
| Clearstar USDC Reactor (CSUSDC) | `0x1D3b1Cd0a0f242d598834b3F2d126dC6bd774657` | USDC | Base | 0x8055 |

### Adding a new Morpho position

**New market (D)**: Only need the `market_id` — add entry to `morpho_markets.json` with loan/collateral token details and wallet. The read logic is identical for all markets.

**New vault (A1)**: Only need the vault contract address — add to `contracts.json` and `tokens.json`. Read via standard ERC-4626 `convertToAssets`.

---

## Midas (Ethereum, Plasma)

Tokenised fund shares. Each product has a token + a Chainlink-style oracle.

**How to read**:
- Balance: `balanceOf(wallet)` on the token contract
- Price: `latestRoundData()` on the oracle contract → `answer` scaled by `decimals()`

**Classification**: Category A2. Value = balance × oracle price.

**No vault involvement for valuation** — if tokens are in the wallet, just read balanceOf and price via oracle. Midas deposit/redemption vaults are subscription/redemption mechanisms, not relevant for NAV purposes.

**Known tokens**:
| Token | Address | Oracle | Chain |
|-------|---------|--------|-------|
| mF-ONE | 0x238a700eD6165261Cf8b2e544ba797BC11e466Ba | 0x8D51DBC85cEef637c97D02bdaAbb5E274850e68C | Ethereum |
| msyrupUSDp | 0x2fE058CcF29f123f9dd2aEC0418AA66a877d8E50 | 0x337d914ff6622510FC2C63ac59c1D07983895241 | Ethereum |
| mHYPER | 0xb31BeA5c2a43f942a3800558B1aa25978da75F8a | 0xfC3E47c4Da8F3a01ac76c3C5ecfBfC302e1A08F0 | Plasma |

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

### Known deployments

| Pool | Pool Contract | Chain | Notes |
|------|---------------|-------|-------|
| Aave Horizon RWA | `0xAe05Cd22df81871bc7cC2a04BeCfb516bFe332C8` | Ethereum | RWA-only, separate from V3 |
| Aave V3 | `0xA238Dd80C259a72e81d7e4664a9801593F98d1c5` | Base | Standard V3 |
| Aave V3 | `0x925a2A7214Ed92428B5b1B090F80b25700095e12` | Plasma | Standard V3 |

### Known aTokens and debt tokens

| Token | Contract | Pool | Chain | Underlying | Type |
|-------|----------|------|-------|------------|------|
| aHorRwaUSCC | `0x08b798c40b9AB931356d9aB4235F548325C4cb80` | Horizon | Ethereum | USCC (A2) | Supply |
| variableDebtHorRwaRLUSD | `0xace8a1c0ec12ae81814377491265b47f4ee5d3dd` | Horizon | Ethereum | RLUSD (E) | Debt |
| aBassyrupUSDC | `0xD7424238CcbE7b7198Ab3cFE232e0271E22da7bd` | V3 | Base | syrupUSDC (A2) | Supply |
| aPlaUSDe | `0x7519403E12111ff6b710877Fcd821D0c12CAF43A` | V3 | Plasma | USDe (E) | Supply |
| aPlasUSDe | `0xc1a318493ff07a68fe438cee60a7ad0d0dba300e` | V3 | Plasma | sUSDe (A1) | Supply |

### Known positions

| Position | Pool | Chain | Wallet | Type | Category |
|----------|------|-------|--------|------|----------|
| USCC/RLUSD | Horizon | Ethereum | 0x8055 | Leveraged (supply USCC, borrow RLUSD) | D |
| sUSDe + USDe supply | V3 | Plasma | 0x6691 | Supply-only (no debt) | A1 |
| syrupUSDC supply | V3 | Base | 0xa33e | Supply-only (no debt) | A1 |

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

### Known vaults

| Vault | Address | Chain | Wallet | Active sub-account | Sub-account address |
|-------|---------|-------|--------|--------------------|---------------------|
| esyrupUSDC-1 | `0xA999f8a38A902f27F278358c4bD20fe1459Ae47C` | Arbitrum | 0xa33e | 1 | `0xa33e...62a3` |

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

| Vault | Address | Chain |
|-------|---------|-------|
| avUSDC | 0x944766f715b51967E56aFdE5f0Aa76cEaCc9E7f9 | Base |

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
Two paths of exposure for Veris:

Path 1 (indirect): Gauntlet vault holds AA_FalconXUSDC as Morpho collateral
  → borrows USDC against it (leveraged)
  → Veris holds gpAAFalconX shares = pro-rata claim on vault's net exposure

Path 2 (direct): Veris wallet 0x0c16 holds AA_FalconXUSDC directly
  → Jul-Sep 2025: held in wallet, then moved to Gauntlet
  → Mar 2026: revived — supplied as Morpho collateral, then withdrawn to wallet
```

### Classification

**Category A3** (private credit). Primary valuation is **manual accrual** from supporting workbook (`outputs/falconx_position.xlsx`). On-chain tranche price is cross-reference only (and only valid at epoch end, not at NAV date).

Full methodology: `docs/methodology/falconx_accrual_analysis.md`
Position collection flow: `plans/falconx_position_flow.md`

### Contracts

| Contract                         | Address                                       | Purpose                                                    |
|----------------------------------|-----------------------------------------------|------------------------------------------------------------|
| Gauntlet Levered FalconX Vault   | `0x00000000d8f3d6c5DFeB2D2b5ED2276095f3aF44`  | Custom vault (NOT ERC-4626). gpAAFalconX, 18 dec.          |
| Gauntlet Price Fee Calculator    | `0x8F3FfA11CD5915f0E869192663b905504A2Ef4a5`  | `convertUnitsToToken()` for post-facto verification        |
| Pareto Credit Vault              | `0x433d5b175148da32ffe1e1a37a939e1b7e79be4d`  | Proxy (impl: `0x8016...Ccaf`). TP, epoch, pool data.       |
| AA_FalconXUSDC Tranche           | `0xC26A6Fa2C37b38E549a4a1807543801Db684f99C`  | ERC-20 tranche token, 18 dec. NOT ERC-4626.                |
| Morpho Market                    | ID: `0xe83d72fa...f36f52`                      | AA_FalconXUSDC/USDC leveraged market                       |

### Pareto Credit Vault — on-chain functions

ABI: `config/abis.json` → `pareto_credit_vault`

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

**Veris balances** (queried on change only via Etherscan transfers):
- `balanceOf(0x0c16)` on Gauntlet vault → gpAAFalconX shares
- `balanceOf(0x0c16)` on AA_FalconXUSDC → direct holding
- `position(AA_USDC_market, 0x0c16)` on Morpho → direct Morpho collateral

**Post-facto verification** (at epoch end only):
- `convertUnitsToToken(vault, USDC, veris_balance)` on PriceFeeCalculator (`0x8F3F...`)

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

### Contracts

| Contract | Address | Purpose |
|----------|---------|---------|
| Veris Credit Vault | `0xb21eAFB126cEf15CB99fe2D23989b58e40097919` | ERC-4626/7540 vault. Primary valuation via `convertToAssets`. |
| LiquidStrategy | `0x671B5B6F01C5FEe16E6F9De2eb85AC027Dc9fE0e` | Deploys idle capital into Gauntlet USDC Core. `totalAssets()` for balance. |
| CreditStrategy | `0x433E415b0fA54C570C450DD976E2402e408cB6db` | Line-of-Credit-v2 to Rain. `totalActiveCredit()` for deployed amount. |
| Rain Credit Line | `0x1e86E49780Dd5FF522B43889A7C196caa0CABd85` | Borrower address for the credit position. |
| Gauntlet USDC Core | `0x8eB67A509616cd6A7c1B3c8C21D48FF57df3d458` | ERC-4626 Morpho vault where liquid strategy deposits. |

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

### Current terms (as of Mar 2026)

- Rain credit line: $3.75M principal, 14% annual rate, 10% performance fee
- Gauntlet USDC Core: ~$113K liquid reserve yielding ~4.77%
- Single wallet: 0xec0b

**Classification**: Category A1. Value = `convertToAssets(shares)` (USDC, at par).

**Implementation**: `src/protocol_queries.py` → `query_creditcoop()` — queries aggregate `convertToAssets` + sub-strategy breakdown (`totalActiveCredit`, `totalAssets` on LiquidStrategy, USDC cash). Breakdown included in position notes for the methodology log.

### Hyperithm USDC Apex (Ethereum, wallet 0xec0b)

MetaMorpho vault. Standard ERC-4626.

| Contract | Address | Description |
|----------|---------|-------------|
| Hyperithm USDC Apex | `0x777791c4d6dc2ce140d00d2828a7c93503c67777` | MetaMorpho vault (hyperUSDCa), ~1,152 USDC |

**Classification**: Category A1. Value = `convertToAssets(shares)` (USDC, at par).

---

## Fluid (Ethereum)

Uses NFT positions, not fungible shares. Each position is an NFT with its own collateral/debt state.

**How to read**: Query by NFT ID via Fluid vault resolver contract.

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

**Implementation**: All proxies share the same implementation contract `0x17bac39f916c21ac825aed89607fdba251dce97d` (EIP-1167 clone pattern).

**Config**: Listed in `wallets.json` under `arma_proxies`, each with `parent_wallet` linking back to the controlling EOA.

**Known proxies**:
| Proxy Address | Chain | Parent Wallet | Holdings |
|---------------|-------|---------------|----------|
| 0xa8d4e894f268438d3438d0030f2e36852aeba97d | Base | 0x6691 (Private Deal Positions) | ~$10 USDC |
| 0xd5086229c2fdea72f8c3292cfafbae7337126c9b | Arbitrum | 0xaca2 (Open Market Positions 3) | ~$0.01 USDC |

---

## Kamino Lend (Solana)

Isolated lending markets on Solana. Each market has its own reserves (tokens) and obligations (user positions with collateral + debt). All markets share the same program.

**Program ID**: `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD`

### Architecture

"Solstice", "Superstate Opening Bell", etc. are just separate lending markets under the same program — not different program types. An obligation is a PDA that holds a user's collateral deposits and borrows within a specific market.

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

### Known positions

| Market | Market Pubkey | Obligation | Collateral | Debt |
|--------|--------------|------------|------------|------|
| Superstate Opening Bell | `CF32kn7AY8X1bW7ZkGcHc4X9ZWTxqKGCJk6QwrQkDcdw` | `D2rcayJTqmZvqaoViEyamQh2vw9T1KYwjbySQZSz6fsS` | USCC (reserve `FQnQgB...`, mint `BTRR3s...`, 6 dec) | USDC (reserve `BnYNV7...`, mint `EPjFWd...`, 6 dec) |
| Solstice | `9Y7uwXgQ68mGqRtZfuFaP4hc4fxeJ7cE9zTtqTxVhfGU` | `HMMc5d9sMrGrAY18wE5yYTPpJNk72nrBrgqz5mtE3yrq` | PT-USX (reserve `BLKW7x...`, mint `3kctCX...`, 6 dec, Cat B) + PT-eUSX (reserve `Ezmztx...`, mint `BNR2Fs...`, 6 dec, Cat B) | USX (reserve `H2pmnD...`, mint `6FrrzD...`, 6 dec) |

**Classification**: Category D. Net value = collateral value − debt value. Collateral priced per its own token category (A2 for USCC, B for PT-USX/PT-eUSX), debt per Category E.

### Farming / Rewards

Kamino farming rewards accrue to obligations via a separate Farms program (`FarmsPZpWu9i7Kky8tPN37rs2TpmMrAZrC7S7vJa91Hr`). Claimable rewards are included in NAV per Category F rules.

**How to read**: `GET /farms/users/{wallet}/transactions` returns claim history. For current unclaimed balances, use the klend-sdk `Farms.getAllFarmsForUser()` or query farm user state accounts on-chain.

**Known farms for Veris wallet**:

| Farm | Reward Token | Reward Mint | Status |
|------|-------------|-------------|--------|
| `sXqHDSD...` | USX | `6FrrzDk5mQARGc1TDYoyVnSyRdds1t4PbtohCD6p3tgG` | Active (weekly claims) |
| `DQGadHq...` | USDG | `2u1tszSeqZ3qBWF3uNGPFc8TzMk2tdiwknnRMWGWjGWH` | Active (last claim Jan 2026) |
| `DEe2NZ5...`, `8hznHD3...` | PYUSD | `2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo` | Inactive since Nov 2025 |

**KMNO season rewards** (claimable from kamino.com/season4): Excluded from NAV — airdrop/points mechanism, not standard farming.

### Adding a new Kamino position

1. Find the market pubkey (`GET /v2/kamino-market`)
2. Query user obligations in that market (`GET /kamino-market/{market}/users/{user}/obligations`)
3. Note the obligation pubkey, deposit reserves (collateral), and borrow reserves (debt)
4. Use metrics/history to get the mint addresses for each reserve
5. Add to the Known positions table above
6. For on-chain reads: use `get_kamino_obligation()` in `solana_client.py`

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

**Production note**: Discovery (`getProgramAccounts`) is slow and rate-limited on Alchemy. For NAV runs, use the known account pubkeys from the table below with `getAccountInfo` only — no discovery step needed. Only re-run discovery when onboarding new positions. No `time.sleep()` needed between Alchemy `getAccountInfo` calls.

### Known positions

| Market | Market Pubkey | Vault | Position Type | User Account |
|--------|-------------|-------|---------------|-------------|
| ONyc-13MAY26 | `8QJRc12BDXHRLghZXFyPtYtAQeRwnZGKMJQa3G2NVQoC` | `J2apQJvz...` | LP (C) | `Bim2Q4nJ...` (lp_balance ~821T raw, 9 dec) |
| eUSX-01JUN26 | `rBbzpGk3PTX8mvQg95VWJ24EDgvxyDJYrEo9jtauvjP` | `7NviQEEi...` | LP (C) | `A5Cf2QFy...` (lp_balance ~119B raw, 6 dec) |
| ONyc-13MAY26 | — | `J2apQJvz...` | YT (F) | `FoiWPd6H...` (yt_balance ~726T raw = 725,568 tokens, 9 dec) |
| eUSX-01JUN26 | — | `7NviQEEi...` | YT (F) | `Bz2FoHme...` (yt_balance ~142B raw = 141,771 tokens, 6 dec) |

### LP mint addresses

| Market | LP Mint | Decimals |
|--------|---------|----------|
| ONyc-13MAY26 | `3gqhwFZtkU1dUyNN6taFp8sbnu3E5bmkumfjtoF9P9JD` | 9 |
| eUSX-01JUN26 | `4GT6g1iKx2TyYCkwt1tERkReQjSUuVE7uh14M5W8v2nn` | 6 |

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
