#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
SERVICE_TOKEN="${SERVICE_TOKEN:-change-me-service-token}"

echo "[1/6] seed demo data"
PYTHONPATH=backend backend/venv/bin/python backend/scripts/seed_demo_data.py > /tmp/seed_result.json
NODE_A=$(python3 -c "import json; print(json.load(open('/tmp/seed_result.json'))['node_ids'][0])")
NODE_B=$(python3 -c "import json; print(json.load(open('/tmp/seed_result.json'))['node_ids'][1])")
NODE_C=$(python3 -c "import json; print(json.load(open('/tmp/seed_result.json'))['node_ids'][2])")

TASK_ID="e2e-$(date +%s)"
echo "[2/6] create business task ${TASK_ID}"
CREATE_BODY=$(cat <<EOF
{
  "external_task_id": "${TASK_ID}",
  "task_type": "low_latency_video_pipeline",
  "modality": "low_latency_forwarding",
  "name": "E2E 视频任务",
  "data_profile": {"profile_id": "video_720p_frame_stream"},
  "business_objective": {
    "metric_key": "end_to_end_latency_ms",
    "operator": "<=",
    "target_value": 200,
    "unit": "ms"
  },
  "runtime_plan": {"codec": "h264", "preset": "ultrafast"},
  "routing_result": {
    "strategy": "completion_time_first",
    "placements": {
      "source": "${NODE_A}",
      "compute": "${NODE_B}",
      "sink": "${NODE_C}"
    },
    "estimated_metric": {
      "metric_key": "end_to_end_latency_ms",
      "metric_value": 180,
      "unit": "ms"
    }
  },
  "auto_start": false
}
EOF
)

INSTANCE_ID=$(curl -sS -X POST "${BASE_URL}/api/business-tasks" \
  -H 'Content-Type: application/json' \
  -d "${CREATE_BODY}" | python3 -c "import sys,json; print(json.load(sys.stdin)['instance_id'])")

echo "[3/6] report metric for ${INSTANCE_ID}"
curl -sS -X POST "${BASE_URL}/api/instances/${INSTANCE_ID}/metrics" \
  -H 'Content-Type: application/json' \
  -d '{
    "metric_key": "end_to_end_latency_ms",
    "metric_value": 186.4,
    "unit": "ms",
    "tags": {"objects": [{"name": "result.json", "uri": "s3://task-results/e2e/result.json"}]}
  }' > /dev/null

echo "[4/6] fetch evaluation"
curl -sS "${BASE_URL}/api/business-tasks/${INSTANCE_ID}/evaluation" | python3 -m json.tool

echo "[5/6] fetch summary"
curl -sS "${BASE_URL}/api/business-tasks/summary" | python3 -m json.tool

echo "[6/6] done"
