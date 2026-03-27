"""
Price fetching adapters for the Veris NAV data collection system.

Implements the Valuation Policy pricing hierarchy driven by config files:
  - config/price_feeds.json    — feed definitions (Chainlink, Pyth, Redstone, Kraken, CoinGecko)
  - config/pricing_policy.json — hierarchy rules per category (A1, A2, E_par, E_oracle, F, etc.)
  - config/tokens.json         — tokens reference feeds by key via pricing.feeds

Adapters (chainlink_price, pyth_price, etc.) are unchanged.
"""

import os
import json
from decimal import Decimal
from datetime import datetime, timezone

import requests
from web3 import Web3

from evm import AGGREGATOR_V3_ABI, TS_FMT
from solana_client import get_eusx_exchange_rate
from block_utils import concurrent_query

# --- Price cache: keyed by (symbol, policy, feed_key), stores result dict ---
_price_cache: dict[str, dict] = {}

COINGECKO_BASE = "https://pro-api.coingecko.com/api/v3"

# --- Config loaders (cached) ---

_FEEDS_CACHE = None
_POLICY_CACHE = None


def _load_feeds_registry() -> dict:
    """Load and flatten config/price_feeds.json.

    The file groups feeds under type keys (chainlink, pyth, etc.).
    This returns a flat dict: feed_key -> feed_cfg, so callers can look up
    any feed by its key regardless of type group.
    """
    global _FEEDS_CACHE
    if _FEEDS_CACHE is None:
        path = os.path.join(os.path.dirname(__file__), "..", "config", "price_feeds.json")
        with open(path) as f:
            raw = json.load(f)
        flat = {}
        for section_key, section_val in raw.items():
            if section_key.startswith("_"):
                continue  # skip _description
            if isinstance(section_val, dict):
                for feed_key, feed_cfg in section_val.items():
                    if isinstance(feed_cfg, dict):
                        flat[feed_key] = feed_cfg
        _FEEDS_CACHE = flat
    return _FEEDS_CACHE


def _load_pricing_policy() -> dict:
    """Load config/pricing_policy.json (cached)."""
    global _POLICY_CACHE
    if _POLICY_CACHE is None:
        path = os.path.join(os.path.dirname(__file__), "..", "config", "pricing_policy.json")
        with open(path) as f:
            _POLICY_CACHE = json.load(f)
    return _POLICY_CACHE


# --- Cache key ---

def _cache_key(token_entry: dict) -> str:
    """Generate a unique cache key for a token's pricing config.

    Uses policy and first feed key to distinguish same-symbol tokens
    with different feeds (e.g. on different chains).
    """
    symbol = token_entry.get("symbol", "UNKNOWN")
    pricing = token_entry.get("pricing", {}) if isinstance(token_entry.get("pricing"), dict) else {}
    policy = pricing.get("policy", "")
    feeds = pricing.get("feeds", {})
    # Use first feed key for cache differentiation
    first_feed = next(iter(feeds.values()), "") if feeds else ""
    return f"{symbol}_{policy}_{first_feed}"


# --- Generic feed query dispatcher ---

def _query_feed(feed_cfg: dict, w3_eth: Web3 | None = None, expected_freq_hours: float = None) -> dict:
    """Query a single price feed based on its type. Returns result dict."""
    feed_type = feed_cfg["type"]
    if feed_type == "chainlink":
        chain = feed_cfg.get("chain", "ethereum")
        if chain != "ethereum":
            from evm import get_web3
            w3 = get_web3(chain)
        else:
            w3 = w3_eth
        if not w3:
            raise ConnectionError(f"No Web3 for chain {chain}")
        return chainlink_price(feed_cfg["address"], w3, expected_freq_hours)
    elif feed_type == "pyth":
        return pyth_price(feed_cfg["feed_id"], expected_freq_hours)
    elif feed_type == "redstone":
        return redstone_price(feed_cfg["symbol"])
    elif feed_type == "kraken":
        return kraken_price(feed_cfg["pair"])
    elif feed_type == "coingecko":
        return coingecko_price(feed_cfg["coin_id"])
    else:
        raise ValueError(f"Unknown feed type: {feed_type}")


# --- Main dispatcher ---

