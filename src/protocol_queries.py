"""
Protocol position query functions for the Veris NAV collection system.

Queries on-chain positions across all protocols (Morpho, Aave, Euler, ERC-4626
vaults, Kamino, Exponent) and returns standardised position dicts. Each function
is config-driven — it reads from contracts.json, morpho_markets.json, etc.

Position dicts are NOT priced here — valuation.py handles pricing.
"""

import json
import math
import os
import sys
import time
from decimal import Decimal

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from evm import CONFIG_DIR, get_web3, get_block_info, TS_FMT
from solana_client import (
    solana_rpc, get_kamino_obligation, get_eusx_exchange_rate,
    get_exponent_lp_positions, get_exponent_yt_positions,
    get_exponent_market, decompose_exponent_lp, get_token_supply,
)
from pt_valuation import value_pt_from_config
from web3 import Web3


# Vault/contract → clean display name (for position labels)
_DISPLAY_NAMES = {
    "0xbeeff047c03714965a54b671a37c18bef6b96210": "Steakhouse Reservoir USDC",
    "0xbeef047a543e45807105e51a8bbefcc5950fcfba": "Steakhouse USDT",
    "0x1d3b1cd0a0f242d598834b3f2d126dc6bd774657": "Clearstar USDC Reactor",
    "0x944766f715b51967e56afde5f0aa76ceacc9e7f9": "Avantis USDC",
    "0x80c34bd3a3569e126e7055831036aa7b212cb159": "Yearn V3 vbUSDC",
    "0xb21eafb126cef15cb99fe2d23989b58e40097919": "Credit Coop Veris Vault",
    "0xa999f8a38a902f27f278358c4bd20fe1459ae47c": "Euler esyrupUSDC",
    "0x777791c4d6dc2ce140d00d2828a7c93503c67777": "Hyperithm USDC Apex",
    # Aave aTokens
    "0x08b798c40b9ab931356d9ab4235f548325c4cb80": "Aave Horizon USCC",
    "0xace8a1c0ec12ae81814377491265b47f4ee5d3dd": "Aave Horizon RLUSD debt",
    "0xd7424238ccbe7b7198ab3cfe232e0271e22da7bd": "Aave Base syrupUSDC",
    "0x7519403e12111ff6b710877fcd821d0c12caf43a": "Aave Plasma USDe",
    "0xc1a318493ff07a68fe438cee60a7ad0d0dba300e": "Aave Plasma sUSDe",
}

# Vault address → underlying token symbol (for A1 valuation pricing)
_VAULT_UNDERLYING = {
    "0xbeeff047c03714965a54b671a37c18bef6b96210": "USDC",    # Steakhouse Reservoir USDC
    "0xbeef047a543e45807105e51a8bbefcc5950fcfba": "USDT",    # Steakhouse USDT
    "0x1d3b1cd0a0f242d598834b3f2d126dc6bd774657": "USDC",    # Clearstar USDC Reactor
    "0x944766f715b51967e56afde5f0aa76ceacc9e7f9": "USDC",    # Avantis avUSDC
    "0x80c34bd3a3569e126e7055831036aa7b212cb159": "USDC",    # Yearn V3 vbUSDC
    "0xb21eafb126cef15cb99fe2d23989b58e40097919": "USDC",    # CreditCoop Vault
    "0xa999f8a38a902f27f278358c4bd20fe1459ae47c": "syrupUSDC",  # Euler esyrupUSDC
    "0x777791c4d6dc2ce140d00d2828a7c93503c67777": "USDC",       # Hyperithm USDC Apex
}


def _fmt(val, decimals):
    """Convert raw uint256 to human-readable Decimal."""
    return Decimal(str(val)) / Decimal(10 ** decimals)


def _load_abis():
    """Load all ABIs from config/abis.json."""
    with open(os.path.join(CONFIG_DIR, "abis.json")) as f:
        return json.load(f)


_ABIS = None

def _get_abi(name):
    global _ABIS
    if _ABIS is None:
        _ABIS = _load_abis()
    return _ABIS[name]


# =============================================================================
# EVM: Morpho Markets (Category D)
# =============================================================================

def query_morpho_markets(w3, chain, wallet, block_number, block_ts):
    """Query all Morpho leveraged market positions for a wallet on a chain.

    Reads market configs from morpho_markets.json. Returns two rows per active
    position: collateral (positive) and debt (negative).
    """
    morpho_cfg = _load_morpho_cfg()
    chain_cfg = morpho_cfg.get(chain, {})
    morpho_addr = chain_cfg.get("morpho_contract")
    if not morpho_addr:
        return []

    markets = [m for m in chain_cfg.get("markets", [])
               if wallet.lower() in [w.lower() for w in m.get("wallets", [])]]
    if not markets:
        return []

    morpho = w3.eth.contract(
        address=Web3.to_checksum_address(morpho_addr), abi=_get_abi("morpho_core"))

    rows = []
    for mkt in markets:
        market_id = bytes.fromhex(mkt["market_id"][2:])
        is_closed = "_note" in mkt and "Closed" in mkt.get("_note", "")

        pos = morpho.functions.position(
            market_id, Web3.to_checksum_address(wallet)).call()
        supply_shares, borrow_shares, collateral = pos

        # Check if actually closed
        if is_closed and collateral == 0 and borrow_shares == 0:
            rows.append({
                "chain": chain, "protocol": "morpho", "wallet": wallet,
                "position_label": mkt["name"], "category": "D",
                "position_type": "closed", "status": "CLOSED",
                "block_number": block_number, "block_timestamp_utc": block_ts,
            })
            continue

        # Get market state for shares → assets conversion
        mkt_state = morpho.functions.market(market_id).call()
        total_borrow_assets, total_borrow_shares = mkt_state[2], mkt_state[3]
        borrow_assets = (
            borrow_shares * total_borrow_assets // total_borrow_shares
            if total_borrow_shares > 0 else 0
        )

        coll_token = mkt["collateral_token"]
        loan_token = mkt["loan_token"]

        # Collateral row
        coll_human = _fmt(collateral, coll_token["decimals"])
        rows.append({
            "chain": chain, "protocol": "morpho", "wallet": wallet,
            "position_label": mkt["name"], "category": "D",
            "position_type": "collateral",
            "token_symbol": coll_token["symbol"],
            "token_contract": coll_token["address"],
            "token_category": coll_token["category"],
            "balance_raw": str(collateral),
            "balance_human": coll_human,
            "decimals": coll_token["decimals"],
            "block_number": block_number, "block_timestamp_utc": block_ts,
            "leverage_market_id": mkt["market_id"],
        })

        # Debt row (negative)
        borrow_human = _fmt(borrow_assets, loan_token["decimals"])
        rows.append({
            "chain": chain, "protocol": "morpho", "wallet": wallet,
            "position_label": mkt["name"], "category": "D",
            "position_type": "debt",
            "token_symbol": loan_token["symbol"],
            "token_contract": loan_token["address"],
            "token_category": loan_token["category"],
            "balance_raw": str(borrow_assets),
            "balance_human": -borrow_human,  # negative for debt
            "decimals": loan_token["decimals"],
            "block_number": block_number, "block_timestamp_utc": block_ts,
            "leverage_market_id": mkt["market_id"],
        })

    return rows


