# Plan: Production Wallet Balance Scanner (Category E + F)

## Context
Move from test script (`test_wallet_balances.py`) to production wallet balance scanner covering:
- **6 EVM wallets** across **5 EVM chains** (Ethereum, Arbitrum, Base, Avalanche, Plasma) = 30 balance queries
- **1 Solana wallet** (`ASQ4kYjSYGUYbbYtsaLhUeJS6RtrN4Uwp4XbF4gDifvr`) = 1 balance query

Filters spam via token registry. Applies Valuation Policy pricing for Category E (stablecoins) and Category F (governance tokens, dust). Documents the methodology in the output for the Calculation Agent.

## Files to Create/Modify

| File | Action | Purpose |
|------|--------|---------|
| `.env` | Modify | Add CoinGecko API key (paid Demo plan) |
| `config/tokens.json` | Create | Token registry — whitelist of known tokens per chain (EVM + Solana) with pricing config |
| `src/evm.py` | Create | Shared EVM utilities — cached Web3 connections, block queries, constants |
| `src/pricing.py` | Create | Price adapters — Chainlink, Pyth, Kraken, CoinGecko (paid API), par with de-peg check |
| `src/collect_balances.py` | Create | Main production script — queries all wallets, filters, prices, outputs |

## Step 1: `.env` — Add CoinGecko API Key

Add `COINGECKO_API_KEY`. CoinGecko paid Demo plan uses header `x-cg-demo-api-key` and base URL `https://api.coingecko.com/api/v3`. Can batch multiple token IDs in one call (comma-separated), higher rate limits than free tier.

## Step 2: `src/evm.py` — Shared EVM Utilities

Extract and cache reusable plumbing from test scripts:
- `load_chains()` — load config/chains.json (cached)
- `get_rpc_url(chain)` — build RPC URL (existing pattern: `rpc_url_template` with `{api_key}` or `rpc_env_var`)
- `get_web3(chain)` — return cached Web3 instance, inject PoA middleware
- `get_block_info(w3, block="latest")` — return `(block_number, block_timestamp_utc_str)`
- Move shared constants: `CONFIG_DIR`, `OUTPUT_DIR`, `TS_FMT`, `ETHERSCAN_V2_BASE`, `NATIVE_TOKEN`, `AGGREGATOR_V3_ABI`

Web3 connections cached in module-level dict — created once per chain, reused for all 6 wallets on that chain.

## Step 3: `config/tokens.json` — Token Registry

Structure: keyed by chain name (including `"solana"`), then by lowercased contract address (or mint address on Solana). Each entry:

```json
{
  "symbol": "USDC",
  "name": "USD Coin",
  "category": "E",
  "decimals": 6,
  "pricing": {
    "method": "par",
    "depeg_check_feed": "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6"
  }
}
```

A `_template` key at the top documents the schema for easy addition of new tokens.

**Pricing methods:**
- `"par"` — E stablecoins pegged to USDC. Price = $1.00, plus Chainlink de-peg check
- `"chainlink"` — E non-USDC stablecoins (USDT, USDG). Query Chainlink, fallback Pyth
- `"kraken"` — F governance tokens. Query Kraken, fallback CoinGecko
- `"coingecko"` — F tokens not on Kraken

**Tokens to populate initially:**

| Token | Category | Method | Chains |
|-------|----------|--------|--------|
| USDC | E | par + de-peg check | All EVM + Solana |
| DAI | E | par + de-peg check | Ethereum |
| PYUSD | E | par + de-peg check | Ethereum |
| USDS | E | par + de-peg check | Ethereum (if present) |
| USDT | E | chainlink → pyth | All EVM |
| USDG | E | chainlink → coingecko | Where present |
| MORPHO | F | kraken → coingecko | Ethereum, Arbitrum |
| PENDLE | F | kraken → coingecko | Ethereum |
| ARB | F | kraken → coingecko | Arbitrum |
| GIZA | F | coingecko | Base |
| RLP | F | coingecko | Ethereum |
| ETH (native) | F | kraken → coingecko | Ethereum, Arbitrum, Base |
| AVAX (native) | F | kraken → coingecko | Avalanche |
| XPL (native) | F | coingecko | Plasma |
| SOL (native) | F | kraken → coingecko | Solana |

Tokens NOT in registry = spam/airdrop → silently skipped.

## Step 4: `src/pricing.py` — Price Adapters

Five adapter functions + one dispatcher:

1. **`par_price(token_entry, w3_eth)`** — returns $1.00, then queries Chainlink for de-peg check:
   - Deviation ≤0.5%: price at par, flag `"none"`
   - Deviation 0.5–2%: price at oracle value, flag `"minor_X.XX%"`
   - Deviation >2%: price at oracle value, flag `"material_X.XX%"`

