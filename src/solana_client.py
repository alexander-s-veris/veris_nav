"""
Solana RPC client for the Veris NAV data collection system.

Provides helpers for querying Solana balances, token accounts,
on-chain exchange rates (e.g. eUSX/USX), and Kamino Lend obligations.
"""

import base64
import json
import os
import struct
from decimal import Decimal

import requests
from dotenv import load_dotenv

load_dotenv()

from evm import TS_FMT

# Standard SPL Token program ID (Solana mainnet)
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

# Rate limit delay between Solana RPC calls (seconds)
SOLANA_RPC_RATE_LIMIT_SECONDS = 0.1

# --- Config loader for solana_protocols.json ---
_SOLANA_CFG = None


def _load_solana_cfg():
    global _SOLANA_CFG
    if _SOLANA_CFG is None:
        with open(os.path.join(os.path.dirname(__file__), "..", "config", "solana_protocols.json")) as f:
            _SOLANA_CFG = json.load(f)
    return _SOLANA_CFG


def get_solana_rpc_url() -> str:
    """Get Solana RPC URL from chains.json config."""
    from evm import get_rpc_url
    try:
        return get_rpc_url("solana")
    except Exception:
        # Fallback if chains.json doesn't have solana or RPC setup fails
        api_key = os.getenv("ALCHEMY_API_KEY")
        return f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"


def solana_rpc(method: str, params: list, url_override: str = None) -> dict:
    """Make a JSON-RPC call to Solana.

    Args:
        method: RPC method name.
        params: RPC parameters.
        url_override: Optional URL to use instead of the default RPC.
                      Used for heavy queries (getProgramAccounts) routed
                      to a public RPC to avoid Alchemy rate limits.
    """
    url = url_override or get_solana_rpc_url()
    resp = requests.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=30 if url_override else 15,
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


def find_valuation_slot(target_ts: int) -> tuple[int, str]:
    """Find the Solana slot closest to but not exceeding target_ts.

    Uses binary search on getBlockTime to converge on the right slot.
    The returned slot's timestamp is guaranteed to be <= target_ts
    (per Valuation Policy: closest to but NOT exceeding 16:00 CET/CEST).

    Args:
        target_ts: Target unix timestamp (e.g. 16:00 CET/CEST on valuation date).

    Returns:
        (slot_number, slot_timestamp_utc_str)
    """
    from datetime import datetime, timezone

    # Get current slot as reference — Alchemy doesn't serve getBlockTime
    # for very recent slots, so start 1000 slots back (~7 minutes)
    current_slot = solana_rpc("getSlot", [])["result"] - 1000
    current_time = solana_rpc("getBlockTime", [current_slot])["result"]

    if current_time is None:
        raise ValueError("Cannot get current block time from Solana")

    # If target is in the future, return current slot
    if target_ts >= current_time:
        ts_str = datetime.fromtimestamp(current_time, tz=timezone.utc).strftime(TS_FMT)
        return current_slot, ts_str

    # Estimate slot, then refine using observed rate (same approach as EVM)
    slots_per_second = 2.5
    diff_seconds = current_time - target_ts
    est_slot = int(current_slot - diff_seconds * slots_per_second)
    est_slot = max(1, est_slot)

    # Check estimate accuracy and correct using observed slot rate
    for _ in range(3):
        est_time = solana_rpc("getBlockTime", [est_slot])["result"]
        if est_time is None:
            est_slot -= 10
            continue
        est_error = est_time - target_ts
        if abs(est_error) <= 30:
            break
        slot_span = current_slot - est_slot
        ts_span = current_time - est_time
        if ts_span > 0 and slot_span > 0:
            observed_rate = ts_span / slot_span
            est_slot = max(1, est_slot - int(est_error / observed_rate))

    # Binary search refinement
    low = est_slot - 500
    high = est_slot + 500
    best_slot = est_slot
    best_ts = None

    for _ in range(12):
        if low > high:
            break
        mid = (low + high) // 2
        mid_time = None

        # Try mid and nearby slots (some slots may be skipped)
        for offset in range(3):
            try:
                resp = solana_rpc("getBlockTime", [mid + offset])
                mid_time = resp["result"]
                if mid_time is not None:
                    mid = mid + offset
                    break
            except Exception:
                continue

        if mid_time is None:
            high = mid - 1
            continue

        if mid_time <= target_ts:
            best_slot = mid
            best_ts = mid_time
            low = mid + 1
        else:
            high = mid - 1

    if best_ts is None:
        # Fallback: use estimate and try to get its time
        try:
            resp = solana_rpc("getBlockTime", [est_slot])
            best_ts = resp["result"]
            best_slot = est_slot
        except Exception:
            best_ts = target_ts

    ts_str = datetime.fromtimestamp(best_ts, tz=timezone.utc).strftime(TS_FMT)
    return best_slot, ts_str


