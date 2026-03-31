"""Aave handler (Category D or A1)."""

import logging
from decimal import Decimal
from web3 import Web3

from handlers import _load_contracts_cfg, _get_abi, _fmt, _get_display_name

logger = logging.getLogger(__name__)


def query_aave_positions(w3, chain, wallet, block_number, block_ts):
    """Query Aave aToken and debt token positions for a wallet.

    Reads aToken/debt token addresses from contracts.json _aave section.
    Supply-only = A1; with debt = D (two rows: collateral + debt).
    """
    contracts = _load_contracts_cfg()

    chain_contracts = contracts.get(chain, {})
    aave_section = chain_contracts.get("_aave", {})
    if not aave_section:
        return []

    rows = []
    erc20_abi = _get_abi("erc20")

    # Find aToken and debt token pairs
    atokens = {}
    debt_tokens = {}
    for entry_key, entry in aave_section.items():
        if not isinstance(entry, dict) or "address" not in entry:
            continue
        if entry_key.startswith("atoken") or entry_key.startswith("horizon_atoken"):
            atokens[entry_key] = entry
        elif "vdebt" in entry_key or "debt" in entry_key:
            debt_tokens[entry_key] = entry

    # Query each aToken
    for akey, aentry in atokens.items():
        token = w3.eth.contract(
            address=Web3.to_checksum_address(aentry["address"]), abi=erc20_abi)
        try:
            bal = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call(block_identifier=block_number)
            logger.info("aave.balanceOf(%s, %s) block=%s → %s", aentry["address"], wallet, block_number, bal)
        except Exception:
            continue
        if bal == 0:
            continue

        # Decimals from config (required) or on-chain fallback
        decimals = aentry.get("decimals")
        if decimals is None:
            try:
                decimals = token.functions.decimals().call(block_identifier=block_number)
                logger.info("aave.decimals(%s) → %s (on-chain)", aentry["address"], decimals)
            except Exception:
                raise ValueError(f"No decimals in config or on-chain for aToken {akey} at {aentry['address']}")

        bal_human = _fmt(bal, decimals)

        rows.append({
            "chain": chain, "protocol": "aave", "wallet": wallet,
            "position_label": _get_display_name(aentry, aentry["address"], akey),
            "category": "D",  # may be reclassified if no debt
            "position_type": "collateral",
            "token_symbol": aentry.get("symbol", akey),
            "underlying_symbol": aentry.get("underlying_symbol", ""),
            "token_contract": aentry["address"],
            "balance_raw": str(bal),
            "balance_human": bal_human,
            "decimals": decimals,
            "block_number": block_number, "block_timestamp_utc": block_ts,
        })

    # Query each debt token
    for dkey, dentry in debt_tokens.items():
        token = w3.eth.contract(
            address=Web3.to_checksum_address(dentry["address"]), abi=erc20_abi)
        try:
            bal = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call(block_identifier=block_number)
            logger.info("aave.balanceOf(%s, %s) block=%s → %s", dentry["address"], wallet, block_number, bal)
        except Exception:
            continue
        if bal == 0:
            continue

        # Decimals from config (required) or on-chain fallback
        decimals = dentry.get("decimals")
        if decimals is None:
            try:
                decimals = token.functions.decimals().call(block_identifier=block_number)
                logger.info("aave.decimals(%s) → %s (on-chain)", dentry["address"], decimals)
            except Exception:
                raise ValueError(f"No decimals in config or on-chain for debt token {dkey} at {dentry['address']}")

        bal_human = _fmt(bal, decimals)

        rows.append({
            "chain": chain, "protocol": "aave", "wallet": wallet,
            "position_label": _get_display_name(dentry, dentry["address"], dkey),
            "category": "D", "position_type": "debt",
            "token_symbol": dentry.get("symbol", dkey),
            "underlying_symbol": dentry.get("underlying_symbol", ""),
            "token_contract": dentry["address"],
            "balance_raw": str(bal),
            "balance_human": -bal_human,  # negative for debt
            "decimals": decimals,
            "block_number": block_number, "block_timestamp_utc": block_ts,
        })

    return rows
