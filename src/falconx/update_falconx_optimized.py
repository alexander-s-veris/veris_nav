"""
Optimized FalconX/Pareto position updater.

Uses block pre-computation and concurrent RPC queries from src/block_utils.py.
Writes to data/falconx.db (SQLite). All values computed in Python — no formulas.

Can be run standalone or imported by collect.py:
    # Standalone
    python src/falconx/update_falconx_optimized.py [--start YYYY-MM-DD-HH] [--end YYYY-MM-DD-HH]

    # From collect.py
    from falconx.update_falconx_optimized import run_update
    g, d = run_update()

Defaults: start = last timestamp in SQLite + 1 hour, end = now (rounded down to hour).
"""
import sys
import os
import time
import logging
import argparse
import sqlite3
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from web3 import Web3

logger = logging.getLogger(__name__)

# --- Path setup (before any local imports) ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from falconx.rates import get_net_rate

# --- Constants ---
VERIS_GP_BALANCE = 2507114.7845223
VERIS_AA_TOKENS_GAUNTLET = 2473068.8259
VERIS_AA_TOKENS_DIRECT = 1894969.859499
DIRECT_OPENING_VALUE = 2024989.2306  # Actual USDC deposited (not tokens × stale TP)

MARKET_ID_HEX = "e83d72fa5b00dcd46d9e0e860d95aa540d5ec106da5833108a9f826f21f36f52"

# Contract addresses (raw strings, checksummed lazily in _init)
_MULTICALL3_ADDR = "0xcA11bde05977b3631167028862bE2a173976CA11"
_MORPHO_ADDR = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
_GAUNTLET_ADDR = "0x00000000d8f3d6c5DFeB2D2b5ED2276095f3aF44"
_PARETO_ADDR = "0x433d5b175148da32ffe1e1a37a939e1b7e79be4d"
_TRANCHE_ADDR = "0xC26A6Fa2C37b38E549a4a1807543801Db684f99C"

DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'falconx.db')

# --- Lazy-initialised Web3 state ---
_initialized = False
_w3 = None
_mc = None
_POS_CALL = None
_MKT_CALL = None
_SUP_CALL = None
_TP_CALL = None
_MORPHO = None
_GAUNTLET = None
_PARETO = None
_TRANCHE = None


def _init():
    """Lazy Web3 + contract initialisation. Only runs once."""
    global _initialized, _w3, _mc, _POS_CALL, _MKT_CALL, _SUP_CALL, _TP_CALL
    global _MORPHO, _GAUNTLET, _PARETO, _TRANCHE

    if _initialized:
        return

    # Load .env if not already loaded (standalone mode)
    if "ALCHEMY_API_KEY" not in os.environ:
        env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        os.environ[k.strip()] = v.strip()

    from evm import get_web3
    _w3 = get_web3("ethereum")

    MARKET_ID = bytes.fromhex(MARKET_ID_HEX)

    _MORPHO = _w3.to_checksum_address(_MORPHO_ADDR)
    _GAUNTLET = _w3.to_checksum_address(_GAUNTLET_ADDR)
    _PARETO = _w3.to_checksum_address(_PARETO_ADDR)
    _TRANCHE = _w3.to_checksum_address(_TRANCHE_ADDR)
    MULTICALL3 = _w3.to_checksum_address(_MULTICALL3_ADDR)

    # Pre-build calldata
    POS_SIG = Web3.keccak(text="position(bytes32,address)")[:4]
    _POS_CALL = POS_SIG + MARKET_ID + bytes.fromhex(_GAUNTLET[2:].lower()).rjust(32, b'\x00')
    MKT_SIG = Web3.keccak(text="market(bytes32)")[:4]
    _MKT_CALL = MKT_SIG + MARKET_ID
    _SUP_CALL = Web3.keccak(text="totalSupply()")[:4]
    TP_SIG = Web3.keccak(text="tranchePrice(address)")[:4]
    _TP_CALL = TP_SIG + bytes.fromhex(_TRANCHE[2:].lower()).rjust(32, b'\x00')

    MC_ABI = [{
        "inputs": [{"components": [
            {"name": "target", "type": "address"},
            {"name": "callData", "type": "bytes"}
        ], "name": "calls", "type": "tuple[]"}],
        "name": "aggregate",
        "outputs": [
            {"name": "blockNumber", "type": "uint256"},
            {"name": "returnData", "type": "bytes[]"}
        ],
        "stateMutability": "view", "type": "function"
    }]
    _mc = _w3.eth.contract(address=MULTICALL3, abi=MC_ABI)

    _initialized = True


# --- Database helpers ---