2. **`chainlink_price(feed_address, w3)`** — call `latestRoundData()` + `decimals()`, return price + updatedAt. Reuse `AGGREGATOR_V3_ABI` from evm.py

3. **`pyth_price(feed_id)`** — REST call to `hermes.pyth.network/v2/updates/price/latest` (free, no key)

4. **`kraken_price(pair)`** — REST call to `api.kraken.com/0/public/Ticker` (free, no key)

5. **`coingecko_price(coin_id)`** — REST call with `x-cg-demo-api-key` header from `.env`. Batch multiple IDs per call.

6. **`get_price(token_entry, w3_eth)`** — dispatcher with fallback chains:
   - E par: `par_price` (with de-peg check via Chainlink)
   - E chainlink: Chainlink → Pyth fallback
   - F kraken: Kraken → CoinGecko fallback
   - F coingecko: CoinGecko direct

Price cache: module-level dict keyed by symbol. Each token priced once per run.

## Step 5: `src/collect_balances.py` — Main Production Script

**Flow:**
1. Load config: tokens.json, wallets.json, chains.json
2. **EVM chains** (5 chains × 6 wallets = 30 queries):
   - For each chain: get cached Web3 connection, fetch block number + timestamp once
   - For each wallet: query all token balances (Alchemy or Etherscan V2)
   - Match each token against registry by contract address (lowercased)
   - Skip unregistered tokens
3. **Solana** (1 wallet):
   - Connect via Alchemy Solana RPC
   - Query SPL token accounts via `getTokenAccountsByOwner`
   - Query native SOL balance
   - Match against `"solana"` entries in tokens.json by mint address
4. Price all matched tokens (once per unique token via cache)
5. For each matched balance row:
   - Look up price, calculate `value_usd = balance × price`
   - Dust threshold: Cat F positions < $100 → value at zero
   - De-peg flags for Cat E tokens
6. Write output with methodology summary

**Output fields:**
```
wallet, chain, token_contract, token_symbol, token_name, category, balance,
price_usd, price_source, value_usd, depeg_flag, notes, block_number, block_timestamp_utc
```

## Step 6: Methodology Documentation in Output

The JSON output includes a `_methodology` header block at the top, documenting:

```json
{
  "_methodology": {
    "description": "Wallet balance snapshot for Veris Capital AMC NAV calculation",
    "scope": "Category E (stablecoins & cash) and Category F (governance tokens, rewards, other)",
    "valuation_policy_ref": "Sections 6.7 (Cat E) and 6.8 (Cat F) of Valuation Policy v1.0",
    "pricing_rules": {
      "E_par": "USDC-pegged stablecoins (USDC, DAI, PYUSD, USDS, USX) valued at par ($1.00). Chainlink oracle queried for de-peg check per Section 9.4. Deviation >0.5% triggers actual traded value pricing.",
      "E_oracle": "Non-USDC-pegged stablecoins (USDT, USDG) valued at oracle price. Source hierarchy: Chainlink → Pyth → Redstone (Section 6.2 tier 1).",
      "F_governance": "Governance tokens priced via: (1) Kraken reported price, (2) CoinGecko aggregated price, (3) DEX TWAP (Section 6.8).",
      "F_dust": "Positions under $100 valued at zero per Section 6.8 dust threshold.",
      "F_unregistered": "Tokens not in the token registry (spam, airdrops, unsolicited deposits) are excluded from the snapshot."
    },
    "chains_queried": ["ethereum", "arbitrum", "base", "avalanche", "plasma", "solana"],
    "wallets_queried": 7,
    "run_timestamp_utc": "dd/mm/yyyy hh:mm:ss"
  },
  "positions": [...]
}
```

Per Section 12.1 of the Valuation Policy, the NAV Report must show for each position: the valuation methodology applied, the pricing source used, and the data source reference. The `price_source`, `category`, `depeg_flag`, and `notes` columns satisfy this per-position.

## Verification

1. Run `python src/collect_balances.py` and confirm:
   - 5 EVM chains × 6 wallets + 1 Solana wallet queried
   - Spam tokens filtered out (no `t.me`, fake tokens, or unsolicited airdrops)
   - USDC priced at par with de-peg check (Chainlink ~$1.00, flag "none")
   - USDT priced via Chainlink oracle
   - MORPHO, ARB, PENDLE priced via Kraken or CoinGecko
   - Solana USDC and other SPL tokens included
   - Dust positions (<$100) flagged and valued at zero
   - `_methodology` block present in JSON output
   - Output files: `outputs/wallet_balances.json` and `outputs/wallet_balances.csv`
2. Spot-check prices against CoinGecko/Kraken manually
3. Verify de-peg check: USDC Chainlink should return ~$1.00, deviation <0.5%, flag "none"
