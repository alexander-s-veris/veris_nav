"""Price feed adapters for the Veris NAV system.

Each adapter queries a single price source and returns a standardized result dict.
One file per oracle provider / pricing method.
"""

from adapters.chainlink import chainlink_price
from adapters.pyth import pyth_price
from adapters.redstone import redstone_price
from adapters.kraken import kraken_price
from adapters.coingecko import coingecko_price, batch_coingecko_prices
from adapters.dex_twap import dex_twap_price
from adapters.exchange_rate import a1_exchange_rate_price
from adapters.curve_lp import curve_lp_price

__all__ = [
    "chainlink_price",
    "pyth_price",
    "redstone_price",
    "kraken_price",
    "coingecko_price",
    "batch_coingecko_prices",
    "dex_twap_price",
    "a1_exchange_rate_price",
    "curve_lp_price",
]
