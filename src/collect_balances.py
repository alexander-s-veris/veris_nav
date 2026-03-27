"""
Production wallet balance scanner for Veris Capital AMC.

Queries all wallets across all chains, filters against the token registry,
prices per Valuation Policy (Category E and F), and outputs to JSON + CSV.
"""

import os
import csv
import json
import sys
import requests
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

# Add src/ to path so imports work when run from project root
sys.path.insert(0, os.path.dirname(__file__))

from evm import (
    CONFIG_DIR, OUTPUT_DIR, TS_FMT,
    ETHERSCAN_V2_BASE, NATIVE_TOKEN,
    load_chains, get_evm_chains, get_web3, get_block_info, get_rpc_url,
)
from pricing import get_price, get_prices_concurrent
from block_utils import concurrent_query

OUTPUT_FIELDS = [
    "wallet",
    "chain",
    "token_contract",
    "token_symbol",
    "token_name",
    "category",
    "balance",
    "price_usd",
    "price_source",
    "value_usd",
    "depeg_flag",
    "notes",
    "block_number",
    "block_timestamp_utc",
    "run_timestamp_cet",
]


# --- Token Registry ---

def load_tokens_registry() -> dict:
    """Load config/tokens.json. Returns dict keyed by chain, then by lowered address."""
    with open(os.path.join(CONFIG_DIR, "tokens.json")) as f:
        registry = json.load(f)
    # Remove template key
    registry.pop("_template", None)
    return registry


def load_wallets() -> dict:
    with open(os.path.join(CONFIG_DIR, "wallets.json")) as f:
        return json.load(f)


# --- EVM Balance Queries ---

def get_token_metadata_alchemy(w3: Web3, contract_address: str) -> dict:
    """Fetch token symbol and decimals via Alchemy's alchemy_getTokenMetadata."""
    result = w3.provider.make_request("alchemy_getTokenMetadata", [contract_address])
    data = result.get("result", {})
    return {
        "symbol": data.get("symbol", "UNKNOWN"),
        "decimals": data.get("decimals", 18),
        "name": data.get("name", ""),
    }


def query_balances_alchemy(w3: Web3, chain: str, wallet: str,
                           block_number: int, block_ts: str,
                           registry: dict) -> list[dict]:
    """Query native + ERC-20 balances via Alchemy, filter against registry."""
    rows = []
    checksum_wallet = Web3.to_checksum_address(wallet)
    chain_registry = registry.get(chain, {})

    # Native balance
    native_wei = w3.eth.get_balance(checksum_wallet)
    native_balance = Decimal(native_wei) / Decimal(10**18)
    native_entry = chain_registry.get("native")

    if native_entry and native_balance > 0:
        rows.append({
            "wallet": wallet,
            "chain": chain,
            "token_contract": "native",
            "token_symbol": native_entry["symbol"],
            "token_name": native_entry["name"],
            "category": native_entry["category"],
            "balance": native_balance,
            "block_number": block_number,
            "block_timestamp_utc": block_ts,
            "_registry_entry": native_entry,
        })

    # ERC-20 balances via Alchemy
    try:
        response = w3.provider.make_request(
            "alchemy_getTokenBalances",
            [checksum_wallet, "erc20"],
        )
        token_balances = response.get("result", {}).get("tokenBalances", [])
    except Exception as e:
        print(f"  alchemy_getTokenBalances failed on {chain}: {e}")
        token_balances = []

    found_contracts = set()
    for tb in token_balances:
        raw_balance = int(tb.get("tokenBalance", "0x0"), 16)
        if raw_balance == 0:
            continue

        contract_addr = tb["contractAddress"].lower()
        token_entry = chain_registry.get(contract_addr)

        if token_entry is None:
            continue  # Not in registry — skip spam

        found_contracts.add(contract_addr)
        decimals = token_entry.get("decimals")
        if decimals is None:
            metadata = get_token_metadata_alchemy(w3, tb["contractAddress"])
            decimals = metadata["decimals"] or 18

        human_balance = Decimal(raw_balance) / Decimal(10**decimals)

        rows.append({
            "wallet": wallet,
            "chain": chain,
            "token_contract": contract_addr,
            "token_symbol": token_entry["symbol"],
            "token_name": token_entry["name"],
            "category": token_entry["category"],
            "balance": human_balance,
            "block_number": block_number,
            "block_timestamp_utc": block_ts,
            "_registry_entry": token_entry,
        })

    # Fallback: direct balanceOf for registry tokens not found by Alchemy
    ERC20_BALANCE_ABI = [{"inputs": [{"name": "account", "type": "address"}],
                          "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}],
                          "stateMutability": "view", "type": "function"}]
    for contract_addr, token_entry in chain_registry.items():
        if contract_addr == "native" or contract_addr in found_contracts:
            continue
        try:
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(contract_addr), abi=ERC20_BALANCE_ABI)
            raw_balance = contract.functions.balanceOf(checksum_wallet).call()
            if raw_balance == 0:
                continue
            decimals = token_entry.get("decimals", 18)
            human_balance = Decimal(raw_balance) / Decimal(10**decimals)
            rows.append({
                "wallet": wallet, "chain": chain,
                "token_contract": contract_addr,
                "token_symbol": token_entry["symbol"],
                "token_name": token_entry["name"],
                "category": token_entry["category"],
                "balance": human_balance,
                "block_number": block_number,
                "block_timestamp_utc": block_ts,
                "_registry_entry": token_entry,
            })
        except Exception:
            pass  # Contract may not exist on this chain

    return rows


