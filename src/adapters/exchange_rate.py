"""A1 exchange rate adapter — generic on-chain exchange rate pricing.

Queries a vault/token contract for its exchange rate, then prices the
underlying token. Token-agnostic: all config comes from token_entry.

Supports two patterns:
1. ERC-4626 convertToAssets — standard vault interface
2. Custom exchange rate function (e.g., eUSX vault ratio)
"""

from decimal import Decimal
from datetime import datetime, timezone

from web3 import Web3

from evm import TS_FMT


def a1_exchange_rate_price(token_entry: dict, w3_eth: Web3 | None = None,
                           price_underlying_fn=None) -> dict:
    """Price an A1 token via on-chain exchange rate × underlying price.

    Args:
        token_entry: Token config with pricing.exchange_rate_contract,
                     pricing.exchange_rate_function, pricing.underlying,
                     pricing.exchange_rate_chain, pricing.decimals_shares,
                     pricing.decimals_underlying.
        w3_eth: Web3 instance (Ethereum default).
        price_underlying_fn: Optional callable(symbol) -> Decimal price.
                             Used to price the underlying token. If None,
                             underlying is assumed at par ($1.00).
    """
    pricing = token_entry.get("pricing", {})
    symbol = token_entry.get("symbol", "UNKNOWN")

    exchange_rate_source = pricing.get("exchange_rate_source")
    contract_addr = pricing.get("exchange_rate_contract")
    function_name = pricing.get("exchange_rate_function", "convertToAssets")
    chain = pricing.get("exchange_rate_chain", "ethereum")
    decimals_shares = pricing.get("decimals_shares", 18)
    decimals_underlying = pricing.get("decimals_underlying")
    underlying_symbol = pricing.get("underlying", "USDC")

    # Solana vault ratio (eUSX-style): custom exchange rate function
    if exchange_rate_source == "solana_vault_ratio":
        return _solana_vault_ratio_price(pricing, symbol, price_underlying_fn)

    if not contract_addr:
        return _unavailable(symbol, "no exchange_rate_contract configured")

    # Get the right Web3 instance
    w3 = w3_eth
    if chain != "ethereum":
        try:
            from evm import get_web3
            w3 = get_web3(chain)
        except Exception as e:
            return _unavailable(symbol, f"cannot connect to {chain}: {e}")

    if not w3:
        return _unavailable(symbol, f"no Web3 for {chain}")

    try:
        # Standard ERC-4626 convertToAssets
        abi = [{"inputs": [{"name": "shares", "type": "uint256"}],
                "name": function_name,
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view", "type": "function"}]

        vault = w3.eth.contract(
            address=Web3.to_checksum_address(contract_addr), abi=abi)

        # Query exchange rate: assets per 1 full share
        one_share = 10 ** decimals_shares
        assets = getattr(vault.functions, function_name)(one_share).call()

        # Determine underlying decimals
        if decimals_underlying is None:
            # Try to read from vault.asset().decimals()
            try:
                asset_abi = [{"inputs": [], "name": "asset",
                              "outputs": [{"name": "", "type": "address"}],
                              "stateMutability": "view", "type": "function"}]
                asset_contract = w3.eth.contract(
                    address=Web3.to_checksum_address(contract_addr), abi=asset_abi)
                asset_addr = asset_contract.functions.asset().call()
                dec_abi = [{"inputs": [], "name": "decimals",
                            "outputs": [{"name": "", "type": "uint8"}],
                            "stateMutability": "view", "type": "function"}]
                underlying_token = w3.eth.contract(
                    address=Web3.to_checksum_address(asset_addr), abi=dec_abi)
                decimals_underlying = underlying_token.functions.decimals().call()
            except Exception:
                decimals_underlying = decimals_shares

        exchange_rate = Decimal(str(assets)) / Decimal(10 ** decimals_underlying)

        # Price the underlying
        underlying_price = Decimal(1)  # default: par
        underlying_source = "par"
        if price_underlying_fn:
            try:
                underlying_price = price_underlying_fn(underlying_symbol)
                underlying_source = "oracle"
            except Exception:
                pass

        price = exchange_rate * underlying_price

        return {
            "price_usd": price,
            "price_source": f"a1_{function_name} (rate={exchange_rate:.6f}) x {underlying_source}",
            "depeg_flag": "none",
            "depeg_deviation_pct": None,
            "oracle_updated_at": None,
            "staleness_hours": None,
            "stale_flag": "",
            "notes": f"{symbol} rate: {exchange_rate:.6f}, {underlying_symbol} at {underlying_price}",
        }

    except Exception as e:
        return _unavailable(symbol, str(e))


def _solana_vault_ratio_price(pricing: dict, symbol: str, price_underlying_fn=None) -> dict:
    """Price a Solana token via vault ratio (total underlying / total supply)."""
    from solana_client import get_eusx_exchange_rate
    from adapters.pyth import pyth_price

    underlying_feed = pricing.get("underlying_pyth_feed_id")
    underlying_symbol = pricing.get("underlying", "USX")

    try:
        exchange_rate = get_eusx_exchange_rate()

        # Price underlying via Pyth feed if configured
        if underlying_feed:
            underlying_result = pyth_price(underlying_feed)
            underlying_price = underlying_result["price_usd"]
        elif price_underlying_fn:
            underlying_price = price_underlying_fn(underlying_symbol)
        else:
            underlying_price = Decimal(1)

        price = exchange_rate * underlying_price

        return {
            "price_usd": price,
            "price_source": f"a1_vault_ratio (rate={exchange_rate:.6f}) x underlying",
            "depeg_flag": "none",
            "depeg_deviation_pct": None,
            "oracle_updated_at": None,
            "staleness_hours": None,
            "stale_flag": "",
            "notes": f"{symbol} rate: {exchange_rate:.6f}, {underlying_symbol} at {underlying_price}",
        }
    except Exception as e:
        return _unavailable(symbol, str(e))


def _unavailable(symbol: str, reason: str = "") -> dict:
    return {
        "price_usd": Decimal("0"),
        "price_source": "unavailable",
        "depeg_flag": "none",
        "depeg_deviation_pct": None,
        "oracle_updated_at": None,
        "staleness_hours": None,
        "stale_flag": "",
        "notes": f"A1 exchange rate failed for {symbol}: {reason}" if reason else f"No price for {symbol}",
    }
