"""
Price dispatcher for the Veris NAV data collection system.

Routes pricing requests through a config-driven hierarchy:
  - config/price_feeds.json    — feed definitions
  - config/pricing_policy.json — hierarchy rules per category
  - config/tokens.json         — tokens reference feeds by key

Adapter implementations live in src/adapters/ (one file per provider).
"""

import os
import json
from decimal import Decimal

from web3 import Web3

from block_utils import concurrent_query

# Import all adapters
from adapters import (
    chainlink_price, pyth_price, redstone_price,
    kraken_price, coingecko_price, batch_coingecko_prices,
    dex_twap_price, a1_exchange_rate_price, curve_lp_price,
)

# --- Price cache ---
_price_cache: dict[str, dict] = {}

# --- Config loaders (cached) ---

_FEEDS_CACHE = None
_POLICY_CACHE = None


def _load_feeds_registry() -> dict:
    """Load and flatten config/price_feeds.json."""
    global _FEEDS_CACHE
    if _FEEDS_CACHE is None:
        path = os.path.join(os.path.dirname(__file__), "..", "config", "price_feeds.json")
        with open(path) as f:
            raw = json.load(f)
        flat = {}
        for section_key, section_val in raw.items():
            if section_key.startswith("_"):
                continue
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
    """Generate a unique cache key for a token's pricing config."""
    symbol = token_entry.get("symbol", "UNKNOWN")
    pricing = token_entry.get("pricing", {}) if isinstance(token_entry.get("pricing"), dict) else {}
    policy = pricing.get("policy", "")
    feeds = pricing.get("feeds", {})
    first_feed = next(iter(feeds.values()), "") if feeds else ""
    return f"{symbol}_{policy}_{first_feed}"


# --- Generic feed query dispatcher ---

def _get_w3_for_chain(feed_cfg: dict, w3_eth: Web3 | None) -> Web3:
    """Resolve the Web3 instance for a feed's chain."""
    chain = feed_cfg.get("chain", "ethereum")
    if chain != "ethereum":
        from evm import get_web3
        w3 = get_web3(chain)
    else:
        w3 = w3_eth
    if not w3:
        raise ConnectionError(f"No Web3 for chain {chain}")
    return w3


def _query_feed(feed_cfg: dict, w3_eth: Web3 | None = None, expected_freq_hours: float = None) -> dict:
    """Query a single price feed based on its type. Returns result dict."""
    feed_type = feed_cfg["type"]
    if feed_type == "chainlink":
        return chainlink_price(feed_cfg["address"], _get_w3_for_chain(feed_cfg, w3_eth), expected_freq_hours)
    elif feed_type == "pyth":
        return pyth_price(feed_cfg["feed_id"], expected_freq_hours)
    elif feed_type == "redstone":
        return redstone_price(feed_cfg["symbol"])
    elif feed_type == "kraken":
        return kraken_price(feed_cfg["pair"])
    elif feed_type == "coingecko":
        return coingecko_price(feed_cfg["coin_id"])
    elif feed_type == "dex_twap":
        return dex_twap_price(feed_cfg, _get_w3_for_chain(feed_cfg, w3_eth))
    else:
        raise ValueError(f"Unknown feed type: {feed_type}")


# --- Main dispatcher ---

def get_price(token_entry: dict, w3_eth: Web3 | None = None) -> dict:
    """Main dispatcher. Routes to hierarchy walker or special method."""
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
        result = a1_exchange_rate_price(token_entry, w3_eth)
    elif method == "curve_lp":
        result = curve_lp_price(token_entry, w3_eth)
    else:
        result = _unavailable(symbol)

    _price_cache[key] = result
    return result


# --- Generic hierarchy walker ---

def _price_with_hierarchy(symbol, token_feeds, policy_cfg, feeds_registry, w3_eth, expected_freq):
    """Walk the pricing hierarchy, trying each source in order."""
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
            if stale_result is None:
                stale_result = result
        except Exception:
            continue

    if stale_result:
        stale_result["notes"] = f"WARNING: {stale_result.get('stale_flag', 'stale')}. No fresher source in hierarchy."
        return stale_result

    return _unavailable(symbol)


# --- Par pricing with depeg check ---

def par_price(token_entry: dict, w3_eth: Web3 | None = None) -> dict:
    """Category E par pricing. $1.00 with depeg monitoring."""
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

    feeds_registry = _load_feeds_registry()
    policy = _load_pricing_policy()
    policy_key = pricing.get("policy", "E_par")
    policy_cfg = policy.get(policy_key, {})
    depeg_hierarchy = policy_cfg.get("depeg_hierarchy", [])

    if not depeg_hierarchy or not token_feeds:
        return result

    # Walk depeg hierarchy to find oracle price
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

    minor_threshold = Decimal(str(policy_cfg.get("depeg_threshold_minor_pct", 0.5)))
    material_threshold = Decimal(str(policy_cfg.get("depeg_threshold_material_pct", 2.0)))
    deviation = abs(oracle_price - Decimal("1")) * Decimal("100")

    if deviation > material_threshold:
        result["price_usd"] = oracle_price
        result["price_source"] = "oracle (de-peg override)"
        result["depeg_flag"] = f"material_{deviation:.2f}%"
        result["notes"] = f"Material de-peg detected: {deviation:.2f}% deviation. Section 9.4."
    elif deviation > minor_threshold:
        result["price_usd"] = oracle_price
        result["price_source"] = "oracle (de-peg override)"
        result["depeg_flag"] = f"minor_{deviation:.2f}%"
        result["notes"] = f"Minor de-peg detected: {deviation:.2f}% deviation. Section 9.4."

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
    """Batch-fetch CoinGecko prices for multiple tokens in one API call."""
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

    # Use batch adapter
    batch_results = batch_coingecko_prices(list(cg_map.keys()))

    results = {}
    for cg_id, symbol in cg_map.items():
        if cg_id in batch_results:
            results[symbol] = batch_results[cg_id]

    return results


def get_prices_concurrent(
    unique_tokens: dict[str, dict],
    w3_eth: Web3 | None = None,
    max_workers: int = 10,
) -> dict[str, dict]:
    """Price all tokens concurrently with CoinGecko batching."""
    results = {}

    # Step 1: Identify CoinGecko-only tokens and batch them
    cg_tokens = {}
    non_cg_tokens = {}
    for symbol, entry in unique_tokens.items():
        feeds = entry.get("pricing", {}).get("feeds", {})
        if not isinstance(feeds, dict):
            feeds = {}
        if "coingecko" in feeds and "kraken" not in feeds and "chainlink" not in feeds and "pyth" not in feeds:
            cg_tokens[symbol] = entry
        else:
            non_cg_tokens[symbol] = entry

    if cg_tokens:
        cg_results = _batch_coingecko(cg_tokens)
        results.update(cg_results)
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

    # Also add any CoinGecko tokens that failed the batch
    for symbol in cg_tokens:
        if symbol not in results:
            results[symbol] = get_price(cg_tokens[symbol], w3_eth)

    return results
