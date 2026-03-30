"""DefiLlama price adapter.

Aggregated price from DefiLlama's coins API, which combines DEX and CEX
sources across all chains. Used as the last-resort fallback in the
pricing hierarchy, replacing per-pool DEX TWAP configs.

API: GET https://coins.llama.fi/prices/current/{chain}:{address}
Supports batch queries (comma-separated). No auth required.

Replaces the previous dex_twap adapter. Rationale:
- Aggregates all DEX liquidity (Uniswap, Curve, etc.) + CEX data
- Chain-agnostic (one adapter for EVM + Solana)
- No pool-specific config (addresses, decimals, inversion)
- Batch support for efficient querying
"""

import logging
import time as _time
from datetime import datetime, timezone
from decimal import Decimal

import requests

from evm import TS_FMT

logger = logging.getLogger(__name__)

_API_BASE = "https://coins.llama.fi/prices/current"
_API_TIMEOUT = 15


def defillama_price(feed_cfg: dict, expected_freq_hours: float = None) -> dict:
    """Query a single token price from DefiLlama.

    Args:
        feed_cfg: Feed config with 'chain' and 'address' fields.
        expected_freq_hours: Expected update frequency for staleness check.

    Returns:
        Standard pricing result dict.
    """
    chain = feed_cfg["chain"]
    address = feed_cfg["address"]
    coin_key = f"{chain}:{address}"

    url = f"{_API_BASE}/{coin_key}"
    logger.info("defillama: GET %s", url)

    resp = requests.get(url, timeout=_API_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    coin_data = data.get("coins", {}).get(coin_key)
    if not coin_data or "price" not in coin_data:
        raise ValueError(f"No price data from DefiLlama for {coin_key}")

    price = Decimal(str(coin_data["price"]))
    timestamp = coin_data.get("timestamp", 0)
    confidence = coin_data.get("confidence", 1.0)
    symbol = coin_data.get("symbol", "")

    if confidence < 0.9:
        logger.warning("defillama: low confidence %.2f for %s (%s)", confidence, coin_key, symbol)

    # Staleness check
    stale_flag = ""
    staleness_hours = None
    if timestamp and expected_freq_hours:
        age_seconds = _time.time() - timestamp
        staleness_hours = round(age_seconds / 3600, 1)
        max_hours = expected_freq_hours * 2
        if staleness_hours > max_hours:
            stale_flag = (
                f"STALE: DefiLlama price {staleness_hours}h old "
                f"(>{max_hours}h = 2x expected {expected_freq_hours}h)"
            )

    updated_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else None

    logger.info("defillama: %s (%s) = $%s confidence=%.2f", coin_key, symbol, price, confidence)

    return {
        "price_usd": price,
        "price_source": f"defillama ({symbol})",
        "oracle_updated_at": updated_dt.strftime(TS_FMT) if updated_dt else None,
        "staleness_hours": staleness_hours,
        "stale_flag": stale_flag,
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "notes": "",
    }


def batch_defillama_prices(feed_configs: list[dict]) -> dict:
    """Batch-query multiple token prices from DefiLlama in one API call.

    Args:
        feed_configs: List of feed config dicts, each with 'chain' and 'address'.

    Returns:
        Dict mapping coin_key ('{chain}:{address}') to price result dicts.
    """
    if not feed_configs:
        return {}

    coin_keys = [f"{fc['chain']}:{fc['address']}" for fc in feed_configs]
    url = f"{_API_BASE}/{','.join(coin_keys)}"
    logger.info("defillama batch: %d tokens", len(coin_keys))

    resp = requests.get(url, timeout=_API_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    results = {}
    for coin_key in coin_keys:
        coin_data = data.get("coins", {}).get(coin_key)
        if not coin_data or "price" not in coin_data:
            continue

        price = Decimal(str(coin_data["price"]))
        timestamp = coin_data.get("timestamp", 0)
        confidence = coin_data.get("confidence", 1.0)
        symbol = coin_data.get("symbol", "")
        updated_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else None

        results[coin_key] = {
            "price_usd": price,
            "price_source": f"defillama ({symbol})",
            "oracle_updated_at": updated_dt.strftime(TS_FMT) if updated_dt else None,
            "staleness_hours": None,
            "stale_flag": "",
            "depeg_flag": "none",
            "depeg_deviation_pct": None,
            "notes": "",
        }

    return results
