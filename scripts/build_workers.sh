#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${WORKER_TAG:-dev}"
CTX="${ROOT}/workers"

build_one() {
  local target="$1"
  local image="$2"
  echo "==> building ${image}:${TAG} (target=${target})"
  docker build -f "${CTX}/high-throughput-matmul/Dockerfile" \
    --target "${target}" \
    -t "${image}:${TAG}" \
    "${CTX}"
}

build_one source manage-deploy/matmul-source
build_one compute manage-deploy/matmul-compute
build_one sink manage-deploy/matmul-sink

echo "Done. Images:"
echo "  manage-deploy/matmul-source:${TAG}"
echo "  manage-deploy/matmul-compute:${TAG}"
echo "  manage-deploy/matmul-sink:${TAG}"
