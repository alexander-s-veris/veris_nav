"""
Price fetching adapters for the Veris NAV data collection system.

Implements the Valuation Policy pricing hierarchy:
  - Category E par: $1.00 with Chainlink de-peg check (Section 6.7 / 9.4)
  - Category E oracle: Chainlink → Pyth fallback (Section 6.2 tier 1)
  - Category F: Kraken → CoinGecko fallback (Section 6.8)
"""

import os
from decimal import Decimal
from datetime import datetime, timezone

import requests
from web3 import Web3

from evm import AGGREGATOR_V3_ABI, TS_FMT
from solana_client import get_eusx_exchange_rate
from block_utils import concurrent_query

# --- Price cache: keyed by symbol, stores result dict ---
_price_cache: dict[str, dict] = {}

COINGECKO_BASE = "https://pro-api.coingecko.com/api/v3"


def get_price(token_entry: dict, w3_eth: Web3 | None = None) -> dict:
    """Main dispatcher. Returns a price result dict.

    Checks cache first (keyed by symbol). Routes to the correct adapter
    based on token_entry["pricing"]["method"].
    """
    symbol = token_entry["symbol"]
    if symbol in _price_cache:
        return _price_cache[symbol]

    method = token_entry["pricing"]["method"]

    if method == "par":
        result = par_price(token_entry, w3_eth)
    elif method == "chainlink":
        result = _price_chainlink_with_fallback(token_entry, w3_eth)
    elif method == "kraken":
        result = _price_kraken_with_fallback(token_entry)
    elif method == "pyth":
        feed_id = token_entry["pricing"].get("pyth_feed_id")
        if feed_id:
            try:
                result = pyth_price(feed_id)
            except Exception:
                result = _unavailable(symbol)
        else:
            result = _unavailable(symbol)
    elif method == "coingecko":
        cg_id = token_entry["pricing"].get("coingecko_id")
        if cg_id:
            try:
                result = coingecko_price(cg_id)
            except Exception:
                result = _unavailable(symbol)
        else:
            result = _unavailable(symbol)
    elif method == "a1_exchange_rate":
        result = _a1_exchange_rate_price(token_entry)
    else:
        result = _unavailable(symbol)

    _price_cache[symbol] = result
    return result


def par_price(token_entry: dict, w3_eth: Web3 | None = None) -> dict:
    """Category E par pricing.

    Price = $1.00, then run Chainlink de-peg check if feed is configured.
    Per Section 9.4: >0.5% deviation = minor, >2% = material.
    """
    result = {
        "price_usd": Decimal("1.00"),
        "price_source": "par",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": None,
        "notes": "",
    }

    depeg_feed = token_entry["pricing"].get("depeg_check_feed")
    if not depeg_feed or not w3_eth:
        return result

    # Query Chainlink for de-peg check
    try:
        cl_result = chainlink_price(depeg_feed, w3_eth)
        oracle_price = cl_result["price_usd"]
        deviation = abs(oracle_price - Decimal("1")) * Decimal("100")

        result["oracle_updated_at"] = cl_result.get("oracle_updated_at")

        if deviation > Decimal("2"):
            result["price_usd"] = oracle_price
            result["price_source"] = "chainlink (de-peg override)"
            result["depeg_flag"] = f"material_{deviation:.2f}%"
            result["notes"] = f"Material de-peg detected: {deviation:.2f}% deviation. Priced at oracle value per Section 9.4."
        elif deviation > Decimal("0.5"):
            result["price_usd"] = oracle_price
            result["price_source"] = "chainlink (de-peg override)"
            result["depeg_flag"] = f"minor_{deviation:.2f}%"
            result["notes"] = f"Minor de-peg detected: {deviation:.2f}% deviation. Priced at oracle value per Section 9.4."
        # else: within tolerance, keep par
    except Exception as e:
        result["notes"] = f"De-peg check failed: {e}"

    return result


