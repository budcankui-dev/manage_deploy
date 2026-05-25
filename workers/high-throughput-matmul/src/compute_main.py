#!/usr/bin/env python3
"""Matmul pipeline compute: run GEMM and write result.json."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from matmul_core import run_matmul

SCRATCH = Path("/scratch")
JOB_FILE = SCRATCH / "job.json"
RESULT_FILE = SCRATCH / "result.json"


def _wait_for_job(timeout_sec: int = 120) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if JOB_FILE.is_file():
            return json.loads(JOB_FILE.read_text(encoding="utf-8"))
        time.sleep(0.5)
    raise TimeoutError(f"job.json not found under {SCRATCH}")


def main() -> int:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    job = _wait_for_job()
    latency_ms, checksum = run_matmul(
        int(job["matrix_size"]),
        int(job["batch_count"]),
        int(job["seed"]),
    )
    result = {
        "compute_latency_ms": latency_ms,
        "checksum": checksum,
        "matrix_size": job["matrix_size"],
        "batch_count": job["batch_count"],
    }
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"COMPUTE_DONE latency_ms={latency_ms:.2f} checksum={checksum}", flush=True)
    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"COMPUTE_FAILED {exc}", flush=True)
        sys.exit(1)
