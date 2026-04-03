"""
Block estimation and concurrent RPC utilities for the Veris NAV system.

Optimizations:
  1. Pre-compute block numbers from a single reference (block, timestamp) pair
     instead of iterative binary search per target. Ethereum averages ~12s/block,
     so estimates are typically within ±2 blocks.
  2. Concurrent RPC queries via ThreadPoolExecutor. Alchemy growth plan allows
     ~330 req/s; we use configurable concurrency (default 20 workers) with
     optional rate limiting.

Usage:
    from block_utils import estimate_blocks, concurrent_query

    # Pre-compute blocks
    blocks = estimate_blocks(ref_block, ref_ts, target_timestamps)

    # Concurrent queries
    results = concurrent_query(query_fn, blocks, max_workers=20)
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed


# --- Block estimation (Option 1) ---

def _get_avg_block_time(chain: str) -> float:
    """Get average block time for a chain from chains.json config.

    Falls back to 12.0s (Ethereum default) if not configured.
    """
    from evm import load_chains
    chains = load_chains()
    chain_cfg = chains.get(chain, {})
    return chain_cfg.get("avg_block_time", 12.0)


def estimate_blocks(
    ref_block: int,
    ref_ts: int,
    target_timestamps: list[int],
    chain: str = "ethereum",
) -> list[int]:
    """Estimate block numbers for a list of unix timestamps.

    Uses linear extrapolation from a single known (block, timestamp) pair.
    Accuracy: typically within ±2 blocks for Ethereum (~24s error).

    Args:
        ref_block: Known block number.
        ref_ts: Unix timestamp of ref_block.
        target_timestamps: List of target unix timestamps.
        chain: Chain name (determines average block time from chains.json).

    Returns:
        List of estimated block numbers (same length as target_timestamps).
    """
    block_time = _get_avg_block_time(chain)
    return [
        max(1, ref_block + round((ts - ref_ts) / block_time))
        for ts in target_timestamps
    ]


def refine_block(w3, estimated_block: int, target_ts: int, tolerance: int = 30,
                 chain: str = "ethereum") -> int:
    """Refine a block estimate via binary search to be within tolerance of target.

    Uses the initial estimate to measure actual block rate, re-estimates if
    far off, then binary searches with tight bounds. Converges in ~20 RPC calls.

    Args:
        w3: Web3 instance.
        estimated_block: Initial estimate from estimate_blocks().
        target_ts: Target unix timestamp.
        tolerance: Acceptable seconds of deviation (default 30s).
        chain: Chain name (unused, kept for API compat).

    Returns:
        Refined block number (closest to but not exceeding target_ts).
    """
    latest = w3.eth.block_number
    est_block = min(estimated_block, latest)

    # Iteratively re-estimate using observed block rate until close enough
    # for binary search. Each iteration uses the previous check as a new
    # reference point, converging in 2-3 steps even on irregular chains.
    for _ in range(3):
        est_data = w3.eth.get_block(est_block)
        est_error = est_data["timestamp"] - target_ts
        if abs(est_error) <= tolerance:
            return est_block
        # Use observed rate between this block and latest to correct
        latest_ts = w3.eth.get_block(latest)["timestamp"]
        ts_span = latest_ts - est_data["timestamp"]
        block_span = latest - est_block
        if ts_span <= 0 or block_span <= 0:
            break
        observed_rate = ts_span / block_span
        est_block = max(1, min(est_block - int(est_error / observed_rate), latest))

    # Binary search with ±500 block margin around the corrected estimate
    low = max(1, est_block - 500)
    high = min(est_block + 500, latest)
    best = max(1, est_block)

    for _ in range(20):
        if low > high:
            break
        mid = (low + high) // 2
        mid_ts = w3.eth.get_block(mid)["timestamp"]

        if mid_ts <= target_ts:
            best = mid
            if target_ts - mid_ts <= tolerance:
                return best
            low = mid + 1
        else:
            high = mid - 1

    return best


# --- Concurrent RPC queries (Option 4) ---

def concurrent_query(
    query_fn,
    items: list,
    max_workers: int = 20,
    rate_limit_pause: float = 0.0,
    retry_on_429: bool = True,
    max_retries: int = 3,
) -> list:
    """Execute query_fn concurrently across items, preserving order.

    Args:
        query_fn: Callable that takes one item and returns a result.
                  Signature: query_fn(item) -> result
        items: List of inputs to query_fn.
        max_workers: Max concurrent threads (default 20, safe for Alchemy).
        rate_limit_pause: Optional pause between submitting batches (seconds).
        retry_on_429: Whether to retry on rate limit errors.
        max_retries: Max retries per item on 429 errors.

    Returns:
        List of results in the same order as items.
    """
    results = [None] * len(items)

    def _execute(index, item):
        for attempt in range(max_retries + 1):
            try:
                return index, query_fn(item)
            except Exception as e:
                if retry_on_429 and ("429" in str(e) or "rate" in str(e).lower()):
                    time.sleep(2 ** attempt)
                else:
                    raise
        raise RuntimeError(f"Max retries exceeded for item {index}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for i, item in enumerate(items):
            future = executor.submit(_execute, i, item)
            futures[future] = i
            if rate_limit_pause > 0 and (i + 1) % max_workers == 0:
                time.sleep(rate_limit_pause)

        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result

    return results


def concurrent_query_batched(
    query_fn,
    items: list,
    batch_size: int = 50,
    max_workers: int = 20,
    pause_between_batches: float = 0.5,
    progress_fn=None,
) -> list:
    """Execute queries in batches with progress reporting.

    Useful for large datasets (500+ items) where you want to avoid
    overwhelming the RPC provider and want progress updates.

    Args:
        query_fn: Callable that takes one item and returns a result.
        items: List of inputs.
        batch_size: Items per batch.
        max_workers: Concurrent workers within each batch.
        pause_between_batches: Sleep between batches (seconds).
        progress_fn: Optional callback(completed, total) for progress reporting.

    Returns:
        List of results in order.
    """
    results = [None] * len(items)
    total = len(items)

    for batch_start in range(0, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        batch_items = items[batch_start:batch_end]
        batch_indices = list(range(batch_start, batch_end))

        batch_results = concurrent_query(
            query_fn, batch_items, max_workers=max_workers
        )

        for i, result in zip(batch_indices, batch_results):
            results[i] = result

        if progress_fn:
            progress_fn(batch_end, total)

        if batch_end < total:
            time.sleep(pause_between_batches)

    return results
