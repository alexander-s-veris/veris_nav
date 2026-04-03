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

def query_evm_balances(w3: Web3, chain: str, wallet: str,
                       block_number: int, block_ts: str,
                       registry: dict) -> list[dict]:
    """Query native + ERC-20 balances for any EVM chain, filter against registry.

    RPC-agnostic: uses alchemy_getTokenBalances as a fast path when the
    RPC is Alchemy, otherwise goes straight to multicall balanceOf.
    """
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

    # ERC-20 fast path: Alchemy-proprietary bulk token scan (only on Alchemy RPCs)
    found_contracts = set()
    rpc_url = getattr(w3.provider, "endpoint_uri", "") or ""
    if "alchemy.com" in rpc_url:
        try:
            response = w3.provider.make_request(
                "alchemy_getTokenBalances",
                [checksum_wallet, "erc20"],
            )
            for tb in response.get("result", {}).get("tokenBalances", []):
                raw_balance = int(tb.get("tokenBalance", "0x0"), 16)
                if raw_balance == 0:
                    continue

                contract_addr = tb["contractAddress"].lower()
                token_entry = chain_registry.get(contract_addr)
                if token_entry is None:
                    continue  # Not in registry — skip spam

                found_contracts.add(contract_addr)
                decimals = token_entry.get("decimals", 18)
                human_balance = Decimal(raw_balance) / Decimal(10 ** decimals)
                rows.append(_build_row(
                    wallet, chain, contract_addr, token_entry, human_balance,
                    block_number, block_ts))
        except Exception:
            pass  # Fall through to multicall

    # Multicall balanceOf for registry tokens not yet found
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


# Backward-compatible alias
query_balances_alchemy = query_evm_balances


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
