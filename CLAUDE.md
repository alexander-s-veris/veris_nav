# Veris Capital AMC — NAV Data Collection System

## Session Start Checklist

At the start of each new conversation, before working on any tasks, read through all project `.md` files to refresh context:
- `CLAUDE.md` (this file)
- `README.md`
- `plans/*.md` — current and future plans
- `docs/internal/*.md` — internal reference docs:
  - `protocol_sourcing.md` — how to read positions from each protocol
  - `valuation_methodology.md` — category A1–F valuation rules
  - `nav_output_spec.md` — output format, methodology log, NAV formula
  - `portfolio_positions.md` — current positions by category
  - `data_sources.md` — oracle feeds, APIs, RPC endpoints
  - `architecture.md` — system design, pricing architecture, robustness
- `docs/methodology/*.md` — methodology deliverables (FalconX accrual, NAV sourcing)
- `docs/reference/valuation_policy_v1.0.md` — Valuation Policy (markdown transcription)
- `.claude/skills/*/SKILL.md` — operational skills (e.g. safe file organization)

Do NOT rely on memory alone — always re-read the docs.

**Memory maintenance**: Update your memory files (`.claude/projects/.../memory/`) every hour during long sessions and after every significant milestone (feature completed, architecture change, new position onboarded, bug fixed). Memory should reflect the current project state so the next session starts with accurate context.

**Doc maintenance**: When positions change (onboarded, closed, rebalanced), update `docs/internal/portfolio_positions.md`. When architecture changes (new handlers, pricing flow), update `docs/internal/architecture.md`. When adding a new protocol, update `docs/internal/protocol_sourcing.md`. The methodology deliverable (`docs/methodology/NAV_Data_Sourcing_Methodology.md`) must be regenerated as PDF before each NAV date — use `docs/methodology/claude_code_formatting_prompt.md` for formatting rules.

---

## Project Overview

This project builds a Python-based data collection system for the Veris Capital AMC (ISIN: LI1536896288), an open-ended Actively Managed Certificate issued by 10C PCC / 10C Cell 11 PC. The system collects on-chain positions, oracle prices, and market data to produce a canonical NAV snapshot file that feeds into the NAV workbook (Excel).

**Product**: USD-denominated stablecoin yield fund deployed across DeFi protocols on Ethereum, Arbitrum, Base, Avalanche, Plasma, Solana, and HyperEVM. The Basket does NOT hold volatile spot tokens (BTC, ETH, SOL) as directional positions, native staking/LST positions, or speculative exchange-traded tokens. Any derivatives/hedging positions not covered by existing categories are classified under Category F.

**Parties**: Bank Frick AG (Calculation Agent / Paying Agent / Custodian), ZEUS Anstalt (Investment Manager), Vistra (Administrator), ForDefi (on-chain custodian), Kraken (additional custodian), Grant Thornton (Auditor).

**Valuation frequency**: Monthly (last calendar day), with Valuation Time 16:00 CET (= 15:00 UTC year-round, no daylight saving adjustment).

**Valuation Block**: The block on each blockchain with timestamp closest to but NOT exceeding 15:00 UTC on the Valuation Date. All on-chain queries must be made at this block, not "latest".

**First NAV date**: 31 March 2026.

**NAV Report deadline**: Within 7 business days of the Valuation Date.

---

## Wallet Addresses

| Chain | Wallet | Description |
|-------|--------|-------------|
| Solana | ASQ4kYjSYGUYbbYtsaLhUeJS6RtrN4Uwp4XbF4gDifvr | Main Solana wallet |
| Ethereum | 0xa33e1f748754d2d624638ab335100d92fcbe62a2 | Open Market Positions |
| Ethereum | 0x6691005cd97656d488b72594c42cae987264e0e7 | Open Market Positions 2 |
| Ethereum | 0x0c1644d7af63df4a3b15423dbe04a1927c00a4f4 | Credit Positions |
| Ethereum | 0xec0b3a9321a5a0a0492bbe20c4d9cd908b10e21a | Credit Positions 2 |
| Ethereum | 0xaca2ef22f720ae3f622b9ce3065848c4333687ae | Multi-chain wallet |
| Ethereum | 0x80559941c1a741bc435cb6782b6f161d5772ac4b | Multi-chain wallet |

