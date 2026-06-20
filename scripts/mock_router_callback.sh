#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
ORDER_ID="${1:?usage: mock_router_callback.sh <order_id> [source_node] [compute_node] [sink_node]}"

SOURCE_NODE="${2:-}"
COMPUTE_NODE="${3:-}"
SINK_NODE="${4:-}"

if [[ -z "${SOURCE_NODE}" ]]; then
  SOURCE_NODE="h1"
  COMPUTE_NODE="compute-1"
  SINK_NODE="h2"
fi

curl -sS -X PATCH "${BASE_URL}/api/routing-orders/${ORDER_ID}/claim" \
  -H "Content-Type: application/json" >/dev/null

curl -sS -X POST "${BASE_URL}/api/routing-orders/${ORDER_ID}/result" \
  -H "Content-Type: application/json" \
  -d "{
    \"strategy\": \"fastest_completion\",
    \"placements\": [
      {\"task_node_id\": \"compute\", \"topology_node_id\": \"${COMPUTE_NODE}\", \"gpu_device\": \"0\"}
    ],
    \"estimated_metric\": {
      \"metric_key\": \"compute_latency_ms\",
      \"metric_value\": 5000,
      \"unit\": \"ms\"
    },
    \"external_routing_id\": \"mock-router\",
    \"metadata\": {\"mode\": \"local-script\", \"path\": [\"${SOURCE_NODE}\", \"${COMPUTE_NODE}\", \"${SINK_NODE}\"]},
    \"require_network_ready\": false
  }" | python3 -m json.tool
