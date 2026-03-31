"""
DeBank portfolio-level verifier.

Compares aggregate and token-level EVM portfolio values from DeBank
against our computed NAV for EVM positions.

Per Valuation Policy Section 7.1 (Portfolio-level verification).

API docs: https://docs.cloud.debank.com/en/readme/api-pro-reference/user
Auth: AccessKey header with DEBANK_API_KEY environment variable.

Token matching priority:
  1. Normalize native tokens (our "native" -> DeBank chain slug from config)
  2. Exact contract match (case-insensitive)
  3. Symbol + chain fallback (handles protocol wrappers)
"""

import logging
import os
import time as _time
from datetime import datetime, timezone
from decimal import Decimal

import requests

from evm import TS_FMT

logger = logging.getLogger(__name__)

_API_TIMEOUT = 15
_RATE_LIMIT_SECONDS = 1.0
_RETRY_BACKOFF = 3


def _get_api_key():
    key = os.environ.get("DEBANK_API_KEY", "")
    if not key:
        raise ValueError("DEBANK_API_KEY environment variable not set")
    return key


def _debank_get(api_base, endpoint, params=None):
    """Make authenticated GET request to DeBank API with retry."""
    url = f"{api_base}{endpoint}"
    headers = {"AccessKey": _get_api_key()}
    logger.info("debank: GET %s %s", url, params or "")

    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=_API_TIMEOUT)
            if resp.status_code in (429, 500, 502, 503):
                if attempt == 0:
                    logger.warning("debank: %d on %s, retrying in %ds", resp.status_code, endpoint, _RETRY_BACKOFF)
                    _time.sleep(_RETRY_BACKOFF)
                    continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            if attempt == 0:
                logger.warning("debank: request failed (%s), retrying", e)
                _time.sleep(_RETRY_BACKOFF)
            else:
                raise
    return None


# --- Config helpers ---

def _build_chain_maps(chain_id_map):
    """Build lookup dicts from the chain_id_map config.

    Returns:
        (our_to_debank, debank_to_our, native_ids)
        - our_to_debank: {"ethereum": "eth", ...}
        - debank_to_our: {"eth": "ethereum", ...}
        - native_ids: {"ethereum": "eth", "base": "base", ...} — native token IDs per chain
    """
    our_to_debank = {}
    debank_to_our = {}
    native_ids = {}

    for our_chain, cfg in chain_id_map.items():
        if isinstance(cfg, dict):
            debank_id = cfg.get("debank_id", our_chain)
            native_id = cfg.get("native_token_id", debank_id)
        else:
            # Backward compat: string value = debank_id
            debank_id = cfg
            native_id = cfg

        our_to_debank[our_chain] = debank_id
        debank_to_our[debank_id] = our_chain
        native_ids[our_chain] = native_id

    return our_to_debank, debank_to_our, native_ids


# --- Main entry point ---

