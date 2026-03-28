"""PT Lots handler (Category B, Solana)."""

import json
import os

from evm import CONFIG_DIR


def query_pt_lots(valuation_date, block_ts):
    """Query PT token positions valued via lot-based linear amortisation.

    Reads lots from config/pt_lots.json, values using pt_valuation.value_pt_from_config().
    Returns one row per lot.
    """
    with open(os.path.join(CONFIG_DIR, "pt_lots.json")) as f:
        pt_cfg = json.load(f)

    rows = []
    for pt_symbol, cfg in pt_cfg.items():
        if pt_symbol.startswith("_"):
            continue
        if "lots_discovered" not in cfg:
            continue

        # For now, use placeholder price -- collect.py will price after
        rows.append({
            "chain": cfg.get("chain", "solana"),
            "protocol": cfg.get("protocol", "exponent"),
            "wallet": "ASQ4kYjSYGUYbbYtsaLhUeJS6RtrN4Uwp4XbF4gDifvr",
            "position_label": f"PT {pt_symbol} (lot-based)",
            "category": "B", "position_type": "pt_lot_aggregate",
            "token_symbol": pt_symbol,
            "token_contract": cfg.get("mint", ""),
            "total_tokens": cfg.get("total_tokens", 0),
            "total_lots": cfg.get("total_lots", 0),
            "underlying": cfg.get("underlying", ""),
            "maturity": cfg.get("maturity", ""),
            "decimals": cfg.get("decimals", 6),
            "held_as": cfg.get("held_as", ""),
            "block_timestamp_utc": block_ts,
            "_pt_symbol": pt_symbol,  # for valuation.py to pick up
        })

    return rows
