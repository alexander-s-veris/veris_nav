"""Kamino Obligations handler (Category D, Solana).

Supports two data paths:
- On-chain: getAccountInfo + binary struct parsing (current/live state)
- API: Kamino REST API historical snapshots (when --date is provided)
"""

import logging
from datetime import date
from decimal import Decimal

import requests

from handlers import _load_solana_cfg
from handlers._registry import register_solana_handler
from solana_client import get_kamino_obligation

logger = logging.getLogger(__name__)

_API_BASE = "https://api.kamino.finance"
_API_TIMEOUT = 15


def _get_obligation_from_api(obligation_pubkey: str, market_id: str,
                             target_date: date) -> dict:
    """Fetch historical obligation snapshot from Kamino REST API.

    Returns dict with 'deposits' and 'borrows' matching the on-chain format.
    """
    url = f"{_API_BASE}/v2/kamino-market/{market_id}/obligations/{obligation_pubkey}/metrics/history"
    resp = requests.get(url, timeout=_API_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    history = data.get("history", [])
    if not history:
        raise ValueError(f"No history for obligation {obligation_pubkey} in market {market_id}")

    # Find snapshot closest to target_date (entries are daily at 00:00 UTC)
    target_str = target_date.isoformat()
    best = None
    for entry in history:
        entry_date = entry["timestamp"][:10]  # "2026-03-31T00:00:00.000Z" -> "2026-03-31"
        if entry_date <= target_str:
            best = entry

    if best is None:
        raise ValueError(f"No history entry at or before {target_date} for {obligation_pubkey}")

    logger.info("kamino.api_history(%s, %s) → snapshot at %s",
                 obligation_pubkey[:10], target_date, best["timestamp"][:10])

    # Convert API format to match on-chain parse format
    deposits = []
    for dep in best.get("deposits", []):
        deposits.append({
            "reserve": dep["reserve"],
            "deposited_amount": int(dep["amount"]),
            "market_value": Decimal(dep.get("marketValueRefreshed", "0")),
        })

    borrows = []
    for bor in best.get("borrows", []):
        # API returns borrow amount as a decimal string (includes interest)
        raw_amount = Decimal(bor["amount"])
        borrows.append({
            "reserve": bor["reserve"],
            "borrowed_amount": raw_amount,
            "market_value": Decimal(bor.get("marketValueRefreshed", "0")),
        })

    return {
        "deposits": deposits,
        "borrows": borrows,
        "last_update_slot": best["timestamp"],
    }


@register_solana_handler("kamino", display_name="Kamino")
def query_kamino_obligations(wallet, block_ts, valuation_date=None):
    """Query Kamino lending obligation positions (leveraged).

    When valuation_date is provided, uses Kamino REST API for historical
    snapshots instead of on-chain state.
    """
    solana_cfg = _load_solana_cfg()
    obligations = solana_cfg.get("kamino", {}).get("obligations", [])
    use_api = valuation_date is not None and valuation_date < date.today()

    rows = []
    for ob_cfg in obligations:
        if use_api:
            market_id = ob_cfg.get("market_id")
            if not market_id:
                logger.warning("kamino: no market_id for %s, falling back to on-chain",
                                ob_cfg["obligation_pubkey"])
                ob = get_kamino_obligation(ob_cfg["obligation_pubkey"])
            else:
                ob = _get_obligation_from_api(
                    ob_cfg["obligation_pubkey"], market_id, valuation_date)
        else:
            ob = get_kamino_obligation(ob_cfg["obligation_pubkey"])

        logger.info("kamino.%s(%s) → %d deposits, %d borrows",
                     "api" if use_api else "rpc",
                     ob_cfg["obligation_pubkey"][:10],
                     len(ob["deposits"]), len(ob["borrows"]))

        # Build combined obligation label
        dep_symbols = [d["symbol"] for d in ob_cfg["deposits"]]
        bor_symbols = [b["symbol"] for b in ob_cfg["borrows"]]
        ob_label = f"Kamino {ob_cfg['market_name']} {' / '.join(dep_symbols + bor_symbols)}"

        # Match deposits to config by reserve pubkey
        for deposit in ob["deposits"]:
            dep_cfg = next(
                (d for d in ob_cfg["deposits"] if d["reserve"] == deposit["reserve"]),
                None
            )
            if dep_cfg is None:
                continue

            amount = Decimal(deposit["deposited_amount"]) / Decimal(10 ** dep_cfg["decimals"])
            rows.append({
                "chain": "solana", "protocol": "kamino", "wallet": wallet,
                "position_label": ob_label,
                "category": "D", "position_type": "collateral",
                "token_symbol": dep_cfg["symbol"],
                "underlying_symbol": dep_cfg.get("underlying", ""),
                "token_contract": dep_cfg.get("mint", ""),
                "token_category": dep_cfg["category"],
                "balance_raw": str(deposit["deposited_amount"]),
                "balance_human": amount,
                "decimals": dep_cfg["decimals"],
                "block_number": str(ob.get("last_update_slot", "latest")),
                "block_timestamp_utc": block_ts,
            })

        # Match borrows
        for borrow in ob["borrows"]:
            bor_cfg = next(
                (b for b in ob_cfg["borrows"] if b["reserve"] == borrow["reserve"]),
                None
            )
            if bor_cfg is None:
                continue

            amount = borrow["borrowed_amount"] / Decimal(10 ** bor_cfg["decimals"])
            rows.append({
                "chain": "solana", "protocol": "kamino", "wallet": wallet,
                "position_label": ob_label,
                "category": "D", "position_type": "debt",
                "token_symbol": bor_cfg["symbol"],
                "token_contract": bor_cfg.get("mint", ""),
                "token_category": bor_cfg["category"],
                "balance_raw": str(borrow["borrowed_amount"]),
                "balance_human": -amount,  # negative for debt
                "decimals": bor_cfg["decimals"],
                "block_number": str(ob.get("last_update_slot", "latest")),
                "block_timestamp_utc": block_ts,
            })

    return rows
