"""
Output writers for the Veris NAV collection system.

Writes position snapshots, detail CSVs, and summary JSON
per the output schema in plans/output_schema_plan.md.
"""

import csv
import json
import os
from datetime import datetime
from decimal import Decimal


# Increment when the output format changes so downstream consumers can detect.
SCHEMA_VERSION = "1.2"


def sanitize_label(text):
    """Clean position labels: replace non-ASCII, strip developer notes."""
    if not text:
        return ""
    # Replace em dash and other unicode dashes with regular dash
    text = text.replace("\u2014", "-").replace("\u2013", "-").replace("\u2012", "-")
    # Strip any remaining non-ASCII
    text = text.encode("ascii", "replace").decode("ascii").replace("?", "")
    # Clean up double spaces
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


# --- Display name formatting for output ---

_CHAIN_DISPLAY = {
    "ethereum": "Ethereum",
    "arbitrum": "Arbitrum",
    "base": "Base",
    "avalanche": "Avalanche",
    "plasma": "Plasma",
    "hyperevm": "HyperEVM",
    "katana": "Katana",
    "solana": "Solana",
}

_PROTOCOL_DISPLAY = {
    "aave": "Aave",
    "credit_coop": "Credit Coop",
    "ethena": "Ethena.fi",
    "euler": "Euler",
    "exponent": "Exponent Finance",
    "kamino": "Kamino",
    "midas": "Midas",
    "morpho": "Morpho (Markets)",
    "uniswap_v4": "Uniswap V4",
    "curve": "Curve",
}


def _format_chain(chain):
    """Format chain name for display output."""
    return _CHAIN_DISPLAY.get(chain, chain.capitalize() if chain else "")


def _format_protocol(protocol, position_label=""):
    """Format protocol name for display output.

    Uses position_label for context-dependent formatting (e.g., Gauntlet vs Pareto).
    """
    if not protocol:
        return "Wallet Balance"

    # Morpho vaults (various section keys like morpho_vaults, morpho_vaults_0xec0b)
    if protocol.startswith("morpho_vaults"):
        return "Morpho (Vaults)"

    # Gauntlet/Pareto — distinguished by position label
    if protocol == "gauntlet_pareto":
        if "Direct" in position_label or "AA_FalconXUSDC" in position_label:
            return "Pareto"
        return "Gauntlet Vaults"

    # Wallet balances
    if protocol == "wallet":
        return "Wallet Balance"

    # ARMA proxy balances
    if protocol == "arma":
        return "ARMA"

    # Yearn
    if protocol == "yearn":
        return "yearn.fi"

    # Avantis
    if protocol == "avantis":
        return "Avantis"

    # PT lots
    if protocol == "pt_lots":
        return "PT Lots"

    # Standard lookup
    if protocol in _PROTOCOL_DISPLAY:
        return _PROTOCOL_DISPLAY[protocol]

    # Fallback: capitalize and replace underscores
    return protocol.replace("_", " ").title()


def _resolve_underlying(pos):
    """Resolve the underlying token for a position.

    Priority: explicit underlying_symbol > token_category lookup > token is its own underlying.
    """
    # Handler already set it
    explicit = pos.get("underlying_symbol", "")
    if explicit:
        return explicit

    pos_type = pos.get("position_type", "")
    token_sym = pos.get("token_symbol", "")

    # Wallet balances, LP constituents, collateral/debt tokens: the token IS the underlying
    if pos_type in ("token_balance", "lp_constituent", "collateral", "debt"):
        return token_sym

    # A2 oracle-priced (Midas tokens etc.): the token is the product, not the underlying
    # A3 manual accrual: specific to FalconX, underlying is complex
    # These intentionally return empty — the underlying is embedded in the product
    return ""


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


# Common columns for positions.csv
POSITION_COLUMNS = [
    "position_id", "chain", "protocol", "wallet", "position_label",
    "category", "position_type", "token_symbol", "underlying", "token_contract",
    "balance_human", "price_usd", "price_source", "value_usd",
    "block_number", "block_timestamp_utc",
    "staleness_hours", "stale_flag",
    "depeg_flag", "depeg_deviation_pct",
    "notes", "run_timestamp_cet",
]

LEVERAGE_COLUMNS = [
    "parent_position_id", "protocol", "market_id", "wallet", "chain",
    "side", "token_symbol", "token_category", "balance_human",
    "price_usd", "price_source", "value_usd",
]

