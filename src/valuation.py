"""
Category-specific valuation logic for the Veris NAV collection system.

Takes raw position dicts from protocol_queries.py and applies the correct
pricing methodology per Valuation Policy:
  A1: convertToAssets × underlying price
  A2: balance × oracle price
  A3: value from supporting workbook (manual accrual)
  B:  per-lot linear amortisation
  C:  LP decomposition × constituent prices
  D:  collateral value − debt value (each side priced per its category)
  E:  par ($1.00) or oracle for non-USDC-pegged
  F:  market price (Kraken → CoinGecko)
"""

import json
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(__file__))

from evm import CONFIG_DIR
from pricing import get_price
from pt_valuation import value_pt_from_config


# --- Pricing indices (built once from config) ---
_PRICING_INDICES = None


def _get_pricing_indices(tokens_registry, contracts_cfg=None):
    """Build or return cached pricing lookup indices from config files.

    Builds:
    - par_symbols: set of lowercase symbols with pricing.policy == "E_par"
    - atoken_map: dict of entry_key.lower() -> underlying_symbol.lower()
    - symbol_index: dict of symbol.lower() -> token_entry for price lookups
    """
    global _PRICING_INDICES
    if _PRICING_INDICES is not None:
        return _PRICING_INDICES

    par_symbols = set()
    symbol_index = {}

    # Build from tokens.json
    if tokens_registry:
        for chain_tokens in tokens_registry.values():
            if not isinstance(chain_tokens, dict):
                continue
            for addr, entry in chain_tokens.items():
                if not isinstance(entry, dict):
                    continue
                sym = entry.get("symbol", "").lower()
                policy = entry.get("pricing", {}).get("policy", "")
                if policy == "E_par":
                    par_symbols.add(sym)
                if sym and sym not in symbol_index:
                    symbol_index[sym] = entry

    # Build atoken map from contracts.json
    atoken_map = {}
    if contracts_cfg is None:
        try:
            contracts_path = os.path.join(CONFIG_DIR, "contracts.json")
            with open(contracts_path) as f:
                contracts_cfg = json.load(f)
        except Exception:
            contracts_cfg = {}

    for chain_key, chain_data in contracts_cfg.items():
        if not isinstance(chain_data, dict):
            continue
        for section_key, section in chain_data.items():
            if not isinstance(section, dict):
                continue
            for entry_key, entry in section.items():
                if isinstance(entry, dict) and "underlying_symbol" in entry:
                    atoken_map[entry_key.lower()] = entry["underlying_symbol"].lower()

    _PRICING_INDICES = {
        "par_symbols": par_symbols,
        "atoken_map": atoken_map,
        "symbol_index": symbol_index,
    }
    return _PRICING_INDICES


def _apply_staleness(pos, stale_flag, staleness_hours, notes=""):
    """Set staleness and notes fields on a position dict from price result.

    Only overwrites notes if there is staleness info to report;
    preserves any existing notes on the position.
    """
    pos["stale_flag"] = stale_flag or ""
    pos["staleness_hours"] = staleness_hours
    if notes:
        existing = pos.get("notes", "")
        pos["notes"] = f"{existing}; {notes}" if existing else notes
    return pos


def value_position(pos, w3_eth=None, valuation_date=None, tokens_registry=None):
    """Value a single position dict. Dispatches to category-specific logic.

    Args:
        pos: Raw position dict from protocol_queries.py
        w3_eth: Web3 instance for Ethereum (needed for Chainlink oracle queries)
        valuation_date: date object for PT lot amortisation
        tokens_registry: tokens.json registry for looking up pricing config

    Returns:
        pos dict with price_usd, value_usd, price_source added.
    """
    category = pos.get("category", "")
    pos_type = pos.get("position_type", "")

    # Skip closed positions
    if pos.get("status") == "CLOSED":
        pos["price_usd"] = Decimal(0)
        pos["value_usd"] = Decimal(0)
        pos["price_source"] = "closed"
        return pos

    if pos_type == "pt_lot_aggregate":
        return _value_b(pos, w3_eth, valuation_date, tokens_registry)
    elif category == "D":
        return _value_d_side(pos, w3_eth, tokens_registry)
    elif category == "A1":
        return _value_a1(pos, w3_eth, tokens_registry)
    elif category == "A2":
        return _value_a2(pos, w3_eth, tokens_registry)
    elif category == "A3":
        return _value_a3(pos)
    elif category == "C":
        return _value_c(pos, w3_eth, tokens_registry)
    elif category in ("E", "F"):
        return _value_ef(pos, w3_eth, tokens_registry)
    else:
        pos["price_usd"] = Decimal(0)
        pos["value_usd"] = Decimal(0)
        pos["price_source"] = "unknown_category"
        return pos


