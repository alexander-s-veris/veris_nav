"""Uniswap V4 handler (Category C -- concentrated liquidity NFT)."""

import logging
from decimal import Decimal
from web3 import Web3

from handlers import _load_contracts_cfg, _get_abi

logger = logging.getLogger(__name__)


def query_uniswap_v4(w3, chain, wallet, block_number, block_ts):
    """Query Uniswap V4 NFT LP positions.

    Reads position manager address and NFT IDs from contracts.json _uniswap section.
    Reports liquidity amount for each owned NFT.
    """
    contracts = _load_contracts_cfg()
    uni_section = contracts.get(chain, {}).get("_uniswap", {})
    pm_entry = uni_section.get("v4_position_manager", {})
    PM = pm_entry.get("address")
    nft_ids = pm_entry.get("nft_ids", [])
    pool_label = pm_entry.get("pool_label", "Uniswap V4 LP")
    pool_fee = pm_entry.get("pool_fee", "")
    if not PM or not nft_ids:
        return []

    pm = w3.eth.contract(address=Web3.to_checksum_address(PM), abi=_get_abi("uniswap_v4_pm"))

    rows = []
    for nft_id in nft_ids:
        try:
            owner = pm.functions.ownerOf(nft_id).call()
            logger.info("uniswap.ownerOf(%s, nft=%s) block=%s → %s", PM, nft_id, block_number, owner)
        except Exception:
            continue

        if owner.lower() != wallet.lower():
            continue

        liquidity = pm.functions.getPositionLiquidity(nft_id).call()
        logger.info("uniswap.getPositionLiquidity(%s, nft=%s) block=%s → %s", PM, nft_id, block_number, liquidity)
        if liquidity == 0:
            continue

        rows.append({
            "chain": chain, "protocol": "uniswap_v4", "wallet": wallet,
            "position_label": f"{pool_label} #{nft_id}",
            "category": "C", "position_type": "lp_position",
            "token_symbol": f"UNI-V4-{nft_id}",
            "token_contract": PM,
            "balance_raw": str(liquidity),
            "balance_human": Decimal(str(liquidity)),
            "nft_id": nft_id,
            "block_number": block_number, "block_timestamp_utc": block_ts,
            "notes": f"Concentrated liquidity {pool_label} {pool_fee}. NFT #{nft_id}.",
        })

    return rows