All EVM wallets are also used on Arbitrum, Base, Avalanche, Plasma, and HyperEVM as applicable.

---

## Asset Classification Framework

Every position falls into one of these categories. The category determines the valuation methodology. Full methodology details in `docs/internal/valuation_methodology.md`.

| Category | Description | Primary Valuation Source |
|----------|-------------|------------------------|
| **A1** | On-chain yield-bearing tokens (deterministic smart contract exchange rate). Note: sUSDe is A1 because its on-chain exchange rate is authoritative, even though underlying yield is off-chain | Smart contract query (e.g. convertToAssets, exchangeRate) |
| **A2** | Off-chain yield-bearing tokens (oracle/issuer NAV) | Oracle feed or issuer-published NAV |
| **A3** | Private credit vault tokens (manual accrual on contractual terms) | Principal + accrued interest from loan agreements |
| **B** | PT tokens (zero-coupon bond, linear amortisation to maturity) | Linear amortisation per individual lot |
| **C** | LP positions (AMM pool decomposition) | Decompose into constituent tokens, price each per its category |
| **D** | Leveraged positions (looping) | Net = Collateral value − Debt value |
| **E** | Stablecoins & cash | Par value (USDC-pegged) or oracle price (non-USDC-pegged) |
| **F** | Other / bespoke (governance tokens, YT, rewards) | Kraken price → CoinGecko → DEX TWAP |

---

## Project Structure

```
veris-nav/
├── CLAUDE.md                  # This file — project context hub
├── .env                       # API keys: Alchemy, Etherscan, CoinGecko Pro (gitignored)
├── .gitignore
├── requirements.txt           # Python dependencies
├── src/
│   ├── evm.py                 # Shared EVM utilities, constants (CET, TS_FMT), cached Web3
│   ├── block_utils.py         # Block estimation + concurrent RPC
│   ├── solana_client.py       # Solana RPC helpers (balances, eUSX rate, find_valuation_slot)
│   ├── pricing.py             # Price dispatcher (hierarchy walker, depeg checks, adapters)
│   ├── collect_balances.py    # Balance scanner library (query functions only, no standalone main)
│   ├── tools/                 # Standalone utilities (run separately)
│   │   ├── diff_snapshots.py      # Snapshot diff tool — compares two NAV snapshots
│   │   ├── cache_xlsx.py          # Cache xlsx sheets as CSVs for fast access
│   │   ├── extract_powerquery.py  # Extract Power Query M code from Excel
│   │   └── generate_methodology_pdf.py  # Generate methodology PDF from markdown
│   ├── falconx/               # FalconX/Pareto A3 position scripts (run before collect.py)
│   │   ├── update_falconx_optimized.py  # Hourly accrual data updater (writes to SQLite)
│   │   ├── import_falconx_xlsx_to_sqlite.py  # One-time xlsx→SQLite migration
│   │   └── query_pareto_tranche_history.py  # Pareto TP history for cross-reference
│   ├── collect.py             # Production orchestrator — parallel balance+protocol scanning, valuation, output (~95s)
│   ├── protocol_queries.py    # Thin dispatcher: handler registry, wallet→protocol mapping, orchestrators
│   ├── handlers/              # Protocol-specific position query handlers (one per protocol)
│   │   ├── morpho.py, erc4626.py, euler.py, aave.py, midas.py
│   │   ├── gauntlet.py, creditcoop.py, uniswap.py, ethena.py
│   │   └── kamino.py, exponent.py, pt_lots.py
│   ├── valuation.py           # Category-specific valuation with config-driven pricing indices
│   └── output.py              # NAV snapshot writer (positions.csv/json, leverage_detail, pt_lots, lp_decomposition, nav_summary)
├── config/
│   ├── chains.json            # Chain configs — RPC URLs, chain IDs, explorers
│   ├── wallets.json           # Wallet addresses per chain with protocol registrations
│   ├── tokens.json            # Token registry — whitelist per chain with pricing config
│   ├── contracts.json         # Protocol contracts with _query_type fields for handler dispatch
│   ├── solana_protocols.json  # Solana protocol configs (Kamino obligations, Exponent markets)
│   ├── abis.json              # Minimal ABIs for all contract interactions
│   ├── morpho_markets.json    # Morpho market IDs and position configs
│   ├── price_feeds.json       # Registry of all available price feeds
│   ├── pricing_policy.json    # Per-category pricing hierarchy rules
│   └── pt_lots.json           # PT token individual lot details
├── plans/                     # Implementation plans
├── cache/                     # Cached xlsx sheets as CSVs (gitignored)
├── outputs/                   # Generated snapshots (gitignored)
│   ├── wallet_balances.json   # Latest wallet balance snapshot with methodology header
│   ├── wallet_balances.csv    # Same data in CSV format
│   ├── falconx_position.xlsx  # FalconX/Pareto A3 accrual workbook
│   └── pareto_tranche_price_history.json  # TP update history
├── docs/
│   ├── internal/                  # Internal reference docs (for Claude/developers)
│   │   ├── protocol_sourcing.md       # Protocol-by-protocol position reading guide
│   │   ├── valuation_methodology.md   # Full A1–F valuation rules
│   │   ├── nav_output_spec.md         # Output format, NAV formula, divergence tolerances
│   │   ├── portfolio_positions.md     # Current positions by category
│   │   ├── data_sources.md            # Oracle feeds, APIs, RPC endpoints
│   │   └── architecture.md            # System design, pricing architecture
│   ├── methodology/               # Methodology deliverables (for Bank Frick / audit)
│   │   ├── NAV_Data_Sourcing_Methodology.md   # NAV report methodology section
│   │   ├── NAV_Data_Sourcing_Methodology.pdf
│   │   └── falconx_accrual_analysis.md        # FalconX A3 position methodology
│   └── reference/                 # Source documents (Valuation Policy, loan notices, Midas reports)
└── README.md
```

