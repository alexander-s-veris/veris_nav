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

AVG_BLOCK_TIME = {
    "ethereum": 12.0,
    "arbitrum": 0.25,
    "base": 2.0,
    "avalanche": 2.0,
    "plasma": 2.0,
    "hyperevm": 2.0,
}


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
        chain: Chain name (determines average block time).

    Returns:
        List of estimated block numbers (same length as target_timestamps).
    """
    block_time = AVG_BLOCK_TIME.get(chain, 12.0)
    return [
        max(1, ref_block + round((ts - ref_ts) / block_time))
        for ts in target_timestamps
    ]


def refine_block(w3, estimated_block: int, target_ts: int, tolerance: int = 15) -> int:
    """Refine a single block estimate to be within tolerance of target timestamp.

    Only needed when exact block alignment matters (e.g. Valuation Block).
    For hourly monitoring data, the raw estimate is sufficient.

    Args:
        w3: Web3 instance.
        estimated_block: Initial estimate.
        target_ts: Target unix timestamp.
        tolerance: Acceptable seconds of deviation.

    Returns:
        Refined block number.
    """
    latest = w3.eth.block_number
    est = max(1, min(estimated_block, latest))

    for _ in range(5):
        bd = w3.eth.get_block(est)
        diff = target_ts - bd["timestamp"]
        if abs(diff) <= tolerance:
            return est
        adj = round(diff / 12)
        if adj == 0:
            adj = 1 if diff > 0 else -1
        est = max(1, min(est + adj, latest))

    return est


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
