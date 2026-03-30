"""
Superstate NAV API verifier.

Cross-checks USCC oracle prices against Superstate's published daily NAV
via their REST API.

Flow:
  1. Query GET /v1/funds/{fund_id}/nav-daily for the latest NAV entry
  2. Extract net_asset_value (NAV per share)
  3. Compare against primary oracle price -> divergence %
  4. Flag if NAV date is stale relative to today

API docs: https://api.superstate.com/swagger-ui/

Per Valuation Policy Section 7.3 (Asset-level verification).
"""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

import requests

from evm import TS_FMT

logger = logging.getLogger(__name__)

_API_TIMEOUT = 15


def verify(config: dict, primary_price: Decimal, api_base: str) -> dict:
    """Verify a Superstate fund token price against the issuer's NAV API.

    Args:
        config: Verification entry from verification.json with:
            - fund_id: Superstate fund numeric ID (e.g. 2 for USCC)
            - max_nav_age_days: flag if latest NAV is older than this
        primary_price: The primary oracle price to verify against.
        api_base: Superstate API base URL (from _api_endpoints.superstate).

    Returns:
        Verification result dict.
    """
    fund_id = config["fund_id"]
    max_age_days = config.get("max_nav_age_days", 3)

    # Query latest NAV — use a 7-day window ending today
    today = date.today()
    start = today.replace(day=max(1, today.day - 7))
    url = f"{api_base}/v1/funds/{fund_id}/nav-daily"
    params = {
        "start_date": start.isoformat(),
        "end_date": today.isoformat(),
    }

    logger.info("Superstate API: GET %s %s", url, params)
    resp = requests.get(url, params=params, timeout=_API_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    if not data:
        raise ValueError(
            f"No NAV data returned from Superstate API for fund {fund_id} "
            f"between {start} and {today}"
        )

    # Latest entry is first (sorted by date descending by API)
    latest = data[0]
    nav_per_share = Decimal(latest["net_asset_value"])
    nav_date_str = latest["net_asset_value_date"]  # "MM/DD/YYYY"
    nav_date = datetime.strptime(nav_date_str, "%m/%d/%Y").date()
    aum = Decimal(latest.get("assets_under_management", "0"))
    outstanding = Decimal(latest.get("outstanding_shares", "0"))

    logger.info(
        "Superstate NAV: fund=%d date=%s nav=$%s aum=$%s shares=%s",
        fund_id, nav_date, nav_per_share, aum, outstanding,
    )

    # Divergence vs primary oracle price
    if primary_price > 0:
        divergence_pct = (
            (nav_per_share - primary_price) / primary_price
        ) * Decimal(100)
    else:
        divergence_pct = Decimal(0)

    # Staleness check
    nav_age_days = (today - nav_date).days
    stale_flag = ""
    if nav_age_days > max_age_days:
        stale_flag = (
            f"STALE_NAV: latest NAV date {nav_date} is {nav_age_days} days old "
            f"(max {max_age_days} days)"
        )

    now_utc = datetime.now(timezone.utc).strftime(TS_FMT)

    return {
        "source": "superstate_nav_api",
        "verified_price_usd": nav_per_share,
        "divergence_pct": divergence_pct,
        "divergence_flag": "",  # set by dispatcher based on category threshold
        "verification_timestamp": now_utc,
        "stale_flag": stale_flag,
        "details": {
            "fund_id": fund_id,
            "nav_date": str(nav_date),
            "nav_per_share": str(nav_per_share),
            "assets_under_management": str(aum),
            "outstanding_shares": str(outstanding),
            "nav_age_days": nav_age_days,
            "api_url": url,
        },
    }
