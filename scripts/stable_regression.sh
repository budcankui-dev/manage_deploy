#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
REPORT_ROOT="${STABLE_REPORT_DIR:-$ROOT_DIR/reports/stable-regression/$(date +%Y%m%d-%H%M%S)}"
BASE_URL="${FRONTEND_BASE_URL:-http://127.0.0.1:5173}"
API_PROXY_TARGET="${VITE_API_PROXY_TARGET:-http://127.0.0.1:8181}"
STABLE_RUN_ID="$(date +%Y%m%d%H%M%S)"

mkdir -p "$REPORT_ROOT"

echo "== 稳定版回归 =="
echo "仓库: $ROOT_DIR"
echo "前端地址: $BASE_URL"
echo "API 代理: $API_PROXY_TARGET"
echo "报告目录: $REPORT_ROOT"

cd "$ROOT_DIR"
git status --short > "$REPORT_ROOT/git-status-before.txt"

echo
echo "== 1/6 前端构建 =="
npm --prefix "$FRONTEND_DIR" run build 2>&1 | tee "$REPORT_ROOT/frontend-build.log"

echo
echo "== 2/6 前端展示逻辑单测 =="
npm --prefix "$FRONTEND_DIR" run test:display 2>&1 | tee "$REPORT_ROOT/frontend-test-display.log"
npm --prefix "$FRONTEND_DIR" run test:route-recovery 2>&1 | tee "$REPORT_ROOT/frontend-test-route-recovery.log"
npm --prefix "$FRONTEND_DIR" run test:benchmark-session 2>&1 | tee "$REPORT_ROOT/frontend-test-benchmark-session.log"

echo
echo "== 3/6 前端页面巡检与截图 =="
UI_SMOKE_BASE_URL="$BASE_URL" \
UI_SMOKE_OUTPUT_DIR="$REPORT_ROOT/ui-smoke" \
E2E_ADMIN_USERNAME="${E2E_ADMIN_USERNAME:-admin}" \
E2E_ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-admin}" \
E2E_USER_USERNAME="${E2E_USER_USERNAME:-codex-stable-ui-$STABLE_RUN_ID}" \
E2E_USER_PASSWORD="${E2E_USER_PASSWORD:-123456}" \
npm --prefix "$FRONTEND_DIR" run ui:smoke 2>&1 | tee "$REPORT_ROOT/ui-smoke.log"

echo
echo "== 4/6 Playwright 主流程 E2E =="
(
  cd "$FRONTEND_DIR"
  PLAYWRIGHT_NO_WEBSERVER="${PLAYWRIGHT_NO_WEBSERVER:-0}" \
  FRONTEND_BASE_URL="$BASE_URL" \
  VITE_API_PROXY_TARGET="$API_PROXY_TARGET" \
  E2E_ADMIN_USERNAME="${E2E_ADMIN_USERNAME:-admin}" \
  E2E_ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-admin}" \
  E2E_USER_USERNAME="${E2E_USER_USERNAME:-codex-stable-e2e-$STABLE_RUN_ID}" \
  E2E_USER_PASSWORD="${E2E_USER_PASSWORD:-123456}" \
  PLAYWRIGHT_HTML_OUTPUT_DIR="$REPORT_ROOT/playwright-report" \
  PLAYWRIGHT_TEST_OUTPUT_DIR="$REPORT_ROOT/playwright-results" \
  npx playwright test --project="${PLAYWRIGHT_PROJECT:-chromium}" --workers="${PLAYWRIGHT_WORKERS:-1}" 2>&1 | tee "$REPORT_ROOT/playwright-e2e.log"
)

echo
echo "== 5/6 后端关键 API 单测（可选） =="
if [ "${SKIP_BACKEND_TESTS:-0}" = "1" ]; then
  echo "已跳过后端测试：SKIP_BACKEND_TESTS=1" | tee "$REPORT_ROOT/backend-tests.log"
elif [ -x "$ROOT_DIR/backend/venv/bin/python" ]; then
  (
    cd "$ROOT_DIR/backend"
    PYTHONPATH=. ./venv/bin/python -m pytest \
      tests/test_conversations_api.py \
      tests/test_business_tasks_api.py \
      tests/test_port_plan.py \
      -q
  ) 2>&1 | tee "$REPORT_ROOT/backend-tests.log"
else
  echo "未找到 backend/venv/bin/python，跳过后端测试。" | tee "$REPORT_ROOT/backend-tests.log"
fi

echo
echo "== 6/6 汇总 =="
cat > "$REPORT_ROOT/README.md" <<EOF
# 稳定版回归报告

- 执行时间：$(date '+%Y-%m-%d %H:%M:%S')
- 前端地址：$BASE_URL
- API 代理：$API_PROXY_TARGET
- Git 状态：见 \`git-status-before.txt\`
- 页面截图：\`ui-smoke/\`
- Playwright 报告：\`playwright-report/index.html\`
- Playwright 结果：\`playwright-results/\`

## 通过标准

- 前端构建成功。
- 展示逻辑、路由恢复、测评会话单测成功。
- UI smoke 不出现页面加载失败、明显横向溢出、中文标签竖排等问题。
- Playwright 主流程 E2E 成功。
- 后端关键 API 单测成功，或明确设置 \`SKIP_BACKEND_TESTS=1\` 跳过。
EOF

echo "稳定版回归通过。报告目录：$REPORT_ROOT"
