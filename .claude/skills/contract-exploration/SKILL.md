---
name: contract-exploration
description: Explore new smart contracts by querying them directly via RPC, not browsing Etherscan
---

# Smart Contract Exploration

When encountering a new or unfamiliar smart contract, **query it directly via RPC** using `src/evm.py` utilities. Do not browse Etherscan pages repeatedly — probe the contract with known function signatures first.

## Step 1: Set up Web3 connection

```python
from src.evm import get_web3, get_block_info
w3 = get_web3("ethereum")  # cached, PoA middleware auto-injected
block, ts = get_block_info(w3)
```

Available chains: `ethereum`, `arbitrum`, `base`, `avalanche`, `plasma`, `hyperevm`, `katana`.

## Step 2: Probe standard interfaces

Build an inline ABI with common functions and call them. Wrap each in try/except — a failed call just means the function doesn't exist.

**Try in this order:**

### ERC-20 basics (almost every token/vault)
- `name()` → string
- `symbol()` → string
- `decimals()` → uint8
- `balanceOf(address)` → uint256
- `totalSupply()` → uint256

### ERC-4626 vault (most yield-bearing positions)
- `asset()` → address (underlying token)
- `totalAssets()` → uint256
- `convertToAssets(uint256 shares)` → uint256
- `sharePrice()` → uint256 (non-standard but common)

### Strategy / sub-allocation (multi-strategy vaults)
- `totalLiquidAssets()` → uint256
- `liquidStrategy()` → address
- `creditStrategy()` → address
- `numCreditPositions()` → uint256

### Chainlink oracle
- `latestRoundData()` → (roundId, answer, startedAt, updatedAt, answeredInRound)
- `decimals()` → uint8
- `description()` → string

### Lending protocol (Morpho, Aave)
- `position(bytes32 id, address user)` → Morpho market position
- `market(bytes32 id)` → Morpho market state
- `getUserAccountData(address)` → Aave aggregate position

## Step 3: Follow references

If a contract returns sub-contract addresses (strategies, lines, pools), query those the same way. Check USDC balances at each address to find idle cash:

```python
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
usdc = w3.eth.contract(address=w3.to_checksum_address(USDC), abi=erc20_abi)
balance = usdc.functions.balanceOf(w3.to_checksum_address(addr)).call()
```

## Step 4: Check known vault holdings

If a strategy deposits into known vaults, check share balances:
```python
vault = w3.eth.contract(address=vault_addr, abi=erc4626_abi)
shares = vault.functions.balanceOf(strategy_addr).call()
if shares > 0:
    assets = vault.functions.convertToAssets(shares).call()
```

## Step 5: Only use Etherscan as last resort

If direct probing fails (no standard interface, unknown function signatures), then fetch the Etherscan contract page **once** to read the ABI or source code. Do not make multiple Etherscan round-trips.

## Step 6: Document findings

After successful exploration:
1. Add contracts to `config/contracts.json` with descriptions
2. Add new ABIs to `config/abis.json` if they introduce new function signatures
3. Add the protocol to `protocol_sourcing.md` with read instructions
4. Add tokens to `config/tokens.json` with pricing config

## Common pitfalls

| Pitfall | Solution |
|---------|----------|
| **Decimals vary** | Always query `decimals()`. USDC = 6, most tokens = 18, Chainlink feeds = 8 |
| **Proxy contracts** | Call functions on the proxy address (it delegates to impl). Don't call impl directly |
| **Stale on-chain prices** | Some prices update infrequently (Pareto TP = ~monthly). Check `updatedAt` timestamp |
| **Euler sub-accounts** | XOR-based addressing (wallet XOR 0–255). Must scan all 256 to discover balances |
| **Shares vs assets** | Morpho supply/borrow are in shares — convert via market state. Aave aTokens are already in underlying terms |
| **Reverted calls** | `('execution reverted', 'no data')` = function doesn't exist on this contract. Move on |
| **Non-ERC-4626 vaults** | Some vaults (Gauntlet) are custom. Check for `convertToAssets` first, fall back to `totalSupply` + pro-rata |

## Existing project ABIs (`config/abis.json`)

| Key | Functions | Used for |
|-----|-----------|----------|
| `erc20` | balanceOf, totalSupply, decimals, name, symbol | Token balances everywhere |
| `erc4626` | ERC-20 + convertToAssets, totalAssets, asset | Morpho/Euler/Ethena/CreditCoop vaults |
| `morpho_core` | position, market | Morpho market positions (D) |
| `chainlink_aggregator_v3` | latestRoundData, decimals, description | Oracle pricing (A2, E) |
| `aave_pool` | getUserAccountData | Aave aggregate position check |
| `pareto_credit_vault` | tranchePrice, getApr, getContractValue, epoch functions | FalconX A3 cross-reference |
| `ethena_cooldown` | cooldowns | sUSDe pending unstakes |
| `credit_coop_vault` | balanceOf, convertToAssets | Credit Coop vault (A1) |

## Solana equivalent

This skill covers EVM contract exploration. For Solana protocols, the approach differs:

1. **No universal ABI** — use the protocol's Anchor IDL or SDK to understand account structures
2. **Probe accounts** via `getAccountInfo` → deserialize binary data using known byte offsets
3. **Transaction history** via `getSignaturesForAddress` on the wallet's **token account** (not wallet itself)
4. **REST APIs** (e.g. `api.kamino.finance`) for initial discovery, not for NAV

Implemented Solana helpers:
- `src/solana_client.py` — RPC calls, eUSX exchange rate, Kamino obligation parsing
- `src/pt_valuation.py` — PT lot discovery from on-chain tx history + linear amortisation

See `protocol_sourcing.md` → "Solana sourcing approach" for the full methodology.

## Concurrency for bulk queries

For scanning multiple addresses or blocks, use `src/block_utils.py`:
```python
from src.block_utils import concurrent_query, concurrent_query_batched
results = concurrent_query(query_fn, items, max_workers=10)
```
10 workers is optimal for Alchemy (~22 queries/s). Auto-retries on 429 rate limits.
