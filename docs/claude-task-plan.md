# Claude 任务文档：科学计算矩阵乘法演示后续

## 1. 产品定位

当前只维护一个可演示业务：**科学计算矩阵乘法演示**。

内部稳定标识：

- `task_type`: `high_throughput_matmul`
- 模板名：`scientific-matmul-demo`
- Worker 镜像：`manage-deploy/scientific-matmul:{tag}`
- 演示准备脚本：`backend/scripts/setup_matmul_demo.py`

旧名 `seed_demo_data.py` 只是兼容包装，不再作为文档主入口。`seed` 的含义是“预置开发/演示数据”，不是业务任务名。

## 2. 当前架构状态

已完成：

- matmul worker 收敛为单镜像，source / compute / sink 通过模板 `command` 区分角色。
- source -> compute -> sink 已改为 HTTP 网络通信，不再用 `/scratch` 传业务数据。
- 模板节点通过 `port_defs` 声明端口，实例物化时生成 `ports` / `port_values` / `PEER_*` 环境变量。
- 前端展示名统一为“科学计算矩阵乘法”。
- 文档入口统一到 `docs/scientific-matmul-demo.md`。

待确认：

- 完整 live E2E 还没有跑通。最近一次失败点是 `setup_matmul_demo.py` 调 `GET /api/nodes` 收到 500，随后本地 backend 一度不可连接。
- 需要确认这是本地运行服务/数据库状态问题，还是代码路径里存在真实缺陷。

## 3. Claude 任务拆分

### Task A：诊断 `/api/nodes` 500

目标：让 `setup_matmul_demo.py` 可以稳定准备演示节点、模板和 catalog。

建议步骤：

1. 启动 backend 和 node_agent，并确认 `/health` 正常。
2. 直接请求 `GET /api/nodes`，拿到完整错误日志。
3. 检查当前数据库 schema，重点看 `nodes.business_ipv6` 等增量列是否存在。
4. 如果是旧数据库 schema 问题，给出清理/迁移方案；如果是代码问题，修复并补测试。

验收：

- `curl -sS http://127.0.0.1:8000/api/nodes | python3 -m json.tool` 正常返回数组。
- `DEMO_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/setup_matmul_demo.py` 正常输出 `node_ids`、`matmul_template_id`、`worker_image`。

### Task B：跑通科学计算矩阵乘法 live E2E

目标：验证单镜像、端口声明、PEER URL 注入、HTTP 数据流、指标上报和业务评估闭环。

建议步骤：

1. 构建 worker 镜像。
2. 准备演示数据。
3. 运行 live E2E。
4. 查看实例详情，确认三个节点都使用同一个镜像，但 command 不同。
5. 查看节点 logs，确认出现 `SOURCE_POSTED_JOB`、`COMPUTE_DONE`、`COMPUTE_POSTED_RESULT`、`SINK_DONE`。

验收：

- `WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh` 末尾输出 `OK matmul live e2e passed`。
- `GET /api/business-tasks/{instance_id}/evaluation` 返回 `metric_key=compute_latency_ms` 且 `business_success=true`。
- source / compute / sink 节点均有非空 `ports` 和 `port_values`。

### Task C：验证端口 preflight

目标：证明 matmul 不再绕过端口冲突检测。

建议步骤：

1. 启动一个 matmul 实例并保持 running。
2. 用同一组 worker placement 再创建/启动第二个 matmul 实例。
3. 观察启动前 preflight 是否报告 18801 / 18802 / 18803 端口冲突。

验收：

- 第二个实例启动失败，错误信息明确包含端口冲突。
- 冲突来自 Manager preflight 或 Node Agent preflight，不能静默进入运行状态。

### Task D：产品口径清理

目标：用户可见入口只强调“科学计算矩阵乘法演示”，避免旧视频/LLM 示例干扰演示。

建议步骤：

1. 检查 README、worker README、HANDOFF、roadmap、business design 文档是否仍把视频/LLM 当作当前演示。
2. 检查前端“任务类型”展示是否默认突出 matmul。
3. 决定 intent parser 对视频/LLM 请求的产品策略：保留为未来能力，还是提示“当前演示仅支持科学计算矩阵乘法”。

验收：

- 当前演示路径中不再出现 `matmul-source` / `matmul-compute` / `matmul-sink` 三镜像名。
- 当前演示路径中不再出现 matmul 依赖 `/scratch` 文件 IPC 的说法。
- 文档主入口统一指向 `docs/scientific-matmul-demo.md`。

## 4. 推荐命令

启动服务：

```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

```bash
cd node_agent
source venv/bin/activate
uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

健康检查：

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8000/api/nodes | python3 -m json.tool
```

构建与准备演示：

```bash
./scripts/build_workers.sh
DEMO_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/setup_matmul_demo.py
```

运行 E2E：

```bash
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
```

自动化测试：

```bash
cd backend && PYTHONPATH=. ./venv/bin/python -m pytest tests/ -q
cd frontend && npm run test:display
python3 -m py_compile backend/scripts/setup_matmul_demo.py backend/scripts/seed_demo_data.py workers/_common/http_server.py workers/high-throughput-matmul/src/*.py
git diff --check
```

排查容器：

```bash
docker images | grep 'manage-deploy'
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
```

清理旧演示工单：

```bash
./scripts/cleanup_stale_business_orders.sh
```

## 5. 注意事项

- 不要把旧 `seed_demo_data.py` 再写回文档主入口；它只是兼容包装。
- 不要恢复三镜像构建，除非明确要做角色专用小镜像优化。
- 不要重新引入 `/scratch` 作为业务数据传递路径。
- 完整 E2E 会创建数据库记录和 Docker 容器，跑完可用 `E2E_DELETE_INSTANCE=1` 或清理脚本收尾。
