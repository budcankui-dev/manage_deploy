#!/usr/bin/env bash
# Delete all business-task orders listed by GET /api/business-tasks (for demo reset)
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

IDS=$(curl -sS "${BASE_URL}/api/business-tasks?page=1&page_size=100" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for item in data.get('items', []):
    print(item['order_id'])
")

if [[ -z "${IDS}" ]]; then
  echo "No business orders to delete."
  exit 0
fi

while IFS= read -r id; do
  [[ -z "${id}" ]] && continue
  echo "DELETE order ${id}"
  curl -sS -X DELETE "${BASE_URL}/api/orders/${id}" > /dev/null
done <<< "${IDS}"

echo "Done."
