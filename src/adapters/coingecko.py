"""CoinGecko price adapter (Pro API with key, public fallback)."""

import logging
import os
from decimal import Decimal

import requests

from adapters import _load_api_endpoints

logger = logging.getLogger(__name__)


def coingecko_price(coin_id: str, valuation_ts: int = None) -> dict:
    """Query CoinGecko price API. Uses /history endpoint for historical dates."""
    base_url = _load_api_endpoints()["coingecko"]
    api_key = os.getenv("COINGECKO_API_KEY")
    headers = {}
    if api_key:
        headers["x-cg-pro-api-key"] = api_key

    if valuation_ts:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(valuation_ts, tz=timezone.utc)
        date_str = dt.strftime("%d-%m-%Y")
        resp = requests.get(
            f"{base_url}/coins/{coin_id}/history",
            params={"date": date_str, "localization": "false"},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        price = Decimal(str(data.get("market_data", {}).get("current_price", {}).get("usd", 0)))
        if price <= 0:
            raise ValueError(f"CoinGecko: no historical price for {coin_id} at {date_str}")
        logger.info("coingecko.history(%s, %s) → %s", coin_id, date_str, price)
        return {
            "price_usd": price,
            "price_source": "coingecko_historical",
            "depeg_flag": "none",
            "depeg_deviation_pct": None,
            "oracle_updated_at": None,
            "staleness_hours": None,
            "stale_flag": "",
            "notes": "",
        }

    resp = requests.get(
        f"{base_url}/simple/price",
        params={"ids": coin_id, "vs_currencies": "usd"},
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    if coin_id not in data or "usd" not in data[coin_id]:
        raise ValueError(f"CoinGecko: no price for {coin_id}")

    price = Decimal(str(data[coin_id]["usd"]))

    logger.info("coingecko.price(%s) → %s", coin_id, price)

    return {
        "price_usd": price,
        "price_source": "coingecko",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": None,
        "staleness_hours": None,
        "stale_flag": "",
        "notes": "",
    }


def batch_coingecko_prices(cg_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch CoinGecko prices for multiple coin IDs in one API call.

    Args:
        cg_ids: List of CoinGecko coin IDs.

    Returns:
        {coin_id: price_result} for successfully priced coins.
    """
    if not cg_ids:
        return {}

    base_url = _load_api_endpoints()["coingecko"]
    api_key = os.getenv("COINGECKO_API_KEY")
    headers = {}
    if api_key:
        headers["x-cg-pro-api-key"] = api_key

    try:
        resp = requests.get(
            f"{base_url}/simple/price",
            params={"ids": ",".join(cg_ids), "vs_currencies": "usd"},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("coingecko batch request failed for %d IDs: %s", len(cg_ids), e)
        return {}

    results = {}
    for cg_id in cg_ids:
        if cg_id in data and "usd" in data[cg_id]:
            results[cg_id] = {
                "price_usd": Decimal(str(data[cg_id]["usd"])),
                "price_source": "coingecko",
                "depeg_flag": "none",
                "depeg_deviation_pct": None,
                "oracle_updated_at": None,
                "staleness_hours": None,
                "stale_flag": "",
                "notes": "",
            }

    logger.info("coingecko.batch(%d ids) → %d prices", len(cg_ids), len(results))

    return results
