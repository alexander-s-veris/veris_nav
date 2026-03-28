"""
Independent verification framework for the Veris NAV system.

Cross-checks primary oracle prices against independent sources
per Valuation Policy Section 7 (Independent Verification).

Asset-level verifiers compare per-token prices derived from issuer
attestations or NAV reports against the primary oracle price.
Portfolio-level verifiers compare aggregate totals (future).

Config: config/verification.json
"""

import json
import logging
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evm import CONFIG_DIR, get_web3

logger = logging.getLogger(__name__)

# --- Config ---

_VERIFICATION_CFG_CACHE = None


def _load_verification_cfg() -> dict:
    """Load and cache config/verification.json."""
    global _VERIFICATION_CFG_CACHE
    if _VERIFICATION_CFG_CACHE is None:
        path = os.path.join(CONFIG_DIR, "verification.json")
        with open(path) as f:
            _VERIFICATION_CFG_CACHE = json.load(f)
    return _VERIFICATION_CFG_CACHE


def _load_divergence_tolerances() -> dict:
    """Load divergence tolerance thresholds from pricing_policy.json."""
    path = os.path.join(CONFIG_DIR, "pricing_policy.json")
    with open(path) as f:
        policy = json.load(f)
    return policy.get("divergence_tolerances", {})


def _get_api_base(provider: str) -> str:
    """Get API base URL for a verification provider."""
    cfg = _load_verification_cfg()
    endpoints = cfg.get("_api_endpoints", {})
    url = endpoints.get(provider, "")
    if not url:
        raise ValueError(f"No API endpoint configured for verification provider '{provider}'")
    return url.rstrip("/")


# --- Verifier registry ---

# Maps verification type names to (module, function) pairs.
# Each verifier function has the signature:
#   verify(config: dict, primary_price: Decimal, api_base: str) -> dict
#
# Adding a new verification type:
#   1. Create src/verifiers/new_type.py with a verify() function
#   2. Add import + registry entry here
#   3. Add entries in config/verification.json

from verifiers.midas_attestation import verify as _verify_midas

_VERIFIER_REGISTRY = {
    "midas_attestation": {
        "fn": _verify_midas,
        "api_provider": "llamarisk",
    },
}


# --- Dispatcher ---

def run_asset_verifications(positions: list[dict]) -> list[dict]:
    """Run asset-level verifications for all positions that have verification config.

    Matches each position's token_symbol against entries in verification.json
    asset_level section. For each match, calls the appropriate verifier and
    computes divergence against the position's primary price.

    Args:
        positions: List of valued position dicts (must have price_usd set).

    Returns:
        List of verification result dicts, one per verified token.
    """
    cfg = _load_verification_cfg()
    asset_cfg = cfg.get("asset_level", {})
    if not asset_cfg:
        return []

    tolerances = _load_divergence_tolerances()
    results = []

    # Build lookup: token_symbol -> first matching position
    # (verification is per-token, not per-position — one check per unique token)
    verified_symbols = set()

    for pos in positions:
        if pos.get("status") == "CLOSED":
            continue

        symbol = pos.get("token_symbol", "")
        if not symbol or symbol in verified_symbols:
            continue

        entry = asset_cfg.get(symbol)
        if not entry:
            continue

        vtype = entry.get("type", "")
        reg = _VERIFIER_REGISTRY.get(vtype)
        if not reg:
            logger.warning("Unknown verification type '%s' for %s", vtype, symbol)
            continue

        primary_price = pos.get("price_usd", Decimal(0))
        if not primary_price or primary_price <= 0:
            logger.info("Skipping verification for %s — no primary price", symbol)
            continue

        try:
            api_base = _get_api_base(reg["api_provider"])
            result = reg["fn"](entry, primary_price, api_base)

            # Compute divergence flag against category tolerance
            category = pos.get("category", "")
            threshold = Decimal(str(tolerances.get(category, 10.0)))
            divergence = result.get("divergence_pct", Decimal(0))

            if abs(divergence) > threshold:
                result["divergence_flag"] = (
                    f"EXCEEDS_THRESHOLD ({abs(divergence):.2f}% > {threshold}% "
                    f"for category {category})"
                )
            else:
                result["divergence_flag"] = ""

            # Enrich with position context
            result["token_symbol"] = symbol
            result["chain"] = pos.get("chain", "")
            result["category"] = category
            result["primary_price_usd"] = primary_price
            result["threshold_pct"] = threshold

            results.append(result)
            verified_symbols.add(symbol)

            flag = result["divergence_flag"]
            logger.info(
                "Verification %s: primary=%.6f verified=%.6f divergence=%.2f%% %s",
                symbol, primary_price, result.get("verified_price_usd", 0),
                divergence, flag or "OK",
            )

        except Exception as e:
            logger.error("Verification failed for %s (%s): %s", symbol, vtype, e)
            results.append({
                "token_symbol": symbol,
                "chain": pos.get("chain", ""),
                "category": pos.get("category", ""),
                "primary_price_usd": primary_price,
                "source": vtype,
                "error": str(e),
                "divergence_flag": f"VERIFICATION_ERROR: {e}",
            })
            verified_symbols.add(symbol)

    return results
