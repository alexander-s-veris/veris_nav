"""
DeBank portfolio-level verifier.

Compares aggregate and token-level EVM portfolio values from DeBank
against our computed NAV for EVM positions.

Per Valuation Policy Section 7.1 (Portfolio-level verification).

API docs: https://docs.cloud.debank.com/en/readme/api-pro-reference/user
Auth: AccessKey header with DEBANK_API_KEY environment variable.
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

    # Step 1: Collect all EVM addresses
    addresses = _collect_evm_addresses(wallets_cfg, chain_id_map)
    logger.info("debank: %d EVM addresses to verify", len(addresses))

    # Step 2: Compute our EVM totals from positions
    our_by_wallet, our_by_token = _compute_our_totals(positions, chain_id_map)

    our_evm_total = sum(our_by_wallet.values())

    # Step 3+4: Query DeBank and match tokens
    debank_total = Decimal(0)
    per_wallet = {}
    token_matches = []

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
            if tokens_data:
                matches = _match_tokens(addr, tokens_data, our_by_token, chain_id_map)
                token_matches.extend(matches)
        except Exception as e:
            logger.error("debank: all_token_list failed for %s: %s", addr[:10], e)

    # Add OUR_ONLY entries — positions we have that DeBank didn't return
    matched_keys = {(m["wallet"], m["chain"], m["token_contract"].lower()) for m in token_matches}
    for key, info in our_by_token.items():
        wallet, chain, contract = key
        if key not in matched_keys and chain in chain_id_map:
            token_matches.append({
                "wallet": wallet,
                "chain": chain,
                "token_symbol": info.get("token_symbol", ""),
                "token_contract": contract,
                "our_balance": str(info.get("balance", "")),
                "debank_balance": "",
                "balance_match": False,
                "our_price": str(info.get("price", "")),
                "debank_price": "",
                "price_divergence_pct": "",
                "our_value": str(info.get("value", "")),
                "debank_value": "",
                "value_diff": str(info.get("value", "")),
                "flag": _classify_our_only(info),
            })

    # Compute aggregate divergence
    if our_evm_total > 0:
        divergence_pct = abs(our_evm_total - debank_total) / our_evm_total * Decimal(100)
    else:
        divergence_pct = Decimal(0)

    divergence_flag = ""
    if divergence_pct > threshold_pct:
        divergence_flag = f"EXCEEDS_THRESHOLD ({divergence_pct:.2f}% > {threshold_pct}%)"

    # Per-chain breakdown
    per_chain = _compute_per_chain(token_matches, chain_id_map)

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


# --- Internal helpers ---

def _collect_evm_addresses(wallets_cfg, chain_id_map):
    """Collect all unique EVM addresses from wallets config."""
    seen = set()
    addresses = []

    # Main EVM wallets
    for chain in chain_id_map:
        for w in wallets_cfg.get(chain, []):
            addr = w.get("address", "").lower()
            if addr and addr not in seen:
                seen.add(addr)
                addresses.append({"address": addr, "type": "wallet"})

    # Chain-specific protocol wallets
    chain_protocols = wallets_cfg.get("_chain_protocols", {})
    for chain, chain_wallets in chain_protocols.items():
        if chain not in chain_id_map:
            continue
        for addr in chain_wallets:
            addr_lower = addr.lower()
            if addr_lower not in seen:
                seen.add(addr_lower)
                addresses.append({"address": addr_lower, "type": "wallet"})

    # ARMA proxies
    for proxy in wallets_cfg.get("arma_proxies", []):
        addr = proxy.get("address", "").lower()
        proxy_chain = proxy.get("chain", "")
        if addr and addr not in seen and proxy_chain in chain_id_map:
            seen.add(addr)
            addresses.append({"address": addr, "type": "arma_proxy"})

    return addresses


def _compute_our_totals(positions, chain_id_map):
    """Compute our EVM totals from positions.

    Returns:
        (by_wallet, by_token) where:
        - by_wallet: {wallet_lower: total_value_usd}
        - by_token: {(wallet_lower, chain, contract_lower): {value, balance, price, ...}}
    """
    by_wallet = {}
    by_token = {}

    for pos in positions:
        if pos.get("status") == "CLOSED":
            continue
        chain = pos.get("chain", "")
        if chain not in chain_id_map:
            continue

        wallet = pos.get("wallet", "").lower()
        contract = pos.get("token_contract", "").lower()
        value = pos.get("value_usd", Decimal(0))
        if not isinstance(value, Decimal):
            try:
                value = Decimal(str(value))
            except Exception:
                value = Decimal(0)

        by_wallet[wallet] = by_wallet.get(wallet, Decimal(0)) + value

        key = (wallet, chain, contract)
        by_token[key] = {
            "value": value,
            "balance": pos.get("balance_human", ""),
            "price": pos.get("price_usd", ""),
            "token_symbol": pos.get("token_symbol", ""),
            "category": pos.get("category", ""),
            "position_type": pos.get("position_type", ""),
        }

    return by_wallet, by_token


def _match_tokens(wallet, debank_tokens, our_by_token, chain_id_map):
    """Match DeBank token list against our positions for one wallet."""
    # Reverse chain_id_map: debank_chain -> our_chain
    debank_to_our_chain = {v: k for k, v in chain_id_map.items()}

    matches = []
    wallet_lower = wallet.lower()

    for dt in debank_tokens:
        debank_chain = dt.get("chain", "")
        our_chain = debank_to_our_chain.get(debank_chain, "")
        if not our_chain:
            continue  # Chain not in our scope

        contract = dt.get("id", "").lower()
        debank_balance = Decimal(str(dt.get("amount", 0)))
        debank_price = Decimal(str(dt.get("price", 0)))
        debank_value = debank_balance * debank_price
        debank_symbol = dt.get("symbol", "")

        # Skip dust
        if abs(debank_value) < Decimal("0.01"):
            continue

        # Match against our positions
        key = (wallet_lower, our_chain, contract)
        our_info = our_by_token.get(key)

        if our_info:
            our_value = our_info.get("value", Decimal(0))
            our_price = our_info.get("price", Decimal(0))
            our_balance = our_info.get("balance", "")

            if not isinstance(our_price, Decimal):
                try:
                    our_price = Decimal(str(our_price))
                except Exception:
                    our_price = Decimal(0)
            if not isinstance(our_value, Decimal):
                try:
                    our_value = Decimal(str(our_value))
                except Exception:
                    our_value = Decimal(0)

            # Price divergence
            if our_price > 0 and debank_price > 0:
                price_div = ((debank_price - our_price) / our_price) * Decimal(100)
            else:
                price_div = Decimal(0)

            # Balance match (within 0.01%)
            try:
                our_bal_dec = Decimal(str(our_balance))
                bal_match = abs(our_bal_dec - debank_balance) / max(our_bal_dec, Decimal("0.001")) < Decimal("0.0001")
            except Exception:
                bal_match = False

            flag = _classify_match(our_info, price_div, bal_match)

            matches.append({
                "wallet": wallet_lower,
                "chain": our_chain,
                "token_symbol": our_info.get("token_symbol", debank_symbol),
                "token_contract": contract,
                "our_balance": str(our_balance),
                "debank_balance": str(debank_balance),
                "balance_match": bal_match,
                "our_price": str(our_price),
                "debank_price": str(debank_price),
                "price_divergence_pct": str(price_div),
                "our_value": str(our_value),
                "debank_value": str(debank_value),
                "value_diff": str(our_value - debank_value),
                "flag": flag,
            })
        else:
            # DeBank sees it, we don't
            if debank_value < Decimal("1"):
                continue  # Skip dust
            matches.append({
                "wallet": wallet_lower,
                "chain": our_chain,
                "token_symbol": debank_symbol,
                "token_contract": contract,
                "our_balance": "",
                "debank_balance": str(debank_balance),
                "balance_match": False,
                "our_price": "",
                "debank_price": str(debank_price),
                "price_divergence_pct": "",
                "our_value": "",
                "debank_value": str(debank_value),
                "value_diff": str(-debank_value),
                "flag": "DEBANK_ONLY",
            })

    return matches


def _classify_match(our_info, price_div, bal_match):
    """Classify a token match into a flag category."""
    category = our_info.get("category", "")
    pos_type = our_info.get("position_type", "")

    # A3 manual accrual — DeBank values at exchange rate, we use workbook accrual
    if category == "A3":
        return "EXPECTED_GAP"

    # Midas oracle-priced — DeBank may not track these
    if pos_type == "oracle_priced":
        return "EXPECTED_GAP"

    if not bal_match:
        return "BALANCE_MISMATCH"

    if abs(price_div) > Decimal("5"):
        return "PRICE_DIVERGENCE"

    return "MATCH"


def _classify_our_only(info):
    """Classify a position we have but DeBank doesn't see."""
    category = info.get("category", "")
    pos_type = info.get("position_type", "")

    # Protocol positions that DeBank may not decompose
    if pos_type in ("vault_share", "vault_strategy", "manual_accrual", "lp_parent"):
        return "EXPECTED_GAP"
    if category == "A3":
        return "EXPECTED_GAP"

    value = info.get("value", Decimal(0))
    if isinstance(value, Decimal) and abs(value) < Decimal("1"):
        return "DUST"

    return "OUR_ONLY"


def _compute_per_chain(token_matches, chain_id_map):
    """Aggregate token matches by chain."""
    per_chain = {}
    for m in token_matches:
        chain = m.get("chain", "")
        if chain not in per_chain:
            per_chain[chain] = {"our_usd": Decimal(0), "debank_usd": Decimal(0)}
        try:
            per_chain[chain]["our_usd"] += Decimal(m.get("our_value", "0") or "0")
        except Exception:
            pass
        try:
            per_chain[chain]["debank_usd"] += Decimal(m.get("debank_value", "0") or "0")
        except Exception:
            pass

    # Convert to strings
    return {
        chain: {
            "our_usd": str(v["our_usd"]),
            "debank_usd": str(v["debank_usd"]),
            "diff_usd": str(v["our_usd"] - v["debank_usd"]),
        }
        for chain, v in per_chain.items()
    }
