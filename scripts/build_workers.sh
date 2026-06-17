#!/usr/bin/env bash
# Build worker images.
#
# Two modes:
#
#   1. Local build (default, single platform = host platform):
#        ./scripts/build_workers.sh
#      Produces: manage-deploy/scientific-matmul:dev (or $WORKER_IMAGE:$WORKER_TAG)
#      WARNING on Apple Silicon / ARM64 hosts: this builds an arm64 image which
#      will fail with "exec format error" on x86_64 compute nodes. For remote
#      testing always use WORKER_PLATFORM=linux/amd64.
#
#   2. Cross-platform build for remote AMD64 compute nodes + push to a private
#      registry (preferred for the test-lab):
#        WORKER_IMAGE=10.112.244.94:5000/scientific-matmul \
#        WORKER_TAG=dev \
#        WORKER_PUSH=1 \
#        WORKER_PLATFORM=linux/amd64 \
#        ./scripts/build_workers.sh
#
# Environment variables:
#   WORKER_IMAGE     Full image repo name. Default: manage-deploy/scientific-matmul.
#                    Set to e.g. 10.112.244.94:5000/scientific-matmul when pushing
#                    to the test-lab private registry.
#   WORKER_KIND      Worker type. Default: matmul.
#                    Supported: matmul, video, matmul-endpoint, video-endpoint.
#                    Endpoint images are lightweight source/sink/receiver images
#                    used by automated benchmark endpoints and manual user demos.
#   WORKER_TAG       Image tag. Default: dev.
#   WORKER_PLATFORM  Target platform passed to buildx (e.g. linux/amd64,
#                    linux/arm64, or linux/amd64,linux/arm64 for multi-arch).
#                    If unset, falls back to a single-platform `docker build`
#                    using the host architecture.
#   WORKER_PUSH      If "1", push the image to the registry after building.
#                    Requires WORKER_PLATFORM (buildx is used).
#   WORKER_BUILDER   Optional buildx builder name. Auto-created if missing.
#                    Default: manage-deploy-multiarch.
#   WORKER_NO_CACHE  If "1", pass --no-cache to the build.
#   WORKER_INSECURE_REGISTRIES
#                    Comma-separated list of registries (host:port) to mark as
#                    HTTP/insecure when (re)creating the buildx builder. The
#                    builder is recreated only if it does not yet exist; to
#                    apply a changed list, `docker buildx rm $WORKER_BUILDER`
#                    first. Default: the registry part of WORKER_IMAGE if it
#                    contains ":" before the first "/" (e.g. 10.112.244.94:5000).
#
# Notes:
#   - When WORKER_PLATFORM is set the script uses `docker buildx build`. buildx
#     must be available locally (`docker buildx version`).
#   - The docker-container buildx driver does NOT inherit the host daemon's
#     insecure-registries setting. To push to plain-HTTP registries like
#     10.112.244.94:5000 the builder must be created with a buildkitd.toml that
#     marks them http+insecure. This script handles that automatically.
#   - When WORKER_PUSH=1 the image is sent straight to the registry; the local
#     daemon does not retain a usable copy for arm64+amd64 multi-arch manifests
#     (this is a buildx constraint). Verify with `docker manifest inspect`.
#   - When WORKER_PUSH is unset on a cross-build the image stays in the build
#     cache only; use --load (single platform) or push manually for use.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CTX="${ROOT}/workers"
KIND="${WORKER_KIND:-matmul}"
case "${KIND}" in
  matmul)
    DOCKERFILE="${CTX}/high-throughput-matmul/Dockerfile"
    DEFAULT_IMAGE="manage-deploy/scientific-matmul"
    ;;
  matmul-endpoint)
    DOCKERFILE="${CTX}/high-throughput-matmul/Dockerfile.endpoint"
    DEFAULT_IMAGE="manage-deploy/scientific-matmul-endpoint"
    ;;
  video)
    DOCKERFILE="${CTX}/low-latency-video/Dockerfile"
    DEFAULT_IMAGE="manage-deploy/low-latency-video"
    ;;
  video-endpoint)
    DOCKERFILE="${CTX}/low-latency-video/Dockerfile.endpoint"
    DEFAULT_IMAGE="manage-deploy/low-latency-video-endpoint"
    ;;
  *)
    echo "ERROR: unsupported WORKER_KIND=${KIND}; expected matmul, video, matmul-endpoint, or video-endpoint." >&2
    exit 1
    ;;
esac

IMAGE="${WORKER_IMAGE:-${DEFAULT_IMAGE}}"
TAG="${WORKER_TAG:-dev}"
PLATFORM="${WORKER_PLATFORM:-}"
PUSH="${WORKER_PUSH:-0}"
BUILDER="${WORKER_BUILDER:-manage-deploy-multiarch}"
NO_CACHE_FLAG=""
if [[ "${WORKER_NO_CACHE:-0}" == "1" ]]; then
  NO_CACHE_FLAG="--no-cache"
fi

FULL_REF="${IMAGE}:${TAG}"

# Auto-detect the registry from WORKER_IMAGE if WORKER_INSECURE_REGISTRIES not set.
INSECURE_REGISTRIES="${WORKER_INSECURE_REGISTRIES:-}"
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
    echo "ERROR: WORKER_PLATFORM=${PLATFORM} requires docker buildx, but 'docker buildx version' failed."
    echo "Install Docker Buildx or unset WORKER_PLATFORM to fall back to a single-platform build."
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
    # --load only works for a single platform; allow it as a convenience for
    # local cross-platform builds where the caller wants the image in their
    # local daemon (e.g. PLATFORM=linux/amd64 from an arm64 host).
    if [[ "${PLATFORM}" != *","* ]]; then
      BUILDX_ARGS+=(--load)
      echo "==> buildx build + load ${FULL_REF} for ${PLATFORM} (no push)"
    else
      echo "==> buildx build ${FULL_REF} for ${PLATFORM} (multi-arch, build cache only)"
      echo "    NOTE: image is NOT loaded into the local daemon. Re-run with WORKER_PUSH=1 to push,"
      echo "          or build a single platform to use --load."
    fi
  fi
  BUILDX_ARGS+=("${CTX}")

  docker "${BUILDX_ARGS[@]}"
else
  if [[ "${PUSH}" == "1" ]]; then
    echo "ERROR: WORKER_PUSH=1 requires WORKER_PLATFORM (use buildx)."
    echo "Example: WORKER_IMAGE=10.112.244.94:5000/scientific-matmul WORKER_TAG=dev \\"
    echo "         WORKER_PLATFORM=linux/amd64 WORKER_PUSH=1 ./scripts/build_workers.sh"
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
  echo "Pushed to registry. Verify with:"
  echo "  docker manifest inspect ${FULL_REF}"
fi
