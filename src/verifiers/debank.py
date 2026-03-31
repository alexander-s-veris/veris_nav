"""
DeBank portfolio-level verifier.

Tier 1: Wallet aggregate — our total vs DeBank total_balance (deduplicated).
Tier 2: Token detail — unified DeBank view matched against our positions.

Unified DeBank view = all_token_list + protocol entries NOT already
represented in token_list (dedup by pool.controller ∈ token contracts).

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

_TIMEOUT = 15
_RATE_LIMIT = 1.0
_RETRY_WAIT = 3


# ── API ──────────────────────────────────────────────────────────────────────

def _api_key():
    key = os.environ.get("DEBANK_API_KEY", "")
    if not key:
        raise ValueError("DEBANK_API_KEY not set")
    return key


def _get(api_base, path, params=None):
    """Authenticated GET with one retry on 429/5xx."""
    url = f"{api_base}{path}"
    hdrs = {"AccessKey": _api_key()}
    logger.info("debank: GET %s %s", url, params or "")
    for attempt in range(2):
        try:
            r = requests.get(url, params=params, headers=hdrs, timeout=_TIMEOUT)
            if r.status_code in (429, 500, 502, 503) and attempt == 0:
                logger.warning("debank: %d, retry in %ds", r.status_code, _RETRY_WAIT)
                _time.sleep(_RETRY_WAIT)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == 0:
                logger.warning("debank: %s, retrying", e)
                _time.sleep(_RETRY_WAIT)
            else:
                raise
    return None


def _dec(v):
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal(0)


# ── Config ───────────────────────────────────────────────────────────────────

def _parse_chain_map(cfg):
    """Returns (debank_to_our, native_ids)."""
    d2o = {}
    nat = {}
    for our, v in cfg.items():
        if isinstance(v, dict):
            db_id, n_id = v.get("debank_id", our), v.get("native_token_id", v.get("debank_id", our))
        else:
            db_id = n_id = v
        d2o[db_id] = our
        nat[our] = n_id
    return d2o, nat


# ── Main ─────────────────────────────────────────────────────────────────────

def verify_portfolio(positions, wallets_cfg, verification_cfg, api_base):
    # TODO: new approach
    pass


# ── Addresses ────────────────────────────────────────────────────────────────

def _collect_addresses(wcfg, chain_map):
    seen, out = set(), []
    for chain in chain_map:
        for w in wcfg.get(chain, []):
            a = w.get("address", "").lower()
            if a and a not in seen:
                seen.add(a)
                out.append({"address": a, "type": "wallet"})
    for chain, cw in wcfg.get("_chain_protocols", {}).items():
        if chain not in chain_map:
            continue
        for a in cw:
            al = a.lower()
            if al not in seen:
                seen.add(al)
                out.append({"address": al, "type": "wallet"})
    for p in wcfg.get("arma_proxies", []):
        a = p.get("address", "").lower()
        if a and a not in seen and p.get("chain", "") in chain_map:
            seen.add(a)
            out.append({"address": a, "type": "arma_proxy"})
    return out