def verify_portfolio(positions, wallets_cfg, verification_cfg, api_base):
    """Run portfolio-level verification against DeBank.

    Args:
        positions: List of valued position dicts from collect.py.
        wallets_cfg: Loaded wallets.json dict.
        verification_cfg: The portfolio_level.debank config dict.
        api_base: DeBank API base URL.

    Returns:
        Result dict with aggregate totals, per-wallet breakdown,
        and token-level cross-reference.
    """
    chain_id_map = verification_cfg.get("chain_id_map", {})
    threshold_pct = Decimal(str(verification_cfg.get("divergence_threshold_pct", 3.0)))
    noise_filter = Decimal(str(verification_cfg.get("noise_filter_usd", 10)))

    our_to_debank, debank_to_our, native_ids = _build_chain_maps(chain_id_map)

    # Step 1: Collect all EVM addresses
    addresses = _collect_evm_addresses(wallets_cfg, chain_id_map)
    logger.info("debank: %d EVM addresses to verify", len(addresses))

    # Step 2: Compute our EVM totals from positions
    our_by_wallet, our_by_token = _compute_our_totals(positions, chain_id_map, native_ids)
    our_evm_total = sum(our_by_wallet.values())

    # Step 3: Query DeBank per address
    debank_total = Decimal(0)
    per_wallet = {}
    all_debank_tokens = {}  # {addr: [token_list]}

    for addr_info in addresses:
        addr = addr_info["address"]
        addr_type = addr_info["type"]
        _time.sleep(_RATE_LIMIT_SECONDS)

        # Aggregate balance
        try:
            bal_data = _debank_get(api_base, "/user/total_balance", {"id": addr})
            debank_wallet_total = Decimal(str(bal_data.get("total_usd_value", 0)))
        except Exception as e:
            logger.error("debank: total_balance failed for %s: %s", addr[:10], e)
            debank_wallet_total = Decimal(0)

        our_wallet_total = our_by_wallet.get(addr.lower(), Decimal(0))
        debank_total += debank_wallet_total

        per_wallet[addr] = {
            "type": addr_type,
            "our_usd": str(our_wallet_total),
            "debank_usd": str(debank_wallet_total),
            "diff_usd": str(our_wallet_total - debank_wallet_total),
        }

        # Token-level
        _time.sleep(_RATE_LIMIT_SECONDS)
        try:
            tokens_data = _debank_get(api_base, "/user/all_token_list", {"id": addr, "is_all": "true"})
            all_debank_tokens[addr] = tokens_data or []
        except Exception as e:
            logger.error("debank: all_token_list failed for %s: %s", addr[:10], e)
            all_debank_tokens[addr] = []

    # Step 4: Match tokens
    token_matches = _match_all_tokens(
        our_by_token, all_debank_tokens, debank_to_our, native_ids, noise_filter)

    # Compute aggregate divergence
    if our_evm_total > 0:
        divergence_pct = abs(our_evm_total - debank_total) / our_evm_total * Decimal(100)
    else:
        divergence_pct = Decimal(0)

    divergence_flag = ""
    if divergence_pct > threshold_pct:
        divergence_flag = f"EXCEEDS_THRESHOLD ({divergence_pct:.2f}% > {threshold_pct}%)"

    per_chain = _compute_per_chain(token_matches)

    now_utc = datetime.now(timezone.utc).strftime(TS_FMT)

    result = {
        "source": "debank_portfolio",
        "our_evm_total_usd": our_evm_total,
        "debank_total_usd": debank_total,
        "divergence_pct": divergence_pct,
        "divergence_flag": divergence_flag,
        "threshold_pct": threshold_pct,
        "wallets_queried": len(addresses),
        "per_wallet": per_wallet,
        "per_chain": per_chain,
        "token_matches": token_matches,
        "verification_timestamp": now_utc,
        "notes": "EVM-only. Excludes Solana, Kraken, Bank Frick fiat.",
    }

    logger.info("debank: our=$%s debank=$%s divergence=%.2f%% %s",
                 our_evm_total, debank_total, divergence_pct,
                 divergence_flag or "OK")

    return result


# --- Address collection ---

def _collect_evm_addresses(wallets_cfg, chain_id_map):
    """Collect all unique EVM addresses from wallets config."""
    seen = set()
    addresses = []

    for chain in chain_id_map:
        for w in wallets_cfg.get(chain, []):
            addr = w.get("address", "").lower()
            if addr and addr not in seen:
                seen.add(addr)
                addresses.append({"address": addr, "type": "wallet"})

    chain_protocols = wallets_cfg.get("_chain_protocols", {})
    for chain, chain_wallets in chain_protocols.items():
        if chain not in chain_id_map:
            continue
        for addr in chain_wallets:
            addr_lower = addr.lower()
            if addr_lower not in seen:
                seen.add(addr_lower)
                addresses.append({"address": addr_lower, "type": "wallet"})

    for proxy in wallets_cfg.get("arma_proxies", []):
        addr = proxy.get("address", "").lower()
        proxy_chain = proxy.get("chain", "")
        if addr and addr not in seen and proxy_chain in chain_id_map:
            seen.add(addr)
            addresses.append({"address": addr, "type": "arma_proxy"})

    return addresses


# --- Our totals ---

