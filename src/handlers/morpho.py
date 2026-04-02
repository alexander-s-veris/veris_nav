"""Morpho Markets handler (Category D)."""

import logging
from decimal import Decimal
from web3 import Web3

from handlers import _load_morpho_cfg, _get_abi, _fmt
from handlers._registry import register_evm_handler

logger = logging.getLogger(__name__)


@register_evm_handler("morpho", query_type="morpho_leverage", display_name="Morpho (Markets)")
def query_morpho_markets(w3, chain, wallet, block_number, block_ts):
    """Query all Morpho leveraged market positions for a wallet on a chain.

    Reads market configs from morpho_markets.json. Returns two rows per active
    position: collateral (positive) and debt (negative).
    """
    morpho_cfg = _load_morpho_cfg()
    chain_cfg = morpho_cfg.get(chain, {})
    morpho_addr = chain_cfg.get("morpho_contract")
    if not morpho_addr:
        return []

    markets = [m for m in chain_cfg.get("markets", [])
               if wallet.lower() in [w.lower() for w in m.get("wallets", [])]]
    if not markets:
        return []

    morpho = w3.eth.contract(
        address=Web3.to_checksum_address(morpho_addr), abi=_get_abi("morpho_core"))

    rows = []
    for mkt in markets:
        market_id = bytes.fromhex(mkt["market_id"][2:])
        is_closed = "_note" in mkt and "Closed" in mkt.get("_note", "")

        pos = morpho.functions.position(
            market_id, Web3.to_checksum_address(wallet)).call(block_identifier=block_number)
        supply_shares, borrow_shares, collateral = pos
        logger.info("morpho.position(%s, %s) block=%s → supply_shares=%s, borrow_shares=%s, collateral=%s",
                     morpho_addr, wallet, block_number, supply_shares, borrow_shares, collateral)

        # Check if actually closed
        if is_closed and collateral == 0 and borrow_shares == 0:
            rows.append({
                "chain": chain, "protocol": "morpho", "wallet": wallet,
                "position_label": mkt["name"], "category": "D",
                "position_type": "closed", "status": "CLOSED",
                "block_number": block_number, "block_timestamp_utc": block_ts,
            })
            continue

        # Get market state for shares -> assets conversion
        mkt_state = morpho.functions.market(market_id).call(block_identifier=block_number)
        logger.info("morpho.market(%s) block=%s → state=%s", mkt["market_id"], block_number, mkt_state)
        total_borrow_assets, total_borrow_shares = mkt_state[2], mkt_state[3]
        borrow_assets = (
            borrow_shares * total_borrow_assets // total_borrow_shares
            if total_borrow_shares > 0 else 0
        )

        coll_token = mkt["collateral_token"]
        loan_token = mkt["loan_token"]

        # Collateral row
        coll_human = _fmt(collateral, coll_token["decimals"])
        rows.append({
            "chain": chain, "protocol": "morpho", "wallet": wallet,
            "position_label": mkt["name"], "category": "D",
            "position_type": "collateral",
            "token_symbol": coll_token["symbol"],
            "token_contract": coll_token["address"],
            "token_category": coll_token["category"],
            "balance_raw": str(collateral),
            "balance_human": coll_human,
            "decimals": coll_token["decimals"],
            "block_number": block_number, "block_timestamp_utc": block_ts,
            "leverage_market_id": mkt["market_id"],
        })

        # Debt row (negative)
        borrow_human = _fmt(borrow_assets, loan_token["decimals"])
        rows.append({
            "chain": chain, "protocol": "morpho", "wallet": wallet,
            "position_label": mkt["name"], "category": "D",
            "position_type": "debt",
            "token_symbol": loan_token["symbol"],
            "token_contract": loan_token["address"],
            "token_category": loan_token["category"],
            "balance_raw": str(borrow_assets),
            "balance_human": -borrow_human,  # negative for debt
            "decimals": loan_token["decimals"],
            "block_number": block_number, "block_timestamp_utc": block_ts,
            "leverage_market_id": mkt["market_id"],
        })

    return rows
