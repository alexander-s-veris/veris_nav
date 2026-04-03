"""Redstone Finance REST API price adapter."""

import logging
from decimal import Decimal
from datetime import datetime, timezone

import requests

from evm import TS_FMT
from adapters import _load_api_endpoints

logger = logging.getLogger(__name__)


def redstone_price(symbol: str, valuation_ts: int = None) -> dict:
    """Query Redstone Finance REST API for a price feed.

    When valuation_ts is provided, uses toTimestamp for historical price.
    Free, no API key needed. Tier 3 in A2 hierarchy (after Chainlink, Pyth).
    """
    url = _load_api_endpoints()["redstone"]
    params = {"symbols": symbol, "provider": "redstone"}
    if valuation_ts:
        params["toTimestamp"] = valuation_ts * 1000  # Redstone uses milliseconds
        params["limit"] = 1
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if symbol not in data:
        raise ValueError(f"Redstone: no price for {symbol}")

    entry = data[symbol]
    price = Decimal(str(entry["value"]))

    # Redstone timestamp is in milliseconds
    ts_ms = entry.get("timestamp")
    oracle_updated_at = None
    staleness_hours = None
    if ts_ms:
        updated_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        oracle_updated_at = updated_utc.strftime(TS_FMT)
        age_hours = (datetime.now(timezone.utc) - updated_utc).total_seconds() / 3600
        staleness_hours = round(age_hours, 1)

    logger.info("redstone.price(%s) → price=%s, updated=%s", symbol, price, oracle_updated_at)

    return {
        "price_usd": price,
        "price_source": "redstone",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": oracle_updated_at,
        "staleness_hours": staleness_hours,
        "stale_flag": "",
        "notes": "",
    }
