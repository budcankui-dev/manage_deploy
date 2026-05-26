#!/usr/bin/env bash
# Build the node_agent image.
#
# Two modes:
#
#   1. Local build (default, single platform = host platform):
#        ./scripts/build_node_agent.sh
#      Produces: manage-deploy/node-agent:dev
#      WARNING on Apple Silicon / ARM64 hosts: this builds an arm64 image which
#      will not run on x86_64 compute nodes.
#
#   2. Cross-platform build for AMD64 compute nodes + push to private registry:
#        NODE_AGENT_IMAGE=10.112.244.94:5000/node-agent \
#        NODE_AGENT_TAG=dev \
#        NODE_AGENT_PUSH=1 \
#        NODE_AGENT_PLATFORM=linux/amd64 \
#        ./scripts/build_node_agent.sh
#
# Environment variables (mirrors build_workers.sh):
#   NODE_AGENT_IMAGE     Default: manage-deploy/node-agent.
#   NODE_AGENT_TAG       Default: dev.
#   NODE_AGENT_PLATFORM  Target platform passed to buildx. If unset, falls back
#                        to `docker build` on the host architecture.
#   NODE_AGENT_PUSH      If "1", push to registry (requires NODE_AGENT_PLATFORM).
#   NODE_AGENT_BUILDER   Buildx builder name. Default: manage-deploy-multiarch.
#   NODE_AGENT_NO_CACHE  If "1", pass --no-cache.
#   NODE_AGENT_INSECURE_REGISTRIES
#                        Comma-separated list of registries (host:port) marked
#                        as HTTP/insecure when creating the builder. Default:
#                        registry part of NODE_AGENT_IMAGE if it contains ":".
#
# The Dockerfile copies port_utils.py explicitly so the agent's preflight port
# checks work after deploy. If you add new Python modules to node_agent/, update
# the Dockerfile too.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CTX="${ROOT}/node_agent"
DOCKERFILE="${CTX}/Dockerfile"

IMAGE="${NODE_AGENT_IMAGE:-manage-deploy/node-agent}"
TAG="${NODE_AGENT_TAG:-dev}"
PLATFORM="${NODE_AGENT_PLATFORM:-}"
PUSH="${NODE_AGENT_PUSH:-0}"
BUILDER="${NODE_AGENT_BUILDER:-manage-deploy-multiarch}"
NO_CACHE_FLAG=""
if [[ "${NODE_AGENT_NO_CACHE:-0}" == "1" ]]; then
  NO_CACHE_FLAG="--no-cache"
fi

FULL_REF="${IMAGE}:${TAG}"

# Sanity check: port_utils.py must exist and the Dockerfile must copy it. If
# either is missing, the deployed agent will silently lose preflight port
# checks, so fail loudly here.
if [[ ! -f "${CTX}/port_utils.py" ]]; then
  echo "ERROR: ${CTX}/port_utils.py missing. node_agent preflight depends on it."
  exit 1
fi
if ! grep -q '^COPY port_utils\.py' "${DOCKERFILE}"; then
  echo "ERROR: ${DOCKERFILE} does not copy port_utils.py. Preflight port checks would be missing in the image."
  exit 1
fi
if [[ ! -f "${CTX}/runtime_resources.py" ]]; then
  echo "ERROR: ${CTX}/runtime_resources.py missing. docker_handler.start_container depends on it."
  exit 1
fi
if ! grep -q '^COPY runtime_resources\.py' "${DOCKERFILE}"; then
  echo "ERROR: ${DOCKERFILE} does not copy runtime_resources.py. Container start would fail with ModuleNotFoundError."
  exit 1
fi

INSECURE_REGISTRIES="${NODE_AGENT_INSECURE_REGISTRIES:-}"
if [[ -z "${INSECURE_REGISTRIES}" ]]; then
  reg_candidate="${IMAGE%%/*}"
  if [[ "${reg_candidate}" == *":"* ]]; then
    INSECURE_REGISTRIES="${reg_candidate}"
  fi
fi

ensure_buildx_builder() {
  if ! docker buildx inspect "${BUILDER}" >/dev/null 2>&1; then
    echo "==> creating buildx builder ${BUILDER}"
    if [[ -n "${INSECURE_REGISTRIES}" ]]; then
      local cfg
      cfg="$(mktemp -t buildkitd.XXXXXX.toml)"
      {
        local r
        IFS=',' read -ra _regs <<<"${INSECURE_REGISTRIES}"
        for r in "${_regs[@]}"; do
          printf '[registry."%s"]\n  http = true\n  insecure = true\n\n' "${r}"
        done
      } >"${cfg}"
      echo "    insecure registries: ${INSECURE_REGISTRIES}"
      docker buildx create --name "${BUILDER}" --driver docker-container --config "${cfg}" --use >/dev/null
    else
      docker buildx create --name "${BUILDER}" --driver docker-container --use >/dev/null
    fi
  else
    docker buildx use "${BUILDER}" >/dev/null
  fi
  docker buildx inspect --bootstrap >/dev/null
}

if [[ -n "${PLATFORM}" ]]; then
  if ! docker buildx version >/dev/null 2>&1; then
    echo "ERROR: NODE_AGENT_PLATFORM=${PLATFORM} requires docker buildx."
    exit 1
  fi

  ensure_buildx_builder

  BUILDX_ARGS=(
    buildx build
    -f "${DOCKERFILE}"
    --platform "${PLATFORM}"
    -t "${FULL_REF}"
  )
  if [[ -n "${NO_CACHE_FLAG}" ]]; then
    BUILDX_ARGS+=("${NO_CACHE_FLAG}")
  fi

  if [[ "${PUSH}" == "1" ]]; then
    BUILDX_ARGS+=(--push)
    echo "==> buildx build + push ${FULL_REF} for ${PLATFORM}"
  else
    if [[ "${PLATFORM}" != *","* ]]; then
      BUILDX_ARGS+=(--load)
      echo "==> buildx build + load ${FULL_REF} for ${PLATFORM} (no push)"
    else
      echo "==> buildx build ${FULL_REF} for ${PLATFORM} (multi-arch, no load)"
    fi
  fi
  BUILDX_ARGS+=("${CTX}")

  docker "${BUILDX_ARGS[@]}"
else
  if [[ "${PUSH}" == "1" ]]; then
    echo "ERROR: NODE_AGENT_PUSH=1 requires NODE_AGENT_PLATFORM."
    exit 1
  fi
  echo "==> docker build ${FULL_REF} (host platform)"
  docker build ${NO_CACHE_FLAG} -f "${DOCKERFILE}" -t "${FULL_REF}" "${CTX}"
fi

echo
echo "Done. Image: ${FULL_REF}"
if [[ -n "${PLATFORM}" ]]; then
  echo "Built for: ${PLATFORM}"
fi
if [[ "${PUSH}" == "1" ]]; then
  echo "Pushed. Verify with: docker manifest inspect ${FULL_REF}"
fi
