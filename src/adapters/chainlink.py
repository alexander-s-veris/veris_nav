"""Chainlink AggregatorV3 price adapter."""

import logging
from decimal import Decimal
from datetime import datetime, timezone

from web3 import Web3

from evm import AGGREGATOR_V3_ABI, TS_FMT

logger = logging.getLogger(__name__)


def chainlink_price(feed_address: str, w3: Web3, expected_freq_hours: float = None,
                    block_identifier: int = None) -> dict:
    """Query a Chainlink AggregatorV3 feed.

    Returns price as Decimal with metadata.
    If block_identifier is provided, queries at that block (historical pricing).
    If expected_freq_hours is provided, checks staleness (>2x expected = stale).
    """
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(feed_address),
        abi=AGGREGATOR_V3_ABI,
    )

    call_kwargs = {"block_identifier": block_identifier} if block_identifier else {}
    decimals = contract.functions.decimals().call(**call_kwargs)
    _round_id, answer, _started_at, updated_at, _answered_in_round = (
        contract.functions.latestRoundData().call(**call_kwargs)
    )

    price = Decimal(answer) / Decimal(10**decimals)
    updated_utc = datetime.fromtimestamp(updated_at, tz=timezone.utc)

    logger.info("chainlink.latestRoundData(%s) → price=%s, updated=%s, decimals=%d",
                 feed_address, price, updated_utc.strftime(TS_FMT), decimals)

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


def chainlink_prices_batch(
    feeds: list[dict],
    w3: Web3,
    chain: str,
) -> dict[str, dict]:
    """Batch-query multiple Chainlink feeds via Multicall3.

    Each feed needs 2 calls (decimals + latestRoundData), so N feeds
    become 1 multicall with 2N sub-calls instead of 2N individual RPCs.

    Args:
        feeds: List of feed config dicts with 'address' and optional 'expected_freq_hours'.
               Each must also have a 'key' field for cache lookup.
        w3: Web3 instance for the chain.
        chain: Chain name.

    Returns:
        {feed_key: price_result_dict} for successfully queried feeds.
    """
    from multicall import (
        multicall, encode_chainlink_decimals,
        encode_chainlink_latest_round_data, decode_uint256,
        decode_chainlink_latest_round_data,
    )

    if not feeds:
        return {}

    # Build 2 calls per feed: decimals() + latestRoundData()
    calls = []
    for feed in feeds:
        addr = feed["address"]
        calls.append((addr, encode_chainlink_decimals()))
        calls.append((addr, encode_chainlink_latest_round_data()))

    results = multicall(w3, chain, calls)

    price_results = {}
    for i, feed in enumerate(feeds):
        dec_success, dec_data = results[i * 2]
        lrd_success, lrd_data = results[i * 2 + 1]

        feed_key = feed["key"]

        if not dec_success or not lrd_success:
            # Fallback to individual call for this feed
            try:
                price_results[feed_key] = chainlink_price(
                    feed["address"], w3, feed.get("expected_freq_hours"))
            except Exception:
                pass
            continue

        try:
            decimals = decode_uint256(dec_data)
            _round_id, answer, _started_at, updated_at, _answered_in_round = (
                decode_chainlink_latest_round_data(lrd_data))

            price = Decimal(answer) / Decimal(10 ** decimals)
            updated_utc = datetime.fromtimestamp(updated_at, tz=timezone.utc)

            logger.info("chainlink.batch(%s) → price=%s, updated=%s",
                         feed["address"][:10], price, updated_utc.strftime(TS_FMT))

            age_hours = (datetime.now(timezone.utc) - updated_utc).total_seconds() / 3600
            expected = feed.get("expected_freq_hours")
            stale_flag = ""
            if expected and age_hours > 2 * expected:
                stale_flag = (
                    f"STALE ({age_hours:.0f}h old, expected every "
                    f"{expected}h, threshold {2 * expected}h)")

            price_results[feed_key] = {
                "price_usd": price,
                "price_source": "chainlink",
                "depeg_flag": "none",
                "depeg_deviation_pct": None,
                "oracle_updated_at": updated_utc.strftime(TS_FMT),
                "staleness_hours": round(age_hours, 1),
                "stale_flag": stale_flag,
                "notes": "",
            }
        except Exception as e:
            logger.warning("chainlink.batch decode failed for %s: %s", feed["address"], e)

    return price_results