def get_solana_vault_exchange_rate(vault_key: str = "eusx") -> Decimal:
    """Calculate exchange rate for a Solana vault token from on-chain data.

    Method: total underlying held in vault / total vault token supply.
    Config read from solana_protocols.json[vault_key] which must have:
      - vault_mint: the vault token mint address
      - mint_authority: the vault's mint authority (holds underlying)
      - underlying_mint: the underlying token mint

    Currently used for eUSX/USX. Token-agnostic — any vault with the same
    pattern (supply + authority-held underlying) can use this.
    """
    cfg = _load_solana_cfg()
    vault_cfg = cfg[vault_key]

    vault_mint = vault_cfg["vault_mint"]
    mint_authority = vault_cfg["mint_authority"]
    underlying_mint = vault_cfg["underlying_mint"]

    vault_supply = get_token_supply(vault_mint)

    if vault_supply == 0:
        raise ValueError(f"{vault_key} supply is zero")

    vault_accounts = get_token_accounts_by_owner(mint_authority, underlying_mint)
    total_underlying = Decimal(0)
    for acc in vault_accounts:
        info = acc["account"]["data"]["parsed"]["info"]
        total_underlying += Decimal(info["tokenAmount"]["uiAmountString"])

    return total_underlying / vault_supply


# Backward compat alias
def get_eusx_exchange_rate() -> Decimal:
    """Backward-compatible alias for get_solana_vault_exchange_rate('eusx')."""
    return get_solana_vault_exchange_rate("eusx")


# --- Kamino Lend ---
# Program ID read from solana_protocols.json["kamino"]["program_id"]

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

    cfg = _load_solana_cfg()
    kamino_program_id = cfg["kamino"]["program_id"]
    if value["owner"] != kamino_program_id:
        raise ValueError(
            f"Account {obligation_pubkey} owned by {value['owner']}, "
            f"expected {kamino_program_id}"
        )

    raw = base64.b64decode(value["data"][0])
    result = parse_kamino_obligation(raw)
    result["obligation_pubkey"] = obligation_pubkey
    result["query_slot"] = slot or "latest"
    return result


# --- Exponent Finance ---
# Program ID read from solana_protocols.json["exponent"]["program_id"]
# Yield-splitting protocol: SY -> PT + YT. Markets are AMM pools (SY vs PT).
# LP and YT positions are PDA accounts, not SPL tokens.

def _get_exponent_program_id() -> str:
    return _load_solana_cfg()["exponent"]["program_id"]

# Public RPC for heavy queries (getProgramAccounts) to avoid Alchemy rate limits
_EXPONENT_PUBLIC_RPC = os.getenv("SOLANA_PUBLIC_RPC_URL", "https://api.mainnet-beta.solana.com")

# Account discriminators (from Exponent IDL — binary struct layout constants)
_LP_POSITION_DISC = bytes([105, 241, 37, 200, 224, 2, 252, 90])
_YT_POSITION_DISC = bytes([227, 92, 146, 49, 29, 85, 71, 94])
_MARKET_TWO_DISC = bytes([212, 4, 132, 126, 169, 121, 121, 20])

# MarketFinancials byte offsets within MarketTwo account
_MF_OFFSET = 364  # offset of expiration_ts in MarketTwo
_YEAR_SECONDS = 31_536_000  # 365 days exactly (Exponent convention)


