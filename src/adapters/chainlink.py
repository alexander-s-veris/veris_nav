"""Chainlink AggregatorV3 price adapter."""

from decimal import Decimal
from datetime import datetime, timezone

from web3 import Web3

from evm import AGGREGATOR_V3_ABI, TS_FMT


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
