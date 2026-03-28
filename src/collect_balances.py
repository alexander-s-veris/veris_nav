"""
Wallet balance query functions for the Veris NAV collection system.

Provides config loaders and per-chain balance scanners used by collect.py.
Each scanner queries token balances, filters against the token registry,
and returns raw balance rows (no pricing — valuation.py handles that).
"""

import json
import os
import sys
from decimal import Decimal
from datetime import datetime, timezone

import requests
from web3 import Web3

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from evm import CONFIG_DIR, TS_FMT, get_native_decimals


# --- Config loaders ---

def load_tokens_registry() -> dict:
    """Load config/tokens.json. Returns dict keyed by chain, then by lowered address."""
    with open(os.path.join(CONFIG_DIR, "tokens.json")) as f:
        registry = json.load(f)
    registry.pop("_template", None)
    return registry


def load_wallets() -> dict:
    """Load config/wallets.json."""
    with open(os.path.join(CONFIG_DIR, "wallets.json")) as f:
        return json.load(f)


# --- Shared ABI (from config/abis.json) ---

_ERC20_ABI = None


def _get_erc20_abi():
    """Load the ERC-20 ABI from config/abis.json (cached)."""
    global _ERC20_ABI
    if _ERC20_ABI is None:
        with open(os.path.join(CONFIG_DIR, "abis.json")) as f:
            abis = json.load(f)
        _ERC20_ABI = abis["erc20"]
    return _ERC20_ABI


# --- EVM Balance Queries ---

def query_balances_alchemy(w3: Web3, chain: str, wallet: str,
                           block_number: int, block_ts: str,
                           registry: dict) -> list[dict]:
    """Query native + ERC-20 balances via Alchemy, filter against registry."""
    rows = []
    checksum_wallet = Web3.to_checksum_address(wallet)
    chain_registry = registry.get(chain, {})
    native_decimals = get_native_decimals(chain)

    # Native balance
    native_wei = w3.eth.get_balance(checksum_wallet)
    native_balance = Decimal(native_wei) / Decimal(10 ** native_decimals)
    native_entry = chain_registry.get("native")

    if native_entry and native_balance > 0:
        rows.append(_build_row(
            wallet, chain, "native", native_entry, native_balance,
            block_number, block_ts))

    # ERC-20 balances via Alchemy
    try:
        response = w3.provider.make_request(
            "alchemy_getTokenBalances",
            [checksum_wallet, "erc20"],
        )
        token_balances = response.get("result", {}).get("tokenBalances", [])
    except Exception as e:
        print(f"  alchemy_getTokenBalances failed on {chain}: {e}")
        token_balances = []

    found_contracts = set()
    for tb in token_balances:
        raw_balance = int(tb.get("tokenBalance", "0x0"), 16)
        if raw_balance == 0:
            continue

        contract_addr = tb["contractAddress"].lower()
        token_entry = chain_registry.get(contract_addr)
        if token_entry is None:
            continue  # Not in registry — skip spam

        found_contracts.add(contract_addr)
        decimals = token_entry.get("decimals")
        if decimals is None:
            # Fetch from Alchemy metadata as last resort
            result = w3.provider.make_request("alchemy_getTokenMetadata", [tb["contractAddress"]])
            decimals = result.get("result", {}).get("decimals", 18) or 18

        human_balance = Decimal(raw_balance) / Decimal(10 ** decimals)
        rows.append(_build_row(
            wallet, chain, contract_addr, token_entry, human_balance,
            block_number, block_ts))

    # Fallback: batch balanceOf via Multicall3 for registry tokens not found by Alchemy
    from multicall import multicall, encode_balance_of, decode_uint256

    remaining = [
        (addr, entry) for addr, entry in chain_registry.items()
        if addr != "native" and addr not in found_contracts and isinstance(entry, dict)
    ]

    if remaining:
        calls = [(addr, encode_balance_of(checksum_wallet)) for addr, _ in remaining]
        results = multicall(w3, chain, calls, block_identifier=block_number)

        for (contract_addr, token_entry), (success, return_data) in zip(remaining, results):
            if not success or len(return_data) < 32:
                continue
            raw_balance = decode_uint256(return_data)
            if raw_balance == 0:
                continue
            decimals = token_entry.get("decimals", 18)
            human_balance = Decimal(raw_balance) / Decimal(10 ** decimals)
            rows.append(_build_row(
                wallet, chain, contract_addr, token_entry, human_balance,
                block_number, block_ts))

    return rows


