"""
OnRe on-chain NAV verifier.

Cross-checks ONyc oracle price against the issuer's on-chain NAV
computed from the OnRe Offer PDA on Solana.

Flow:
  1. Read Offer PDA via Solana RPC (getAccountInfo)
  2. Find active pricing vector, compute NAV from APR-based step formula
  3. Compare against primary oracle price (Pyth) -> divergence %

Config: solana_protocols.json["onre"]
Per Valuation Policy Section 7.3 (Asset-level verification).
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from evm import TS_FMT
from solana_client import get_onre_nav

logger = logging.getLogger(__name__)


def verify(config: dict, primary_price: Decimal, api_base: str) -> dict:
    """Verify ONyc price against on-chain NAV from OnRe program.

    Args:
        config: Verification entry from verification.json with:
            - max_vector_age_days: flag if active vector is older than this
        primary_price: The primary oracle price (Pyth) to verify against.
        api_base: Unused (no external API — reads from Solana RPC).

    Returns:
        Verification result dict.
    """
    max_age_days = config.get("max_vector_age_days", 30)

    nav = get_onre_nav()
    verified_price = nav["price"]
    active = nav["active_vector"]

    logger.info(
        "OnRe NAV verification: price=%s offer=%s step=%d",
        verified_price, nav["offer_pda"][:12], nav["step"],
    )

    # Divergence vs primary oracle price
    if primary_price > 0:
        divergence_pct = (
            (verified_price - primary_price) / primary_price
        ) * Decimal(100)
    else:
        divergence_pct = Decimal(0)

    # Staleness: check how old the active vector is
    vector_age_seconds = nav["current_time"] - active["start_time"]
    vector_age_days = vector_age_seconds / 86400
    stale_flag = ""
    if vector_age_days > max_age_days:
        stale_flag = (
            f"STALE_VECTOR: active vector set {vector_age_days:.0f} days ago "
            f"(max {max_age_days} days)"
        )

    now_utc = datetime.now(timezone.utc).strftime(TS_FMT)

    return {
        "source": "onre_onchain_nav",
        "verified_price_usd": verified_price,
        "divergence_pct": divergence_pct,
        "divergence_flag": "",  # set by dispatcher based on category threshold
        "verification_timestamp": now_utc,
        "stale_flag": stale_flag,
        "details": {
            "offer_pda": nav["offer_pda"],
            "price_raw": str(nav["price_raw"]),
            "active_vector_start_time": active["start_time"],
            "active_vector_base_price": active["base_price"],
            "active_vector_apr": active["apr"],
            "vector_age_days": round(vector_age_days, 1),
            "step": nav["step"],
        },
    }
