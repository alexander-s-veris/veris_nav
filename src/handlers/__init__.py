"""
Shared utilities for protocol handler modules.

Handler functions self-register via decorators in _registry.py.
discover_handlers() auto-imports all handler files on first load.
"""

import json
import os
import sys

# Ensure src/ is on sys.path so sibling modules (evm, solana_client, etc.) resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
from evm import CONFIG_DIR


# =============================================================================
# Config caches and loaders
# =============================================================================

_ABIS = None
_MORPHO_CFG_CACHE = None
_CONTRACTS_CFG_CACHE = None
_SOLANA_CFG_CACHE = None


def _load_morpho_cfg():
    global _MORPHO_CFG_CACHE
    if _MORPHO_CFG_CACHE is None:
        with open(os.path.join(CONFIG_DIR, "morpho_markets.json")) as f:
            _MORPHO_CFG_CACHE = json.load(f)
    return _MORPHO_CFG_CACHE


def _load_contracts_cfg():
    global _CONTRACTS_CFG_CACHE
    if _CONTRACTS_CFG_CACHE is None:
        with open(os.path.join(CONFIG_DIR, "contracts.json")) as f:
            _CONTRACTS_CFG_CACHE = json.load(f)
    return _CONTRACTS_CFG_CACHE


def _load_solana_cfg():
    global _SOLANA_CFG_CACHE
    if _SOLANA_CFG_CACHE is None:
        with open(os.path.join(CONFIG_DIR, "solana_protocols.json")) as f:
            _SOLANA_CFG_CACHE = json.load(f)
    return _SOLANA_CFG_CACHE


def _load_abis():
    """Load all ABIs from config/abis.json."""
    with open(os.path.join(CONFIG_DIR, "abis.json")) as f:
        return json.load(f)


def _get_abi(name):
    global _ABIS
    if _ABIS is None:
        _ABIS = _load_abis()
    return _ABIS[name]


def _get_display_name(entry, vault_addr, fallback=""):
    """Get display name from config entry, falling back to entry_key."""
    return entry.get("display_name", fallback)


def _get_underlying_symbol(entry, vault_addr, fallback=""):
    """Get underlying token symbol from config entry.

    Fallback should be passed explicitly by the caller when a default is known,
    rather than assuming USDC globally.
    """
    return entry.get("underlying_symbol", fallback)


def _fmt(val, decimals):
    """Convert raw uint256 to human-readable Decimal."""
    return Decimal(str(val)) / Decimal(10 ** decimals)


# =============================================================================
# Auto-discover and register all handler modules
# =============================================================================

from handlers._registry import (
    EVM_HANDLERS, SOLANA_HANDLERS, HANDLER_REGISTRY, DISPLAY_NAMES,
    discover_handlers,
)
discover_handlers()
