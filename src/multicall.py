"""
Multicall3 utility for batching EVM contract reads into single RPC calls.

Aggregates multiple eth_call operations via the Multicall3 contract
(deployed at same address on all major EVM chains).

Usage:
    from multicall import multicall, encode_balance_of

    results = multicall(w3, "ethereum", [
        (token_addr, encode_balance_of(wallet)),
        (oracle_addr, encode_chainlink_latest_round_data()),
    ])
    # results: list of (success: bool, return_data: bytes)
"""

import logging

from web3 import Web3

from evm import load_chains

logger = logging.getLogger(__name__)

MULTICALL3_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "target", "type": "address"},
                    {"name": "allowFailure", "type": "bool"},
                    {"name": "callData", "type": "bytes"},
                ],
                "name": "calls",
                "type": "tuple[]",
            }
        ],
        "name": "aggregate3",
        "outputs": [
            {
                "components": [
                    {"name": "success", "type": "bool"},
                    {"name": "returnData", "type": "bytes"},
                ],
                "name": "returnData",
                "type": "tuple[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

# Max calls per multicall to stay under gas/calldata limits
MAX_BATCH_SIZE = 50


def get_multicall3_address(chain: str) -> str | None:
    """Get Multicall3 contract address for a chain from chains.json."""
    chains = load_chains()
    return chains.get(chain, {}).get("multicall3")


def multicall(
    w3: Web3,
    chain: str,
    calls: list[tuple[str, bytes]],
    block_identifier: int | str = "latest",
    batch_size: int = MAX_BATCH_SIZE,
) -> list[tuple[bool, bytes]]:
    """Execute multiple contract reads in a single RPC call.

    Args:
        w3: Web3 instance for the target chain.
        chain: Chain name (for looking up Multicall3 address in chains.json).
        calls: List of (contract_address, encoded_call_data) tuples.
        block_identifier: Block number or 'latest'.
        batch_size: Max calls per aggregate3 invocation.

    Returns:
        List of (success, return_data) tuples, same length and order as calls.
        Falls back to individual eth_call on chains without Multicall3.
    """
    if not calls:
        return []

    mc3_addr = get_multicall3_address(chain)

    if not mc3_addr:
        return _fallback_individual(w3, calls, block_identifier)

    mc3 = w3.eth.contract(
        address=Web3.to_checksum_address(mc3_addr),
        abi=MULTICALL3_ABI,
    )

    all_results = []
    total_batches = (len(calls) + batch_size - 1) // batch_size

    for batch_idx in range(0, len(calls), batch_size):
        batch = calls[batch_idx:batch_idx + batch_size]
        call_structs = [
            (Web3.to_checksum_address(target), True, calldata)
            for target, calldata in batch
        ]

        batch_num = batch_idx // batch_size + 1
        logger.info("multicall3.aggregate3(%s) chain=%s block=%s batch=%d/%d calls=%d",
                     mc3_addr[:10], chain, block_identifier, batch_num, total_batches, len(batch))

        try:
            raw_results = mc3.functions.aggregate3(call_structs).call(
                block_identifier=block_identifier
            )
            for success, return_data in raw_results:
                all_results.append((success, bytes(return_data)))
        except Exception as e:
            logger.warning("multicall3 batch %d/%d failed on %s: %s — falling back to individual calls",
                            batch_num, total_batches, chain, e)
            # Fallback this batch to individual calls
            all_results.extend(_fallback_individual(w3, batch, block_identifier))

    return all_results


def _fallback_individual(w3, calls, block_identifier):
    """Execute calls individually when Multicall3 is unavailable or fails."""
    results = []
    for target, calldata in calls:
        try:
            result = w3.eth.call(
                {"to": Web3.to_checksum_address(target), "data": calldata},
                block_identifier=block_identifier,
            )
            results.append((True, bytes(result)))
        except Exception:
            results.append((False, b""))
    return results


# ---------------------------------------------------------------------------
# Calldata encoding helpers for common patterns
# ---------------------------------------------------------------------------

def encode_balance_of(wallet: str) -> bytes:
    """Encode balanceOf(address) — ERC-20 standard."""
    # selector: 0x70a08231
    return bytes.fromhex("70a08231" + wallet[2:].lower().zfill(64))


def encode_decimals() -> bytes:
    """Encode decimals() — ERC-20 standard."""
    return bytes.fromhex("313ce567")


def encode_total_supply() -> bytes:
    """Encode totalSupply() — ERC-20 standard."""
    return bytes.fromhex("18160ddd")


def encode_convert_to_assets(shares: int) -> bytes:
    """Encode convertToAssets(uint256) — ERC-4626 vault."""
    return bytes.fromhex("07a2d13a" + hex(shares)[2:].zfill(64))


def encode_chainlink_latest_round_data() -> bytes:
    """Encode latestRoundData() — Chainlink AggregatorV3."""
    return bytes.fromhex("feaf968c")


def encode_chainlink_decimals() -> bytes:
    """Encode decimals() — Chainlink AggregatorV3."""
    return bytes.fromhex("313ce567")


def decode_uint256(data: bytes) -> int:
    """Decode a single uint256 from return data."""
    if len(data) < 32:
        return 0
    return int.from_bytes(data[:32], "big")


def decode_chainlink_latest_round_data(data: bytes) -> tuple:
    """Decode latestRoundData() return: (roundId, answer, startedAt, updatedAt, answeredInRound)."""
    if len(data) < 160:
        raise ValueError(f"Invalid latestRoundData return length: {len(data)}")
    round_id = int.from_bytes(data[0:32], "big")
    answer = int.from_bytes(data[32:64], "big", signed=True)
    started_at = int.from_bytes(data[64:96], "big")
    updated_at = int.from_bytes(data[96:128], "big")
    answered_in_round = int.from_bytes(data[128:160], "big")
    return round_id, answer, started_at, updated_at, answered_in_round
