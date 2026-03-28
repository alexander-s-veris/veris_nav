"""CreditCoop handler (Category A1)."""

from decimal import Decimal
from web3 import Web3

from handlers import _load_contracts_cfg, _get_abi, _fmt


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
    VAULT = cc_section.get("vault", {}).get("address")
    LIQUID_STRATEGY = cc_section.get("liquid_strategy", {}).get("address")
    CREDIT_STRATEGY = cc_section.get("credit_strategy", {}).get("address")
    USDC = cc_section.get("usdc_token", {}).get("address")
    if not VAULT:
        return []

    erc20_abi = _get_abi("erc20")
    erc4626_abi = _get_abi("erc4626")

    vault = w3.eth.contract(
        address=Web3.to_checksum_address(VAULT), abi=erc4626_abi)

    shares = vault.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
    if shares == 0:
        return []

    assets = vault.functions.convertToAssets(shares).call()
    shares_human = _fmt(shares, 6)
    assets_human = _fmt(assets, 6)

    rows = [{
        "chain": chain, "protocol": "credit_coop", "wallet": wallet,
        "position_label": "Credit Coop Veris Vault",
        "category": "A1", "position_type": "vault_share",
        "token_symbol": "ccVaultUSDC",
        "token_contract": VAULT,
        "balance_raw": str(shares),
        "balance_human": shares_human,
        "decimals": 6,
        "exchange_rate": assets_human / shares_human if shares_human > 0 else Decimal(0),
        "underlying_amount": assets_human,
        "underlying_symbol": "USDC",
        "block_number": block_number, "block_timestamp_utc": block_ts,
    }]

    # Sub-strategy breakdown (for methodology log, not separate NAV rows)
    # These are informational -- the aggregate convertToAssets is the primary value
    TOTAL_ASSETS_ABI = [{"inputs": [], "name": "totalAssets",
                         "outputs": [{"name": "", "type": "uint256"}],
                         "stateMutability": "view", "type": "function"}]
    TOTAL_ACTIVE_CREDIT_ABI = [{"inputs": [], "name": "totalActiveCredit",
                                "outputs": [{"name": "", "type": "uint256"}],
                                "stateMutability": "view", "type": "function"}]

    try:
        # Rain credit line (principal + uncollected interest)
        credit = w3.eth.contract(
            address=Web3.to_checksum_address(CREDIT_STRATEGY),
            abi=TOTAL_ACTIVE_CREDIT_ABI)
        credit_amount = _fmt(credit.functions.totalActiveCredit().call(), 6)

        # Gauntlet USDC Core liquid reserve
        liquid = w3.eth.contract(
            address=Web3.to_checksum_address(LIQUID_STRATEGY),
            abi=TOTAL_ASSETS_ABI)
        liquid_amount = _fmt(liquid.functions.totalAssets().call(), 6)

        # Undeployed cash in vault
        usdc = w3.eth.contract(
            address=Web3.to_checksum_address(USDC), abi=erc20_abi)
        vault_cash = _fmt(usdc.functions.balanceOf(Web3.to_checksum_address(VAULT)).call(), 6)
        credit_cash = _fmt(usdc.functions.balanceOf(Web3.to_checksum_address(CREDIT_STRATEGY)).call(), 6)

        rows[0]["_breakdown"] = {
            "rain_credit_line": str(credit_amount),
            "gauntlet_usdc_core": str(liquid_amount),
            "vault_cash": str(vault_cash),
            "credit_strategy_cash": str(credit_cash),
        }
        rows[0]["notes"] = (
            f"Breakdown: Rain credit={credit_amount:,.2f}, "
            f"Gauntlet USDC Core={liquid_amount:,.2f}, "
            f"vault cash={vault_cash:,.2f}, "
            f"credit cash={credit_cash:,.2f}"
        )
    except Exception as e:
        rows[0]["notes"] = f"Sub-strategy breakdown failed: {e}"

    return rows
