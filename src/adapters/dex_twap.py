"""DEX TWAP price adapters (Uniswap V3 + Curve)."""

import logging
from decimal import Decimal
from datetime import datetime, timezone

from web3 import Web3

from evm import TS_FMT

logger = logging.getLogger(__name__)

# Uniswap V3 observe ABI
_UNI_V3_OBSERVE_ABI = [
    {"inputs": [{"name": "secondsAgos", "type": "uint32[]"}],
     "name": "observe",
     "outputs": [{"name": "tickCumulatives", "type": "int56[]"},
                 {"name": "secondsPerLiquidityCumulativeX128s", "type": "uint160[]"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "slot0",
     "outputs": [{"name": "sqrtPriceX96", "type": "uint160"},
                 {"name": "tick", "type": "int24"},
                 {"name": "observationIndex", "type": "uint16"},
                 {"name": "observationCardinality", "type": "uint16"},
                 {"name": "observationCardinalityNext", "type": "uint16"},
                 {"name": "feeProtocol", "type": "uint8"},
                 {"name": "unlocked", "type": "bool"}],
     "stateMutability": "view", "type": "function"},
]

# Curve get_dy ABI for spot price
_CURVE_DY_ABI = [
    {"inputs": [{"name": "i", "type": "int128"}, {"name": "j", "type": "int128"},
                {"name": "dx", "type": "uint256"}],
     "name": "get_dy", "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
]


def dex_twap_price(feed_cfg: dict, w3: Web3) -> dict:
    """DEX TWAP price — dispatches to Uniswap V3 or Curve based on feed config.

    feed_cfg must have:
    - dex_type: "uniswap_v3" or "curve"
    - pool_address: contract address
    For Uniswap V3: twap_seconds, decimals_0, decimals_1, invert
    For Curve: token_in_index, token_out_index, decimals_in, decimals_out, invert
    """
    dex_type = feed_cfg.get("dex_type", "uniswap_v3")
    if dex_type == "uniswap_v3":
        return _uniswap_v3_twap(feed_cfg, w3)
    elif dex_type == "curve":
        return _curve_spot_price(feed_cfg, w3)
    else:
        raise ValueError(f"Unknown dex_type: {dex_type}")


def _uniswap_v3_twap(feed_cfg: dict, w3: Web3) -> dict:
    """Calculate TWAP from Uniswap V3 pool using observe().

    Uses tick cumulative difference over the window to derive average price.
    """
    pool_addr = feed_cfg["pool_address"]
    twap_seconds = feed_cfg.get("twap_seconds", 1800)
    decimals_0 = feed_cfg.get("decimals_0", 18)
    decimals_1 = feed_cfg.get("decimals_1", 6)
    invert = feed_cfg.get("invert", False)

    pool = w3.eth.contract(
        address=Web3.to_checksum_address(pool_addr),
        abi=_UNI_V3_OBSERVE_ABI,
    )

    # Query tick cumulatives at [twap_seconds ago, 0 (now)]
    tick_cumulatives, _ = pool.functions.observe([twap_seconds, 0]).call()

    # Average tick over the window
    tick_diff = tick_cumulatives[1] - tick_cumulatives[0]
    avg_tick = tick_diff // twap_seconds

    # Tick to price: price = 1.0001^tick, adjusted for decimals
    # Use Decimal exponentiation to avoid float precision loss
    price_raw = Decimal("1.0001") ** avg_tick
    decimal_adjustment = Decimal(10 ** (decimals_0 - decimals_1))
    price = price_raw * decimal_adjustment

    if invert:
        price = Decimal(1) / price if price > 0 else Decimal(0)

    logger.info("dex_twap.uniswap_v3(%s, %ds) → avg_tick=%d, price=%s",
                 pool_addr[:10], twap_seconds, avg_tick, price)

    return {
        "price_usd": price,
        "price_source": f"dex_twap_uniswap_v3 ({twap_seconds}s window)",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": datetime.now(timezone.utc).strftime(TS_FMT),
        "staleness_hours": 0,
        "stale_flag": "",
        "notes": f"Uniswap V3 TWAP from pool {pool_addr[:10]}... over {twap_seconds}s",
    }


def _curve_spot_price(feed_cfg: dict, w3: Web3) -> dict:
    """Get spot price from a Curve pool using get_dy()."""
    pool_addr = feed_cfg["pool_address"]
    i = feed_cfg.get("token_in_index", 0)
    j = feed_cfg.get("token_out_index", 1)
    decimals_in = feed_cfg.get("decimals_in", 18)
    decimals_out = feed_cfg.get("decimals_out", 6)
    invert = feed_cfg.get("invert", False)

    pool = w3.eth.contract(
        address=Web3.to_checksum_address(pool_addr),
        abi=_CURVE_DY_ABI,
    )

    amount_in = 10 ** decimals_in
    amount_out = pool.functions.get_dy(i, j, amount_in).call()
    price = Decimal(str(amount_out)) / Decimal(10 ** decimals_out)

    if invert:
        price = Decimal(1) / price if price > 0 else Decimal(0)

    logger.info("dex_twap.curve(%s, %d→%d) → price=%s", pool_addr[:10], i, j, price)

    return {
        "price_usd": price,
        "price_source": "dex_spot_curve",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": datetime.now(timezone.utc).strftime(TS_FMT),
        "staleness_hours": 0,
        "stale_flag": "",
        "notes": f"Curve pool {pool_addr[:10]}... get_dy({i},{j})",
    }
