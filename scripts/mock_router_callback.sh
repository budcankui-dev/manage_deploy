#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SERVICE_TOKEN="${SERVICE_TOKEN:-change-me-service-token}"
ROUTING_ID="${1:?usage: mock_router_callback.sh <routing_request_id> [source_node] [compute_node] [sink_node]}"

SOURCE_NODE="${2:-}"
COMPUTE_NODE="${3:-}"
SINK_NODE="${4:-}"

if [[ -z "${SOURCE_NODE}" ]]; then
  DEMO=$(DEMO_BASE_URL="${BASE_URL}" PYTHONPATH=backend backend/venv/bin/python backend/scripts/setup_matmul_demo.py)
  SOURCE_NODE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['node_ids'][0])" "${DEMO}")
  COMPUTE_NODE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['node_ids'][1])" "${DEMO}")
  SINK_NODE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['node_ids'][2])" "${DEMO}")
fi

curl -sS -X POST "${BASE_URL}/api/routing-results/${ROUTING_ID}" \
  -H "Content-Type: application/json" \
  -H "X-Service-Token: ${SERVICE_TOKEN}" \
  -d "{
    \"status\": \"completed\",
    \"strategy\": \"completion_time_first\",
    \"placements\": {
      \"source\": \"${SOURCE_NODE}\",
      \"compute\": \"${COMPUTE_NODE}\",
      \"sink\": \"${SINK_NODE}\"
    },
    \"estimated_metric\": {
      \"metric_key\": \"compute_latency_ms\",
      \"metric_value\": 5000,
      \"unit\": \"ms\"
    },
    \"external_routing_id\": \"mock-router\"
  }" | python3 -m json.tool
