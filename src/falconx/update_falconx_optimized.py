"""
Optimized FalconX/Pareto position updater.

Uses block pre-computation (Option 1) and concurrent RPC queries (Option 4)
from src/block_utils.py. Typically 5-8x faster than the serial approach.

Writes to data/falconx.db (SQLite). All values computed in Python — no formulas.

Usage:
    python src/falconx/update_falconx_optimized.py [--start YYYY-MM-DD-HH] [--end YYYY-MM-DD-HH]

Defaults: start = last timestamp in SQLite + 1 hour, end = now (rounded down to hour).
"""
import sys
import os
import time
import argparse
import sqlite3
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from web3 import Web3

# Load .env
with open(os.path.join(os.path.dirname(__file__), '..', '..', '.env')) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from evm import get_web3
from block_utils import estimate_blocks, concurrent_query_batched

w3 = get_web3("ethereum")

# --- Contracts ---
MULTICALL3 = w3.to_checksum_address("0xcA11bde05977b3631167028862bE2a173976CA11")
MORPHO = w3.to_checksum_address("0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb")
GAUNTLET = w3.to_checksum_address("0x00000000d8f3d6c5DFeB2D2b5ED2276095f3aF44")
MARKET_ID = bytes.fromhex("e83d72fa5b00dcd46d9e0e860d95aa540d5ec106da5833108a9f826f21f36f52")
PARETO = w3.to_checksum_address("0x433d5b175148da32ffe1e1a37a939e1b7e79be4d")
TRANCHE_ADDR = w3.to_checksum_address("0xC26A6Fa2C37b38E549a4a1807543801Db684f99C")

# --- Constants ---
VERIS_GP_BALANCE = 2507114.7845223
VERIS_AA_TOKENS_GAUNTLET = 2473068.8259
VERIS_AA_TOKENS_DIRECT = 1894969.859499
DIRECT_OPENING_VALUE = 2024989.2306  # Actual USDC deposited (not tokens × stale TP)

# Loan notice schedule: (start_date_utc, gross_rate)
RATE_SCHEDULE = [
    (datetime(2025, 6, 30, tzinfo=timezone.utc), 0.1125),
    (datetime(2025, 7, 31, tzinfo=timezone.utc), 0.1125),
    (datetime(2025, 9,  1, tzinfo=timezone.utc), 0.1200),
    (datetime(2025, 10, 1, tzinfo=timezone.utc), 0.1200),
    (datetime(2025, 11, 1, tzinfo=timezone.utc), 0.1200),
    (datetime(2025, 12, 1, tzinfo=timezone.utc), 0.1150),
    (datetime(2026, 1,  1, tzinfo=timezone.utc), 0.1050),
    (datetime(2026, 2,  1, tzinfo=timezone.utc), 0.1000),
    (datetime(2026, 3,  3, tzinfo=timezone.utc), 0.0925),
]

def get_net_rate(ts):
    """Get net rate for a given timestamp from loan notice schedule."""
    rate = RATE_SCHEDULE[0][1]
    for start, r in RATE_SCHEDULE:
        if ts >= start:
            rate = r
    return rate * 0.90

# --- Calldata (pre-built, no per-call overhead) ---
POS_SIG = Web3.keccak(text="position(bytes32,address)")[:4]
POS_CALL = POS_SIG + MARKET_ID + bytes.fromhex(GAUNTLET[2:].lower()).rjust(32, b'\x00')
MKT_SIG = Web3.keccak(text="market(bytes32)")[:4]
MKT_CALL = MKT_SIG + MARKET_ID
SUP_SIG = Web3.keccak(text="totalSupply()")[:4]
SUP_CALL = SUP_SIG
TP_SIG = Web3.keccak(text="tranchePrice(address)")[:4]
TP_CALL = TP_SIG + bytes.fromhex(TRANCHE_ADDR[2:].lower()).rjust(32, b'\x00')

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
mc = w3.eth.contract(address=MULTICALL3, abi=MC_ABI)

DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'falconx.db')


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
    conn.commit()
    return conn


