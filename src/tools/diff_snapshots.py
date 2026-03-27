"""
Snapshot diff tool for Veris NAV system.

Compares two NAV snapshot directories and flags changes that may
indicate errors, missed positions, or unexpected movements.

Usage:
    python src/tools/diff_snapshots.py outputs/nav_20260330 outputs/nav_20260430
    python src/tools/diff_snapshots.py --latest     # compares two most recent snapshots
"""

import argparse
import csv
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "outputs")


def _parse_decimal(value):
    """Parse a string to Decimal, returning 0 on failure."""
    try:
        return Decimal(value or "0")
    except (InvalidOperation, ValueError):
        return Decimal(0)


def load_positions(snapshot_dir):
    """Load positions.csv from a snapshot directory. Returns dict keyed by position_id.

    If a position_id appears multiple times (e.g. duplicated category D entries),
    values and balances are summed. The first occurrence's metadata is kept.
    """
    csv_path = os.path.join(snapshot_dir, "positions.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"No positions.csv in {snapshot_dir}")

    positions = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = row["position_id"]
            row_value = _parse_decimal(row.get("value_usd"))
            row_balance = _parse_decimal(row.get("balance_human"))
            row_price = _parse_decimal(row.get("price_usd"))

            if pid in positions:
                # Duplicate position_id: sum value and balance, keep first row's metadata
                positions[pid]["_value"] += row_value
                positions[pid]["_balance"] += row_balance
            else:
                row["_value"] = row_value
                row["_balance"] = row_balance
                row["_price"] = row_price
                positions[pid] = row
    return positions


def load_summary(snapshot_dir):
    """Load nav_summary.json from a snapshot directory."""
    json_path = os.path.join(snapshot_dir, "nav_summary.json")
    if not os.path.exists(json_path):
        return None
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def find_latest_snapshots():
    """Find the two most recent snapshot directories."""
    output_dir = Path(OUTPUT_DIR).resolve()
    dirs = sorted(
        [d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("nav_")],
        key=lambda d: d.name,
        reverse=True,
    )
    if len(dirs) < 2:
        raise ValueError(f"Need at least 2 snapshot dirs in {output_dir}, found {len(dirs)}")
    return str(dirs[1]), str(dirs[0])  # previous, current


def pct_change(old, new):
    """Calculate percentage change. Returns None if old is zero."""
    if old == 0:
        return None
    return ((new - old) / abs(old)) * Decimal(100)


def diff_snapshots(prev_dir, curr_dir):
    """Compare two snapshots and return a structured diff report."""
    prev = load_positions(prev_dir)
    curr = load_positions(curr_dir)

    prev_ids = set(prev.keys())
    curr_ids = set(curr.keys())

    report = {
        "previous": os.path.basename(prev_dir),
        "current": os.path.basename(curr_dir),
        "new_positions": [],
        "disappeared_positions": [],
        "value_changes_gt_10pct": [],
        "price_source_changes": [],
        "zero_value_positions": [],
        "balance_changes_gt_50pct": [],
        "category_summary": {},
    }

    # New positions
    for pid in sorted(curr_ids - prev_ids):
        pos = curr[pid]
        report["new_positions"].append({
            "position_id": pid,
            "chain": pos.get("chain", ""),
            "protocol": pos.get("protocol", ""),
            "token_symbol": pos.get("token_symbol", ""),
            "category": pos.get("category", ""),
            "value_usd": str(pos["_value"]),
        })

    # Disappeared positions
    for pid in sorted(prev_ids - curr_ids):
        pos = prev[pid]
        report["disappeared_positions"].append({
            "position_id": pid,
            "chain": pos.get("chain", ""),
            "protocol": pos.get("protocol", ""),
            "token_symbol": pos.get("token_symbol", ""),
            "category": pos.get("category", ""),
            "prev_value_usd": str(pos["_value"]),
        })

    # Compare matching positions
    for pid in sorted(prev_ids & curr_ids):
        p, c = prev[pid], curr[pid]

        # Value change > 10% — use abs() on both sides to handle negative (debt) values
        pct = pct_change(p["_value"], c["_value"])
        if pct is not None and abs(pct) > 10:
            report["value_changes_gt_10pct"].append({
                "position_id": pid,
                "token_symbol": c.get("token_symbol", ""),
                "category": c.get("category", ""),
                "prev_value": str(p["_value"]),
                "curr_value": str(c["_value"]),
                "change_pct": f"{pct:+.1f}%",
            })

        # Price source changed
        if p.get("price_source", "") != c.get("price_source", ""):
            report["price_source_changes"].append({
                "position_id": pid,
                "token_symbol": c.get("token_symbol", ""),
                "prev_source": p.get("price_source", ""),
                "curr_source": c.get("price_source", ""),
            })

        # Balance change > 50% — compare absolute values to handle negative balances
        bal_pct = pct_change(p["_balance"], c["_balance"])
        if bal_pct is not None and abs(bal_pct) > 50:
            report["balance_changes_gt_50pct"].append({
                "position_id": pid,
                "token_symbol": c.get("token_symbol", ""),
                "prev_balance": str(p["_balance"]),
                "curr_balance": str(c["_balance"]),
                "change_pct": f"{bal_pct:+.1f}%",
            })

    # Zero-value positions in current snapshot
    # Include positions where value is exactly zero but balance is non-zero (pricing failure),
    # or where value is zero and position is not explicitly closed.
    for pid in sorted(curr.keys()):
        pos = curr[pid]
        if pos["_value"] == 0 and pos.get("position_type") != "closed":
            report["zero_value_positions"].append({
                "position_id": pid,
                "token_symbol": pos.get("token_symbol", ""),
                "category": pos.get("category", ""),
                "price_source": pos.get("price_source", ""),
                "balance_human": str(pos["_balance"]),
            })

    # Category summary — sums include negative values (debt positions)
    prev_by_cat = {}
    curr_by_cat = {}
    for pos in prev.values():
        cat = pos.get("category", "?")
        prev_by_cat[cat] = prev_by_cat.get(cat, Decimal(0)) + pos["_value"]
    for pos in curr.values():
        cat = pos.get("category", "?")
        curr_by_cat[cat] = curr_by_cat.get(cat, Decimal(0)) + pos["_value"]

    all_cats = sorted(set(list(prev_by_cat.keys()) + list(curr_by_cat.keys())))
    for cat in all_cats:
        p_val = prev_by_cat.get(cat, Decimal(0))
        c_val = curr_by_cat.get(cat, Decimal(0))
        delta = c_val - p_val
        pct = pct_change(p_val, c_val)
        report["category_summary"][cat] = {
            "previous": str(p_val),
            "current": str(c_val),
            "delta": str(delta),
            "change_pct": f"{pct:+.1f}%" if pct is not None else "N/A",
        }

    return report


def print_report(report):
    """Print a human-readable diff report to stdout."""
    print("=" * 80)
    print(f"NAV SNAPSHOT DIFF: {report['previous']} -> {report['current']}")
    print("=" * 80)

    # Critical: disappeared positions
    disappeared = report["disappeared_positions"]
    if disappeared:
        print(f"\n*** DISAPPEARED POSITIONS ({len(disappeared)}) ***")
        for p in disappeared:
            print(f"  MISSING  {p['position_id']}")
            print(f"           {p['token_symbol']} ({p['category']}) on {p['chain']}/{p['protocol']}")
            print(f"           Previous value: ${p['prev_value_usd']}")

    # New positions
    new = report["new_positions"]
    if new:
        print(f"\n+++ NEW POSITIONS ({len(new)}) +++")
        for p in new:
            print(f"  NEW      {p['position_id']}")
            print(f"           {p['token_symbol']} ({p['category']}) value: ${p['value_usd']}")

    # Zero-value positions
    zeros = report["zero_value_positions"]
    if zeros:
        print(f"\n!!! ZERO VALUE POSITIONS ({len(zeros)}) !!!")
        for p in zeros:
            print(f"  ZERO     {p['position_id']}")
            print(f"           {p['token_symbol']} ({p['category']}) balance={p['balance_human']} source={p['price_source']}")

    # Value changes > 10%
    changes = report["value_changes_gt_10pct"]
    if changes:
        print(f"\n~~~ VALUE CHANGES >10% ({len(changes)}) ~~~")
        for p in changes:
            print(f"  {p['change_pct']:>8s}  {p['token_symbol']} ({p['category']})")
            print(f"           ${p['prev_value']} -> ${p['curr_value']}")

    # Price source changes
    source_changes = report["price_source_changes"]
    if source_changes:
        print(f"\n--- PRICE SOURCE CHANGES ({len(source_changes)}) ---")
        for p in source_changes:
            print(f"  {p['token_symbol']}: {p['prev_source']} -> {p['curr_source']}")

    # Balance changes > 50%
    bal_changes = report["balance_changes_gt_50pct"]
    if bal_changes:
        print(f"\n--- BALANCE CHANGES >50% ({len(bal_changes)}) ---")
        for p in bal_changes:
            print(f"  {p['change_pct']:>8s}  {p['token_symbol']}")
            print(f"           {p['prev_balance']} -> {p['curr_balance']}")

    # Category summary table
    print(f"\n{'Category':<10} {'Previous':>16} {'Current':>16} {'Delta':>16} {'Change':>8}")
    print("-" * 70)
    cats = report["category_summary"]
    total_prev = Decimal(0)
    total_curr = Decimal(0)
    for cat in sorted(cats.keys()):
        c = cats[cat]
        p_val = Decimal(c["previous"])
        c_val = Decimal(c["current"])
        d_val = Decimal(c["delta"])
        total_prev += p_val
        total_curr += c_val
        print(f"  {cat:<8} {p_val:>16,.2f} {c_val:>16,.2f} {d_val:>+16,.2f} {c['change_pct']:>8}")
    print("-" * 70)
    total_delta = total_curr - total_prev
    total_pct = pct_change(total_prev, total_curr)
    pct_str = f"{total_pct:+.1f}%" if total_pct is not None else "N/A"
    print(f"  {'NET':<8} {total_prev:>16,.2f} {total_curr:>16,.2f} {total_delta:>+16,.2f} {pct_str:>8}")

    # Summary counts
    print(f"\nSummary: {len(new)} new, {len(disappeared)} disappeared, "
          f"{len(zeros)} zero-value, {len(changes)} value>10%, "
          f"{len(source_changes)} source changes, {len(bal_changes)} balance>50%")

    # Return exit code: non-zero if any critical issues
    if disappeared or zeros:
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="Compare two NAV snapshots")
    parser.add_argument("previous", nargs="?", help="Previous snapshot directory")
    parser.add_argument("current", nargs="?", help="Current snapshot directory")
    parser.add_argument("--latest", action="store_true", help="Compare the two most recent snapshots")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of human-readable")
    args = parser.parse_args()

    if args.latest:
        prev_dir, curr_dir = find_latest_snapshots()
    elif args.previous and args.current:
        prev_dir, curr_dir = args.previous, args.current
    else:
        parser.error("Provide two snapshot directories or use --latest")

    report = diff_snapshots(prev_dir, curr_dir)

    if args.json:
        # Write JSON report into the current snapshot directory
        json_path = os.path.join(curr_dir, "diff_report.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Diff report written to {json_path}")
    else:
        exit_code = print_report(report)
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
