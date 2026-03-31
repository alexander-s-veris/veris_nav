"""ERC-4626 Vaults handler (Category A1)."""

import logging
from decimal import Decimal
from web3 import Web3

from handlers import (
    _load_contracts_cfg, _get_abi, _fmt,
    _get_display_name, _get_underlying_symbol,
)

logger = logging.getLogger(__name__)


def query_erc4626_vaults(w3, chain, wallet, block_number, block_ts):
    """Query all ERC-4626 vault positions for a wallet on a chain.

    Reads vault contracts from contracts.json (keys starting with _morpho_vaults,
    _avantis, _yearn, _credit_coop). Returns one row per vault with shares and
    underlying value.
    """
    contracts = _load_contracts_cfg()
    chain_contracts = contracts.get(chain, {})
    rows = []

    # Collect all ERC-4626 vault entries from sections with _query_type == "erc4626"
    vault_entries = []
    for section_key, section in chain_contracts.items():
        if not isinstance(section, dict):
            continue
        # Only scan sections with _query_type == "erc4626"
        if section.get("_query_type") != "erc4626":
            continue
        for entry_key, entry in section.items():
            if isinstance(entry, dict) and entry.get("abi") == "erc4626":
                vault_entries.append((section_key, entry_key, entry))

    for section_key, entry_key, entry in vault_entries:
        vault_addr = entry["address"]
        abi_name = entry.get("abi", "erc4626")
        vault = w3.eth.contract(
            address=Web3.to_checksum_address(vault_addr), abi=_get_abi(abi_name))

        try:
            shares = vault.functions.balanceOf(Web3.to_checksum_address(wallet)).call(block_identifier=block_number)
            logger.info("erc4626.balanceOf(%s, %s) block=%s → %s", vault_addr, wallet, block_number, shares)
        except Exception:
            continue

        if shares == 0:
            continue

        try:
            assets = vault.functions.convertToAssets(shares).call(block_identifier=block_number)
            share_decimals = vault.functions.decimals().call(block_identifier=block_number)
            logger.info("erc4626.convertToAssets(%s, shares=%s) block=%s → assets=%s, decimals=%s",
                         vault_addr, shares, block_number, assets, share_decimals)
            # Underlying may have different decimals (e.g. vault=18dec, USDC=6dec)
            try:
                asset_addr = vault.functions.asset().call(block_identifier=block_number)
                underlying_contract = w3.eth.contract(
                    address=Web3.to_checksum_address(asset_addr),
                    abi=_get_abi("erc20"))
                underlying_decimals = underlying_contract.functions.decimals().call(block_identifier=block_number)
            except Exception:
                underlying_decimals = share_decimals
        except Exception:
            continue

        protocol = section_key.strip("_")
        shares_human = _fmt(shares, share_decimals)
        assets_human = _fmt(assets, underlying_decimals)

        underlying_sym = _get_underlying_symbol(entry, vault_addr)
        display_name = _get_display_name(entry, vault_addr, entry_key)

        rows.append({
            "chain": chain, "protocol": protocol, "wallet": wallet,
            "position_label": display_name,
            "category": "A1", "position_type": "vault_share",
            "token_symbol": entry_key,
            "token_contract": vault_addr,
            "balance_raw": str(shares),
            "balance_human": shares_human,
            "decimals": share_decimals,
            "exchange_rate": assets_human / shares_human if shares_human > 0 else Decimal(0),
            "underlying_amount": assets_human,
            "underlying_symbol": underlying_sym,
            "block_number": block_number, "block_timestamp_utc": block_ts,
        })

    return rows
