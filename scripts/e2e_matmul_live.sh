#!/usr/bin/env bash
# Live E2E: prepare scientific matmul demo -> business-task -> start -> wait evaluation
#
# Local mode (default, single host):
#   ./scripts/e2e_matmul_live.sh
#
# Remote mode (3 physically isolated compute nodes):
#   E2E_REMOTE=1 \
#   WORKER_IMAGE=<registry-host:port>/scientific-matmul \
#   WORKER_TAG=dev \
#   NODE_AGENT_IMAGE=<registry-host:port>/node-agent \
#   NODE_AGENT_TAG=dev \
#   E2E_REMOTE_NODES="manage-compute-1 manage-compute-2 manage-compute-3" \
#   E2E_NODE_AGENT_HOSTS="<ip1> <ip2> <ip3>" \
#   ./scripts/e2e_matmul_live.sh
#
# Placement: source -> compute-1, compute -> compute-2, sink -> compute-3.
# Each role runs on a different physical host; the data path source->compute
# and compute->sink crosses physical machines, exercising the random-walk
# routing decision end to end.
#
# Both WORKER_IMAGE and NODE_AGENT_IMAGE are required in remote mode and
# must be registry-qualified so the remote nodes can pull them.
#
# In remote mode the script verifies, before creating the business task:
#   - WORKER_IMAGE:WORKER_TAG exists in the configured registry and has a
#     linux/amd64 entry (docker manifest inspect)
#   - NODE_AGENT_IMAGE:NODE_AGENT_TAG likewise has a linux/amd64 manifest
#     and is pullable on every remote node
#   - every host in E2E_REMOTE_NODES can `docker pull` the worker image, the
#     pulled image is amd64, and it can `docker run` without hitting exec
#     format error
#   - every host:port in E2E_NODE_AGENT_HOSTS answers /health
#
# WORKER_SKIP_BUILD=1 is only honored after the image already passed the remote
# preflight (manifest + pull + arch + node_agent health). If any preflight
# check fails the script aborts before creating any business task.
#
# E2E_SKIP_IMAGE_PRECHECK=1 fully skips the manifest / pull / arch / node_agent
# health preflight. Use only for fast local iteration when you already know the
# images and remote daemons are good. Production / CI runs MUST leave this
# unset so the script can fail fast on registry or registry-config drift.
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
WORKER_IMAGE="${WORKER_IMAGE:-manage-deploy/scientific-matmul}"
WORKER_TAG="${WORKER_TAG:-dev}"
MATRIX_SIZE="${MATMUL_MATRIX_SIZE:-64}"
BATCH_COUNT="${MATMUL_BATCH_COUNT:-1}"
export WORKER_IMAGE WORKER_TAG

E2E_REMOTE="${E2E_REMOTE:-0}"
E2E_REMOTE_NODES="${E2E_REMOTE_NODES:-}"
E2E_NODE_AGENT_HOSTS="${E2E_NODE_AGENT_HOSTS:-}"
NODE_AGENT_PORT="${NODE_AGENT_PORT:-8001}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=5}"
E2E_SKIP_IMAGE_PRECHECK="${E2E_SKIP_IMAGE_PRECHECK:-0}"

# Optional node_agent image used by the preflight. Defaults to empty (the
# remote preflight will then refuse to run because it has no agent image to
# verify; set NODE_AGENT_IMAGE to a registry-qualified reference to enable
# the agent-image preflight). For local-only mode (E2E_REMOTE!=1) the value
# is unused and may stay empty.
NODE_AGENT_IMAGE="${NODE_AGENT_IMAGE:-}"
NODE_AGENT_TAG="${NODE_AGENT_TAG:-dev}"

FULL_IMAGE="${WORKER_IMAGE}:${WORKER_TAG}"
if [[ -n "${NODE_AGENT_IMAGE}" ]]; then
  FULL_NODE_AGENT_IMAGE="${NODE_AGENT_IMAGE}:${NODE_AGENT_TAG}"
else
  FULL_NODE_AGENT_IMAGE=""
fi

