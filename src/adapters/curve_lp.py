"""Curve LP token pricing via get_virtual_price()."""

import logging
from decimal import Decimal

from web3 import Web3

logger = logging.getLogger(__name__)


def curve_lp_price(token_entry: dict, w3_eth: Web3 | None, eth_block: int = None) -> dict:
    """Category C: Curve LP token priced via get_virtual_price().

    For stablecoin pools, virtual_price * $1 gives a good approximation.
    """
    pricing = token_entry.get("pricing", {})
    symbol = token_entry.get("symbol", "UNKNOWN")
    pool_addr = pricing.get("pool_address")

    if not pool_addr or not w3_eth:
        return _unavailable(symbol)

    try:
        abi = [{"inputs": [], "name": "get_virtual_price",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view", "type": "function"}]
        pool = w3_eth.eth.contract(
            address=Web3.to_checksum_address(pool_addr), abi=abi)
        call_kwargs = {"block_identifier": eth_block} if eth_block else {}
        vp = pool.functions.get_virtual_price().call(**call_kwargs)
        price = Decimal(str(vp)) / Decimal(10**18)

        logger.info("curve.get_virtual_price(%s) → %s (price=%s)", pool_addr[:10], vp, price)

        return {
            "price_usd": price,
            "price_source": "curve_virtual_price",
            "depeg_flag": "none",
            "depeg_deviation_pct": None,
            "oracle_updated_at": None,
            "staleness_hours": None,
            "stale_flag": "",
            "notes": f"Curve virtual price: {price:.6f}",
        }
    except Exception as e:
        result = _unavailable(symbol)
        result["notes"] = f"Curve virtual price failed: {e}"
        return result


def _unavailable(symbol: str) -> dict:
    return {
        "price_usd": Decimal("0"),
        "price_source": "unavailable",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": None,
        "staleness_hours": None,
        "stale_flag": "",
        "notes": f"No price source available for {symbol}",
    }
