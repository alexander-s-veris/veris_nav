"""
Solana RPC client for the Veris NAV data collection system.

Provides helpers for querying Solana balances, token accounts,
and on-chain exchange rates (e.g. eUSX/USX).
"""

import os
from decimal import Decimal

import requests
from dotenv import load_dotenv

load_dotenv()

from evm import TS_FMT

# --- eUSX constants ---
EUSX_MINT = "3ThdFZQKM6kRyVGLG48kaPg5TRMhYMKY1iCRa9xop1WC"
EUSX_MINT_AUTHORITY = "2aHdm37djj4c21ztMRBmmo4my6RtzN5Nn58Y39rpWbRM"
USX_MINT = "6FrrzDk5mQARGc1TDYoyVnSyRdds1t4PbtohCD6p3tgG"


def get_solana_rpc_url() -> str:
    api_key = os.getenv("ALCHEMY_API_KEY")
    return f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"


def solana_rpc(method: str, params: list) -> dict:
    """Make a JSON-RPC call to Solana."""
    resp = requests.post(
        get_solana_rpc_url(),
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=15,
    )
    resp.raise_for_status()
    result = resp.json()
    if "error" in result:
        raise ValueError(f"Solana RPC error: {result['error']}")
    return result


def get_token_supply(mint: str) -> Decimal:
    """Get total supply of an SPL token mint."""
    resp = solana_rpc("getTokenSupply", [mint])
    value = resp["result"]["value"]
    return Decimal(value["uiAmountString"])


def get_token_accounts_by_owner(owner: str, mint: str) -> list[dict]:
    """Get all token accounts for a given owner and mint."""
    resp = solana_rpc("getTokenAccountsByOwner", [
        owner,
        {"mint": mint},
        {"encoding": "jsonParsed"},
    ])
    return resp["result"]["value"]


def get_eusx_exchange_rate() -> Decimal:
    """Calculate the eUSX/USX exchange rate from on-chain data.

    Method: total USX held in the eUSX vault / total eUSX supply.
    The vault is the USX token account owned by the eUSX mint authority.
    """
    # Total eUSX supply
    eusx_supply = get_token_supply(EUSX_MINT)

    if eusx_supply == 0:
        raise ValueError("eUSX supply is zero")

    # Total USX held in the vault (token accounts owned by mint authority)
    vault_accounts = get_token_accounts_by_owner(EUSX_MINT_AUTHORITY, USX_MINT)
    total_usx = Decimal(0)
    for acc in vault_accounts:
        info = acc["account"]["data"]["parsed"]["info"]
        total_usx += Decimal(info["tokenAmount"]["uiAmountString"])

    return total_usx / eusx_supply