def _get_last_gauntlet(conn):
    """Get last row from gauntlet_levered. Returns (timestamp_utc, block, running_balance) or None."""
    row = conn.execute(
        "SELECT timestamp_utc, block, running_balance FROM gauntlet_levered ORDER BY timestamp_utc DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    ts = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    return ts, int(row[1]), row[2]


def _get_last_direct(conn):
    """Get last row from direct_accrual. Returns (timestamp_utc, running_balance) or None."""
    row = conn.execute(
        "SELECT timestamp_utc, running_balance FROM direct_accrual ORDER BY timestamp_utc DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    ts = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    return ts, row[1]


def query_at_block(block):
    """Multicall query at a given block. Returns (coll, borrow, supply, tp)."""
    calls = [
        (MORPHO, POS_CALL),
        (MORPHO, MKT_CALL),
        (GAUNTLET, SUP_CALL),
        (PARETO, TP_CALL),
    ]
    _, data = mc.functions.aggregate(calls).call(block_identifier=block)

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", help="Start UTC: YYYY-MM-DD-HH (default: last row + 1h)")
    parser.add_argument("--end", help="End UTC: YYYY-MM-DD-HH (default: current hour)")
    parser.add_argument("--workers", type=int, default=10, help="Concurrent RPC workers (10 optimal for Alchemy)")
    parser.add_argument("--batch", type=int, default=50, help="Batch size for concurrent queries")
    args = parser.parse_args()

    conn = _ensure_db()

    # ========================================
    # Find last Gauntlet row from SQLite
    # ========================================
    last_g = _get_last_gauntlet(conn)
    if last_g is None:
        print("ERROR: No existing data in gauntlet_levered table.")
        print("Run import_falconx_xlsx_to_sqlite.py first to seed the database.")
        conn.close()
        return

    last_ts_g, last_block_g, prev_running_balance_g = last_g
    print(f"Gauntlet last: ts={last_ts_g.strftime('%Y-%m-%d %H:%M')}, block={last_block_g}, running_balance={prev_running_balance_g:,.2f}")

    # Determine time range
    if args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
    else:
        start = last_ts_g + timedelta(hours=1)

    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
    else:
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
        return

    print(f"Period: {start.strftime('%Y-%m-%d %H:%M')} to {end.strftime('%Y-%m-%d %H:%M')} ({total} hours)")

    # ========================================
    # Option 1: Pre-compute block numbers
    # ========================================
    t0 = time.time()

    # Get reference: last known block + its timestamp
    ref_block = last_block_g
    ref_data = w3.eth.get_block(ref_block)
    ref_ts = ref_data['timestamp']

    target_unix = [int(ts.timestamp()) for ts in timestamps]
    latest_block = w3.eth.block_number
    estimated_blocks = estimate_blocks(ref_block, ref_ts, target_unix, chain="ethereum")
    # Cap at latest block (can't query future blocks)
    estimated_blocks = [min(b, latest_block) for b in estimated_blocks]

    block_time = time.time() - t0
    print(f"Block estimation: {total} blocks in {block_time:.1f}s (2 RPC calls)")
    print(f"  Latest chain block: {latest_block}, estimated range: {estimated_blocks[0]}-{estimated_blocks[-1]}")

    # ========================================
    # Option 4: Concurrent Multicall queries
    # ========================================
    t1 = time.time()

    def progress(done, total_items):
        elapsed = time.time() - t1
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total_items - done) / rate if rate > 0 else 0
        print(f"  Queried {done}/{total_items} | {rate:.1f}/s | ETA: {eta:.0f}s")

    print(f"Querying on-chain data ({args.workers} workers, batch {args.batch})...")

    results = concurrent_query_batched(
        query_fn=query_at_block,
        items=estimated_blocks,
        batch_size=args.batch,
        max_workers=args.workers,
        pause_between_batches=0.3,
        progress_fn=progress,
    )

    query_time = time.time() - t1
    print(f"Query phase: {total} calls in {query_time:.1f}s ({total/query_time:.1f}/s)")

    # ========================================
    # Compute and write Gauntlet rows to SQLite
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
    # Direct Accrual — append if active
    # ========================================
    last_d = _get_last_direct(conn)
    if last_d is not None:
        last_ts_d, prev_running_balance_d = last_d
        print(f"\nDirect Accrual last: ts={last_ts_d.strftime('%Y-%m-%d %H:%M')}, running_balance={prev_running_balance_d:,.2f}")

        da_start = last_ts_d + timedelta(hours=1)

        if da_start <= end:
            da_timestamps = []
            current = da_start
            while current <= end:
                da_timestamps.append(current)
                current += timedelta(hours=1)

            total_d = len(da_timestamps)
            print(f"Appending {total_d} rows to Direct Accrual")

            tp_direct = 1.067961  # TP unchanged since Mar 3
            prev_ts_d = last_ts_d
            direct_rows = []

            for ts in da_timestamps:
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


if __name__ == "__main__":
    main()
