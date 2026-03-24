# Veris Capital AMC — NAV Data Collection System

Automated data collection system for the monthly NAV calculation of the Veris Capital AMC (ISIN: LI1536896288).

Queries on-chain positions, oracle prices, and market data across Ethereum, Arbitrum, Base, Avalanche, Plasma, and Solana to produce a canonical NAV snapshot consumed by the Excel NAV workbook.

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env` and add your API keys:
```
ALCHEMY_API_KEY=your_key
ETHERSCAN_API_KEY=your_key
```

## Project Structure

```
src/            Source code (collection scripts, pricing, valuation)
config/         Chain configs, wallet addresses, contract addresses, price feed mappings
outputs/        Generated snapshot files (CSV/JSON)
docs/           Valuation Policy and reference documents
```

## Configuration

- `config/chains.json` — RPC endpoints per chain
- `config/wallets.json` — Wallet addresses per chain
- `config/contracts.json` — Contract addresses and ABIs
- `config/price_feeds.json` — Token-to-price-source mapping
- `config/pt_lots.json` — PT token individual lot details for linear amortisation

## Reference

See `CLAUDE.md` for full project context, valuation methodology, and asset classification framework.

See `docs/` for the Valuation Policy governing how all positions are priced.