def parse_exponent_market(raw: bytes) -> dict:
    """Parse an Exponent MarketTwo account to extract pool state and implied rate.

    Returns dict with pubkeys (vault, sy_mint, pt_mint, lp_mint),
    pool balances, expiration timestamp, and last_ln_implied_rate.
    """
    # Pubkeys at offset 8, 32 bytes each
    vault = _bytes_to_b58(raw[8 + 3 * 32: 8 + 4 * 32])  # idx 3
    sy_mint = _bytes_to_b58(raw[8 + 1 * 32: 8 + 2 * 32])  # idx 1
    pt_mint = _bytes_to_b58(raw[8 + 2 * 32: 8 + 3 * 32])  # idx 2
    lp_mint = _bytes_to_b58(raw[8 + 4 * 32: 8 + 5 * 32])  # idx 4

    # MarketFinancials at offset 364
    expiration_ts = struct.unpack_from("<Q", raw, _MF_OFFSET)[0]
    pt_balance = struct.unpack_from("<Q", raw, _MF_OFFSET + 8)[0]
    sy_balance = struct.unpack_from("<Q", raw, _MF_OFFSET + 16)[0]
    ln_fee_rate_root = struct.unpack_from("<d", raw, _MF_OFFSET + 24)[0]
    last_ln_implied_rate = struct.unpack_from("<d", raw, _MF_OFFSET + 32)[0]
    rate_scalar_root = struct.unpack_from("<d", raw, _MF_OFFSET + 40)[0]

    return {
        "vault": vault,
        "sy_mint": sy_mint,
        "pt_mint": pt_mint,
        "lp_mint": lp_mint,
        "expiration_ts": expiration_ts,
        "pt_balance": pt_balance,
        "sy_balance": sy_balance,
        "ln_fee_rate_root": ln_fee_rate_root,
        "last_ln_implied_rate": last_ln_implied_rate,
        "rate_scalar_root": rate_scalar_root,
    }


def get_exponent_market(market_pubkey: str, slot: int | None = None) -> dict:
    """Fetch and parse an Exponent MarketTwo account."""
    params = [market_pubkey, {"encoding": "base64"}]
    if slot is not None:
        params[1]["minContextSlot"] = slot

    resp = solana_rpc("getAccountInfo", params)
    value = resp["result"]["value"]
    if value is None:
        raise ValueError(f"Market account not found: {market_pubkey}")

    raw = base64.b64decode(value["data"][0])
    result = parse_exponent_market(raw)
    result["market_pubkey"] = market_pubkey
    result["query_slot"] = slot or "latest"
    return result


def get_exponent_lp_positions(wallet: str) -> list[dict]:
    """Find all Exponent LP positions for a wallet via getProgramAccounts.

    Uses public RPC to avoid Alchemy rate limits on getProgramAccounts.
    Returns list of dicts with market pubkey and lp_balance.
    """
    resp = solana_rpc("getProgramAccounts", [
        _get_exponent_program_id(),
        {
            "encoding": "base64",
            "filters": [
                {"memcmp": {"offset": 0, "bytes": base64.b64encode(_LP_POSITION_DISC).decode(), "encoding": "base64"}},
                {"memcmp": {"offset": 8, "bytes": wallet, "encoding": "base58"}},
            ],
        },
    ], url_override=_EXPONENT_PUBLIC_RPC)

    positions = []
    for acc in resp["result"]:
        raw = base64.b64decode(acc["account"]["data"][0])
        offset = 8  # skip discriminator
        owner = _bytes_to_b58(raw[offset:offset + 32]); offset += 32
        market = _bytes_to_b58(raw[offset:offset + 32]); offset += 32
        lp_balance = struct.unpack_from("<Q", raw, offset)[0]

        if lp_balance > 0:
            positions.append({
                "account_pubkey": acc["pubkey"],
                "market": market,
                "lp_balance": lp_balance,
            })

    return positions