def chainlink_price(feed_address: str, w3: Web3) -> dict:
    """Query a Chainlink AggregatorV3 feed.

    Returns price as Decimal with metadata.
    """
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(feed_address),
        abi=AGGREGATOR_V3_ABI,
    )

    decimals = contract.functions.decimals().call()
    _round_id, answer, _started_at, updated_at, _answered_in_round = (
        contract.functions.latestRoundData().call()
    )

    price = Decimal(answer) / Decimal(10**decimals)
    updated_utc = datetime.fromtimestamp(updated_at, tz=timezone.utc)

    return {
        "price_usd": price,
        "price_source": "chainlink",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": updated_utc.strftime(TS_FMT),
        "notes": "",
    }


def pyth_price(feed_id: str) -> dict:
    """Query Pyth Hermes REST API for a price feed."""
    url = f"https://hermes.pyth.network/v2/updates/price/latest"
    resp = requests.get(url, params={"ids[]": feed_id}, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("parsed") or len(data["parsed"]) == 0:
        raise ValueError(f"No Pyth data for feed {feed_id}")

    price_data = data["parsed"][0]["price"]
    price = Decimal(price_data["price"]) * Decimal(10) ** Decimal(price_data["expo"])

    return {
        "price_usd": price,
        "price_source": "pyth",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": None,
        "notes": "",
    }


def kraken_price(pair: str) -> dict:
    """Query Kraken public ticker API."""
    url = f"https://api.kraken.com/0/public/Ticker"
    resp = requests.get(url, params={"pair": pair}, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get("error") and len(data["error"]) > 0:
        raise ValueError(f"Kraken error for {pair}: {data['error']}")

    # Kraken returns results keyed by their internal pair name
    result_key = list(data["result"].keys())[0]
    # 'c' = last trade close price [price, lot_volume]
    last_price = Decimal(data["result"][result_key]["c"][0])

    return {
        "price_usd": last_price,
        "price_source": "kraken",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": None,
        "notes": "",
    }


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
        "notes": "",
    }


# --- A1 exchange rate pricing ---

def _a1_exchange_rate_price(token_entry: dict) -> dict:
    """Category A1: query on-chain exchange rate, then price underlying via Pyth.

    Currently supports eUSX (Solana): eUSX/USX rate from vault, then USX price from Pyth.
    """
    pricing = token_entry["pricing"]
    symbol = token_entry["symbol"]
    underlying_feed = pricing.get("underlying_pyth_feed_id")

    try:
        # Get exchange rate (eUSX → USX)
        exchange_rate = get_eusx_exchange_rate()

        # Get underlying price (USX → USD) via Pyth
        underlying_price = pyth_price(underlying_feed)
        usx_usd = underlying_price["price_usd"]

        # eUSX price = exchange_rate x USX/USD
        price = exchange_rate * usx_usd

        return {
            "price_usd": price,
            "price_source": f"a1_exchange_rate (rate={exchange_rate:.6f}) x pyth",
            "depeg_flag": "none",
            "depeg_deviation_pct": None,
            "oracle_updated_at": underlying_price.get("oracle_updated_at"),
            "notes": f"eUSX/USX rate: {exchange_rate:.6f}, USX/USD: {usx_usd}",
        }
    except Exception as e:
        result = _unavailable(symbol)
        result["notes"] = f"A1 exchange rate failed: {e}"
        return result


# --- Internal fallback helpers ---

def _price_chainlink_with_fallback(token_entry: dict, w3_eth: Web3 | None) -> dict:
    """Category E oracle-priced: Chainlink → Pyth → CoinGecko fallback."""
    pricing = token_entry["pricing"]

    # Try Chainlink
    if pricing.get("chainlink_feed") and w3_eth:
        try:
            return chainlink_price(pricing["chainlink_feed"], w3_eth)
        except Exception as e:
            pass  # fall through to Pyth

    # Try Pyth
    if pricing.get("pyth_feed_id"):
        try:
            return pyth_price(pricing["pyth_feed_id"])
        except Exception:
            pass

    # Try CoinGecko
    if pricing.get("coingecko_id"):
        try:
            return coingecko_price(pricing["coingecko_id"])
        except Exception:
            pass

    return _unavailable(token_entry["symbol"])


def _price_kraken_with_fallback(token_entry: dict) -> dict:
    """Category F: Kraken → CoinGecko fallback."""
    pricing = token_entry["pricing"]

    # Try Kraken
    if pricing.get("kraken_pair"):
        try:
            return kraken_price(pricing["kraken_pair"])
        except Exception:
            pass

    # Try CoinGecko
    if pricing.get("coingecko_id"):
        try:
            return coingecko_price(pricing["coingecko_id"])
        except Exception:
            pass

    return _unavailable(token_entry["symbol"])


def _unavailable(symbol: str) -> dict:
    """Return a result indicating price is unavailable."""
    return {
        "price_usd": Decimal("0"),
        "price_source": "unavailable",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": None,
        "notes": f"No price source available for {symbol}",
    }


# --- Batch / concurrent pricing ---

def _batch_coingecko(tokens: dict[str, dict]) -> dict[str, dict]:
    """Batch-fetch CoinGecko prices for multiple tokens in one API call.

    CoinGecko supports comma-separated IDs, so we can price all CoinGecko
    tokens in a single request instead of N requests.

    Args:
        tokens: {symbol: token_entry} for tokens using coingecko pricing.

    Returns:
        {symbol: price_result} for successfully priced tokens.
    """
    # Collect CoinGecko IDs
    cg_map = {}  # coingecko_id -> symbol
    for symbol, entry in tokens.items():
        cg_id = entry.get("pricing", {}).get("coingecko_id")
        if cg_id:
            cg_map[cg_id] = symbol

    if not cg_map:
        return {}

    api_key = os.getenv("COINGECKO_API_KEY")
    headers = {}
    if api_key:
        headers["x-cg-pro-api-key"] = api_key

    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/simple/price",
            params={"ids": ",".join(cg_map.keys()), "vs_currencies": "usd"},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}

    results = {}
    for cg_id, symbol in cg_map.items():
        if cg_id in data and "usd" in data[cg_id]:
            results[symbol] = {
                "price_usd": Decimal(str(data[cg_id]["usd"])),
                "price_source": "coingecko",
                "depeg_flag": "none",
                "depeg_deviation_pct": None,
                "oracle_updated_at": None,
                "notes": "",
            }

    return results


