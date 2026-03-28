# Data Sources & API Reference

Price feeds, oracle contracts, and API endpoints used by the NAV system. For protocol-specific contract addresses and read methods, see `protocol_sourcing.md`.

---

## Known Chainlink Feeds (free on-chain Data Feeds)

| Token | Feed Type | Contract / ENS | Chain |
|-------|-----------|---------------|-------|
| USCC NAV per share | NAVLink (SmartData) | `uscc-nav.data.eth` / `0xAfFd...00d9` | Ethereum | *(cross-reference only — SmartData, not standard AggregatorV3. Primary: Pyth)* |
| USDT/USD | Price Feed | `0x3E7d1eAB13ad0104d2750B8863b489D65364e32D` | Ethereum |
| USDC/USD | Price Feed | `0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6` | Ethereum |
| DAI/USD | Price Feed | `0xAed0c38402a5d19df6E4c03F4E2DceD6e29c1ee9` | Ethereum |
| mF-ONE/USD | Chainlink-style oracle (Midas) | `0x8D51DBC85cEef637c97D02bdaAbb5E274850e68C` | Ethereum |

Note: USX/USD, SyrupUSDC/USDC, eUSX/USX, RLP/USD etc. appear on Chainlink but are **Data Streams** (paid), NOT free Data Feeds. Do not attempt to query these via contract call.

### ABI for Chainlink AggregatorV3Interface
```json
[
  {"inputs":[],"name":"latestRoundData","outputs":[
    {"name":"roundId","type":"uint80"},
    {"name":"answer","type":"int256"},
    {"name":"startedAt","type":"uint256"},
    {"name":"updatedAt","type":"uint256"},
    {"name":"answeredInRound","type":"uint80"}
  ],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"stateMutability":"view","type":"function"},
  {"inputs":[],"name":"description","outputs":[{"name":"","type":"string"}],"stateMutability":"view","type":"function"}
]
```

---

## Pyth Hermes API

Free REST endpoint, no API key needed:
```
GET https://hermes.pyth.network/v2/updates/price/latest?ids[]=<price_feed_id>
```
Check https://docs.pyth.network/price-feeds/price-feeds for available feed IDs.

---

## CoinGecko API (Pro plan)

Using Pro API key with `x-cg-pro-api-key` header:
```
GET https://pro-api.coingecko.com/api/v3/simple/price?ids=<coin_id>&vs_currencies=usd
```
Note: Pro plan uses `pro-api.coingecko.com` base URL (not `api.coingecko.com`). Multiple IDs can be batched in one call (comma-separated).
The NAV spreadsheet already uses CoinGecko via a helper table `tbl_Helper_CoinIds` with these mappings:
- usd-coin → USDC
- usdt0 → USDT0
- resolv-wstusr → wstUSR
- superstate-uscc → USCC
- ripple-usd → RLUSD
- giza → GIZA
- resolv-rlp → RLP
- And ~20 more

---

## Kraken API

Kraken is an approved custodian and reference price source (per Final Terms). Used as:
- **Primary** for all assets held at Kraken (regardless of category)
- **First source** for governance token pricing (Category F)

Public ticker endpoint (no API key needed):
```
GET https://api.kraken.com/0/public/Ticker?pair=<pair>
```

---

## Midas mF-ONE Daily Reports

Published as image-based PDFs (no extractable text) in a public Google Drive folder. Filename format: `mfone_reporting_public_YYYYMMDD.pdf`. Key field: "Price as of report Date: $X.XXXXXXXX". Reports are daily (business days), taken at 5pm ET snapshot. The PDF requires OCR to extract the price programmatically. Folder: `https://drive.google.com/drive/folders/1NnrtI39fO2XuaNvnnZurvGskTYv_B4i_`. Local copies saved to `docs/reference/midas/mf-one/`.

---

## RPC Endpoints

- **Ethereum**: Alchemy or Infura (user has Alchemy)
- **Arbitrum**: Alchemy
- **Base**: Alchemy
- **Avalanche**: Public RPC or Alchemy
- **Plasma**: Etherscan V2 API (chain ID 9745, native token: XPL, explorer: plasmascan.to). Alchemy not available for Plasma.
- **HyperEVM**: Alchemy (chain ID 999, native token: HYPE)
- **Solana**: Alchemy (`solana-mainnet.g.alchemy.com/v2/API_KEY`)

Store API keys in a `.env` file (never commit to GitHub).
