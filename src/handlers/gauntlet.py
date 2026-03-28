"""Gauntlet / FalconX handlers (Category A3 cross-reference)."""

import logging
import os
import sqlite3
from decimal import Decimal

from web3 import Web3

from handlers import _load_contracts_cfg, _get_abi, _fmt

logger = logging.getLogger(__name__)


def query_gauntlet_falconx(w3, chain, wallet, block_number, block_ts):
    """Query Gauntlet vault FalconX A3 position.

    Computes the NAV value using accrual methodology from the raw data in the
    supporting workbook (Gauntlet_LeveredX sheet). Also queries on-chain
    cross-reference data (TP x collateral - debt x share%).

    Accrual formula (per falconx_position_flow.md):
      Running Balance = Opening Value + sum(Opening x Rate x Period / 365)
      TP (re-engineered) = Running Balance / Veris AA_FalconXUSDC
      Collateral (USD) = Vault Collateral x TP (re-engineered)
      Net = Collateral (USD) - Borrow
      Veris share = Net x Veris %
    """
    contracts = _load_contracts_cfg()
    gp_section = contracts.get(chain, {}).get("_gauntlet_pareto", {})
    vault_cfg = gp_section.get("gauntlet_vault", {})
    GAUNTLET_VAULT = vault_cfg.get("address")
    if not GAUNTLET_VAULT:
        return []
    vault_decimals = vault_cfg.get("decimals", 18)
    erc20_abi = _get_abi("erc20")

    # Only need veris shares for reporting (balance_human)
    vault = w3.eth.contract(address=Web3.to_checksum_address(GAUNTLET_VAULT), abi=erc20_abi)
    veris_shares = vault.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
    total_supply = vault.functions.totalSupply().call()
    logger.info("gauntlet.balanceOf(%s, %s) block=%s → shares=%s, totalSupply=%s",
                 GAUNTLET_VAULT, wallet, block_number, veris_shares, total_supply)
    if veris_shares == 0:
        return []

    share_pct = Decimal(str(veris_shares)) / Decimal(str(total_supply))

    # --- Read accrual NAV from SQLite (primary) or xlsx (fallback) ---
    accrual_value = _read_falconx_sqlite("gauntlet_levered", "veris_share")
    source_note = "from data/falconx.db gauntlet_levered"

    if accrual_value is None:
        xlsx_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "outputs", "falconx_position.xlsx")
        accrual_value = _read_falconx_xlsx(xlsx_path, "Gauntlet_LeveredX", col_index=17)
        source_note = "from outputs/falconx_position.xlsx Gauntlet_LeveredX col R (fallback)"

    if accrual_value is None:
        accrual_value = Decimal(0)

    return [{
        "chain": chain, "protocol": "gauntlet_pareto", "wallet": wallet,
        "position_label": "Gauntlet FalconX Vault",
        "category": "A3", "position_type": "manual_accrual",
        "token_symbol": "gpAAFalconX",
        "token_contract": GAUNTLET_VAULT,
        "balance_raw": str(veris_shares),
        "balance_human": _fmt(veris_shares, vault_decimals),
        "decimals": vault_decimals,
        "veris_share_pct": share_pct * 100,
        "accrual_value": accrual_value,
        "block_number": block_number, "block_timestamp_utc": block_ts,
        "price_source": "a3_workbook_accrual",
        "notes": f"Value {source_note} (Veris share). TP on-chain is cross-reference only (stale, not used for valuation).",
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
    except Exception:
        pass
    return None


def _read_falconx_xlsx(xlsx_path, sheet_name, col_index):
    """Read the NAV value from the FalconX workbook (fallback if SQLite unavailable).

    First tries formula result columns (openpyxl data_only=True).
    If formula columns are empty (newly written rows), computes the value
    from the raw data columns using the accrual methodology.

    Gauntlet_LeveredX: col R (17) = Veris share = (Collateral x TP_reeng - Borrow) x Veris%
    Direct Accrual: col H (7) = Running Balance = Opening + cumulative interest
    """
    import openpyxl

    if not os.path.exists(xlsx_path):
        return None

    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
        ws = wb[sheet_name]

        # Read last cached formula value from Excel-saved workbook
        last_value = None
        all_rows = []
        for row in ws.iter_rows(min_row=2):
            if len(row) > col_index and row[col_index].value is not None:
                last_value = row[col_index].value
            if row[0].value is not None:
                all_rows.append([cell.value for cell in row])

        wb.close()

        # Primary: cached formula value (requires workbook saved from Excel)
        if last_value is not None:
            return Decimal(str(last_value))

        # Fallback: compute from raw data columns if formulas not cached
        if all_rows:
            if sheet_name == "Gauntlet_LeveredX":
                return _compute_gauntlet_value(all_rows)
            elif sheet_name == "Direct Accrual":
                return _compute_direct_value(all_rows)

    except Exception:
        pass

    return None


def _compute_gauntlet_value(rows):
    """Compute Gauntlet Veris share from raw data columns when formulas aren't cached.

    Uses the accrual methodology from falconx_position_flow.md:
    Running Balance accrues interest hourly at Net Rate.
    TP_reengineered = Running Balance / Veris AA_FalconXUSDC.
    Collateral(USD) = on-chain Collateral x TP_reengineered.
    Net = Collateral(USD) - Borrow.
    Veris share = Net x (VerisBalance / TotalSupply).
    """
    running_balance = None
    veris_aa = None
    prev_ts = None

    for row in rows:
        ts = row[0]
        if ts is None:
            continue
        rate = Decimal(str(row[7])) if row[7] else Decimal(0)
        if row[8] is not None:
            veris_aa = Decimal(str(row[8]))
        if running_balance is None:
            if row[11] is not None:
                running_balance = Decimal(str(row[11]))
            elif veris_aa and row[9]:
                running_balance = veris_aa * Decimal(str(row[9]))
            prev_ts = ts
            continue
        if prev_ts is None:
            prev_ts = ts
            continue
        delta = (ts - prev_ts).total_seconds()
        period_days = Decimal(str(delta)) / Decimal(86400)
        if period_days > 0 and rate > 0:
            running_balance += running_balance * rate * period_days / Decimal(365)
        prev_ts = ts

    if running_balance is None or veris_aa is None or veris_aa == 0:
        return None

    last = rows[-1]
    collateral = Decimal(str(last[2])) if last[2] else Decimal(0)
    borrow = Decimal(str(last[3])) if last[3] else Decimal(0)
    total_supply = Decimal(str(last[4])) if last[4] else Decimal(1)
    veris_balance = Decimal(str(last[5])) if last[5] else Decimal(0)

    tp_reeng = running_balance / veris_aa
    collateral_usd = collateral * tp_reeng
    net = collateral_usd - borrow
    veris_pct = veris_balance / total_supply if total_supply > 0 else Decimal(0)
    return net * veris_pct


def _compute_direct_value(rows):
    """Compute Direct Accrual Running Balance from raw data columns.

    Running Balance = Opening Value + cumulative interest.
    Interest = Running Balance x Rate x Period / 365.
    """
    running_balance = None
    prev_ts = None
    rate = None  # Must come from data (row[4]) -- no hardcoded default

    for row in rows:
        ts = row[0]
        if ts is None:
            continue
        if row[4] is not None:
            rate = Decimal(str(row[4]))
        if running_balance is None:
            if row[3] is not None:
                running_balance = Decimal(str(row[3]))
            prev_ts = ts
            continue
        if prev_ts is None:
            prev_ts = ts
            continue
        delta = (ts - prev_ts).total_seconds()
        period_days = Decimal(str(delta)) / Decimal(86400)
        if rate is None:
            raise ValueError("No rate found in Direct Accrual data -- rate must come from loan notice")
        if period_days > 0 and rate > 0:
            running_balance += running_balance * rate * period_days / Decimal(365)
        prev_ts = ts

    return running_balance


def query_falconx_direct(w3, chain, wallet, block_number, block_ts):
    """Query direct AA_FalconXUSDC holding for A3 accrual.

    Reads the Running Balance from the supporting workbook (Direct Accrual sheet).
    """
    contracts = _load_contracts_cfg()
    gp_section = contracts.get(chain, {}).get("_gauntlet_pareto", {})
    tranche_cfg = gp_section.get("aa_falconxusdc_tranche", {})
    AA_TRANCHE = tranche_cfg.get("address")
    if not AA_TRANCHE:
        return []
    tranche_decimals = tranche_cfg.get("decimals", 18)
    erc20_abi = _get_abi("erc20")

    # Check if wallet holds AA_FalconXUSDC
    token = w3.eth.contract(
        address=Web3.to_checksum_address(AA_TRANCHE), abi=erc20_abi)
    balance = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
    logger.info("falconx_direct.balanceOf(%s, %s) block=%s → %s", AA_TRANCHE, wallet, block_number, balance)
    if balance == 0:
        return []

    balance_human = _fmt(balance, tranche_decimals)

    # Read accrual value from SQLite (primary) or xlsx (fallback)
    running_balance = _read_falconx_sqlite("direct_accrual", "running_balance")
    source_note = "from data/falconx.db direct_accrual"

    if running_balance is None:
        xlsx_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "outputs", "falconx_position.xlsx")
        running_balance = _read_falconx_xlsx(xlsx_path, "Direct Accrual", col_index=7)
        source_note = "from outputs/falconx_position.xlsx Direct Accrual col H (fallback)"

    if running_balance is None:
        running_balance = Decimal(0)

    return [{
        "chain": chain, "protocol": "gauntlet_pareto", "wallet": wallet,
        "position_label": "FalconX Direct AA_FalconXUSDC",
        "category": "A3", "position_type": "manual_accrual",
        "token_symbol": "AA_FalconXUSDC",
        "token_contract": AA_TRANCHE,
        "balance_raw": str(balance),
        "balance_human": balance_human,
        "decimals": tranche_decimals,
        "accrual_value": running_balance,
        "price_source": "a3_workbook_accrual",
        "block_number": block_number, "block_timestamp_utc": block_ts,
        "notes": f"Value {source_note}. Running Balance={running_balance:,.2f}",
    }]