def _ensure_db():
    """Ensure database and tables exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gauntlet_levered (
            timestamp_utc TEXT PRIMARY KEY,
            block INTEGER,
            collateral REAL,
            borrow REAL,
            vault_total_supply REAL,
            veris_balance REAL,
            veris_pct REAL,
            net_rate REAL,
            veris_aa_falconx REAL,
            tranche_price REAL,
            period_days REAL,
            opening_value REAL,
            interest REAL,
            running_balance REAL,
            tp_reengineered REAL,
            collateral_usd REAL,
            net REAL,
            veris_share REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS direct_accrual (
            timestamp_utc TEXT PRIMARY KEY,
            token_balance REAL,
            tranche_price REAL,
            opening_value REAL,
            net_rate REAL,
            period_days REAL,
            interest REAL,
            running_balance REAL,
            tp_reengineered REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tp_changes (
            detected_at TEXT,
            timestamp_utc TEXT,
            old_tp REAL,
            new_tp REAL
        )
    """)
    conn.commit()
    return conn


def _get_last_gauntlet(conn):
    """Get last row from gauntlet_levered. Returns (ts, block, running_balance, tp) or None."""
    row = conn.execute(
        "SELECT timestamp_utc, block, running_balance, tranche_price "
        "FROM gauntlet_levered ORDER BY timestamp_utc DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    ts = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    return ts, int(row[1]), row[2], row[3]


def _get_last_direct(conn):
    """Get last row from direct_accrual. Returns (timestamp_utc, running_balance) or None."""
    row = conn.execute(
        "SELECT timestamp_utc, running_balance FROM direct_accrual ORDER BY timestamp_utc DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    ts = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    return ts, row[1]


# --- On-chain query ---

def _query_at_block(block):
    """Multicall query at a given block. Returns (coll, borrow, supply, tp)."""
    calls = [
        (_MORPHO, _POS_CALL),
        (_MORPHO, _MKT_CALL),
        (_GAUNTLET, _SUP_CALL),
        (_PARETO, _TP_CALL),
    ]
    _, data = _mc.functions.aggregate(calls).call(block_identifier=block)

    coll = int.from_bytes(data[0][64:96], 'big')
    borrow_shares = int.from_bytes(data[0][32:64], 'big')
    total_borrow_assets = int.from_bytes(data[1][64:96], 'big')
    total_borrow_shares = int.from_bytes(data[1][96:128], 'big')
    borrow = borrow_shares * total_borrow_assets // total_borrow_shares if total_borrow_shares > 0 else 0
    total_supply = int.from_bytes(data[2][0:32], 'big')
    tp = int.from_bytes(data[3][0:32], 'big')

    return (
        float(Decimal(str(coll)) / Decimal(10**18)),
        float(Decimal(str(borrow)) / Decimal(10**6)),
        float(Decimal(str(total_supply)) / Decimal(10**18)),
        float(Decimal(str(tp)) / Decimal(10**6)),
    )


# --- TP change detection ---

def _detect_tp_changes(conn, prev_tp, gauntlet_rows):
    """Detect and record on-chain tranche price changes.

    Compares each row's TP against the previous. Logs prominently and
    writes to tp_changes table.
    """
    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    changes = []

    for row in gauntlet_rows:
        ts_str = row[0]
        tp = row[9]  # tranche_price column
        if prev_tp is not None and abs(tp - prev_tp) > 0.000001:
            msg = f"*** TP CHANGE DETECTED at {ts_str}: {prev_tp:.6f} -> {tp:.6f} ***"
            print(msg)
            logger.warning(msg)
            changes.append((now_str, ts_str, prev_tp, tp))
        prev_tp = tp

    if changes:
        conn.executemany(
            "INSERT INTO tp_changes (detected_at, timestamp_utc, old_tp, new_tp) VALUES (?, ?, ?, ?)",
            changes)
        conn.commit()
        print(f"  Recorded {len(changes)} TP change(s) in tp_changes table")

    return prev_tp


# --- Rate back-recalculation ---

def _check_and_recompute_rates(conn):
    """Check for rate mismatches and recompute affected rows.

    When a new loan notice rate is added to config, existing rows may have
    been computed with a stale rate. This detects mismatches and cascades
    the correct values forward from the first affected row.
    """
    # --- Gauntlet ---
    rows = conn.execute(
        "SELECT timestamp_utc, net_rate FROM gauntlet_levered ORDER BY timestamp_utc"
    ).fetchall()

    first_bad_g = None
    for ts_str, stored_rate in rows:
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        expected = get_net_rate(ts)
        if abs(stored_rate - expected) > 1e-10:
            first_bad_g = ts_str
            break

    if first_bad_g:
        _recompute_gauntlet_from(conn, first_bad_g)

    # --- Direct ---
    rows_d = conn.execute(
        "SELECT timestamp_utc, net_rate FROM direct_accrual ORDER BY timestamp_utc"
    ).fetchall()

    first_bad_d = None
    for ts_str, stored_rate in rows_d:
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        expected = get_net_rate(ts)
        if abs(stored_rate - expected) > 1e-10:
            first_bad_d = ts_str
            break

    if first_bad_d:
        _recompute_direct_from(conn, first_bad_d)


def _recompute_gauntlet_from(conn, first_bad_ts):
    """Recompute gauntlet_levered rows from first_bad_ts onward."""
    # Get the row before the first bad one for opening state
    prev = conn.execute(
        "SELECT running_balance, timestamp_utc FROM gauntlet_levered "
        "WHERE timestamp_utc < ? ORDER BY timestamp_utc DESC LIMIT 1",
        (first_bad_ts,)
    ).fetchone()

    if prev is None:
        print(f"  WARNING: Cannot recompute gauntlet — no row before {first_bad_ts}")
        return

    prev_running_balance = prev[0]
    prev_ts = datetime.strptime(prev[1], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)

    # Get all rows from first_bad_ts onward
    rows = conn.execute(
        "SELECT timestamp_utc, block, collateral, borrow, vault_total_supply, tranche_price "
        "FROM gauntlet_levered WHERE timestamp_utc >= ? ORDER BY timestamp_utc",
        (first_bad_ts,)
    ).fetchall()

    print(f"  Recomputing {len(rows)} gauntlet rows from {first_bad_ts}")

    updates = []
    for ts_str, block, coll, borrow, supply, tp in rows:
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        net_rate = get_net_rate(ts)
        veris_pct = VERIS_GP_BALANCE / supply if supply > 0 else 0
        period_days = (ts - prev_ts).total_seconds() / 86400.0
        opening_value = prev_running_balance
        interest = opening_value * net_rate * period_days / 365.0
        running_balance = opening_value + interest
        tp_reengineered = running_balance / VERIS_AA_TOKENS_GAUNTLET if VERIS_AA_TOKENS_GAUNTLET > 0 else 0
        collateral_usd = coll * tp_reengineered
        net = collateral_usd - borrow
        veris_share = net * veris_pct

        updates.append((
            veris_pct, net_rate, period_days, opening_value, interest,
            running_balance, tp_reengineered, collateral_usd, net, veris_share,
            ts_str
        ))

        prev_running_balance = running_balance
        prev_ts = ts

    conn.executemany("""
        UPDATE gauntlet_levered SET
            veris_pct=?, net_rate=?, period_days=?, opening_value=?, interest=?,
            running_balance=?, tp_reengineered=?, collateral_usd=?, net=?, veris_share=?
        WHERE timestamp_utc=?
    """, updates)
    conn.commit()
    print(f"  Gauntlet: recomputed {len(updates)} rows")


def _recompute_direct_from(conn, first_bad_ts):
    """Recompute direct_accrual rows from first_bad_ts onward."""
    prev = conn.execute(
        "SELECT running_balance, timestamp_utc FROM direct_accrual "
        "WHERE timestamp_utc < ? ORDER BY timestamp_utc DESC LIMIT 1",
        (first_bad_ts,)
    ).fetchone()

    if prev is None:
        print(f"  WARNING: Cannot recompute direct — no row before {first_bad_ts}")
        return

    prev_running_balance = prev[0]
    prev_ts = datetime.strptime(prev[1], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)

    rows = conn.execute(
        "SELECT timestamp_utc FROM direct_accrual WHERE timestamp_utc >= ? ORDER BY timestamp_utc",
        (first_bad_ts,)
    ).fetchall()

    print(f"  Recomputing {len(rows)} direct rows from {first_bad_ts}")

    updates = []
    for (ts_str,) in rows:
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        net_rate = get_net_rate(ts)
        period_days = (ts - prev_ts).total_seconds() / 86400.0
        opening_value = prev_running_balance
        interest = opening_value * net_rate * period_days / 365.0
        running_balance = opening_value + interest
        tp_reengineered = running_balance / VERIS_AA_TOKENS_DIRECT if VERIS_AA_TOKENS_DIRECT > 0 else 0

        updates.append((
            opening_value, net_rate, period_days, interest,
            running_balance, tp_reengineered,
            ts_str
        ))

        prev_running_balance = running_balance
        prev_ts = ts

    conn.executemany("""
        UPDATE direct_accrual SET
            opening_value=?, net_rate=?, period_days=?, interest=?,
            running_balance=?, tp_reengineered=?
        WHERE timestamp_utc=?
    """, updates)
    conn.commit()
    print(f"  Direct: recomputed {len(updates)} rows")


# --- Main update function ---

def run_update(start=None, end=None, workers=10, batch=50):
    """Run the FalconX updater. Returns (gauntlet_rows_written, direct_rows_written).

    Args:
        start: Start datetime (UTC) or string 'YYYY-MM-DD-HH'. Default: last row + 1h.
        end: End datetime (UTC) or string 'YYYY-MM-DD-HH'. Default: current hour.
        workers: Concurrent RPC workers.
        batch: Batch size for concurrent queries.

    Returns:
        Tuple of (gauntlet_rows, direct_rows) written.
    """
    _init()
    from block_utils import estimate_blocks, concurrent_query_batched

    conn = _ensure_db()

    # --- Check for rate changes first (back-recalculation) ---
    _check_and_recompute_rates(conn)

    # ========================================
    # Find last Gauntlet row from SQLite
    # ========================================
    last_g = _get_last_gauntlet(conn)
    if last_g is None:
        print("ERROR: No existing data in gauntlet_levered table.")
        conn.close()
        return 0, 0

    last_ts_g, last_block_g, prev_running_balance_g, last_tp_g = last_g
    print(f"Gauntlet last: ts={last_ts_g.strftime('%Y-%m-%d %H:%M')}, block={last_block_g}, "
          f"running_balance={prev_running_balance_g:,.2f}")

    # Determine time range
    if isinstance(start, str):
        start = datetime.strptime(start, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
    elif start is None:
        start = last_ts_g + timedelta(hours=1)

    if isinstance(end, str):
        end = datetime.strptime(end, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
    elif end is None:
        now = datetime.now(timezone.utc)
        end = now.replace(minute=0, second=0, microsecond=0)

    timestamps = []
    current = start
    while current <= end:
        timestamps.append(current)
        current += timedelta(hours=1)

    total = len(timestamps)
    if total == 0:
        print("No new rows to append.")
        conn.close()
        return 0, 0

    print(f"Period: {start.strftime('%Y-%m-%d %H:%M')} to {end.strftime('%Y-%m-%d %H:%M')} ({total} hours)")

    # ========================================
    # Pre-compute block numbers
    # ========================================
    t0 = time.time()

    ref_block = last_block_g
    ref_data = _w3.eth.get_block(ref_block)
    ref_ts = ref_data['timestamp']

    target_unix = [int(ts.timestamp()) for ts in timestamps]
    latest_block = _w3.eth.block_number
    estimated_blocks = estimate_blocks(ref_block, ref_ts, target_unix, chain="ethereum")
    estimated_blocks = [min(b, latest_block) for b in estimated_blocks]

    block_time = time.time() - t0
    print(f"Block estimation: {total} blocks in {block_time:.1f}s (2 RPC calls)")
    print(f"  Latest chain block: {latest_block}, estimated range: {estimated_blocks[0]}-{estimated_blocks[-1]}")

    # ========================================
    # Concurrent Multicall queries
    # ========================================
    t1 = time.time()

    def progress(done, total_items):
        elapsed = time.time() - t1
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total_items - done) / rate if rate > 0 else 0
        print(f"  Queried {done}/{total_items} | {rate:.1f}/s | ETA: {eta:.0f}s")

    print(f"Querying on-chain data ({workers} workers, batch {batch})...")

    results = concurrent_query_batched(
        query_fn=_query_at_block,
        items=estimated_blocks,
        batch_size=batch,
        max_workers=workers,
        pause_between_batches=0.3,
        progress_fn=progress,
    )

    query_time = time.time() - t1
    print(f"Query phase: {total} calls in {query_time:.1f}s ({total/query_time:.1f}/s)")

    # ========================================
    # Compute and write Gauntlet rows
    # ========================================
    prev_ts_g = last_ts_g
    gauntlet_rows = []

    for ts, block, data in zip(timestamps, estimated_blocks, results):
        coll, borrow, supply, tp = data
        net_rate = get_net_rate(ts)

        veris_pct = VERIS_GP_BALANCE / supply if supply > 0 else 0
        period_days = (ts - prev_ts_g).total_seconds() / 86400.0
        opening_value = prev_running_balance_g
        interest = opening_value * net_rate * period_days / 365.0
        running_balance = opening_value + interest
        tp_reengineered = running_balance / VERIS_AA_TOKENS_GAUNTLET if VERIS_AA_TOKENS_GAUNTLET > 0 else 0
        collateral_usd = coll * tp_reengineered
        net = collateral_usd - borrow
        veris_share = net * veris_pct

        gauntlet_rows.append((
            ts.strftime('%Y-%m-%d %H:%M:%S'),
            block, coll, borrow, supply, VERIS_GP_BALANCE, veris_pct,
            net_rate, VERIS_AA_TOKENS_GAUNTLET, tp,
            period_days, opening_value, interest, running_balance,
            tp_reengineered, collateral_usd, net, veris_share
        ))

        prev_running_balance_g = running_balance
        prev_ts_g = ts

    # TP change detection (before writing, so we can compare against last stored TP)
    _detect_tp_changes(conn, last_tp_g, gauntlet_rows)

    conn.executemany("""
        INSERT OR REPLACE INTO gauntlet_levered (
            timestamp_utc, block, collateral, borrow, vault_total_supply,
            veris_balance, veris_pct, net_rate, veris_aa_falconx, tranche_price,
            period_days, opening_value, interest, running_balance,
            tp_reengineered, collateral_usd, net, veris_share
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, gauntlet_rows)
    conn.commit()
    print(f"Gauntlet: {total} rows written to SQLite")

    # ========================================
    # Direct Accrual — with live on-chain TP
    # ========================================
    # Build TP lookup from Multicall results for per-timestamp accuracy
    tp_by_ts = {}
    latest_on_chain_tp = None
    for ts, data in zip(timestamps, results):
        tp_by_ts[ts] = data[3]  # on-chain TP
        latest_on_chain_tp = data[3]

    total_d = 0
    last_d = _get_last_direct(conn)
    if last_d is not None:
        last_ts_d, prev_running_balance_d = last_d
        print(f"\nDirect Accrual last: ts={last_ts_d.strftime('%Y-%m-%d %H:%M')}, "
              f"running_balance={prev_running_balance_d:,.2f}")

        da_start = last_ts_d + timedelta(hours=1)

        if da_start <= end:
            da_timestamps = []
            current = da_start
            while current <= end:
                da_timestamps.append(current)
                current += timedelta(hours=1)

            total_d = len(da_timestamps)
            print(f"Appending {total_d} rows to Direct Accrual")

            prev_ts_d = last_ts_d
            direct_rows = []

            for ts in da_timestamps:
                # Live on-chain TP — falls back to latest if timestamp not in Multicall batch
                tp_direct = tp_by_ts.get(ts, latest_on_chain_tp)
                if tp_direct is None:
                    # Edge case: no Multicall results at all (shouldn't happen)
                    tp_direct = 0.0

                net_rate = get_net_rate(ts)
                period_days = (ts - prev_ts_d).total_seconds() / 86400.0
                opening_value = prev_running_balance_d
                interest = opening_value * net_rate * period_days / 365.0
                running_balance = opening_value + interest
                tp_reengineered = running_balance / VERIS_AA_TOKENS_DIRECT if VERIS_AA_TOKENS_DIRECT > 0 else 0

                direct_rows.append((
                    ts.strftime('%Y-%m-%d %H:%M:%S'),
                    VERIS_AA_TOKENS_DIRECT, tp_direct,
                    opening_value, net_rate, period_days, interest,
                    running_balance, tp_reengineered
                ))

                prev_running_balance_d = running_balance
                prev_ts_d = ts

            conn.executemany("""
                INSERT OR REPLACE INTO direct_accrual (
                    timestamp_utc, token_balance, tranche_price,
                    opening_value, net_rate, period_days, interest,
                    running_balance, tp_reengineered
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, direct_rows)
            conn.commit()
            print(f"Direct Accrual: {total_d} rows written to SQLite")
        else:
            print("Direct Accrual already up to date.")
    else:
        print("\nDirect Accrual: no existing data in table.")

    conn.close()

    total_time = time.time() - t0
    print(f"\nSaved to {DB_PATH}")
    print(f"Total time: {total_time:.1f}s ({total/total_time:.1f} rows/s)")

    return total, total_d


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="Start UTC: YYYY-MM-DD-HH (default: last row + 1h)")
    parser.add_argument("--end", help="End UTC: YYYY-MM-DD-HH (default: current hour)")
    parser.add_argument("--workers", type=int, default=10, help="Concurrent RPC workers (10 optimal for Alchemy)")
    parser.add_argument("--batch", type=int, default=50, help="Batch size for concurrent queries")
    args = parser.parse_args()

    run_update(
        start=args.start,
        end=args.end,
        workers=args.workers,
        batch=args.batch,
    )


if __name__ == "__main__":
    main()
