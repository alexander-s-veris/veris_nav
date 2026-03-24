"""
Test script: Query all balances (native + ERC-20 tokens) for a wallet
across all EVM chains defined in config/chains.json.

Uses Alchemy endpoints for most chains, Etherscan V2 API for chains
without Alchemy support (e.g. Plasma).
"""

import os
import csv
import json
import requests
from decimal import Decimal
from datetime import datetime, timezone

from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

load_dotenv()

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")
TS_FMT = "%d/%m/%Y %H:%M:%S"

WALLET = "0xa33e1f748754d2d624638ab335100d92fcbe62a2"

ETHERSCAN_V2_BASE = "https://api.etherscan.io/v2/api"

OUTPUT_FIELDS = [
    "wallet",
    "chain",
    "token_contract",
    "token_symbol",
    "token_name",
    "balance",
    "block_number",
    "block_timestamp_utc",
]

# Native token name per chain
NATIVE_TOKEN = {
    "ethereum": "ETH",
    "arbitrum": "ETH",
    "base": "ETH",
    "avalanche": "AVAX",
    "plasma": "XPL",
}


def load_chains() -> dict:
    with open(os.path.join(CONFIG_DIR, "chains.json")) as f:
        return json.load(f)


def get_rpc_url(chain: str) -> str:
    """Build RPC URL for a chain using config/chains.json.

    Chains with rpc_url_template use Alchemy API key substitution.
    Chains with rpc_env_var read a full URL from .env.
    """
    chains = load_chains()
    if chain not in chains:
        raise ValueError(f"Unknown chain: {chain}")
    cfg = chains[chain]
    if "rpc_env_var" in cfg:
        return os.getenv(cfg["rpc_env_var"])
    api_key = os.getenv("ALCHEMY_API_KEY")
    return cfg["rpc_url_template"].format(api_key=api_key)


def get_token_metadata(w3: Web3, contract_address: str) -> dict:
    """Fetch token symbol and decimals via Alchemy's alchemy_getTokenMetadata."""
    result = w3.provider.make_request(
        "alchemy_getTokenMetadata",
        [contract_address],
    )
    data = result.get("result", {})
    return {
        "symbol": data.get("symbol", "UNKNOWN"),
        "decimals": data.get("decimals", 18),
        "name": data.get("name", ""),
    }


def make_row(wallet: str, chain: str, contract: str, symbol: str, name: str,
             balance: Decimal, block_number: str = "N/A", block_ts: str = "N/A") -> dict:
    return {
        "wallet": wallet,
        "chain": chain,
        "token_contract": contract,
        "token_symbol": symbol,
        "token_name": name,
        "balance": str(balance),
        "block_number": block_number,
        "block_timestamp_utc": block_ts,
    }


def query_chain_alchemy(chain: str, wallet: str) -> list[dict]:
    """Query native + all ERC-20 balances via Alchemy RPC."""
    rows = []
    rpc_url = get_rpc_url(chain)
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    # PoA chains (e.g. Avalanche) have oversized extraData fields
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not w3.is_connected():
        print(f"  SKIP {chain} — cannot connect")
        return rows

    block_number = w3.eth.block_number
    block_data = w3.eth.get_block(block_number)
    block_ts = datetime.fromtimestamp(block_data["timestamp"], tz=timezone.utc).strftime(TS_FMT)
    checksum_wallet = Web3.to_checksum_address(wallet)

    # 1. Native balance
    native_wei = w3.eth.get_balance(checksum_wallet)
    native_balance = Decimal(native_wei) / Decimal(10**18)
    native_symbol = NATIVE_TOKEN.get(chain, "ETH")

    rows.append(make_row(wallet, chain, "ETH", native_symbol, native_symbol, native_balance,
                         str(block_number), block_ts))
    if native_balance > 0:
        print(f"  {native_symbol}: {native_balance}")

    # 2. All ERC-20 token balances via Alchemy
    try:
        response = w3.provider.make_request(
            "alchemy_getTokenBalances",
            [checksum_wallet, "erc20"],
        )
        token_balances = response.get("result", {}).get("tokenBalances", [])
    except Exception as e:
        print(f"  alchemy_getTokenBalances failed: {e}")
        token_balances = []

    for tb in token_balances:
        hex_balance = tb.get("tokenBalance", "0x0")
        raw_balance = int(hex_balance, 16)

        if raw_balance == 0:
            continue

        contract_addr = tb["contractAddress"]
        metadata = get_token_metadata(w3, contract_addr)
        decimals = metadata["decimals"] or 18
        human_balance = Decimal(raw_balance) / Decimal(10**decimals)

        rows.append(make_row(
            wallet, chain, contract_addr,
            metadata["symbol"], metadata["name"], human_balance,
            str(block_number), block_ts,
        ))

        symbol_safe = metadata["symbol"].encode("ascii", errors="replace").decode()
        print(f"  {symbol_safe}: {human_balance}")

    return rows