def get_price(token_entry: dict, w3_eth: Web3 | None = None) -> dict:
    """Main dispatcher. Returns a price result dict.

    Reads pricing.policy from the token entry, looks up the method from
    pricing_policy.json, then routes to the correct adapter or hierarchy walker.
    """
    key = _cache_key(token_entry)
    if key in _price_cache:
        return _price_cache[key]

    symbol = token_entry.get("symbol", "UNKNOWN")
    pricing = token_entry.get("pricing", {})
    if not isinstance(pricing, dict):
        pricing = {}
    policy_key = pricing.get("policy", "")
    token_feeds = pricing.get("feeds", {})
    if not isinstance(token_feeds, dict):
        token_feeds = {}
    expected_freq = pricing.get("expected_update_freq_hours")

    feeds_registry = _load_feeds_registry()
    policy = _load_pricing_policy()
    policy_cfg = policy.get(policy_key, {})
    method = policy_cfg.get("method", policy_key)

    if method == "par":
        result = par_price(token_entry, w3_eth)
    elif method in ("oracle_hierarchy", "market_hierarchy"):
        result = _price_with_hierarchy(symbol, token_feeds, policy_cfg, feeds_registry, w3_eth, expected_freq)
    elif method == "exchange_rate":
        # A1: special exchange rate logic
        result = _a1_exchange_rate_price(token_entry)
    elif method == "curve_lp":
        result = _curve_lp_price(token_entry, w3_eth)
    else:
        # manual_accrual (A3), pt_linear_amortisation (B), lp_decomposition (C),
        # net_position (D) — these are handled by valuation.py, not pricing.py.
        # If we reach here, it means no price feed is configured.
        result = _unavailable(symbol)

    _price_cache[key] = result
    return result


# --- Generic hierarchy walker ---

def _price_with_hierarchy(
    symbol: str,
    token_feeds: dict,
    policy_cfg: dict,
    feeds_registry: dict,
    w3_eth: Web3 | None,
    expected_freq: float | None,
) -> dict:
    """Walk the pricing hierarchy, trying each source in order.

    Falls through on error or staleness. Returns the first fresh result,
    or the best stale result if all sources are stale/failed.
    """
    hierarchy = policy_cfg.get("hierarchy", [])
    stale_result = None

    for source_type in hierarchy:
        feed_key = token_feeds.get(source_type)
        if not feed_key:
            continue
        feed_cfg = feeds_registry.get(feed_key)
        if not feed_cfg:
            continue
        try:
            result = _query_feed(feed_cfg, w3_eth, expected_freq)
            if not result.get("stale_flag"):
                return result
            # Stale — save as fallback, note it, try next
            if stale_result is None:
                stale_result = result
        except Exception:
            continue

    # All sources failed or stale
    if stale_result:
        stale_result["notes"] = f"WARNING: {stale_result.get('stale_flag', 'stale')}. No fresher source in hierarchy."
        return stale_result

    return _unavailable(symbol)


# --- Par pricing with depeg check ---

def par_price(token_entry: dict, w3_eth: Web3 | None = None) -> dict:
    """Category E par pricing.

    Price = $1.00, then run depeg check using the depeg_hierarchy from
    pricing_policy.json. Per Section 9.4: >0.5% deviation = minor, >2% = material.
    """
    result = {
        "price_usd": Decimal("1.00"),
        "price_source": "par",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": None,
        "staleness_hours": None,
        "stale_flag": "",
        "notes": "",
    }

    pricing = token_entry.get("pricing", {})
    if not isinstance(pricing, dict):
        pricing = {}
    token_feeds = pricing.get("feeds", {})
    if not isinstance(token_feeds, dict):
        token_feeds = {}

    feeds_registry = _load_feeds_registry()
    policy = _load_pricing_policy()
    policy_key = pricing.get("policy", "E_par")
    policy_cfg = policy.get(policy_key, {})
    depeg_hierarchy = policy_cfg.get("depeg_hierarchy", [])

    if not depeg_hierarchy or not token_feeds:
        return result

    # Walk depeg hierarchy to find the oracle price
    oracle_price = None
    for source_type in depeg_hierarchy:
        feed_key = token_feeds.get(source_type)
        if not feed_key:
            continue
        feed_cfg = feeds_registry.get(feed_key)
        if not feed_cfg:
            continue
        try:
            check_result = _query_feed(feed_cfg, w3_eth)
            oracle_price = check_result["price_usd"]
            result["oracle_updated_at"] = check_result.get("oracle_updated_at")
            result["staleness_hours"] = check_result.get("staleness_hours")
            break
        except Exception:
            continue

    if oracle_price is None:
        return result

    # Depeg thresholds from policy
    minor_threshold = Decimal(str(policy_cfg.get("depeg_threshold_minor_pct", 0.5)))
    material_threshold = Decimal(str(policy_cfg.get("depeg_threshold_material_pct", 2.0)))
    deviation = abs(oracle_price - Decimal("1")) * Decimal("100")

    if deviation > material_threshold:
        result["price_usd"] = oracle_price
        result["price_source"] = "oracle (de-peg override)"
        result["depeg_flag"] = f"material_{deviation:.2f}%"
        result["notes"] = f"Material de-peg detected: {deviation:.2f}% deviation. Priced at oracle value per Section 9.4."
    elif deviation > minor_threshold:
        result["price_usd"] = oracle_price
        result["price_source"] = "oracle (de-peg override)"
        result["depeg_flag"] = f"minor_{deviation:.2f}%"
        result["notes"] = f"Minor de-peg detected: {deviation:.2f}% deviation. Priced at oracle value per Section 9.4."
    # else: within tolerance, keep par

    return result


