"""Exponent LP and YT handlers (Solana -- Category C and F)."""

import logging
import math
import time
from decimal import Decimal

from handlers import _load_solana_cfg
from solana_client import (
    solana_rpc, get_exponent_lp_positions, get_exponent_yt_positions,
    get_exponent_market, decompose_exponent_lp, SOLANA_RPC_RATE_LIMIT_SECONDS,
)

logger = logging.getLogger(__name__)


def query_exponent_lps(wallet, block_ts):
    """Query Exponent LP positions and decompose into SY + PT constituents.

    Reads market configs from solana_protocols.json exponent section.
    """
    solana_cfg = _load_solana_cfg()
    markets = solana_cfg.get("exponent", {}).get("markets", [])

    lp_positions = get_exponent_lp_positions(wallet)
    if not lp_positions:
        return []

    rows = []
    for mcfg in markets:
        lp = next(
            (l for l in lp_positions if l["market"] == mcfg["market_pubkey"]),
            None
        )
        if lp is None or lp["lp_balance"] == 0:
            continue

        sy = mcfg["sy"]
        pt = mcfg["pt"]

        time.sleep(SOLANA_RPC_RATE_LIMIT_SECONDS)
        market = get_exponent_market(mcfg["market_pubkey"])
        logger.info("exponent.getMarket(%s) → lp_mint=%s", mcfg["market_pubkey"], market["lp_mint"])
        time.sleep(SOLANA_RPC_RATE_LIMIT_SECONDS)
        lp_supply_resp = solana_rpc("getTokenSupply", [market["lp_mint"]])
        lp_supply = int(lp_supply_resp["result"]["value"]["amount"])

        decomp = decompose_exponent_lp(market, lp["lp_balance"], lp_supply)

        sy_amount = Decimal(decomp["user_sy"]) / Decimal(10 ** sy["decimals"])
        pt_amount = Decimal(decomp["user_pt"]) / Decimal(10 ** pt["decimals"])
        pt_price_ratio = Decimal(str(decomp["pt_price_ratio"]))

        # SY constituent row
        rows.append({
            "chain": "solana", "protocol": "exponent", "wallet": wallet,
            "position_label": f"Exponent {mcfg['name']} LP",
            "category": "C", "position_type": "lp_constituent",
            "token_symbol": sy["symbol"],
            "token_category": sy["category"],
            "balance_human": sy_amount,
            "decimals": sy["decimals"],
            "lp_constituent_type": "SY",
            "lp_share": decomp["lp_share"],
            "block_timestamp_utc": block_ts,
        })

        # PT constituent row
        rows.append({
            "chain": "solana", "protocol": "exponent", "wallet": wallet,
            "position_label": f"Exponent {mcfg['name']} LP",
            "category": "C", "position_type": "lp_constituent",
            "token_symbol": pt["symbol"],
            "token_category": "C",  # PT in LP uses AMM rate, not lot amortisation
            "underlying_symbol": sy["symbol"],  # SY token is the underlying for PT pricing
            "balance_human": pt_amount,
            "decimals": pt["decimals"],
            "lp_constituent_type": "PT",
            "pt_price_ratio": pt_price_ratio,
            "last_ln_implied_rate": decomp["last_ln_implied_rate"],
            "seconds_remaining": decomp["seconds_remaining"],
            "lp_share": decomp["lp_share"],
            "block_timestamp_utc": block_ts,
        })

    return rows


def query_exponent_yts(wallet, block_ts):
    """Query Exponent Yield Token positions.

    Reads market configs from solana_protocols.json exponent section.
    """
    solana_cfg = _load_solana_cfg()
    markets = solana_cfg.get("exponent", {}).get("markets", [])

    yt_positions = get_exponent_yt_positions(wallet)
    if not yt_positions:
        return []

    rows = []
    for mcfg in markets:
        yt_cfg = mcfg.get("yt")
        if not yt_cfg:
            continue
        yt_vault = mcfg.get("yt_vault")
        if not yt_vault:
            continue

        yt = next(
            (y for y in yt_positions if y["vault"] == yt_vault),
            None
        )
        if yt is None or yt["yt_balance"] == 0:
            continue

        yt_human = Decimal(yt["yt_balance"]) / Decimal(10 ** yt_cfg["decimals"])

        # Get PT price ratio from market for YT pricing
        time.sleep(SOLANA_RPC_RATE_LIMIT_SECONDS)
        market = get_exponent_market(mcfg["market_pubkey"])
        logger.info("exponent.getMarket(%s) for YT pricing", mcfg["market_pubkey"])
        sec_remaining = market["expiration_ts"] - int(time.time())
        if sec_remaining > 0 and market["last_ln_implied_rate"] > 0:
            exchange_rate = math.exp(
                market["last_ln_implied_rate"] * sec_remaining / 31_536_000)
            pt_price_ratio = 1.0 / exchange_rate
        else:
            pt_price_ratio = 1.0

        yt_price_ratio = Decimal(str(1.0 - pt_price_ratio))

        rows.append({
            "chain": "solana", "protocol": "exponent", "wallet": wallet,
            "position_label": f"Exponent {yt_cfg['symbol']}",
            "category": "F", "position_type": "reward",
            "token_symbol": yt_cfg["symbol"],
            "underlying_symbol": yt_cfg.get("underlying", ""),
            "balance_human": yt_human,
            "decimals": yt_cfg["decimals"],
            "yt_price_ratio": yt_price_ratio,
            "block_timestamp_utc": block_ts,
        })

    return rows
