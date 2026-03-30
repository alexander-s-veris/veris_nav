# Veris Capital AMC — NAV Data Collection System

Automated data collection system for the monthly NAV calculation of the Veris Capital AMC (ISIN: LI1536896288), an open-ended Actively Managed Certificate issued by 10C PCC / 10C Cell 11 PC.

Queries on-chain positions, oracle prices, and market data across Ethereum, Arbitrum, Base, Avalanche, Plasma, HyperEVM, Katana, and Solana to produce a canonical NAV snapshot consumed by the Excel NAV workbook.

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env` and add your API keys:
```
ALCHEMY_API_KEY=your_key
ETHERSCAN_API_KEY=your_key
COINGECKO_API_KEY=your_key
KATANA_RPC_URL=https://rpc.katana.network
SOLSCAN_API_KEY=your_key
```

## Usage

### NAV Collection (production)

```bash
# Latest block (development/testing)
python src/collect.py

# Pinned to Valuation Block at 15:00 UTC on a specific date (production)
python src/collect.py --date 2026-03-31
```

When `--date` is provided, all on-chain queries are pinned to the block/slot closest to but not exceeding 15:00 UTC on that date, per the Valuation Policy. Without `--date`, queries run at latest block.

### Snapshot Diff (pre-submission check)

```bash
# Compare the two most recent snapshots
python src/tools/diff_snapshots.py --latest

# Compare specific snapshots
python src/tools/diff_snapshots.py outputs/nav_20260228 outputs/nav_20260331

# Output as JSON
python src/tools/diff_snapshots.py --latest --json
```

Flags: new/disappeared positions, zero-value positions, value changes >10%, price source changes, balance changes >50%. Returns exit code 1 if critical issues found.

### Supporting scripts

```bash
# Wallet balance scanner (standalone quick check, ~45s)
python src/collect_balances.py

# FalconX/Pareto A3 hourly accrual updater (writes to data/falconx.db, run before collect.py)
python src/falconx/update_falconx_optimized.py
```

## Current Status

**Production NAV collection** (`src/collect.py`) is operational. Queries all protocol positions + wallet balances across 7 EVM chains + Solana, values per category methodology, and outputs to `outputs/nav_YYYYMMDD/`. ~108 positions, ~$26M net. RPC calls optimized via Multicall3 batching and concurrent execution.

**All protocol positions are registered:**

| Wallet | Description | Positions Registered |
|--------|-------------|---------------------|
| 0xa33e | Open Market Positions | Morpho D (3 active, 1 closed), Steakhouse USDC A1, Steakhouse USDT A1, Euler A1, Aave Base A1, mF-ONE A2, mHYPER A2, Ethena cooldown, Uniswap V4 LP |
| 0x6691 | Private Deal Positions | msyrupUSDp A2, Aave Plasma A1, Avantis A1, Yearn Katana A1, ARMA proxy, Curve LP |
| 0x0c16 | Credit Positions | Gauntlet/FalconX A3 (indirect via vault + direct AA_FalconXUSDC), Morpho AA_FalconXUSDC closed |
| 0xeC0B | Credit Positions 2 | CreditCoop A1, Hyperithm A1, Ethena cooldown |
| 0xaca2 | Open Market Positions 3 | ARMA proxy (Arbitrum) |
| 0x8055 | Open Market Positions 2 | Aave Horizon D, Clearstar A1, mHYPER A2 |
| ASQ4... | Solana Vault 1 | Kamino D (2 obligations: USCC/USDC + PT-USX/PT-eUSX/USX), PT-USX B (7 lots), PT-eUSX B (1 lot), Exponent C (2 LPs: ONyc + eUSX), Exponent F (2 YTs: ONyc + eUSX), farming rewards F |

## Architecture

The system uses a **config-driven handler registry** pattern. Adding a new position for a standard protocol pattern requires only config changes, no code:

1. `wallets.json` declares which protocols each wallet uses on each chain
2. `contracts.json` defines protocol contracts with `_query_type` fields
3. `protocol_queries.py` dispatches via `HANDLER_REGISTRY` based on protocol type
4. `solana_protocols.json` configures Solana positions (Kamino, Exponent)
5. `tokens.json` defines pricing config per token (method, feed IDs, fallback sources)
6. `valuation.py` builds pricing indices from config at init — no hardcoded prices or feed IDs

Additional features:
- **Oracle staleness checking**: A2 tokens flag stale prices (>2x expected update frequency) and fall through to next source in hierarchy
- **Independent verification (Section 7.3)**: 5 tokens verified — mHYPER (LlamaRisk attestation), msyrupUSDp + mF-ONE (Midas PDF reports via Google Drive OCR), USCC (Superstate REST API), ONyc (OnRe on-chain NAV)
- **Valuation Policy compliance tests**: 61 automated tests validate config against the Valuation Policy v1.0 (`python -m unittest discover -s tests -v`)
- **Chain health tracking**: Reports per-chain success/failure in `nav_summary.json`
- **Snapshot diff tool**: `python src/tools/diff_snapshots.py --latest` catches disappeared/changed positions before submission

See `docs/internal/protocol_sourcing.md` for the "Adding a New Position" quick reference table.

## Project Structure

```
src/
  collect.py                # Production orchestrator (--date pinning)
  protocol_queries.py       # Handler registry, concurrent dispatch
  handlers/                 # Protocol-specific position readers
    morpho.py, erc4626.py, euler.py, aave.py, midas.py
    gauntlet.py, creditcoop.py, uniswap.py, ethena.py
    kamino.py, exponent.py, pt_lots.py
  adapters/                 # Price feed adapters (per provider)
    chainlink.py, pyth.py, redstone.py, kraken.py
    coingecko.py, dex_twap.py, exchange_rate.py
    curve_lp.py
  verifiers/                # Independent verification (Sec 7)
    midas_attestation.py, midas_pdf_report.py
    superstate_api.py, onre_onchain.py
  valuation.py              # Category-specific valuation (A1-F)
  pricing.py                # Hierarchy walker, batch fetching
  multicall.py              # Multicall3 batching (aggregate3)
  evm.py                    # Shared EVM utils (Web3, blocks)
  block_utils.py            # Block estimation, concurrent RPC
  solana_client.py          # Solana RPC (Kamino, Exponent, OnRe)
  pt_valuation.py           # PT lot-based amortisation (Cat B)
  collect_balances.py       # Wallet balance scanner library
  output.py                 # Snapshot writer (CSV/JSON/summary)
  tools/                    # Standalone utilities
    diff_snapshots.py       # Compare NAV snapshots
    cache_xlsx.py           # Cache xlsx sheets as CSVs
    extract_powerquery.py   # Extract Power Query M code
    generate_methodology_pdf.py
  falconx/                  # FalconX/Pareto A3 accrual scripts
    update_falconx_optimized.py
    import_falconx_xlsx_to_sqlite.py
    query_pareto_tranche_history.py