---

## Compliance Testing

The system must have automated tests that verify the valuation methodology matches the Valuation Policy (`docs/reference/23-03-2026_Veris_Capital_AMC_Valuation_Policy DRAFT_v.1.0.pdf`). Tests should be strict and cover:

- **Category classification**: Every token in `tokens.json` must have a valid category (A1-F) matching the Policy Section 5 definitions
- **Primary pricing source per category**: A1 uses smart contract exchange rate, A2 uses oracle hierarchy (Chainlink → Pyth → Redstone → Issuer NAV → CoinGecko → DEX TWAP), E par-priced tokens have depeg monitoring, F uses Kraken → CoinGecko → DEX TWAP
- **Fallback source configuration**: Every A2 token must have at least one fallback source configured. Every E token with `method: "par"` should have a depeg check feed (Chainlink or Pyth). Every F token with Kraken primary should have CoinGecko fallback.
- **Staleness thresholds**: Every A2 token must have `expected_update_freq_hours` configured. The staleness flag threshold is 2x the expected frequency per Section 6.2.
- **Divergence tolerances**: Output should flag positions exceeding Appendix B thresholds (A1: 2%, A2: 3%, A3: 5%, B: 6%, C: 5%, D: 5%, E: 0.5%, F: 10%)
- **Category-specific methodology**: A1 = convertToAssets, A3 = manual accrual (not on-chain TP), B = linear amortisation per lot (not AMM price), C = decomposition with PT in LP using AMM rate (not lot amortisation), D = net (collateral − debt)

Run tests with: `python -m unittest discover -s tests -v`

---

## Development Guidelines

- Keep the code readable — Bank Frick will review it
- Log every query: contract address, function called, block number, result
- Use `.env` for all API keys and RPC URLs
- Output timestamps in UTC, formatted as `dd/mm/yyyy hh:mm:ss` (e.g. `23/03/2026 19:21:35`)
- Use `decimal.Decimal` for financial calculations, not float
- Each function should do one thing clearly
- Add comments explaining the "why" for non-obvious logic (e.g. why sUSDe is A1 not A2)
