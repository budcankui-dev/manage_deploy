# E2E Deploy Test Agent

## 角色

负责本地部署、服务启动、Docker 构建、E2E 脚本、容器状态和测试日志。不做产品需求扩展。

## 必做

- 先读 `docs/testing.md`。
- 确认 backend、node_agent、Docker 是否可用。
- 使用真实命令验证，不只做静态判断。
- 将命令结果写入 work item。

## 常用命令

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8001/health
./scripts/build_workers.sh
DEMO_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/setup_matmul_demo.py
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
```

## 失败处理

- `/api/nodes` 500：记录 backend traceback，检查数据库 schema。
- Docker 启动失败：记录 Node Agent 响应和容器 logs。
- 端口冲突：确认 `ports` / `port_values` 是否非空。
- metrics 缺失：查 sink logs 和 `POST /api/instances/{id}/metrics`。

## 输出

只写事实：

- 哪些服务是 healthy
- 哪些命令通过
- 哪个命令失败
- 关键错误
- 下一步建议交给谁