# =============================================================================
# EVM: ERC-4626 Vaults (Category A1)
# =============================================================================

def query_erc4626_vaults(w3, chain, wallet, block_number, block_ts):
    """Query all ERC-4626 vault positions for a wallet on a chain.

    Reads vault contracts from contracts.json (keys starting with _morpho_vaults,
    _avantis, _yearn, _credit_coop). Returns one row per vault with shares and
    underlying value.
    """
    contracts = _load_contracts_cfg()
    chain_contracts = contracts.get(chain, {})
    rows = []

    # Collect all ERC-4626 vault entries
    vault_entries = []
    for section_key, section in chain_contracts.items():
        if not isinstance(section, dict):
            continue
        for entry_key, entry in section.items():
            if isinstance(entry, dict) and entry.get("abi") == "erc4626":
                vault_entries.append((section_key, entry_key, entry))

    # Also check Credit Coop vault (uses credit_coop_vault ABI but is ERC-4626)
    if "_credit_coop" in chain_contracts:
        cc = chain_contracts["_credit_coop"]
        if "vault" in cc and cc["vault"].get("abi") == "credit_coop_vault":
            vault_entries.append(("_credit_coop", "vault", cc["vault"]))

    for section_key, entry_key, entry in vault_entries:
        vault_addr = entry["address"]
        abi_name = entry.get("abi", "erc4626")
        vault = w3.eth.contract(
            address=Web3.to_checksum_address(vault_addr), abi=_get_abi(abi_name))

        try:
            shares = vault.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
        except Exception:
            continue

        if shares == 0:
            continue

        try:
            assets = vault.functions.convertToAssets(shares).call()
            share_decimals = vault.functions.decimals().call()
            # Underlying may have different decimals (e.g. vault=18dec, USDC=6dec)
            try:
                asset_addr = vault.functions.asset().call()
                underlying_contract = w3.eth.contract(
                    address=Web3.to_checksum_address(asset_addr),
                    abi=_get_abi("erc20"))
                underlying_decimals = underlying_contract.functions.decimals().call()
            except Exception:
                underlying_decimals = share_decimals
        except Exception:
            continue

        protocol = section_key.strip("_")
        shares_human = _fmt(shares, share_decimals)
        assets_human = _fmt(assets, underlying_decimals)

        # Determine underlying symbol from known vault mappings
        underlying_sym = _VAULT_UNDERLYING.get(vault_addr.lower(), "USDC")
        display_name = _DISPLAY_NAMES.get(vault_addr.lower(), entry_key)

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


# =============================================================================
# EVM: Euler V2 Vaults (Category A1, sub-account scan)
# =============================================================================

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

                display_name = _DISPLAY_NAMES.get(vault_addr.lower(), entry_key)
                rows.append({
                    "chain": chain, "protocol": "euler", "wallet": wallet,
                    "position_label": display_name,
                    "category": "A1", "position_type": "vault_share",
                    "token_symbol": entry_key,
                    "token_contract": vault_addr,
                    "balance_raw": str(shares),
                    "balance_human": shares_human,
                    "decimals": share_dec,
                    "exchange_rate": assets_human / shares_human if shares_human > 0 else Decimal(0),
                    "underlying_amount": assets_human,
                    "underlying_symbol": "syrupUSDC",
                    "euler_sub_account": sub_id,
                    "euler_sub_address": sub_addr.lower(),
                    "block_number": block_number, "block_timestamp_utc": block_ts,
                })
                found = True
                break  # found the active sub-account

    return rows