# --- Individual price adapters (unchanged) ---

def chainlink_price(feed_address: str, w3: Web3, expected_freq_hours: float = None) -> dict:
    """Query a Chainlink AggregatorV3 feed.

    Returns price as Decimal with metadata.
    If expected_freq_hours is provided, checks staleness (>2x expected = stale).
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

    # Calculate staleness
    age_seconds = (datetime.now(timezone.utc) - updated_utc).total_seconds()
    age_hours = age_seconds / 3600

    stale_flag = ""
    if expected_freq_hours and age_hours > 2 * expected_freq_hours:
        stale_flag = (
            f"STALE ({age_hours:.0f}h old, expected update every "
            f"{expected_freq_hours}h, threshold {2 * expected_freq_hours}h)"
        )

    return {
        "price_usd": price,
        "price_source": "chainlink",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": updated_utc.strftime(TS_FMT),
        "staleness_hours": round(age_hours, 1),
        "stale_flag": stale_flag,
        "notes": "",
    }


def pyth_price(feed_id: str, expected_freq_hours: float = None) -> dict:
    """Query Pyth Hermes REST API for a price feed.

    If expected_freq_hours is provided, checks staleness (>2x expected = stale).
    """
    url = f"https://hermes.pyth.network/v2/updates/price/latest"
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
        "staleness_hours": None,
        "stale_flag": "",
        "notes": "",
    }


def redstone_price(symbol: str) -> dict:
    """Query Redstone Finance REST API for a price feed.

    Free, no API key needed. Tier 3 in A2 hierarchy (after Chainlink, Pyth).
    Used as fallback for stablecoins and governance tokens.
    """
    url = "https://api.redstone.finance/prices"
    resp = requests.get(url, params={"symbols": symbol, "provider": "redstone"}, timeout=10)
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


# --- A1 exchange rate pricing ---

def _curve_lp_price(token_entry: dict, w3_eth: Web3 | None) -> dict:
    """Category C: Curve LP token priced via get_virtual_price().

    For stablecoin pools, virtual_price * $1 gives a good approximation.
    """
    pricing = token_entry["pricing"]
    symbol = token_entry["symbol"]
    pool_addr = pricing.get("pool_address")

    if not pool_addr or not w3_eth:
        return _unavailable(symbol)

    try:
        abi = [{"inputs": [], "name": "get_virtual_price",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view", "type": "function"}]
        pool = w3_eth.eth.contract(
            address=Web3.to_checksum_address(pool_addr), abi=abi)
        vp = pool.functions.get_virtual_price().call()
        price = Decimal(str(vp)) / Decimal(10**18)
        return {
            "price_usd": price,
            "price_source": "curve_virtual_price",
            "depeg_flag": "none",
            "depeg_deviation_pct": None,
            "oracle_updated_at": None,
            "staleness_hours": None,
            "stale_flag": "",
            "notes": f"Curve virtual price: {price:.6f}",
        }
    except Exception as e:
        result = _unavailable(symbol)
        result["notes"] = f"Curve virtual price failed: {e}"
        return result


def _a1_exchange_rate_price(token_entry: dict) -> dict:
    """Category A1: query on-chain exchange rate, then price underlying.

    Supports:
    - eUSX (Solana): eUSX/USX rate from vault, then USX price from Pyth
    - sUSDe (Ethereum): convertToAssets on ERC-4626, underlying USDe at par
    - Other ERC-4626 vaults with coingecko fallback via feeds
    """
    pricing = token_entry["pricing"]
    symbol = token_entry["symbol"]
    underlying_feed = pricing.get("underlying_pyth_feed_id")

    # eUSX — Solana-specific exchange rate
    if symbol.lower() == "eusx":
        try:
            exchange_rate = get_eusx_exchange_rate()
            underlying_price = pyth_price(underlying_feed)
            usx_usd = underlying_price["price_usd"]
            price = exchange_rate * usx_usd
            return {
                "price_usd": price,
                "price_source": f"a1_exchange_rate (rate={exchange_rate:.6f}) x pyth",
                "depeg_flag": "none",
                "depeg_deviation_pct": None,
                "oracle_updated_at": underlying_price.get("oracle_updated_at"),
                "staleness_hours": underlying_price.get("staleness_hours"),
                "stale_flag": underlying_price.get("stale_flag", ""),
                "notes": f"eUSX/USX rate: {exchange_rate:.6f}, USX/USD: {usx_usd}",
            }
        except Exception as e:
            pass  # fall through to CoinGecko

    # sUSDe — ERC-4626 on Ethereum, convertToAssets
    if symbol.lower() == "susde":
        try:
            from evm import get_web3
            w3 = get_web3("ethereum")
            contract_addr = pricing.get("exchange_rate_contract", "0x9d39a5de30e57443bff2a8307a4256c8797a3497")
            abi = [{"inputs": [{"name": "shares", "type": "uint256"}], "name": "convertToAssets",
                    "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
            vault = w3.eth.contract(address=Web3.to_checksum_address(contract_addr), abi=abi)
            # Exchange rate: assets per 1e18 shares
            assets = vault.functions.convertToAssets(10**18).call()
            exchange_rate = Decimal(str(assets)) / Decimal(10**18)
            # USDe at par (~$1)
            price = exchange_rate
            return {
                "price_usd": price,
                "price_source": f"a1_convertToAssets (rate={exchange_rate:.6f})",
                "depeg_flag": "none",
                "depeg_deviation_pct": None,
                "oracle_updated_at": None,
                "staleness_hours": None,
                "stale_flag": "",
                "notes": f"sUSDe/USDe rate: {exchange_rate:.6f}, USDe at par",
            }
        except Exception as e:
            pass  # fall through to CoinGecko

    # Fallback: CoinGecko via feeds registry
    feeds = pricing.get("feeds", {})
    if isinstance(feeds, dict):
        cg_key = feeds.get("coingecko")
        if cg_key:
            feed_cfg = _load_feeds_registry().get(cg_key)
            if feed_cfg:
                try:
                    return coingecko_price(feed_cfg["coin_id"])
                except Exception:
                    pass

    result = _unavailable(symbol)
    result["notes"] = f"A1 exchange rate: no handler for {symbol}"
    return result


# --- Internal helpers ---

def _unavailable(symbol: str) -> dict:
    """Return a result indicating price is unavailable."""
    return {
        "price_usd": Decimal("0"),
        "price_source": "unavailable",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": None,
        "staleness_hours": None,
        "stale_flag": "",
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
    feeds_registry = _load_feeds_registry()
    cg_map = {}  # coingecko coin_id -> symbol
    for symbol, entry in tokens.items():
        feeds = entry.get("pricing", {}).get("feeds", {})
        if not isinstance(feeds, dict):
            continue
        cg_key = feeds.get("coingecko")
        if cg_key:
            feed_cfg = feeds_registry.get(cg_key, {})
            cg_id = feed_cfg.get("coin_id")
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
                "staleness_hours": None,
                "stale_flag": "",
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
    1. Batch all CoinGecko-only tokens into one API call
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

    # Step 1: Identify CoinGecko-only tokens (tokens whose only feed is coingecko)
    # and batch them in one call
    cg_tokens = {}
    non_cg_tokens = {}
    for symbol, entry in unique_tokens.items():
        feeds = entry.get("pricing", {}).get("feeds", {})
        if not isinstance(feeds, dict):
            feeds = {}
        # Tokens whose primary source is coingecko (no higher-priority feeds)
        if "coingecko" in feeds and "kraken" not in feeds and "chainlink" not in feeds and "pyth" not in feeds:
            cg_tokens[symbol] = entry
        else:
            non_cg_tokens[symbol] = entry

    # Batch CoinGecko
    if cg_tokens:
        cg_results = _batch_coingecko(cg_tokens)
        results.update(cg_results)
        # Pre-populate cache so get_price() won't re-fetch
        for symbol, result in cg_results.items():
            _price_cache[_cache_key(cg_tokens[symbol])] = result

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
