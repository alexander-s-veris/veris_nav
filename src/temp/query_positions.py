"""
Reusable position query script for wallet walkthrough.
Queries Morpho markets, ERC-4626 vaults, Aave positions, plain token balances,
and Gauntlet/Pareto cross-reference — all via RPC.

Usage:
    python src/temp/query_positions.py <wallet_address> [chain1,chain2,...]

If no chains specified, queries all chains where the wallet has registered positions.
"""
import sys
import os
import json
from decimal import Decimal

# Setup paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR = os.path.dirname(SRC_DIR)
CONFIG_DIR = os.path.join(PROJECT_DIR, "config")

sys.path.insert(0, SRC_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

from evm import get_web3, get_block_info

# --- ABIs ---

ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply",
     "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

ERC4626_ABI = ERC20_ABI + [
    {"inputs": [{"name": "shares", "type": "uint256"}], "name": "convertToAssets",
     "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

MORPHO_ABI = [
    {"inputs": [{"name": "id", "type": "bytes32"}, {"name": "user", "type": "address"}],
     "name": "position",
     "outputs": [{"name": "supplyShares", "type": "uint256"},
                 {"name": "borrowShares", "type": "uint128"},
                 {"name": "collateral", "type": "uint128"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "id", "type": "bytes32"}], "name": "market",
     "outputs": [{"name": "totalSupplyAssets", "type": "uint128"},
                 {"name": "totalSupplyShares", "type": "uint128"},
                 {"name": "totalBorrowAssets", "type": "uint128"},
                 {"name": "totalBorrowShares", "type": "uint128"},
                 {"name": "lastUpdate", "type": "uint128"},
                 {"name": "fee", "type": "uint128"}],
     "stateMutability": "view", "type": "function"},
]

CHAINLINK_ABI = [
    {"inputs": [], "name": "latestRoundData",
     "outputs": [{"name": "roundId", "type": "uint80"}, {"name": "answer", "type": "int256"},
                 {"name": "startedAt", "type": "uint256"}, {"name": "updatedAt", "type": "uint256"},
                 {"name": "answeredInRound", "type": "uint80"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
]

PARETO_ABI = [
    {"inputs": [{"name": "", "type": "address"}], "name": "tranchePrice",
     "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]


def fmt(val, decimals):
    """Convert raw integer to human-readable Decimal."""
    return Decimal(str(val)) / Decimal(10 ** decimals)


def load_config(filename):
    with open(os.path.join(CONFIG_DIR, filename)) as f:
        return json.load(f)


# --- Morpho Markets (Category D) ---

def query_morpho_markets(wallet):
    """Query all Morpho market positions for a wallet."""
    morpho_cfg = load_config("morpho_markets.json")
    results = []

    for chain_name in ["ethereum", "arbitrum", "base"]:
        chain_cfg = morpho_cfg.get(chain_name, {})
        morpho_addr = chain_cfg.get("morpho_contract")
        if not morpho_addr:
            continue

        markets = [m for m in chain_cfg.get("markets", [])
                   if wallet.lower() in [w.lower() for w in m.get("wallets", [])]]
        if not markets:
            continue

        w3 = get_web3(chain_name)
        block_num, block_ts = get_block_info(w3)
        morpho = w3.eth.contract(address=w3.to_checksum_address(morpho_addr), abi=MORPHO_ABI)

        for mkt in markets:
            is_closed = "_note" in mkt and "Closed" in mkt.get("_note", "")
            market_id = bytes.fromhex(mkt["market_id"][2:])

            if is_closed:
                # Verify it's actually closed
                pos = morpho.functions.position(market_id, w3.to_checksum_address(wallet)).call()
                if pos[2] == 0 and pos[1] == 0:
                    results.append({
                        "chain": chain_name, "name": mkt["name"], "status": "CLOSED",
                        "block": block_num, "block_ts": block_ts,
                    })
                    continue

            pos = morpho.functions.position(market_id, w3.to_checksum_address(wallet)).call()
            supply_shares, borrow_shares, collateral = pos

            mkt_state = morpho.functions.market(market_id).call()
            total_borrow_assets, total_borrow_shares = mkt_state[2], mkt_state[3]
            borrow_assets = borrow_shares * total_borrow_assets // total_borrow_shares if total_borrow_shares > 0 else 0

            results.append({
                "chain": chain_name, "name": mkt["name"], "status": "ACTIVE",
                "block": block_num, "block_ts": block_ts,
                "collateral_raw": collateral,
                "collateral_human": fmt(collateral, mkt["collateral_token"]["decimals"]),
                "collateral_symbol": mkt["collateral_token"]["symbol"],
                "collateral_decimals": mkt["collateral_token"]["decimals"],
                "borrow_human": fmt(borrow_assets, mkt["loan_token"]["decimals"]),
                "borrow_symbol": mkt["loan_token"]["symbol"],
            })

    return results


# --- ERC-4626 Vaults (Category A1) ---

def query_erc4626_vault(w3, vault_addr, wallet, share_decimals, underlying_decimals=None):
    """Query an ERC-4626 vault for a wallet's shares and underlying."""
    vault = w3.eth.contract(address=w3.to_checksum_address(vault_addr), abi=ERC4626_ABI)
    shares = vault.functions.balanceOf(w3.to_checksum_address(wallet)).call()
    if shares == 0:
        return Decimal(0), Decimal(0)
    assets_raw = vault.functions.convertToAssets(shares).call()
    shares_human = fmt(shares, share_decimals)
    assets_human = fmt(assets_raw, underlying_decimals or share_decimals)
    return shares_human, assets_human


# --- Euler V2 (with sub-account scan) ---

def query_euler_vault(w3, vault_addr, wallet, share_decimals, known_sub=None):
    """Query Euler vault, scanning sub-accounts if needed."""
    vault = w3.eth.contract(address=w3.to_checksum_address(vault_addr), abi=ERC4626_ABI)
    wallet_int = int(wallet, 16)

    if known_sub is not None:
        subs_to_check = [known_sub]
    else:
        subs_to_check = range(256)

    results = []
    for i in subs_to_check:
        sub_addr = w3.to_checksum_address(hex(wallet_int ^ i))
        shares = vault.functions.balanceOf(sub_addr).call()
        if shares > 0:
            assets = vault.functions.convertToAssets(shares).call()
            results.append({
                "sub_account": i,
                "sub_address": sub_addr,
                "shares": fmt(shares, share_decimals),
                "assets": fmt(assets, share_decimals),
            })

    return results


# --- Aave (aToken balanceOf) ---

def query_aave_balance(w3, atoken_addr, wallet, decimals):
    """Query Aave aToken or debt token balance."""
    token = w3.eth.contract(address=w3.to_checksum_address(atoken_addr), abi=ERC20_ABI)
    bal = token.functions.balanceOf(w3.to_checksum_address(wallet)).call()
    return fmt(bal, decimals)


# --- Plain ERC-20 balance ---

def query_erc20_balance(w3, token_addr, wallet, decimals):
    """Query plain ERC-20 token balance."""
    token = w3.eth.contract(address=w3.to_checksum_address(token_addr), abi=ERC20_ABI)
    bal = token.functions.balanceOf(w3.to_checksum_address(wallet)).call()
    return fmt(bal, decimals)


# --- Chainlink oracle price ---

def query_chainlink_price(w3, feed_addr):
    """Query Chainlink oracle for latest price."""
    feed = w3.eth.contract(address=w3.to_checksum_address(feed_addr), abi=CHAINLINK_ABI)
    decimals = feed.functions.decimals().call()
    round_data = feed.functions.latestRoundData().call()
    price = fmt(round_data[1], decimals)
    updated_at = round_data[3]
    return price, updated_at


# --- Gauntlet / Pareto FalconX (cross-reference) ---

def query_gauntlet_falconx(w3, wallet):
    """Query Gauntlet vault cross-reference for FalconX position."""
    GAUNTLET_VAULT = "0x00000000d8f3d6c5DFeB2D2b5ED2276095f3aF44"
    MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
    MARKET_ID = "0xe83d72fa5b00dcd46d9e0e860d95aa540d5ec106da5833108a9f826f21f36f52"
    PARETO_PRICE = "0x433d5b175148da32ffe1e1a37a939e1b7e79be4d"
    PARETO_TRANCHE = "0xC26A6Fa2C37b38E549a4a1807543801Db684f99C"

    market_id_bytes = bytes.fromhex(MARKET_ID[2:])

    # Tranche price
    pareto = w3.eth.contract(address=w3.to_checksum_address(PARETO_PRICE), abi=PARETO_ABI)
    tranche_price = fmt(pareto.functions.tranchePrice(w3.to_checksum_address(PARETO_TRANCHE)).call(), 6)

    # Vault's Morpho position
    morpho = w3.eth.contract(address=w3.to_checksum_address(MORPHO), abi=MORPHO_ABI)
    pos = morpho.functions.position(market_id_bytes, w3.to_checksum_address(GAUNTLET_VAULT)).call()
    collateral = fmt(pos[2], 18)
    mkt = morpho.functions.market(market_id_bytes).call()
    borrow = fmt(pos[1] * mkt[2] // mkt[3], 6) if mkt[3] > 0 else Decimal(0)

    # Veris's share
    vault = w3.eth.contract(address=w3.to_checksum_address(GAUNTLET_VAULT), abi=ERC20_ABI)
    veris_shares = vault.functions.balanceOf(w3.to_checksum_address(wallet)).call()
    total_supply = vault.functions.totalSupply().call()
    share_pct = Decimal(str(veris_shares)) / Decimal(str(total_supply)) if total_supply > 0 else Decimal(0)

    collateral_value = collateral * tranche_price
    net = collateral_value - borrow
    veris_portion = net * share_pct

    return {
        "tranche_price": tranche_price,
        "vault_collateral": collateral,
        "vault_collateral_value": collateral_value,
        "vault_borrow": borrow,
        "vault_net": net,
        "veris_shares": fmt(veris_shares, 18),
        "total_supply": fmt(total_supply, 18),
        "veris_pct": share_pct * 100,
        "veris_portion": veris_portion,
    }


# --- CreditCoop Vault (ERC-4626 cross-reference) ---

def query_creditcoop(w3, wallet):
    """Query CreditCoop vault — ERC-4626 convertToAssets as cross-reference."""
    VAULT = "0xb21eAFB126cEf15CB99fe2D23989b58e40097919"
    vault = w3.eth.contract(address=w3.to_checksum_address(VAULT), abi=ERC4626_ABI)
    shares = vault.functions.balanceOf(w3.to_checksum_address(wallet)).call()
    if shares == 0:
        return {"shares": Decimal(0), "assets": Decimal(0)}
    assets = vault.functions.convertToAssets(shares).call()
    return {
        "shares": fmt(shares, 6),
        "assets": fmt(assets, 6),
    }


# --- Main ---

def main():
    if len(sys.argv) < 2:
        print("Usage: python query_positions.py <wallet_address> [chain1,chain2,...]")
        sys.exit(1)

    wallet = sys.argv[1].lower()
    chains = sys.argv[2].split(",") if len(sys.argv) > 2 else None

    print("=" * 80)
    print(f"POSITIONS FOR {wallet}")
    print("=" * 80)

    # Morpho Markets (D)
    print("\n--- MORPHO MARKETS (Category D) ---")
    morpho_results = query_morpho_markets(wallet)
    for r in morpho_results:
        if r["status"] == "CLOSED":
            print(f"\n  [{r['chain']}] {r['name']} — CLOSED (block {r['block']})")
        else:
            print(f"\n  [{r['chain']}] {r['name']} (block {r['block']}, {r['block_ts']})")
            print(f"    Collateral: {r['collateral_human']:,.6f} {r['collateral_symbol']}")
            print(f"    Borrow:     {r['borrow_human']:,.6f} {r['borrow_symbol']}")

    # Gauntlet/FalconX cross-reference (only for 0x0c16)
    if "0x0c1644d7af63df4a3b15423dbe04a1927c00a4f4" in wallet:
        print("\n--- GAUNTLET / FALCONX (A3 cross-reference) ---")
        w3_eth = get_web3("ethereum")
        block_num, block_ts = get_block_info(w3_eth)
        gf = query_gauntlet_falconx(w3_eth, wallet)
        print(f"  Block: {block_num}, Timestamp: {block_ts}")
        print(f"  Tranche price: ${gf['tranche_price']}")
        print(f"  Veris shares: {gf['veris_shares']:,.6f} / {gf['total_supply']:,.6f} ({gf['veris_pct']:.4f}%)")
        print(f"  Vault collateral: {gf['vault_collateral']:,.6f} AA_FalconXUSDC = ${gf['vault_collateral_value']:,.2f}")
        print(f"  Vault borrow: ${gf['vault_borrow']:,.2f} USDC")
        print(f"  Vault net: ${gf['vault_net']:,.2f}")
        print(f"  Veris portion: ${gf['veris_portion']:,.2f}")

    # CreditCoop (check for relevant wallets)
    for credit_wallet in ["0x0c1644d7af63df4a3b15423dbe04a1927c00a4f4",
                          "0xec0b3a9321a5a0a0492bbe20c4d9cd908b10e21a"]:
        if credit_wallet in wallet:
            print("\n--- CREDIT COOP (A3 cross-reference) ---")
            w3_eth = get_web3("ethereum")
            block_num, block_ts = get_block_info(w3_eth)
            cc = query_creditcoop(w3_eth, wallet)
            print(f"  Block: {block_num}, Timestamp: {block_ts}")
            print(f"  Shares: {cc['shares']:,.6f}")
            print(f"  convertToAssets: ${cc['assets']:,.2f}")

    # ERC-4626 vaults — check known vaults for this wallet
    # (extend as needed per wallet)

    print("\n" + "=" * 80)
    print("Done.")


if __name__ == "__main__":
    main()
