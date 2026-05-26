# 测试与验收

本文档是唯一的测试入口。新增功能、修复和 agent 交接都应记录实际执行过的命令和结果。

## 基础服务

启动 Task Manager：

```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

启动 Node Agent：

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

## 自动化测试

后端：

```bash
cd backend
PYTHONPATH=. ./venv/bin/python -m pytest tests/ -q
```

前端展示逻辑：

```bash
cd frontend
npm run test:display
```

Worker 和脚本语法：

```bash
python3 -m py_compile \
  backend/scripts/setup_matmul_demo.py \
  backend/scripts/seed_demo_data.py \
  workers/_common/http_server.py \
  workers/high-throughput-matmul/src/*.py
```

格式/空白：

```bash
git diff --check
```

## 科学计算矩阵乘法 E2E

构建 worker 镜像：

```bash
./scripts/build_workers.sh
```

准备演示数据：

```bash
DEMO_BASE_URL=http://127.0.0.1:8000 \
PYTHONPATH=backend \
backend/venv/bin/python backend/scripts/setup_matmul_demo.py
```

运行 live E2E：

```bash
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
```

可选参数：

```bash
MATMUL_MATRIX_SIZE=256 WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
E2E_DELETE_INSTANCE=1 WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
```

期望：

- 脚本末尾输出 `OK matmul live e2e passed`
- 实例状态进入 `running`
- evaluation 返回 `metric_key=compute_latency_ms`
- `business_success=true`
- source / compute / sink 均有非空 `ports` 和 `port_values`

## 端口冲突验收

目的：确认 matmul 已进入 preflight 检查，不再绕过端口冲突。

步骤：

1. 启动一个 matmul 实例并保持 running。
2. 使用同一组 placements 再创建/启动第二个 matmul 实例。
3. 观察启动前 preflight 是否报告 `18801` / `18802` / `18803` 冲突。

期望：第二个实例启动失败，错误信息包含端口冲突，不能静默进入 running。

## 回滚清理验收

```bash
./scripts/verify_rollback_cleanup.sh
```

期望：

- 故意失败的实例进入 `failed`
- Docker 中没有残留 `{instance_id}_*` 容器

## 常见排查

查看镜像和容器：

```bash
docker images | grep 'manage-deploy'
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
```

清理旧演示工单：

```bash
./scripts/cleanup_stale_business_orders.sh
```

如果 `GET /api/nodes` 返回 500，优先检查：

- backend 是否重启并执行过 `init_db()`
- 当前数据库是否缺少新增列，如 `nodes.business_ipv6`
- backend 控制台完整 traceback
- 当前服务连接的是 MySQL 还是 SQLite

## 提交前最低要求

- 后端改动：跑相关单测；共享行为变更跑全量 `backend/tests`。
- 前端展示改动：跑 `npm run test:display`，必要时打开页面手工确认。
- Worker/Docker 改动：跑 `./scripts/build_workers.sh`，能跑 E2E 时跑 `e2e_matmul_live.sh`。
- 文档/agent 提示词改动：跑 `git diff --check`，确认 README 链接不指向已删除文件。
