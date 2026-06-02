"""Batched matrix multiply — GPU (CuPy) or CPU (NumPy) via USE_GPU env."""

from __future__ import annotations

import os
import time

USE_GPU = os.environ.get("USE_GPU", "false").lower() in ("true", "1", "yes")

if USE_GPU:
    import cupy as xp
    xp.cuda.Stream.null.synchronize()
else:
    import numpy as xp


def run_matmul(matrix_size: int, batch_count: int, seed: int) -> dict:
    """Run batched matmul and return performance metrics."""
    rng = xp.random.default_rng(seed)
    actual_batches = max(1, batch_count)

    if USE_GPU:
        xp.cuda.Stream.null.synchronize()

    t0 = time.perf_counter()
    last = None
    for _ in range(actual_batches):
        a = rng.standard_normal((matrix_size, matrix_size), dtype=xp.float32)
        b = rng.standard_normal((matrix_size, matrix_size), dtype=xp.float32)
        last = a @ b

    if USE_GPU:
        xp.cuda.Stream.null.synchronize()

    elapsed_s = time.perf_counter() - t0
    elapsed_ms = elapsed_s * 1000.0
    total_flops = 2.0 * (matrix_size ** 3) * actual_batches
    effective_gflops = total_flops / elapsed_s / 1e9 if elapsed_s > 0 else 0.0

    if last is not None:
        val = float(last.flat[0]) if not USE_GPU else float(last.get().flat[0])
        checksum = f"{val:.6f}"
    else:
        checksum = "0"

    return {
        "elapsed_ms": elapsed_ms,
        "effective_gflops": effective_gflops,
        "checksum": checksum,
        "backend": "cupy_gpu" if USE_GPU else "numpy_cpu",
    }
