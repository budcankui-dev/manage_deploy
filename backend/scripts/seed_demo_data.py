#!/usr/bin/env python3
"""Compatibility wrapper for the old demo setup command.

The legacy entry points `seed_demo_data.py` and `setup_matmul_demo.py` have
been retired. The active entry point is
``backend/scripts/rebuild_matmul_template.py``; this wrapper delegates to it
so existing automation that still calls ``seed_demo_data.py`` keeps working.
"""

from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from scripts.rebuild_matmul_template import main  # noqa: E402,F401


if __name__ == "__main__":
    main()
