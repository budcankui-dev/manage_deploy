#!/usr/bin/env bash
# 验证 DAG 失败回滚会 delete 容器，而非留下 Exited 残留
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
DEBUG_LOG="${DEBUG_LOG:-.cursor/debug-2df3cf.log}"

echo "[1/6] prepare scientific matmul demo data"
DEMO_BASE_URL="${BASE_URL}" PYTHONPATH=backend backend/venv/bin/python backend/scripts/setup_matmul_demo.py > /tmp/matmul_demo_verify.json
MATMUL_TEMPLATE_ID=$(python3 -c "import json; print(json.load(open('/tmp/matmul_demo_verify.json'))['matmul_template_id'])")
NODE_A=$(python3 -c "import json; print(json.load(open('/tmp/matmul_demo_verify.json'))['node_ids'][0])")

echo "[2/6] create instance with impossible source health check"
CREATE_BODY=$(cat <<EOF
{
  "template_id": "${MATMUL_TEMPLATE_ID}",
  "name": "rollback-verify-$(date +%s)",
  "node_overrides": [
    {
      "template_node_name": "source",
      "health_check": {
        "type": "log",
        "keyword": "NEVER_MATCH_ROLLBACK_VERIFY",
        "timeout": 15,
        "interval": 2,
        "retry": 3
      }
    }
  ]
}
EOF
)
CREATE_RESP=$(curl -sS -X POST "${BASE_URL}/api/instances" \
  -H 'Content-Type: application/json' \
  -d "${CREATE_BODY}")
INSTANCE_ID=$(echo "${CREATE_RESP}" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "instance_id=${INSTANCE_ID}"

echo "[3/6] start instance (expect failure + rollback)"
curl -sS --max-time 120 -X POST "${BASE_URL}/api/instances/${INSTANCE_ID}/start" \
  -H 'Content-Type: application/json' > /dev/null || true

echo "[4/6] wait for failed status"
STATUS=""
for _ in $(seq 1 30); do
  STATUS=$(curl -sS "${BASE_URL}/api/instances/${INSTANCE_ID}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  echo "  status=${STATUS}"
  if [[ "${STATUS}" == "failed" ]]; then
    break
  fi
  sleep 2
done
if [[ "${STATUS}" != "failed" ]]; then
  echo "ERROR: expected failed, got ${STATUS}"
  curl -sS "${BASE_URL}/api/instances/${INSTANCE_ID}" | python3 -m json.tool
  exit 1
fi

echo "[5/6] check docker for leftover containers named ${INSTANCE_ID}_*"
LEFTOVER=$(docker ps -a --format '{{.Names}}' | grep -c "^${INSTANCE_ID}_" || true)
echo "leftover_containers=${LEFTOVER}"
if [[ "${LEFTOVER}" != "0" ]]; then
  docker ps -a --format '{{.Names}}\t{{.Status}}' | grep "^${INSTANCE_ID}_" || true
  echo "ERROR: rollback should delete containers for this instance"
  exit 1
fi

echo "[6/6] check debug log entries"
if [[ -f "${DEBUG_LOG}" ]]; then
  grep -c "rollback_remove_result" "${DEBUG_LOG}" || true
  grep "rollback_remove_result" "${DEBUG_LOG}" | tail -5 || true
else
  echo "WARN: debug log not found at ${DEBUG_LOG}"
fi

echo "OK rollback cleanup verified for ${INSTANCE_ID}"
