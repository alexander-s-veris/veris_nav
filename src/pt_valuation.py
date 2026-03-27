"""
PT Token Lot-Based Valuation Module (Category B).

Discovers purchase lots from on-chain transaction history and values them
using linear amortisation (hold-to-maturity). Agnostic — works for any PT
token on Solana (Exponent) given the PT mint, underlying mint, and maturity.

Methodology per Valuation Policy Section 6.4:
  PT value = Purchase_Value + (Gain_to_Maturity × Days_Elapsed / Total_Days)
  where Gain_to_Maturity = PT_Quantity × Underlying_Price_at_Maturity − Purchase_Value
  and Underlying_Price_at_Maturity = 1 (PT redeems 1:1 for underlying at maturity)

Individual lot tracking: each purchase is valued separately with its own
implied rate from the trade.
"""

import json
import os
import sys
from datetime import datetime, timezone, date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(__file__))

from evm import CONFIG_DIR
from solana_client import solana_rpc, get_token_accounts_by_owner


# --- Lot Discovery ---

def discover_pt_lots(
    wallet: str,
    pt_mint: str,
    underlying_mint: str,
    maturity: date,
    lp_lot_tx_groups: list[list[str]] | None = None,
) -> list[dict]:
    """Discover PT token purchase lots from on-chain transaction history.

    Scans all transactions involving the wallet's PT token account, identifies
    AMM swaps (PT in, underlying out), and constructs lots with purchase details.

    LP lots require explicit transaction signatures because the LP deposit
    (underlying out) and LP withdrawal (PT + underlying back) are separate
    transactions that can't be auto-linked. Pass groups of related tx
    signatures via lp_lot_tx_groups.

    Args:
        wallet: Solana wallet address
        pt_mint: PT token mint address
        underlying_mint: Underlying token mint address (e.g. USX)
        maturity: PT maturity date
        lp_lot_tx_groups: List of tx signature groups for LP lots. Each group
            is a list of related tx signatures (deposit, partial returns,
            final withdrawal). The net underlying/PT change across the group
            forms one lot.

    Returns:
        List of lot dicts with: purchase_date, pt_quantity, underlying_paid,
        gain_to_maturity, total_days, implied_rate, tx_signature, lot_type
    """
    # Find the wallet's token account for this PT mint
    pt_accounts = get_token_accounts_by_owner(wallet, pt_mint)
    if not pt_accounts:
        return []

    pt_token_account = pt_accounts[0]["pubkey"]

    # Get all signatures for this token account
    all_sigs = []
    before = None
    while True:
        params = [pt_token_account, {"limit": 1000}]
        if before:
            params[1]["before"] = before
        resp = solana_rpc("getSignaturesForAddress", params)
        sigs = resp["result"]
        if not sigs:
            break
        all_sigs.extend(sigs)
        before = sigs[-1]["signature"]
        if len(sigs) < 1000:
            break

    # Parse each transaction for balance changes
    raw_events = []
    for sig_info in all_sigs:
        sig = sig_info["signature"]
        tx_resp = solana_rpc("getTransaction", [
            sig,
            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
        ])
        tx = tx_resp.get("result")
        if tx is None:
            continue

        ts = datetime.fromtimestamp(tx["blockTime"], tz=timezone.utc)
        meta = tx["meta"]

        # Extract wallet's token balance changes
        pre = {}
        post = {}
        for b in meta.get("preTokenBalances", []):
            if b.get("owner") == wallet:
                pre[b["mint"]] = Decimal(
                    b["uiTokenAmount"].get("uiAmountString", "0")
                )
        for b in meta.get("postTokenBalances", []):
            if b.get("owner") == wallet:
                post[b["mint"]] = Decimal(
                    b["uiTokenAmount"].get("uiAmountString", "0")
                )

        pt_diff = post.get(pt_mint, Decimal(0)) - pre.get(pt_mint, Decimal(0))
        underlying_diff = (
            post.get(underlying_mint, Decimal(0))
            - pre.get(underlying_mint, Decimal(0))
        )

        if pt_diff != 0:
            raw_events.append({
                "timestamp": ts,
                "pt_diff": pt_diff,
                "underlying_diff": underlying_diff,
                "tx_signature": sig,
            })

    # Sort chronologically
    raw_events.sort(key=lambda e: e["timestamp"])

    # Classify events into AMM swap lots
    lots = []

    for event in raw_events:
        pt_diff = event["pt_diff"]
        underlying_diff = event["underlying_diff"]

        if pt_diff > 0 and underlying_diff < 0:
            # AMM swap: underlying out, PT in — clear purchase lot
            lots.append(_build_lot(
                purchase_date=event["timestamp"].date(),
                pt_quantity=pt_diff,
                underlying_paid=abs(underlying_diff),
                maturity=maturity,
                tx_signature=event["tx_signature"],
                lot_type="amm_swap",
            ))
        # Other patterns (PT out = Kamino deposit, PT in + underlying in = LP
        # withdrawal, etc.) are not AMM swaps. LP lots handled separately below.

    # Resolve LP lots from explicit tx groups
    if lp_lot_tx_groups:
        for tx_group in lp_lot_tx_groups:
            lp_lot = _resolve_lp_lot(wallet, pt_mint, underlying_mint, maturity, tx_group)
            if lp_lot:
                lots.append(lp_lot)

    # Sort by purchase date
    lots.sort(key=lambda lot: lot["purchase_date"])

    return lots