config/
  chains.json               # RPC URLs, chain IDs, explorers
  wallets.json              # Wallets + protocol registrations
  tokens.json               # Token registry + pricing config
  contracts.json            # Protocol contracts (_query_type)
  solana_protocols.json     # Kamino, Exponent, OnRe configs
  abis.json                 # Minimal ABIs for all interactions
  morpho_markets.json       # Morpho market IDs + positions
  pt_lots.json              # PT lot details for amortisation
  price_feeds.json          # Feed definitions (58 entries)
  pricing_policy.json       # Per-category hierarchy rules
  verification.json         # Verification sources (Sec 7)
docs/
  internal/                 # Internal reference docs
  methodology/              # Deliverables (Bank Frick / audit)
  reference/                # Valuation Policy, loan notices
```

## Configuration Files

- `config/chains.json` — RPC endpoints per chain, `token_balance_method` (default=Alchemy, `etherscan_v2` for Plasma, `balance_of` for Katana), `multicall3` addresses
- `config/wallets.json` — Wallet addresses per chain with per-wallet protocol registrations. Used by the handler dispatch to determine which protocols to query for each wallet.
- `config/tokens.json` — Token registry per chain with category (A1-F) and pricing config (method, feed IDs, fallback sources). Pricing indices are built from this at init.
- `config/contracts.json` — Protocol contracts grouped by chain and protocol, with `_query_type` fields that map to handlers in `HANDLER_REGISTRY`
- `config/solana_protocols.json` — Solana protocol position configs (Kamino obligations with reserve mappings, Exponent markets with SY/PT/YT details)
- `config/abis.json` — Minimal ABIs for all contract interactions (ERC-20, ERC-4626, Morpho, Chainlink, Aave, Pareto, Ethena, CreditCoop strategies, Uniswap V4)
- `config/morpho_markets.json` — Morpho leveraged position market IDs with collateral/loan token details
- `config/pt_lots.json` — PT token individual lot details for linear amortisation

## Asset Categories

| Category | Description | Pricing Method |
|----------|-------------|---------------|
| A1 | On-chain yield-bearing (ERC-4626 vaults, sUSDe, eUSX) | Smart contract `convertToAssets` |
| A2 | Off-chain yield-bearing (mF-ONE, USCC, syrupUSDC, ONyc) | Oracle (Chainlink/Pyth) or issuer NAV |
| A3 | Private credit (FalconX/Pareto) | Manual accrual from contractual terms |
| B | PT tokens (zero-coupon, hold-to-maturity) | Linear amortisation per lot |
| C | LP positions (Curve, Uniswap, Exponent) | Decompose into constituents |
| D | Leveraged positions (Morpho, Aave, Kamino, Fluid) | Net = Collateral - Debt |
| E | Stablecoins and cash | Par ($1.00) for USDC-pegged; oracle for non-USDC-pegged |
| F | Governance tokens, rewards, other | Kraken/CoinGecko/DEX TWAP |

## Output Format

Each NAV run produces a date-stamped folder in `outputs/nav_YYYYMMDD/` containing:
- `positions.json` / `positions.csv` — One row per position with full audit trail
- `nav_summary.json` — Aggregated NAV by category and wallet, with valuation block metadata
- `leverage_detail.csv` — Category D collateral/debt breakdown
- `pt_lots.csv` — Per-lot PT linear amortisation detail
- `lp_decomposition.csv` — Category C LP constituent breakdown
- `diff_report.json` — Snapshot diff (when run via diff_snapshots.py --json)

## Reference

See `CLAUDE.md` for full project context, valuation methodology, and asset classification framework.

See `docs/reference/` for the Valuation Policy and NAV workbook.

See `docs/internal/protocol_sourcing.md` for detailed protocol-by-protocol position reading guide.