# =============================================================================
# A1: Vault shares — value = underlying_amount × underlying_price
# =============================================================================

def _value_a1(pos, w3_eth, tokens_registry):
    """Value an ERC-4626 vault position.

    The underlying amount is already computed by protocol_queries (convertToAssets).
    We just need the underlying token's price.
    """
    underlying_amount = pos.get("underlying_amount", pos.get("balance_human", Decimal(0)))
    underlying_sym = pos.get("underlying_symbol", "USDC")

    # Price the underlying token via config-driven lookup
    price, source, stale_flag, staleness_hours, notes = _get_token_price_by_symbol(
        underlying_sym, pos.get("chain", ""), w3_eth, tokens_registry)

    # For A1 vaults, show the underlying amount as balance_human (what you own),
    # not the share count. Share count stays in balance_raw.
    pos["balance_human"] = underlying_amount
    pos["price_usd"] = price
    pos["value_usd"] = underlying_amount * price
    pos["price_source"] = source
    _apply_staleness(pos, stale_flag, staleness_hours, notes)
    return pos


# =============================================================================
# A2: Oracle-priced — value = balance × oracle price
# =============================================================================

def _value_a2(pos, w3_eth, tokens_registry):
    price, source, stale_flag, staleness_hours, notes = _get_token_price(pos, w3_eth, tokens_registry)
    balance = pos.get("balance_human", Decimal(0))
    pos["price_usd"] = price
    pos["value_usd"] = balance * price
    pos["price_source"] = source
    _apply_staleness(pos, stale_flag, staleness_hours, notes)
    return pos


# =============================================================================
# A3: Manual accrual — value from supporting workbook
# =============================================================================

def _value_a3(pos):
    """Value an A3 position.

    Reads the accrual value from the position dict (set by protocol_queries
    from data/falconx.db). Falls back to on-chain cross-reference.
    """
    # A3 positions carry accrual_value from SQLite
    value = pos.get("accrual_value", Decimal(0))
    if value and value > 0:
        pos["price_usd"] = Decimal(1)  # value already in USD
        pos["value_usd"] = value
        pos["price_source"] = pos.get("price_source", "a3_workbook_accrual")
        return pos

    # Fallback: on-chain cross-reference
    cross_ref = pos.get("cross_ref_veris_portion", Decimal(0))
    pos["price_usd"] = Decimal(1)
    pos["value_usd"] = cross_ref
    pos["price_source"] = "a3_on_chain_cross_ref"
    return pos


# =============================================================================
# B: PT lots — per-lot linear amortisation
# =============================================================================

