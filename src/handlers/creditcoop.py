"""CreditCoop handler (Category A1)."""

import logging
from decimal import Decimal
from web3 import Web3

from handlers import _load_contracts_cfg, _get_abi, _fmt

logger = logging.getLogger(__name__)


def query_creditcoop(w3, chain, wallet, block_number, block_ts):
    """Query CreditCoop vault -- ERC-4626 convertToAssets + sub-strategy breakdown.

    Returns:
    - Main A1 position (aggregate via convertToAssets)
    - Sub-strategy breakdown rows for methodology log:
      - Rain credit line (totalActiveCredit on CreditStrategy)
      - Gauntlet USDC Core (totalAssets on LiquidStrategy)
      - Undeployed cash (USDC balanceOf on vault + credit strategy)
    """
    contracts = _load_contracts_cfg()
    cc_section = contracts.get(chain, {}).get("_credit_coop", {})
    vault_cfg = cc_section.get("vault", {})
    VAULT = vault_cfg.get("address")
    vault_decimals = vault_cfg.get("decimals")
    underlying_decimals = cc_section.get("underlying_decimals")
    if vault_decimals is None or underlying_decimals is None:
        raise ValueError("CreditCoop config missing required 'decimals' or 'underlying_decimals' in contracts.json")
    LIQUID_STRATEGY = cc_section.get("liquid_strategy", {}).get("address")
    CREDIT_STRATEGY = cc_section.get("credit_strategy", {}).get("address")
    GAUNTLET_CORE = cc_section.get("gauntlet_usdc_core", {}).get("address")
    USDC = cc_section.get("usdc_token", {}).get("address")
    if not VAULT:
        return []

    erc20_abi = _get_abi("erc20")
    erc4626_abi = _get_abi("erc4626")

    vault = w3.eth.contract(
        address=Web3.to_checksum_address(VAULT), abi=erc4626_abi)

    shares = vault.functions.balanceOf(Web3.to_checksum_address(wallet)).call(block_identifier=block_number)
    logger.info("creditcoop.balanceOf(%s, %s) block=%s → %s", VAULT, wallet, block_number, shares)
    if shares == 0:
        return []

    assets = vault.functions.convertToAssets(shares).call(block_identifier=block_number)
    logger.info("creditcoop.convertToAssets(%s, shares=%s) block=%s → %s", VAULT, shares, block_number, assets)
    shares_human = _fmt(shares, vault_decimals)
    assets_human = _fmt(assets, underlying_decimals)

    rows = [{
        "chain": chain, "protocol": "credit_coop", "wallet": wallet,
        "position_label": "Credit Coop Veris Vault",
        "category": "A1", "position_type": "vault_share",
        "token_symbol": "ccVaultUSDC",
        "token_contract": VAULT,
        "balance_raw": str(shares),
        "balance_human": shares_human,
        "decimals": vault_decimals,
        "exchange_rate": assets_human / shares_human if shares_human > 0 else Decimal(0),
        "underlying_amount": assets_human,
        "underlying_symbol": "USDC",
        "block_number": block_number, "block_timestamp_utc": block_ts,
    }]

    # Sub-strategy breakdown
    # Rain credit + Gauntlet deployed + idle cash = aggregate convertToAssets
    try:
        # Rain credit line (principal + uncollected interest)
        credit = w3.eth.contract(
            address=Web3.to_checksum_address(CREDIT_STRATEGY),
            abi=_get_abi("credit_coop_credit_strategy"))
        rain_amount = _fmt(credit.functions.totalActiveCredit().call(block_identifier=block_number), underlying_decimals)
        logger.info("creditcoop.totalActiveCredit(%s) block=%s → %s", CREDIT_STRATEGY, block_number, rain_amount)

        # Gauntlet USDC Core — actual amount deployed via LiquidStrategy
        gauntlet_deployed = Decimal(0)
        if GAUNTLET_CORE and LIQUID_STRATEGY:
            gauntlet = w3.eth.contract(
                address=Web3.to_checksum_address(GAUNTLET_CORE), abi=erc4626_abi)
            liq_shares = gauntlet.functions.balanceOf(Web3.to_checksum_address(LIQUID_STRATEGY)).call(block_identifier=block_number)
            if liq_shares > 0:
                gauntlet_deployed = _fmt(gauntlet.functions.convertToAssets(liq_shares).call(block_identifier=block_number), underlying_decimals)
            logger.info("creditcoop.gauntlet_deployed(%s) block=%s → %s", GAUNTLET_CORE[:10], block_number, gauntlet_deployed)

        # Credit strategy cash (USDC idle in credit strategy contract)
        usdc = w3.eth.contract(
            address=Web3.to_checksum_address(USDC), abi=erc20_abi)
        credit_cash = _fmt(usdc.functions.balanceOf(Web3.to_checksum_address(CREDIT_STRATEGY)).call(block_identifier=block_number), underlying_decimals)

        # Vault cash = USDC in vault contract + LiquidStrategy idle (totalAssets - gauntlet deployed)
        vault_usdc = _fmt(usdc.functions.balanceOf(Web3.to_checksum_address(VAULT)).call(block_identifier=block_number), underlying_decimals)
        liquid = w3.eth.contract(
            address=Web3.to_checksum_address(LIQUID_STRATEGY),
            abi=_get_abi("credit_coop_liquid_strategy"))
        liquid_total = _fmt(liquid.functions.totalAssets().call(block_identifier=block_number), underlying_decimals)
        vault_cash = vault_usdc + (liquid_total - gauntlet_deployed)

        rows[0]["_breakdown"] = {
            "rain_credit_line": str(rain_amount),
            "gauntlet_usdc_core": str(gauntlet_deployed),
            "vault_cash": str(vault_cash),
            "credit_strategy_cash": str(credit_cash),
        }
        rows[0]["notes"] = (
            f"Breakdown: Rain credit={rain_amount:,.2f}, "
            f"Gauntlet USDC Core={gauntlet_deployed:,.2f}, "
            f"vault cash={vault_cash:,.2f}, "
            f"credit cash={credit_cash:,.2f}"
        )
    except Exception as e:
        rows[0]["notes"] = f"Sub-strategy breakdown failed: {e}"

    return rows
