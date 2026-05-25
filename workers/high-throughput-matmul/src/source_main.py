#!/usr/bin/env python3
"""Matmul pipeline source: validate profile and write job.json."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

SCRATCH = Path("/scratch")
JOB_FILE = SCRATCH / "job.json"


def _parse_json_env(name: str, default: dict | None = None) -> dict:
    raw = os.environ.get(name, "")
    if not raw:
        return default or {}
    return json.loads(raw)


def main() -> int:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    profile = _parse_json_env("DATA_PROFILE")
    matrix_size = int(profile.get("matrix_size") or 512)
    batch_count = int(profile.get("batch_count") or 4)
    seed = int(profile.get("seed") or 42)

    job = {
        "matrix_size": matrix_size,
        "batch_count": batch_count,
        "seed": seed,
        "profile_id": profile.get("profile_id", "matmul_dev"),
    }
    JOB_FILE.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    print(f"SOURCE_READY job={job}", flush=True)
    # 保持 running 直至 DAG 下游启动
    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
