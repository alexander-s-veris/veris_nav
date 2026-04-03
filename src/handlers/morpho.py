"""Morpho Markets handler (Category D)."""

import logging
from decimal import Decimal
from web3 import Web3

from handlers import _load_morpho_cfg, _get_abi, _fmt
from handlers._registry import register_evm_handler
from collect_balances import load_full_registry

logger = logging.getLogger(__name__)

_TOKEN_REGISTRY = None


def _get_token_registry():
    """Load and cache the merged token registry for decimals/category lookups."""
    global _TOKEN_REGISTRY
    if _TOKEN_REGISTRY is None:
        _TOKEN_REGISTRY = load_full_registry()
    return _TOKEN_REGISTRY


def _resolve_token(chain, token_cfg):
    """Resolve decimals and category from the token registry.

    Falls back to morpho_markets.json fields if the token isn't in the registry.
    """
    registry = _get_token_registry()
    chain_reg = registry.get(chain, {})
    addr = token_cfg["address"].lower()
    entry = chain_reg.get(addr) or chain_reg.get(token_cfg["address"]) or {}

    return {
        "symbol": token_cfg["symbol"],
        "address": token_cfg["address"],
        "decimals": entry.get("decimals", token_cfg.get("decimals", 18)),
        "category": entry.get("category", token_cfg.get("category", "")),
    }


@register_evm_handler("morpho", query_type="morpho_leverage", display_name="Morpho (Markets)")
def query_morpho_markets(w3, chain, wallet, block_number, block_ts):
    """Query all Morpho leveraged market positions for a wallet on a chain.

    Reads market configs from morpho_markets.json. Token metadata (decimals,
    category) is resolved from the token registry, not from morpho_markets.json.
    Returns two rows per active position: collateral (positive) and debt (negative).
    """
    morpho_cfg = _load_morpho_cfg()
    chain_cfg = morpho_cfg.get(chain, {})
    morpho_addr = chain_cfg.get("morpho_contract")
    if not morpho_addr:
        return []

    markets = chain_cfg.get("markets", [])
    if not markets:
        return []

    morpho = w3.eth.contract(
        address=Web3.to_checksum_address(morpho_addr), abi=_get_abi("morpho_core"))

    rows = []
    for mkt in markets:
        market_id = bytes.fromhex(mkt["market_id"][2:])

        pos = morpho.functions.position(
            market_id, Web3.to_checksum_address(wallet)).call(block_identifier=block_number)
        supply_shares, borrow_shares, collateral = pos
        logger.info("morpho.position(%s, %s) block=%s → supply_shares=%s, borrow_shares=%s, collateral=%s",
                     morpho_addr, wallet, block_number, supply_shares, borrow_shares, collateral)

        # Skip positions with no collateral and no debt (empty or closed)
        if collateral == 0 and borrow_shares == 0:
            continue

        # Get market state for shares -> assets conversion
        mkt_state = morpho.functions.market(market_id).call(block_identifier=block_number)
        logger.info("morpho.market(%s) block=%s → state=%s", mkt["market_id"], block_number, mkt_state)
        total_borrow_assets, total_borrow_shares = mkt_state[2], mkt_state[3]
        borrow_assets = (
            borrow_shares * total_borrow_assets // total_borrow_shares
            if total_borrow_shares > 0 else 0
        )

        coll = _resolve_token(chain, mkt["collateral_token"])
        loan = _resolve_token(chain, mkt["loan_token"])

        # Collateral row
        coll_human = _fmt(collateral, coll["decimals"])
        rows.append({
            "chain": chain, "protocol": "morpho", "wallet": wallet,
            "position_label": mkt["name"], "category": "D",
            "position_type": "collateral",
            "token_symbol": coll["symbol"],
            "token_contract": coll["address"],
            "token_category": coll["category"],
            "balance_raw": str(collateral),
            "balance_human": coll_human,
            "decimals": coll["decimals"],
            "block_number": block_number, "block_timestamp_utc": block_ts,
            "leverage_market_id": mkt["market_id"],
        })

        # Debt row (negative)
        borrow_human = _fmt(borrow_assets, loan["decimals"])
        rows.append({
            "chain": chain, "protocol": "morpho", "wallet": wallet,
            "position_label": mkt["name"], "category": "D",
            "position_type": "debt",
            "token_symbol": loan["symbol"],
            "token_contract": loan["address"],
            "token_category": loan["category"],
            "balance_raw": str(borrow_assets),
            "balance_human": -borrow_human,  # negative for debt
            "decimals": loan["decimals"],
            "block_number": block_number, "block_timestamp_utc": block_ts,
            "leverage_market_id": mkt["market_id"],
        })

    return rows
