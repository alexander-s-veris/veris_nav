"""
DeBank portfolio-level verifier.

Compares aggregate and token-level EVM portfolio values from DeBank
against our computed NAV for EVM positions.

Per Valuation Policy Section 7.1 (Portfolio-level verification).

API: pro-openapi.debank.com/v1, auth via AccessKey header.
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


# ── API ──────────────────────────────────────────────────────────────────────

def _get_api_key():
    key = os.environ.get("DEBANK_API_KEY", "")
    if not key:
        raise ValueError("DEBANK_API_KEY environment variable not set")
    return key


def _debank_get(api_base, endpoint, params=None):
    """Authenticated GET with one retry on 429/5xx."""
    url = f"{api_base}{endpoint}"
    headers = {"AccessKey": _get_api_key()}
    logger.info("debank: GET %s %s", url, params or "")

    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=_API_TIMEOUT)
            if resp.status_code in (429, 500, 502, 503) and attempt == 0:
                logger.warning("debank: %d, retrying in %ds", resp.status_code, _RETRY_BACKOFF)
                _time.sleep(_RETRY_BACKOFF)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            if attempt == 0:
                logger.warning("debank: %s, retrying", e)
                _time.sleep(_RETRY_BACKOFF)
            else:
                raise
    return None


# ── Config helpers ───────────────────────────────────────────────────────────

def _build_chain_maps(chain_id_map):
    """Parse chain_id_map config into lookup dicts."""
    our_to_debank = {}
    debank_to_our = {}
    native_ids = {}

    for our_chain, cfg in chain_id_map.items():
        if isinstance(cfg, dict):
            db_id = cfg.get("debank_id", our_chain)
            nat_id = cfg.get("native_token_id", db_id)
        else:
            db_id = cfg
            nat_id = cfg
        our_to_debank[our_chain] = db_id
        debank_to_our[db_id] = our_chain
        native_ids[our_chain] = nat_id

    return our_to_debank, debank_to_our, native_ids


# ── Main entry ───────────────────────────────────────────────────────────────

def verify_portfolio(positions, wallets_cfg, verification_cfg, api_base):
    """Run portfolio-level verification against DeBank."""
    chain_id_map = verification_cfg.get("chain_id_map", {})
    threshold_pct = Decimal(str(verification_cfg.get("divergence_threshold_pct", 3.0)))
    noise_usd = Decimal(str(verification_cfg.get("noise_filter_usd", 10)))
    leveraged_protocols = set(verification_cfg.get("leveraged_protocols", []))

    _, debank_to_our, native_ids = _build_chain_maps(chain_id_map)

    # 1. Collect EVM addresses
    addresses = _collect_evm_addresses(wallets_cfg, chain_id_map)
    logger.info("debank: %d addresses", len(addresses))

    # 2. Aggregate our positions by (wallet, chain, symbol)
    our_by_wallet, our_agg = _aggregate_our(positions, chain_id_map, native_ids)
    our_evm_total = sum(our_by_wallet.values())

    # 3. Query DeBank
    debank_total = Decimal(0)
    per_wallet = {}
    debank_tokens_all = []

    for ai in addresses:
        addr = ai["address"]
        _time.sleep(_RATE_LIMIT_SECONDS)

        try:
            bal = _debank_get(api_base, "/user/total_balance", {"id": addr})
            db_wallet = Decimal(str(bal.get("total_usd_value", 0)))
        except Exception as e:
            logger.error("debank: total_balance %s: %s", addr[:10], e)
            db_wallet = Decimal(0)

        our_wallet = our_by_wallet.get(addr, Decimal(0))
        debank_total += db_wallet
        per_wallet[addr] = {
            "type": ai["type"],
            "our_usd": str(our_wallet),
            "debank_usd": str(db_wallet),
            "diff_usd": str(our_wallet - db_wallet),
        }

        _time.sleep(_RATE_LIMIT_SECONDS)
        try:
            tlist = _debank_get(api_base, "/user/all_token_list", {"id": addr, "is_all": "true"})
            for dt in (tlist or []):
                our_chain = debank_to_our.get(dt.get("chain", ""), "")
                if our_chain:
                    debank_tokens_all.append({
                        "wallet": addr,
                        "chain": our_chain,
                        "symbol": dt.get("symbol", ""),
                        "contract": dt.get("id", "").lower(),
                        "balance": _dec(dt.get("amount", 0)),
                        "price": _dec(dt.get("price", 0)),
                        "value": _dec(dt.get("amount", 0)) * _dec(dt.get("price", 0)),
                    })
        except Exception as e:
            logger.error("debank: all_token_list %s: %s", addr[:10], e)

    # 4. Match
    token_matches = _match(our_agg, debank_tokens_all, noise_usd, leveraged_protocols)

    # 5. Aggregate divergence
    if our_evm_total > 0:
        div_pct = abs(our_evm_total - debank_total) / our_evm_total * Decimal(100)
    else:
        div_pct = Decimal(0)

    div_flag = ""
    if div_pct > threshold_pct:
        div_flag = f"EXCEEDS_THRESHOLD ({div_pct:.2f}% > {threshold_pct}%)"

    per_chain = _per_chain(token_matches)

    return {
        "source": "debank_portfolio",
        "our_evm_total_usd": our_evm_total,
        "debank_total_usd": debank_total,
        "divergence_pct": div_pct,
        "divergence_flag": div_flag,
        "threshold_pct": threshold_pct,
        "wallets_queried": len(addresses),
        "per_wallet": per_wallet,
        "per_chain": per_chain,
        "token_matches": token_matches,
        "verification_timestamp": datetime.now(timezone.utc).strftime(TS_FMT),
        "notes": "EVM-only. Excludes Solana, Kraken, Bank Frick fiat.",
    }


# ── Address collection ───────────────────────────────────────────────────────

def _collect_evm_addresses(wallets_cfg, chain_id_map):
    seen = set()
    out = []

    for chain in chain_id_map:
        for w in wallets_cfg.get(chain, []):
            a = w.get("address", "").lower()
            if a and a not in seen:
                seen.add(a)
                out.append({"address": a, "type": "wallet"})

    for chain, cw in wallets_cfg.get("_chain_protocols", {}).items():
        if chain not in chain_id_map:
            continue
        for a in cw:
            al = a.lower()
            if al not in seen:
                seen.add(al)
                out.append({"address": al, "type": "wallet"})

    for p in wallets_cfg.get("arma_proxies", []):
        a = p.get("address", "").lower()
        if a and a not in seen and p.get("chain", "") in chain_id_map:
            seen.add(a)
            out.append({"address": a, "type": "arma_proxy"})

    return out


# ── Aggregate our positions ──────────────────────────────────────────────────

def _aggregate_our(positions, chain_id_map, native_ids):
    """Aggregate positions by (wallet, chain, symbol). Track debt separately."""
    by_wallet = {}
    agg = []
    bucket = {}  # (wallet, chain, sym_lower, is_debt) -> index in agg

    for pos in positions:
        if pos.get("status") == "CLOSED" or pos.get("position_type") == "lp_parent":
            continue
        chain = pos.get("chain", "")
        if chain not in chain_id_map:
            continue

        wallet = pos.get("wallet", "").lower()
        contract = pos.get("token_contract", "").lower()
        if contract == "native":
            contract = native_ids.get(chain, contract)

        symbol = pos.get("token_symbol", "")
        value = _dec(pos.get("value_usd", 0))
        is_debt = pos.get("position_type") == "debt" or value < 0

        by_wallet[wallet] = by_wallet.get(wallet, Decimal(0)) + value

        bk = (wallet, chain, symbol.lower(), is_debt)
        if bk in bucket:
            entry = agg[bucket[bk]]
            entry["value"] += value
            entry["position_count"] += 1
            entry["contracts"].add(contract)
            entry["protocols"].add(pos.get("protocol", ""))
        else:
            bucket[bk] = len(agg)
            agg.append({
                "wallet": wallet,
                "chain": chain,
                "symbol": symbol,
                "contracts": {contract},
                "protocols": {pos.get("protocol", "")},
                "value": value,
                "price": pos.get("price_usd", ""),
                "position_count": 1,
                "position_type": pos.get("position_type", ""),
                "category": pos.get("category", ""),
                "is_debt": is_debt,
            })

    return by_wallet, agg


# ── Matching ─────────────────────────────────────────────────────────────────

def _match(our_agg, debank_tokens, noise_usd, leveraged_protocols):
    """Match our aggregated positions against DeBank tokens.

    Contract match first, symbol fallback second, classify leftovers last.
    """
    # Index DeBank tokens for lookup
    remaining = {}
    for i, dt in enumerate(debank_tokens):
        remaining[i] = dt

    results = []

    for ours in our_agg:
        our_value = _dec(ours["value"])
        wallet = ours["wallet"]

        # Normalize contract for matching
        contracts = ours["contracts"]

        # Try contract match
        match_idx = None
        for contract in contracts:
            for idx, dt in remaining.items():
                if dt["wallet"] == wallet and dt["contract"] == contract:
                    match_idx = idx
                    break
            if match_idx is not None:
                break

        # Try symbol fallback
        if match_idx is None:
            sym_lower = ours["symbol"].lower()
            for idx, dt in remaining.items():
                if dt["wallet"] == wallet and dt["chain"] == ours["chain"] and dt["symbol"].lower() == sym_lower:
                    match_idx = idx
                    break

        if match_idx is not None:
            dt = remaining.pop(match_idx)
            db_value = _dec(dt["value"])

            # Noise filter: skip if BOTH below threshold
            if abs(our_value) < noise_usd and abs(db_value) < noise_usd:
                continue

            price_div = _price_div(ours["price"], dt["price"])
            flag = "PRICE_DIVERGENCE" if isinstance(price_div, Decimal) and abs(price_div) > Decimal("5") else "MATCH"

            # A3 manual accrual: expected methodology gap even when matched
            if ours["category"] == "A3" or ours["position_type"] == "manual_accrual":
                flag = "EXPECTED_GAP"

            results.append(_row(
                wallet, ours["chain"], ours["symbol"], dt["contract"],
                ours["position_count"], our_value, db_value,
                ours["price"], dt["price"], price_div, flag, ""))
        else:
            # Unmatched — classify
            if abs(our_value) < noise_usd:
                continue

            if ours["is_debt"]:
                results.append(_row(
                    wallet, ours["chain"], ours["symbol"], ", ".join(contracts),
                    ours["position_count"], our_value, "",
                    ours["price"], "", "", "EXPECTED_GAP",
                    "Debt — DeBank nets collateral/debt"))
            elif ours["position_type"] == "collateral" and ours["protocols"] & leveraged_protocols:
                results.append(_row(
                    wallet, ours["chain"], ours["symbol"], ", ".join(contracts),
                    ours["position_count"], our_value, "",
                    ours["price"], "", "", "EXPECTED_GAP",
                    "Leveraged collateral — DeBank tracks under different contract"))
            else:
                results.append(_row(
                    wallet, ours["chain"], ours["symbol"], ", ".join(contracts),
                    ours["position_count"], our_value, "",
                    ours["price"], "", "", "OUR_ONLY", ""))

    # DeBank leftovers
    for dt in remaining.values():
        db_value = _dec(dt["value"])
        if abs(db_value) < noise_usd:
            continue
        results.append(_row(
            dt["wallet"], dt["chain"], dt["symbol"], dt["contract"],
            "", "", db_value, "", dt["price"], "", "DEBANK_ONLY", ""))

    return results


# ── Helpers ──────────────────────────────────────────────────────────────────

def _dec(val):
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal(0)


def _price_div(our, db):
    a = _dec(our)
    b = _dec(db)
    if a > 0 and b > 0:
        return ((b - a) / a) * Decimal(100)
    return Decimal(0)


def _row(wallet, chain, symbol, contract, pos_count, our_val, db_val,
         our_price, db_price, price_div, flag, gap_reason):
    our_d = _dec(our_val)
    db_d = _dec(db_val)
    diff = our_d - db_d if our_val != "" and db_val != "" else ""
    return {
        "wallet": wallet,
        "chain": chain,
        "token_symbol": symbol,
        "token_contract": contract,
        "our_position_count": pos_count,
        "our_value": str(our_val),
        "debank_value": str(db_val),
        "value_diff": str(diff),
        "our_price": str(our_price),
        "debank_price": str(db_price),
        "price_divergence_pct": str(price_div),
        "flag": flag,
        "gap_reason": gap_reason,
    }


def _per_chain(matches):
    pc = {}
    for m in matches:
        c = m.get("chain", "")
        if c not in pc:
            pc[c] = {"our": Decimal(0), "db": Decimal(0)}
        pc[c]["our"] += _dec(m.get("our_value", 0))
        pc[c]["db"] += _dec(m.get("debank_value", 0))
    return {c: {"our_usd": str(v["our"]), "debank_usd": str(v["db"]),
                "diff_usd": str(v["our"] - v["db"])} for c, v in pc.items()}
