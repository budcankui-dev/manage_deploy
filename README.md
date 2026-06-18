# manage_deploy

通用多节点 Docker 任务编排系统（DAG 执行器）。Task Manager 负责编排和业务评估，Node Agent 负责在 worker 机器上控制 Docker 容器，Frontend 提供管理端和意图对话入口。

当前维护两类演示业务：

- **矩阵乘法计算任务**，内部 `task_type` 为 `high_throughput_matmul`，用于高通量计算模态验收。
- **视频AI推理任务**，内部 `task_type` 为 `low_latency_video_pipeline`，用于低时延转发模态演示，支持 YOLO 抽帧推理、检测框和带框预览图展示。

## 文档入口

- [系统架构](docs/architecture.md)
- [测试与验收](docs/testing.md)
- [科学计算矩阵乘法演示](docs/scientific-matmul-demo.md)
- [业务目标成功率测评方案](docs/benchmark-test-plan.md)
- [新业务接入交接说明](docs/新业务接入交接说明.md)
- [测试部署机器清单](docs/deployment/测试部署机器清单.md)
- [管理节点跳板与网络迁移方案](docs/deployment/管理节点跳板与网络迁移方案.md)
- [终端拓扑节点扩展接入说明](docs/deployment/终端拓扑节点扩展接入说明.md)
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

## 演示业务

矩阵乘法 worker：

```bash
./scripts/build_workers.sh
DEMO_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/rebuild_matmul_template.py
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
```

视频推理 worker：

```bash
WORKER_KIND=video WORKER_IMAGE=10.112.244.94:5000/low-latency-video WORKER_TAG=dev WORKER_PLATFORM=linux/amd64 WORKER_PUSH=1 ./scripts/build_workers.sh
cd backend && WORKER_IMAGE=10.112.244.94:5000/low-latency-video WORKER_TAG=dev PYTHONPATH=. ./venv/bin/python scripts/rebuild_video_template.py
```

前端入口：普通用户进入 `/intent-chat`，可输入矩阵乘法或视频AI推理自然语言需求；确认参数后生成统一工单 ID、展示 DAG JSON 和模态信息。外部路由系统未接入时，可在用户端使用“随机路由并部署”完成演示闭环。

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
