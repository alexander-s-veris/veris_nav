# Current Portfolio Positions (as of March 2026)

## A2 Positions (Off-chain yield-bearing)
- **USCC (Superstate Crypto Carry Fund)**: ~738K USCC as collateral on Kamino Superstate Opening Bell market (Solana), ~177K USCC on Aave Horizon (Ethereum). NAV ~$11.51/share. **Primary: Pyth feed. Chainlink NAVLink as cross-reference.**
- **mF-ONE (Midas Fasanara)**: ~3.85M tokens in wallet 0xa33e. Oracle price ~$1.067. **Use Midas Chainlink-style oracle.**
- **syrupUSDC (Maple)**: Large positions across Morpho loops (Ethereum, Arbitrum). CG price ~$1.12.
- **ONyc (OnRe reinsurance)**: On Solana (Exponent LPs + standalone). Weekly NAV updates.
- **mHYPER (Midas Hyperithm)**: Small positions.
- **RLP (Resolv)**: 204,746 tokens. Pyth oracle as primary, CoinGecko as fallback.

## A1 Positions — Credit Coop / Rain
- **Credit Coop / Rain**: ~$3.87M in Veris Credit Vault (0xb21e), wallet 0xec0b. **Reclassified A3 → A1** (rationale below). ERC-4626/7540 vault with deterministic `convertToAssets`. Sub-strategies: Rain credit line ($3.75M principal, 14% rate, 10% perf fee) + Gauntlet USDC Core liquid reserve (~$113K). Interest collected periodically from Rain and reinvested into liquid strategy. Sub-strategy breakdown queried for methodology log: `totalActiveCredit()` on CreditStrategy, `totalAssets()` on LiquidStrategy, USDC cash on vault.
- **Hyperithm USDC Apex**: ~1,152 USDC in MetaMorpho vault (`0x7777...`), wallet 0xec0b. Standard ERC-4626 `convertToAssets`.
- **Reclassification rationale (per Valuation Policy Section 6.1)**: The vault's on-chain exchange rate (`convertToAssets`) is authoritative and deterministic — it reflects both collected and uncollected interest from the Rain credit line, plus yield from the Gauntlet USDC Core liquid reserve, net of performance fees. This is analogous to sUSDe (classified A1 even though underlying yield is off-chain). The credit strategy's `getPositionActiveCredit()` provides granular principal/interest breakdown for the methodology log, but `convertToAssets` is the primary valuation source.

## A3 Positions (Private credit)
- **FalconX / Pareto (Gauntlet)**: gpAAFalconX shares (2,507,115). Gauntlet vault holds 55.56M AA_FalconXUSDC as Morpho collateral, borrows ~$30.9M USDC. Veris share ~9.38%. Manual accrual at 8.325% net (Mar 2026: 9.25% gross × 0.90). On-chain TP (1.067961) is cross-reference only.
- **FalconX / Pareto (Direct)**: 1,894,970 AA_FalconXUSDC held directly in wallet 0x0c16 (since Mar 6 2026). Opening value $2,024,989 (actual USDC deposited). Same accrual rate as Gauntlet.

## B Positions (PT tokens)
- **PT-USX (Exponent, Solana)**: 7 tranches totaling 1,802,168 PT-USX, maturity 01-Jun-2026. Individual lot tracking with linear amortisation.
- **PT-eUSX (Exponent, Solana)**: 77,840 tokens as collateral in Kamino Solstice market.
- **PT-ONyc-13MAY26 (Exponent, Solana)**: In LP position.

## C Positions (LP)
- **Exponent ONyc-13MAY26 LP**: 1,063,938 ONyc + 709,406 PT-ONyc. PT priced using Exponent formula: `underlying_price × EXP(-last_ln_implied_rate × days/365)`.
- **Exponent eUSX-01JUN26 LP**: 195,927 eUSX + 41,422 PT-eUSX.

## D Positions (Leveraged / Looping)
- **Kamino USCC/USDC (Superstate Opening Bell market)**: 737,994 USCC collateral, -6,790,572 USDC debt (largest position)
- **Kamino PT-USX+PT-eUSX/USX (Solstice market)**: 1,802,168 PT-USX + 77,840 PT-eUSX collateral (both B, lot-based), USX debt.
- **Morpho syrupUSDC/USDT (Arbitrum)**: 10.46M syrupUSDC collateral, -9.85M USDT0 debt
- **Morpho syrupUSDC/PYUSD**: 778,640 syrupUSDC, -724,736 PYUSD debt
- **Morpho syrupUSDC/AUSD**: 483,000 syrupUSDC, -450,479 AUSD debt
- **Morpho syrupUSDC/RLUSD**: 267,000 syrupUSDC, -250,166 RLUSD debt
- **Aave Horizon USCC/RLUSD**: 176,845 USCC collateral, -1,622,969 RLUSD debt
- **Aave Plasma sUSDe/USDe**: Small position

## E Positions (Stablecoins & Cash)
- **Hyperliquid**: ~$1M USDC
- **Various small balances**: USDC, USDT, USDG across wallets
- USDC-pegged stablecoins (USDC, USDS, DAI, PYUSD) valued at par within ±0.5%
- Non-USDC-pegged (USDT, USX, USDG) valued at oracle price (Pyth/Chainlink)

## F Positions (Other)
- **MORPHO, PENDLE, ARB, KMNO**: Governance token rewards across wallets
- **GIZA**: 223,251 tokens on Base
- **YT-ONyc-13MAY26**: ~725,568 tokens
- **YT-eUSX-01JUN26**: ~141,771 tokens
- **Kamino farming rewards** (Solana): Unclaimed USDG (~6,035) and USX from farming. Included if claimable at Valuation Block. KMNO season rewards excluded.
- All whitelisted tokens with balance >$0 included in valuation