def _compute_our_totals(positions, chain_id_map, native_ids):
    """Compute our EVM totals from positions.

    Normalizes native token contracts to the chain's native_token_id
    so they match DeBank's convention.

    Returns:
        (by_wallet, by_token)
    """
    by_wallet = {}
    by_token = {}

    for pos in positions:
        if pos.get("status") == "CLOSED":
            continue
        if pos.get("position_type") == "lp_parent":
            continue
        chain = pos.get("chain", "")
        if chain not in chain_id_map:
            continue

        wallet = pos.get("wallet", "").lower()
        contract = pos.get("token_contract", "").lower()

        # Normalize native token contract to DeBank's convention
        if contract == "native":
            contract = native_ids.get(chain, contract)

        value = pos.get("value_usd", Decimal(0))
        if not isinstance(value, Decimal):
            try:
                value = Decimal(str(value))
            except Exception:
                value = Decimal(0)

        by_wallet[wallet] = by_wallet.get(wallet, Decimal(0)) + value

        key = (wallet, chain, contract)
        if key in by_token:
            # Multiple positions for same token (e.g. multiple Morpho markets with same collateral)
            existing = by_token[key]
            existing["value"] = existing.get("value", Decimal(0)) + value
        else:
            by_token[key] = {
                "value": value,
                "balance": pos.get("balance_human", ""),
                "price": pos.get("price_usd", ""),
                "token_symbol": pos.get("token_symbol", ""),
                "category": pos.get("category", ""),
                "position_type": pos.get("position_type", ""),
            }

    return by_wallet, by_token


# --- Token matching ---

def _match_all_tokens(our_by_token, all_debank_tokens, debank_to_our, native_ids, noise_filter):
    """Match all DeBank tokens against our positions across all wallets.

    Matching priority per DeBank token:
      1. Exact contract match (case-insensitive)
      2. Symbol + chain fallback

    Returns list of match result dicts.
    """
    # Build symbol index for fallback matching: {(wallet, chain, symbol_lower): key}
    symbol_index = {}
    for key, info in our_by_token.items():
        wallet, chain, contract = key
        sym = info.get("token_symbol", "").lower()
        if sym:
            skey = (wallet, chain, sym)
            if skey not in symbol_index:
                symbol_index[skey] = key

    matched_our_keys = set()
    matches = []

    for addr, debank_tokens in all_debank_tokens.items():
        wallet_lower = addr.lower()

        for dt in debank_tokens:
            debank_chain = dt.get("chain", "")
            our_chain = debank_to_our.get(debank_chain, "")
            if not our_chain:
                continue

            debank_contract = dt.get("id", "").lower()
            debank_balance = _to_decimal(dt.get("amount", 0))
            debank_price = _to_decimal(dt.get("price", 0))
            debank_value = debank_balance * debank_price
            debank_symbol = dt.get("symbol", "")

            # Priority 1: exact contract match
            key = (wallet_lower, our_chain, debank_contract)
            our_info = our_by_token.get(key)

            # Priority 2: symbol + chain fallback
            if not our_info:
                skey = (wallet_lower, our_chain, debank_symbol.lower())
                fallback_key = symbol_index.get(skey)
                if fallback_key:
                    our_info = our_by_token.get(fallback_key)
                    key = fallback_key

            if our_info:
                matched_our_keys.add(key)
                our_value = _to_decimal(our_info.get("value", 0))
                our_price = _to_decimal(our_info.get("price", 0))
                our_balance = our_info.get("balance", "")

                # Noise filter: skip if BOTH sides below threshold
                if abs(our_value) < noise_filter and abs(debank_value) < noise_filter:
                    continue

                price_div = _price_divergence(our_price, debank_price)
                bal_match = _balance_match(our_balance, debank_balance)
                flag = _classify_match(our_info, price_div, bal_match)

                matches.append(_build_match_row(
                    wallet_lower, our_chain, our_info.get("token_symbol", debank_symbol),
                    debank_contract, our_balance, debank_balance, bal_match,
                    our_price, debank_price, price_div, our_value, debank_value, flag))
            else:
                # Noise filter for DEBANK_ONLY
                if abs(debank_value) < noise_filter:
                    continue
                matches.append(_build_match_row(
                    wallet_lower, our_chain, debank_symbol, debank_contract,
                    "", debank_balance, False, "", debank_price, "",
                    "", debank_value, "DEBANK_ONLY"))

    # OUR_ONLY: positions we have that weren't matched
    for key, info in our_by_token.items():
        if key in matched_our_keys:
            continue
        wallet, chain, contract = key
        our_value = _to_decimal(info.get("value", 0))

        # Noise filter
        if abs(our_value) < noise_filter:
            continue

        flag = _classify_our_only(info)
        matches.append(_build_match_row(
            wallet, chain, info.get("token_symbol", ""), contract,
            info.get("balance", ""), "", False, info.get("price", ""), "", "",
            our_value, "", flag))

    return matches