def query_balances_etherscan(chain: str, chain_id: int, wallet: str,
                             registry: dict) -> list[dict]:
    """Query native + ERC-20 balances via Etherscan V2 API, filter against registry."""
    from evm import ETHERSCAN_V2_BASE
    etherscan_base = ETHERSCAN_V2_BASE
    rows = []
    api_key = os.getenv("ETHERSCAN_API_KEY")
    chain_registry = registry.get(chain, {})
    native_decimals = get_native_decimals(chain)

    # Get block info via Etherscan proxy
    block_number = "N/A"
    block_ts = "N/A"
    try:
        resp = requests.get(etherscan_base, params={
            "chainid": chain_id, "module": "proxy",
            "action": "eth_blockNumber", "apikey": api_key,
        }, timeout=10)
        data = resp.json()
        if data.get("result"):
            block_number = str(int(data["result"], 16))
            resp2 = requests.get(etherscan_base, params={
                "chainid": chain_id, "module": "proxy",
                "action": "eth_getBlockByNumber",
                "tag": data["result"], "boolean": "false", "apikey": api_key,
            }, timeout=10)
            block_data = resp2.json()
            if block_data.get("result", {}).get("timestamp"):
                ts = int(block_data["result"]["timestamp"], 16)
                block_ts = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(TS_FMT)
    except Exception:
        pass

    # Native balance
    native_entry = chain_registry.get("native")
    try:
        resp = requests.get(etherscan_base, params={
            "chainid": chain_id, "module": "account", "action": "balance",
            "address": wallet, "tag": "latest", "apikey": api_key,
        }, timeout=10)
        data = resp.json()
        if data.get("status") == "1" and native_entry:
            native_wei = int(data["result"])
            native_balance = Decimal(native_wei) / Decimal(10 ** native_decimals)
            if native_balance > 0:
                rows.append(_build_row(
                    wallet, chain, "native", native_entry, native_balance,
                    block_number, block_ts))
    except Exception:
        pass

    # ERC-20 tokens via Etherscan V2
    page = 1
    while True:
        try:
            resp = requests.get(etherscan_base, params={
                "chainid": chain_id, "module": "account",
                "action": "addresstokenbalance",
                "address": wallet, "page": page, "offset": 10000, "apikey": api_key,
            }, timeout=10)
            data = resp.json()
        except Exception:
            break

        if data.get("status") != "1" or not data.get("result"):
            break

        for token in data["result"]:
            raw_balance = int(token.get("TokenQuantity", "0"))
            if raw_balance == 0:
                continue

            contract_addr = token.get("TokenAddress", "").lower()
            token_entry = chain_registry.get(contract_addr)
            if token_entry is None:
                continue

            decimals = token_entry.get("decimals", int(token.get("TokenDivisor", "18")))
            human_balance = Decimal(raw_balance) / Decimal(10 ** decimals)
            rows.append(_build_row(
                wallet, chain, contract_addr, token_entry, human_balance,
                block_number, block_ts))

        if len(data["result"]) < 10000:
            break
        page += 1

    # Fallback: direct balanceOf via Etherscan proxy for registry tokens not found
    found_contracts = {r["token_contract"] for r in rows if r["token_contract"] != "native"}
    for contract_addr, token_entry in chain_registry.items():
        if contract_addr == "native" or contract_addr in found_contracts:
            continue
        if not isinstance(token_entry, dict):
            continue
        try:
            # balanceOf(address) function selector = 0x70a08231
            call_data = "0x70a08231" + wallet[2:].lower().zfill(64)
            resp = requests.get(etherscan_base, params={
                "chainid": chain_id, "module": "proxy", "action": "eth_call",
                "to": contract_addr, "data": call_data, "tag": "latest",
                "apikey": api_key,
            }, timeout=10)
            result = resp.json()
            if result.get("result") and result["result"] != "0x":
                raw_balance = int(result["result"], 16)
                if raw_balance == 0:
                    continue
                decimals = token_entry.get("decimals", 18)
                human_balance = Decimal(raw_balance) / Decimal(10 ** decimals)
                rows.append(_build_row(
                    wallet, chain, contract_addr, token_entry, human_balance,
                    block_number, block_ts))
        except Exception:
            pass

    return rows


