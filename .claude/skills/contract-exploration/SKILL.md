---
name: contract-exploration
description: Explore new smart contracts by querying them directly via RPC, not browsing Etherscan
---

# Smart Contract Exploration

When encountering a new or unfamiliar smart contract, **query it directly via RPC** using `src/evm.py` utilities. Do not browse Etherscan pages repeatedly -- probe the contract with known function signatures first.

## Step 1: Set up Web3 connection

```python
from src.evm import get_web3, get_block_info
w3 = get_web3("ethereum")  # cached, PoA middleware auto-injected
block, ts = get_block_info(w3)
```

Available EVM chains: `ethereum`, `arbitrum`, `base`, `avalanche`, `plasma`, `hyperevm`, `katana` (all configured in `config/chains.json`).

For Solana, see the Solana section below.

## Step 2: Probe standard interfaces

Build an inline ABI with common functions and call them. Wrap each in try/except -- a failed call just means the function doesn't exist.

**Try in this order:**

### ERC-20 basics (almost every token/vault)
- `name()` -> string
- `symbol()` -> string
- `decimals()` -> uint8
- `balanceOf(address)` -> uint256
- `totalSupply()` -> uint256

### ERC-4626 vault (most yield-bearing positions)
- `asset()` -> address (underlying token)
- `totalAssets()` -> uint256
- `convertToAssets(uint256 shares)` -> uint256
- `sharePrice()` -> uint256 (non-standard but common)

### Strategy / sub-allocation (multi-strategy vaults)
- `totalLiquidAssets()` -> uint256
- `liquidStrategy()` -> address
- `creditStrategy()` -> address
- `numCreditPositions()` -> uint256
- `totalActiveCredit()` -> uint256

### Chainlink oracle
- `latestRoundData()` -> (roundId, answer, startedAt, updatedAt, answeredInRound)
- `decimals()` -> uint8
- `description()` -> string

### Lending protocol (Morpho, Aave)
- `position(bytes32 id, address user)` -> Morpho market position
- `market(bytes32 id)` -> Morpho market state
- `getUserAccountData(address)` -> Aave aggregate position

## Step 3: Follow references

If a contract returns sub-contract addresses (strategies, lines, pools), query those the same way. To check USDC balances at each address, use the `erc20` ABI from `config/abis.json`:

```python
from src.handlers import _get_abi
erc20_abi = _get_abi("erc20")
# Get USDC address from config/tokens.json for the relevant chain
usdc = w3.eth.contract(address=w3.to_checksum_address(usdc_addr), abi=erc20_abi)
balance = usdc.functions.balanceOf(w3.to_checksum_address(addr)).call()
```

## Step 4: Check known vault holdings

If a strategy deposits into known vaults, check share balances:
```python
erc4626_abi = _get_abi("erc4626")
vault = w3.eth.contract(address=vault_addr, abi=erc4626_abi)
shares = vault.functions.balanceOf(strategy_addr).call()
if shares > 0:
    assets = vault.functions.convertToAssets(shares).call()
```

## Step 5: Check transaction history

When contract probing is ambiguous -- unknown token types, unclear position mechanics, or unrecognised contract interactions -- check the wallet's transaction history for that token/contract:

- **EVM**: Etherscan V2 API `tokentx` or `txlist` for the wallet, filtered by contract address. Shows token transfers with from/to/value, revealing what flows in and out of protocol interactions.
- **Solana**: `getSignaturesForAddress` on the wallet's token account, then `getTransaction` with `jsonParsed` to see pre/post balance changes per mint.

This reveals:
- What tokens were swapped for what (identifies unknown mints)
- Whether a token was received from an LP withdrawal, swap, or transfer
- The purchase price / cost basis for lot tracking (PT tokens, etc.)

More reliable than guessing from struct field ordering or contract ABI analysis alone.

## Step 6: Only use Etherscan as last resort

If direct probing fails (no standard interface, unknown function signatures), then fetch the Etherscan contract page **once** to read the ABI or source code. Do not make multiple Etherscan round-trips.

## Step 7: Onboard into the system

After successful exploration, add the new position to the config-driven system (see `docs/internal/architecture.md` for the full pattern):

