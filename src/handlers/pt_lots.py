"""PT Lots handler (Category B, Solana)."""

import json
import logging
import os

from evm import CONFIG_DIR

logger = logging.getLogger(__name__)


def query_pt_lots(wallet, block_ts):
    """Query PT token positions valued via lot-based linear amortisation.

    Reads lots from config/pt_lots.json. Returns one row per PT symbol.
    Wallet is passed by the orchestrator from wallets.json config.
    """
    logger.info("Loading PT lots config from pt_lots.json for wallet=%s", wallet)
    with open(os.path.join(CONFIG_DIR, "pt_lots.json")) as f:
        pt_cfg = json.load(f)

    rows = []
    for pt_symbol, cfg in pt_cfg.items():
        if pt_symbol.startswith("_"):
            continue
        if "lots_discovered" not in cfg:
            continue
        # PTs held as Kamino collateral are valued inside the D obligation,
        # not as standalone B positions
        if cfg.get("held_as", "").startswith("kamino_"):
            continue

        logger.info("PT lot: %s — %d lots, %s total tokens",
                     pt_symbol, cfg.get("total_lots", 0), cfg.get("total_tokens", 0))

        rows.append({
            "chain": cfg.get("chain", "solana"),
            "protocol": cfg.get("protocol", "exponent"),
            "wallet": wallet,
            "position_label": f"{pt_symbol} (lot-based)",
            "category": "B", "position_type": "pt_lot_aggregate",
            "token_symbol": pt_symbol,
            "token_contract": cfg.get("mint", ""),
            "total_tokens": cfg.get("total_tokens", 0),
            "total_lots": cfg.get("total_lots", 0),
            "underlying_symbol": cfg.get("underlying", ""),
            "maturity": cfg.get("maturity", ""),
            "decimals": cfg.get("decimals", 6),
            "held_as": cfg.get("held_as", ""),
            "block_number": "",  # Config-driven, no on-chain query
            "block_timestamp_utc": block_ts,
            "_pt_symbol": pt_symbol,  # for valuation.py to pick up
        })

    return rows
