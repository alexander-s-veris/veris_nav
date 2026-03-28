"""Kraken public ticker API price adapter."""

import logging
from decimal import Decimal

import requests

from adapters import _load_api_endpoints

logger = logging.getLogger(__name__)


def kraken_price(pair: str) -> dict:
    """Query Kraken public ticker API."""
    url = _load_api_endpoints()["kraken"]
    resp = requests.get(url, params={"pair": pair}, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get("error") and len(data["error"]) > 0:
        raise ValueError(f"Kraken error for {pair}: {data['error']}")

    # Kraken returns results keyed by their internal pair name
    result_key = list(data["result"].keys())[0]
    # 'c' = last trade close price [price, lot_volume]
    last_price = Decimal(data["result"][result_key]["c"][0])

    logger.info("kraken.ticker(%s) → price=%s", pair, last_price)

    return {
        "price_usd": last_price,
        "price_source": "kraken",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": None,
        "staleness_hours": None,
        "stale_flag": "",
        "notes": "",
    }
