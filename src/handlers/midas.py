"""Midas handler (Category A2 -- tokenised fund shares with oracle)."""

import logging
from decimal import Decimal
from web3 import Web3

from handlers import _load_contracts_cfg, _get_abi, _fmt

logger = logging.getLogger(__name__)


def query_midas_positions(w3, chain, wallet, block_number, block_ts):
    """Query Midas tokenised fund positions (mF-ONE, mHYPER, msyrupUSDp).

    Reads token addresses and oracles from contracts.json _midas section.
    """
    contracts = _load_contracts_cfg()
    midas_section = contracts.get(chain, {}).get("_midas", {})
    if not midas_section:
        return []

    erc20_abi = _get_abi("erc20")
    rows = []

    for entry_key, entry in midas_section.items():
        if entry_key.startswith("_") or not isinstance(entry, dict):
            continue
        if "address" not in entry or "oracle" not in entry:
            continue  # Skip oracle-only entries (like mhyper_oracle)

        if "decimals" not in entry:
            raise ValueError(f"Midas entry '{entry_key}' missing required 'decimals' field in contracts.json")
        if "oracle_chain" not in entry:
            raise ValueError(f"Midas entry '{entry_key}' missing required 'oracle_chain' field in contracts.json")

        token = w3.eth.contract(
            address=Web3.to_checksum_address(entry["address"]), abi=erc20_abi)
        try:
            bal = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call(block_identifier=block_number)
            logger.info("midas.balanceOf(%s, %s) block=%s → %s", entry["address"], wallet, block_number, bal)
        except Exception as e:
            logger.error("midas: balanceOf failed for entry=%s address=%s: %s", entry_key, entry["address"], e)
            continue

        if bal == 0:
            continue

        bal_human = _fmt(bal, entry["decimals"])

        rows.append({
            "chain": chain, "protocol": "midas", "wallet": wallet,
            "position_label": entry.get("display_name", entry.get("symbol", entry_key)),
            "category": "A2", "position_type": "oracle_priced",
            "token_symbol": entry.get("symbol", entry_key),
            "token_contract": entry["address"],
            "balance_raw": str(bal),
            "balance_human": bal_human,
            "decimals": entry["decimals"],
            "oracle_address": entry["oracle"],
            "oracle_chain": entry["oracle_chain"],
            "block_number": block_number, "block_timestamp_utc": block_ts,
        })

    return rows
