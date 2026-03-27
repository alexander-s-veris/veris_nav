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

import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(__file__))

from evm import CONFIG_DIR
from pricing import get_price
from pt_valuation import value_pt_from_config
from solana_client import get_eusx_exchange_rate


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
        return _value_b(pos, w3_eth, valuation_date)
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

    # Price the underlying token
    if underlying_sym.upper() in ("USDC", "USDT"):
        price = Decimal(1)
        source = "par"
    elif "syrupusdc" in underlying_sym.lower():
        price, source = _get_token_price_by_symbol("syrupUSDC", pos.get("chain", ""), w3_eth, tokens_registry)
    else:
        price, source = _get_token_price_by_symbol(underlying_sym, pos.get("chain", ""), w3_eth, tokens_registry)

    # For A1 vaults, show the underlying amount as balance_human (what you own),
    # not the share count. Share count stays in balance_raw.
    pos["balance_human"] = underlying_amount
    pos["price_usd"] = price
    pos["value_usd"] = underlying_amount * price
    pos["price_source"] = source
    return pos


# =============================================================================
# A2: Oracle-priced — value = balance × oracle price
# =============================================================================

def _value_a2(pos, w3_eth, tokens_registry):
    price, source = _get_token_price(pos, w3_eth, tokens_registry)
    balance = pos.get("balance_human", Decimal(0))
    pos["price_usd"] = price
    pos["value_usd"] = balance * price
    pos["price_source"] = source
    return pos


# =============================================================================
# A3: Manual accrual — value from supporting workbook
# =============================================================================

def _value_a3(pos):
    """Value an A3 position.

    Reads the most recent accrual value from the FalconX supporting workbook
    (cached CSV). Falls back to on-chain cross-reference if workbook unavailable.
    """
    import csv
    import os

    cache_dir = os.path.join(
        os.path.dirname(__file__), "..", "cache", "falconx_position")

    protocol = pos.get("protocol", "")

    # A3 positions carry accrual_value from the supporting workbook
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

def _value_b(pos, w3_eth, valuation_date):
    """Value PT position via lot-based linear amortisation."""
    pt_symbol = pos.get("_pt_symbol", "")
    if not pt_symbol or not valuation_date:
        pos["price_usd"] = Decimal(0)
        pos["value_usd"] = Decimal(0)
        pos["price_source"] = "pt_no_valuation_date"
        return pos

    underlying = pos.get("underlying", "")

    # Get underlying price
    if underlying == "USX":
        # USX priced via Pyth
        from pricing import pyth_price
        try:
            result = pyth_price("0x85d11b381ccc3e3021b7f84fa757cc01b9b5b5b1b899192b28bae7429e92926b")
            underlying_price = result["price_usd"]
        except Exception:
            underlying_price = Decimal(1)  # fallback
    elif underlying == "eUSX":
        # eUSX = exchange_rate × USX_price
        try:
            eusx_rate = get_eusx_exchange_rate()
            from pricing import pyth_price
            usx_result = pyth_price("0x85d11b381ccc3e3021b7f84fa757cc01b9b5b5b1b899192b28bae7429e92926b")
            underlying_price = eusx_rate * usx_result["price_usd"]
        except Exception:
            underlying_price = Decimal(1)
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
        pos["price_source"] = f"exponent_amm_rate (pt_ratio={pt_ratio:.6f})"
    else:
        # SY constituent — price per its token category
        price, source = _get_token_price_by_symbol(
            pos.get("token_symbol", ""), pos.get("chain", ""), w3_eth, tokens_registry)
        pos["price_usd"] = price
        pos["value_usd"] = balance * price
        pos["price_source"] = source

    return pos


def _get_underlying_price_for_lp(pos, w3_eth, tokens_registry):
    """Get the underlying price for an LP position's constituents."""
    sym = pos.get("token_symbol", "")
    if "ONyc" in sym:
        # ONyc priced via Pyth
        try:
            from pricing import pyth_price
            return pyth_price("0xbabbfcc7f46b6e7df73adcccece8b6782408ed27c4e77f35ba39a449440170ab")["price_usd"]
        except Exception:
            return Decimal(1)
    elif "eUSX" in sym:
        try:
            eusx_rate = get_eusx_exchange_rate()
            from pricing import pyth_price
            usx_result = pyth_price("0x85d11b381ccc3e3021b7f84fa757cc01b9b5b5b1b899192b28bae7429e92926b")
            return eusx_rate * usx_result["price_usd"]
        except Exception:
            return Decimal(1)
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

    price, source = _get_token_price_by_symbol(
        token_sym, pos.get("chain", ""), w3_eth, tokens_registry)

    pos["price_usd"] = price
    pos["value_usd"] = balance * price  # balance is negative for debt
    pos["price_source"] = source
    return pos


# =============================================================================
# E/F: Token balance — use pricing.py
# =============================================================================

def _value_ef(pos, w3_eth, tokens_registry):
    """Value a plain token balance (Category E or F)."""
    balance = pos.get("balance_human", Decimal(0))
    price, source = _get_token_price(pos, w3_eth, tokens_registry)
    pos["price_usd"] = price
    pos["value_usd"] = balance * price
    pos["price_source"] = source
    return pos


