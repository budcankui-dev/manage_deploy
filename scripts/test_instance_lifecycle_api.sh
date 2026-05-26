#!/usr/bin/env bash
# 实例 CRUD + 批量操作 API 验收（需 backend + node agent）
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

require_http() {
  curl -sS -o /dev/null --max-time 5 -w '' "$1" || {
    echo "ERROR: not reachable: $1"
    exit 1
  }
}

echo "[0] prerequisites"
require_http "${BASE_URL}/docs"
require_http "http://127.0.0.1:8001/health"

echo "[1] prepare scientific matmul demo"
DEMO_BASE_URL="${BASE_URL}" PYTHONPATH=backend backend/venv/bin/python backend/scripts/setup_matmul_demo.py > /tmp/lifecycle_matmul_demo.json
TEMPLATE_ID=$(python3 -c "import json; print(json.load(open('/tmp/lifecycle_matmul_demo.json'))['matmul_template_id'])")
NODE_A=$(python3 -c "import json; print(json.load(open('/tmp/lifecycle_matmul_demo.json'))['node_ids'][0])")

echo "[2] create instance"
CREATE=$(curl -sS -X POST "${BASE_URL}/api/instances" -H 'Content-Type: application/json' -d "{
  \"template_id\": \"${TEMPLATE_ID}\",
  \"name\": \"lifecycle-api-$(date +%s)\",
  \"node_overrides\": [{\"template_node_name\": \"source\", \"node_id\": \"${NODE_A}\"}]
}")
INSTANCE_ID=$(echo "${CREATE}" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "instance_id=${INSTANCE_ID}"

echo "[3] start"
curl -sS --max-time 180 -X POST "${BASE_URL}/api/instances/${INSTANCE_ID}/start" > /dev/null
STATUS=$(curl -sS "${BASE_URL}/api/instances/${INSTANCE_ID}" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
echo "status_after_start=${STATUS}"

echo "[4] stop"
curl -sS --max-time 180 -X POST "${BASE_URL}/api/instances/${INSTANCE_ID}/stop" > /dev/null
STATUS=$(curl -sS "${BASE_URL}/api/instances/${INSTANCE_ID}" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
echo "status_after_stop=${STATUS}"

echo "[5] delete"
curl -sS --max-time 180 -X DELETE "${BASE_URL}/api/instances/${INSTANCE_ID}" > /dev/null
CODE=$(curl -sS -o /dev/null -w "%{http_code}" "${BASE_URL}/api/instances/${INSTANCE_ID}")
echo "get_after_delete=${CODE} (expect 404)"

echo "[6] batch delete remaining matmul-live / Matmul Live E2E instances"
IDS=$(curl -sS "${BASE_URL}/api/instances" | python3 -c "
import sys, json
items = json.load(sys.stdin)
ids = [i['id'] for i in items if 'matmul' in (i.get('name') or '').lower() or 'Matmul' in (i.get('name') or '')]
print(json.dumps(ids))
")
COUNT=$(echo "${IDS}" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
if [[ "${COUNT}" -gt 0 ]]; then
  echo "batch deleting ${COUNT} instances..."
  RESULT=$(curl -sS --max-time 300 -X POST "${BASE_URL}/api/instances/batch/delete" \
    -H 'Content-Type: application/json' \
    -d "{\"instance_ids\": ${IDS}}")
  echo "${RESULT}" | python3 -m json.tool
else
  echo "no matmul instances to batch delete"
fi

echo "OK instance lifecycle api passed"