# --- Solana Balance Query ---

def query_balances_solana(wallet: str, registry: dict,
                          slot_override: tuple = None) -> list[dict]:
    """Query native SOL + SPL token balances via Solana RPC.

    Args:
        wallet: Solana wallet address.
        registry: Token registry dict.
        slot_override: Optional (slot, block_ts_str) tuple for Valuation Block
                       pinning. If None, uses latest slot.
    """
    from solana_client import get_solana_rpc_url, SPL_TOKEN_PROGRAM_ID

    rows = []
    solana_registry = registry.get("solana", {})
    rpc_url = get_solana_rpc_url()
    native_decimals = get_native_decimals("solana")

    def rpc_call(method: str, params: list) -> dict:
        resp = requests.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
        }, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # Get slot (Solana's equivalent of block number)
    if slot_override:
        slot, block_ts = slot_override
    else:
        try:
            slot_resp = rpc_call("getSlot", [])
            slot = slot_resp.get("result", "N/A")
            time_resp = rpc_call("getBlockTime", [slot])
            block_time = time_resp.get("result")
            block_ts = datetime.fromtimestamp(block_time, tz=timezone.utc).strftime(TS_FMT) if block_time else "N/A"
        except Exception:
            slot = "N/A"
            block_ts = "N/A"

    # Native SOL balance
    native_entry = solana_registry.get("native")
    try:
        bal_resp = rpc_call("getBalance", [wallet])
        lamports = bal_resp.get("result", {}).get("value", 0)
        sol_balance = Decimal(lamports) / Decimal(10 ** native_decimals)
        if native_entry and sol_balance > 0:
            rows.append(_build_row(
                wallet, "solana", "native", native_entry, sol_balance,
                str(slot), block_ts))
    except Exception as e:
        print(f"  Solana native balance failed: {e}")

    # SPL token accounts
    try:
        token_resp = rpc_call("getTokenAccountsByOwner", [
            wallet,
            {"programId": SPL_TOKEN_PROGRAM_ID},
            {"encoding": "jsonParsed"},
        ])
        accounts = token_resp.get("result", {}).get("value", [])
    except Exception as e:
        print(f"  Solana SPL token query failed: {e}")
        accounts = []

    for account in accounts:
        parsed = account.get("account", {}).get("data", {}).get("parsed", {})
        info = parsed.get("info", {})
        mint = info.get("mint", "").lower()
        token_amount = info.get("tokenAmount", {})

        raw_amount = int(token_amount.get("amount", "0"))
        if raw_amount == 0:
            continue

        # Solana mint addresses are case-sensitive, but we lowercase in registry
        token_entry = solana_registry.get(mint)
        if token_entry is None:
            token_entry = solana_registry.get(info.get("mint", ""))
        if token_entry is None:
            continue

        decimals = token_entry.get("decimals", int(token_amount.get("decimals", 9)))
        human_balance = Decimal(raw_amount) / Decimal(10 ** decimals)
        rows.append(_build_row(
            wallet, "solana", info.get("mint", mint), token_entry, human_balance,
            str(slot), block_ts))

    return rows


# --- Shared row builder ---

def _build_row(wallet, chain, contract, entry, balance, block_number, block_ts):
    """Build a standardised balance row dict."""
    return {
        "wallet": wallet,
        "chain": chain,
        "token_contract": contract,
        "token_symbol": entry.get("symbol", "UNKNOWN"),
        "token_name": entry.get("name", ""),
        "category": entry.get("category", ""),
        "balance": balance,
        "block_number": block_number,
        "block_timestamp_utc": block_ts,
        "_registry_entry": entry,
    }