1. Add contracts to `config/contracts.json` with `_query_type` and descriptions
2. Add new ABIs to `config/abis.json` if they introduce new function signatures
3. Add tokens to `config/tokens.json` with category, decimals, and pricing config
4. Add wallet protocol registration to `config/wallets.json` (e.g. `"new_protocol": true`)
5. If new protocol type: add handler to `src/handlers/` and register in `protocol_queries.py`
6. Document read mechanics in `docs/internal/protocol_sourcing.md`

For standard patterns (ERC-4626, Morpho market, Aave, Midas oracle), only steps 1-4 are needed -- no code changes.

## Common pitfalls

| Pitfall | Solution |
|---------|----------|
| **Decimals vary** | Always query `decimals()`. USDC = 6, most tokens = 18, Chainlink feeds = 8 |
| **Proxy contracts** | Call functions on the proxy address (it delegates to impl). Don't call impl directly |
| **Stale on-chain prices** | Some prices update infrequently (Pareto TP = ~monthly). Check `updatedAt` timestamp |
| **Euler sub-accounts** | XOR-based addressing (wallet XOR 0-255). Must scan all 256 to discover balances |
| **Shares vs assets** | Morpho supply/borrow are in shares -- convert via market state. Aave aTokens are already in underlying terms |
| **Reverted calls** | `('execution reverted', 'no data')` = function doesn't exist on this contract. Move on |
| **Non-ERC-4626 vaults** | Some vaults (Gauntlet) are custom. Check for `convertToAssets` first, fall back to `totalSupply` + pro-rata |

## Existing project ABIs (`config/abis.json`)

| Key | Functions | Used for |
|-----|-----------|----------|
| `erc20` | balanceOf, totalSupply, decimals, name, symbol | Token balances everywhere |
| `erc4626` | ERC-20 + convertToAssets, totalAssets, asset | Morpho/Euler/Ethena/Avantis/Yearn vaults |
| `morpho_core` | position, market | Morpho market positions (D) |
| `chainlink_aggregator_v3` | latestRoundData, decimals, description | Oracle pricing (A2, E) |
| `aave_pool` | getUserAccountData | Aave aggregate position check |
| `pareto_credit_vault` | tranchePrice, getApr, getContractValue, epoch functions | FalconX A3 cross-reference |
| `credit_coop_vault` | convertToAssets, totalAssets, totalActiveCredit, totalLiquidAssets, sub-strategy queries | Credit Coop vault (A1) + methodology breakdown |
| `erc4337_account` | implementation | ARMA/Giza smart account proxy detection |

## Solana equivalent

This skill covers EVM contract exploration. For Solana protocols, the approach differs:

1. **No universal ABI** -- use the protocol's Anchor IDL or SDK to understand account structures
2. **Probe accounts** via `getAccountInfo` -> deserialize binary data using known byte offsets
3. **Transaction history** via `getSignaturesForAddress` on the wallet's **token account** (not wallet itself)
4. **REST APIs** (e.g. `api.kamino.finance`) for initial discovery, not for NAV

Implemented Solana helpers:
- `src/solana_client.py` -- RPC calls, eUSX exchange rate, Kamino obligation parsing, Exponent market/LP/YT position reading
- `src/pt_valuation.py` -- PT lot discovery from on-chain tx history + linear amortisation

Key patterns:
- Use **Alchemy** for both `getProgramAccounts` (discovery) and `getAccountInfo` (valuation block queries). Note: `getProgramAccounts` is slow and rate-limited on Alchemy -- use sparingly, cache results in `config/solana_protocols.json`
- Scan binary data for expected value ranges (f64 rates, timestamps) to find field offsets -- faster than computing from Rust structs
- LP and YT positions are PDA accounts, not SPL tokens -- invisible to wallet balance scans
- **Transaction history as token identity fallback**: when struct field analysis is ambiguous about what a token mint is (SY vs PT vs LP), check `getSignaturesForAddress` on the token account and parse the balance changes. Token flows in/out of swaps and LP withdrawals definitively identify each mint.

See `docs/internal/protocol_sourcing.md` -> "Solana sourcing approach" for the full methodology.

## Concurrency for bulk queries

For scanning multiple addresses or blocks, use `src/block_utils.py`:
```python
from src.block_utils import concurrent_query, concurrent_query_batched
results = concurrent_query(query_fn, items, max_workers=10)
```
10 workers is optimal for Alchemy (~22 queries/s). Auto-retries on 429 rate limits.
