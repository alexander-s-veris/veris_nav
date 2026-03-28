"""
Production position collection orchestrator for the Veris NAV system.

Queries ALL protocol positions across all EVM chains and Solana, combines
with wallet token balances, applies category-specific valuation, deduplicates,
and outputs the full NAV snapshot.

Usage:
    python src/collect.py                       # latest block, all wallets
    python src/collect.py --date 2026-04-30     # specific valuation date
"""

import argparse
import json
import os
import sys
import time as _time
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from evm import (
    CONFIG_DIR, OUTPUT_DIR, TS_FMT, CET,
    load_chains, get_evm_chains, get_web3, get_block_info,
    find_valuation_block,
)
from block_utils import concurrent_query
from collect_balances import (
    load_tokens_registry, load_wallets,
    query_balances_alchemy, query_balances_solana,
    query_balances_etherscan,
)
from protocol_queries import (
    query_evm_wallet_positions,
    query_solana_positions,
    set_config_validation,
)
from valuation import value_position
from output import (
    write_positions, write_leverage_detail, write_pt_lots,
    write_lp_decomposition, write_verification, write_nav_summary,
)
from verifiers import run_asset_verifications


def main():
    parser = argparse.ArgumentParser(description="Veris NAV Position Collection")
    parser.add_argument("--date", type=str, help="Valuation date (YYYY-MM-DD)")
    parser.add_argument("--strict-config", action="store_true",
                        help="Fail fast if config validation finds missing required fields")
    args = parser.parse_args()

    valuation_date = date.fromisoformat(args.date) if args.date else date.today()

    now = datetime.now(timezone.utc)
    run_ts_cet = now.astimezone(CET).strftime(TS_FMT)
    run_ts_utc = now.strftime(TS_FMT)

    print("=" * 80, flush=True)
    print("VERIS NAV — FULL POSITION COLLECTION")
    print(f"Valuation date: {valuation_date}")
    print(f"Run: {run_ts_cet} CET")
    print("=" * 80, flush=True)

    set_config_validation(strict=args.strict_config)

    # --- Load configs ---
    registry = load_tokens_registry()
    wallets = load_wallets()
    chains = load_chains()
    evm_chains = get_evm_chains()
    evm_wallets = wallets.get("ethereum", [])
    solana_wallets = wallets.get("solana", [])
    arma_proxies = wallets.get("arma_proxies", [])

    # Ethereum Web3 for pricing (Chainlink oracles)
    try:
        w3_eth = get_web3("ethereum")
    except ConnectionError:
        w3_eth = None
        print("WARNING: Cannot connect to Ethereum — Chainlink pricing unavailable")

    # --- Valuation Block pinning ---
    # When --date is specified, find the block on each chain closest to but not
    # exceeding 15:00 UTC on the valuation date. All on-chain queries use this block.
    valuation_blocks = {}  # chain -> (block_number, block_ts_str)
    solana_valuation_slot = None  # (slot, slot_ts_str)
    valuation_ts = None

    if args.date:
        valuation_dt = datetime(valuation_date.year, valuation_date.month,
                                valuation_date.day, 15, 0, 0, tzinfo=timezone.utc)
        valuation_ts = int(valuation_dt.timestamp())

        print(f"Valuation time: {valuation_dt.strftime(TS_FMT)} UTC")
        print("Finding valuation blocks...", flush=True)

        def find_block_for_chain(chain_name):
            try:
                w3 = get_web3(chain_name)
                bn, bts = find_valuation_block(w3, chain_name, valuation_ts)
                return chain_name, bn, bts
            except Exception as e:
                print(f"  [{chain_name}] Cannot find valuation block: {e}")
                return chain_name, None, None

        block_results = concurrent_query(find_block_for_chain, evm_chains,
                                         max_workers=len(evm_chains))

        for chain_name, bn, bts in block_results:
            if bn is not None:
                valuation_blocks[chain_name] = (bn, bts)
                print(f"  [{chain_name}] Block {bn} ({bts})")

        # Solana valuation slot
        try:
            from solana_client import find_valuation_slot
            sol_slot, sol_ts = find_valuation_slot(valuation_ts)
            solana_valuation_slot = (sol_slot, sol_ts)
            print(f"  [solana] Slot {sol_slot} ({sol_ts})")
        except Exception as e:
            print(f"  [solana] Cannot find valuation slot: {e}")

        print()

    # --- Output directory ---
    output_dir = os.path.join(OUTPUT_DIR, f"nav_{valuation_date.strftime('%Y%m%d')}")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output: {output_dir}")
    print()

    all_positions = []
    t_start = _time.time()

    # Chain health tracking — populated during steps 1+2, included in output
    chain_health = {}  # chain -> {"balances": int, "positions": int, "errors": [str]}

    def _track_chain(chain_name, balances=0, positions=0, error=None):
        if chain_name not in chain_health:
            chain_health[chain_name] = {"balances": 0, "positions": 0, "errors": []}
        chain_health[chain_name]["balances"] += balances
        chain_health[chain_name]["positions"] += positions
        if error:
            chain_health[chain_name]["errors"].append(error)

    def _to_position(r, protocol="wallet", wallet_override=None, notes=""):
        """Convert a balance scanner row to a position dict."""
        pos = {
            "chain": r["chain"], "protocol": protocol,
            "wallet": wallet_override or r["wallet"],
            "position_label": r["token_symbol"], "category": r["category"],
            "position_type": "token_balance", "token_symbol": r["token_symbol"],
            "token_contract": r["token_contract"],
            "balance_human": r["balance"],
            "block_number": r["block_number"],
            "block_timestamp_utc": r["block_timestamp_utc"],
            "_registry_entry": r.get("_registry_entry"),
        }
        if notes:
            pos["notes"] = notes
        return pos

    # =========================================================================
    # STEPS 1+2: Run wallet balances and protocol positions CONCURRENTLY
    # =========================================================================
    from concurrent.futures import ThreadPoolExecutor

    wallet_balance_rows = []
    protocol_rows = []

    # --- Step 1 worker: wallet token balances ---
    def run_step1():
        """Scan all wallet token balances across all chains."""
        rows = []
        log = []

        # Balance scanner dispatch, keyed by chain config "token_balance_method"
        def _scan_alchemy(chain_name, chain_cfg):
            chain_rows = []
            try:
                w3 = get_web3(chain_name)
                if chain_name in valuation_blocks:
                    bn, bts = valuation_blocks[chain_name]
                else:
                    bn, bts = get_block_info(w3)
                for w in evm_wallets:
                    chain_rows.extend(query_balances_alchemy(
                        w3, chain_name, w["address"], bn, bts, registry))
            except ConnectionError as e:
                _track_chain(chain_name, error=f"balance scan: {e}")
            return chain_rows

        def _scan_etherscan(chain_name, chain_cfg):
            chain_rows = []
            for w in evm_wallets:
                chain_rows.extend(query_balances_etherscan(
                    chain_name, chain_cfg["chain_id"], w["address"], registry))
            return chain_rows

        balance_scanners = {
            "alchemy": _scan_alchemy,
            "etherscan_v2": _scan_etherscan,
            "balance_of": lambda cn, cc: [],  # Handled by protocol queries (e.g. Katana)
        }

        def scan_evm_balances(chain_name):
            chain_cfg = chains[chain_name]
            method = chain_cfg.get("token_balance_method", "alchemy")
            scanner = balance_scanners.get(method, _scan_alchemy)
            return chain_name, scanner(chain_name, chain_cfg)

        evm_tasks = [lambda cn=cn: scan_evm_balances(cn) for cn in evm_chains]
        evm_results = concurrent_query(lambda fn: fn(), evm_tasks, max_workers=len(evm_tasks))

        for chain_name, chain_rows in evm_results:
            _track_chain(chain_name, balances=len(chain_rows))
            if chain_rows:
                log.append(f"  [{chain_name}] {len(chain_rows)} token balances")
            for r in chain_rows:
                rows.append(_to_position(r))

        # Solana
        for w in solana_wallets:
            try:
                sol_rows = query_balances_solana(w["address"], registry,
                                                slot_override=solana_valuation_slot)
            except Exception as e:
                sol_rows = []
                _track_chain("solana", error=f"balance scan: {e}")
            _track_chain("solana", balances=len(sol_rows))
            log.append(f"  [solana] {len(sol_rows)} token balances")
            for r in sol_rows:
                rows.append(_to_position(r))

        # ARMA proxies — scan as regular wallets, annotate with parent
        for proxy in arma_proxies:
            p_chain, p_addr = proxy["chain"], proxy["address"]
            parent_wallet = proxy.get("parent_wallet", p_addr)
            try:
                w3 = get_web3(p_chain)
                if p_chain in valuation_blocks:
                    bn, bts = valuation_blocks[p_chain]
                else:
                    bn, bts = get_block_info(w3)
                proxy_rows = query_balances_alchemy(w3, p_chain, p_addr, bn, bts, registry)
                if proxy_rows:
                    log.append(f"  [{p_chain}] ARMA {p_addr[:8]}...: {len(proxy_rows)} balances")
                for r in proxy_rows:
                    rows.append(_to_position(
                        r, protocol="arma", wallet_override=parent_wallet,
                        notes=f"ARMA proxy {p_addr[:10]}... on {p_chain}"))
            except Exception:
                pass

        return rows, log

    # --- Step 2 worker: protocol positions ---
    def run_step2():
        """Query all protocol positions across all chains."""
        rows = []
        log = []

        for chain_name in evm_chains:
            t_chain = _time.time()
            block_override = valuation_blocks.get(chain_name)
            chain_pos_count = 0

            # Regular wallets + ARMA proxies on this chain
            all_evm_wallets = [(w["address"], w["address"]) for w in evm_wallets]
            for proxy in arma_proxies:
                if proxy["chain"] == chain_name:
                    all_evm_wallets.append(
                        (proxy["address"], proxy.get("parent_wallet", proxy["address"])))

            # Parallelize wallet queries within each chain
            def _query_wallet(wallet_pair):
                scan_addr, report_wallet = wallet_pair
                return query_evm_wallet_positions(
                    chain_name, scan_addr, block_override=block_override)

            wallet_results = concurrent_query(
                _query_wallet, all_evm_wallets,
                max_workers=min(6, len(all_evm_wallets)))

            for (scan_addr, report_wallet), chain_rows in zip(all_evm_wallets, wallet_results):
                active = [r for r in chain_rows if r.get("status") != "CLOSED"]
                chain_pos_count += len(active)
                is_proxy = scan_addr.lower() != report_wallet.lower()
                if active:
                    label = f"ARMA {scan_addr[:8]}..." if is_proxy else f"{scan_addr[:8]}..."
                    log.append(f"  [{chain_name}] {label}: {len(active)} active positions")
                for r in chain_rows:
                    if is_proxy:
                        r["wallet"] = report_wallet
                        r["notes"] = r.get("notes", "") + f" (via ARMA proxy {scan_addr[:10]}...)"
                rows.extend(chain_rows)

            _track_chain(chain_name, positions=chain_pos_count)
            elapsed = _time.time() - t_chain
            if elapsed > 1:
                log.append(f"  [{chain_name}] ({elapsed:.1f}s)")

        # Solana
        for w in solana_wallets:
            try:
                sol_rows = query_solana_positions(
                    w["address"], valuation_date,
                    block_ts_override=solana_valuation_slot)
                _track_chain("solana", positions=len(sol_rows))
                rows.extend(sol_rows)
            except Exception as e:
                _track_chain("solana", error=f"protocol scan: {e}")

        return rows, log

    # Run both steps concurrently
    print("--- Steps 1+2: Wallet Balances + Protocol Positions (concurrent) ---", flush=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_balances = executor.submit(run_step1)
        future_protocol = executor.submit(run_step2)

        wallet_balance_rows, balance_log = future_balances.result()
        protocol_rows, protocol_log = future_protocol.result()

    t_both = _time.time()

    print("  [Wallet Balances]")
    for line in balance_log:
        print(line)
    print(f"  Total: {len(wallet_balance_rows)} rows")

    print("  [Protocol Positions]")
    for line in protocol_log:
        print(line)
    active_protocol = [r for r in protocol_rows if r.get("status") != "CLOSED"]
    print(f"  Total: {len(active_protocol)} active")
    print(f"  Combined: {t_both - t_start:.1f}s", flush=True)

    # =========================================================================
    # STEP 3: Deduplication
    # =========================================================================
    print("\n--- Step 3: Deduplication ---")

    # Protocol positions override wallet token balances
    # Build set of (chain, wallet, token_contract) from protocol positions
    protocol_tokens = set()
    for pos in protocol_rows:
        if pos.get("status") == "CLOSED":
            continue
        contract = pos.get("token_contract", "").lower()
        if contract:
            protocol_tokens.add((pos["chain"], pos["wallet"].lower(), contract))

    # Filter wallet balances: remove tokens that appear as protocol positions
    deduplicated_balances = []
    removed_count = 0
    for bal in wallet_balance_rows:
        key = (bal["chain"], bal["wallet"].lower(), bal.get("token_contract", "").lower())
        if key in protocol_tokens:
            removed_count += 1
        else:
            deduplicated_balances.append(bal)

    print(f"  Wallet balances: {len(wallet_balance_rows)} -> {len(deduplicated_balances)} ({removed_count} deduplicated)")

    # Combine
    all_positions = protocol_rows + deduplicated_balances

    # =========================================================================
    # STEP 4: Valuation
    # =========================================================================
    print("\n--- Step 4: Valuation ---")

    # All positions — wallet balances and protocol positions alike — go through
    # value_position() for consistent category-specific pricing and depeg handling.
    for pos in all_positions:
        try:
            value_position(pos, w3_eth, valuation_date, registry)
        except Exception as e:
            pos["price_usd"] = Decimal(0)
            pos["value_usd"] = Decimal(0)
            pos["price_source"] = f"error: {e}"

    t_valuation = _time.time()
    print(f"  Valued {len(all_positions)} positions ({t_valuation - t_both:.1f}s)")

    # =========================================================================
    # STEP 4.5: Independent Verification (Section 7.3)
    # =========================================================================
    print("\n--- Step 4.5: Asset-Level Verification (Section 7.3) ---")

    verification_results = []
    try:
        verification_results = run_asset_verifications(all_positions)
        if verification_results:
            for v in verification_results:
                flag = v.get("divergence_flag", "")
                sym = v.get("token_symbol", "")
                div = v.get("divergence_pct", 0)
                err = v.get("error", "")
                if err:
                    print(f"  [{sym}] VERIFICATION ERROR: {err}")
                elif flag:
                    print(f"  [{sym}] {flag}")
                else:
                    print(f"  [{sym}] OK (divergence: {div:.2f}%)")
        else:
            print("  No tokens configured for verification")
    except Exception as e:
        print(f"  Verification step failed: {e}")

    # =========================================================================
    # STEP 5: Write Outputs
    # =========================================================================
    print("\n--- Step 5: Write Outputs ---")

    # Clean internal fields before output
    for pos in all_positions:
        pos.pop("_registry_entry", None)
        pos.pop("_pt_symbol", None)

    csv_path, json_path = write_positions(all_positions, output_dir, run_ts_cet)
    print(f"  {csv_path}")
    print(f"  {json_path}")

    lev_path = write_leverage_detail(all_positions, output_dir)
    if lev_path:
        print(f"  {lev_path}")

    pt_path = write_pt_lots(all_positions, output_dir)
    if pt_path:
        print(f"  {pt_path}")

    lp_path = write_lp_decomposition(all_positions, output_dir)
    if lp_path:
        print(f"  {lp_path}")

    ver_path = write_verification(verification_results, output_dir)
    if ver_path:
        print(f"  {ver_path}")

    # Build valuation block metadata for the summary
    vb_metadata = {}
    if valuation_blocks:
        for cn, (bn, bts) in valuation_blocks.items():
            vb_metadata[cn] = {"block_number": bn, "block_timestamp_utc": bts}
    if solana_valuation_slot:
        sol_slot, sol_ts = solana_valuation_slot
        vb_metadata["solana"] = {"slot": sol_slot, "slot_timestamp_utc": sol_ts}

    summary_path = write_nav_summary(all_positions, output_dir, run_ts_cet,
                                     valuation_blocks=vb_metadata,
                                     chain_health=chain_health,
                                     verification_results=verification_results)
    print(f"  {summary_path}")

    # =========================================================================
    # STEP 6: Summary
    # =========================================================================
    t_end = _time.time()
    print(f"\n{'=' * 80}")
    print(f"COLLECTION COMPLETE — {t_end - t_start:.1f}s")
    print(f"{'=' * 80}")

    # Chain health summary
    failed_chains = {c: h for c, h in chain_health.items() if h["errors"]}
    if failed_chains:
        print(f"\n*** CHAIN HEALTH — {len(failed_chains)} CHAIN(S) HAD ERRORS ***")
        for chain, health in sorted(failed_chains.items()):
            print(f"  [{chain}] {health['balances']} balances, {health['positions']} positions")
            for err in health["errors"]:
                print(f"    ERROR: {err}")
        print("  Run diff_snapshots.py to check for missing positions.")

    # Print summary table
    total_positive = Decimal(0)
    total_negative = Decimal(0)

    print(f"\n{'Category':<6} {'Count':>6} {'Gross Value':>18}")
    print("-" * 35)

    by_cat = {}
    for pos in all_positions:
        if pos.get("status") == "CLOSED":
            continue
        cat = pos.get("category", "?")
        val = pos.get("value_usd", Decimal(0))
        if not isinstance(val, Decimal):
            try:
                val = Decimal(str(val))
            except Exception:
                val = Decimal(0)
        if cat not in by_cat:
            by_cat[cat] = {"count": 0, "value": Decimal(0)}
        by_cat[cat]["count"] += 1
        by_cat[cat]["value"] += val
        if val >= 0:
            total_positive += val
        else:
            total_negative += val

    for cat in sorted(by_cat.keys()):
        info = by_cat[cat]
        print(f"  {cat:<4} {info['count']:>6} {info['value']:>18,.2f}")

    print("-" * 35)
    print(f"  {'TOTAL':.<12} {'Assets:':>8} {total_positive:>14,.2f}")
    print(f"  {'':.<12} {'Debt:':>8} {total_negative:>14,.2f}")
    print(f"  {'':.<12} {'Net:':>8} {total_positive + total_negative:>14,.2f}")


if __name__ == "__main__":
    main()
