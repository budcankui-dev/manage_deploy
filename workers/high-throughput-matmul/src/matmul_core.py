"""CPU batched matrix multiply for demo / acceptance."""

from __future__ import annotations

import time

import numpy as np


def run_matmul(matrix_size: int, batch_count: int, seed: int) -> tuple[float, str]:
    rng = np.random.default_rng(seed)
    t0 = time.perf_counter()
    last = None
    for _ in range(max(1, batch_count)):
        a = rng.standard_normal((matrix_size, matrix_size), dtype=np.float32)
        b = rng.standard_normal((matrix_size, matrix_size), dtype=np.float32)
        last = a @ b
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    checksum = f"{float(last.flat[0]):.6f}" if last is not None else "0"
    return elapsed_ms, checksum
