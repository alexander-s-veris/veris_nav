"""Curve LP handler (Category C — LP decomposition).

Decomposes Curve LP token holdings into underlying token constituents
based on the holder's pro-rata share of the pool. Each constituent
is priced per its own category.

Per Valuation Policy Section 6.5: value reflects actual token amounts
within the position at the Valuation Block.
"""

import logging
from decimal import Decimal
from web3 import Web3

from handlers import _load_contracts_cfg, _get_abi, _fmt

logger = logging.getLogger(__name__)

_POOL_ABI = [
    {"inputs": [], "name": "get_virtual_price",
     "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "i", "type": "uint256"}], "name": "coins",
     "outputs": [{"name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "i", "type": "uint256"}], "name": "balances",
     "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply",
     "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
]

_ERC20_ABI = [
    {"inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol",
     "outputs": [{"name": "", "type": "string"}],
     "stateMutability": "view", "type": "function"},
]


def query_curve_lp(w3, chain, wallet, block_number, block_ts):
    """Query Curve LP positions and decompose into underlying constituents."""
    contracts = _load_contracts_cfg()
    curve_section = contracts.get(chain, {}).get("_curve", {})

    rows = []
    for pool_key, pool_cfg in curve_section.items():
        if not isinstance(pool_cfg, dict) or pool_key.startswith("_"):
            continue

        pool_addr = pool_cfg.get("address")
        if not pool_addr:
            continue

        pool = w3.eth.contract(
            address=Web3.to_checksum_address(pool_addr), abi=_POOL_ABI)

        # Check if wallet holds LP tokens
        lp_balance = pool.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
        if lp_balance == 0:
            continue

        lp_decimals = pool.functions.decimals().call()
        total_supply = pool.functions.totalSupply().call()
        lp_balance_human = Decimal(str(lp_balance)) / Decimal(10**lp_decimals)
        share = Decimal(str(lp_balance)) / Decimal(str(total_supply))

        logger.info("curve.balanceOf(%s, %s) block=%s -> %s (share=%.6f%%)",
                     pool_addr[:10], wallet[:10], block_number, lp_balance_human, float(share * 100))

        pool_label = pool_cfg.get("pool_label", pool_key.replace("_", " ").title())

        # Dedup marker — ensures the raw LP token wallet balance is suppressed.
        # This row carries no value (constituents carry the value), filtered in output.
        rows.append({
            "chain": chain, "protocol": "curve", "wallet": wallet,
            "position_label": f"Curve {pool_label}",
            "category": "C", "position_type": "lp_parent",
            "token_symbol": pool_cfg.get("lp_symbol", pool_key),
            "token_contract": pool_addr,
            "balance_human": Decimal(0),
            "block_number": block_number, "block_timestamp_utc": block_ts,
        })

        # Enumerate coins in the pool
        for i in range(8):  # Curve pools have at most 8 coins
            try:
                coin_addr = pool.functions.coins(i).call()
                coin_balance = pool.functions.balances(i).call()
            except Exception:
                break

            # Get coin metadata
            coin = w3.eth.contract(address=coin_addr, abi=_ERC20_ABI)
            try:
                coin_decimals = coin.functions.decimals().call()
                coin_symbol = coin.functions.symbol().call()
            except Exception:
                coin_decimals = 18
                coin_symbol = f"coin{i}"

            # Our pro-rata share of this coin
            our_amount = Decimal(str(coin_balance)) / Decimal(10**coin_decimals) * share

            if our_amount <= 0:
                continue

            logger.info("curve: %s coin[%d] %s = %s (our share: %s)",
                         pool_key, i, coin_symbol, coin_balance, our_amount)

            rows.append({
                "chain": chain, "protocol": "curve", "wallet": wallet,
                "position_label": f"Curve {pool_label}",
                "category": "C", "position_type": "lp_constituent",
                "token_symbol": coin_symbol,
                "token_contract": coin_addr,
                "balance_human": our_amount,
                "lp_constituent_type": f"coin{i}",
                "lp_share": str(share),
                "block_number": block_number, "block_timestamp_utc": block_ts,
                "notes": f"Curve {pool_label}. LP share: {share*100:.4f}%.",
            })

    return rows
