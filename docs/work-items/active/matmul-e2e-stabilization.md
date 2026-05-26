# Work Item: Matmul E2E Stabilization

Status: todo
Owner Agent: E2E Deploy Test Agent
Last Updated: 2026-05-26

## Goal

跑通科学计算矩阵乘法 live E2E，确认单镜像、端口声明、PEER URL 注入、HTTP 数据流、指标上报和业务评估闭环稳定。

## Non-goals

- 不新增业务类型。
- 不恢复三镜像构建。
- 不使用 `/scratch` 传递 source/compute/sink 业务数据。
- 不重构前端 UI。

## Context

当前唯一维护的演示业务是科学计算矩阵乘法，内部 `task_type=high_throughput_matmul`。

本任务的架构关注点是随路计算：DAG 拓扑启动保证生命周期安全，但验收重点是业务数据沿外部路由选择的 source -> compute -> sink 节点路径通过 HTTP 网络流转。

最新已知阻塞：提升权限运行 `WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh` 时，`setup_matmul_demo.py` 调 `GET /api/nodes` 返回 500，随后本地 backend 一度不可连接。需要确认这是旧数据库 schema、运行服务状态，还是代码缺陷。

## Files Likely Involved

- `backend/api/nodes.py`
- `backend/database.py`
- `backend/models/__init__.py`
- `backend/scripts/setup_matmul_demo.py`
- `scripts/e2e_matmul_live.sh`
- `workers/high-throughput-matmul/src/*.py`
- `workers/_common/http_server.py`

## Required Commands

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8000/api/nodes | python3 -m json.tool
./scripts/build_workers.sh
DEMO_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/setup_matmul_demo.py
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
cd frontend && npm run test:e2e
# 可选：需要人工观察浏览器过程时
cd frontend && npm run test:e2e:headed
```

## Acceptance Criteria

- `GET /api/nodes` 正常返回数组。
- `setup_matmul_demo.py` 输出 `node_ids`、`matmul_template_id`、`worker_image`。
- `e2e_matmul_live.sh` 输出 `OK matmul live e2e passed`。
- evaluation 返回 `metric_key=compute_latency_ms` 且 `business_success=true`。
- source / compute / sink 日志或 API 结果能证明 job/result 通过 HTTP `PEER_*` 链路流转。
- source / compute / sink 节点均有非空 `ports` 和 `port_values`。
- 同机重复部署 matmul 能触发端口冲突。
- 前端浏览器 E2E 能打开业务工单中心；需要人工观察时可用有头浏览器模式。

## Commands Run

- Pending.

## Findings

- Pending.

## Changes Made

- Pending.

## Open Risks

- 本地开发数据库可能有旧 schema。
- backend 进程可能没有重启加载最新 `init_db()`。

## Next Agent Instructions

E2E Deploy Test Agent 先定位 `/api/nodes` 500。拿到 backend traceback 后，如果是代码问题，转给 Implementation Agent；如果是环境或旧 DB 问题，给出最小清理/迁移命令并继续跑 E2E。E2E 通过后补充 source/compute/sink 日志或等价证据，证明矩阵 job/result 走的是网络随路计算链路。