require_http() {
  local name="$1" url="$2"
  if ! curl -sS -o /dev/null --max-time 5 -w '' "${url}"; then
    echo "ERROR: ${name} not reachable at ${url}"
    exit 1
  fi
}

# Decide whether an image reference needs `--insecure` for manifest inspect.
# Heuristic: host:port references are assumed plain HTTP unless WORKER_REGISTRY_INSECURE=0.
manifest_insecure_flag() {
  local image="$1"
  local registry_host="${image%%/*}"
  if [[ "${registry_host}" == *":"* ]]; then
    if [[ "${WORKER_REGISTRY_INSECURE:-1}" == "1" ]]; then
      echo "--insecure"
      return
    fi
  fi
  echo ""
}

# Verify that an image reference is registry-qualified (host:port/repo) so the
# remote nodes can actually pull it.
require_registry_qualified() {
  local image="$1" var_name="$2"
  if [[ "${image}" != *":"*"/"* && "${image}" != *"/"*"/"* && "${image}" != *":5000/"* ]]; then
    case "${image}" in
      */*) : ;; # docker hub-style ok
      *)
        echo "ERROR: ${var_name}=${image} is not registry-qualified; compute nodes cannot pull it."
        exit 1
        ;;
    esac
  fi
}

# Verify a single image: manifest exists, lists linux/amd64, every remote node
# can pull it, and the pulled image reports amd64.
verify_image_on_nodes() {
  local image_ref="$1" label="$2"
  local manifest_flags
  manifest_flags=$(manifest_insecure_flag "${image_ref}")
  echo "  - docker manifest inspect ${manifest_flags} ${image_ref}"
  local manifest
  if ! manifest=$(docker manifest inspect ${manifest_flags} "${image_ref}" 2>&1); then
    echo "ERROR: docker manifest inspect failed for ${label} ${image_ref}:"
    echo "${manifest}"
    exit 1
  fi
  if ! echo "${manifest}" | grep -q '"architecture": "amd64"'; then
    echo "ERROR: ${image_ref} manifest has no linux/amd64 entry:"
    echo "${manifest}"
    exit 1
  fi
  echo "    manifest contains linux/amd64"

  local node arch
  for node in ${E2E_REMOTE_NODES}; do
    echo "  - ${node}: docker pull ${image_ref}"
    if ! ssh ${SSH_OPTS} "${node}" "docker pull ${image_ref}" >/dev/null 2>&1; then
      echo "ERROR: ${node} failed to pull ${image_ref}."
      echo "  Check that the host has the registry configured as insecure-registries if it's HTTP."
      ssh ${SSH_OPTS} "${node}" "docker pull ${image_ref}" || true
      exit 1
    fi
    arch=$(ssh ${SSH_OPTS} "${node}" "docker inspect ${image_ref} --format '{{.Architecture}}/{{.Os}}'" 2>/dev/null || echo "")
    if [[ "${arch}" != "amd64/linux" ]]; then
      echo "ERROR: ${node} pulled ${image_ref} but architecture=${arch} (expected amd64/linux)."
      exit 1
    fi
    echo "    arch=${arch}"
  done
}

remote_preflight() {
  if [[ "${E2E_SKIP_IMAGE_PRECHECK}" == "1" ]]; then
    echo "==> remote preflight skipped (E2E_SKIP_IMAGE_PRECHECK=1)"
    return 0
  fi

  if [[ -z "${NODE_AGENT_IMAGE}" ]]; then
    echo "ERROR: NODE_AGENT_IMAGE must be set when running remote precheck."
    echo "  Provide a registry-qualified reference, e.g."
    echo "    NODE_AGENT_IMAGE=<registry-host:port>/node-agent NODE_AGENT_TAG=<tag>"
    exit 1
  fi

  echo "==> remote preflight for worker=${FULL_IMAGE} node_agent=${FULL_NODE_AGENT_IMAGE}"

  require_registry_qualified "${WORKER_IMAGE}" "WORKER_IMAGE"
  require_registry_qualified "${NODE_AGENT_IMAGE}" "NODE_AGENT_IMAGE"

  if [[ -z "${E2E_REMOTE_NODES}" ]]; then
    echo "ERROR: E2E_REMOTE=1 but E2E_REMOTE_NODES is empty."
    exit 1
  fi

  # 1. Worker image: manifest + pull + arch on each node + smoke run.
  verify_image_on_nodes "${FULL_IMAGE}" "worker"
  local node ran
  for node in ${E2E_REMOTE_NODES}; do
    # Smoke run: invoke `python -c "print('ok')"` inside the worker image. This
    # proves the binary actually executes on this host (no exec format error)
    # without depending on the matmul source code or networking.
    echo "  - ${node}: docker run --rm ${FULL_IMAGE} python -c 'print(\"ok\")'"
    ran=$(ssh ${SSH_OPTS} "${node}" "docker run --rm --entrypoint python ${FULL_IMAGE} -c 'print(\"ok\")'" 2>&1 || true)
    if [[ "${ran}" != *"ok"* ]]; then
      echo "ERROR: ${node} could not run a noop container from ${FULL_IMAGE}:"
      echo "${ran}"
      exit 1
    fi
    echo "    noop run succeeded"
  done

  # 2. Node-agent image: manifest + pull + arch on each node. The image is
  # required to be registry-qualified (checked above), so we always verify it.
  verify_image_on_nodes "${FULL_NODE_AGENT_IMAGE}" "node_agent"

  # 3. Each node_agent /health is reachable on the REAL node hosts.
  if [[ -z "${E2E_NODE_AGENT_HOSTS}" ]]; then
    echo "ERROR: E2E_REMOTE=1 but E2E_NODE_AGENT_HOSTS is empty."
    exit 1
  fi
  local host url status
  for host in ${E2E_NODE_AGENT_HOSTS}; do
    url="http://${host}:${NODE_AGENT_PORT}/health"
    echo "  - node_agent ${url}"
    status=$(curl -s -o /dev/null --max-time 5 -w '%{http_code}' "${url}" 2>/dev/null || true)
    status="${status:-000}"
    if [[ "${status}" != "200" ]]; then
      echo "ERROR: node_agent /health not reachable at ${url} (http_code=${status})"
      echo "  Hint: check that the node_agent container is running on host ${host}:${NODE_AGENT_PORT}."
      exit 1
    fi
  done

  echo "==> remote preflight OK"
}

echo "[0/7] prerequisites"
require_http "backend" "${BASE_URL}/docs"

if [[ "${E2E_REMOTE}" == "1" ]]; then
  # Skip the local node_agent check; it isn't representative of remote health.
  echo "  (remote mode: skipping local 127.0.0.1:8001 node agent check)"
else
  require_http "node agent" "http://127.0.0.1:${NODE_AGENT_PORT}/health"
fi

echo "[1/7] build worker images (skip if WORKER_SKIP_BUILD=1)"
if [[ "${WORKER_SKIP_BUILD:-0}" != "1" ]]; then
  if [[ "${E2E_REMOTE}" == "1" ]]; then
    # In remote mode, require an explicit registry-qualified WORKER_IMAGE and
    # cross-build for amd64.
    : "${WORKER_PLATFORM:=linux/amd64}"
    : "${WORKER_PUSH:=1}"
    export WORKER_PLATFORM WORKER_PUSH
  fi
  "$(dirname "$0")/build_workers.sh"
else
  echo "  WORKER_SKIP_BUILD=1: skipping build (will validate via remote preflight)"
fi

if [[ "${E2E_REMOTE}" == "1" ]]; then
  remote_preflight
fi

echo "[2/7] create business task (using real node hostnames)"
TASK_ID="matmul-live-$(date +%s)"
echo "[3/7] create business task ${TASK_ID} (matrix=${MATRIX_SIZE}, batch=${BATCH_COUNT})"
CREATE_BODY=$(cat <<EOF
{
  "external_task_id": "${TASK_ID}",
  "task_type": "high_throughput_matmul",
  "modality": "高通量计算模态",
  "name": "Scientific Matmul Live E2E",
  "data_profile": {
    "profile_id": "matmul_dev",
    "matrix_size": ${MATRIX_SIZE},
    "batch_count": ${BATCH_COUNT},
    "seed": 42
  },
  "business_objective": {
    "metric_key": "compute_latency_ms",
    "operator": "<=",
    "target_value": 60000,
    "unit": "ms"
  },
  "runtime_plan": {
    "algorithm": "batched_matmul",
    "precision": "fp32",
    "use_gpu": false
  },
  "routing_result": {
    "strategy": "fastest_completion",
    "placements": [
      {"task_node_id": "source", "topology_node_id": "compute-1"},
      {"task_node_id": "compute", "topology_node_id": "compute-2", "gpu_device": "0"},
      {"task_node_id": "sink", "topology_node_id": "compute-3"}
    ],
    "estimated_metric": {
      "metric_key": "compute_latency_ms",
      "metric_value": 5000,
      "unit": "ms"
    }
  },
  "auto_start": false
}
EOF
)

CREATE_RESP=$(curl -sS --max-time 120 -X POST "${BASE_URL}/api/business-tasks" \
  -H 'Content-Type: application/json' \
  -d "${CREATE_BODY}")
INSTANCE_ID=$(echo "${CREATE_RESP}" | python3 -c "import sys,json; print(json.load(sys.stdin)['instance_id'])")
echo "instance_id=${INSTANCE_ID}"

echo "[4/7] start instance (DAG + health, up to 600s)"
curl -sS --max-time 600 -X POST "${BASE_URL}/api/instances/${INSTANCE_ID}/start" \
  -H 'Content-Type: application/json' > /dev/null || true

echo "[5/7] wait for instance running or failed (up to 300s)"
STATUS=""
for _ in $(seq 1 60); do
  INST_JSON=$(curl -sS "${BASE_URL}/api/instances/${INSTANCE_ID}")
  STATUS=$(echo "${INST_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  echo "  status=${STATUS}"
  if [[ "${STATUS}" == "running" ]]; then
    break
  fi
  if [[ "${STATUS}" == "failed" ]]; then
    echo "${INST_JSON}" | python3 -m json.tool
    exit 1
  fi
  sleep 5
done
if [[ "${STATUS}" != "running" ]]; then
  echo "ERROR: instance did not reach running (status=${STATUS})"
  curl -sS "${BASE_URL}/api/instances/${INSTANCE_ID}" | python3 -m json.tool
  exit 1
fi

echo "[6/7] wait for business evaluation (up to 120s)"
EVAL=""
for _ in $(seq 1 24); do
  EVAL=$(curl -sS "${BASE_URL}/api/business-tasks/${INSTANCE_ID}/evaluation" || true)
  if echo "${EVAL}" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('metric_key') else 1)" 2>/dev/null; then
    echo "${EVAL}" | python3 -m json.tool
    break
  fi
  sleep 5
done

echo "[7/7] assert business_success"
EVAL_JSON=$(curl -sS "${BASE_URL}/api/business-tasks/${INSTANCE_ID}/evaluation")
echo "${EVAL_JSON}" | python3 -m json.tool
SUCCESS=$(echo "${EVAL_JSON}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('business_success', False))" 2>/dev/null || echo "False")
if [[ "${SUCCESS}" != "True" && "${SUCCESS}" != "true" ]]; then
  echo "business_success=${SUCCESS} (expected true); instance_status=${STATUS}"
  curl -sS "${BASE_URL}/api/instances/${INSTANCE_ID}" | python3 -m json.tool
  exit 1
fi

if [[ "${E2E_DELETE_INSTANCE:-0}" == "1" ]]; then
  echo "[cleanup] delete instance ${INSTANCE_ID}"
  curl -sS -X DELETE "${BASE_URL}/api/instances/${INSTANCE_ID}" > /dev/null || true
fi

echo "[done] summary"
curl -sS "${BASE_URL}/api/business-tasks/summary" | python3 -m json.tool
echo "OK matmul live e2e passed (instance_id=${INSTANCE_ID})"
