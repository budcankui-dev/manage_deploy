# 业务目标验收 Runbook（矩阵乘法 / 视频推理）

> 适用场景：将本地业务目标验收改动迁移到真实实验拓扑，并完成 `/benchmark` 页面 30 任务验收截图。矩阵乘法是主验收链路，视频推理作为第二模态扩展业务按同一工具链执行。

## 0. 验收目标

正式验收只认 `/benchmark` 页面 Step 4 的结果：

```text
任务类型：矩阵乘法计算任务
统计范围：当前 benchmark_run_id 下 is_benchmark=true 的验收测评工单
正式通过：已评估任务数 >= 30 且业务目标成功率 >= 90%
```

当前 `/benchmark` 页面优先使用外部路由系统回写的 placements；系统设置页可切换开发调试路由流程，用于外部路由系统联调前验证部署与评价闭环。正式矩阵验收使用“运行测评”，按小批次限流执行，避免 30 个任务一次性并发启动导致单任务基线口径失真。

最近一次真实矩阵验收轮次：

```text
benchmark_run_id: high_throughput_matmul-20260612095418
结果: 30 / 30 已评估，30 / 30 达标，业务目标成功率 100.0%
页面: http://10.112.244.94:8182/benchmark?benchmark_run_id=high_throughput_matmul-20260612095418
```

视频 AI 推理当前已完成小批量联调轮次 `video-route-pool-check-20260612160633`，4 / 4 可评价且达标，可用于证明固定视频、YOLO 推理、GPU 分配和带框预览链路；正式留档仍需按同一页面流程重新执行不少于 30 个可评价工单的验收轮次。

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
docs/deployment/测试部署机器清单.md
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

启用业务面 IPv6 时，管理节点 `backend/.env` 至少确认：

```bash
PREFER_BUSINESS_IPV6=true
BACKEND_PORT=8181
```

`BACKEND_PORT` 必须等于实际后端端口。该值会参与生成 worker 容器内的 `MANAGER_API_BASE`；如果仍是默认 `8000`，source/compute/sink 的 IPv6 数据面可能跑通，但 sink 指标回写会失败。

后端重启后检查日志：

```bash
ssh manage-admin "grep 'Resolved MANAGER_PUBLIC_URL' /home/bupt/manage_deploy/backend/backend.log | tail -1"
```

期望包含：

```text
Resolved MANAGER_PUBLIC_URL=http://10.112.244.94:8181
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

如果现场网络无法访问 Docker Hub、Ubuntu apt 或 NVIDIA 软件源，但 registry 中已有可运行的 `linux/amd64` 旧镜像，可用“刷新业务代码层”的备用路径，避免重新下载系统依赖：

```bash
ssh manage-admin "cd /home/bupt/manage_deploy && \
  docker pull localhost:5000/scientific-matmul:dev && \
  docker tag localhost:5000/scientific-matmul:dev scientific-matmul:base-cache && \
  cat >/tmp/Dockerfile.matmul-refresh <<'EOF'
