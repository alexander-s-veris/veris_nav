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
    with open(os.path.join(CONFIG_DIR, "morpho_markets.json")) as f:
        morpho_cfg = json.load(f)

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
    with open(os.path.join(CONFIG_DIR, "contracts.json")) as f:
        contracts = json.load(f)

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
            decimals = vault.functions.decimals().call()
        except Exception:
            continue

        protocol = section_key.strip("_")
        shares_human = _fmt(shares, decimals)
        assets_human = _fmt(assets, decimals)

        rows.append({
            "chain": chain, "protocol": protocol, "wallet": wallet,
            "position_label": entry.get("description", entry_key),
            "category": "A1", "position_type": "vault_share",
            "token_symbol": entry_key,
            "token_contract": vault_addr,
            "balance_raw": str(shares),
            "balance_human": shares_human,
            "decimals": decimals,
            "exchange_rate": assets_human / shares_human if shares_human > 0 else Decimal(0),
            "underlying_amount": assets_human,
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
    with open(os.path.join(CONFIG_DIR, "contracts.json")) as f:
        contracts = json.load(f)

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
                decimals = vault.functions.decimals().call()
                shares_human = _fmt(shares, decimals)
                assets_human = _fmt(assets, decimals)

                rows.append({
                    "chain": chain, "protocol": "euler", "wallet": wallet,
                    "position_label": entry.get("description", entry_key),
                    "category": "A1", "position_type": "vault_share",
                    "token_symbol": entry_key,
                    "token_contract": vault_addr,
                    "balance_raw": str(shares),
                    "balance_human": shares_human,
                    "decimals": decimals,
                    "exchange_rate": assets_human / shares_human if shares_human > 0 else Decimal(0),
                    "underlying_amount": assets_human,
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
    with open(os.path.join(CONFIG_DIR, "contracts.json")) as f:
        contracts = json.load(f)

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
        desc = aentry.get("description", akey)

        rows.append({
            "chain": chain, "protocol": "aave", "wallet": wallet,
            "position_label": desc,
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
            "position_label": dentry.get("description", dkey),
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
    """Query Gauntlet vault + Pareto tranche price for FalconX A3 cross-reference.

    Only relevant for wallet 0x0c16. Returns A3 position with on-chain cross-ref data.
    """
    GAUNTLET_VAULT = "0x00000000d8f3d6c5DFeB2D2b5ED2276095f3aF44"
    MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
    MARKET_ID = "0xe83d72fa5b00dcd46d9e0e860d95aa540d5ec106da5833108a9f826f21f36f52"
    PARETO_PRICE = "0x433d5b175148da32ffe1e1a37a939e1b7e79be4d"
    PARETO_TRANCHE = "0xC26A6Fa2C37b38E549a4a1807543801Db684f99C"
    AA_FALCON = "0xC26A6Fa2C37b38E549a4a1807543801Db684f99C"

    market_id_bytes = bytes.fromhex(MARKET_ID[2:])
    erc20_abi = _get_abi("erc20")

    # Veris's Gauntlet vault share
    vault = w3.eth.contract(address=Web3.to_checksum_address(GAUNTLET_VAULT), abi=erc20_abi)
    veris_shares = vault.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
    total_supply = vault.functions.totalSupply().call()

    if veris_shares == 0:
        return []

    share_pct = Decimal(str(veris_shares)) / Decimal(str(total_supply))

    # Vault's Morpho position (collateral + debt)
    morpho = w3.eth.contract(
        address=Web3.to_checksum_address(MORPHO), abi=_get_abi("morpho_core"))
    pos = morpho.functions.position(
        market_id_bytes, Web3.to_checksum_address(GAUNTLET_VAULT)).call()
    collateral = _fmt(pos[2], 18)  # AA_FalconXUSDC, 18 dec
    mkt = morpho.functions.market(market_id_bytes).call()
    borrow = _fmt(pos[1] * mkt[2] // mkt[3], 6) if mkt[3] > 0 else Decimal(0)

    # Tranche price (cross-reference only, NOT for primary valuation)
    pareto_abi = _get_abi("pareto_credit_vault")
    pareto = w3.eth.contract(address=Web3.to_checksum_address(PARETO_PRICE), abi=pareto_abi)
    tranche_price = _fmt(
        pareto.functions.tranchePrice(Web3.to_checksum_address(PARETO_TRANCHE)).call(), 6)

    collateral_value = collateral * tranche_price
    vault_net = collateral_value - borrow
    veris_portion = vault_net * share_pct

    return [{
        "chain": "ethereum", "protocol": "gauntlet_pareto", "wallet": wallet,
        "position_label": "Gauntlet FalconX (A3 — accrual from workbook)",
        "category": "A3", "position_type": "manual_accrual",
        "token_symbol": "gpAAFalconX",
        "token_contract": GAUNTLET_VAULT,
        "balance_raw": str(veris_shares),
        "balance_human": _fmt(veris_shares, 18),
        "decimals": 18,
        "veris_share_pct": share_pct * 100,
        "cross_ref_tranche_price": tranche_price,
        "cross_ref_vault_net": vault_net,
        "cross_ref_veris_portion": veris_portion,
        "block_number": block_number, "block_timestamp_utc": block_ts,
        "notes": "Primary value from supporting workbook (outputs/falconx_position.xlsx). On-chain TP is cross-reference only.",
    }]


# =============================================================================
# EVM: CreditCoop (Category A1)
# =============================================================================

def query_creditcoop(w3, wallet, block_number, block_ts):
    """Query CreditCoop vault — ERC-4626 convertToAssets."""
    VAULT = "0xb21eAFB126cEf15CB99fe2D23989b58e40097919"
    vault = w3.eth.contract(
        address=Web3.to_checksum_address(VAULT), abi=_get_abi("erc4626"))

    shares = vault.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
    if shares == 0:
        return []

    assets = vault.functions.convertToAssets(shares).call()
    shares_human = _fmt(shares, 6)
    assets_human = _fmt(assets, 6)

    return [{
        "chain": "ethereum", "protocol": "credit_coop", "wallet": wallet,
        "position_label": "Credit Coop Veris Vault (A1)",
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

def query_evm_wallet_positions(chain, wallet, wallet_desc=""):
    """Query all protocol positions for one wallet on one EVM chain.

    Returns list of raw position dicts (not yet priced).
    """
    try:
        w3 = get_web3(chain)
        block_number, block_ts = get_block_info(w3)
    except (ConnectionError, Exception) as e:
        print(f"  [{chain}] SKIP — {e}")
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

    # Gauntlet/FalconX (A3, only for 0x0c16 on Ethereum)
    if chain == "ethereum" and "0x0c16" in wallet.lower():
        try:
            gf_rows = query_gauntlet_falconx(w3, wallet, block_number, block_ts)
            rows.extend(gf_rows)
        except Exception as e:
            print(f"  [{chain}] Gauntlet/FalconX error: {e}")

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
