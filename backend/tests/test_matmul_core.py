from pathlib import Path
import sys

import pytest

pytest.importorskip("numpy")

WORKERS_SRC = Path(__file__).resolve().parents[2] / "workers" / "high-throughput-matmul" / "src"
WORKERS_ROOT = Path(__file__).resolve().parents[2] / "workers"
sys.path.insert(0, str(WORKERS_ROOT))
sys.path.insert(0, str(WORKERS_SRC))

from matmul_core import run_matmul  # noqa: E402
from compute_main import _run_observation_window  # noqa: E402


def test_run_matmul_returns_positive_latency():
    result = run_matmul(64, 1, 7)
    assert result["elapsed_ms"] > 0
    assert result["effective_gflops"] > 0
    assert result["checksum"]


def test_matmul_observation_window_returns_samples():
    result = _run_observation_window(
        {
            "matrix_size": 16,
            "sample_batch_count": 1,
            "seed": 7,
            "observation_duration_sec": 0.02,
            "sample_interval_sec": 0,
            "warmup_batches": 1,
            "min_samples": 2,
            "max_samples": 3,
        }
    )

    assert result["aggregation"] == "median_after_warmup"
    assert result["sample_count"] >= 2
    assert len(result["samples"]) == result["sample_count"]
    assert result["effective_gflops"] > 0