# =============================================================================
# EVM: Aave (Category D or A1)
# =============================================================================

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
            bal = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
        except Exception:
            continue
        if bal == 0:
            continue

        # Determine decimals from description or try on-chain
        try:
            decimals = token.functions.decimals().call()
        except Exception:
            decimals = 6  # default

        bal_human = _fmt(bal, decimals)
        display_name = _DISPLAY_NAMES.get(aentry["address"].lower(), akey)

        rows.append({
            "chain": chain, "protocol": "aave", "wallet": wallet,
            "position_label": display_name,
            "category": "D",  # may be reclassified if no debt
            "position_type": "collateral",
            "token_symbol": akey,
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
            bal = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
        except Exception:
            continue
        if bal == 0:
            continue

        try:
            decimals = token.functions.decimals().call()
        except Exception:
            decimals = 18

        bal_human = _fmt(bal, decimals)

        display_name = _DISPLAY_NAMES.get(dentry["address"].lower(), dkey)
        rows.append({
            "chain": chain, "protocol": "aave", "wallet": wallet,
            "position_label": display_name,
            "category": "D", "position_type": "debt",
            "token_symbol": dkey,
            "token_contract": dentry["address"],
            "balance_raw": str(bal),
            "balance_human": -bal_human,  # negative for debt
            "decimals": decimals,
            "block_number": block_number, "block_timestamp_utc": block_ts,
        })

    return rows


# =============================================================================
# EVM: Gauntlet / FalconX (Category A3 cross-reference)
# =============================================================================

def query_gauntlet_falconx(w3, wallet, block_number, block_ts):
    """Query Gauntlet vault FalconX A3 position.

    Computes the NAV value using accrual methodology from the raw data in the
    supporting workbook (Gauntlet_LeveredX sheet). Also queries on-chain
    cross-reference data (TP × collateral − debt × share%).

    Accrual formula (per falconx_position_flow.md):
      Running Balance = Opening Value + sum(Opening × Rate × Period / 365)
      TP (re-engineered) = Running Balance / Veris AA_FalconXUSDC
      Collateral (USD) = Vault Collateral × TP (re-engineered)
      Net = Collateral (USD) − Borrow
      Veris share = Net × Veris %
    """
    import csv

    GAUNTLET_VAULT = "0x00000000d8f3d6c5DFeB2D2b5ED2276095f3aF44"
    erc20_abi = _get_abi("erc20")

    # Only need veris shares for reporting (balance_human)
    vault = w3.eth.contract(address=Web3.to_checksum_address(GAUNTLET_VAULT), abi=erc20_abi)
    veris_shares = vault.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
    total_supply = vault.functions.totalSupply().call()
    if veris_shares == 0:
        return []

    share_pct = Decimal(str(veris_shares)) / Decimal(str(total_supply))

    # --- Read accrual NAV from supporting workbook ---
    xlsx_path = os.path.join(
        os.path.dirname(__file__), "..", "outputs", "falconx_position.xlsx")

    accrual_value = _read_falconx_xlsx(xlsx_path, "Gauntlet_LeveredX", col_index=17)
    if accrual_value is None:
        accrual_value = Decimal(0)

    return [{
        "chain": "ethereum", "protocol": "gauntlet_pareto", "wallet": wallet,
        "position_label": "Gauntlet FalconX Vault",
        "category": "A3", "position_type": "manual_accrual",
        "token_symbol": "gpAAFalconX",
        "token_contract": GAUNTLET_VAULT,
        "balance_raw": str(veris_shares),
        "balance_human": _fmt(veris_shares, 18),
        "decimals": 18,
        "veris_share_pct": share_pct * 100,
        "accrual_value": accrual_value,
        "block_number": block_number, "block_timestamp_utc": block_ts,
        "price_source": "a3_workbook_accrual",
        "notes": f"Value from outputs/falconx_position.xlsx Gauntlet_LeveredX col R (Veris share). TP on-chain is cross-reference only (stale, not used for valuation).",
    }]


def _read_falconx_xlsx(xlsx_path, sheet_name, col_index):
    """Read the NAV value from the FalconX workbook.

    First tries formula result columns (openpyxl data_only=True).
    If formula columns are empty (newly written rows), computes the value
    from the raw data columns using the accrual methodology.

    Gauntlet_LeveredX: col R (17) = Veris share = (Collateral × TP_reeng - Borrow) × Veris%
    Direct Accrual: col H (7) = Running Balance = Opening + cumulative interest
    """
    import openpyxl

    if not os.path.exists(xlsx_path):
        return None

    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
        ws = wb[sheet_name]

        # Read last cached formula value from Excel-saved workbook
        last_value = None
        all_rows = []
        for row in ws.iter_rows(min_row=2):
            if len(row) > col_index and row[col_index].value is not None:
                last_value = row[col_index].value
            if row[0].value is not None:
                all_rows.append([cell.value for cell in row])

        wb.close()

        # Primary: cached formula value (requires workbook saved from Excel)
        if last_value is not None:
            return Decimal(str(last_value))

        # Fallback: compute from raw data columns if formulas not cached
        if all_rows:
            if sheet_name == "Gauntlet_LeveredX":
                return _compute_gauntlet_value(all_rows)
            elif sheet_name == "Direct Accrual":
                return _compute_direct_value(all_rows)

    except Exception:
        pass

    return None


def _compute_gauntlet_value(rows):
    """Compute Gauntlet Veris share from raw data columns when formulas aren't cached.

    Uses the accrual methodology from falconx_position_flow.md:
    Running Balance accrues interest hourly at Net Rate.
    TP_reengineered = Running Balance / Veris AA_FalconXUSDC.
    Collateral(USD) = on-chain Collateral × TP_reengineered.
    Net = Collateral(USD) - Borrow.
    Veris share = Net × (VerisBalance / TotalSupply).
    """
    running_balance = None
    veris_aa = None
    prev_ts = None

    for row in rows:
        ts = row[0]
        if ts is None:
            continue
        rate = Decimal(str(row[7])) if row[7] else Decimal(0)
        if row[8] is not None:
            veris_aa = Decimal(str(row[8]))
        if running_balance is None:
            if row[11] is not None:
                running_balance = Decimal(str(row[11]))
            elif veris_aa and row[9]:
                running_balance = veris_aa * Decimal(str(row[9]))
            prev_ts = ts
            continue
        if prev_ts is None:
            prev_ts = ts
            continue
        delta = (ts - prev_ts).total_seconds()
        period_days = Decimal(str(delta)) / Decimal(86400)
        if period_days > 0 and rate > 0:
            running_balance += running_balance * rate * period_days / Decimal(365)
        prev_ts = ts

    if running_balance is None or veris_aa is None or veris_aa == 0:
        return None

    last = rows[-1]
    collateral = Decimal(str(last[2])) if last[2] else Decimal(0)
    borrow = Decimal(str(last[3])) if last[3] else Decimal(0)
    total_supply = Decimal(str(last[4])) if last[4] else Decimal(1)
    veris_balance = Decimal(str(last[5])) if last[5] else Decimal(0)

    tp_reeng = running_balance / veris_aa
    collateral_usd = collateral * tp_reeng
    net = collateral_usd - borrow
    veris_pct = veris_balance / total_supply if total_supply > 0 else Decimal(0)
    return net * veris_pct


def _compute_direct_value(rows):
    """Compute Direct Accrual Running Balance from raw data columns.

    Running Balance = Opening Value + cumulative interest.
    Interest = Running Balance × Rate × Period / 365.
    """
    running_balance = None
    prev_ts = None
    rate = Decimal("0.08325")

    for row in rows:
        ts = row[0]
        if ts is None:
            continue
        if row[4] is not None:
            rate = Decimal(str(row[4]))
        if running_balance is None:
            if row[3] is not None:
                running_balance = Decimal(str(row[3]))
            prev_ts = ts
            continue
        if prev_ts is None:
            prev_ts = ts
            continue
        delta = (ts - prev_ts).total_seconds()
        period_days = Decimal(str(delta)) / Decimal(86400)
        if period_days > 0 and rate > 0:
            running_balance += running_balance * rate * period_days / Decimal(365)
        prev_ts = ts

    return running_balance


# =============================================================================
# EVM: Uniswap V4 (Category C — concentrated liquidity NFT)
# =============================================================================

def query_uniswap_v4(w3, wallet, block_number, block_ts):
    """Query Uniswap V4 NFT position #142965 (USDC/DUSD).

    Small position (~$9 USDC). Reports liquidity amount; value estimated
    from the position's USDC component only (DUSD is depegged).
    """
    PM = "0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e"
    NFT_ID = 142965

    # Check ownership
    owner_abi = [{"inputs": [{"name": "tokenId", "type": "uint256"}], "name": "ownerOf",
                  "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"}]
    liq_abi = [{"inputs": [{"name": "tokenId", "type": "uint256"}], "name": "getPositionLiquidity",
                "outputs": [{"name": "", "type": "uint128"}], "stateMutability": "view", "type": "function"}]

    pm = w3.eth.contract(address=Web3.to_checksum_address(PM), abi=owner_abi + liq_abi)

    try:
        owner = pm.functions.ownerOf(NFT_ID).call()
    except Exception:
        return []

    if owner.lower() != wallet.lower():
        return []

    liquidity = pm.functions.getPositionLiquidity(NFT_ID).call()
    if liquidity == 0:
        return []

    # Position is USDC/DUSD CL, ~$9 total from 1Token snapshots
    # Exact decomposition requires V4 pool state (sqrtPriceX96, ticks)
    # For this small position, report as LP with approximate value
    return [{
        "chain": "ethereum", "protocol": "uniswap_v4", "wallet": wallet,
        "position_label": "Uniswap V4 USDC/DUSD #142965",
        "category": "C", "position_type": "lp_position",
        "token_symbol": "UNI-V4-142965",
        "token_contract": PM,
        "balance_human": Decimal(str(liquidity)),
        "nft_id": NFT_ID,
        "block_number": block_number, "block_timestamp_utc": block_ts,
        "notes": "Concentrated liquidity USDC/DUSD 0.01% fee. Range 0.95-0.9999. ~$9 per 1Token snapshots.",
    }]


# =============================================================================
# EVM: Ethena sUSDe Cooldowns (pending unstakes)
# =============================================================================

def query_ethena_cooldowns(w3, wallet, block_number, block_ts):
    """Query Ethena sUSDe cooldown (pending unstakes).

    cooldowns(wallet) returns (cooldownEnd, underlyingAmount).
    These are NOT visible via balanceOf — separate from the sUSDe balance.
    """
    SUSDE = "0x9d39a5de30e57443bff2a8307a4256c8797a3497"
    cooldown_abi = [{"inputs": [{"name": "account", "type": "address"}],
                     "name": "cooldowns",
                     "outputs": [{"name": "cooldownEnd", "type": "uint104"},
                                 {"name": "underlyingAmount", "type": "uint152"}],
                     "stateMutability": "view", "type": "function"}]

    susde = w3.eth.contract(address=Web3.to_checksum_address(SUSDE), abi=cooldown_abi)

    try:
        result = susde.functions.cooldowns(Web3.to_checksum_address(wallet)).call()
        cooldown_end, underlying = result
    except Exception:
        return []

    if underlying == 0:
        return []

    from datetime import datetime
    amount = _fmt(underlying, 18)
    end_ts = datetime.fromtimestamp(cooldown_end, tz=__import__("datetime").timezone.utc) if cooldown_end > 0 else None
    claimable = end_ts and end_ts < datetime.now(__import__("datetime").timezone.utc)

    return [{
        "chain": "ethereum", "protocol": "ethena", "wallet": wallet,
        "position_label": "Ethena sUSDe Cooldown",
        "category": "E", "position_type": "token_balance",
        "token_symbol": "USDe",
        "token_contract": "0x4c9edd5852cd905f086c759e8383e09bff1e68b3",  # USDe
        "balance_human": amount,
        "decimals": 18,
        "block_number": block_number, "block_timestamp_utc": block_ts,
        "notes": f"Pending unstake from sUSDe. Cooldown ended {end_ts}. {'Claimable' if claimable else 'Locked'}.",
    }]


# =============================================================================
# EVM: Midas (Category A2 — tokenised fund shares with oracle)
# =============================================================================

def query_midas_positions(w3, chain, wallet, block_number, block_ts):
    """Query Midas tokenised fund positions (mF-ONE, mHYPER, msyrupUSDp).

    These are ERC-20 tokens with Chainlink-style oracles. Category A2.
    """
    # Known Midas tokens per chain
    MIDAS_TOKENS = {
        "ethereum": [
            {
                "address": "0x238a700eD6165261Cf8b2e544ba797BC11e466Ba",
                "symbol": "mF-ONE", "name": "Midas Fasanara ONE",
                "decimals": 18, "oracle": "0x8D51DBC85cEef637c97D02bdaAbb5E274850e68C",
            },
            {
                "address": "0x2fE058CcF29f123f9dd2aEC0418AA66a877d8E50",
                "symbol": "msyrupUSDp", "name": "Midas syrupUSD Pre-deposit",
                "decimals": 18, "oracle": "0x337d914ff6622510FC2C63ac59c1D07983895241",
            },
        ],
        "plasma": [
            {
                "address": "0xb31BeA5c2a43f942a3800558B1aa25978da75F8a",
                "symbol": "mHYPER", "name": "Midas Hyperithm",
                "decimals": 18, "oracle": "0xfC3E47c4Da8F3a01ac76c3C5ecfBfC302e1A08F0",
                "oracle_chain": "plasma",
            },
        ],
    }

    chain_tokens = MIDAS_TOKENS.get(chain, [])
    if not chain_tokens:
        return []

    erc20_abi = _get_abi("erc20")
    rows = []

    for tok in chain_tokens:
        token = w3.eth.contract(
            address=Web3.to_checksum_address(tok["address"]), abi=erc20_abi)
        try:
            bal = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
        except Exception:
            continue

        if bal == 0:
            continue

        bal_human = _fmt(bal, tok["decimals"])

        rows.append({
            "chain": chain, "protocol": "midas", "wallet": wallet,
            "position_label": tok["name"],
            "category": "A2", "position_type": "oracle_priced",
            "token_symbol": tok["symbol"],
            "token_contract": tok["address"],
            "balance_raw": str(bal),
            "balance_human": bal_human,
            "decimals": tok["decimals"],
            "oracle_address": tok["oracle"],
            "oracle_chain": tok.get("oracle_chain", "ethereum"),
            "block_number": block_number, "block_timestamp_utc": block_ts,
        })

    return rows


# =============================================================================
# EVM: FalconX Direct AA_FalconXUSDC (Category A3)
# =============================================================================

def query_falconx_direct(w3, wallet, block_number, block_ts):
    """Query direct AA_FalconXUSDC holding for A3 accrual.

    Reads the Running Balance from the supporting workbook (Direct Accrual sheet).
    """
    AA_TRANCHE = "0xC26A6Fa2C37b38E549a4a1807543801Db684f99C"
    erc20_abi = _get_abi("erc20")

    # Check if wallet holds AA_FalconXUSDC
    token = w3.eth.contract(
        address=Web3.to_checksum_address(AA_TRANCHE), abi=erc20_abi)
    balance = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
    if balance == 0:
        return []

    balance_human = _fmt(balance, 18)

    # Read accrual value from supporting workbook (col H = Running Balance, index 7)
    xlsx_path = os.path.join(
        os.path.dirname(__file__), "..", "outputs", "falconx_position.xlsx")

    running_balance = _read_falconx_xlsx(xlsx_path, "Direct Accrual", col_index=7)
    if running_balance is None:
        running_balance = Decimal(0)

    return [{
        "chain": "ethereum", "protocol": "gauntlet_pareto", "wallet": wallet,
        "position_label": "FalconX Direct AA_FalconXUSDC",
        "category": "A3", "position_type": "manual_accrual",
        "token_symbol": "AA_FalconXUSDC",
        "token_contract": AA_TRANCHE,
        "balance_raw": str(balance),
        "balance_human": balance_human,
        "decimals": 18,
        "accrual_value": running_balance,
        "price_source": "a3_workbook_accrual",
        "block_number": block_number, "block_timestamp_utc": block_ts,
        "notes": f"Value from outputs/falconx_position.xlsx Direct Accrual sheet col H. Running Balance={running_balance:,.2f}",
    }]


# =============================================================================
# EVM: CreditCoop (Category A1)
# =============================================================================

def query_creditcoop(w3, wallet, block_number, block_ts):
    """Query CreditCoop vault — ERC-4626 convertToAssets + sub-strategy breakdown.

    Returns:
    - Main A1 position (aggregate via convertToAssets)
    - Sub-strategy breakdown rows for methodology log:
      - Rain credit line (totalActiveCredit on CreditStrategy)
      - Gauntlet USDC Core (totalAssets on LiquidStrategy)
      - Undeployed cash (USDC balanceOf on vault + credit strategy)
    """
    VAULT = "0xb21eAFB126cEf15CB99fe2D23989b58e40097919"
    LIQUID_STRATEGY = "0x671B5B6F01C5FEe16E6F9De2eb85AC027Dc9fE0e"
    CREDIT_STRATEGY = "0x433E415b0fA54C570C450DD976E2402e408cB6db"
    USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"

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
        "chain": "ethereum", "protocol": "credit_coop", "wallet": wallet,
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
    # These are informational — the aggregate convertToAssets is the primary value
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


# =============================================================================
# Solana: Kamino Obligations (Category D)
# =============================================================================

def query_kamino_obligations(wallet, block_ts):
    """Query Kamino lending obligation positions (leveraged).

    Returns collateral + debt rows for each known obligation.
    """
    # Known obligations from protocol_sourcing.md
    obligations = [
        {
            "market_name": "Superstate Opening Bell",
            "obligation_pubkey": "D2rcayJTqmZvqaoViEyamQh2vw9T1KYwjbySQZSz6fsS",
            "deposits": [
                {"reserve": "FQnQgBYzJkiVfUZgggfTRn4FGKE3FN94UoZgBreZMgTR",
                 "symbol": "USCC", "decimals": 6, "category": "A2"},
            ],
            "borrows": [
                {"reserve": "BnYNV7TdhwASUab7mQCRhzHvasjp8o8xmmvVtKnPe3Zi",
                 "symbol": "USDC", "decimals": 6, "category": "E"},
            ],
        },
        {
            "market_name": "Solstice",
            "obligation_pubkey": "HMMc5d9sMrGrAY18wE5yYTPpJNk72nrBrgqz5mtE3yrq",
            "deposits": [
                {"reserve": "BLKW7xCY5g5qE8S5Z3riw7TYRQnm8NMfeqB9qb269Bo3",
                 "symbol": "PT-USX-01JUN26", "decimals": 6, "category": "B"},
                {"reserve": "EzmztxShSt8AwpBBbJxpYaKAY3E3PWQCyPQPkUYbP9u",
                 "symbol": "PT-eUSX-01JUN26", "decimals": 6, "category": "B"},
            ],
            "borrows": [
                {"reserve": "H2pmnDSjfxeQ8zUeyUohokegYbXZgkjH4kgmoQVybyAX",
                 "symbol": "USX", "decimals": 6, "category": "E"},
            ],
        },
    ]

    rows = []
    for ob_cfg in obligations:
        ob = get_kamino_obligation(ob_cfg["obligation_pubkey"])

        # Match deposits to config by reserve pubkey
        for i, deposit in enumerate(ob["deposits"]):
            dep_cfg = next(
                (d for d in ob_cfg["deposits"] if d["reserve"] == deposit["reserve"]),
                None
            )
            if dep_cfg is None:
                continue

            amount = Decimal(deposit["deposited_amount"]) / Decimal(10 ** dep_cfg["decimals"])
            rows.append({
                "chain": "solana", "protocol": "kamino", "wallet": wallet,
                "position_label": f"Kamino {ob_cfg['market_name']}",
                "category": "D", "position_type": "collateral",
                "token_symbol": dep_cfg["symbol"],
                "token_category": dep_cfg["category"],
                "balance_raw": str(deposit["deposited_amount"]),
                "balance_human": amount,
                "decimals": dep_cfg["decimals"],
                "block_number": str(ob.get("last_update_slot", "latest")),
                "block_timestamp_utc": block_ts,
            })

        # Match borrows
        for borrow in ob["borrows"]:
            bor_cfg = next(
                (b for b in ob_cfg["borrows"] if b["reserve"] == borrow["reserve"]),
                None
            )
            if bor_cfg is None:
                continue

            amount = borrow["borrowed_amount"] / Decimal(10 ** bor_cfg["decimals"])
            rows.append({
                "chain": "solana", "protocol": "kamino", "wallet": wallet,
                "position_label": f"Kamino {ob_cfg['market_name']}",
                "category": "D", "position_type": "debt",
                "token_symbol": bor_cfg["symbol"],
                "token_category": bor_cfg["category"],
                "balance_raw": str(borrow["borrowed_amount_sf"]),
                "balance_human": -amount,  # negative for debt
                "decimals": bor_cfg["decimals"],
                "block_number": str(ob.get("last_update_slot", "latest")),
                "block_timestamp_utc": block_ts,
            })

    return rows


# =============================================================================
# Solana: Exponent LP (Category C)
# =============================================================================

def query_exponent_lps(wallet, block_ts):
    """Query Exponent LP positions and decompose into SY + PT constituents."""
    # Known markets
    market_configs = [
        {
            "market_pubkey": "8QJRc12BDXHRLghZXFyPtYtAQeRwnZGKMJQa3G2NVQoC",
            "name": "ONyc-13MAY26",
            "sy_symbol": "ONyc", "sy_category": "A2", "sy_decimals": 9,
            "pt_symbol": "PT-ONyc-13MAY26", "pt_decimals": 9,
        },
        {
            "market_pubkey": "rBbzpGk3PTX8mvQg95VWJ24EDgvxyDJYrEo9jtauvjP",
            "name": "eUSX-01JUN26",
            "sy_symbol": "eUSX", "sy_category": "A1", "sy_decimals": 6,
            "pt_symbol": "PT-eUSX-01JUN26", "pt_decimals": 6,
        },
    ]

    lp_positions = get_exponent_lp_positions(wallet)
    if not lp_positions:
        return []

    rows = []
    for mcfg in market_configs:
        lp = next(
            (l for l in lp_positions if l["market"] == mcfg["market_pubkey"]),
            None
        )
        if lp is None or lp["lp_balance"] == 0:
            continue

        time.sleep(0.3)
        market = get_exponent_market(mcfg["market_pubkey"])
        time.sleep(0.3)
        lp_supply_resp = solana_rpc("getTokenSupply", [market["lp_mint"]])
        lp_supply = int(lp_supply_resp["result"]["value"]["amount"])

        decomp = decompose_exponent_lp(market, lp["lp_balance"], lp_supply)

        sy_amount = Decimal(decomp["user_sy"]) / Decimal(10 ** mcfg["sy_decimals"])
        pt_amount = Decimal(decomp["user_pt"]) / Decimal(10 ** mcfg["pt_decimals"])
        pt_price_ratio = Decimal(str(decomp["pt_price_ratio"]))

        # SY constituent row
        rows.append({
            "chain": "solana", "protocol": "exponent", "wallet": wallet,
            "position_label": f"Exponent {mcfg['name']} LP",
            "category": "C", "position_type": "lp_constituent",
            "token_symbol": mcfg["sy_symbol"],
            "token_category": mcfg["sy_category"],
            "balance_human": sy_amount,
            "decimals": mcfg["sy_decimals"],
            "lp_constituent_type": "SY",
            "lp_share": decomp["lp_share"],
            "block_timestamp_utc": block_ts,
        })

        # PT constituent row
        rows.append({
            "chain": "solana", "protocol": "exponent", "wallet": wallet,
            "position_label": f"Exponent {mcfg['name']} LP",
            "category": "C", "position_type": "lp_constituent",
            "token_symbol": mcfg["pt_symbol"],
            "token_category": "C",  # PT in LP uses AMM rate, not lot amortisation
            "balance_human": pt_amount,
            "decimals": mcfg["pt_decimals"],
            "lp_constituent_type": "PT",
            "pt_price_ratio": pt_price_ratio,
            "last_ln_implied_rate": decomp["last_ln_implied_rate"],
            "seconds_remaining": decomp["seconds_remaining"],
            "lp_share": decomp["lp_share"],
            "block_timestamp_utc": block_ts,
        })

    return rows


# =============================================================================
# Solana: Exponent YT (Category F)
# =============================================================================

def query_exponent_yts(wallet, block_ts):
    """Query Exponent Yield Token positions."""
    yt_configs = [
        {
            "vault": "J2apQJvzq1yuhBoa1mVwAXr3P5oEzFaCVohq1GQMcW2c",
            "market_pubkey": "8QJRc12BDXHRLghZXFyPtYtAQeRwnZGKMJQa3G2NVQoC",
            "symbol": "YT-ONyc-13MAY26", "underlying": "ONyc",
            "decimals": 9,
        },
        {
            "vault": "7NviQEEiA5RSY4aL1wpqGE8CYAx2Lx7THHinsW1CWDXu",
            "market_pubkey": "rBbzpGk3PTX8mvQg95VWJ24EDgvxyDJYrEo9jtauvjP",
            "symbol": "YT-eUSX-01JUN26", "underlying": "eUSX",
            "decimals": 6,
        },
    ]

    yt_positions = get_exponent_yt_positions(wallet)
    if not yt_positions:
        return []

    rows = []
    for yt_cfg in yt_configs:
        yt = next(
            (y for y in yt_positions if y["vault"] == yt_cfg["vault"]),
            None
        )
        if yt is None or yt["yt_balance"] == 0:
            continue

        yt_human = Decimal(yt["yt_balance"]) / Decimal(10 ** yt_cfg["decimals"])

        # Get PT price ratio from market for YT pricing
        time.sleep(0.3)
        market = get_exponent_market(yt_cfg["market_pubkey"])
        sec_remaining = market["expiration_ts"] - int(time.time())
        if sec_remaining > 0 and market["last_ln_implied_rate"] > 0:
            exchange_rate = math.exp(
                market["last_ln_implied_rate"] * sec_remaining / 31_536_000)
            pt_price_ratio = 1.0 / exchange_rate
        else:
            pt_price_ratio = 1.0

        yt_price_ratio = Decimal(str(1.0 - pt_price_ratio))

        rows.append({
            "chain": "solana", "protocol": "exponent", "wallet": wallet,
            "position_label": f"Exponent {yt_cfg['symbol']}",
            "category": "F", "position_type": "reward",
            "token_symbol": yt_cfg["symbol"],
            "underlying_symbol": yt_cfg["underlying"],
            "balance_human": yt_human,
            "decimals": yt_cfg["decimals"],
            "yt_price_ratio": yt_price_ratio,
            "block_timestamp_utc": block_ts,
        })

    return rows


# =============================================================================
# Solana: PT Lots (Category B)
# =============================================================================

def query_pt_lots(valuation_date, block_ts):
    """Query PT token positions valued via lot-based linear amortisation.

    Reads lots from config/pt_lots.json, values using pt_valuation.value_pt_from_config().
    Returns one row per lot.
    """
    with open(os.path.join(CONFIG_DIR, "pt_lots.json")) as f:
        pt_cfg = json.load(f)

    rows = []
    for pt_symbol, cfg in pt_cfg.items():
        if pt_symbol.startswith("_"):
            continue
        if "lots_discovered" not in cfg:
            continue

        # For now, use placeholder price — collect.py will price after
        rows.append({
            "chain": cfg.get("chain", "solana"),
            "protocol": cfg.get("protocol", "exponent"),
            "wallet": "ASQ4kYjSYGUYbbYtsaLhUeJS6RtrN4Uwp4XbF4gDifvr",
            "position_label": f"PT {pt_symbol} (lot-based)",
            "category": "B", "position_type": "pt_lot_aggregate",
            "token_symbol": pt_symbol,
            "token_contract": cfg.get("mint", ""),
            "total_tokens": cfg.get("total_tokens", 0),
            "total_lots": cfg.get("total_lots", 0),
            "underlying": cfg.get("underlying", ""),
            "maturity": cfg.get("maturity", ""),
            "decimals": cfg.get("decimals", 6),
            "held_as": cfg.get("held_as", ""),
            "block_timestamp_utc": block_ts,
            "_pt_symbol": pt_symbol,  # for valuation.py to pick up
        })

    return rows


# =============================================================================
# Orchestrator helper: query all EVM positions for a wallet on a chain
# =============================================================================

_MORPHO_CFG_CACHE = None
_CONTRACTS_CFG_CACHE = None


def _load_morpho_cfg():
    global _MORPHO_CFG_CACHE
    if _MORPHO_CFG_CACHE is None:
        with open(os.path.join(CONFIG_DIR, "morpho_markets.json")) as f:
            _MORPHO_CFG_CACHE = json.load(f)
    return _MORPHO_CFG_CACHE


def _load_contracts_cfg():
    global _CONTRACTS_CFG_CACHE
    if _CONTRACTS_CFG_CACHE is None:
        with open(os.path.join(CONFIG_DIR, "contracts.json")) as f:
            _CONTRACTS_CFG_CACHE = json.load(f)
    return _CONTRACTS_CFG_CACHE


def _has_protocol_positions(chain, wallet):
    """Quick check: does this wallet have any registered protocol positions on this chain?

    Avoids expensive RPC calls for wallet/chain combos with nothing registered.
    """
    wallet_lower = wallet.lower()
    wallet_short = wallet_lower[:6]

    # Morpho markets — wallet-specific
    morpho_cfg = _load_morpho_cfg()
    chain_morpho = morpho_cfg.get(chain, {})
    for mkt in chain_morpho.get("markets", []):
        if wallet_lower in [w.lower() for w in mkt.get("wallets", [])]:
            return True

    # Known wallet → chain → position mappings (avoid scanning all wallets on all chains)
    KNOWN_POSITIONS = {
        # (wallet_prefix, chain) → True
        ("0xa33e", "ethereum"): True,   # Morpho D, Steakhouse A1, Midas mF-ONE A2
        ("0xa33e", "arbitrum"): True,   # Morpho D, Euler A1
        ("0xa33e", "base"): True,       # Aave A1
        ("0x8055", "ethereum"): True,   # Aave Horizon D
        ("0x8055", "base"): True,       # Clearstar A1, Avantis A1
        ("0x0c16", "ethereum"): True,   # Gauntlet/FalconX A3
        ("0xec0b", "ethereum"): True,   # CreditCoop A1, Hyperithm A1
        ("0x6691", "base"): True,       # Avantis A1
        ("0x6691", "plasma"): True,     # Aave sUSDe/USDe
        ("0x8055", "plasma"): True,     # Midas mHYPER
        ("0xa33e", "plasma"): True,     # Midas mHYPER
        ("0x6691", "katana"): True,     # Yearn V3
    }

    return KNOWN_POSITIONS.get((wallet_short, chain), False)


def query_evm_wallet_positions(chain, wallet, wallet_desc=""):
    """Query all protocol positions for one wallet on one EVM chain.

    Returns list of raw position dicts (not yet priced).
    Skips chains with no registered positions for this wallet.
    """
    if not _has_protocol_positions(chain, wallet):
        return []

    try:
        w3 = get_web3(chain)
        block_number, block_ts = get_block_info(w3)
    except (ConnectionError, Exception) as e:
        print(f"  [{chain}] SKIP -- {e}")
        return []

    rows = []

    # Morpho markets (D)
    try:
        morpho_rows = query_morpho_markets(w3, chain, wallet, block_number, block_ts)
        rows.extend(morpho_rows)
    except Exception as e:
        print(f"  [{chain}] Morpho error: {e}")

    # ERC-4626 vaults (A1)
    try:
        vault_rows = query_erc4626_vaults(w3, chain, wallet, block_number, block_ts)
        rows.extend(vault_rows)
    except Exception as e:
        print(f"  [{chain}] ERC-4626 error: {e}")

    # Euler vaults (A1, only on chains with Euler)
    try:
        euler_rows = query_euler_vaults(w3, chain, wallet, block_number, block_ts)
        rows.extend(euler_rows)
    except Exception as e:
        pass  # Euler not on all chains

    # Aave positions (D or A1)
    try:
        aave_rows = query_aave_positions(w3, chain, wallet, block_number, block_ts)
        rows.extend(aave_rows)
    except Exception as e:
        print(f"  [{chain}] Aave error: {e}")

    # Midas positions (A2)
    try:
        midas_rows = query_midas_positions(w3, chain, wallet, block_number, block_ts)
        rows.extend(midas_rows)
    except Exception as e:
        pass  # Midas not on all chains

    # Gauntlet/FalconX (A3, only for 0x0c16 on Ethereum)
    if chain == "ethereum" and "0x0c16" in wallet.lower():
        try:
            gf_rows = query_gauntlet_falconx(w3, wallet, block_number, block_ts)
            rows.extend(gf_rows)
        except Exception as e:
            print(f"  [{chain}] Gauntlet/FalconX error: {e}")

        # Direct AA_FalconXUSDC holding (A3, separate accrual)
        try:
            da_rows = query_falconx_direct(w3, wallet, block_number, block_ts)
            rows.extend(da_rows)
        except Exception as e:
            print(f"  [{chain}] FalconX Direct error: {e}")

    # Uniswap V4 LP (C, only for 0xa33e on Ethereum — NFT #142965, ~$9 USDC/DUSD)
    if chain == "ethereum" and "0xa33e" in wallet.lower():
        try:
            uni_rows = query_uniswap_v4(w3, wallet, block_number, block_ts)
            rows.extend(uni_rows)
        except Exception as e:
            pass

    # Ethena sUSDe cooldowns (pending unstakes, only on Ethereum)
    if chain == "ethereum":
        try:
            cooldown_rows = query_ethena_cooldowns(w3, wallet, block_number, block_ts)
            rows.extend(cooldown_rows)
        except Exception as e:
            pass

    # CreditCoop (A1, only for 0xec0b on Ethereum)
    if chain == "ethereum" and "0xec0b" in wallet.lower():
        try:
            cc_rows = query_creditcoop(w3, wallet, block_number, block_ts)
            rows.extend(cc_rows)
        except Exception as e:
            print(f"  [{chain}] CreditCoop error: {e}")

    return rows


# =============================================================================
# Orchestrator helper: query all Solana positions
# =============================================================================

def query_solana_positions(wallet, valuation_date=None):
    """Query all Solana protocol positions for a wallet.

    Includes Kamino obligations, Exponent LPs, Exponent YTs, and PT lots.
    """
    from datetime import datetime, timezone
    block_ts = datetime.now(timezone.utc).strftime(TS_FMT)

    rows = []

    # Kamino obligations (D)
    try:
        kamino_rows = query_kamino_obligations(wallet, block_ts)
        rows.extend(kamino_rows)
        print(f"  [solana] Kamino: {len(kamino_rows)} positions")
    except Exception as e:
        print(f"  [solana] Kamino error: {e}")

    # Exponent LPs (C)
    try:
        lp_rows = query_exponent_lps(wallet, block_ts)
        rows.extend(lp_rows)
        print(f"  [solana] Exponent LP: {len(lp_rows)} constituents")
    except Exception as e:
        print(f"  [solana] Exponent LP error: {e}")

    # Exponent YTs (F)
    try:
        yt_rows = query_exponent_yts(wallet, block_ts)
        rows.extend(yt_rows)
        print(f"  [solana] Exponent YT: {len(yt_rows)} positions")
    except Exception as e:
        print(f"  [solana] Exponent YT error: {e}")

    # PT lots (B)
    if valuation_date:
        try:
            pt_rows = query_pt_lots(valuation_date, block_ts)
            rows.extend(pt_rows)
            print(f"  [solana] PT lots: {len(pt_rows)} aggregates")
        except Exception as e:
            print(f"  [solana] PT lots error: {e}")

    return rows