def _resolve_lp_lot(
    wallet: str,
    pt_mint: str,
    underlying_mint: str,
    maturity: date,
    tx_signatures: list[str],
) -> dict | None:
    """Resolve an LP lot from a group of related transactions.

    Parses each transaction in the group, sums the net PT and underlying
    changes across all of them, and builds a lot from the net result.
    The purchase date is the date of the last transaction (withdrawal).
    """
    total_pt = Decimal(0)
    total_underlying = Decimal(0)
    last_ts = None

    for sig in tx_signatures:
        tx_resp = solana_rpc("getTransaction", [
            sig,
            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
        ])
        tx = tx_resp.get("result")
        if tx is None:
            continue

        ts = datetime.fromtimestamp(tx["blockTime"], tz=timezone.utc)
        if last_ts is None or ts > last_ts:
            last_ts = ts

        meta = tx["meta"]
        pre = {}
        post = {}
        for b in meta.get("preTokenBalances", []):
            if b.get("owner") == wallet:
                pre[b["mint"]] = Decimal(
                    b["uiTokenAmount"].get("uiAmountString", "0")
                )
        for b in meta.get("postTokenBalances", []):
            if b.get("owner") == wallet:
                post[b["mint"]] = Decimal(
                    b["uiTokenAmount"].get("uiAmountString", "0")
                )

        total_pt += post.get(pt_mint, Decimal(0)) - pre.get(pt_mint, Decimal(0))
        total_underlying += (
            post.get(underlying_mint, Decimal(0))
            - pre.get(underlying_mint, Decimal(0))
        )

    # Net: PT received > 0, underlying paid = negative of net underlying change
    if total_pt <= 0 or total_underlying >= 0:
        return None  # not a valid LP lot

    return _build_lot(
        purchase_date=last_ts.date() if last_ts else maturity,
        pt_quantity=total_pt,
        underlying_paid=abs(total_underlying),
        maturity=maturity,
        tx_signature=tx_signatures[-1],  # reference the withdrawal tx
        lot_type="lp_net",
    )


def _build_lot(
    purchase_date: date,
    pt_quantity: Decimal,
    underlying_paid: Decimal,
    maturity: date,
    tx_signature: str,
    lot_type: str,
) -> dict:
    """Build a lot dict with derived fields."""
    total_days = (maturity - purchase_date).days
    # At maturity each PT redeems for 1 underlying, so gain = pt_qty - underlying_paid
    gain_to_maturity = pt_quantity - underlying_paid
    implied_rate = gain_to_maturity / underlying_paid if underlying_paid > 0 else Decimal(0)
    # Annualised rate
    apy = implied_rate * Decimal(365) / Decimal(total_days) if total_days > 0 else Decimal(0)

    return {
        "purchase_date": purchase_date,
        "pt_quantity": pt_quantity,
        "underlying_paid": underlying_paid,
        "gain_to_maturity": gain_to_maturity,
        "total_days": total_days,
        "implied_rate": implied_rate,
        "apy": apy,
        "tx_signature": tx_signature,
        "lot_type": lot_type,
    }


# --- Lot Valuation ---

def value_pt_lots(
    lots: list[dict],
    valuation_date: date,
    underlying_price: Decimal,
) -> dict:
    """Value PT token lots using linear amortisation at a given date.

    Args:
        lots: List of lot dicts from discover_pt_lots()
        valuation_date: Date to value at (e.g. NAV valuation date)
        underlying_price: Price of the underlying token in USD

    Returns:
        Dict with per-lot valuations and aggregate totals.
    """
    lot_valuations = []
    total_pt_quantity = Decimal(0)
    total_underlying_value = Decimal(0)
    total_usd_value = Decimal(0)

    for lot in lots:
        days_elapsed = (valuation_date - lot["purchase_date"]).days
        days_elapsed = max(0, min(days_elapsed, lot["total_days"]))

        # Linear amortisation: yield accrues linearly from purchase to maturity
        if lot["total_days"] > 0:
            yield_to_date = lot["gain_to_maturity"] * Decimal(days_elapsed) / Decimal(lot["total_days"])
        else:
            yield_to_date = lot["gain_to_maturity"]

        # Value in underlying terms
        lot_value_underlying = lot["underlying_paid"] + yield_to_date
        # Value in USD
        lot_value_usd = lot_value_underlying * underlying_price

        lot_valuations.append({
            **lot,
            "days_elapsed": days_elapsed,
            "yield_to_date": yield_to_date,
            "value_underlying": lot_value_underlying,
            "value_usd": lot_value_usd,
        })

        total_pt_quantity += lot["pt_quantity"]
        total_underlying_value += lot_value_underlying
        total_usd_value += lot_value_usd

    # Weighted average implied rate
    total_cost = sum(lot["underlying_paid"] for lot in lots)
    weighted_apy = (
        sum(lot["apy"] * lot["underlying_paid"] for lot in lots) / total_cost
        if total_cost > 0 else Decimal(0)
    )

    return {
        "lots": lot_valuations,
        "total_pt_quantity": total_pt_quantity,
        "total_underlying_value": total_underlying_value,
        "total_usd_value": total_usd_value,
        "total_lots": len(lots),
        "weighted_avg_apy": weighted_apy,
        "valuation_date": valuation_date,
        "underlying_price": underlying_price,
    }


