"""CreditCoop handler (Category A1).

Dynamically discovers sub-strategies from on-chain contract state:
  - vault.liquidStrategy() / vault.creditStrategy() for strategy addresses
  - liquidStrategy.vaults(i) for iterating deployed ERC-4626 vaults
  - CreditStrategy.totalActiveCredit() for Rain credit line
  - USDC balanceOf for idle cash in each contract

Returns one aggregate A1 row (convertToAssets) plus sub-strategy breakdown rows.
"""

import logging
from decimal import Decimal
from web3 import Web3

from handlers import _load_contracts_cfg, _get_abi, _fmt
from handlers._registry import register_evm_handler

logger = logging.getLogger(__name__)

# Minimal ABIs for on-chain discovery (not in abis.json — structural, not config)
_VAULT_DISCOVERY_ABI = [
    {"inputs": [], "name": "liquidStrategy", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "creditStrategy", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalLiquidAssets", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

_LIQUID_VAULTS_ABI = [
    {"inputs": [{"name": "", "type": "uint256"}], "name": "vaults", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalAssets", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

_CREDIT_STRATEGY_ABI = [
    {"inputs": [], "name": "totalActiveCredit", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "numCreditPositions", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

_ERC20_NAME_ABI = [
    {"inputs": [], "name": "name", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
]


def _discover_liquid_vaults(w3, liquid_strategy_addr, block_number):
    """Iterate liquidStrategy.vaults(i) until revert to discover all sub-vaults."""
    c = w3.eth.contract(
        address=Web3.to_checksum_address(liquid_strategy_addr),
        abi=_LIQUID_VAULTS_ABI)
    vaults = []
    for i in range(20):  # safety cap
        try:
            addr = c.functions.vaults(i).call(block_identifier=block_number)
            vaults.append(addr)
        except Exception:
            break
    return vaults


@register_evm_handler("credit_coop", query_type="credit_coop", display_name="Credit Coop")
def query_creditcoop(w3, chain, wallet, block_number, block_ts):
    """Query CreditCoop vault -- ERC-4626 convertToAssets + dynamic sub-strategy breakdown.

    Returns:
    - Main A1 position (aggregate via convertToAssets)
    - Sub-strategy breakdown rows (position_type="vault_breakdown"):
      - Rain credit line (totalActiveCredit on CreditStrategy)
      - Each ERC-4626 vault discovered via liquidStrategy.vaults(i)
      - Undeployed cash (USDC balanceOf on vault + liquid strategy + credit strategy)
    """
    contracts = _load_contracts_cfg()
    cc_section = contracts.get(chain, {}).get("_credit_coop", {})
    vault_cfg = cc_section.get("vault", {})
    VAULT = vault_cfg.get("address")
    vault_decimals = vault_cfg.get("decimals")
    underlying_decimals = cc_section.get("underlying_decimals")
    if vault_decimals is None or underlying_decimals is None:
        raise ValueError("CreditCoop config missing required 'decimals' or 'underlying_decimals' in contracts.json")
    if not VAULT:
        return []

    erc20_abi = _get_abi("erc20")
    erc4626_abi = _get_abi("erc4626")

    vault = w3.eth.contract(
        address=Web3.to_checksum_address(VAULT), abi=erc4626_abi + _VAULT_DISCOVERY_ABI)

    shares = vault.functions.balanceOf(Web3.to_checksum_address(wallet)).call(block_identifier=block_number)
    logger.info("creditcoop.balanceOf(%s, %s) block=%s → %s", VAULT, wallet, block_number, shares)
    if shares == 0:
        return []

    total_supply = vault.functions.totalSupply().call(block_identifier=block_number)
    assets = vault.functions.convertToAssets(shares).call(block_identifier=block_number)
    logger.info("creditcoop.convertToAssets(%s, shares=%s) block=%s → %s", VAULT, shares, block_number, assets)
    shares_human = _fmt(shares, vault_decimals)
    assets_human = _fmt(assets, underlying_decimals)

    # Our pro-rata ownership of the vault (for scaling breakdown rows)
    our_share = Decimal(str(shares)) / Decimal(str(total_supply)) if total_supply > 0 else Decimal(1)
    logger.info("creditcoop: ownership share = %s / %s = %.6f%%", shares, total_supply, float(our_share * 100))

    # Common fields for all rows
    base = {
        "chain": chain, "protocol": "credit_coop", "wallet": wallet,
        "block_number": block_number, "block_timestamp_utc": block_ts,
        "underlying_symbol": "USDC",
    }

    # Aggregate A1 row
    aggregate_row = {
        **base,
        "position_label": "Credit Coop Veris Vault",
        "category": "A1", "position_type": "vault_share",
        "token_symbol": "ccVaultUSDC",
        "token_contract": VAULT,
        "balance_raw": str(shares),
        "balance_human": shares_human,
        "decimals": vault_decimals,
        "exchange_rate": assets_human / shares_human if shares_human > 0 else Decimal(0),
        "underlying_amount": assets_human,
    }

    rows = [aggregate_row]

    # --- Dynamic sub-strategy breakdown ---
    try:
        # Discover strategy addresses from the vault contract
        liquid_strategy_addr = vault.functions.liquidStrategy().call(block_identifier=block_number)
        credit_strategy_addr = vault.functions.creditStrategy().call(block_identifier=block_number)
        logger.info("creditcoop: liquidStrategy=%s, creditStrategy=%s", liquid_strategy_addr, credit_strategy_addr)

        usdc_addr = vault.functions.asset().call(block_identifier=block_number)
        usdc = w3.eth.contract(address=Web3.to_checksum_address(usdc_addr), abi=erc20_abi)

        # 1. Rain credit line
        credit = w3.eth.contract(
            address=Web3.to_checksum_address(credit_strategy_addr),
            abi=_CREDIT_STRATEGY_ABI)
        rain_total = _fmt(
            credit.functions.totalActiveCredit().call(block_identifier=block_number),
            underlying_decimals)
        rain_amount = rain_total * our_share
        logger.info("creditcoop.totalActiveCredit(%s) block=%s → total=%s, ours=%s",
                     credit_strategy_addr[:10], block_number, rain_total, rain_amount)

        rows.append({
            **base,
            "position_label": "Credit Coop — Rain Credit Line",
            "category": "A1", "position_type": "vault_breakdown",
            "token_symbol": "USDC",
            "token_contract": credit_strategy_addr,
            "balance_human": rain_amount,
            "underlying_amount": rain_amount,
        })

        # 2. Dynamically discover ERC-4626 vaults from LiquidStrategy
        liquid_vaults = _discover_liquid_vaults(w3, liquid_strategy_addr, block_number)
        logger.info("creditcoop: discovered %d liquid vaults: %s",
                     len(liquid_vaults), [v[:10] for v in liquid_vaults])

        liquid_c = w3.eth.contract(
            address=Web3.to_checksum_address(liquid_strategy_addr), abi=_LIQUID_VAULTS_ABI)
        liquid_total = _fmt(
            liquid_c.functions.totalAssets().call(block_identifier=block_number),
            underlying_decimals)

        total_vault_deployed = Decimal(0)
        for vault_addr in liquid_vaults:
            sub_vault = w3.eth.contract(
                address=Web3.to_checksum_address(vault_addr),
                abi=erc4626_abi + _ERC20_NAME_ABI)

            liq_shares = sub_vault.functions.balanceOf(
                Web3.to_checksum_address(liquid_strategy_addr)
            ).call(block_identifier=block_number)

            deployed_total = Decimal(0)
            if liq_shares > 0:
                deployed_total = _fmt(
                    sub_vault.functions.convertToAssets(liq_shares).call(block_identifier=block_number),
                    underlying_decimals)
            deployed = deployed_total * our_share
            total_vault_deployed += deployed_total

            # Get vault name for labeling
            try:
                vault_name = sub_vault.functions.name().call(block_identifier=block_number)
            except Exception:
                vault_name = vault_addr[:10]

            logger.info("creditcoop: %s (%s) deployed=%s", vault_name, vault_addr[:10], deployed)

            rows.append({
                **base,
                "position_label": f"Credit Coop — {vault_name}",
                "category": "A1", "position_type": "vault_breakdown",
                "token_symbol": "USDC",
                "token_contract": vault_addr,
                "balance_human": deployed,
                "underlying_amount": deployed,
            })

        # 3. Cash: vault USDC + liquid strategy idle + credit strategy USDC
        vault_usdc_total = _fmt(
            usdc.functions.balanceOf(Web3.to_checksum_address(VAULT)).call(block_identifier=block_number),
            underlying_decimals)
        liquid_idle_total = liquid_total - total_vault_deployed
        credit_cash_total = _fmt(
            usdc.functions.balanceOf(Web3.to_checksum_address(credit_strategy_addr)).call(block_identifier=block_number),
            underlying_decimals)
        total_cash = (vault_usdc_total + liquid_idle_total + credit_cash_total) * our_share

        logger.info("creditcoop: cash (total): vault=%s, liquid_idle=%s, credit=%s; ours=%s",
                     vault_usdc_total, liquid_idle_total, credit_cash_total, total_cash)

        rows.append({
            **base,
            "position_label": "Credit Coop — Cash",
            "category": "A1", "position_type": "vault_breakdown",
            "token_symbol": "USDC",
            "token_contract": usdc_addr,
            "balance_human": total_cash,
            "underlying_amount": total_cash,
        })

        # Store structured breakdown on aggregate row (all values are our pro-rata share)
        breakdown = {
            "rain_credit_line": str(rain_amount),
            "total_cash": str(total_cash),
            "ownership_share": str(our_share),
        }
        for v_addr, deployed_row in zip(liquid_vaults, rows[2:2 + len(liquid_vaults)]):
            label = deployed_row["position_label"].replace("Credit Coop — ", "")
            breakdown[label] = str(deployed_row["balance_human"])

        aggregate_row["_breakdown"] = breakdown

    except Exception as e:
        logger.exception("creditcoop: sub-strategy breakdown failed")

    return rows