def query_balances_etherscan(chain: str, chain_id: int, wallet: str,
                             registry: dict) -> list[dict]:
    """Query native + ERC-20 balances via Etherscan V2 API, filter against registry."""
    rows = []
    api_key = os.getenv("ETHERSCAN_API_KEY")
    chain_registry = registry.get(chain, {})

    # Get block info via Etherscan proxy
    block_number = "N/A"
    block_ts = "N/A"
    try:
        resp = requests.get(ETHERSCAN_V2_BASE, params={
            "chainid": chain_id, "module": "proxy",
            "action": "eth_blockNumber", "apikey": api_key,
        }, timeout=10)
        data = resp.json()
        if data.get("result"):
            block_number = str(int(data["result"], 16))
            resp2 = requests.get(ETHERSCAN_V2_BASE, params={
                "chainid": chain_id, "module": "proxy",
                "action": "eth_getBlockByNumber",
                "tag": data["result"], "boolean": "false", "apikey": api_key,
            }, timeout=10)
            block_data = resp2.json()
            if block_data.get("result", {}).get("timestamp"):
                ts = int(block_data["result"]["timestamp"], 16)
                block_ts = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(TS_FMT)
    except Exception:
        pass

    # Native balance
    native_entry = chain_registry.get("native")
    try:
        resp = requests.get(ETHERSCAN_V2_BASE, params={
            "chainid": chain_id, "module": "account", "action": "balance",
            "address": wallet, "tag": "latest", "apikey": api_key,
        }, timeout=10)
        data = resp.json()
        if data.get("status") == "1" and native_entry:
            native_wei = int(data["result"])
            native_balance = Decimal(native_wei) / Decimal(10**18)
            if native_balance > 0:
                rows.append({
                    "wallet": wallet, "chain": chain,
                    "token_contract": "native",
                    "token_symbol": native_entry["symbol"],
                    "token_name": native_entry["name"],
                    "category": native_entry["category"],
                    "balance": native_balance,
                    "block_number": block_number, "block_timestamp_utc": block_ts,
                    "_registry_entry": native_entry,
                })
    except Exception:
        pass

    # ERC-20 tokens via Etherscan V2
    page = 1
    while True:
        try:
            resp = requests.get(ETHERSCAN_V2_BASE, params={
                "chainid": chain_id, "module": "account",
                "action": "addresstokenbalance",
                "address": wallet, "page": page, "offset": 100, "apikey": api_key,
            }, timeout=10)
            data = resp.json()
        except Exception:
            break

        if data.get("status") != "1" or not data.get("result"):
            break

        for token in data["result"]:
            raw_balance = int(token.get("TokenQuantity", "0"))
            if raw_balance == 0:
                continue

            contract_addr = token.get("TokenAddress", "").lower()
            token_entry = chain_registry.get(contract_addr)
            if token_entry is None:
                continue

            decimals = token_entry.get("decimals", int(token.get("TokenDivisor", "18")))
            human_balance = Decimal(raw_balance) / Decimal(10**decimals)

            rows.append({
                "wallet": wallet, "chain": chain,
                "token_contract": contract_addr,
                "token_symbol": token_entry["symbol"],
                "token_name": token_entry["name"],
                "category": token_entry["category"],
                "balance": human_balance,
                "block_number": block_number, "block_timestamp_utc": block_ts,
                "_registry_entry": token_entry,
            })

        if len(data["result"]) < 100:
            break
        page += 1

    # Fallback: direct balanceOf via Etherscan proxy for registry tokens not found
    found_contracts = {r["token_contract"] for r in rows if r["token_contract"] != "native"}
    for contract_addr, token_entry in chain_registry.items():
        if contract_addr == "native" or contract_addr in found_contracts:
            continue
        try:
            # balanceOf(address) selector = 0x70a08231
            call_data = "0x70a08231" + wallet[2:].lower().zfill(64)
            resp = requests.get(ETHERSCAN_V2_BASE, params={
                "chainid": chain_id, "module": "proxy", "action": "eth_call",
                "to": contract_addr, "data": call_data, "tag": "latest",
                "apikey": api_key,
            }, timeout=10)
            result = resp.json()
            if result.get("result") and result["result"] != "0x":
                raw_balance = int(result["result"], 16)
                if raw_balance == 0:
                    continue
                decimals = token_entry.get("decimals", 18)
                human_balance = Decimal(raw_balance) / Decimal(10**decimals)
                rows.append({
                    "wallet": wallet, "chain": chain,
                    "token_contract": contract_addr,
                    "token_symbol": token_entry["symbol"],
                    "token_name": token_entry["name"],
                    "category": token_entry["category"],
                    "balance": human_balance,
                    "block_number": block_number, "block_timestamp_utc": block_ts,
                    "_registry_entry": token_entry,
                })
        except Exception:
            pass

    return rows


