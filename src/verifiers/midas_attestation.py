"""
Midas Attestation Engine verifier.

Cross-checks Midas token oracle prices against the independently
attested total NAV published via LlamaRisk's verification dashboard.

Flow:
  1. Query LlamaRisk API for the latest attestation (total fund NAV)
  2. Query totalSupply() on the mToken contract on-chain
  3. Compute: verified_price = total_nav / total_supply
  4. Compare against primary oracle price → divergence %

API: GET {api_base}/proof/midas/{proof_id}
Returns: { nav, token, timestamp, attestation_hash, ... }

Per Valuation Policy Section 7.3 (Asset-level verification).
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

import requests
from web3 import Web3

from evm import get_web3, TS_FMT
from handlers import _get_abi

logger = logging.getLogger(__name__)

# LlamaRisk API timeout
_API_TIMEOUT = 15


def _parse_nav_from_snippet(snippet: str) -> tuple[Decimal, str, str]:
    """Parse total NAV, token name, and timestamp from email snippet.

    Snippet format: "Token: mHYPER Date: 3/27/2026 Timestamp: 1774595218
    CEX NAV: 0 Onchain NAV: 51172364.89 Total NAV: 51172364.89 Denomination: USD"
    """
    import re

    nav_match = re.search(r"Total\s+NAV:\s*([\d,.]+)", snippet)
    if not nav_match:
        raise ValueError(f"Cannot parse 'Total NAV' from snippet: {snippet[:200]}")

    nav_str = nav_match.group(1).replace(",", "")
    total_nav = Decimal(nav_str)

    token_match = re.search(r"Token:\s*(\S+)", snippet)
    token_name = token_match.group(1) if token_match else ""

    ts_match = re.search(r"Timestamp:\s*(\d+)", snippet)
    timestamp = ts_match.group(1) if ts_match else ""

    return total_nav, token_name, timestamp


def _fetch_latest_attestation(api_base: str, proof_id: str) -> dict:
    """Fetch the latest attestation data from LlamaRisk API.

    The API returns the proof with its last_attestation, which contains
    the attestation_json. The NAV is extracted from the email snippet
    inside the attestation claims.

    Returns dict with total_nav_usd, attestation_hash, timestamp, etc.
    """
    url = f"{api_base}/proof/midas/{proof_id}"
    logger.info("LlamaRisk API: GET %s", url)

    resp = requests.get(url, timeout=_API_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    last_att = data.get("last_attestation")
    if not last_att:
        raise ValueError(f"No 'last_attestation' in LlamaRisk response for proof {proof_id}")

    attestation_hash = last_att.get("attestation_hash", "")
    att_created = last_att.get("created_at", "")

    # NAV is inside the attestation JSON → claims[0] → data → response → body (Gmail API)
    # The email body contains a "snippet" field with the structured NAV data
    att_json = last_att.get("attestation_json", {})
    claims = att_json.get("claims", [])

    total_nav = None
    token_name = ""
    nav_timestamp = ""

    for claim in claims:
        if claim.get("claimType") != "inline":
            continue
        body_str = claim.get("data", {}).get("response", {}).get("body", "")
        if not body_str:
            continue

        # The body is a Gmail API message JSON; NAV is in the snippet field
        try:
            import json as _json
            email_data = _json.loads(body_str) if isinstance(body_str, str) else body_str
            snippet = email_data.get("snippet", "")
            if "Total NAV" in snippet:
                total_nav, token_name, nav_timestamp = _parse_nav_from_snippet(snippet)
                break
        except Exception as e:
            logger.warning("Failed to parse claim body: %s", e)
            continue

    if total_nav is None:
        raise ValueError(
            f"Could not extract Total NAV from attestation claims for proof {proof_id}")

    # Metadata from attestation JSON
    metadata = att_json.get("metadata", {})
    created_at = metadata.get("createdAt", str(att_created))

    logger.info(
        "LlamaRisk attestation: token=%s, total_nav=$%s, hash=%s..., created=%s",
        token_name, total_nav, attestation_hash[:16], created_at,
    )

    return {
        "total_nav_usd": total_nav,
        "attestation_hash": attestation_hash,
        "attestation_timestamp": nav_timestamp,
        "created_at": created_at,
        "token_name": token_name,
    }


def _query_total_supply_multichain(
    token_addresses: dict[str, str], decimals: int,
) -> tuple[Decimal, list[str]]:
    """Query totalSupply() across multiple chains and sum.

    Multi-chain OFT tokens (like mHYPER) have separate totalSupply per chain.
    The aggregate supply is the sum across all deployment chains.

    Args:
        token_addresses: {chain_name: contract_address} mapping.
        decimals: Token decimals (same on all chains).

    Returns:
        (total_supply, chain_details) where chain_details is a list of
        "chain: supply" strings for logging.
    """
    erc20_abi = _get_abi("erc20")
    total = Decimal(0)
    details = []

    for chain, addr in token_addresses.items():
        try:
            w3 = get_web3(chain)
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(addr), abi=erc20_abi,
            )
            raw = contract.functions.totalSupply().call()
            supply = Decimal(str(raw)) / Decimal(10 ** decimals)
            total += supply
            details.append(f"{chain}: {supply:,.6f}")
            logger.info("totalSupply(%s) on %s → %s", addr[:10], chain, supply)
        except Exception as e:
            details.append(f"{chain}: ERROR ({e})")
            logger.warning("totalSupply failed on %s for %s: %s", chain, addr[:10], e)

    return total, details


def verify(config: dict, primary_price: Decimal, api_base: str) -> dict:
    """Verify a Midas token price against LlamaRisk attestation.

    Args:
        config: Verification entry from verification.json with:
            - proof_id: LlamaRisk proof ID
            - token_addresses: {chain: address} for multi-chain totalSupply
            - token_decimals: token decimals for totalSupply conversion
        primary_price: The primary oracle price (from Chainlink) to verify against.
        api_base: LlamaRisk API base URL.

    Returns:
        Verification result dict.
    """
    proof_id = config["proof_id"]
    token_addresses = config.get("token_addresses", {})
    token_decimals = config.get("token_decimals", 18)

    if not token_addresses:
        raise ValueError("No token_addresses configured for verification")

    # 1. Fetch attestation total NAV
    attestation = _fetch_latest_attestation(api_base, proof_id)
    total_nav = attestation["total_nav_usd"]

    # 2. Query total supply across all deployment chains
    total_supply, supply_details = _query_total_supply_multichain(
        token_addresses, token_decimals)

    if total_supply <= 0:
        raise ValueError(
            f"Aggregate totalSupply is zero across chains: {supply_details}")

    # 3. Compute verified per-token price
    verified_price = total_nav / total_supply

    # 4. Compute divergence
    if primary_price > 0:
        divergence_pct = ((verified_price - primary_price) / primary_price) * Decimal(100)
    else:
        divergence_pct = Decimal(0)

    now_utc = datetime.now(timezone.utc).strftime(TS_FMT)

    return {
        "source": "midas_attestation",
        "verified_price_usd": verified_price,
        "divergence_pct": divergence_pct,
        "divergence_flag": "",  # set by dispatcher based on category threshold
        "verification_timestamp": now_utc,
        "details": {
            "total_nav_usd": str(total_nav),
            "total_supply": str(total_supply),
            "supply_by_chain": "; ".join(supply_details),
            "attestation_hash": attestation.get("attestation_hash", ""),
            "attestation_timestamp": attestation.get("attestation_timestamp", ""),
            "attestation_created_at": attestation.get("created_at", ""),
            "api_url": f"{api_base}/proof/midas/{proof_id}",
        },
    }
