"""CPU batched matrix multiply for demo / acceptance."""

from __future__ import annotations

import time

import numpy as np


def run_matmul(matrix_size: int, batch_count: int, seed: int) -> dict:
    """Run batched matmul and return performance metrics.

    Returns dict with elapsed_ms, effective_gflops, and checksum.
    """
    rng = np.random.default_rng(seed)
    actual_batches = max(1, batch_count)
    t0 = time.perf_counter()
    last = None
    for _ in range(actual_batches):
        a = rng.standard_normal((matrix_size, matrix_size), dtype=np.float32)
        b = rng.standard_normal((matrix_size, matrix_size), dtype=np.float32)
        last = a @ b
    elapsed_s = time.perf_counter() - t0
    elapsed_ms = elapsed_s * 1000.0
    # FLOPS for matrix multiply: 2 * N^3 per batch (multiply + accumulate)
    total_flops = 2.0 * (matrix_size ** 3) * actual_batches
    effective_gflops = total_flops / elapsed_s / 1e9 if elapsed_s > 0 else 0.0
    checksum = f"{float(last.flat[0]):.6f}" if last is not None else "0"
    return {
        "elapsed_ms": elapsed_ms,
        "effective_gflops": effective_gflops,
        "checksum": checksum,
    }
