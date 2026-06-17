#!/usr/bin/env python3
"""User-controlled receiver for matmul callback demos."""

from __future__ import annotations

import sys
from pathlib import Path

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.receiver_server import main


if __name__ == "__main__":
    raise SystemExit(main("high_throughput_matmul"))

