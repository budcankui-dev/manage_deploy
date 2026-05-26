#!/usr/bin/env bash
set -euo pipefail

# Compatibility entrypoint: the only maintained demo business is the scientific matmul flow.
"$(dirname "$0")/e2e_matmul_live.sh"
