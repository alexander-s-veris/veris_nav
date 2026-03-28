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

---

## Architecture

### Layer 1: Transaction History Scanner

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

**Output:** Append-only transaction log per wallet, with structured events.

### Layer 2: Position State Tracker

Maintains a live position inventory by processing the transaction log:

- **Token balances**: Running balance per token per wallet per chain
- **Protocol positions**: Detect open/close events per protocol type
- **Position lifecycle**: Track opened_at, last_updated, closed_at, current_balance
- **PnL calculation**: Apply category methodology to compute unrealised PnL

### Layer 3: Protocol Discovery Agent

Triggered when Layer 1 detects an unknown contract interaction:

1. Look up the contract on the block explorer (Etherscan / Solscan)
2. Identify the protocol (check known protocol contract patterns first)
3. If unknown: search GitHub for the protocol, find the ABI / IDL
4. Classify the position type (A1-F) based on the contract interface
5. Register in `contracts.json`, `tokens.json`, `abis.json`
6. Flag for human review before including in NAV

**Key principle**: Auto-discover, auto-classify, but **human approval** before inclusion in NAV. The agent proposes; the Investment Manager confirms.

### Layer 4: Valuation Agent

Runs before each NAV date to produce the snapshot. Essentially the current `collect.py` pipeline but informed by the position inventory from Layer 2 rather than manual config.

---

## Implementation with Claude Agentic Stack

The original plan assumed external cron or manual triggering. Claude's agentic tooling now provides native infrastructure for each layer.

### Scheduling Options

| Method | Persistence | Use Case |
|--------|-------------|----------|
| **CronCreate** (session-scoped) | Dies with session, 7-day max | Dev/testing: `CronCreate("7 */6 * * *", "scan wallets for changes")` |
| **Durable scheduled tasks** | Survives restarts | Production monitoring: runs every 6 hours unattended |
| **Agent SDK** + system cron | Full control | Production: Python script triggered by OS cron, uses Agent SDK for Claude reasoning |

For production NAV monitoring, **Agent SDK + system cron** is the most reliable — no dependency on a live Claude session.

### Agent SDK for Autonomous Monitoring

Each layer maps to an Agent SDK invocation:

```python
# Layer 1: Transaction scanner (runs every 6 hours)
from claude_agent_sdk import query, ClaudeAgentOptions

async for msg in query(
    prompt="Scan all wallets in config/wallets.json for new transactions since last scan. "
           "Log new protocol interactions, token movements, balance changes. "
           "Flag anything not in contracts.json or tokens.json.",
    options=ClaudeAgentOptions(
        allowed_tools=["Read", "Bash", "Write", "Grep"],
        permission_mode="acceptEdits",
        mcp_servers={"blockchain": {"type": "stdio", "command": "python", "args": ["src/mcp/rpc_server.py"]}}
    ),
):
    ...
```

Key Agent SDK features for this system:
- **Sessions API** — resume context across runs (session_id persistence). The scanner can remember where it left off without re-scanning everything.
- **Permission modes** — `acceptEdits` for config updates, read-only for scanning.
- **MCP servers** — custom blockchain RPC server provides structured access to Alchemy/Etherscan without Claude constructing raw curl commands.

### MCP Server for Blockchain Access

A custom MCP server wraps our existing `src/` modules:

```python
# src/mcp/rpc_server.py — exposes existing code as MCP tools
# Tools: get_wallet_balances, query_protocol_positions, get_oracle_price,
#        get_block_at_timestamp, query_transaction_history
```

This gives Claude structured, validated blockchain access instead of raw RPC calls. The MCP server:
- Reuses `evm.py`, `block_utils.py`, `solana_client.py`, `collect_balances.py`
- Enforces read-only access (no state-changing transactions)
- Caches results to respect RPC rate limits
- Returns typed results (Decimal amounts, formatted timestamps)

### Hooks for Validation and Audit

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Write",
      "hooks": [{
        "type": "command",
        "command": "python src/hooks/validate_config_change.py"
      }]
    }],
    "PostToolUse": [{
      "matcher": "Bash",
      "hooks": [{
        "type": "command",
        "command": "python src/hooks/audit_log.py"
      }]
    }]
  }
}
```

- **PreToolUse** on Write: validate that config changes follow architecture principles (required fields, no hardcoded values, single source of truth)
- **PostToolUse** on Bash: audit log of all RPC calls for compliance record-keeping (Valuation Policy Section 12)

### Subagents for Parallel Chain Scanning

Layer 1 can be parallelized with subagents — one per chain:

```yaml
# .claude/agents/chain-scanner.md
---
name: chain-scanner
description: Scans a single chain for wallet activity changes
tools: Read, Bash, Grep
model: haiku  # Fast and cheap for polling
---
Scan the specified chain for new transactions across all configured wallets.
Compare against last known state. Report new interactions, balance changes,
and unknown contracts.
```

Haiku model keeps cost low for high-frequency polling. The main agent orchestrates, subagents do the per-chain work in parallel.

### Agent Teams for NAV Day

On Valuation Date, spawn a team for parallel collection:

```
Teammate 1: EVM balance collection (all chains)
Teammate 2: Protocol position queries (Morpho, Aave, Euler, Midas, Credit Coop)
Teammate 3: Solana positions (Kamino, Exponent, PT lots)
Teammate 4: Pricing (oracle queries, CoinGecko, Kraken)
Teammate 5: Verification (attestation cross-checks, divergence flags)
```

Each teammate has independent context and coordinates via shared task list. Results merge into the final NAV snapshot. This parallelizes what `collect.py` currently does sequentially in Steps 1-4.5.

Requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (opt-in, experimental).

---

## Implementation Phases

### Phase 1: MCP server + basic monitoring
- Build `src/mcp/rpc_server.py` wrapping existing modules
- Create transaction diff script (compare current vs last snapshot)
- Schedule via CronCreate for testing, then durable task for production
- Output: change report flagging new contracts/tokens

### Phase 2: Agent SDK scanner
- Agent SDK script for automated scanning with session persistence
- Transaction log with append-only storage
- Protocol pattern matching against known types
- Human-in-the-loop approval via AskUserQuestion for new positions

### Phase 3: Full position tracking
- Position lifecycle management (open/close detection)
- Running balance reconciliation against on-chain state
- Config auto-registration (proposed changes, human-approved)
- PnL calculation per category methodology

### Phase 4: NAV Day automation
- Agent team for parallel collection across chains
- Automated verification pipeline (attestation + portfolio-level)
- NAV report generation with full methodology log
- Pre-flight checks before submitting to Calculation Agent

---

## Key Design Decisions

- **Append-only transaction log** — never delete historical data, enables audit trail
- **Config files remain source of truth for methodology** — agents propose changes, but methodology (category, pricing method) is human-approved
- **Human-in-the-loop for new protocols** — auto-discovery proposes, human confirms before NAV inclusion
- **MCP server wraps existing code** — no rewriting; the MCP server exposes `src/` modules as structured tools
- **Subagents for cost efficiency** — Haiku for polling/scanning, Opus for reasoning/classification
- **Hooks for compliance** — every RPC call and config change is logged per Valuation Policy Section 12

## Dependencies

- Claude Agent SDK (Python)
- Etherscan V2 API (EVM transaction history)
- Solana RPC (transaction history, getProgramAccounts)
- Existing `src/` modules (pricing, block_utils, solana_client, collect_balances)
- MCP server runtime (stdio transport)