# --- Classification ---

def _classify_match(our_info, price_div, bal_match):
    """Classify a matched token pair."""
    category = our_info.get("category", "")
    pos_type = our_info.get("position_type", "")

    # Expected methodology gaps
    if category == "A3" or pos_type == "manual_accrual":
        return "EXPECTED_GAP"
    if pos_type == "oracle_priced":
        return "EXPECTED_GAP"

    if isinstance(price_div, Decimal) and abs(price_div) > Decimal("5"):
        return "PRICE_DIVERGENCE"

    if not bal_match:
        return "BALANCE_MISMATCH"

    return "MATCH"


def _classify_our_only(info):
    """Classify a position we have but DeBank doesn't see."""
    pos_type = info.get("position_type", "")
    category = info.get("category", "")

    if pos_type in ("vault_share", "vault_strategy", "manual_accrual", "lp_parent", "lp_constituent"):
        return "EXPECTED_GAP"
    if category == "A3":
        return "EXPECTED_GAP"

    return "OUR_ONLY"


# --- Helpers ---

def _to_decimal(val):
    """Convert any value to Decimal, defaulting to 0."""
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal(0)


def _price_divergence(our_price, debank_price):
    """Compute price divergence percentage."""
    our = _to_decimal(our_price)
    db = _to_decimal(debank_price)
    if our > 0 and db > 0:
        return ((db - our) / our) * Decimal(100)
    return Decimal(0)


def _balance_match(our_balance, debank_balance):
    """Check if balances match within 0.1%."""
    try:
        our = abs(Decimal(str(our_balance)))
        db = abs(_to_decimal(debank_balance))
        if our == 0 and db == 0:
            return True
        denom = max(our, Decimal("0.001"))
        return abs(our - db) / denom < Decimal("0.001")
    except Exception:
        return False


def _build_match_row(wallet, chain, symbol, contract, our_bal, db_bal, bal_match,
                     our_price, db_price, price_div, our_val, db_val, flag):
    """Build a standardized match result row."""
    our_val_dec = _to_decimal(our_val)
    db_val_dec = _to_decimal(db_val)
    diff = our_val_dec - db_val_dec if our_val != "" and db_val != "" else ""

    return {
        "wallet": wallet,
        "chain": chain,
        "token_symbol": symbol,
        "token_contract": contract,
        "our_balance": str(our_bal),
        "debank_balance": str(db_bal),
        "balance_match": bal_match,
        "our_price": str(our_price),
        "debank_price": str(db_price),
        "price_divergence_pct": str(price_div),
        "our_value": str(our_val),
        "debank_value": str(db_val),
        "value_diff": str(diff),
        "flag": flag,
    }


def _compute_per_chain(token_matches):
    """Aggregate token matches by chain."""
    per_chain = {}
    for m in token_matches:
        chain = m.get("chain", "")
        if chain not in per_chain:
            per_chain[chain] = {"our_usd": Decimal(0), "debank_usd": Decimal(0)}
        per_chain[chain]["our_usd"] += _to_decimal(m.get("our_value", 0))
        per_chain[chain]["debank_usd"] += _to_decimal(m.get("debank_value", 0))

    return {
        chain: {
            "our_usd": str(v["our_usd"]),
            "debank_usd": str(v["debank_usd"]),
            "diff_usd": str(v["our_usd"] - v["debank_usd"]),
        }
        for chain, v in per_chain.items()
    }
