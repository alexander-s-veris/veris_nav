# Veris Capital AMC - Wallet and Token Registry

Auto-generated from config/wallets.json, config/tokens.json, config/chains.json

## Wallets

### EVM Wallets (used across all EVM chains)

| # | Address | Description |
|---|---------|-------------|
| 1 | 0xa33e1f748754d2d624638ab335100d92fcbe62a2 | Open Market Positions |
| 2 | 0x6691005cd97656d488b72594c42cae987264e0e7 | Open Market Positions 2 |
| 3 | 0x0c1644d7af63df4a3b15423dbe04a1927c00a4f4 | Credit Positions |
| 4 | 0xec0b3a9321a5a0a0492bbe20c4d9cd908b10e21a | Credit Positions 2 |
| 5 | 0xaca2ef22f720ae3f622b9ce3065848c4333687ae | Multi-chain wallet |
| 6 | 0x80559941c1a741bc435cb6782b6f161d5772ac4b | Multi-chain wallet |

### Solana Wallets

| # | Address | Description |
|---|---------|-------------|
| 1 | ASQ4kYjSYGUYbbYtsaLhUeJS6RtrN4Uwp4XbF4gDifvr | Main Solana wallet |

## Chains

| Chain | Chain ID | RPC Provider |
|-------|---------|-------------|
| ethereum | 1 | Alchemy |
| arbitrum | 42161 | Alchemy |
| base | 8453 | Alchemy |
| avalanche | 43114 | Alchemy |
| plasma | 9745 | Etherscan V2 |
| hyperevm | 999 | Alchemy |
| solana | - | Alchemy |

## Token Registry

### Ethereum

| Symbol | Name | Category | Contract / Mint | Pricing Method |
|--------|------|----------|----------------|---------------|
| ETH | Ether | F | native | kraken |
| USDC | USD Coin | E | 0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48 | par |
| USDT | Tether USD | E | 0xdac17f958d2ee523a2206206994597c13d831ec7 | chainlink |
| DAI | Dai Stablecoin | E | 0x6b175474e89094c44da98b954eedeac495271d0f | par |
| PYUSD | PayPal USD | E | 0x6c3ea9036406852006290770bedfcaba0e23a0e8 | par |
| USDD | USDD | E | 0x4f8e5de400de08b164e7421b3ee387f461becd1a | pyth |
| DAM | Reservoir | F | 0x0fedba9178b70e8b54e2af08ebffcf28a1e5a43b | coingecko |
| MORPHO | Morpho | F | 0x58d97b57bb95320f9a05dc918aef65434969c2b2 | kraken |
| PENDLE | Pendle | F | 0x808507121b80c02388fad14726482e061b8da827 | kraken |
| RLP | Resolv Liquidity Provider Token | A1 | 0x4956b52ae2ff65d74ca2d61207523288e4528f96 | pyth |

### Arbitrum

| Symbol | Name | Category | Contract / Mint | Pricing Method |
|--------|------|----------|----------------|---------------|
| ETH | Ether | F | native | kraken |
| USDC | USD Coin | E | 0xaf88d065e77c8cc2239327c5edb3a432268e5831 | par |
| USDT | Tether USD | E | 0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9 | chainlink |
| ARB | Arbitrum | F | 0x912ce59144191c1204e64559fe8253a0e49e6548 | kraken |
| MORPHO | Morpho | F | 0x40bd670a58238e6e230c430bbb5ce6ec0d40df48 | kraken |

### Base

| Symbol | Name | Category | Contract / Mint | Pricing Method |
|--------|------|----------|----------------|---------------|
| ETH | Ether | F | native | kraken |
| USDC | USD Coin | E | 0x833589fcd6edb6e08f4c7c32d4f71b54bda02913 | par |
| MORPHO | Morpho | F | 0xbaa5cc21fd487b8fcc2f632f3f4e8d37262a0842 | kraken |
| GIZA | Giza | F | 0x590830dfdf9a3f68afcdde2694773debdf267774 | coingecko |

### Avalanche

| Symbol | Name | Category | Contract / Mint | Pricing Method |
|--------|------|----------|----------------|---------------|
| AVAX | Avalanche | F | native | kraken |
| USDC | USD Coin | E | 0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e | par |
| USDT | Tether USD | E | 0x9702230a8ea53601f5cd2dc00fdbc13d4df4a8c7 | chainlink |

### Hyperevm

| Symbol | Name | Category | Contract / Mint | Pricing Method |
|--------|------|----------|----------------|---------------|
| HYPE | Hyperliquid | F | native | kraken |
| USDC | USD Coin | E | 0xb88339cb7199b77e23db6e890353e22632ba630f | par |

### Plasma

| Symbol | Name | Category | Contract / Mint | Pricing Method |
|--------|------|----------|----------------|---------------|
| XPL | Plasma | F | native | kraken |
| WXPL | Wrapped XPL | F | 0x6100e367285b01f48d07953803a2d8dca5d19873 | kraken |
| USDT0 | USDT0 | E | 0xb8ce59fc3717ada4c02eadf9682a9e934f625ebb | chainlink |

### Solana

| Symbol | Name | Category | Contract / Mint | Pricing Method |
|--------|------|----------|----------------|---------------|
| SOL | Solana | F | native | kraken |
| USDC | USD Coin | E | epjfwdd5aufqssqem2qn1xzybapc8g4weggkzwytdt1v | par |
| USDT | Tether USD | E | es9vmfrzacermjfrf4h2fyd4kconky11mcce8benwnyb | chainlink |
| ONyc | OnRe Reinsurance | A2 | 5y8nv33vv7wbnlfq3zbcksdyprk7g2koiqoe7m2tcxp5 | pyth |
| USX | USX | E | 6frrzdk5mqargc1tdyoyvnsyrdds1t4pbtohcd6p3tgg | pyth |
| eUSX | eUSX (yield-bearing USX) | A1 | 3thdfzqkm6kryvglg48kapg5trmhymky1icra9xop1wc | a1_exchange_rate |