def _value_b(pos, w3_eth, valuation_date, tokens_registry=None):
    """Value PT position via lot-based linear amortisation."""
    pt_symbol = pos.get("_pt_symbol", "")
    if not pt_symbol or not valuation_date:
        pos["price_usd"] = Decimal(0)
        pos["value_usd"] = Decimal(0)
        pos["price_source"] = "pt_no_valuation_date"
        return pos

    underlying = pos.get("underlying", "")

    # Get underlying price via registry (no hardcoded Pyth feed IDs)
    if underlying:
        underlying_price, _, ul_stale, ul_staleness_h, ul_notes = _get_token_price_by_symbol(
            underlying, pos.get("chain", "solana"), w3_eth, tokens_registry)
        if underlying_price <= 0:
            underlying_price = Decimal(1)  # safety fallback
        # Propagate underlying staleness to the PT position
        _apply_staleness(pos, ul_stale, ul_staleness_h, ul_notes)
    else:
        underlying_price = Decimal(1)

    val = value_pt_from_config(pt_symbol, valuation_date, underlying_price)

    pos["balance_human"] = val["total_pt_quantity"]
    pos["price_usd"] = val["total_usd_value"] / val["total_pt_quantity"] if val["total_pt_quantity"] > 0 else Decimal(0)
    pos["value_usd"] = val["total_usd_value"]
    pos["price_source"] = "pt_linear_amortisation"
    pos["weighted_avg_apy"] = val["weighted_avg_apy"]
    pos["total_lots"] = val["total_lots"]
    pos["_pt_lot_detail"] = val["lots"]  # for pt_lots.csv
    return pos


# =============================================================================
# C: LP constituents — price each per its category
# =============================================================================

def _value_c(pos, w3_eth, tokens_registry):
    """Value an LP constituent (SY or PT component)."""
    balance = pos.get("balance_human", Decimal(0))
    token_cat = pos.get("token_category", "")
    constituent_type = pos.get("lp_constituent_type", "")

    if constituent_type == "PT":
        # PT in LP uses AMM implied rate, NOT linear amortisation
        pt_ratio = pos.get("pt_price_ratio", Decimal(1))
        # Get underlying price for the SY token
        underlying_price = _get_underlying_price_for_lp(pos, w3_eth, tokens_registry)
        price = pt_ratio * underlying_price
        pos["price_usd"] = price
        pos["value_usd"] = balance * price
        pos["price_source"] = f"amm_implied_rate (pt_ratio={pt_ratio:.6f})"
    else:
        # SY constituent — price per its token category
        price, source, stale_flag, staleness_hours, notes = _get_token_price_by_symbol(
            pos.get("token_symbol", ""), pos.get("chain", ""), w3_eth, tokens_registry)
        pos["price_usd"] = price
        pos["value_usd"] = balance * price
        pos["price_source"] = source
        _apply_staleness(pos, stale_flag, staleness_hours, notes)

    return pos


def _get_underlying_price_for_lp(pos, w3_eth, tokens_registry):
    """Get the underlying price for an LP position's constituents."""
    sym = pos.get("token_symbol", "")

    # Use the standard symbol-based lookup which reads from config.
    # Strip "PT-" prefix if present to get the underlying token symbol.
    lookup_sym = sym
    if sym.startswith("PT-"):
        # For PT constituents, find the SY token's underlying
        underlying = pos.get("underlying_symbol", "")
        if underlying:
            lookup_sym = underlying

    if lookup_sym:
        price, source, *_ = _get_token_price_by_symbol(
            lookup_sym, pos.get("chain", ""), w3_eth, tokens_registry)
        if price > 0:
            return price

    return Decimal(1)


# =============================================================================
# D: Leverage side — price collateral or debt per its token category
# =============================================================================

def _value_d_side(pos, w3_eth, tokens_registry):
    """Value one side (collateral or debt) of a leveraged position."""
    balance = pos.get("balance_human", Decimal(0))  # negative for debt
    token_cat = pos.get("token_category", "")
    token_sym = pos.get("token_symbol", "")

    # PT tokens as collateral (Kamino Solstice) — don't price here,
    # they'll be valued via the B methodology in collect.py
    if token_cat == "B":
        # Placeholder — collect.py will handle PT collateral pricing
        pos["price_usd"] = Decimal(0)
        pos["value_usd"] = Decimal(0)
        pos["price_source"] = "pt_collateral_see_B_lots"
        pos["notes"] = "PT collateral priced via Category B lot methodology"
        return pos

    price, source, stale_flag, staleness_hours, notes = _get_token_price_by_symbol(
        token_sym, pos.get("chain", ""), w3_eth, tokens_registry)

    pos["price_usd"] = price
    pos["value_usd"] = balance * price  # balance is negative for debt
    pos["price_source"] = source
    _apply_staleness(pos, stale_flag, staleness_hours, notes)
    return pos