# --- Solana Balance Query ---

def query_balances_solana(wallet: str, registry: dict,
                          slot_override: tuple = None) -> list[dict]:
    """Query native SOL + SPL token balances via Alchemy Solana RPC.

    Args:
        wallet: Solana wallet address.
        registry: Token registry dict.
        slot_override: Optional (slot, block_ts_str) tuple for Valuation Block
                       pinning. If None, uses latest slot.
    """
    rows = []
    solana_registry = registry.get("solana", {})
    api_key = os.getenv("ALCHEMY_API_KEY")
    rpc_url = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"

    def rpc_call(method: str, params: list) -> dict:
        resp = requests.post(rpc_url, json={
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
        }, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # Get slot (Solana's equivalent of block number)
    if slot_override:
        slot, block_ts = slot_override
    else:
        try:
            slot_resp = rpc_call("getSlot", [])
            slot = slot_resp.get("result", "N/A")
            # Get block time for the slot
            time_resp = rpc_call("getBlockTime", [slot])
            block_time = time_resp.get("result")
            block_ts = datetime.fromtimestamp(block_time, tz=timezone.utc).strftime(TS_FMT) if block_time else "N/A"
        except Exception:
            slot = "N/A"
            block_ts = "N/A"

    # Native SOL balance
    native_entry = solana_registry.get("native")
    try:
        bal_resp = rpc_call("getBalance", [wallet])
        lamports = bal_resp.get("result", {}).get("value", 0)
        sol_balance = Decimal(lamports) / Decimal(10**9)
        if native_entry and sol_balance > 0:
            rows.append({
                "wallet": wallet, "chain": "solana",
                "token_contract": "native",
                "token_symbol": "SOL", "token_name": "Solana",
                "category": native_entry["category"],
                "balance": sol_balance,
                "block_number": str(slot), "block_timestamp_utc": block_ts,
                "_registry_entry": native_entry,
            })
    except Exception as e:
        print(f"  Solana native balance failed: {e}")

    # SPL token accounts
    try:
        token_resp = rpc_call("getTokenAccountsByOwner", [
            wallet,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"},
        ])
        accounts = token_resp.get("result", {}).get("value", [])
    except Exception as e:
        print(f"  Solana SPL token query failed: {e}")
        accounts = []

    for account in accounts:
        parsed = account.get("account", {}).get("data", {}).get("parsed", {})
        info = parsed.get("info", {})
        mint = info.get("mint", "").lower()
        token_amount = info.get("tokenAmount", {})

        raw_amount = int(token_amount.get("amount", "0"))
        if raw_amount == 0:
            continue

        # Solana mint addresses are case-sensitive, but we lowercase in registry
        token_entry = solana_registry.get(mint)
        if token_entry is None:
            # Try original case
            token_entry = solana_registry.get(info.get("mint", ""))
        if token_entry is None:
            continue

        decimals = token_entry.get("decimals", int(token_amount.get("decimals", 9)))
        human_balance = Decimal(raw_amount) / Decimal(10**decimals)

        rows.append({
            "wallet": wallet, "chain": "solana",
            "token_contract": info.get("mint", mint),
            "token_symbol": token_entry["symbol"],
            "token_name": token_entry["name"],
            "category": token_entry["category"],
            "balance": human_balance,
            "block_number": str(slot), "block_timestamp_utc": block_ts,
            "_registry_entry": token_entry,
        })

    return rows


# --- Output ---

def build_methodology(request_ts_utc: str, request_ts_cet: str,
                      chains_queried: list, wallet_count: int) -> dict:
    """Build the _methodology header block for JSON output."""
    return {
        "description": "Wallet balance snapshot for Veris Capital AMC NAV calculation",
        "scope": "Category A1, A2, E, and F tokens held directly in wallet balances",
        "valuation_policy_ref": "Valuation Policy v1.0 — Sections 6.1 (A1), 6.2 (A2), 6.7 (E), 6.8 (F), 9.4 (de-peg)",
        "pricing_rules": {
            "E_par": "USDC-pegged stablecoins (USDC, DAI, PYUSD, USDS) valued at par ($1.00). Chainlink oracle on Ethereum queried for de-peg check per Section 9.4. Deviation >0.5% triggers actual traded value pricing; >2% = material de-peg.",
            "E_oracle": "Non-USDC-pegged stablecoins (USDT, USDG, USDD) valued at oracle price. Source hierarchy: Chainlink → Pyth → CoinGecko (Section 6.2 tier 1).",
            "A2_oracle": "Off-chain yield-bearing tokens (ONyc) priced via Pyth Network oracle (Section 6.2).",
            "A1_exchange_rate": "On-chain yield-bearing tokens (eUSX) priced by querying the on-chain exchange rate from Solana, then multiplying by the underlying token price via Pyth (Section 6.1).",
            "F_governance": "Governance tokens (MORPHO, PENDLE, ARB, etc.) priced via: (1) Kraken reported price, (2) CoinGecko aggregated price (Section 6.8).",
            "F_other": "Other tokens (DAM, GIZA, RLP, etc.) priced via CoinGecko.",
            "F_native": "Native chain tokens (ETH, AVAX, XPL, HYPE, SOL) priced via Kraken or CoinGecko.",
            "filtering": "Only tokens pre-registered in config/tokens.json are included. Unregistered tokens (spam, airdrops, unsolicited deposits) are excluded. All whitelisted tokens with balance >$0 are included regardless of value.",
        },
        "data_retrieval": {
            "evm_primary": "Alchemy alchemy_getTokenBalances RPC (returns all ERC-20 balances in one call)",
            "evm_fallback": "Direct balanceOf contract call for registered tokens not indexed by Alchemy",
            "evm_plasma": "Etherscan V2 API (Alchemy not available for Plasma)",
            "solana": "Alchemy Solana RPC getTokenAccountsByOwner (returns all SPL token accounts)",
            "solana_exchange_rate": "eUSX/USX rate derived from vault: total USX held by mint authority / total eUSX supply",
        },
        "chains_queried": chains_queried,
        "wallets_queried": wallet_count,
        "run_timestamp_utc": request_ts_utc,
        "run_timestamp_cet": request_ts_cet,
    }


# --- Main ---

def main():
    request_ts = datetime.now(timezone.utc)
    request_ts_str = request_ts.strftime(TS_FMT)
    # CET is UTC+1 year-round (no daylight saving adjustment per Valuation Policy)
    CET = timezone(timedelta(hours=1))
    run_ts_cet = request_ts.astimezone(CET).strftime(TS_FMT)

    registry = load_tokens_registry()
    wallets = load_wallets()
    chains = load_chains()
    evm_chains = get_evm_chains()
    evm_wallets = wallets.get("ethereum", [])
    solana_wallets = wallets.get("solana", [])

    print(f"Veris NAV — Wallet Balance Collection")
    print(f"Run: {request_ts_str}")
    print(f"EVM chains: {', '.join(evm_chains)}")
    print(f"EVM wallets: {len(evm_wallets)} × {len(evm_chains)} chains = {len(evm_wallets) * len(evm_chains)} queries")
    print(f"Solana wallets: {len(solana_wallets)}")
    print()

    raw_rows = []

    # --- Scan all chains concurrently, wallets within each chain also concurrent ---
    import time as _time

    def _scan_single_wallet_alchemy(args):
        """Scan one wallet on one Alchemy chain. Thread-safe."""
        w3, chain_name, w_entry, block_number, block_ts = args
        wallet = w_entry["address"]
        wallet_rows = query_balances_alchemy(
            w3, chain_name, wallet, block_number, block_ts, registry)
        log = []
        for r in wallet_rows:
            log.append(f"  {w_entry['description']}: {r['token_symbol']} = {r['balance']}")
        return wallet_rows, log

    def _scan_single_wallet_etherscan(args):
        """Scan one wallet on one Etherscan chain. Thread-safe."""
        chain_name, chain_id, w_entry = args
        wallet = w_entry["address"]
        wallet_rows = query_balances_etherscan(
            chain_name, chain_id, wallet, registry)
        log = []
        for r in wallet_rows:
            log.append(f"  {w_entry['description']}: {r['token_symbol']} = {r['balance']}")
        return wallet_rows, log

    def _scan_single_wallet_balanceof(args):
        """Scan one wallet via direct balanceOf. Thread-safe."""
        w3, chain_name, w_entry, block_number, block_ts, chain_registry = args
        wallet = w_entry["address"]
        checksum = Web3.to_checksum_address(wallet)
        rows = []
        log = []
        ERC20_ABI = [{"inputs": [{"name": "account", "type": "address"}],
                      "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}],
                      "stateMutability": "view", "type": "function"}]
        for contract_addr, token_entry in chain_registry.items():
            if contract_addr == "native":
                native_wei = w3.eth.get_balance(checksum)
                if native_wei > 0:
                    bal = Decimal(native_wei) / Decimal(10**18)
                    rows.append({
                        "wallet": wallet, "chain": chain_name,
                        "token_contract": "native",
                        "token_symbol": token_entry["symbol"],
                        "token_name": token_entry["name"],
                        "category": token_entry["category"],
                        "balance": bal,
                        "block_number": block_number, "block_timestamp_utc": block_ts,
                        "_registry_entry": token_entry,
                    })
                    log.append(f"  {w_entry['description']}: {token_entry['symbol']} = {bal}")
                continue
            try:
                contract = w3.eth.contract(
                    address=Web3.to_checksum_address(contract_addr), abi=ERC20_ABI)
                raw = contract.functions.balanceOf(checksum).call()
                if raw > 0:
                    decimals = token_entry.get("decimals", 18)
                    bal = Decimal(raw) / Decimal(10**decimals)
                    rows.append({
                        "wallet": wallet, "chain": chain_name,
                        "token_contract": contract_addr,
                        "token_symbol": token_entry["symbol"],
                        "token_name": token_entry["name"],
                        "category": token_entry["category"],
                        "balance": bal,
                        "block_number": block_number, "block_timestamp_utc": block_ts,
                        "_registry_entry": token_entry,
                    })
                    log.append(f"  {w_entry['description']}: {token_entry['symbol']} = {bal}")
            except Exception:
                pass
        return rows, log

    def scan_evm_chain(chain_name):
        """Scan all wallets on a single EVM chain concurrently."""
        t0 = _time.time()
        chain_cfg = chains[chain_name]
        log = []
        rows = []

        balance_method = chain_cfg.get("token_balance_method")

        if balance_method == "etherscan_v2":
            wallet_tasks = [
                (chain_name, chain_cfg["chain_id"], w) for w in evm_wallets
            ]
            wallet_results = concurrent_query(
                _scan_single_wallet_etherscan, wallet_tasks,
                max_workers=len(evm_wallets))
            for wallet_rows, wallet_log in wallet_results:
                rows.extend(wallet_rows)
                log.extend(wallet_log)

        elif balance_method == "balance_of":
            try:
                w3 = get_web3(chain_name)
                block_number, block_ts = get_block_info(w3)
                log.append(f"  Block: {block_number} ({block_ts})")
            except ConnectionError as e:
                log.append(f"  SKIP — {e}")
                elapsed = _time.time() - t0
                log.append(f"  ({elapsed:.1f}s)")
                return chain_name, rows, log

            chain_registry = registry.get(chain_name, {})
            wallet_tasks = [
                (w3, chain_name, w, block_number, block_ts, chain_registry)
                for w in evm_wallets
            ]
            wallet_results = concurrent_query(
                _scan_single_wallet_balanceof, wallet_tasks,
                max_workers=len(evm_wallets))
            for wallet_rows, wallet_log in wallet_results:
                rows.extend(wallet_rows)
                log.extend(wallet_log)

        else:
            # Alchemy path
            try:
                w3 = get_web3(chain_name)
                block_number, block_ts = get_block_info(w3)
                log.append(f"  Block: {block_number} ({block_ts})")
            except ConnectionError as e:
                log.append(f"  SKIP — {e}")
                elapsed = _time.time() - t0
                log.append(f"  ({elapsed:.1f}s)")
                return chain_name, rows, log

            wallet_tasks = [
                (w3, chain_name, w, block_number, block_ts) for w in evm_wallets
            ]
            wallet_results = concurrent_query(
                _scan_single_wallet_alchemy, wallet_tasks,
                max_workers=len(evm_wallets))
            for wallet_rows, wallet_log in wallet_results:
                rows.extend(wallet_rows)
                log.extend(wallet_log)

        elapsed = _time.time() - t0
        log.append(f"  ({elapsed:.1f}s)")
        return chain_name, rows, log

    def scan_solana():
        """Scan all Solana wallets."""
        t0 = _time.time()
        log = []
        rows = []
        for w_entry in solana_wallets:
            wallet = w_entry["address"]
            sol_rows = query_balances_solana(wallet, registry)
            rows.extend(sol_rows)
            for r in sol_rows:
                log.append(f"  {w_entry['description']}: {r['token_symbol']} = {r['balance']}")
        elapsed = _time.time() - t0
        log.append(f"  ({elapsed:.1f}s)")
        return "solana", rows, log

    # Build task list: all EVM chains + Solana
    all_tasks = [lambda cn=cn: scan_evm_chain(cn) for cn in evm_chains]
    if solana_wallets:
        all_tasks.append(scan_solana)

    t_start = _time.time()

    print(f"Scanning {len(all_tasks)} chains concurrently (wallets parallel within each)...")
    chain_results = concurrent_query(
        query_fn=lambda fn: fn(),
        items=all_tasks,
        max_workers=len(all_tasks),
    )

    t_chains = _time.time()
    print(f"Chain scanning: {t_chains - t_start:.1f}s")

    # Print results in chain order and collect rows
    for chain_name, rows, log_lines in chain_results:
        print(f"[{chain_name}]")
        for line in log_lines:
            print(line)
        raw_rows.extend(rows)
        print()

    # --- Pricing (concurrent) ---
    print("Pricing tokens...")
    try:
        w3_eth = get_web3("ethereum")
    except ConnectionError:
        w3_eth = None
        print("  WARNING: Cannot connect to Ethereum — Chainlink de-peg checks unavailable")

    # Collect unique tokens
    unique_tokens = {}
    for row in raw_rows:
        symbol = row["token_symbol"]
        if symbol not in unique_tokens:
            unique_tokens[symbol] = row["_registry_entry"]

    # Price all tokens concurrently
    t_price_start = _time.time()
    price_results = get_prices_concurrent(unique_tokens, w3_eth)
    t_price_end = _time.time()
    for symbol, result in price_results.items():
        print(f"  {symbol}: ${result['price_usd']} ({result['price_source']})")
    print(f"Pricing: {t_price_end - t_price_start:.1f}s ({len(price_results)} tokens)")

    # --- Build output rows ---
    output_rows = []
    for row in raw_rows:
        price_result = get_price(row["_registry_entry"], w3_eth)
        balance = row["balance"]
        price = price_result["price_usd"]
        value = balance * price

        notes = price_result.get("notes", "")

        output_rows.append({
            "wallet": row["wallet"],
            "chain": row["chain"],
            "token_contract": row["token_contract"],
            "token_symbol": row["token_symbol"],
            "token_name": row["token_name"],
            "category": row["category"],
            "balance": str(row["balance"]),
            "price_usd": str(price_result["price_usd"]),
            "price_source": price_result["price_source"],
            "value_usd": str(value),
            "depeg_flag": price_result["depeg_flag"],
            "notes": notes,
            "block_number": str(row["block_number"]),
            "block_timestamp_utc": row["block_timestamp_utc"],
            "run_timestamp_cet": run_ts_cet,
        })

    # --- Write outputs ---
    chains_queried = evm_chains + (["solana"] if solana_wallets else [])
    total_wallets = len(evm_wallets) * len(evm_chains) + len(solana_wallets)
    methodology = build_methodology(request_ts_str, run_ts_cet, chains_queried, total_wallets)

    # JSON with methodology header
    json_output = {
        "_methodology": methodology,
        "positions": output_rows,
    }
    json_path = os.path.join(OUTPUT_DIR, "wallet_balances.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_output, f, indent=2)
    print(f"\nJSON written: {json_path}")

    # CSV (positions only)
    csv_path = os.path.join(OUTPUT_DIR, "wallet_balances.csv")
    if output_rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(output_rows)
        print(f"CSV  written: {csv_path}")

    t_end = _time.time()
    print(f"\nTotal: {len(output_rows)} registered token balances across {len(chains_queried)} chains")
    print(f"Skipped: {len(raw_rows) - len(output_rows)} rows (if any from pricing failures)")
    print(f"Total time: {t_end - t_start:.1f}s")


if __name__ == "__main__":
    main()
