# Matmul 业务目标验收 Runbook

> 适用场景：将本地业务目标验收改动迁移到 4 节点真实实验拓扑，并完成 `/benchmark` 页面 30 任务验收截图。

## 0. 验收目标

正式验收只认 `/benchmark` 页面 Step 4 的结果：

```text
任务类型：矩阵乘法计算任务
统计范围：is_benchmark=true 的验收压测工单
正式通过：已评估任务数 >= 30 且业务目标成功率 >= 90%
```

当前 `/benchmark` 页面的一键路由是验收 mock 路由，只用于跑通闭环，不替代外部路由系统，也不证明路由算法最优。

## 1. 本地提交前检查

本地至少执行：

```bash
PYTHONPATH=backend backend/venv/bin/python -m pytest \
  backend/tests/test_business_tasks_api.py::test_business_task_summary_can_filter_benchmark_orders \
  backend/tests/test_business_tasks_api.py::test_business_task_summary_success_rate_excludes_unevaluated_orders \
  backend/tests/test_business_tasks_api.py::test_business_task_create_and_metric_evaluation \
  backend/tests/test_business_tasks.py \
  backend/tests/test_matmul_core.py

cd frontend && npm run build
git diff --check
```

如果只部署业务目标验收最小集合，建议检查并提交以下文件：

```text
backend/api/baselines.py
backend/api/business_tasks.py
backend/api/orders.py
backend/services/baseline_runner.py
backend/services/business_task_query.py
backend/tests/test_business_tasks_api.py
frontend/src/api/index.js
frontend/src/views/BenchmarkView.vue
docs/benchmark-test-plan.md
docs/deployment/test-lab.md
docs/deployment/matmul-acceptance-runbook.md
docs/roadmap.md
```

其中 `frontend/src/App.vue`、`frontend/src/router.js`、`frontend/src/stores/auth.js` 只有在本次提交确实修改了 `/benchmark` 入口或认证逻辑时才需要纳入；若这些文件只包含其它功能线（例如意图评测）的改动，不要纳入 matmul 验收最小提交。`frontend/src/api/index.js` 当前只需要纳入 `businessApi.summary(params)` 的 hunk，避免把其它未完成页面的 API 一起提交。

不要把 `backend/app.db`、`backend/manage_deploy.db`、`output/`、`reports/`、`.claude/worktrees/` 等本地运行产物提交。

## 2. 管理节点更新

```bash
ssh manage-admin "cd /home/bupt/manage_deploy && git pull"

ssh manage-admin "cd /home/bupt/manage_deploy/frontend && npm ci && npm run build"

ssh manage-admin "pkill -f 'uvicorn main:app' 2>/dev/null || true; sleep 1; \
  cd /home/bupt/manage_deploy/backend && \
  nohup /home/bupt/miniconda3/envs/manage_deploy/bin/uvicorn main:app \
    --host 0.0.0.0 --port 8181 > /tmp/manage_deploy_backend.log 2>&1 &"
```

验证管理面：

```bash
curl -sS http://10.112.244.94:8181/docs >/dev/null
curl -sS http://10.112.244.94:8181/api/nodes | python3 -m json.tool
```

## 3. AMD64 Worker 镜像

在 `admin-server` 构建并推送，不要使用本地 macOS ARM64 镜像：

```bash
ssh manage-admin "cd /home/bupt/manage_deploy && \
  WORKER_IMAGE=10.112.244.94:5000/scientific-matmul \
  WORKER_TAG=dev \
  WORKER_PLATFORM=linux/amd64 \
  WORKER_PUSH=1 \
  ./scripts/build_workers.sh"
```

重建矩阵乘法模板，确保模板镜像指向私有仓库：

```bash
ssh manage-admin "cd /home/bupt/manage_deploy && \
  WORKER_IMAGE=10.112.244.94:5000/scientific-matmul \
  WORKER_TAG=dev \
  DEMO_BASE_URL=http://127.0.0.1:8181 \
  PYTHONPATH=backend \
  /home/bupt/miniconda3/envs/manage_deploy/bin/python backend/scripts/rebuild_matmul_template.py"
```

## 4. 业务节点预检

```bash
for host in manage-compute-1 manage-compute-2 manage-compute-3; do
  ssh "$host" "hostname; docker --version; docker pull 10.112.244.94:5000/scientific-matmul:dev"
done
```

如果业务节点拉取私有仓库失败，先确认 `/etc/docker/daemon.json` 包含：

```json
{
  "insecure-registries": ["10.112.244.94:5000"]
}
```

然后重启 Docker 和 Node Agent。

## 5. 命令行 E2E 预检

真实验收前先跑一次命令行 E2E，禁止设置 `WORKER_SKIP_BUILD=1`，禁止跳过远端镜像/架构/Agent 检查：

```bash
BASE_URL=http://10.112.244.94:8181 \
E2E_REMOTE=1 \
WORKER_IMAGE=10.112.244.94:5000/scientific-matmul \
WORKER_TAG=dev \
E2E_REMOTE_NODES="manage-compute-1 manage-compute-2 manage-compute-3" \
E2E_NODE_AGENT_HOSTS="10.112.249.191 10.112.150.166 10.112.116.165" \
MATMUL_MATRIX_SIZE=1024 \
MATMUL_BATCH_COUNT=50 \
./scripts/e2e_matmul_live.sh
```

E2E 通过后再进入页面完整验收，避免专家演示时暴露镜像架构或 Node Agent 问题。

## 6. 页面验收流程

打开：

```text
http://10.112.244.94:8182/benchmark
```

操作顺序：

1. Step 1 点击“批量测试所有节点”，确认 `compute-1/2/3` 都有稳定 baseline。
2. Step 2 使用默认 `任务数=30`、`矩阵=1024`、`批次=50`，点击“创建压测工单”。
3. Step 3 点击“一键路由”，再点击“一键启动”，等待状态进入“已完成”或“失败”。
4. Step 4 点击“刷新结果”，确认“已评估数 >= 30”。
5. 若成功率 `>= 90%`，保存页面截图和后端 summary JSON；若不足，保存失败任务详情和容器日志。

后端结果留档：

```bash
curl -sS "http://10.112.244.94:8181/api/business-tasks/summary?is_benchmark=true" \
  | tee reports/business_objective_summary_$(date +%Y%m%d_%H%M%S).json
```

## 7. 常见失败定位

| 现象 | 优先检查 |
|------|----------|
| `exec format error` | 镜像不是 `linux/amd64`，在 admin-server 重新构建并推送 |
| baseline 失败 | Node Agent 地址、Docker 权限、私有仓库拉取、benchmark 容器日志 |
| Step 4 样本不足 | 任务未完成、指标未上报、无 baseline 导致不可评价 |
| 成功率异常 100% 但任务数很少 | 不是正式验收；必须达到 30 个已评估任务 |
| 一键启动后无运行中状态 | 检查 `/tmp/manage_deploy_backend.log`、Node Agent 日志、端口冲突预检 |
