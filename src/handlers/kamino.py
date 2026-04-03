"""Kamino Obligations handler (Category D, Solana)."""

import logging
from decimal import Decimal

from handlers import _load_solana_cfg
from handlers._registry import register_solana_handler
from solana_client import get_kamino_obligation

logger = logging.getLogger(__name__)


@register_solana_handler("kamino", display_name="Kamino")
def query_kamino_obligations(wallet, block_ts):
    """Query Kamino lending obligation positions (leveraged).

    Reads obligation configs from solana_protocols.json kamino section.
    Returns collateral + debt rows for each known obligation.
    Label format: "Kamino {market} {deposit1} / {deposit2} / {borrow1}"
    """
    solana_cfg = _load_solana_cfg()
    obligations = solana_cfg.get("kamino", {}).get("obligations", [])

    rows = []
    for ob_cfg in obligations:
        ob = get_kamino_obligation(ob_cfg["obligation_pubkey"])
        logger.info("kamino.getAccountInfo(%s) → %d deposits, %d borrows",
                     ob_cfg["obligation_pubkey"], len(ob["deposits"]), len(ob["borrows"]))

        # Build combined obligation label from all deposit + borrow symbols
        dep_symbols = [d["symbol"] for d in ob_cfg["deposits"]]
        bor_symbols = [b["symbol"] for b in ob_cfg["borrows"]]
        all_symbols = dep_symbols + bor_symbols
        ob_label = f"Kamino {ob_cfg['market_name']} {' / '.join(all_symbols)}"

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
