"""Kraken public ticker API price adapter."""

import logging
from decimal import Decimal

import requests

from adapters import _load_api_endpoints

logger = logging.getLogger(__name__)


def kraken_price(pair: str, valuation_ts: int = None) -> dict:
    """Query Kraken public ticker or OHLC API.

    When valuation_ts is provided, uses OHLC endpoint for historical close price.
    """
    if valuation_ts:
        return _kraken_historical(pair, valuation_ts)

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


def _kraken_historical(pair: str, valuation_ts: int) -> dict:
    """Query Kraken OHLC for historical daily close price."""
    # Request daily candles starting from the target timestamp
    url = "https://api.kraken.com/0/public/OHLC"
    resp = requests.get(url, params={"pair": pair, "interval": 1440, "since": valuation_ts}, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get("error") and len(data["error"]) > 0:
        raise ValueError(f"Kraken OHLC error for {pair}: {data['error']}")

    result_key = [k for k in data["result"] if k != "last"][0]
    candles = data["result"][result_key]
    if not candles:
        raise ValueError(f"No Kraken OHLC data for {pair} at ts={valuation_ts}")

    # First candle's close price (index 4)
    close_price = Decimal(str(candles[0][4]))
    candle_ts = candles[0][0]

    logger.info("kraken.ohlc(%s, ts=%d) → close=%s (candle_ts=%d)", pair, valuation_ts, close_price, candle_ts)

    return {
        "price_usd": close_price,
        "price_source": "kraken_historical",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": None,
        "staleness_hours": None,
        "stale_flag": "",
        "notes": "",
    }