PT_LOT_COLUMNS = [
    "pt_symbol", "lot_index", "purchase_date", "lot_type",
    "pt_quantity", "underlying_paid", "implied_rate", "apy",
    "maturity_date", "total_days", "days_elapsed",
    "yield_to_date", "value_underlying", "value_usd",
]

LP_COLUMNS = [
    "parent_position_id", "lp_name", "chain", "protocol",
    "constituent_type", "token_symbol", "token_category",
    "balance_human", "price_usd", "price_source", "value_usd",
    "pt_price_ratio", "lp_share",
]

VERIFICATION_COLUMNS = [
    "token_symbol", "chain", "category",
    "primary_price_usd", "verified_price_usd",
    "divergence_pct", "threshold_pct", "divergence_flag",
    "source", "total_nav_usd", "total_supply",
    "attestation_hash", "verification_timestamp",
]


def make_position_id(pos):
    """Generate a unique position ID from position dict."""
    chain = pos.get("chain", "")
    protocol = pos.get("protocol", "")
    wallet = pos.get("wallet", "")[:8]
    token = pos.get("token_symbol", "")
    category = pos.get("category", "")
    pos_type = pos.get("position_type", "")
    return f"{chain}_{protocol}_{wallet}_{token}_{category}_{pos_type}"


def write_positions(positions, output_dir, run_ts_cet, file_suffix=""):
    """Write positions.json and positions.csv."""
    os.makedirs(output_dir, exist_ok=True)

    # Build output rows
    rows = []
    for pos in positions:
        if pos.get("status") == "CLOSED":
            continue
        if pos.get("position_type") == "lp_parent":
            continue

        row = {
            "position_id": make_position_id(pos),
            "chain": _format_chain(pos.get("chain", "")),
            "protocol": _format_protocol(pos.get("protocol", ""), pos.get("position_label", "")),
            "wallet": pos.get("wallet", ""),
            "position_label": sanitize_label(pos.get("position_label", "")),
            "category": pos.get("category", ""),
            "position_type": pos.get("position_type", ""),
            "token_symbol": pos.get("token_symbol", ""),
            "underlying": _resolve_underlying(pos),
            "token_contract": pos.get("token_contract", ""),
            "balance_human": str(pos.get("balance_human", "")),
            "price_usd": str(pos.get("price_usd", "")),
            "price_source": pos.get("price_source", ""),
            "value_usd": str(pos.get("value_usd", "")),
            "block_number": str(pos.get("block_number", "")),
            "block_timestamp_utc": pos.get("block_timestamp_utc", ""),
            "staleness_hours": str(pos.get("staleness_hours", "")),
            "stale_flag": pos.get("stale_flag", ""),
            "depeg_flag": pos.get("depeg_flag", ""),
            "depeg_deviation_pct": str(pos.get("depeg_deviation_pct", "")),
            "notes": pos.get("notes", ""),
            "run_timestamp_cet": run_ts_cet,
        }
        rows.append(row)

    # CSV
    csv_path = os.path.join(output_dir, f"positions{file_suffix}.csv")
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=POSITION_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    # JSON
    json_path = os.path.join(output_dir, f"positions{file_suffix}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "_schema_version": SCHEMA_VERSION,
            "_methodology": {
                "description": "Veris Capital AMC position snapshot",
                "scope": "All protocol positions + wallet token balances",
                "run_timestamp_cet": run_ts_cet,
            },
            "positions": rows,
        }, f, indent=2, cls=DecimalEncoder)

    return csv_path, json_path


def write_leverage_detail(positions, output_dir, file_suffix=""):
    """Write leverage_detail.csv for Category D positions."""
    d_positions = [p for p in positions if p.get("category") == "D"
                   and p.get("status") != "CLOSED"]
    if not d_positions:
        return None

    csv_path = os.path.join(output_dir, f"leverage_detail{file_suffix}.csv")
    rows = []
    for pos in d_positions:
        rows.append({
            "parent_position_id": make_position_id(pos),
            "protocol": _format_protocol(pos.get("protocol", ""), pos.get("position_label", "")),
            "market_id": pos.get("leverage_market_id", ""),
            "wallet": pos.get("wallet", ""),
            "chain": _format_chain(pos.get("chain", "")),
            "side": pos.get("position_type", ""),
            "token_symbol": pos.get("token_symbol", ""),
            "token_category": pos.get("token_category", pos.get("category", "")),
            "balance_human": str(pos.get("balance_human", "")),
            "price_usd": str(pos.get("price_usd", "")),
            "price_source": pos.get("price_source", ""),
            "value_usd": str(pos.get("value_usd", "")),
        })

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEVERAGE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return csv_path


