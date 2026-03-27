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


# =============================================================================
# Config caches and loaders
# =============================================================================

_ABIS = None
_MORPHO_CFG_CACHE = None
_CONTRACTS_CFG_CACHE = None
_SOLANA_CFG_CACHE = None
_WALLETS_CFG_CACHE = None


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


def _load_solana_cfg():
    global _SOLANA_CFG_CACHE
    if _SOLANA_CFG_CACHE is None:
        with open(os.path.join(CONFIG_DIR, "solana_protocols.json")) as f:
            _SOLANA_CFG_CACHE = json.load(f)
    return _SOLANA_CFG_CACHE


def _load_wallets_cfg():
    global _WALLETS_CFG_CACHE
    if _WALLETS_CFG_CACHE is None:
        with open(os.path.join(CONFIG_DIR, "wallets.json")) as f:
            _WALLETS_CFG_CACHE = json.load(f)
    return _WALLETS_CFG_CACHE


_CONFIG_VALIDATED = False
_CONFIG_STRICT = False


def set_config_validation(strict=False):
    """Configure validation behavior for this process.

    Args:
        strict: If True, config validation errors raise ValueError.
                If False, errors are logged as warnings.
    """
    global _CONFIG_STRICT, _CONFIG_VALIDATED
    _CONFIG_STRICT = bool(strict)
    # Re-run once if strictness changed before first query invocation
    _CONFIG_VALIDATED = False


def _validate_config():
    """Validate config files have required fields. Called once on first query."""
    global _CONFIG_VALIDATED
    if _CONFIG_VALIDATED:
        return
    _CONFIG_VALIDATED = True

    errors = []
    contracts = _load_contracts_cfg()

    for chain, chain_data in contracts.items():
        if not isinstance(chain_data, dict) or chain.startswith("_"):
            continue
        for section_key, section in chain_data.items():
            if not isinstance(section, dict) or not section_key.startswith("_"):
                continue
            query_type = section.get("_query_type")
            for entry_key, entry in section.items():
                if entry_key.startswith("_") or not isinstance(entry, dict):
                    continue
                # All entries with abi field should have an address
                if "abi" in entry and "address" not in entry:
                    errors.append(f"{chain}.{section_key}.{entry_key}: has 'abi' but no 'address'")
                # Midas entries need oracle
                if query_type == "midas_oracle" and "oracle" in entry and "address" not in entry:
                    errors.append(f"{chain}.{section_key}.{entry_key}: midas entry has 'oracle' but no 'address'")

    # Validate morpho markets
    morpho = _load_morpho_cfg()
    for chain, chain_data in morpho.items():
        if not isinstance(chain_data, dict):
            continue
        for mkt in chain_data.get("markets", []):
            if "market_id" not in mkt:
                errors.append(f"morpho_markets.{chain}: market missing 'market_id'")
            for side in ("loan_token", "collateral_token"):
                tok = mkt.get(side, {})
                for field in ("symbol", "address", "decimals"):
                    if field not in tok:
                        errors.append(f"morpho_markets.{chain}.{mkt.get('name', '?')}.{side}: missing '{field}'")

    # Validate solana protocols
    solana = _load_solana_cfg()
    for ob in solana.get("kamino", {}).get("obligations", []):
        if "obligation_pubkey" not in ob:
            errors.append(f"solana_protocols.kamino: obligation missing 'obligation_pubkey'")
    for mkt in solana.get("exponent", {}).get("markets", []):
        if "market_pubkey" not in mkt:
            errors.append(f"solana_protocols.exponent: market missing 'market_pubkey'")
        for sub in ("sy", "pt"):
            if sub not in mkt:
                errors.append(f"solana_protocols.exponent.{mkt.get('name', '?')}: missing '{sub}'")

    if errors:
        if _CONFIG_STRICT:
            raise ValueError(
                "Config validation failed with "
                f"{len(errors)} issue(s): " + "; ".join(errors)
            )
        print(f"WARNING: Config validation found {len(errors)} issues:")
        for e in errors:
            print(f"  - {e}")


def _get_display_name(entry, vault_addr, fallback=""):
    """Get display name from config entry, falling back to entry_key."""
    return entry.get("display_name", fallback)


def _get_underlying_symbol(entry, vault_addr, fallback="USDC"):
    """Get underlying token symbol from config entry."""
    return entry.get("underlying_symbol", fallback)