def query_chain_etherscan(chain: str, chain_id: int, wallet: str) -> list[dict]:
    """Query native + all ERC-20 balances via Etherscan V2 API."""
    rows = []
    api_key = os.getenv("ETHERSCAN_API_KEY")

    # Get latest block number and timestamp
    block_number = "N/A"
    block_ts = "N/A"
    resp = requests.get(ETHERSCAN_V2_BASE, params={
        "chainid": chain_id,
        "module": "proxy",
        "action": "eth_blockNumber",
        "apikey": api_key,
    })
    data = resp.json()
    if data.get("result"):
        block_number = str(int(data["result"], 16))
        # Get block timestamp
        resp = requests.get(ETHERSCAN_V2_BASE, params={
            "chainid": chain_id,
            "module": "proxy",
            "action": "eth_getBlockByNumber",
            "tag": data["result"],
            "boolean": "false",
            "apikey": api_key,
        })
        block_data = resp.json()
        if block_data.get("result", {}).get("timestamp"):
            ts = int(block_data["result"]["timestamp"], 16)
            block_ts = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(TS_FMT)

    # 1. Native balance
    resp = requests.get(ETHERSCAN_V2_BASE, params={
        "chainid": chain_id,
        "module": "account",
        "action": "balance",
        "address": wallet,
        "tag": "latest",
        "apikey": api_key,
    })
    data = resp.json()
    if data.get("status") == "1":
        native_wei = int(data["result"])
        native_balance = Decimal(native_wei) / Decimal(10**18)
        native_symbol = NATIVE_TOKEN.get(chain, "ETH")

        rows.append(make_row(wallet, chain, "ETH", native_symbol, native_symbol, native_balance,
                             block_number, block_ts))
        if native_balance > 0:
            print(f"  {native_symbol}: {native_balance}")
    else:
        print(f"  Native balance query failed: {data.get('message')}")

    # 2. All ERC-20 token holdings via Etherscan V2
    page = 1
    while True:
        resp = requests.get(ETHERSCAN_V2_BASE, params={
            "chainid": chain_id,
            "module": "account",
            "action": "addresstokenbalance",
            "address": wallet,
            "page": page,
            "offset": 100,
            "apikey": api_key,
        })
        data = resp.json()

        if data.get("status") != "1" or not data.get("result"):
            if page == 1:
                print(f"  Token balance query: {data.get('message', 'no tokens')}")
            break

        for token in data["result"]:
            raw_balance = int(token.get("TokenQuantity", "0"))
            if raw_balance == 0:
                continue

            decimals = int(token.get("TokenDivisor", "18"))
            human_balance = Decimal(raw_balance) / Decimal(10**decimals)
            symbol = token.get("TokenSymbol", "UNKNOWN")

            rows.append(make_row(
                wallet, chain, token.get("TokenAddress", ""),
                symbol, token.get("TokenName", ""), human_balance,
                block_number, block_ts,
            ))

            symbol_safe = symbol.encode("ascii", errors="replace").decode()
            print(f"  {symbol_safe}: {human_balance}")

        if len(data["result"]) < 100:
            break
        page += 1

    return rows


def main():
    request_ts = datetime.now(timezone.utc)
    chains = load_chains()
    evm_chains = [name for name, cfg in chains.items() if "chain_id" in cfg]

    print(f"Querying wallet {WALLET}")
    print(f"Chains: {', '.join(evm_chains)}\n")

    all_rows = []
    for chain in evm_chains:
        print(f"[{chain}]")
        cfg = chains[chain]

        if cfg.get("token_balance_method") == "etherscan_v2":
            rows = query_chain_etherscan(chain, cfg["chain_id"], WALLET)
        else:
            rows = query_chain_alchemy(chain, WALLET)

        all_rows.extend(rows)
        if not rows:
            print("  (no balances)")
        print()

    # Write outputs
    json_path = os.path.join(OUTPUT_DIR, "test_balances.json")
    csv_path = os.path.join(OUTPUT_DIR, "test_balances.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2)
    print(f"JSON written: {json_path}")

    if all_rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"CSV  written: {csv_path}")

    print(f"\nTotal: {len(all_rows)} non-zero balances across {len(evm_chains)} chains")


if __name__ == "__main__":
    main()
