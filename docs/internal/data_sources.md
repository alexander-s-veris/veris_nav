# Data Sources & API Reference

Price feeds, oracle contracts, and API endpoints used by the NAV system. For protocol-specific contract addresses and read methods, see `protocol_sourcing.md`.

---

## Chainlink Feeds

All feed addresses are in `config/price_feeds.json` (single source of truth). Do not hardcode addresses here.

Note: USX/USD, SyrupUSDC/USDC, eUSX/USX, RLP/USD etc. appear on Chainlink but are **Data Streams** (paid), NOT free Data Feeds. Do not attempt to query these via contract call.

ABI: see `config/abis.json` → `chainlink_aggregator_v3`.

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
Note: Pro plan uses `pro-api.coingecko.com` base URL (not `api.coingecko.com`). Multiple IDs can be batched in one call (comma-separated). Coin ID mappings are in `config/price_feeds.json` (each CoinGecko feed entry has a `coin_id` field).

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

## Verification Sources (Section 7)

Asset-level verification sources cross-check primary oracle prices against independent data. Config in `config/verification.json`.

| Source | API | Used For |
|--------|-----|----------|
| LlamaRisk (Midas Attestation Engine) | `GET /api/proof/midas/{proof_id}` → attested total NAV | A2 mHYPER. Derives per-token price = total NAV / totalSupply (summed across deployment chains) |
| Midas PDF Reports (Google Drive) | Google Drive API v3 (service account) → PDF download → OCR | A2 msyrupUSDp, mF-ONE. Reports with Total assets / Issued tokens. Saved to `docs/reference/midas/` for audit trail |
| Superstate NAV API | `GET /v1/funds/{id}/nav-daily` → daily NAV/S, AUM, outstanding shares | A2 USCC. No auth required. API docs: `api.superstate.com/swagger-ui/` |
| OnRe On-Chain NAV | Solana RPC `getAccountInfo` on Offer PDA → APR-based step pricing | A2 ONyc. Verification cross-check against Pyth primary. Config in `solana_protocols.json` |

Portfolio-level verification (DeBank, Octav) per Section 7.1 — not yet implemented.

---

## DefiLlama

Last-resort aggregated price source. Combines DEX and CEX data across all chains. Replaces per-pool DEX TWAP.

```
GET https://coins.llama.fi/prices/current/{chain}:{address}
```

Supports batch queries (comma-separated). No API key needed. Response includes `price`, `timestamp`, `confidence`, `symbol`. Chain prefixes: `ethereum`, `solana`, `arbitrum`, `base`, `avalanche`, `coingecko` (for native tokens by CoinGecko ID).

Feed definitions in `config/price_feeds.json` under `defillama` section.

---

## RPC Endpoints

Chain RPC URLs, chain IDs, and native token metadata are in `config/chains.json` (single source of truth). API keys in `.env` (never commit to GitHub).
