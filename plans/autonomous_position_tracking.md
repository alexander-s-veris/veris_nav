# Autonomous Position Tracking System

## Problem

Current workflow relies on manual position discovery via portfolio dashboards (DeBank, ForDefi, Kamino UI). This is:
- **Unreliable** — dashboards miss positions, misclassify tokens, or lag behind on-chain state
- **Not auditable** — no record of how positions were discovered
- **Not scalable** — every new protocol interaction requires manual walkthrough
- **Institutional-grade NAV requires** complete, independently verifiable position inventory sourced from on-chain data

## Vision

Agents running periodically that:
1. Scan all wallet transaction history across all chains
2. Discover every protocol interaction and token movement
3. Identify live positions, closed positions, and new positions
4. Auto-register new tokens and protocols in config files
5. Search for protocol GitHub repos, apply appropriate methodology
6. Calculate PnL per position using the correct category methodology
7. Flag positions that need human review (new protocols, unusual patterns)

## Architecture

### Layer 1: Transaction History Scanner (async, periodic)

For each wallet on each chain, maintain a cursor of the last processed transaction. On each run:

**EVM chains:**
- Etherscan V2 `txlist` + `tokentx` + `internaltx` for each wallet
- Parse every transaction for:
  - Token transfers in/out (ERC-20 Transfer events)
  - Contract interactions (which protocols did the wallet call?)
  - New token contracts not in `tokens.json`
  - New protocol contracts not in `contracts.json`

**Solana:**
- `getSignaturesForAddress` for wallet + all known token accounts
- `getTransaction` with `jsonParsed` for each new signature
- Parse pre/post token balance changes per mint
- `getProgramAccounts` with discriminator filters for PDA-based positions (LP, YT, obligations)

**Output:** Append-only transaction log per wallet, with structured events:
```json
{
  "chain": "ethereum",
  "wallet": "0xa33e...",
  "tx_hash": "0x...",
  "timestamp": "2026-03-27T15:00:00Z",
  "block": 12345678,
  "events": [
    {"type": "token_transfer", "token": "USCC", "amount": 1000, "direction": "in", "counterparty": "0x..."},
    {"type": "protocol_interaction", "protocol": "morpho", "contract": "0xBBBB...", "method": "supply"}
  ]
}
```

### Layer 2: Position State Tracker

Maintains a live position inventory by processing the transaction log:

- **Token balances**: Running balance per token per wallet per chain. Simple sum of in/out transfers.
- **Protocol positions**: Detect open/close events:
  - Morpho: `supply` opens, `withdraw` closes (or reduces)
  - Aave: aToken minting = open, burning = close
  - Kamino: obligation creation = open, full repay = close
  - Exponent: LP position init = open, full remove = close
  - PT lots: each swap = new lot, maturity = close
- **Position lifecycle**: Track opened_at, last_updated, closed_at, current_balance
- **PnL calculation**: Apply category methodology to compute unrealised PnL:
  - A1: convertToAssets growth since deposit
  - A2: oracle price change × balance
  - A3: manual accrual (interest earned)
  - B: linear amortisation yield since purchase
  - C: LP decomposition value change
  - D: net position value change
  - E: par (no PnL unless de-peg)
  - F: market price change

**Output:** `positions_state.json` — complete inventory of all live and closed positions with PnL.

### Layer 3: Protocol Discovery Agent (async, on-demand)

Triggered when Layer 1 detects an unknown contract interaction:

1. Look up the contract on the block explorer (Etherscan / Solscan)
2. Identify the protocol (check known protocol contract patterns first)
3. If unknown: search GitHub for the protocol, find the ABI / IDL
4. Classify the position type (A1-F) based on the contract interface
5. Register in `contracts.json`, `tokens.json`, `abis.json`
6. Flag for human review before including in NAV

**Key principle**: Auto-discover, auto-classify, but **human approval** before inclusion in NAV. The agent proposes; the Investment Manager confirms.

### Layer 4: Valuation Agent (scheduled, pre-NAV)

Runs before each NAV date to produce the snapshot:

1. Read position inventory from Layer 2
2. For each position, query on-chain state at the Valuation Block slot/block
3. Apply pricing per category methodology
4. Cross-reference against verification sources (DeBank, Octav)
5. Flag divergences exceeding tolerance thresholds
6. Produce the NAV snapshot file

This is essentially the current `collect.py` + `valuation.py` + `output.py` but informed by the position inventory from Layer 2 rather than manual config.

## Implementation Phases

### Phase 1: Transaction log (foundation)
- Build transaction history scanner for all wallets/chains
- Store append-only log with structured events
- Run as a scheduled agent (daily or more frequent)
- Compare against current `wallet_balances.json` for validation

### Phase 2: Position state tracking
- Process transaction log into position inventory
- Detect open/close events per protocol
- Maintain running balances and lot tracking
- Replace manual position registration in configs

### Phase 3: Protocol discovery
- Auto-detect new contract interactions
- Pattern-match against known protocol types (ERC-4626, Morpho, Aave, etc.)
- For unknown protocols: search GitHub, fetch ABI/IDL, propose classification
- Human-in-the-loop approval for new positions

### Phase 4: PnL and full automation
- Calculate PnL per position using category methodology
- Generate position reports with historical performance
- Integrate with NAV valuation pipeline
- Full end-to-end: tx scan → position tracking → valuation → NAV snapshot

## Key Design Decisions

- **Append-only transaction log** — never delete historical data, enables audit trail
- **Config files remain source of truth for methodology** — the agent updates them, but methodology (category, pricing method) is human-approved
- **Human-in-the-loop for new protocols** — auto-discovery proposes, human confirms before NAV inclusion
- **Periodic async execution** — agents run on schedule (Claude Code triggers or cron), not blocking the NAV process
- **Chain-agnostic event model** — same event structure for EVM and Solana, different scanners per chain

## Dependencies

- Etherscan V2 API (EVM transaction history)
- Solana RPC (transaction history, getProgramAccounts)
- Existing `src/` modules (pricing, block_utils, solana_client)
- Claude Code scheduled agents or external cron for periodic execution
- GitHub API for protocol discovery (optional, can be manual)

## Relationship to Existing Plans

- Supersedes `plans/change_detection_agent.md` (which was the simpler version of this idea)
- Builds on top of the existing position collection pipeline (`collect_balances.py`, `solana_client.py`, `pt_valuation.py`)
- The output schema from `plans/output_schema_plan.md` remains the target format
