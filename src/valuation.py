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
  E:  par ($1.00) with depeg monitoring, or oracle for non-USDC-pegged
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


def _apply_price_result(pos, result):
    """Apply pricing metadata from a get_price() result dict to a position.

    Propagates staleness fields, depeg fields (Policy Section 9.4 / 12.1),
    and notes. Preserves existing notes on the position.
    """
    pos["stale_flag"] = result.get("stale_flag", "") or ""
    pos["staleness_hours"] = result.get("staleness_hours")

    # Propagate depeg fields
    depeg_flag = result.get("depeg_flag", "")
    if depeg_flag and depeg_flag != "none":
        pos["depeg_flag"] = depeg_flag
    depeg_pct = result.get("depeg_deviation_pct")
    if depeg_pct is not None:
        pos["depeg_deviation_pct"] = depeg_pct

    notes = result.get("notes", "")
    if notes:
        existing = pos.get("notes", "")
        pos["notes"] = f"{existing}; {notes}" if existing else notes
    return pos


# =============================================================================
# Pricing helpers — return a standardised result dict
# =============================================================================

def _price_by_entry_or_symbol(pos, w3_eth, tokens_registry):
    """Get price for a position using its registry entry or token_symbol.

    Returns a pricing result dict with price_usd, price_source, stale_flag,
    staleness_hours, notes, depeg_flag, depeg_deviation_pct.
    """
    chain = pos.get("chain", "")
    contract = pos.get("token_contract", "").lower()

    if tokens_registry and chain in tokens_registry:
        entry = tokens_registry[chain].get(contract)
        if entry:
            try:
                return get_price(entry, w3_eth)
            except Exception:
                pass

    return _price_by_symbol(
        pos.get("token_symbol", ""), chain, w3_eth, tokens_registry)


def _price_by_symbol(symbol, chain, w3_eth, tokens_registry):
    """Look up token price by symbol using config-derived indices.

    Routes par-priced stablecoins through pricing.get_price() so depeg
    checks are applied (Policy Section 9.4).

    Returns a pricing result dict.
    """
    indices = _get_pricing_indices(tokens_registry)
    sym_lower = symbol.lower()

    # 1. aToken/debt token mapping -> recurse with underlying
    underlying = indices["atoken_map"].get(sym_lower)
    if underlying:
        return _price_by_symbol(underlying, chain, w3_eth, tokens_registry)

    # 2. Par-priced stablecoins and all other tokens — route through
    #    pricing.get_price() which handles depeg checks for E_par tokens
    entry = indices["symbol_index"].get(sym_lower)
    if entry:
        try:
            return get_price(entry, w3_eth)
        except Exception:
            pass

    # 3. Fallback for par symbols without a registry entry (shouldn't happen)
    if sym_lower in indices["par_symbols"]:
        return _make_result(Decimal(1), "par")

    # 4. Not found
    return _make_result(Decimal(0), f"price_not_found_{symbol}",
                        notes=f"No pricing config found for {symbol}")


def _make_result(price, source, notes=""):
    """Create a minimal pricing result dict."""
    return {
        "price_usd": price,
        "price_source": source,
        "stale_flag": "",
        "staleness_hours": None,
        "notes": notes,
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
    }


# =============================================================================
# Category dispatch
# =============================================================================

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
    elif category == "E":
        return _value_e(pos, w3_eth, tokens_registry)
    elif category == "F":
        return _value_f(pos, w3_eth, tokens_registry)
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
    underlying_sym = pos.get("underlying_symbol")

    # Look up underlying from tokens.json if not set by a handler
    if not underlying_sym and tokens_registry:
        chain = pos.get("chain", "")
        contract = pos.get("token_contract", "").lower()
        entry = (tokens_registry.get(chain, {}).get(contract) or {})
        underlying_sym = entry.get("pricing", {}).get("underlying")

    if not underlying_sym:
        pos["price_usd"] = Decimal(0)
        pos["value_usd"] = Decimal(0)
        pos["price_source"] = "error_no_underlying_symbol"
        pos["notes"] = "A1 position missing underlying_symbol — check handler config"
        return pos

    result = _price_by_symbol(underlying_sym, pos.get("chain", ""), w3_eth, tokens_registry)

    # For A1 vaults, show the underlying amount as balance_human (what you own),
    # not the share count. Share count stays in balance_raw.
    pos["balance_human"] = underlying_amount
    pos["price_usd"] = result["price_usd"]
    pos["value_usd"] = underlying_amount * result["price_usd"]
    pos["price_source"] = result["price_source"]
    _apply_price_result(pos, result)
    return pos


# =============================================================================
# A2: Oracle-priced — value = balance × oracle price
# =============================================================================

