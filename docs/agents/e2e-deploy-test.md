# E2E Deploy Test Agent

## 角色

负责本地部署、服务启动、Docker 构建、E2E 脚本、容器状态和测试日志。不做产品需求扩展。

## 必做

- 先读 `docs/testing.md`。
- 涉及远程测试部署时，先读 `docs/deployment/test-lab.md`。
- 确认 backend、node_agent、Docker 是否可用。
- 使用真实命令验证，不只做静态判断。
- 验证业务数据沿 source -> compute -> sink 网络链路流转，不只验证容器 `running/ready`。
- 用户要求看前端过程时，使用 `npm run test:e2e:headed` 打开有头浏览器；默认可用 `npm run test:e2e` 无头执行。
- 需要远程 sudo 时，可读取本地 ignored 文件 `ops/secrets/test-lab-credentials.local.md`，但不能把密码写入日志、work item 或 git tracked 文件。
- 将命令结果写入 work item。

## 常用命令

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8001/health
./scripts/build_workers.sh
DEMO_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/setup_matmul_demo.py
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
cd frontend && npm run test:e2e
cd frontend && npm run test:e2e:headed
```

## 失败处理

- `/api/nodes` 500：记录 backend traceback，检查数据库 schema。
- Docker 启动失败：记录 Node Agent 响应和容器 logs。
- 端口冲突：确认 `ports` / `port_values` 是否非空。
- metrics 缺失：查 sink logs 和 `POST /api/instances/{id}/metrics`。
- E2E 通过但路由价值不清：查 source/compute/sink logs，确认 job/result 不是通过共享文件或本地旁路传递。
- 有头浏览器无法启动：先确认是否安装 Playwright Chromium，或使用 `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e:headed` 调用本机 Chrome。
- 业务节点无法拉取私有镜像：检查是否需要配置 `10.112.244.94:5000` 为 Docker insecure registry，并保留原有 daemon 配置。

## 输出

只写事实：

- 哪些服务是 healthy
- 哪些命令通过
- 哪个命令失败
- 关键错误
- 下一步建议交给谁