def write_pt_lots(positions, output_dir, file_suffix=""):
    """Write pt_lots.csv with per-lot detail from Category B positions."""
    csv_path = os.path.join(output_dir, f"pt_lots{file_suffix}.csv")
    rows = []

    for pos in positions:
        if pos.get("position_type") != "pt_lot_aggregate":
            continue
        lots = pos.get("_pt_lot_detail", [])
        pt_sym = pos.get("token_symbol", "")
        maturity = pos.get("maturity", "")

        for i, lot in enumerate(lots):
            rows.append({
                "pt_symbol": pt_sym,
                "lot_index": i + 1,
                "purchase_date": str(lot.get("purchase_date", "")),
                "lot_type": lot.get("lot_type", ""),
                "pt_quantity": str(lot.get("pt_quantity", "")),
                "underlying_paid": str(lot.get("underlying_paid", "")),
                "implied_rate": str(lot.get("implied_rate", "")),
                "apy": str(lot.get("apy", "")),
                "maturity_date": maturity,
                "total_days": str(lot.get("total_days", "")),
                "days_elapsed": str(lot.get("days_elapsed", "")),
                "yield_to_date": str(lot.get("yield_to_date", "")),
                "value_underlying": str(lot.get("value_underlying", "")),
                "value_usd": str(lot.get("value_usd", "")),
            })

    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=PT_LOT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        return csv_path
    return None


def write_lp_decomposition(positions, output_dir, file_suffix=""):
    """Write lp_decomposition.csv for Category C LP constituents."""
    c_positions = [p for p in positions if p.get("category") == "C"]
    if not c_positions:
        return None

    csv_path = os.path.join(output_dir, f"lp_decomposition{file_suffix}.csv")
    rows = []
    for pos in c_positions:
        rows.append({
            "parent_position_id": make_position_id(pos),
            "lp_name": pos.get("position_label", ""),
            "chain": _format_chain(pos.get("chain", "")),
            "protocol": _format_protocol(pos.get("protocol", ""), pos.get("position_label", "")),
            "constituent_type": pos.get("lp_constituent_type", ""),
            "token_symbol": pos.get("token_symbol", ""),
            "token_category": pos.get("token_category", ""),
            "balance_human": str(pos.get("balance_human", "")),
            "price_usd": str(pos.get("price_usd", "")),
            "price_source": pos.get("price_source", ""),
            "value_usd": str(pos.get("value_usd", "")),
            "pt_price_ratio": str(pos.get("pt_price_ratio", "")),
            "lp_share": str(pos.get("lp_share", "")),
        })

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LP_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return csv_path


def write_verification(verification_results, output_dir, file_suffix=""):
    """Write verification.csv with asset-level verification results (Section 7.3)."""
    if not verification_results:
        return None

    csv_path = os.path.join(output_dir, f"verification{file_suffix}.csv")
    rows = []

    for v in verification_results:
        details = v.get("details", {})
        rows.append({
            "token_symbol": v.get("token_symbol", ""),
            "chain": _format_chain(v.get("chain", "")),
            "category": v.get("category", ""),
            "primary_price_usd": str(v.get("primary_price_usd", "")),
            "verified_price_usd": str(v.get("verified_price_usd", "")),
            "divergence_pct": str(v.get("divergence_pct", "")),
            "threshold_pct": str(v.get("threshold_pct", "")),
            "divergence_flag": v.get("divergence_flag", v.get("error", "")),
            "source": v.get("source", ""),
            "total_nav_usd": details.get("total_nav_usd", ""),
            "total_supply": details.get("total_supply", ""),
            "attestation_hash": details.get("attestation_hash", ""),
            "verification_timestamp": v.get("verification_timestamp", ""),
        })

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=VERIFICATION_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return csv_path