FROM scientific-matmul:base-cache
COPY _common /app/_common
COPY high-throughput-matmul/src /app/src
ENV PYTHONPATH=/app/src:/app
ENV USE_GPU=true
CMD [\"python3\", \"/app/src/source_main.py\"]
EOF
  docker build --pull=false --platform linux/amd64 \
    -f /tmp/Dockerfile.matmul-refresh \
    -t localhost:5000/scientific-matmul:dev workers && \
  docker run --rm --entrypoint python3 localhost:5000/scientific-matmul:dev \
    -c 'import pathlib; t=pathlib.Path(\"/app/src/compute_main.py\").read_text(); print(\"observation_duration_sec\" in t, \"sample_count\" in t)' && \
  docker push localhost:5000/scientific-matmul:dev"
```

该备用路径只适用于已确认旧镜像基础依赖正确的验收环境。若改动涉及系统包、Python 依赖或 CUDA 版本，仍需恢复网络后完整重建。

如果只是刷新公共业务通信代码（例如 `_common/http_server.py` 的 IPv6 双栈监听修复），且现场网络无法访问 Docker Hub / apt / NVIDIA 源，可使用更小的补丁镜像路径：

```bash
ssh manage-admin "cd /home/bupt/manage_deploy && \
  printf 'FROM localhost:5000/scientific-matmul:dev\nCOPY _common/http_server.py /app/_common/http_server.py\n' \
    >/tmp/Dockerfile.scientific-matmul-ipv6 && \
  docker build -f /tmp/Dockerfile.scientific-matmul-ipv6 \
    -t 10.112.244.94:5000/scientific-matmul:dev workers && \
  docker push 10.112.244.94:5000/scientific-matmul:dev"
```

视频 worker 同理：

```bash
ssh manage-admin "cd /home/bupt/manage_deploy && \
  printf 'FROM 10.112.244.94:5000/low-latency-video:dev\nCOPY _common/http_server.py /app/_common/http_server.py\n' \
    >/tmp/Dockerfile.low-latency-video-ipv6 && \
  docker build -f /tmp/Dockerfile.low-latency-video-ipv6 \
    -t 10.112.244.94:5000/low-latency-video:dev workers && \
  docker push 10.112.244.94:5000/low-latency-video:dev"
```

推送后，三台业务节点必须重新 `docker pull` 对应 tag。Node Agent 不会自动拉取已存在的同名旧 tag。

重建矩阵乘法模板，确保模板镜像指向私有仓库：

```bash
ssh manage-admin "cd /home/bupt/manage_deploy/backend && \
  WORKER_IMAGE=10.112.244.94:5000/scientific-matmul \
  WORKER_TAG=dev \
  DEMO_BASE_URL=http://127.0.0.1:8181 \
  PYTHONPATH=/home/bupt/manage_deploy/backend \
  /home/bupt/miniconda3/envs/manage_deploy/bin/python scripts/rebuild_matmul_template.py"
```

模板节点必须开启 `port_defs.auto=true`。正式 `/benchmark` 批量验收会并发物化 30 个实例，如果端口仍固定为 `18801/18802/18803`，同一物理节点上的多个容器会互相抢端口或串到其它实例，表现为只有少数任务上报指标。

视频推理 worker 使用固定测试视频和 YOLO 权重，镜像同样在 `admin-server` 构建并推送：

```bash
ssh manage-admin "cd /home/bupt/manage_deploy && \
  WORKER_KIND=video \
  WORKER_IMAGE=10.112.244.94:5000/low-latency-video \
  WORKER_TAG=dev \
  WORKER_PLATFORM=linux/amd64 \
  WORKER_PUSH=1 \
  ./scripts/build_workers.sh"
```

重建视频业务模板和 catalog：

```bash
ssh manage-admin "cd /home/bupt/manage_deploy/backend && \
  WORKER_IMAGE=10.112.244.94:5000/low-latency-video \
  WORKER_TAG=dev \
  DEMO_BASE_URL=http://127.0.0.1:8181 \
  PYTHONPATH=/home/bupt/manage_deploy/backend \
  /home/bupt/miniconda3/envs/manage_deploy/bin/python scripts/rebuild_video_template.py"
```

视频模板同样要求 `port_defs.auto=true`。compute 子任务默认需要 GPU，路由结果应写回 `gpu_device`；如果启用了仅开发调试的 CPU 路径，工单详情会显示 `gpu_assigned=false` 或无 GPU 分配，不建议作为正式达标样本。

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

如果 Node Agent 镜像较旧，`POST /ports/available` 可能返回 404。当前 backend 会在这种情况下使用数据库已分配端口和模板端口范围做本地开发调试端口分配，足够支撑联调；正式环境仍建议重建并部署包含 `/ports/available` 的 Node Agent 镜像。

## 5. 命令行 E2E 预检

真实验收前先跑一次命令行 E2E，禁止设置 `WORKER_SKIP_BUILD=1`，禁止跳过远端镜像/架构/Agent 检查：

```bash
BASE_URL=http://10.112.244.94:8181 \
E2E_REMOTE=1 \
WORKER_IMAGE=10.112.244.94:5000/scientific-matmul \
WORKER_TAG=dev \
E2E_REMOTE_NODES="manage-compute-1 manage-compute-2 manage-compute-3" \
E2E_NODE_AGENT_HOSTS="10.112.38.25 10.112.17.51 10.112.59.209" \
MATMUL_MATRIX_SIZE=1024 \
MATMUL_BATCH_COUNT=50 \
./scripts/e2e_matmul_live.sh
```

E2E 通过后再进入页面完整验收，避免专家演示时暴露镜像架构或 Node Agent 问题。

IPv6 数据面验证必须额外抽查真实容器，而不是只看 `OK`：

```bash
docker inspect <container_name> --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -E 'PEER_.*_URL|TASK_PEERS_JSON|MANAGER_API_BASE'
docker logs --tail 50 <sink_container_name>
```

期望：

- `PEER_*_URL` 使用 `http://[2001:...]:port` 方括号 IPv6 URL。
- `TASK_PEERS_JSON` 中 `business_address` 为 IPv6。
- `MANAGER_API_BASE=http://10.112.244.94:8181`。
- sink 日志出现 `SINK_DONE`，业务评估返回 `business_success=true`。

## 6. 页面验收流程

打开：

```text
http://10.112.244.94:8182/benchmark
```

操作顺序：

1. Step 1 点击“批量测试所有节点”，确认 `compute-1/2/3` 都有稳定 baseline。
2. Step 2 使用默认 `任务数=30`、`矩阵=1024`、`批次=50`，点击“创建测评工单”，记录页面顶部显示的 `benchmark_run_id`。
3. Step 3 使用外部路由系统回写 placements，或在系统设置页启用开发调试路由流程后点击“运行测评”，等待当前轮次状态进入“已评估完成”或“失败”。运行测评会按小批次启动下一批任务，已评估样本会自动清理容器实例但保留工单证据。
4. Step 4 点击“计算/更新成功率”，确认“已评估数 >= 30”。
5. 若成功率 `>= 90%`，保存页面截图和后端 summary JSON；若不足，保存失败任务详情和容器日志。

视频推理业务页面流程基本相同：

1. 在页面顶部任务类型选择“视频AI推理任务”。
2. Step 1 对参与计算的节点执行视频 profile baseline，确认基线稳定。
3. Step 2 使用默认 `任务数=30`、`frame_stride=30`、`warmup_frames=10`、`measured_frames=30` 创建测评工单。
4. Step 3 完成路由结果回写后点击“运行测评”，系统按小批次分批运行；正式测评时同一 GPU 并发数设为 1。
5. 在工单详情中确认 source / compute / sink 放置、compute GPU 编号、`frame_latency_p90_ms`、检测类别、画框坐标和带框预览图。
6. Step 4 确认已评估任务数 `>= 30` 且成功率 `>= 90%`。

后端结果留档：

```bash
RUN_ID="high_throughput_matmul-YYYYMMDDHHMMSS"
curl -sS "http://10.112.244.94:8181/api/business-tasks/summary?is_benchmark=true&benchmark_run_id=${RUN_ID}" \
  | tee reports/business_objective_summary_$(date +%Y%m%d_%H%M%S).json

curl -sS "http://10.112.244.94:8181/api/orders?is_benchmark=true&benchmark_run_id=${RUN_ID}&limit=100" \
  | tee reports/business_objective_orders_${RUN_ID}.json
```

## 7. 常见失败定位

| 现象 | 优先检查 |
|------|----------|
| `exec format error` | 镜像不是 `linux/amd64`，在 admin-server 重新构建并推送 |
| baseline 失败 | Node Agent 地址、Docker 权限、私有仓库拉取、benchmark 容器日志 |
| Step 4 样本不足 | 任务未完成、指标未上报、无 baseline 导致不可评价 |
| 成功率异常 100% 但任务数很少 | 不是正式验收；必须达到 30 个已评估任务 |
| 批量测评只有少数任务上报指标 | 检查模板 `port_defs.auto=true`、backend 自动端口分配、同一节点端口是否重复 |
| 运行测评长时间无进展 | 检查当前轮次是否已路由、是否仍有运行中任务未上报指标、Node Agent 日志、容器日志和端口冲突预检 |
| 一次性启动后成功率低于 90% | 不建议作为正式矩阵验收口径；改用“运行测评”，因为 baseline 是同 profile 单任务历史能力 |
| 视频详情没有带框图 | 确认 worker 镜像已包含 `workers/low-latency-video/assets`，sink 上报 tags.result 中有 `annotated_frame_data_url`，后端已重启到最新代码 |
| 视频详情 GPU 显示无分配 | 检查路由结果是否为 compute/worker 写回 `gpu_device`，以及 Node Agent 创建容器时是否传入 GPU 设备 |
| 视频基线或任务很慢 | 优先确认是否走 GPU；正式参数为 `measured_frames=30`，不要在演示前临时提高帧数 |