def get_exponent_yt_positions(wallet: str) -> list[dict]:
    """Find all Exponent YT positions for a wallet via getProgramAccounts.

    Uses public RPC to avoid Alchemy rate limits.
    Returns list of dicts with vault pubkey and yt_balance.
    """
    resp = solana_rpc("getProgramAccounts", [
        _get_exponent_program_id(),
        {
            "encoding": "base64",
            "filters": [
                {"memcmp": {"offset": 0, "bytes": base64.b64encode(_YT_POSITION_DISC).decode(), "encoding": "base64"}},
                {"memcmp": {"offset": 8, "bytes": wallet, "encoding": "base58"}},
            ],
        },
    ], url_override=_EXPONENT_PUBLIC_RPC)

    positions = []
    for acc in resp["result"]:
        raw = base64.b64decode(acc["account"]["data"][0])
        offset = 8
        owner = _bytes_to_b58(raw[offset:offset + 32]); offset += 32
        vault = _bytes_to_b58(raw[offset:offset + 32]); offset += 32
        yt_balance = struct.unpack_from("<Q", raw, offset)[0]

        if yt_balance > 0:
            positions.append({
                "account_pubkey": acc["pubkey"],
                "vault": vault,
                "yt_balance": yt_balance,
            })

    return positions


def decompose_exponent_lp(
    market: dict,
    lp_balance: int,
    lp_total_supply: int,
) -> dict:
    """Decompose an Exponent LP position into SY and PT components.

    Args:
        market: Parsed MarketTwo dict from get_exponent_market()
        lp_balance: User's LP token balance (raw)
        lp_total_supply: Total LP supply from getTokenSupply (raw)

    Returns dict with user_sy, user_pt amounts and PT price ratio.
    """
    import math

    user_sy = market["sy_balance"] * lp_balance // lp_total_supply
    user_pt = market["pt_balance"] * lp_balance // lp_total_supply

    # PT price using AMM implied rate
    import time
    sec_remaining = market["expiration_ts"] - int(time.time())
    if sec_remaining > 0 and market["last_ln_implied_rate"] > 0:
        exchange_rate = math.exp(
            market["last_ln_implied_rate"] * sec_remaining / _YEAR_SECONDS
        )
        pt_price_ratio = 1.0 / exchange_rate
    else:
        # At or past maturity — PT = 1:1 underlying
        exchange_rate = 1.0
        pt_price_ratio = 1.0

    return {
        "user_sy": user_sy,
        "user_pt": user_pt,
        "pt_price_ratio": pt_price_ratio,
        "exchange_rate": exchange_rate,
        "seconds_remaining": max(0, sec_remaining),
        "last_ln_implied_rate": market["last_ln_implied_rate"],
        "lp_share": lp_balance / lp_total_supply if lp_total_supply > 0 else 0,
    }


# --- OnRe Finance (ONyc) ---
# NAV computed from Offer PDA with APR-based discrete step pricing.
# Config read from solana_protocols.json["onre"].

# Offer account layout (zero_copy, repr(C), after 8-byte Anchor discriminator):
#   token_in_mint:  Pubkey (32 bytes)
#   token_out_mint: Pubkey (32 bytes)
#   vectors:        [OfferVector; 10] (10 × 40 bytes = 400 bytes)
#     Each OfferVector:
#       start_time:         u64 (8 bytes)
#       base_time:          u64 (8 bytes)
#       base_price:         u64 (8 bytes) — scale=9
#       apr:                u64 (8 bytes) — scale=6 (1_000_000 = 1%)
#       price_fix_duration: u64 (8 bytes)
#   fee_basis_points: u16 (2 bytes)
#   bump:             u8  (1 byte)
#   needs_approval:   u8  (1 byte)
#   allow_permissionless: u8 (1 byte)
#   reserved:         [u8; 131]

_OFFER_VECTOR_SIZE = 40  # 5 × u64
_MAX_VECTORS = 10
_OFFER_VECTORS_OFFSET = 8 + 32 + 32  # discriminator + 2 pubkeys


def _derive_onre_offer_pda() -> str:
    """Derive the Offer PDA for the USDC→ONyc pair from config."""
    from solders.pubkey import Pubkey as SoldersPubkey

    cfg = _load_solana_cfg()["onre"]
    program_id = SoldersPubkey.from_string(cfg["program_id"])
    usdc_mint = SoldersPubkey.from_string(cfg["usdc_mint"])
    onyc_mint = SoldersPubkey.from_string(cfg["onyc_mint"])

    pda, _bump = SoldersPubkey.find_program_address(
        [cfg["offer_seed"].encode(), bytes(usdc_mint), bytes(onyc_mint)],
        program_id,
    )
    return str(pda)


