"""
Shared EVM utilities for the Veris NAV data collection system.

Provides cached Web3 connections, block queries, and shared constants
used across all collection and pricing scripts.
"""

import os
import json
from datetime import datetime, timezone

from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

load_dotenv()

# --- Paths ---
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")

# --- Formatting ---
TS_FMT = "%d/%m/%Y %H:%M:%S"

# --- Etherscan V2 ---
ETHERSCAN_V2_BASE = "https://api.etherscan.io/v2/api"

# --- Native token symbol per chain ---
NATIVE_TOKEN = {
    "ethereum": "ETH",
    "arbitrum": "ETH",
    "base": "ETH",
    "avalanche": "AVAX",
    "plasma": "XPL",
    "hyperevm": "HYPE",
}

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


def get_block_info(w3: Web3, block_identifier="latest") -> tuple[int, str]:
    """Return (block_number, block_timestamp_utc_str) for a given block."""
    block_number = w3.eth.block_number if block_identifier == "latest" else block_identifier
    block_data = w3.eth.get_block(block_number)
    block_ts = datetime.fromtimestamp(block_data["timestamp"], tz=timezone.utc)
    return block_number, block_ts.strftime(TS_FMT)
