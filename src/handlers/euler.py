"""Euler V2 Vaults handler (Category A1, sub-account scan)."""

from decimal import Decimal
from web3 import Web3

from handlers import (
    _load_contracts_cfg, _get_abi, _fmt,
    _get_display_name, _get_underlying_symbol,
)


def query_euler_vaults(w3, chain, wallet, block_number, block_ts):
    """Query Euler V2 vaults with sub-account scanning.

    Euler uses XOR-based sub-accounts. Known sub-account IDs are used from config
    to avoid scanning all 256.
    """
    contracts = _load_contracts_cfg()

    chain_contracts = contracts.get(chain, {})
    euler_section = chain_contracts.get("_euler", {})
    if not euler_section:
        return []

    rows = []
    wallet_int = int(wallet, 16)

    for entry_key, entry in euler_section.items():
        if not isinstance(entry, dict) or entry.get("abi") != "erc4626":
            continue

        vault_addr = entry["address"]
        vault = w3.eth.contract(
            address=Web3.to_checksum_address(vault_addr), abi=_get_abi("erc4626"))

        # Scan known sub-accounts (from config description) or all 256
        # For speed, scan sub-accounts 0 and 1 first (most common), then others
        found = False
        for sub_id in [0, 1] + list(range(2, 256)):
            sub_addr = Web3.to_checksum_address(hex(wallet_int ^ sub_id))
            try:
                shares = vault.functions.balanceOf(sub_addr).call()
            except Exception:
                continue

            if shares > 0:
                assets = vault.functions.convertToAssets(shares).call()
                share_dec = vault.functions.decimals().call()
                try:
                    asset_addr = vault.functions.asset().call()
                    u_contract = w3.eth.contract(
                        address=Web3.to_checksum_address(asset_addr),
                        abi=_get_abi("erc20"))
                    u_dec = u_contract.functions.decimals().call()
                except Exception:
                    u_dec = share_dec

                shares_human = _fmt(shares, share_dec)
                assets_human = _fmt(assets, u_dec)

                rows.append({
                    "chain": chain, "protocol": "euler", "wallet": wallet,
                    "position_label": _get_display_name(entry, vault_addr, entry_key),
                    "category": "A1", "position_type": "vault_share",
                    "token_symbol": entry_key,
                    "token_contract": vault_addr,
                    "balance_raw": str(shares),
                    "balance_human": shares_human,
                    "decimals": share_dec,
                    "exchange_rate": assets_human / shares_human if shares_human > 0 else Decimal(0),
                    "underlying_amount": assets_human,
                    "underlying_symbol": _get_underlying_symbol(entry, vault_addr, "syrupUSDC"),
                    "euler_sub_account": sub_id,
                    "euler_sub_address": sub_addr.lower(),
                    "block_number": block_number, "block_timestamp_utc": block_ts,
                })
                found = True
                break  # found the active sub-account

    return rows
