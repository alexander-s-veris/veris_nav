"""Pyth Network Hermes REST API price adapter."""

from decimal import Decimal
from datetime import datetime, timezone

import requests

from evm import TS_FMT


def pyth_price(feed_id: str, expected_freq_hours: float = None) -> dict:
    """Query Pyth Hermes REST API for a price feed.

    If expected_freq_hours is provided, checks staleness (>2x expected = stale).
    """
    url = "https://hermes.pyth.network/v2/updates/price/latest"
    resp = requests.get(url, params={"ids[]": feed_id}, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("parsed") or len(data["parsed"]) == 0:
        raise ValueError(f"No Pyth data for feed {feed_id}")

    price_data = data["parsed"][0]["price"]
    price = Decimal(price_data["price"]) * Decimal(10) ** Decimal(price_data["expo"])

    # Pyth publish_time is inside the price object
    publish_time = price_data.get("publish_time")

    oracle_updated_at = None
    staleness_hours = None
    stale_flag = ""

    if publish_time and isinstance(publish_time, (int, float)):
        updated_utc = datetime.fromtimestamp(publish_time, tz=timezone.utc)
        oracle_updated_at = updated_utc.strftime(TS_FMT)
        age_hours = (datetime.now(timezone.utc) - updated_utc).total_seconds() / 3600
        staleness_hours = round(age_hours, 1)

        if expected_freq_hours and age_hours > 2 * expected_freq_hours:
            stale_flag = (
                f"STALE ({age_hours:.0f}h old, expected every "
                f"{expected_freq_hours}h, threshold {2 * expected_freq_hours}h)"
            )

    return {
        "price_usd": price,
        "price_source": "pyth",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": oracle_updated_at,
        "staleness_hours": staleness_hours,
        "stale_flag": stale_flag,
        "notes": "",
    }
