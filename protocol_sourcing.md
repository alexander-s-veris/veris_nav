# Protocol Sourcing Reference

How to read balances and positions from each protocol encountered in the portfolio. Use this to avoid re-researching protocol mechanics.

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

**ABI (minimal)**:
```json
[
  {
    "inputs": [{"name": "id", "type": "bytes32"}, {"name": "user", "type": "address"}],
    "name": "position",
    "outputs": [
      {"name": "supplyShares", "type": "uint256"},
      {"name": "borrowShares", "type": "uint128"},
      {"name": "collateral", "type": "uint128"}
    ],
    "stateMutability": "view", "type": "function"
  },
  {
    "inputs": [{"name": "id", "type": "bytes32"}],
    "name": "market",
    "outputs": [
      {"name": "totalSupplyAssets", "type": "uint128"},
      {"name": "totalSupplyShares", "type": "uint128"},
      {"name": "totalBorrowAssets", "type": "uint128"},
      {"name": "totalBorrowShares", "type": "uint128"},
      {"name": "lastUpdate", "type": "uint128"},
      {"name": "fee", "type": "uint128"}
    ],
    "stateMutability": "view", "type": "function"
  }
]
```

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

**ABI (minimal)**:
```json
[
  {
    "inputs": [{"name": "account", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "", "type": "uint256"}],
    "stateMutability": "view", "type": "function"
  },
  {
    "inputs": [{"name": "user", "type": "address"}],
    "name": "getUserAccountData",
    "outputs": [
      {"name": "totalCollateralBase", "type": "uint256"},
      {"name": "totalDebtBase", "type": "uint256"},
      {"name": "availableBorrowsBase", "type": "uint256"},
      {"name": "currentLiquidationThreshold", "type": "uint256"},
      {"name": "ltv", "type": "uint256"},
      {"name": "healthFactor", "type": "uint256"}
    ],
    "stateMutability": "view", "type": "function"
  }
]
```

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

ERC-4626 vaults with sub-account system.

**How to read**:
- Sub-accounts: `address XOR i` for i = 0..255. Must scan all 256 to find active ones.
- Once sub-account found: `balanceOf(sub_account_address)` on vault contract → shares
- `convertToAssets(shares)` → underlying amount

**Classification**: Category A1.

**Known vaults**:
| Vault | Address | Chain | Active sub-account |
|-------|---------|-------|--------------------|
| esyrupUSDC-1 | 0xA999f8a38A902f27F278358c4bD20fe1459Ae47C | Arbitrum | 163 (for 0xa33e) |

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