def _value_a2(pos, w3_eth, tokens_registry):
    result = _price_by_entry_or_symbol(pos, w3_eth, tokens_registry)
    balance = pos.get("balance_human", Decimal(0))
    pos["price_usd"] = result["price_usd"]
    pos["value_usd"] = balance * result["price_usd"]
    pos["price_source"] = result["price_source"]
    _apply_price_result(pos, result)
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
        result = _price_by_symbol(
            underlying, pos.get("chain", "solana"), w3_eth, tokens_registry)
        underlying_price = result["price_usd"]
        if underlying_price <= 0:
            underlying_price = Decimal(1)
            pos["notes"] = (pos.get("notes", "") +
                            "; WARNING: underlying price lookup failed, using $1.00 fallback").lstrip("; ")
        _apply_price_result(pos, result)
    else:
        underlying_price = Decimal(1)
        pos["notes"] = (pos.get("notes", "") +
                        "; WARNING: no underlying symbol for PT, using $1.00 fallback").lstrip("; ")

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
    constituent_type = pos.get("lp_constituent_type", "")

    if constituent_type == "PT":
        # PT in LP uses AMM implied rate, NOT linear amortisation
        pt_ratio = pos.get("pt_price_ratio", Decimal(1))
        underlying_price = _get_underlying_price_for_lp(pos, w3_eth, tokens_registry)
        price = pt_ratio * underlying_price
        pos["price_usd"] = price
        pos["value_usd"] = balance * price
        pos["price_source"] = f"amm_implied_rate (pt_ratio={pt_ratio:.6f})"
    else:
        # SY constituent — price per its token category
        result = _price_by_symbol(
            pos.get("token_symbol", ""), pos.get("chain", ""), w3_eth, tokens_registry)
        pos["price_usd"] = result["price_usd"]
        pos["value_usd"] = balance * result["price_usd"]
        pos["price_source"] = result["price_source"]
        _apply_price_result(pos, result)

    return pos


def _get_underlying_price_for_lp(pos, w3_eth, tokens_registry):
    """Get the underlying price for an LP position's constituents."""
    sym = pos.get("token_symbol", "")

    # Strip "PT-" prefix if present to get the underlying token symbol.
    lookup_sym = sym
    if sym.startswith("PT-"):
        underlying = pos.get("underlying_symbol", "")
        # Look up underlying from tokens.json if not set by handler
        if not underlying and tokens_registry:
            chain = pos.get("chain", "")
            contract = pos.get("token_contract", "").lower()
            entry = (tokens_registry.get(chain, {}).get(contract) or {})
            underlying = entry.get("pricing", {}).get("underlying")
            # Also try symbol index for Solana tokens (keyed by lowered mint)
            if not underlying:
                indices = _get_pricing_indices(tokens_registry)
                pt_entry = indices["symbol_index"].get(sym.lower())
                if pt_entry:
                    underlying = pt_entry.get("pricing", {}).get("underlying")
        if underlying:
            lookup_sym = underlying

    if lookup_sym:
        result = _price_by_symbol(
            lookup_sym, pos.get("chain", ""), w3_eth, tokens_registry)
        if result["price_usd"] > 0:
            return result["price_usd"]

    # Fallback — flag it clearly
    pos["notes"] = (pos.get("notes", "") +
                    "; WARNING: LP underlying price lookup failed, using $1.00 fallback").lstrip("; ")
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
        pos["price_usd"] = Decimal(0)
        pos["value_usd"] = Decimal(0)
        pos["price_source"] = "pt_collateral_see_B_lots"
        pos["notes"] = "PT collateral priced via Category B lot methodology"
        return pos

    result = _price_by_symbol(token_sym, pos.get("chain", ""), w3_eth, tokens_registry)

    pos["price_usd"] = result["price_usd"]
    pos["value_usd"] = balance * result["price_usd"]  # balance is negative for debt
    pos["price_source"] = result["price_source"]
    _apply_price_result(pos, result)
    return pos


# =============================================================================
# E: Stablecoins & Cash — par with depeg monitoring (Section 6.7 / 9.4)
# =============================================================================

def _value_e(pos, w3_eth, tokens_registry):
    """Value a Category E position (stablecoins, cash).

    Routes through pricing.get_price() which handles par pricing with
    depeg checks per Policy Section 9.4.
    """
    balance = pos.get("balance_human", Decimal(0))
    result = _price_by_entry_or_symbol(pos, w3_eth, tokens_registry)
    pos["price_usd"] = result["price_usd"]
    pos["value_usd"] = balance * result["price_usd"]
    pos["price_source"] = result["price_source"]
    _apply_price_result(pos, result)
    return pos


# =============================================================================
# F: Other / Bespoke — market price, YT formula (Section 6.8)
# =============================================================================

def _value_f(pos, w3_eth, tokens_registry):
    """Value a Category F position (governance tokens, YT, rewards).

    For YT tokens: uses yt_price_ratio × underlying_price (Section 6.8).
    Near-expiry YTs are flagged for review.
    For everything else: standard market price lookup.
    """
    balance = pos.get("balance_human", Decimal(0))

    # YT tokens have yt_price_ratio set by the Exponent handler
    yt_ratio = pos.get("yt_price_ratio")
    if yt_ratio is not None and yt_ratio > 0:
        underlying_sym = pos.get("underlying_symbol", "")
        if underlying_sym:
            result = _price_by_symbol(
                underlying_sym, pos.get("chain", ""), w3_eth, tokens_registry)
            price = result["price_usd"] * yt_ratio
            pos["price_usd"] = price
            pos["value_usd"] = balance * price
            pos["price_source"] = f"yt_formula ({underlying_sym} × {yt_ratio:.6f})"
            _apply_price_result(pos, result)

            # Flag near-expiry YTs for manual review (Policy Section 6.8)
            days_to_maturity = pos.get("days_to_maturity")
            if days_to_maturity is not None and days_to_maturity <= 7:
                existing = pos.get("notes", "")
                warning = (f"YT near expiry ({days_to_maturity}d remaining). "
                           "Per Section 6.8, illiquid near-expiry YTs may be marked to zero.")
                pos["notes"] = f"{existing}; {warning}" if existing else warning

            return pos

    result = _price_by_entry_or_symbol(pos, w3_eth, tokens_registry)
    pos["price_usd"] = result["price_usd"]
    pos["value_usd"] = balance * result["price_usd"]
    pos["price_source"] = result["price_source"]
    _apply_price_result(pos, result)
    return pos
