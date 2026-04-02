"""Uniswap V4 handler (Category C -- concentrated liquidity NFT).

Decomposes LP positions into token0 + token1 amounts based on the
position's tick range and current pool tick. Each constituent is
priced per its own category.

Per Valuation Policy Section 6.5: value reflects actual token amounts
within the position's active range at the Valuation Block. If price
is outside the range, the position holds only one token.
"""

import logging
import math
from decimal import Decimal
from web3 import Web3

from handlers import _load_contracts_cfg, _get_abi
from handlers._registry import register_evm_handler

logger = logging.getLogger(__name__)


def _decode_position_info(info_bytes: bytes) -> dict:
    """Decode V4 PositionInfo from packed bytes32.

    Layout from LSB: hasSubscriber(8) | tickLower(24) | tickUpper(24) | poolId(200)
    """
    val = int.from_bytes(info_bytes, "big")

    has_subscriber = val & 0xFF

    tick_lower_raw = (val >> 8) & 0xFFFFFF
    tick_lower = tick_lower_raw - (1 << 24) if tick_lower_raw >= (1 << 23) else tick_lower_raw

    tick_upper_raw = (val >> 32) & 0xFFFFFF
    tick_upper = tick_upper_raw - (1 << 24) if tick_upper_raw >= (1 << 23) else tick_upper_raw

    return {"tick_lower": tick_lower, "tick_upper": tick_upper}


def _compute_amounts(liquidity: int, tick_lower: int, tick_upper: int,
                     current_tick: int, decimals0: int, decimals1: int) -> tuple:
    """Compute token0 and token1 amounts from concentrated liquidity position.

    Uses standard Uniswap V3/V4 math:
    - Below range: all token0
    - Above range: all token1
    - In range: mix of both
    """
    sa = math.sqrt(1.0001 ** tick_lower)
    sb = math.sqrt(1.0001 ** tick_upper)
    sp = math.sqrt(1.0001 ** current_tick)

    if current_tick < tick_lower:
        # Below range — all token0
        amount0 = liquidity * (1 / sa - 1 / sb)
        amount1 = 0
    elif current_tick >= tick_upper:
        # Above range — all token1
        amount0 = 0
        amount1 = liquidity * (sb - sa)
    else:
        # In range
        amount0 = liquidity * (1 / sp - 1 / sb)
        amount1 = liquidity * (sp - sa)

    return (
        Decimal(str(amount0)) / Decimal(10 ** decimals0),
        Decimal(str(amount1)) / Decimal(10 ** decimals1),
    )


def _estimate_current_tick(decimals0: int, decimals1: int, price_ratio: float) -> int:
    """Estimate the current pool tick from a price ratio.

    price_ratio = price of token0 in terms of token1 (e.g. 1.02 USDC per DUSD)
    Uniswap tick: price = 1.0001^tick * 10^(decimals0 - decimals1)
    So: tick = log(price_ratio / 10^(decimals0 - decimals1)) / log(1.0001)
    """
    decimal_adj = 10 ** (decimals0 - decimals1)
    return int(math.log(price_ratio / decimal_adj) / math.log(1.0001))


@register_evm_handler("uniswap_v4", query_type="nft_lp", display_name="Uniswap V4")
def query_uniswap_v4(w3, chain, wallet, block_number, block_ts):
    """Query Uniswap V4 NFT LP positions and decompose into constituents.

    Reads position manager address, NFT IDs, and token pair info from
    contracts.json _uniswap section. Decomposes each position into
    token0 + token1 amounts based on tick range.
    """
    contracts = _load_contracts_cfg()
    uni_section = contracts.get(chain, {}).get("_uniswap", {})
    pm_entry = uni_section.get("v4_position_manager", {})
    PM = pm_entry.get("address")
    nft_ids = pm_entry.get("nft_ids", [])
    pool_label = pm_entry.get("pool_label", "Uniswap V4 LP")
    pool_fee = pm_entry.get("pool_fee", "")
    token0_cfg = pm_entry.get("token0", {})
    token1_cfg = pm_entry.get("token1", {})

    if not PM or not nft_ids or not token0_cfg or not token1_cfg:
        return []

    pm_abi = _get_abi("uniswap_v4_pm")
    pm = w3.eth.contract(address=Web3.to_checksum_address(PM), abi=pm_abi)

    rows = []
    for nft_id in nft_ids:
        try:
            owner = pm.functions.ownerOf(nft_id).call(block_identifier=block_number)
            logger.info("uniswap.ownerOf(%s, nft=%s) block=%s → %s",
                        PM[:10], nft_id, block_number, owner)
        except Exception as e:
            logger.error("uniswap: ownerOf failed for nft_id=%s: %s", nft_id, e)
            continue

        if owner.lower() != wallet.lower():
            continue

        liquidity = pm.functions.getPositionLiquidity(nft_id).call(block_identifier=block_number)
        logger.info("uniswap.getPositionLiquidity(nft=%s) → %s", nft_id, liquidity)
        if liquidity == 0:
            continue

        # Get tick range from positionInfo
        info_raw = pm.functions.positionInfo(nft_id).call(block_identifier=block_number)
        pos_info = _decode_position_info(info_raw)
        tick_lower = pos_info["tick_lower"]
        tick_upper = pos_info["tick_upper"]
        logger.info("uniswap.positionInfo(nft=%s) → tickLower=%d tickUpper=%d",
                    nft_id, tick_lower, tick_upper)

        dec0 = token0_cfg["decimals"]
        dec1 = token1_cfg["decimals"]

        # Estimate current tick from DefiLlama price of token0
        try:
            from adapters import defillama_price
            feed_cfg = {"chain": chain, "address": token0_cfg["address"]}
            result = defillama_price(feed_cfg)
            price0 = float(result["price_usd"])
            current_tick = _estimate_current_tick(dec0, dec1, price0)
            logger.info("uniswap: estimated current tick=%d from price=%s", current_tick, price0)
        except Exception as e:
            current_tick = (tick_lower + tick_upper) // 2
            logger.warning("uniswap: tick estimation failed (%s), using mid-range=%d", e, current_tick)

        amount0, amount1 = _compute_amounts(
            liquidity, tick_lower, tick_upper, current_tick, dec0, dec1)

        label = f"{pool_label} #{nft_id}"

        # Token0 constituent
        if amount0 > 0:
            rows.append({
                "chain": chain, "protocol": "uniswap_v4", "wallet": wallet,
                "position_label": label,
                "category": "C", "position_type": "lp_constituent",
                "token_symbol": token0_cfg["symbol"],
                "token_contract": token0_cfg["address"],
                "balance_human": amount0,
                "lp_constituent_type": "token0",
                "block_number": block_number, "block_timestamp_utc": block_ts,
                "notes": f"Concentrated liquidity {pool_label} {pool_fee}. NFT #{nft_id}. "
                         f"Ticks [{tick_lower}, {tick_upper}].",
            })

        # Token1 constituent
        if amount1 > 0:
            rows.append({
                "chain": chain, "protocol": "uniswap_v4", "wallet": wallet,
                "position_label": label,
                "category": "C", "position_type": "lp_constituent",
                "token_symbol": token1_cfg["symbol"],
                "token_contract": token1_cfg["address"],
                "balance_human": amount1,
                "lp_constituent_type": "token1",
                "block_number": block_number, "block_timestamp_utc": block_ts,
                "notes": f"Concentrated liquidity {pool_label} {pool_fee}. NFT #{nft_id}. "
                         f"Ticks [{tick_lower}, {tick_upper}].",
            })

    return rows
