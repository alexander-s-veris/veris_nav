# Current Portfolio Positions

Position balances and values are in the latest NAV snapshot (`outputs/`). This doc describes the position structure and methodology — not current amounts.

## A2 Positions (Off-chain yield-bearing)
- **USCC (Superstate Crypto Carry Fund)**: Collateral on Kamino Superstate Opening Bell market (Solana) + Aave Horizon (Ethereum). Primary: Pyth feed. Chainlink NAVLink as cross-reference.
- **mF-ONE (Midas Fasanara)**: Ethereum. Midas Chainlink-style oracle.
- **syrupUSDC (Maple)**: Across Morpho loops (Ethereum, Arbitrum). CoinGecko pricing.
- **ONyc (OnRe reinsurance)**: Solana (Exponent LPs + standalone). Weekly NAV updates.
- **mHYPER (Midas Hyperithm)**: Multi-chain OFT (Plasma, Ethereum, Monad, Katana). Midas Chainlink-style oracle on Plasma. Attestation verification via LlamaRisk API.
- **RLP (Resolv)**: Pyth oracle as primary, CoinGecko as fallback.

## A1 Positions (On-chain yield-bearing)
- **Credit Coop / Rain**: Veris Credit Vault (Ethereum). Reclassified A3 → A1 — on-chain `convertToAssets` is authoritative (analogous to sUSDe). Sub-strategies: Rain credit line + Gauntlet USDC Core + Gauntlet USDC Prime liquid reserves. Sub-strategy breakdown queried for methodology log.
- **Hyperithm USDC Apex**: MetaMorpho vault (Ethereum). Standard ERC-4626.
- **Other ERC-4626 vaults**: Euler (Arbitrum), Avantis (Base), Yearn (Katana), sUSDe (Ethereum). All standard `convertToAssets`.

## A3 Positions (Private credit)
- **FalconX / Pareto (Gauntlet)**: gpAAFalconX shares. Gauntlet vault holds AA_FalconXUSDC as Morpho collateral, borrows USDC. Manual accrual (gross rate from loan notices × 0.90 net). On-chain TP is cross-reference only.
- **FalconX / Pareto (Direct)**: AA_FalconXUSDC held directly. Same accrual rate as Gauntlet. Opening value = actual USDC deposited.

## B Positions (PT tokens)
- **PT-USX (Exponent, Solana)**: Multiple tranches with individual lot tracking, linear amortisation.
- **PT-eUSX (Exponent, Solana)**: Collateral in Kamino Solstice market.
- **PT-ONyc (Exponent, Solana)**: In LP position.

## C Positions (LP)
- **Exponent ONyc LP**: ONyc (SY) + PT-ONyc decomposition. PT priced using AMM implied rate, not lot amortisation.
- **Exponent eUSX LP**: eUSX (SY) + PT-eUSX decomposition.

## D Positions (Leveraged / Looping)
- **Kamino USCC/USDC**: Superstate Opening Bell market (Solana).
- **Kamino PT-USX+PT-eUSX/USX**: Solstice market (Solana). PT collateral priced via Category B lot methodology.
- **Morpho syrupUSDC loops**: Multiple markets on Ethereum and Arbitrum (USDT, PYUSD, AUSD, RLUSD debt).
- **Aave Horizon USCC/RLUSD**: Ethereum.
- **Aave Plasma sUSDe/USDe**: Plasma.

## E Positions (Stablecoins & Cash)
- USDC-pegged stablecoins (USDC, USDS, DAI, PYUSD) valued at par with depeg monitoring (±0.5%).
- Non-USDC-pegged (USDT, USX, USDG) valued at oracle price.
- Fiat at Bank Frick valued at face value.

## F Positions (Other)
- **Governance tokens**: MORPHO, PENDLE, ARB, KMNO, GIZA. Priced via Kraken → CoinGecko → DefiLlama hierarchy.
- **YT tokens**: YT-ONyc, YT-eUSX. Priced via `underlying × (1 − PT ratio)`. Near-expiry marked to zero.
- **Kamino farming rewards**: Included if claimable at Valuation Block. KMNO season rewards excluded.
- All whitelisted tokens with balance >$0 included in valuation.
