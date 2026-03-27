"""
Solana RPC client for the Veris NAV data collection system.

Provides helpers for querying Solana balances, token accounts,
on-chain exchange rates (e.g. eUSX/USX), and Kamino Lend obligations.
"""

import base64
import os
import struct
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


# --- Kamino Lend ---
# Program: KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD
# Obligations store collateral (deposits) and debt (borrows) for leveraged positions.

KAMINO_PROGRAM_ID = "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"
KAMINO_API_BASE = "https://api.kamino.finance"

# Account layout sizes (bytes)
_ANCHOR_DISCRIMINATOR = 8
_COLLATERAL_SIZE = 136  # ObligationCollateral: pubkey(32) + amount(8) + marketValueSf(16) + borrowAgainst(8) + padding(72)
_LIQUIDITY_SIZE = 200   # ObligationLiquidity: pubkey(32) + cumBorrowRate(48) + lastBorrowTs(8) + borrowedSf(16) + mvSf(16) + bfAdjMvSf(16) + borrowOutside(8) + fixedTerm(16) + borrowAtExp(8) + padding(32)
_SF_DIVISOR = Decimal(2**60)  # Scale factor for Sf fields
_ZERO_PUBKEY = "11111111111111111111111111111111"


def _bytes_to_b58(raw_bytes: bytes) -> str:
    """Convert raw bytes to base58 string (Solana address format)."""
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = int.from_bytes(raw_bytes, "big")
    result = ""
    while num > 0:
        num, rem = divmod(num, 58)
        result = alphabet[rem] + result
    for byte in raw_bytes:
        if byte == 0:
            result = "1" + result
        else:
            break
    return result


def parse_kamino_obligation(raw: bytes) -> dict:
    """Deserialize a Kamino Lend obligation account from raw binary data.

    Returns dict with tag, market, owner, deposits (collateral), and borrows (debt).
    Token amounts are returned as raw integers — caller converts using token decimals.
    borrowedAmountSf is divided by 2^60 to get the human-readable amount.
    marketValueSf fields are included but may be stale — do NOT use for NAV.
    """
    offset = _ANCHOR_DISCRIMINATOR

    tag = struct.unpack_from("<Q", raw, offset)[0]
    offset += 8

    # lastUpdate: slot(u64) + stale(u8) + priceStatus(u8) + placeholder(6 bytes)
    last_update_slot = struct.unpack_from("<Q", raw, offset)[0]
    offset += 8
    stale = raw[offset]
    offset += 1 + 1 + 6  # stale + priceStatus + placeholder

    market = _bytes_to_b58(raw[offset:offset + 32])
    offset += 32

    owner = _bytes_to_b58(raw[offset:offset + 32])
    offset += 32

    # Parse 8 deposit slots
    deposits = []
    for i in range(8):
        dep_offset = offset + i * _COLLATERAL_SIZE
        reserve = _bytes_to_b58(raw[dep_offset:dep_offset + 32])
        if reserve == _ZERO_PUBKEY:
            continue
        amount = struct.unpack_from("<Q", raw, dep_offset + 32)[0]
        if amount == 0:
            continue
        market_value_sf = int.from_bytes(raw[dep_offset + 40:dep_offset + 56], "little")
        deposits.append({
            "reserve": reserve,
            "deposited_amount": amount,
            "market_value_sf": market_value_sf,
            "market_value_usd_stale": Decimal(market_value_sf) / _SF_DIVISOR,
        })
    offset += 8 * _COLLATERAL_SIZE

    # lowestReserveDepositLiquidationLtv (u64) + depositedValueSf (u128)
    offset += 8
    deposited_value_sf = int.from_bytes(raw[offset:offset + 16], "little")
    offset += 16

    # Parse 5 borrow slots
    borrows = []
    for i in range(5):
        bor_offset = offset + i * _LIQUIDITY_SIZE
        reserve = _bytes_to_b58(raw[bor_offset:bor_offset + 32])
        if reserve == _ZERO_PUBKEY:
            continue
        # Skip cumulativeBorrowRateBsf (48) + lastBorrowedAtTimestamp (8)
        sf_offset = bor_offset + 32 + 48 + 8
        borrowed_sf = int.from_bytes(raw[sf_offset:sf_offset + 16], "little")
        if borrowed_sf == 0:
            continue
        market_value_sf = int.from_bytes(raw[sf_offset + 16:sf_offset + 32], "little")
        borrows.append({
            "reserve": reserve,
            "borrowed_amount_sf": borrowed_sf,
            "borrowed_amount": Decimal(borrowed_sf) / _SF_DIVISOR,
            "market_value_sf": market_value_sf,
            "market_value_usd_stale": Decimal(market_value_sf) / _SF_DIVISOR,
        })

    return {
        "tag": tag,
        "last_update_slot": last_update_slot,
        "stale": bool(stale),
        "market": market,
        "owner": owner,
        "deposits": deposits,
        "borrows": borrows,
        "deposited_value_usd_stale": Decimal(deposited_value_sf) / _SF_DIVISOR,
    }


def get_kamino_obligation(obligation_pubkey: str, slot: int | None = None) -> dict:
    """Fetch and parse a Kamino obligation account at a given slot.

    If slot is None, queries latest. For NAV, pass the Valuation Block slot.
    Returns parsed obligation dict from parse_kamino_obligation().
    """
    params = [obligation_pubkey, {"encoding": "base64"}]
    if slot is not None:
        params[1]["minContextSlot"] = slot

    resp = solana_rpc("getAccountInfo", params)
    value = resp["result"]["value"]
    if value is None:
        raise ValueError(f"Obligation account not found: {obligation_pubkey}")

    if value["owner"] != KAMINO_PROGRAM_ID:
        raise ValueError(
            f"Account {obligation_pubkey} owned by {value['owner']}, "
            f"expected {KAMINO_PROGRAM_ID}"
        )

    raw = base64.b64decode(value["data"][0])
    result = parse_kamino_obligation(raw)
    result["obligation_pubkey"] = obligation_pubkey
    result["query_slot"] = slot or "latest"
    return result