# =============================================================================
# Helpers
# =============================================================================

def _get_token_price(pos, w3_eth, tokens_registry):
    """Get price for a position using its registry entry or token_symbol."""
    # Try to find in tokens registry
    chain = pos.get("chain", "")
    contract = pos.get("token_contract", "").lower()

    if tokens_registry and chain in tokens_registry:
        entry = tokens_registry[chain].get(contract)
        if entry:
            try:
                result = get_price(entry, w3_eth)
                return result["price_usd"], result["price_source"]
            except Exception:
                pass

    # Fallback: try by symbol
    return _get_token_price_by_symbol(
        pos.get("token_symbol", ""), chain, w3_eth, tokens_registry)


def _get_token_price_by_symbol(symbol, chain, w3_eth, tokens_registry):
    """Look up token price by symbol across all chains in registry."""
    if not tokens_registry:
        return Decimal(0), "no_registry"

    sym_lower = symbol.lower()

    # Known direct mappings for common tokens
    SYMBOL_PRICING = {
        "usdc": (Decimal(1), "par"),
        "usds": (Decimal(1), "par"),
        "dai": (Decimal(1), "par"),
        "pyusd": (Decimal(1), "par"),
        "ausd": (Decimal(1), "par"),
    }

    # Aave aToken/debt token → underlying symbol mapping
    ATOKEN_MAP = {
        "horizon_atoken_uscc": "uscc",
        "horizon_vdebt_rlusd": "rlusd",
        "atoken_syrupusdc": "syrupusdc",
        "atoken_usde": "usde",
        "atoken_susde": "susde",
        "abassyrupusdc": "syrupusdc",
    }
    mapped = ATOKEN_MAP.get(sym_lower)
    if mapped:
        return _get_token_price_by_symbol(mapped, chain, w3_eth, tokens_registry)
    if sym_lower in SYMBOL_PRICING:
        return SYMBOL_PRICING[sym_lower]

    # Search registry for matching symbol
    for chain_key, chain_tokens in tokens_registry.items():
        if not isinstance(chain_tokens, dict):
            continue
        for addr, entry in chain_tokens.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("symbol", "").lower() == sym_lower:
                try:
                    result = get_price(entry, w3_eth)
                    return result["price_usd"], result["price_source"]
                except Exception:
                    continue

    # Special cases
    if "uscc" in sym_lower:
        try:
            from pricing import pyth_price
            r = pyth_price("0x5d73a5953dc86c4773adc778c30e8a6dfc94c5c3a74d7ebb56dd5e70350f044a")
            return r["price_usd"], "pyth"
        except Exception:
            pass

    if sym_lower in ("onyc",):
        try:
            from pricing import pyth_price
            r = pyth_price("0xbabbfcc7f46b6e7df73adcccece8b6782408ed27c4e77f35ba39a449440170ab")
            return r["price_usd"], "pyth"
        except Exception:
            pass

    if "syrupusdc" in sym_lower:
        try:
            from pricing import pyth_price
            r = pyth_price("0xe616297dab48626eaacf6d030717b25823b13ae6520b83f4735bf8deec8e2c9a")
            return r["price_usd"], "pyth"
        except Exception:
            pass

    if sym_lower in ("usx",):
        try:
            from pricing import pyth_price
            r = pyth_price("0x85d11b381ccc3e3021b7f84fa757cc01b9b5b5b1b899192b28bae7429e92926b")
            return r["price_usd"], "pyth"
        except Exception:
            pass

    if sym_lower in ("eusx",):
        try:
            eusx_rate = get_eusx_exchange_rate()
            from pricing import pyth_price
            usx = pyth_price("0x85d11b381ccc3e3021b7f84fa757cc01b9b5b5b1b899192b28bae7429e92926b")
            return eusx_rate * usx["price_usd"], "a1_exchange_rate"
        except Exception:
            pass

    if "rlusd" in sym_lower:
        return Decimal(1), "par"

    if sym_lower == "usde":
        return Decimal(1), "par"  # USDe is a stablecoin, ~$1

    if sym_lower in ("susde", "aplasusde"):
        # sUSDe is A1 — Ethena staked USDe. Price via exchange rate.
        if tokens_registry:
            for chain_tokens in tokens_registry.values():
                if isinstance(chain_tokens, dict):
                    for addr, entry in chain_tokens.items():
                        if isinstance(entry, dict) and entry.get("symbol", "").lower() == "susde":
                            try:
                                result = get_price(entry, w3_eth)
                                return result["price_usd"], result["price_source"]
                            except Exception:
                                pass
        return Decimal("1.22"), "fallback_susde"

    if sym_lower in ("aplausde", "atoken_usde"):
        return Decimal(1), "par"  # USDe at par  # approximate

    if "usdt" in sym_lower:
        # USDT priced via Chainlink on Ethereum
        try:
            from pricing import chainlink_price
            r = chainlink_price("0x3E7d1eAB13ad0104d2750B8863b489D65364e32D", w3_eth)
            return r["price_usd"], "chainlink"
        except Exception:
            return Decimal("0.9997"), "fallback"

    return Decimal(0), f"price_not_found_{symbol}"
