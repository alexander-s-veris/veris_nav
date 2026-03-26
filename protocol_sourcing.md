# Protocol Sourcing Reference

How to read balances and positions from each protocol encountered in the portfolio. Use this to avoid re-researching protocol mechanics.

---

## Data Sourcing Method

**All position data is sourced via RPC endpoints** (Alchemy) as configured in `config/chains.json`. This is the primary and only method for reading on-chain balances and positions.

- **EVM chains**: Alchemy RPC (Ethereum, Arbitrum, Base, Avalanche, Plasma, HyperEVM)
- **Katana**: Public RPC endpoint (env var)
- **Solana**: Alchemy Solana RPC

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
| AA_FalconXUSDC/USDC | 16 Mar 2026 | Gauntlet/Pareto position |

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
  → Previously deployed as Morpho collateral (closed 16 Mar 2026)
  → Tokens withdrawn to wallet, still held
```

### Classification

**Category A3** (private credit). Primary valuation is **manual accrual** at contractual interest rate, NOT on-chain value. The on-chain queries below serve as **cross-reference only**.

### Contracts

| Contract | Address | Purpose |
|----------|---------|---------|
| Gauntlet Levered FalconX Vault | `0x00000000d8f3d6c5DFeB2D2b5ED2276095f3aF44` | Custom vault (NOT ERC-4626). gpAAFalconX token, 18 decimals. No convertToAssets/totalAssets. |
| Gauntlet Provisioner | `0x21994912f1D286995c4d4961303cBB8E44939944` | Vault management |
| Gauntlet Price Fee Calculator | `0x8F3FfA11CD5915f0E869192663b905504A2Ef4a5` | Fee calculations |
| Pareto Credit Vault FalconX | `0x433d5b175148da32ffe1e1a37a939e1b7e79be4d` | Price oracle only (NOT ERC-20). `tranchePrice(address)` → uint256 (6 dec) |
| AA_FalconXUSDC Tranche | `0xC26A6Fa2C37b38E549a4a1807543801Db684f99C` | ERC-20 tranche token, 18 decimals. Total supply 120.4M. NOT ERC-4626. |
| Morpho Market (AA_FalconXUSDC/USDC) | ID: `0xe83d72fa...f36f52` | The leveraged market |

### How to read (on-chain cross-reference)

**Step 1 — Tranche price:**
- Call `tranchePrice(tranche_address)` on Pareto contract `0x433d...`
- Input: `0xC26A6Fa2C37b38E549a4a1807543801Db684f99C`
- Returns: price scaled by 6 decimals (e.g. 1067961 = $1.067961 per tranche token)
- Note: `getTranchePrice()` reverts — use `tranchePrice()` instead

**Step 2 — Vault's Morpho position:**
- Call `position(market_id, vault_address)` on Morpho Core
- Returns collateral (AA_FalconXUSDC, 18 decimals) and borrow shares
- Convert borrow shares to USDC using `market(market_id)`
- Collateral value = collateral tokens × tranche price

**Step 3 — Veris's share:**
- `balanceOf(0x0c16)` on Gauntlet vault → Veris's gpAAFalconX shares
- `totalSupply()` on Gauntlet vault → total shares
- Veris % = veris_shares / total_supply

**Step 4 — Veris's indirect (Gauntlet) on-chain cross-reference:**
- Vault net = (Morpho collateral × tranche price) − borrow USDC
- Veris portion = vault net × Veris %
- Note: Gauntlet vault holds 0 AA_FalconXUSDC in wallet — all deployed as Morpho collateral

**Step 5 — Veris's direct AA_FalconXUSDC holding:**
- `balanceOf(0x0c16)` on AA_FalconXUSDC token `0xC26A...`
- Direct value = balance × tranche price

### Current values (26 Mar 2026)

**Indirect (via Gauntlet vault):**

| Metric | Value |
|--------|-------|
| Veris gpAAFalconX shares | 2,507,115 |
| Total supply | 26,740,263 |
| Veris ownership | 9.3758% |
| Vault Morpho collateral | 55,561,262 AA_FalconXUSDC |
| Tranche price | $1.067961 |
| Vault collateral value | $59,337,261 |
| Vault borrow | $30,924,012 USDC |
| Vault net | $28,413,248 |
| Veris on-chain cross-ref | $2,663,971 |

**Direct (AA_FalconXUSDC in wallet 0x0c16):**

| Metric | Value |
|--------|-------|
| 0x0c16 AA_FalconXUSDC balance | 1,894,970 |
| Tranche price | $1.067961 |
| Direct on-chain cross-ref | $2,023,746 |

**Combined FalconX cross-ref: ~$4,687,717**

### Accrual (primary valuation)

Contractual rate history:
- Jul 2025: initial $2M investment
- Aug 2025: 11.25%
- Sep 2025: 12%
- Oct 2025: 12% (additional investment, total ~$4.36M Gauntlet value)
- Jan 2026: 10.5%
- Feb 2026: 10%

Accrual details to be provided separately in loan documentation.

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

## General Patterns

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
