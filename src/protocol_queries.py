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

# Import all handler functions from handlers package
from handlers import (
    query_morpho_markets, query_erc4626_vaults, query_euler_vaults,
    query_aave_positions, query_midas_positions, query_gauntlet_falconx,
    query_falconx_direct, query_uniswap_v4, query_ethena_cooldowns,
    query_creditcoop, query_kamino_obligations, query_exponent_lps,
    query_exponent_yts, query_pt_lots,
)

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
                for field in ("symbol", "address", "decimals"):
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

    # Check morpho_markets.json for wallet-specific Morpho positions
    morpho_cfg = _load_morpho_cfg()
    chain_morpho = morpho_cfg.get(chain, {})
    for mkt in chain_morpho.get("markets", []):
        if wallet_lower in [w.lower() for w in mkt.get("wallets", [])]:
            protocols.add("morpho")
            break

    return list(protocols)


# =============================================================================
# Protocol key -> handler mapping
# =============================================================================

# Protocol key (from wallets.json) -> handler key
PROTOCOL_TO_HANDLER = {
    "morpho":           "morpho_leverage",
    "erc4626_vaults":   "erc4626",
    "euler":            "euler_erc4626",
    "aave":             "aave_leverage",
    "midas":            "midas_oracle",
    "gauntlet_falconx": "manual_accrual_gauntlet",
    "falconx_direct":   "manual_accrual_direct",
    "uniswap_v4":       "nft_lp",
    "ethena_cooldowns": "ethena_cooldown",
    "credit_coop":      "credit_coop",
}

# Handler key -> handler function
HANDLER_REGISTRY = {
    "morpho_leverage":          query_morpho_markets,
    "erc4626":                  query_erc4626_vaults,
    "euler_erc4626":            query_euler_vaults,
    "aave_leverage":            query_aave_positions,
    "midas_oracle":             query_midas_positions,
    "manual_accrual_gauntlet":  query_gauntlet_falconx,
    "manual_accrual_direct":    query_falconx_direct,
    "nft_lp":                   query_uniswap_v4,
    "ethena_cooldown":          query_ethena_cooldowns,
    "credit_coop":              query_creditcoop,
}


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

    rows = []
    for protocol_key in protocols:
        handler_key = PROTOCOL_TO_HANDLER.get(protocol_key)
        if not handler_key:
            continue
        handler = HANDLER_REGISTRY.get(handler_key)
        if not handler:
            continue
        # Single retry with backoff for resilience
        for attempt in range(2):
            try:
                handler_rows = handler(w3, chain, wallet, block_number, block_ts)
                rows.extend(handler_rows)
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(2)  # brief backoff before retry
                else:
                    print(f"  [{chain}] {protocol_key} error (after retry): {e}")

    return rows


# =============================================================================
# Orchestrator helper: query all Solana positions
# =============================================================================

# Solana protocol key -> list of (name, handler_fn, needs_valuation_date)
SOLANA_HANDLER_REGISTRY = {
    "kamino":   [("Kamino", query_kamino_obligations, False)],
    "exponent": [("Exponent LP", query_exponent_lps, False),
                 ("Exponent YT", query_exponent_yts, False)],
    "pt_lots":  [("PT lots", query_pt_lots, True)],
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
                    rows.extend(_run_with_retry(
                        name, lambda fn=handler_fn: fn(valuation_date, block_ts)))
            else:
                rows.extend(_run_with_retry(
                    name, lambda fn=handler_fn: fn(wallet, block_ts)))

    return rows
