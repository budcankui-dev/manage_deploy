from pathlib import Path
import sys

import pytest

pytest.importorskip("numpy")

WORKERS_SRC = Path(__file__).resolve().parents[2] / "workers" / "high-throughput-matmul" / "src"
sys.path.insert(0, str(WORKERS_SRC))

from matmul_core import run_matmul  # noqa: E402


def test_run_matmul_returns_positive_latency():
    result = run_matmul(64, 1, 7)
    assert result["elapsed_ms"] > 0
    assert result["effective_gflops"] > 0
    assert result["checksum"]
