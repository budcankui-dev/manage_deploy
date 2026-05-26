# manage_deploy

通用多节点 Docker 任务编排系统（DAG 执行器）。Task Manager 负责编排和业务评估，Node Agent 负责在 worker 机器上控制 Docker 容器，Frontend 提供管理端和意图对话入口。

当前维护的演示业务是 **科学计算矩阵乘法演示**，内部 `task_type` 为 `high_throughput_matmul`。

## 文档入口

- [系统架构](docs/architecture.md)
- [测试与验收](docs/testing.md)
- [科学计算矩阵乘法演示](docs/scientific-matmul-demo.md)
- [Roadmap](docs/roadmap.md)
- [Agent 协作手册](docs/agents/README.md)
- [当前 Work Items](docs/work-items/active/matmul-e2e-stabilization.md)

## 快速启动

后端：

```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Node Agent：

```bash
cd node_agent
source venv/bin/activate
uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

前端：

```bash
cd frontend
npm install
npm run dev
```

默认账号：

- `admin` / `admin`
- `user` / `user`

## 科学计算矩阵乘法演示

```bash
./scripts/build_workers.sh
DEMO_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/setup_matmul_demo.py
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
```

前端入口：Admin -> 业务任务中心 -> 一键演示矩阵乘法。

## 常用测试

```bash
cd backend && PYTHONPATH=. ./venv/bin/python -m pytest tests/ -q
cd frontend && npm run test:display
cd frontend && npm run test:e2e
git diff --check
```

更多测试命令见 [docs/testing.md](docs/testing.md)。

## 项目结构

```text
manage_deploy/
├── backend/       # Task Manager
├── node_agent/    # Worker 机器上的 Docker 控制 Agent
├── frontend/      # Vue3 + Element Plus
├── workers/       # 业务 Worker 镜像源码
├── scripts/       # 构建、E2E、清理和验证脚本
└── docs/          # 架构、测试、演示、agent 协作和 work item
```
