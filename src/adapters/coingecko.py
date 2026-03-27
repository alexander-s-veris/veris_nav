"""CoinGecko price adapter (Pro API with key, public fallback)."""

import os
from decimal import Decimal

import requests

COINGECKO_BASE = "https://pro-api.coingecko.com/api/v3"


def coingecko_price(coin_id: str) -> dict:
    """Query CoinGecko simple price API (paid Demo plan with API key)."""
    api_key = os.getenv("COINGECKO_API_KEY")
    headers = {}
    if api_key:
        headers["x-cg-pro-api-key"] = api_key

    resp = requests.get(
        f"{COINGECKO_BASE}/simple/price",
        params={"ids": coin_id, "vs_currencies": "usd"},
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    if coin_id not in data or "usd" not in data[coin_id]:
        raise ValueError(f"CoinGecko: no price for {coin_id}")

    price = Decimal(str(data[coin_id]["usd"]))

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

    api_key = os.getenv("COINGECKO_API_KEY")
    headers = {}
    if api_key:
        headers["x-cg-pro-api-key"] = api_key

    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/simple/price",
            params={"ids": ",".join(cg_ids), "vs_currencies": "usd"},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
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

    return results
