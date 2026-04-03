"""
Protocol position query functions for the Veris NAV collection system.

Thin dispatcher that imports handler functions from src/handlers/ and
orchestrates queries across EVM chains and Solana.

Position dicts are NOT priced here -- valuation.py handles pricing.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from evm import CONFIG_DIR, get_web3, get_block_info, TS_FMT
from block_utils import concurrent_query

# Auto-registered handler registries
from handlers._registry import EVM_HANDLERS, SOLANA_HANDLERS, HANDLER_REGISTRY

# Import config loaders from handlers for validation
from handlers import _load_contracts_cfg, _load_morpho_cfg, _load_solana_cfg


# =============================================================================
# Wallets config (stays here -- only used by the orchestrator)
# =============================================================================

_WALLETS_CFG_CACHE = None


def _load_wallets_cfg():
    global _WALLETS_CFG_CACHE
    if _WALLETS_CFG_CACHE is None:
        with open(os.path.join(CONFIG_DIR, "wallets.json")) as f:
            _WALLETS_CFG_CACHE = json.load(f)
    return _WALLETS_CFG_CACHE


# =============================================================================
# Config validation
# =============================================================================

_CONFIG_VALIDATED = False
_CONFIG_STRICT = False


def set_config_validation(strict=False):
    """Configure validation behavior for this process.

    Args:
        strict: If True, config validation errors raise ValueError.
                If False, errors are logged as warnings.
    """
    global _CONFIG_STRICT, _CONFIG_VALIDATED
    _CONFIG_STRICT = bool(strict)
    _CONFIG_VALIDATED = False


def _validate_config():
    """Validate config files have required fields. Called once on first query."""
    global _CONFIG_VALIDATED
    if _CONFIG_VALIDATED:
        return
    _CONFIG_VALIDATED = True

    errors = []
    contracts = _load_contracts_cfg()

    for chain, chain_data in contracts.items():
        if not isinstance(chain_data, dict) or chain.startswith("_"):
            continue
        for section_key, section in chain_data.items():
            if not isinstance(section, dict) or not section_key.startswith("_"):
                continue
            query_type = section.get("_query_type")
            for entry_key, entry in section.items():
                if entry_key.startswith("_") or not isinstance(entry, dict):
                    continue
                # All entries with abi field should have an address
                if "abi" in entry and "address" not in entry:
                    errors.append(f"{chain}.{section_key}.{entry_key}: has 'abi' but no 'address'")
                # Midas entries need oracle
                if query_type == "midas_oracle" and "oracle" in entry and "address" not in entry:
                    errors.append(f"{chain}.{section_key}.{entry_key}: midas entry has 'oracle' but no 'address'")

    # Validate morpho markets
    morpho = _load_morpho_cfg()
    for chain, chain_data in morpho.items():
        if not isinstance(chain_data, dict):
            continue
        for mkt in chain_data.get("markets", []):
            if "market_id" not in mkt:
                errors.append(f"morpho_markets.{chain}: market missing 'market_id'")
            for side in ("loan_token", "collateral_token"):
                tok = mkt.get(side, {})
                for field in ("symbol", "address"):
                    if field not in tok:
                        errors.append(f"morpho_markets.{chain}.{mkt.get('name', '?')}.{side}: missing '{field}'")

    # Validate solana protocols
    solana = _load_solana_cfg()
    for ob in solana.get("kamino", {}).get("obligations", []):
        if "obligation_pubkey" not in ob:
            errors.append(f"solana_protocols.kamino: obligation missing 'obligation_pubkey'")
    for mkt in solana.get("exponent", {}).get("markets", []):
        if "market_pubkey" not in mkt:
            errors.append(f"solana_protocols.exponent: market missing 'market_pubkey'")
        for sub in ("sy", "pt"):
            if sub not in mkt:
                errors.append(f"solana_protocols.exponent.{mkt.get('name', '?')}: missing '{sub}'")

    if errors:
        if _CONFIG_STRICT:
            raise ValueError(
                f"Config validation failed with {len(errors)} issue(s): "
                + "; ".join(errors)
            )
        print(f"WARNING: Config validation found {len(errors)} issues:")
        for e in errors:
            print(f"  - {e}")


# =============================================================================
# Config-driven wallet -> protocol mapping
# =============================================================================

def _get_wallet_protocols(chain, wallet):
    """Get list of protocol keys this wallet is registered for on this chain.

    Reads from wallets.json instead of hardcoded KNOWN_POSITIONS.
    For ethereum chain: uses the wallet's 'protocols' dict.
    For other chains: uses '_chain_protocols' section.
    Also checks morpho_markets.json for Morpho positions.
    """
    wallet_lower = wallet.lower()
    wallets_cfg = _load_wallets_cfg()
    protocols = set()

    # Check ethereum wallet entries (used for all EVM chains on ethereum section)
    if chain == "ethereum":
        for w in wallets_cfg.get("ethereum", []):
            if w["address"].lower() == wallet_lower:
                for p_key, enabled in w.get("protocols", {}).items():
                    if enabled:
                        protocols.add(p_key)
                break

    # Check chain-specific protocol registrations
    chain_protocols = wallets_cfg.get("_chain_protocols", {}).get(chain, {})
    wallet_chain_entry = chain_protocols.get(wallet_lower)
    if wallet_chain_entry:
        for p_key, enabled in wallet_chain_entry.get("protocols", {}).items():
            if enabled:
                protocols.add(p_key)

    return list(protocols)


# =============================================================================
# Backward-compatible aliases (used by tests)
# =============================================================================

# Flat identity map — protocol_key -> protocol_key (the two-level indirection
# is now handled by decorators, but tests still import PROTOCOL_TO_HANDLER)
PROTOCOL_TO_HANDLER = {k: k for k in EVM_HANDLERS}


# =============================================================================
# Orchestrator: query all EVM positions for a wallet on a chain
# =============================================================================

def query_evm_wallet_positions(chain, wallet, wallet_desc="", block_override=None):
    """Query all protocol positions for one wallet on one EVM chain.

    Config-driven: reads wallet protocol registrations from wallets.json,
    dispatches to the appropriate handler via HANDLER_REGISTRY.

    Args:
        chain: EVM chain name.
        wallet: Wallet address.
        wallet_desc: Optional description for logging.
        block_override: Optional (block_number, block_ts_str) tuple for
                        Valuation Block pinning. If None, uses latest block.
    """
    _validate_config()

    protocols = _get_wallet_protocols(chain, wallet)
    if not protocols:
        return []

    try:
        w3 = get_web3(chain)
        if block_override:
            block_number, block_ts = block_override
        else:
            block_number, block_ts = get_block_info(w3)
    except (ConnectionError, Exception) as e:
        print(f"  [{chain}] SKIP -- {e}")
        return []

    # Build list of handlers to run
    handler_tasks = []
    for protocol_key in protocols:
        handler = EVM_HANDLERS.get(protocol_key)
        if not handler:
            continue
        handler_tasks.append((protocol_key, handler))

    if not handler_tasks:
        return []

    # Run handlers concurrently within this wallet-chain pair
    def _run_handler(task):
        p_key, handler_fn = task
        for attempt in range(2):
            try:
                return handler_fn(w3, chain, wallet, block_number, block_ts)
            except Exception as e:
                if attempt == 0:
                    time.sleep(2)
                else:
                    print(f"  [{chain}] {p_key} error (after retry): {e}")
        return []

    handler_results = concurrent_query(
        _run_handler, handler_tasks,
        max_workers=min(6, len(handler_tasks)))

    rows = []
    for result_rows in handler_results:
        rows.extend(result_rows)

    return rows


# =============================================================================
# Orchestrator helper: query all Solana positions
# =============================================================================

# Backward-compatible alias — adds the needs_valuation_date=False tuple element
# that the old manual registry had. Tests import SOLANA_HANDLER_REGISTRY.
SOLANA_HANDLER_REGISTRY = {
    k: [(dn, fn, False) for dn, fn in v]
    for k, v in SOLANA_HANDLERS.items()
}


def query_solana_positions(wallet, valuation_date=None, block_ts_override=None):
    """Query all Solana protocol positions for a wallet.

    Config-driven: reads wallet protocol registrations from wallets.json,
    dispatches to the appropriate handlers via SOLANA_HANDLER_REGISTRY.

    Args:
        wallet: Solana wallet address.
        valuation_date: Optional date for PT lot valuation.
        block_ts_override: Optional (slot, block_ts_str) tuple for
                           Valuation Block pinning. If None, uses current time.
    """
    _validate_config()

    from datetime import datetime, timezone
    if block_ts_override:
        _slot, block_ts = block_ts_override
    else:
        block_ts = datetime.now(timezone.utc).strftime(TS_FMT)
        # Get current slot for block_number backfill
        try:
            from solana_client import solana_rpc
            slot_resp = solana_rpc("getSlot", [])
            _slot = slot_resp.get("result")
        except Exception:
            _slot = None

    # Read wallet protocol registrations
    wallets_cfg = _load_wallets_cfg()
    wallet_protocols = set()
    for w in wallets_cfg.get("solana", []):
        if w["address"] == wallet:
            for p_key, enabled in w.get("protocols", {}).items():
                if enabled:
                    wallet_protocols.add(p_key)
            break

    rows = []

    # Helper: run a Solana handler with single retry
    def _run_with_retry(name, fn):
        for attempt in range(2):
            try:
                result = fn()
                print(f"  [solana] {name}: {len(result)} positions")
                return result
            except Exception as e:
                if attempt == 0:
                    time.sleep(2)
                else:
                    print(f"  [solana] {name} error (after retry): {e}")
        return []

    for protocol_key in wallet_protocols:
        handlers = SOLANA_HANDLER_REGISTRY.get(protocol_key, [])
        for name, handler_fn, needs_date in handlers:
            if needs_date:
                if valuation_date:
                    result = _run_with_retry(
                        name, lambda fn=handler_fn: fn(valuation_date, block_ts))
                    if _slot:
                        for r in result:
                            if not r.get("block_number"):
                                r["block_number"] = str(_slot)
                    rows.extend(result)
            else:
                result = _run_with_retry(
                    name, lambda fn=handler_fn: fn(wallet, block_ts))
                # Backfill slot as block_number for handlers that don't set it
                if _slot:
                    for r in result:
                        if not r.get("block_number"):
                            r["block_number"] = str(_slot)
                rows.extend(result)

    return rows
