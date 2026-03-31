"""Ethena sUSDe Cooldowns handler (pending unstakes)."""

import logging
from datetime import datetime, timezone
from web3 import Web3

from handlers import _load_contracts_cfg, _get_abi, _fmt

logger = logging.getLogger(__name__)


def query_ethena_cooldowns(w3, chain, wallet, block_number, block_ts):
    """Query Ethena sUSDe cooldown (pending unstakes).
    Reads sUSDe address from contracts.json _ethena section.
    """
    contracts = _load_contracts_cfg()
    ethena_section = contracts.get(chain, {}).get("_ethena", {})
    susde_entry = ethena_section.get("susde", {})
    susde_addr = susde_entry.get("address")
    usde_addr = susde_entry.get("usde_token")
    if not usde_addr:
        return []
    if not susde_addr:
        return []

    # ABI defined in config/abis.json as "ethena_cooldown"
    susde = w3.eth.contract(address=Web3.to_checksum_address(susde_addr), abi=_get_abi("ethena_cooldown"))

    try:
        result = susde.functions.cooldowns(Web3.to_checksum_address(wallet)).call(block_identifier=block_number)
        cooldown_end, underlying = result
        logger.info("ethena.cooldowns(%s, %s) block=%s → end=%s, amount=%s",
                     susde_addr, wallet, block_number, cooldown_end, underlying)
    except Exception:
        return []

    if underlying == 0:
        return []

    amount = _fmt(underlying, 18)
    end_ts = datetime.fromtimestamp(cooldown_end, tz=timezone.utc) if cooldown_end > 0 else None
    claimable = end_ts and end_ts < datetime.now(timezone.utc)

    return [{
        "chain": chain, "protocol": "ethena", "wallet": wallet,
        "position_label": "Ethena sUSDe Cooldown",
        "category": "E", "position_type": "token_balance",
        "token_symbol": "USDe",
        "token_contract": usde_addr,
        "balance_human": amount,
        "decimals": 18,
        "block_number": block_number, "block_timestamp_utc": block_ts,
        "notes": f"Pending unstake from sUSDe. Cooldown ended {end_ts}. {'Claimable' if claimable else 'Locked'}.",
    }]