# --- Load from config (fast path — no RPC) ---

def load_pt_lots(pt_symbol: str) -> tuple[list[dict], dict]:
    """Load pre-discovered PT lots from config/pt_lots.json.

    Use this for valuation — avoids re-querying the blockchain.
    Use discover_pt_lots() only for initial onboarding or auditing.

    Args:
        pt_symbol: Key in pt_lots.json (e.g. "PT-USX-01JUN26")

    Returns:
        Tuple of (lots list ready for value_pt_lots(), config dict)
    """
    with open(os.path.join(CONFIG_DIR, "pt_lots.json")) as f:
        config = json.load(f)

    if pt_symbol not in config:
        raise ValueError(f"PT symbol {pt_symbol} not found in pt_lots.json")

    pt_config = config[pt_symbol]
    maturity = date.fromisoformat(pt_config["maturity"])
    lots = []

    for lot_data in pt_config.get("lots_discovered", []):
        lots.append(_build_lot(
            purchase_date=date.fromisoformat(lot_data["date"]),
            pt_quantity=Decimal(str(lot_data["pt_qty"])),
            underlying_paid=Decimal(str(lot_data["underlying_paid"])),
            maturity=maturity,
            tx_signature="from_config",
            lot_type=lot_data["type"],
        ))

    return lots, pt_config


def value_pt_from_config(
    pt_symbol: str,
    valuation_date: date,
    underlying_price: Decimal,
) -> dict:
    """Value a PT position using lots from config. No RPC calls.

    Args:
        pt_symbol: Key in pt_lots.json (e.g. "PT-USX-01JUN26")
        valuation_date: Date to value at
        underlying_price: Price of the underlying token in USD

    Returns:
        Dict with per-lot valuations and aggregate totals.
    """
    lots, pt_config = load_pt_lots(pt_symbol)
    result = value_pt_lots(lots, valuation_date, underlying_price)
    result["pt_symbol"] = pt_symbol
    result["maturity"] = pt_config["maturity"]
    result["underlying"] = pt_config["underlying"]
    return result


if __name__ == "__main__":
    from datetime import date as d

    # Fast path: load from config (no RPC calls)
    print("=== PT-USX from config (fast) ===")
    val_usx = value_pt_from_config("PT-USX-01JUN26", d(2026, 3, 18), Decimal("1.0"))
    for lot in val_usx["lots"]:
        print(
            f"  {lot['purchase_date']} ({lot['lot_type']:8s}): "
            f"{lot['pt_quantity']:>12,.2f} PT | "
            f"cost {lot['underlying_paid']:>12,.2f} | "
            f"val {lot['value_underlying']:>12,.2f} | "
            f"APY {lot['apy']:.2%}"
        )
    print(f"  Total: ${val_usx['total_usd_value']:,.2f}  (spreadsheet: $1,766,815.73, diff: ${val_usx['total_usd_value'] - Decimal('1766815.73'):+,.2f})")

    print("\n=== PT-eUSX from config (fast) ===")
    from solana_client import get_eusx_exchange_rate
    eusx_rate = get_eusx_exchange_rate()
    val_eusx = value_pt_from_config("PT-eUSX-01JUN26", d(2026, 3, 18), eusx_rate)
    for lot in val_eusx["lots"]:
        print(
            f"  {lot['purchase_date']} ({lot['lot_type']:8s}): "
            f"{lot['pt_quantity']:>12,.2f} PT | "
            f"cost {lot['underlying_paid']:>12,.2f} eUSX | "
            f"val {lot['value_underlying']:>12,.2f} eUSX | "
            f"APY {lot['apy']:.2%}"
        )
    print(f"  Total: ${val_eusx['total_usd_value']:,.2f}  (eUSX rate: {eusx_rate:.6f})")
