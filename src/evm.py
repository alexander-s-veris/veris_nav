"""
Shared EVM utilities for the Veris NAV data collection system.

Provides cached Web3 connections, block queries, and shared constants
used across all collection and pricing scripts.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

load_dotenv()

# --- Paths ---
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")

# --- Formatting ---
TS_FMT = "%d/%m/%Y %H:%M:%S"

# Liechtenstein follows CET/CEST (Europe/Zurich) — automatically handles DST
CET = ZoneInfo("Europe/Zurich")


def get_native_symbol(chain: str) -> str:
    """Get native token symbol for a chain from chains.json."""
    chains = load_chains()
    return chains.get(chain, {}).get("native_symbol", "ETH")


def get_native_decimals(chain: str) -> int:
    """Get native token decimals for a chain from chains.json."""
    chains = load_chains()
    return chains.get(chain, {}).get("native_decimals", 18)

# --- Chainlink AggregatorV3Interface ABI ---
AGGREGATOR_V3_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "description",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# --- Caches ---
_chains_cache: dict | None = None
_web3_cache: dict[str, Web3] = {}


def load_chains() -> dict:
    """Load and cache config/chains.json."""
    global _chains_cache
    if _chains_cache is None:
        with open(os.path.join(CONFIG_DIR, "chains.json")) as f:
            _chains_cache = json.load(f)
    return _chains_cache


def get_evm_chains() -> list[str]:
    """Return list of EVM chain names (those with a chain_id)."""
    chains = load_chains()
    return [name for name, cfg in chains.items() if "chain_id" in cfg]


def get_rpc_url(chain: str) -> str:
    """Build RPC URL for a chain.

    Chains with rpc_url_template use Alchemy API key substitution.
    Chains with rpc_env_var read a full URL from .env.
    """
    chains = load_chains()
    if chain not in chains:
        raise ValueError(f"Unknown chain: {chain}")
    cfg = chains[chain]
    if "rpc_url" in cfg:
        return cfg["rpc_url"]
    if "rpc_env_var" in cfg:
        return os.getenv(cfg["rpc_env_var"])
    api_key = os.getenv("ALCHEMY_API_KEY")
    return cfg["rpc_url_template"].format(api_key=api_key)


def get_web3(chain: str) -> Web3:
    """Return a cached Web3 instance for an EVM chain.

    Injects PoA middleware (needed for Avalanche, safe no-op on others).
    Raises ConnectionError if cannot connect.
    """
    if chain in _web3_cache:
        return _web3_cache[chain]

    rpc_url = get_rpc_url(chain)
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to {chain} RPC at {rpc_url}")

    _web3_cache[chain] = w3
    return w3


_web3_fallback_cache = {}


def get_web3_fallback(chain: str) -> Web3 | None:
    """Return a cached Web3 instance using the chain's fallback RPC, if configured.

    Used when the primary Alchemy RPC doesn't support historical queries.
    Returns None if no fallback is configured.
    """
    if chain in _web3_fallback_cache:
        return _web3_fallback_cache[chain]

    chains = load_chains()
    cfg = chains.get(chain, {})
    fallback_url = cfg.get("fallback_rpc")
    if not fallback_url:
        # Check for Alchemy-templated fallback
        template = cfg.get("fallback_rpc_template")
        if template:
            api_key = os.getenv("ALCHEMY_API_KEY")
            fallback_url = template.format(api_key=api_key)
        else:
            return None

    provider = Web3.HTTPProvider(fallback_url)

    w3 = Web3(provider)
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    _web3_fallback_cache[chain] = w3
    return w3


def get_block_info(w3: Web3, block_identifier="latest") -> tuple[int, str]:
    """Return (block_number, block_timestamp_utc_str) for a given block."""
    block_number = w3.eth.block_number if block_identifier == "latest" else block_identifier
    block_data = w3.eth.get_block(block_number)
    block_ts = datetime.fromtimestamp(block_data["timestamp"], tz=timezone.utc)
    return block_number, block_ts.strftime(TS_FMT)


def find_valuation_block(w3: Web3, chain: str, target_ts: int) -> tuple[int, str]:
    """Find the block closest to but not exceeding target_ts on a chain.

    Uses block_utils.estimate_blocks for initial estimate, then refine_block
    for precise alignment. The returned block timestamp is guaranteed to be
    <= target_ts (per Valuation Policy: closest to but NOT exceeding 16:00 CET/CEST).

    Falls back to the chain's fallback RPC if the primary one fails on
    historical block queries.

    Args:
        w3: Web3 instance for the chain.
        chain: Chain name (for block time estimation).
        target_ts: Target unix timestamp (e.g. 16:00 CET/CEST on valuation date).

    Returns:
        (block_number, block_timestamp_utc_str)
    """
    try:
        return _find_valuation_block(w3, chain, target_ts)
    except Exception as primary_err:
        # Try fallback RPC if available
        w3_fb = get_web3_fallback(chain)
        if w3_fb is None:
            raise
        import logging
        logging.getLogger(__name__).info(
            "find_valuation_block: primary RPC failed for %s (%s), trying fallback",
            chain, primary_err)
        return _find_valuation_block(w3_fb, chain, target_ts)


def _find_valuation_block(w3: Web3, chain: str, target_ts: int) -> tuple[int, str]:
    """Internal: find valuation block using a single Web3 instance."""
    from block_utils import estimate_blocks, refine_block

    # Get current block as reference
    latest = w3.eth.block_number
    latest_data = w3.eth.get_block(latest)
    ref_ts = latest_data["timestamp"]

    # If target is in the future, return latest block
    if target_ts >= ref_ts:
        block_ts_str = datetime.fromtimestamp(ref_ts, tz=timezone.utc).strftime(TS_FMT)
        return latest, block_ts_str

    # Estimate then refine (pass chain for correct block time in adjustment)
    [est_block] = estimate_blocks(latest, ref_ts, [target_ts], chain)
    refined = refine_block(w3, est_block, target_ts, tolerance=15, chain=chain)

    # Ensure block timestamp does NOT exceed target (must be <= target_ts)
    block_data = w3.eth.get_block(refined)
    while block_data["timestamp"] > target_ts and refined > 1:
        refined -= 1
        block_data = w3.eth.get_block(refined)

    block_ts_str = datetime.fromtimestamp(block_data["timestamp"], tz=timezone.utc).strftime(TS_FMT)
    return refined, block_ts_str
