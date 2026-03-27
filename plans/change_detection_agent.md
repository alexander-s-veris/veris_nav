# Change Detection Agent — Future Enhancement

## Problem

Currently, new protocol positions are discovered manually by checking DeBank or similar portfolio trackers. This is error-prone and time-consuming. If a wallet interacts with a new protocol between Valuation Dates, it could be missed.

## Proposed Solution

A periodic change detection agent that monitors wallet activity and flags changes for manual review.

### Scope

1. **Balance diffing**: Compare current token balances against the last known snapshot. Flag:
   - New tokens appearing in a wallet (possible new protocol interaction)
   - Tokens going to zero (position closed or migrated)
   - Large balance changes (>10% delta)

2. **Transaction scanning**: Pull recent transaction history via Alchemy/Etherscan since last scan. Flag:
   - Interactions with contracts not in `config/contracts.json`
   - Approvals to unknown spenders

3. **Alerting**: Output a change report for manual review. The operator identifies the protocol and registers it in configs (`tokens.json`, `contracts.json`, `morpho_markets.json`, etc.).

### What This Does NOT Do

- Auto-decode protocol positions (each protocol needs hand-coded reading logic)
- Replace the manual walkthrough for new protocols
- Cover Solana — tooling now exists: `getProgramAccounts` with discriminator filters on public RPC for PDA-based positions (LP, YT), `getTokenAccountsByOwner` for SPL tokens, `getSignaturesForAddress` on token accounts for tx history

## Why Not Full Auto-Decode

DeBank maintains decoders for thousands of protocols with a large team. For our scale (~7 wallets, ~20 protocols), the ROI isn't there. New protocol interactions happen infrequently — the 80/20 is: **detect changes automatically, register positions manually**.

## Dependencies

- `collect_balances.py` (already built) — provides the baseline snapshot to diff against
- Alchemy/Etherscan transaction history APIs
- Existing config files as the "known" registry

## Priority

Post-launch. Build after core NAV collection pipeline is production-ready and validated for the first NAV date (30 April 2026).
