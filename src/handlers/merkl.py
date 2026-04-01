"""Merkl rewards handler (Category F).

Queries Merkl REST API for unclaimed, claimable reward balances.
Per Valuation Policy Section 6.8 — only claimable rewards are valued.
Rewards in dispute (pending) are excluded.

API docs: https://docs.merkl.xyz
"""

import logging
import time as _time
from decimal import Decimal

import requests

from evm import load_chains

logger = logging.getLogger(__name__)

_API_BASE = "https://api.merkl.xyz/v4"
_TIMEOUT = 15
_RATE_LIMIT = 0.5


def query_merkl_rewards(w3, chain, wallet, block_number, block_ts):
    """Query Merkl for all claimable rewards across all EVM chains.

    Runs only on the ethereum pass (Option A). Makes one multi-chain API
    call per wallet and returns rewards tagged with the correct chain.
    """
    if chain != "ethereum":
        return []

    chains_cfg = load_chains()
    chain_ids = {}
    for cname, ccfg in chains_cfg.items():
        cid = ccfg.get("chain_id")
        if cid:
            chain_ids[cid] = cname

    params = [("chainId", cid) for cid in chain_ids]
    url = f"{_API_BASE}/users/{wallet}/rewards"

    _time.sleep(_RATE_LIMIT)
    try:
        r = requests.get(url, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        logger.error("merkl: API error for %s: %s", wallet[:10], e)
        return []
    except ValueError as e:
        logger.error("merkl: JSON parse error for %s: %s", wallet[:10], e)
        return []

    rows = []
    for chain_entry in data:
        chain_info = chain_entry.get("chain", {})
        cid = chain_info.get("id")
        cname = chain_ids.get(cid)
        if not cname:
            continue

        for reward in chain_entry.get("rewards", []):
            token = reward.get("token", {})
            decimals = token.get("decimals", 18)
            divisor = Decimal(10) ** decimals

            amount = Decimal(str(reward.get("amount", "0")))
            claimed = Decimal(str(reward.get("claimed", "0")))
            pending = Decimal(str(reward.get("pending", "0")))

            unclaimed = (amount - claimed) / divisor
            pending_human = pending / divisor
            claimable = unclaimed - pending_human

            if claimable <= 0:
                continue

            token_symbol = token.get("symbol", "")
            token_address = token.get("address", "")

            rows.append({
                "chain": cname,
                "protocol": "merkl",
                "wallet": wallet,
                "position_label": token_symbol,
                "category": "F",
                "position_type": "reward",
                "token_symbol": token_symbol,
                "token_contract": token_address,
                "balance_human": claimable,
                "block_number": block_number,
                "block_timestamp_utc": block_ts,
                "notes": f"Merkl claimable reward. Pending in dispute: {pending_human:.6f}",
            })

    logger.info("merkl: %s → %d claimable rewards", wallet[:10], len(rows))
    return rows
