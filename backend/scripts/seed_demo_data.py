#!/usr/bin/env python3
"""Compatibility wrapper for the old demo setup command.

Prefer backend/scripts/setup_matmul_demo.py for new docs and scripts.
"""

from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from scripts.setup_matmul_demo import main, seed, setup_demo  # noqa: E402,F401


if __name__ == "__main__":
    main()
