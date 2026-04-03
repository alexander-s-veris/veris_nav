"""Gauntlet / FalconX handlers (Category A3 — manual accrual from SQLite)."""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

from web3 import Web3

from handlers import _load_contracts_cfg, _get_abi, _fmt
from handlers._registry import register_evm_handler

logger = logging.getLogger(__name__)


def _get_tp_staleness_threshold():
    """Read TP staleness threshold from config."""
    contracts = _load_contracts_cfg()
    gp = contracts.get("ethereum", {}).get("_gauntlet_pareto", {})
    return gp.get("tp_staleness_threshold_days", 45)


@register_evm_handler("gauntlet_falconx", query_type="manual_accrual_gauntlet", display_name="Gauntlet (FalconX)")
def query_gauntlet_falconx(w3, chain, wallet, block_number, block_ts):
    """Query Gauntlet vault FalconX A3 position.

    Reads the accrual NAV value from data/falconx.db (gauntlet_levered table).
    On-chain vault shares are queried for balance_human reporting only.
    """
    contracts = _load_contracts_cfg()
    gp_section = contracts.get(chain, {}).get("_gauntlet_pareto", {})
    vault_cfg = gp_section.get("gauntlet_vault", {})
    GAUNTLET_VAULT = vault_cfg.get("address")
    if not GAUNTLET_VAULT:
        return []
    vault_decimals = vault_cfg.get("decimals")
    if vault_decimals is None:
        raise ValueError("Gauntlet vault config missing 'decimals' in contracts.json")
    erc20_abi = _get_abi("erc20")

    vault = w3.eth.contract(address=Web3.to_checksum_address(GAUNTLET_VAULT), abi=erc20_abi)
    veris_shares = vault.functions.balanceOf(Web3.to_checksum_address(wallet)).call(block_identifier=block_number)
    total_supply = vault.functions.totalSupply().call(block_identifier=block_number)
    logger.info("gauntlet.balanceOf(%s, %s) block=%s → shares=%s, totalSupply=%s",
                 GAUNTLET_VAULT, wallet, block_number, veris_shares, total_supply)
    if veris_shares == 0:
        return []

    share_pct = Decimal(str(veris_shares)) / Decimal(str(total_supply))

    # Read accrual NAV from SQLite (sole source of truth)
    accrual_value = _read_falconx_sqlite("gauntlet_levered", "veris_share")
    source_note = "from data/falconx.db gauntlet_levered"

    if accrual_value is None:
        logger.warning("gauntlet_levered: SQLite returned None — no data in falconx.db")
        accrual_value = Decimal(0)
        source_note = "WARNING: no data in falconx.db"

    # TP staleness check
    staleness_note = _check_tp_staleness()
    if staleness_note:
        source_note += f" | {staleness_note}"

    return [{
        "chain": chain, "protocol": "gauntlet_pareto", "protocol_display": "Gauntlet Vaults", "wallet": wallet,
        "position_label": "Gauntlet Levered FalconX",
        "category": "A3", "position_type": "manual_accrual",
        "token_symbol": "gpAAFalconX",
        "underlying_symbol": vault_cfg.get("underlying_symbol", ""),
        "token_contract": GAUNTLET_VAULT,
        "balance_raw": str(veris_shares),
        "balance_human": _fmt(veris_shares, vault_decimals),
        "decimals": vault_decimals,
        "veris_share_pct": share_pct * 100,
        "accrual_value": accrual_value,
        "block_number": block_number, "block_timestamp_utc": block_ts,
        "price_source": "a3_workbook_accrual",
        "notes": f"Value {source_note} (Veris share). TP on-chain is cross-reference only.",
    }]


def _read_falconx_sqlite(table_name, value_column):
    """Read the latest value from the FalconX SQLite database.

    Args:
        table_name: 'gauntlet_levered' or 'direct_accrual'
        value_column: column name to read (e.g. 'veris_share' or 'running_balance')
    """
    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "falconx.db")
    if not os.path.exists(db_path):
        return None

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            f"SELECT {value_column} FROM {table_name} ORDER BY timestamp_utc DESC LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()
        if row and row[0] is not None:
            return Decimal(str(row[0]))
    except Exception as e:
        logger.warning("gauntlet: _read_falconx_sqlite failed for %s.%s: %s", table_name, value_column, e)
    return None