def _fmt(val, decimals):
    """Convert raw uint256 to human-readable Decimal."""
    return Decimal(str(val)) / Decimal(10 ** decimals)


def _load_abis():
    """Load all ABIs from config/abis.json."""
    with open(os.path.join(CONFIG_DIR, "abis.json")) as f:
        return json.load(f)


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

        rows.append({
            "chain": chain, "protocol": "aave", "wallet": wallet,
            "position_label": _get_display_name(aentry, aentry["address"], akey),
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

        rows.append({
            "chain": chain, "protocol": "aave", "wallet": wallet,
            "position_label": _get_display_name(dentry, dentry["address"], dkey),
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

def query_gauntlet_falconx(w3, chain, wallet, block_number, block_ts):
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
    contracts = _load_contracts_cfg()
    gp_section = contracts.get("ethereum", {}).get("_gauntlet_pareto", {})
    GAUNTLET_VAULT = gp_section.get("gauntlet_vault", {}).get("address", "0x00000000d8f3d6c5DFeB2D2b5ED2276095f3aF44")
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

def query_uniswap_v4(w3, chain, wallet, block_number, block_ts):
    """Query Uniswap V4 NFT LP positions.

    Reads position manager address and NFT IDs from contracts.json _uniswap section.
    Reports liquidity amount for each owned NFT.
    """
    contracts = _load_contracts_cfg()
    uni_section = contracts.get(chain, {}).get("_uniswap", {})
    pm_entry = uni_section.get("v4_position_manager", {})
    PM = pm_entry.get("address")
    nft_ids = pm_entry.get("nft_ids", [])
    if not PM or not nft_ids:
        return []

    # Check ownership
    owner_abi = [{"inputs": [{"name": "tokenId", "type": "uint256"}], "name": "ownerOf",
                  "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"}]
    liq_abi = [{"inputs": [{"name": "tokenId", "type": "uint256"}], "name": "getPositionLiquidity",
                "outputs": [{"name": "", "type": "uint128"}], "stateMutability": "view", "type": "function"}]

    pm = w3.eth.contract(address=Web3.to_checksum_address(PM), abi=owner_abi + liq_abi)

    rows = []
    for nft_id in nft_ids:
        try:
            owner = pm.functions.ownerOf(nft_id).call()
        except Exception:
            continue

        if owner.lower() != wallet.lower():
            continue

        liquidity = pm.functions.getPositionLiquidity(nft_id).call()
        if liquidity == 0:
            continue

        rows.append({
            "chain": chain, "protocol": "uniswap_v4", "wallet": wallet,
            "position_label": f"Uniswap V4 USDC/DUSD #{nft_id}",
            "category": "C", "position_type": "lp_position",
            "token_symbol": f"UNI-V4-{nft_id}",
            "token_contract": PM,
            "balance_human": Decimal(str(liquidity)),
            "nft_id": nft_id,
            "block_number": block_number, "block_timestamp_utc": block_ts,
            "notes": f"Concentrated liquidity USDC/DUSD 0.01% fee. NFT #{nft_id}.",
        })

    return rows


# =============================================================================
# EVM: Ethena sUSDe Cooldowns (pending unstakes)
# =============================================================================

def query_ethena_cooldowns(w3, chain, wallet, block_number, block_ts):
    """Query Ethena sUSDe cooldown (pending unstakes).
    Reads sUSDe address from contracts.json _ethena section.
    """
    contracts = _load_contracts_cfg()
    ethena_section = contracts.get(chain, {}).get("_ethena", {})
    susde_entry = ethena_section.get("susde", {})
    susde_addr = susde_entry.get("address")
    usde_addr = susde_entry.get("usde_token", "0x4c9edd5852cd905f086c759e8383e09bff1e68b3")
    if not susde_addr:
        return []

    cooldown_abi = [{"inputs": [{"name": "account", "type": "address"}],
                     "name": "cooldowns",
                     "outputs": [{"name": "cooldownEnd", "type": "uint104"},
                                 {"name": "underlyingAmount", "type": "uint152"}],
                     "stateMutability": "view", "type": "function"}]

    susde = w3.eth.contract(address=Web3.to_checksum_address(susde_addr), abi=cooldown_abi)

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


# =============================================================================
# EVM: Midas (Category A2 — tokenised fund shares with oracle)
# =============================================================================

def query_midas_positions(w3, chain, wallet, block_number, block_ts):
    """Query Midas tokenised fund positions (mF-ONE, mHYPER, msyrupUSDp).

    Reads token addresses and oracles from contracts.json _midas section.
    """
    contracts = _load_contracts_cfg()
    midas_section = contracts.get(chain, {}).get("_midas", {})
    if not midas_section:
        return []

    erc20_abi = _get_abi("erc20")
    rows = []

    for entry_key, entry in midas_section.items():
        if entry_key.startswith("_") or not isinstance(entry, dict):
            continue
        if "address" not in entry or "oracle" not in entry:
            continue  # Skip oracle-only entries (like mhyper_oracle)

        token = w3.eth.contract(
            address=Web3.to_checksum_address(entry["address"]), abi=erc20_abi)
        try:
            bal = token.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
        except Exception:
            continue

        if bal == 0:
            continue

        bal_human = _fmt(bal, entry.get("decimals", 18))

        rows.append({
            "chain": chain, "protocol": "midas", "wallet": wallet,
            "position_label": entry.get("display_name", entry.get("symbol", entry_key)),
            "category": "A2", "position_type": "oracle_priced",
            "token_symbol": entry.get("symbol", entry_key),
            "token_contract": entry["address"],
            "balance_raw": str(bal),
            "balance_human": bal_human,
            "decimals": entry.get("decimals", 18),
            "oracle_address": entry["oracle"],
            "oracle_chain": entry.get("oracle_chain", "ethereum"),
            "block_number": block_number, "block_timestamp_utc": block_ts,
        })

    return rows


# =============================================================================
# EVM: FalconX Direct AA_FalconXUSDC (Category A3)
# =============================================================================

def query_falconx_direct(w3, chain, wallet, block_number, block_ts):
    """Query direct AA_FalconXUSDC holding for A3 accrual.

    Reads the Running Balance from the supporting workbook (Direct Accrual sheet).
    """
    contracts = _load_contracts_cfg()
    gp_section = contracts.get("ethereum", {}).get("_gauntlet_pareto", {})
    AA_TRANCHE = gp_section.get("aa_falconxusdc_tranche", {}).get("address", "0xC26A6Fa2C37b38E549a4a1807543801Db684f99C")
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

def query_creditcoop(w3, chain, wallet, block_number, block_ts):
    """Query CreditCoop vault — ERC-4626 convertToAssets + sub-strategy breakdown.

    Returns:
    - Main A1 position (aggregate via convertToAssets)
    - Sub-strategy breakdown rows for methodology log:
      - Rain credit line (totalActiveCredit on CreditStrategy)
      - Gauntlet USDC Core (totalAssets on LiquidStrategy)
      - Undeployed cash (USDC balanceOf on vault + credit strategy)
    """
    contracts = _load_contracts_cfg()
    cc_section = contracts.get("ethereum", {}).get("_credit_coop", {})
    VAULT = cc_section.get("vault", {}).get("address")
    LIQUID_STRATEGY = cc_section.get("liquid_strategy", {}).get("address")
    CREDIT_STRATEGY = cc_section.get("credit_strategy", {}).get("address")
    USDC = cc_section.get("usdc_token", {}).get("address", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
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

    Reads obligation configs from solana_protocols.json kamino section.
    Returns collateral + debt rows for each known obligation.
    """
    solana_cfg = _load_solana_cfg()
    obligations = solana_cfg.get("kamino", {}).get("obligations", [])

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
    """Query Exponent LP positions and decompose into SY + PT constituents.

    Reads market configs from solana_protocols.json exponent section.
    """
    solana_cfg = _load_solana_cfg()
    markets = solana_cfg.get("exponent", {}).get("markets", [])

    lp_positions = get_exponent_lp_positions(wallet)
    if not lp_positions:
        return []

    rows = []
    for mcfg in markets:
        lp = next(
            (l for l in lp_positions if l["market"] == mcfg["market_pubkey"]),
            None
        )
        if lp is None or lp["lp_balance"] == 0:
            continue

        sy = mcfg["sy"]
        pt = mcfg["pt"]

        time.sleep(0.3)
        market = get_exponent_market(mcfg["market_pubkey"])
        time.sleep(0.3)
        lp_supply_resp = solana_rpc("getTokenSupply", [market["lp_mint"]])
        lp_supply = int(lp_supply_resp["result"]["value"]["amount"])

        decomp = decompose_exponent_lp(market, lp["lp_balance"], lp_supply)

        sy_amount = Decimal(decomp["user_sy"]) / Decimal(10 ** sy["decimals"])
        pt_amount = Decimal(decomp["user_pt"]) / Decimal(10 ** pt["decimals"])
        pt_price_ratio = Decimal(str(decomp["pt_price_ratio"]))

        # SY constituent row
        rows.append({
            "chain": "solana", "protocol": "exponent", "wallet": wallet,
            "position_label": f"Exponent {mcfg['name']} LP",
            "category": "C", "position_type": "lp_constituent",
            "token_symbol": sy["symbol"],
            "token_category": sy["category"],
            "balance_human": sy_amount,
            "decimals": sy["decimals"],
            "lp_constituent_type": "SY",
            "lp_share": decomp["lp_share"],
            "block_timestamp_utc": block_ts,
        })

        # PT constituent row
        rows.append({
            "chain": "solana", "protocol": "exponent", "wallet": wallet,
            "position_label": f"Exponent {mcfg['name']} LP",
            "category": "C", "position_type": "lp_constituent",
            "token_symbol": pt["symbol"],
            "token_category": "C",  # PT in LP uses AMM rate, not lot amortisation
            "balance_human": pt_amount,
            "decimals": pt["decimals"],
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
    """Query Exponent Yield Token positions.

    Reads market configs from solana_protocols.json exponent section.
    """
    solana_cfg = _load_solana_cfg()
    markets = solana_cfg.get("exponent", {}).get("markets", [])

    yt_positions = get_exponent_yt_positions(wallet)
    if not yt_positions:
        return []

    rows = []
    for mcfg in markets:
        yt_cfg = mcfg.get("yt")
        if not yt_cfg:
            continue
        yt_vault = mcfg.get("yt_vault")
        if not yt_vault:
            continue

        yt = next(
            (y for y in yt_positions if y["vault"] == yt_vault),
            None
        )
        if yt is None or yt["yt_balance"] == 0:
            continue

        yt_human = Decimal(yt["yt_balance"]) / Decimal(10 ** yt_cfg["decimals"])

        # Get PT price ratio from market for YT pricing
        time.sleep(0.3)
        market = get_exponent_market(mcfg["market_pubkey"])
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
            "underlying_symbol": yt_cfg.get("underlying", ""),
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
# Config-driven wallet → protocol mapping
# =============================================================================

def _get_wallet_protocols(chain, wallet):
    """Get list of protocol keys this wallet is registered for on this chain.

    Reads from wallets.json instead of hardcoded KNOWN_POSITIONS.
    For ethereum chain: uses the wallet's 'protocols' dict.
    For other chains: uses '_chain_protocols' section.
    Also checks morpho_markets.json for Morpho positions.
    """
    wallet_lower = wallet.lower()
    wallets_cfg = _load_wallets_cfg()
    protocols = set()

    # Check ethereum wallet entries (used for all EVM chains on ethereum section)
    if chain == "ethereum":
        for w in wallets_cfg.get("ethereum", []):
            if w["address"].lower() == wallet_lower:
                for p_key, enabled in w.get("protocols", {}).items():
                    if enabled:
                        protocols.add(p_key)
                break

    # Check chain-specific protocol registrations
    chain_protocols = wallets_cfg.get("_chain_protocols", {}).get(chain, {})
    wallet_chain_entry = chain_protocols.get(wallet_lower)
    if wallet_chain_entry:
        for p_key, enabled in wallet_chain_entry.get("protocols", {}).items():
            if enabled:
                protocols.add(p_key)

    # Check morpho_markets.json for wallet-specific Morpho positions
    morpho_cfg = _load_morpho_cfg()
    chain_morpho = morpho_cfg.get(chain, {})
    for mkt in chain_morpho.get("markets", []):
        if wallet_lower in [w.lower() for w in mkt.get("wallets", [])]:
            protocols.add("morpho")
            break

    return list(protocols)


# =============================================================================
# Protocol key -> handler mapping
# =============================================================================

# Protocol key (from wallets.json) -> handler key
PROTOCOL_TO_HANDLER = {
    "morpho":           "morpho_leverage",
    "erc4626_vaults":   "erc4626",
    "euler":            "euler_erc4626",
    "aave":             "aave_leverage",
    "midas":            "midas_oracle",
    "gauntlet_falconx": "manual_accrual_gauntlet",
    "falconx_direct":   "manual_accrual_direct",
    "uniswap_v4":       "nft_lp",
    "ethena_cooldowns": "ethena_cooldown",
    "credit_coop":      "credit_coop",
}

# Handler key -> handler function
HANDLER_REGISTRY = {
    "morpho_leverage":          query_morpho_markets,
    "erc4626":                  query_erc4626_vaults,
    "euler_erc4626":            query_euler_vaults,
    "aave_leverage":            query_aave_positions,
    "midas_oracle":             query_midas_positions,
    "manual_accrual_gauntlet":  query_gauntlet_falconx,
    "manual_accrual_direct":    query_falconx_direct,
    "nft_lp":                   query_uniswap_v4,
    "ethena_cooldown":          query_ethena_cooldowns,
    "credit_coop":              query_creditcoop,
}


# =============================================================================
# Orchestrator: query all EVM positions for a wallet on a chain
# =============================================================================

def query_evm_wallet_positions(chain, wallet, wallet_desc="", block_override=None):
    """Query all protocol positions for one wallet on one EVM chain.

    Config-driven: reads wallet protocol registrations from wallets.json,
    dispatches to the appropriate handler via HANDLER_REGISTRY.

    Args:
        chain: EVM chain name.
        wallet: Wallet address.
        wallet_desc: Optional description for logging.
        block_override: Optional (block_number, block_ts_str) tuple for
                        Valuation Block pinning. If None, uses latest block.
    """
    _validate_config()

    protocols = _get_wallet_protocols(chain, wallet)
    if not protocols:
        return []

    try:
        w3 = get_web3(chain)
        if block_override:
            block_number, block_ts = block_override
        else:
            block_number, block_ts = get_block_info(w3)
    except (ConnectionError, Exception) as e:
        print(f"  [{chain}] SKIP -- {e}")
        return []

    rows = []
    for protocol_key in protocols:
        handler_key = PROTOCOL_TO_HANDLER.get(protocol_key)
        if not handler_key:
            continue
        handler = HANDLER_REGISTRY.get(handler_key)
        if not handler:
            continue
        # Single retry with backoff for resilience
        for attempt in range(2):
            try:
                handler_rows = handler(w3, chain, wallet, block_number, block_ts)
                rows.extend(handler_rows)
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(2)  # brief backoff before retry
                else:
                    print(f"  [{chain}] {protocol_key} error (after retry): {e}")

    return rows


# =============================================================================
# Orchestrator helper: query all Solana positions
# =============================================================================

def query_solana_positions(wallet, valuation_date=None, block_ts_override=None):
    """Query all Solana protocol positions for a wallet.

    Includes Kamino obligations, Exponent LPs, Exponent YTs, and PT lots.

    Args:
        wallet: Solana wallet address.
        valuation_date: Optional date for PT lot valuation.
        block_ts_override: Optional (slot, block_ts_str) tuple for
                           Valuation Block pinning. If None, uses current time.
    """
    _validate_config()

    from datetime import datetime, timezone
    if block_ts_override:
        _slot, block_ts = block_ts_override
    else:
        block_ts = datetime.now(timezone.utc).strftime(TS_FMT)

    rows = []

    # Helper: run a Solana handler with single retry
    def _run_with_retry(name, fn):
        for attempt in range(2):
            try:
                result = fn()
                print(f"  [solana] {name}: {len(result)} positions")
                return result
            except Exception as e:
                if attempt == 0:
                    time.sleep(2)
                else:
                    print(f"  [solana] {name} error (after retry): {e}")
        return []

    # Kamino obligations (D)
    rows.extend(_run_with_retry(
        "Kamino", lambda: query_kamino_obligations(wallet, block_ts)))

    # Exponent LPs (C)
    lp_rows = _run_with_retry(
        "Exponent LP", lambda: query_exponent_lps(wallet, block_ts))
    rows.extend(lp_rows)

    # Exponent YTs (F)
    rows.extend(_run_with_retry(
        "Exponent YT", lambda: query_exponent_yts(wallet, block_ts)))

    # PT lots (B)
    if valuation_date:
        rows.extend(_run_with_retry(
            "PT lots", lambda: query_pt_lots(valuation_date, block_ts)))

    return rows