def write_nav_summary(positions, output_dir, run_ts_cet, file_suffix="",
                      valuation_blocks=None, chain_health=None,
                      verification_results=None):
    """Write nav_summary.json with aggregations by category and wallet.

    Args:
        positions: List of position dicts.
        output_dir: Output directory path.
        run_ts_cet: Run timestamp in CET.
        valuation_blocks: Optional dict of chain -> block info for methodology log.
        chain_health: Optional dict of chain -> {balances, positions, errors}.
    """
    by_category = {}
    by_wallet = {}
    total_positive = Decimal(0)
    total_negative = Decimal(0)

    for pos in positions:
        if pos.get("status") == "CLOSED":
            continue

        value = pos.get("value_usd", Decimal(0))
        if not isinstance(value, Decimal):
            try:
                value = Decimal(str(value))
            except Exception:
                value = Decimal(0)

        category = pos.get("category", "unknown")
        wallet = pos.get("wallet", "unknown")

        # By category
        if category not in by_category:
            by_category[category] = {"count": 0, "gross_value": Decimal(0)}
        by_category[category]["count"] += 1
        by_category[category]["gross_value"] += value

        # By wallet
        wallet_short = wallet[:8] + "..." if len(wallet) > 8 else wallet
        if wallet_short not in by_wallet:
            by_wallet[wallet_short] = {"count": 0, "gross_value": Decimal(0)}
        by_wallet[wallet_short]["count"] += 1
        by_wallet[wallet_short]["gross_value"] += value

        if value >= 0:
            total_positive += value
        else:
            total_negative += value

    summary = {
        "_schema_version": SCHEMA_VERSION,
        "run_timestamp_cet": run_ts_cet,
        "total_positions": len([p for p in positions if p.get("status") != "CLOSED"]),
        "total_assets_usd": str(total_positive),
        "total_liabilities_usd": str(total_negative),
        "net_assets_usd": str(total_positive + total_negative),
        "by_category": {
            k: {"count": v["count"], "gross_value": str(v["gross_value"])}
            for k, v in sorted(by_category.items())
        },
        "by_wallet": {
            k: {"count": v["count"], "gross_value": str(v["gross_value"])}
            for k, v in sorted(by_wallet.items())
        },
    }

    # Methodology: Valuation Block pinning (Step 1 of NAV Methodology Log)
    if valuation_blocks:
        summary["valuation_blocks"] = valuation_blocks
        summary["valuation_block_note"] = (
            "All on-chain balance and position queries were made at the Valuation Block "
            "shown above for each chain (closest to but not exceeding 16:00 CET/CEST on the "
            "Valuation Date, per Valuation Policy Section 12.1). "
            "Pricing data (oracles, CoinGecko, Kraken) was sourced at run time. "
            "For same-day NAV runs this is immaterial; for retrospective runs, "
            "pricing may not match the Valuation Block exactly."
        )
    else:
        summary["valuation_block_note"] = (
            "No --date flag was specified. All queries were made at the latest block "
            "at run time. For official NAV calculation, re-run with --date YYYY-MM-DD "
            "to pin all queries to the Valuation Block (16:00 CET/CEST)."
        )

    # Verification results (Section 7.3)
    if verification_results:
        verification_summary = []
        for v in verification_results:
            entry = {
                "token_symbol": v.get("token_symbol", ""),
                "chain": _format_chain(v.get("chain", "")),
                "category": v.get("category", ""),
                "source": v.get("source", ""),
                "primary_price_usd": str(v.get("primary_price_usd", "")),
                "verified_price_usd": str(v.get("verified_price_usd", "")),
                "divergence_pct": str(v.get("divergence_pct", "")),
                "threshold_pct": str(v.get("threshold_pct", "")),
                "divergence_flag": v.get("divergence_flag", ""),
            }
            if v.get("error"):
                entry["error"] = v["error"]
            verification_summary.append(entry)
        summary["verification"] = verification_summary

    # Chain health report
    if chain_health:
        health_summary = {}
        for chain, health in sorted(chain_health.items()):
            entry = {
                "balances": health["balances"],
                "positions": health["positions"],
                "status": "ERROR" if health["errors"] else "OK",
            }
            if health["errors"]:
                entry["errors"] = health["errors"]
            health_summary[chain] = entry
        summary["chain_health"] = health_summary

    json_path = os.path.join(output_dir, f"nav_summary{file_suffix}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, cls=DecimalEncoder)

    return json_path