def parse_onre_offer(raw: bytes) -> dict:
    """Parse an OnRe Offer account to extract pricing vectors.

    Returns dict with token mints, active vectors, and fee config.
    """
    offset = 8  # skip Anchor discriminator
    token_in = _bytes_to_b58(raw[offset:offset + 32]); offset += 32
    token_out = _bytes_to_b58(raw[offset:offset + 32]); offset += 32

    vectors = []
    for i in range(_MAX_VECTORS):
        v_offset = offset + i * _OFFER_VECTOR_SIZE
        start_time = struct.unpack_from("<Q", raw, v_offset)[0]
        base_time = struct.unpack_from("<Q", raw, v_offset + 8)[0]
        base_price = struct.unpack_from("<Q", raw, v_offset + 16)[0]
        apr = struct.unpack_from("<Q", raw, v_offset + 24)[0]
        price_fix_duration = struct.unpack_from("<Q", raw, v_offset + 32)[0]

        if start_time == 0:
            continue  # empty vector slot

        vectors.append({
            "start_time": start_time,
            "base_time": base_time,
            "base_price": base_price,
            "apr": apr,
            "price_fix_duration": price_fix_duration,
        })

    return {
        "token_in": token_in,
        "token_out": token_out,
        "vectors": vectors,
    }


def get_onre_nav(slot: int | None = None) -> dict:
    """Compute ONyc NAV from the on-chain Offer account.

    Reads the Offer PDA, finds the active pricing vector, and computes
    the current price using the APR-based discrete step formula.

    Returns dict with price (Decimal, scale=9 converted to human),
    active vector details, and offer PDA.
    """
    import time as _time

    cfg = _load_solana_cfg()["onre"]
    price_decimals = cfg["price_decimals"]
    apr_scale = cfg["apr_scale"]
    seconds_in_year = cfg["seconds_in_year"]

    offer_pda = _derive_onre_offer_pda()

    params = [offer_pda, {"encoding": "base64"}]
    if slot is not None:
        params[1]["minContextSlot"] = slot

    resp = solana_rpc("getAccountInfo", params)
    value = resp["result"]["value"]
    if value is None:
        raise ValueError(f"OnRe Offer PDA not found: {offer_pda}")

    raw = base64.b64decode(value["data"][0])
    offer = parse_onre_offer(raw)

    if not offer["vectors"]:
        raise ValueError("OnRe Offer has no active pricing vectors")

    # Find active vector: latest start_time <= current_time
    current_time = int(_time.time())
    active = None
    for v in sorted(offer["vectors"], key=lambda x: x["start_time"], reverse=True):
        if v["start_time"] <= current_time:
            active = v
            break

    if active is None:
        raise ValueError("No active pricing vector in OnRe Offer")

    # Compute price using discrete step formula:
    #   step = floor((now - base_time) / price_fix_duration)
    #   effective_elapsed = (step + 1) * price_fix_duration
    #   price = base_price * (1 + apr * effective_elapsed / SECONDS_IN_YEAR) / APR_SCALE
    elapsed = current_time - active["base_time"]
    step = elapsed // active["price_fix_duration"]
    step_end_time = (step + 1) * active["price_fix_duration"]

    # Fixed-point: factor = (APR_SCALE * SECONDS_IN_YEAR + apr * step_end_time) / (APR_SCALE * SECONDS_IN_YEAR)
    factor_den = apr_scale * seconds_in_year
    factor_num = factor_den + active["apr"] * step_end_time
    price_raw = active["base_price"] * factor_num // factor_den

    price = Decimal(price_raw) / Decimal(10 ** price_decimals)

    return {
        "offer_pda": offer_pda,
        "price": price,
        "price_raw": price_raw,
        "active_vector": active,
        "current_time": current_time,
        "step": step,
        "step_end_time": step_end_time,
    }
