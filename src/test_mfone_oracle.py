"""
Test script: Query the mF-ONE/USD Chainlink-style oracle on Ethereum.

Oracle contract: 0x8D51DBC85cEef637c97D02bdaAbb5E274850e68C
Uses AggregatorV3Interface — latestRoundData() + decimals()
"""

import os
import csv
import json
from decimal import Decimal
from datetime import datetime, timezone

from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

# --- Config ---
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")
TS_FMT = "%d/%m/%Y %H:%M:%S"

MFONE_ORACLE = "0x8D51DBC85cEef637c97D02bdaAbb5E274850e68C"

AGGREGATOR_V3_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "description",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def get_rpc_url(chain: str) -> str:
    """Build RPC URL for a chain using config/chains.json."""
    with open(os.path.join(CONFIG_DIR, "chains.json")) as f:
        chains = json.load(f)
    if chain not in chains:
        raise ValueError(f"Unknown chain: {chain}")
    cfg = chains[chain]
    if "rpc_env_var" in cfg:
        return os.getenv(cfg["rpc_env_var"])
    api_key = os.getenv("ALCHEMY_API_KEY")
    return cfg["rpc_url_template"].format(api_key=api_key)


def main():
    request_ts = datetime.now(timezone.utc)

    w3 = Web3(Web3.HTTPProvider(get_rpc_url("ethereum")))

    if not w3.is_connected():
        print("ERROR: Cannot connect to Ethereum RPC. Check your ALCHEMY_API_KEY in .env")
        return

    block_number = w3.eth.block_number
    block_data = w3.eth.get_block(block_number)
    block_timestamp_utc = datetime.fromtimestamp(block_data["timestamp"], tz=timezone.utc)
    print(f"Connected to Ethereum — latest block: {block_number}")

    oracle = w3.eth.contract(
        address=Web3.to_checksum_address(MFONE_ORACLE),
        abi=AGGREGATOR_V3_ABI,
    )

    decimals = oracle.functions.decimals().call()
    description = oracle.functions.description().call()

    round_id, answer, started_at, updated_at, answered_in_round = (
        oracle.functions.latestRoundData().call()
    )

    price = Decimal(answer) / Decimal(10**decimals)
    started_at_utc = datetime.fromtimestamp(started_at, tz=timezone.utc)
    updated_at_utc = datetime.fromtimestamp(updated_at, tz=timezone.utc)

    row = {
        "feed": description,
        "contract": MFONE_ORACLE,
        "price_usd": str(price),
        "raw_answer": answer,
        "decimals": decimals,
        "round_id": round_id,
        "block_number": block_number,
        "block_timestamp_utc": block_timestamp_utc.strftime(TS_FMT),
        "request_timestamp_utc": request_ts.strftime(TS_FMT),
        "started_at_utc": started_at_utc.strftime(TS_FMT),
        "updated_at_utc": updated_at_utc.strftime(TS_FMT),
    }

    # Print summary
    print(f"Feed:               {description}")
    print(f"Price:              ${price}")
    print(f"Block:              {block_number}")
    print(f"Block timestamp:    {block_timestamp_utc.strftime(TS_FMT)}")
    print(f"Request timestamp:  {request_ts.strftime(TS_FMT)}")
    print(f"StartedAt UTC:      {started_at_utc.strftime(TS_FMT)}")
    print(f"UpdatedAt UTC:      {updated_at_utc.strftime(TS_FMT)}")

    # Write outputs
    file_stem = "test_mfone"
    json_path = os.path.join(OUTPUT_DIR, f"{file_stem}.json")
    csv_path = os.path.join(OUTPUT_DIR, f"{file_stem}.csv")

    with open(json_path, "w") as f:
        json.dump(row, f, indent=2)
    print(f"\nJSON written: {json_path}")

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)
    print(f"CSV  written: {csv_path}")


if __name__ == "__main__":
    main()
