"""
Query full history of Pareto FalconX tranche price updates.

Method:
1. Fetch ALL transactions to the Pareto Credit Vault contract via Etherscan
2. Query tranchePrice(tranche_address) at each unique block
3. Identify price changes (method 0xb4ecd47f is the price update function)

Contracts:
- Pareto Credit Vault: 0x433d5b175148da32ffe1e1a37a939e1b7e79be4d
- AA_FalconXUSDC Tranche: 0xC26A6Fa2C37b38E549a4a1807543801Db684f99C
- Function: tranchePrice(address) → uint256 (6 decimals)
- Price update method: 0xb4ecd47f

Usage:
    python src/falconx/query_pareto_tranche_history.py
"""
import sys
import os
import json
import csv
import requests
from datetime import datetime, timezone
from decimal import Decimal

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(SRC_DIR)

sys.path.insert(0, SRC_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

from evm import get_web3

PARETO = "0x433d5b175148da32ffe1e1a37a939e1b7e79be4d"
TRANCHE = "0xC26A6Fa2C37b38E549a4a1807543801Db684f99C"
ETHERSCAN_KEY = os.environ.get("ETHERSCAN_API_KEY")

ABI = [{"inputs": [{"name": "", "type": "address"}], "name": "tranchePrice",
        "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]


def fmt(val, dec):
    return Decimal(str(val)) / Decimal(10 ** dec)


def main():
    w3 = get_web3("ethereum")
    contract = w3.eth.contract(address=w3.to_checksum_address(PARETO), abi=ABI)
    tranche_addr = w3.to_checksum_address(TRANCHE)

    # Step 1: Fetch all transactions to the contract
    resp = requests.get("https://api.etherscan.io/v2/api", params={
        "chainid": 1, "module": "account", "action": "txlist",
        "address": PARETO, "startblock": 0, "endblock": 99999999,
        "sort": "asc", "apikey": ETHERSCAN_KEY,
    })
    txs = resp.json()["result"]
    print(f"Total transactions to contract: {len(txs)}")

    # Step 2: Query price at each unique block
    seen_blocks = set()
    price_history = []

    for tx in txs:
        if tx["isError"] != "0":
            continue
        block = int(tx["blockNumber"])
        if block in seen_blocks:
            continue
        seen_blocks.add(block)

        ts = datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)
        method = tx["input"][:10]

        try:
            price_raw = contract.functions.tranchePrice(tranche_addr).call(block_identifier=block)
            price = fmt(price_raw, 6)
            price_history.append({
                "date": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "block": block,
                "method": method,
                "price_raw": int(price_raw),
                "price": price,
            })
        except Exception as e:
            print(f"  Error at block {block}: {e}")

    # Step 3: Extract only the price changes
    inception_date = None
    inception_price = None
    changes = []

    prev_price = None
    for entry in price_history:
        if prev_price is None or entry["price"] != prev_price:
            if inception_date is None:
                inception_date = datetime.strptime(entry["date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                inception_price = entry["price"]

            change = entry["price"] - prev_price if prev_price is not None else Decimal(0)

            # Annualised rate from inception
            current_date = datetime.strptime(entry["date"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            days_since_inception = (current_date - inception_date).days if inception_date else 0
            if days_since_inception > 0 and inception_price > 0:
                total_return = float(entry["price"] / inception_price - 1)
                annualised = total_return * 365.0 / days_since_inception
            else:
                annualised = 0.0

            changes.append({
                "date": entry["date"],
                "block": entry["block"],
                "price": str(entry["price"]),
                "change": str(change),
                "days_since_inception": days_since_inception,
                "total_return_pct": f"{float(entry['price'] / inception_price - 1) * 100:.4f}" if inception_price and days_since_inception > 0 else "0",
                "annualised_rate_pct": f"{annualised * 100:.2f}",
            })
            prev_price = entry["price"]

    # Print summary
    print(f"\n{'Date':<22} {'Block':<12} {'Price':>10} {'Change':>10} {'Days':>6} {'Total %':>10} {'Ann. %':>8}")
    print("-" * 82)
    for c in changes:
        print(f"{c['date']:<22} {c['block']:<12} {c['price']:>10} {c['change']:>10} {c['days_since_inception']:>6} {c['total_return_pct']:>10} {c['annualised_rate_pct']:>8}")

    # Step 4: Save to outputs
    output_dir = os.path.join(PROJECT_DIR, "outputs")
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, "pareto_tranche_price_history.json")
    with open(output_path, "w") as f:
        json.dump({
            "contract": PARETO,
            "tranche": TRANCHE,
            "function": "tranchePrice(address) → uint256 (6 decimals)",
            "price_update_method": "0xb4ecd47f",
            "query_method": "Etherscan txlist → query tranchePrice at each block",
            "queried_at_utc": datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S"),
            "update_pattern": "Monthly (end-of-month), ~28-32 day intervals",
            "staleness_threshold_days": 45,
            "price_updates": changes,
        }, f, indent=2)
    print(f"\nSaved to {output_path}")

    csv_path = os.path.join(output_dir, "pareto_tranche_price_history.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=changes[0].keys())
        writer.writeheader()
        writer.writerows(changes)
    print(f"Saved to {csv_path}")


if __name__ == "__main__":
    main()