def _check_tp_staleness():
    """Check if on-chain TP hasn't changed beyond the configured threshold.

    First checks the tp_changes table (populated by the updater).
    Falls back to scanning gauntlet_levered for the last TP transition.

    Returns a warning string if stale, or None.
    """
    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "falconx.db")
    if not os.path.exists(db_path):
        return None

    try:
        conn = sqlite3.connect(db_path)

        # Try tp_changes table first (faster, populated by updater)
        try:
            row = conn.execute(
                "SELECT timestamp_utc FROM tp_changes ORDER BY timestamp_utc DESC LIMIT 1"
            ).fetchone()
            if row:
                last_change = datetime.strptime(
                    row[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                days = (datetime.now(timezone.utc) - last_change).days
                conn.close()
                if days > _get_tp_staleness_threshold():
                    return f"WARNING: on-chain TP stale ({days} days since last change, threshold={_get_tp_staleness_threshold()}d)"
                return None
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet — fall through

        # Fallback: scan gauntlet_levered for last distinct TP transition
        rows = conn.execute(
            "SELECT timestamp_utc, tranche_price FROM gauntlet_levered "
            "WHERE tranche_price IS NOT NULL ORDER BY timestamp_utc DESC"
        ).fetchall()
        conn.close()

        if not rows:
            return None

        current_tp = rows[0][1]
        last_change_ts = rows[0][0]
        for ts_str, tp in rows:
            if abs(tp - current_tp) > 0.000001:
                # Found the transition point — last_change_ts is the first row with current TP
                break
            last_change_ts = ts_str

        last_change = datetime.strptime(
            last_change_ts, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - last_change).days
        if days > _get_tp_staleness_threshold():
            return f"WARNING: on-chain TP stale ({days} days since last change, threshold={_get_tp_staleness_threshold()}d)"

    except Exception as e:
        logger.warning("gauntlet: _check_tp_staleness failed: %s", e)

    return None


@register_evm_handler("falconx_direct", query_type="manual_accrual_direct", display_name="FalconX (Direct)")
def query_falconx_direct(w3, chain, wallet, block_number, block_ts):
    """Query direct AA_FalconXUSDC holding for A3 accrual.

    Reads the Running Balance from data/falconx.db (direct_accrual table).
    """
    contracts = _load_contracts_cfg()
    gp_section = contracts.get(chain, {}).get("_gauntlet_pareto", {})
    tranche_cfg = gp_section.get("aa_falconxusdc_tranche", {})
    AA_TRANCHE = tranche_cfg.get("address")
    if not AA_TRANCHE:
        return []
    tranche_decimals = tranche_cfg.get("decimals")
    if tranche_decimals is None:
        raise ValueError("AA_FalconXUSDC tranche config missing 'decimals' in contracts.json")
    erc20_abi = _get_abi("erc20")

    token = w3.eth.contract(
        address=Web3.to_checksum_address(AA_TRANCHE), abi=erc20_abi)
    balance = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call(block_identifier=block_number)
    logger.info("falconx_direct.balanceOf(%s, %s) block=%s → %s", AA_TRANCHE, wallet, block_number, balance)
    if balance == 0:
        return []

    balance_human = _fmt(balance, tranche_decimals)

    # Read accrual value from SQLite (sole source of truth)
    running_balance = _read_falconx_sqlite("direct_accrual", "running_balance")
    source_note = "from data/falconx.db direct_accrual"

    if running_balance is None:
        logger.warning("direct_accrual: SQLite returned None — no data in falconx.db")
        running_balance = Decimal(0)
        source_note = "WARNING: no data in falconx.db"

    # TP staleness check (same TP as Gauntlet — shared Pareto tranche)
    staleness_note = _check_tp_staleness()
    if staleness_note:
        source_note += f" | {staleness_note}"

    return [{
        "chain": chain, "protocol": "gauntlet_pareto", "protocol_display": "Pareto", "wallet": wallet,
        "position_label": "Pareto / FalconX",
        "category": "A3", "position_type": "manual_accrual",
        "token_symbol": "AA_FalconXUSDC",
        "underlying_symbol": tranche_cfg.get("underlying_symbol", ""),
        "token_contract": AA_TRANCHE,
        "balance_raw": str(balance),
        "balance_human": balance_human,
        "decimals": tranche_decimals,
        "accrual_value": running_balance,
        "price_source": "a3_workbook_accrual",
        "block_number": block_number, "block_timestamp_utc": block_ts,
        "notes": f"Value {source_note}. Running Balance={running_balance:,.2f}",
    }]
