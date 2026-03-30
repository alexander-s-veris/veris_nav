"""Price feed adapters for the Veris NAV system.

Each adapter queries a single price source and returns a standardized result dict.
One file per oracle provider / pricing method.
"""

import json
import os

from evm import CONFIG_DIR

# Lazy-loaded API endpoints from price_feeds.json
_API_ENDPOINTS_CACHE = None


def _load_api_endpoints():
    """Load REST API base URLs from price_feeds.json _api_endpoints section."""
    global _API_ENDPOINTS_CACHE
    if _API_ENDPOINTS_CACHE is None:
        with open(os.path.join(CONFIG_DIR, "price_feeds.json")) as f:
            cfg = json.load(f)
        _API_ENDPOINTS_CACHE = cfg.get("_api_endpoints", {})
    return _API_ENDPOINTS_CACHE


from adapters.chainlink import chainlink_price
from adapters.pyth import pyth_price
from adapters.redstone import redstone_price
from adapters.kraken import kraken_price
from adapters.coingecko import coingecko_price, batch_coingecko_prices
from adapters.defillama import defillama_price, batch_defillama_prices
from adapters.exchange_rate import a1_exchange_rate_price
from adapters.curve_lp import curve_lp_price

__all__ = [
    "chainlink_price",
    "pyth_price",
    "redstone_price",
    "kraken_price",
    "coingecko_price",
    "batch_coingecko_prices",
    "defillama_price",
    "batch_defillama_prices",
    "a1_exchange_rate_price",
    "curve_lp_price",
    "_load_api_endpoints",
]
