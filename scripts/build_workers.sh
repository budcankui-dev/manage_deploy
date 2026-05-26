#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${WORKER_TAG:-dev}"
CTX="${ROOT}/workers"
IMAGE="manage-deploy/scientific-matmul"

echo "==> building ${IMAGE}:${TAG}"
docker build -f "${CTX}/high-throughput-matmul/Dockerfile" \
  -t "${IMAGE}:${TAG}" \
  "${CTX}"

echo "Done. Images:"
echo "  ${IMAGE}:${TAG}"