# =============================================================================
# E/F: Token balance — use pricing.py
# =============================================================================

def _value_ef(pos, w3_eth, tokens_registry):
    """Value a plain token balance (Category E or F).

    For YT tokens: uses yt_price_ratio × underlying_price (Section 6.8).
    For everything else: standard registry price lookup.
    """
    balance = pos.get("balance_human", Decimal(0))

    # YT tokens have yt_price_ratio set by the Exponent handler
    yt_ratio = pos.get("yt_price_ratio")
    if yt_ratio is not None and yt_ratio > 0:
        underlying_sym = pos.get("underlying_symbol", "")
        if underlying_sym:
            ul_price, ul_source, stale_flag, staleness_hours, notes = _get_token_price_by_symbol(
                underlying_sym, pos.get("chain", ""), w3_eth, tokens_registry)
            price = ul_price * yt_ratio
            pos["price_usd"] = price
            pos["value_usd"] = balance * price
            pos["price_source"] = f"yt_formula ({underlying_sym} × {yt_ratio:.6f})"
            _apply_staleness(pos, stale_flag, staleness_hours, notes)
            return pos

    price, source, stale_flag, staleness_hours, notes = _get_token_price(pos, w3_eth, tokens_registry)
    pos["price_usd"] = price
    pos["value_usd"] = balance * price
    pos["price_source"] = source
    _apply_staleness(pos, stale_flag, staleness_hours, notes)
    return pos


# =============================================================================
# Helpers
# =============================================================================

def _get_token_price(pos, w3_eth, tokens_registry):
    """Get price for a position using its registry entry or token_symbol.

    Returns (price_usd, price_source, stale_flag, staleness_hours, notes).
    """
    # Try to find in tokens registry
    chain = pos.get("chain", "")
    contract = pos.get("token_contract", "").lower()

    if tokens_registry and chain in tokens_registry:
        entry = tokens_registry[chain].get(contract)
        if entry:
            try:
                result = get_price(entry, w3_eth)
                return (result["price_usd"], result["price_source"],
                        result.get("stale_flag", ""),
                        result.get("staleness_hours"),
                        result.get("notes", ""))
            except Exception:
                pass

    # Fallback: try by symbol
    return _get_token_price_by_symbol(
        pos.get("token_symbol", ""), chain, w3_eth, tokens_registry)


def _get_token_price_by_symbol(symbol, chain, w3_eth, tokens_registry):
    """Look up token price by symbol using config-derived indices.

    Lookup order:
    1. aToken/debt token -> recurse with underlying symbol
    2. Par-priced stablecoins -> $1.00
    3. Token registry symbol index -> pricing.get_price()
    4. Not found -> (Decimal(0), "price_not_found_{symbol}", "", None, "")

    Returns (price_usd, price_source, stale_flag, staleness_hours, notes).
    """
    indices = _get_pricing_indices(tokens_registry)
    sym_lower = symbol.lower()

    # 1. aToken/debt token mapping -> recurse with underlying
    underlying = indices["atoken_map"].get(sym_lower)
    if underlying:
        return _get_token_price_by_symbol(underlying, chain, w3_eth, tokens_registry)

    # 2. Par-priced stablecoins
    if sym_lower in indices["par_symbols"]:
        return Decimal(1), "par", "", None, ""

    # 3. Symbol index -> use pricing.get_price()
    entry = indices["symbol_index"].get(sym_lower)
    if entry:
        try:
            result = get_price(entry, w3_eth)
            return (result["price_usd"], result["price_source"],
                    result.get("stale_flag", ""),
                    result.get("staleness_hours"),
                    result.get("notes", ""))
        except Exception:
            pass

    # 4. Not found
    return Decimal(0), f"price_not_found_{symbol}", "", None, ""