def get_prices_concurrent(
    unique_tokens: dict[str, dict],
    w3_eth: Web3 | None = None,
    max_workers: int = 10,
) -> dict[str, dict]:
    """Price all tokens concurrently with CoinGecko batching.

    Strategy:
    1. Batch all CoinGecko-eligible tokens into one API call
    2. Pre-populate cache with batched results
    3. Price remaining tokens (Chainlink, Kraken, Pyth, par, A1) concurrently

    Args:
        unique_tokens: {symbol: token_entry} from the balance scanner.
        w3_eth: Web3 instance for Chainlink calls (can be None).
        max_workers: Concurrent threads for non-CoinGecko pricing.

    Returns:
        {symbol: price_result} for all tokens.
    """
    results = {}

    # Step 1: Identify CoinGecko-only tokens (method=coingecko or fallback)
    # and batch them in one call
    cg_tokens = {}
    non_cg_tokens = {}
    for symbol, entry in unique_tokens.items():
        method = entry.get("pricing", {}).get("method", "")
        if method == "coingecko":
            cg_tokens[symbol] = entry
        else:
            non_cg_tokens[symbol] = entry

    # Batch CoinGecko
    if cg_tokens:
        cg_results = _batch_coingecko(cg_tokens)
        results.update(cg_results)
        # Pre-populate cache so get_price() won't re-fetch
        for symbol, result in cg_results.items():
            _price_cache[symbol] = result

    # Step 2: Price non-CoinGecko tokens concurrently
    remaining = [(s, e) for s, e in non_cg_tokens.items() if s not in results]

    if remaining:
        def price_one(item):
            symbol, entry = item
            return symbol, get_price(entry, w3_eth)

        concurrent_results = concurrent_query(
            query_fn=price_one,
            items=remaining,
            max_workers=max_workers,
        )

        for symbol, result in concurrent_results:
            results[symbol] = result

    # Also add any CoinGecko tokens that failed the batch (price them individually)
    for symbol in cg_tokens:
        if symbol not in results:
            results[symbol] = get_price(cg_tokens[symbol], w3_eth)

    return results
