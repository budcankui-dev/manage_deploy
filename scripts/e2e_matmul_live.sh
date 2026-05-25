#!/usr/bin/env bash
# Live E2E: seed -> business-task (matmul) -> start -> wait evaluation
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
WORKER_TAG="${WORKER_TAG:-dev}"
MATRIX_SIZE="${MATMUL_MATRIX_SIZE:-64}"
BATCH_COUNT="${MATMUL_BATCH_COUNT:-1}"
export WORKER_TAG

require_http() {
  local name="$1" url="$2"
  if ! curl -sS -o /dev/null --max-time 5 -w '' "${url}"; then
    echo "ERROR: ${name} not reachable at ${url}"
    exit 1
  fi
}

echo "[0/7] prerequisites"
require_http "backend" "${BASE_URL}/docs"
require_http "node agent" "http://127.0.0.1:8001/health"

echo "[1/7] build worker images (skip if WORKER_SKIP_BUILD=1)"
if [[ "${WORKER_SKIP_BUILD:-0}" != "1" ]]; then
  "$(dirname "$0")/build_workers.sh"
fi

echo "[2/7] seed demo data (via ${BASE_URL})"
SEED_BASE_URL="${BASE_URL}" PYTHONPATH=backend backend/venv/bin/python backend/scripts/seed_demo_data.py > /tmp/seed_matmul.json
NODE_A=$(python3 -c "import json; print(json.load(open('/tmp/seed_matmul.json'))['node_ids'][0])")
NODE_B=$(python3 -c "import json; print(json.load(open('/tmp/seed_matmul.json'))['node_ids'][1])")
NODE_C=$(python3 -c "import json; print(json.load(open('/tmp/seed_matmul.json'))['node_ids'][2])")

TASK_ID="matmul-live-$(date +%s)"
echo "[3/7] create business task ${TASK_ID} (matrix=${MATRIX_SIZE}, batch=${BATCH_COUNT})"
CREATE_BODY=$(cat <<EOF
{
  "external_task_id": "${TASK_ID}",
  "task_type": "high_throughput_matmul",
  "modality": "high_throughput_compute",
  "name": "Matmul Live E2E",
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
    "strategy": "completion_time_first",
    "placements": {
      "source": "${NODE_A}",
      "compute": "${NODE_B}",
      "sink": "${NODE_C}"
    },
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
