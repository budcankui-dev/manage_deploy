# AGENTS.md

本文件为 Codex (Codex.ai/code) 在本代码仓库中工作时提供指导。

## 项目概述

通用多节点 Docker 任务编排系统（DAG 执行器），用于管理远程容器。

### 核心概念
- **任务（Task）** = 由多个节点组成的 DAG，每个节点在一台远程机器上启动一个 Docker 容器
- **Task Manager** (backend/) = 负责 DAG 执行编排、调度、批量操作、幂等性、失败回滚
- **Node Agent** (node_agent/) = 部署在每个 worker 机器上，接收 HTTP 命令控制本地 Docker

### 网络架构
- **控制面（IPv4）**：Manager、MySQL、MinIO、Node Agent API（如 `127.0.0.1:8000/8001`）
- **数据面（开发）**：`business_ip` 与管理面同源（seed 默认 `127.0.0.1`），`PREFER_BUSINESS_IPV6=false`
- **数据面（验收）**：节点配置 `business_ipv6`，`PREFER_BUSINESS_IPV6=true`，跑 `scripts/verify_macro_port_e2e.py`
- **macOS Docker Desktop**：Worker 回调 Manager/MinIO 用 `MANAGER_PUBLIC_URL=http://host.docker.internal:8000`（见 `backend/.env.example`）
- **业务 Worker**：`workers/high-throughput-matmul/` 三镜像；`./scripts/build_workers.sh` + `scripts/e2e_matmul_live.sh`
- **节点间业务通信（强约束）**：业务节点之间必须通过网络通信（host 网络 + IPv6/IPv4 PEER URL），每节点必须如实声明 `ports`（监听端口），让 preflight（`backend/api/instances.py` + `node_agent/port_utils.py`）能检出冲突；不允许共享卷/宿主机文件做业务数据传递（MinIO 仅用于结果归档）。当前科学计算矩阵乘法演示已改为 HTTP 网络通信，详 `docs/scientific-matmul-demo.md`。

## 技术栈
- 后端：FastAPI + SQLAlchemy（异步）+ APScheduler + Docker SDK
- 数据库：SQLite（开发用）/ MySQL（生产用）
- Node Agent：FastAPI + docker-py
- 前端：Vue3 + Element Plus（部分已实现）
- 部署：每台机器一个 Docker Compose

## 项目结构
```
manage_deploy/
├── backend/                    # Task Manager（FastAPI 应用）
│   ├── main.py                 # 应用入口
│   ├── config.py              # 配置
│   ├── database.py            # SQLAlchemy 异步配置
│   ├── enums.py               # TaskStatus, NodeStatus, HealthCheckType
│   ├── models/                # SQLAlchemy 模型
│   ├── schemas/               # Pydantic 请求/响应 schemas
│   ├── api/                   # FastAPI 路由处理器
│   ├── services/              # DAG 执行器、健康检查器、调度器
│   └── agents/                # AgentClient（HTTP 调用 Node Agents）
├── node_agent/                # Node Agent（worker 机器上运行）
│   ├── main.py               # Agent API
│   ├── docker_handler.py     # Docker SDK 封装
│   └── health_checks.py      # 健康检查实现
├── frontend/                  # Vue3 前端
├── docker-compose.yml        # 本地开发环境（manager + agent）
├── docker-compose.agents.yml # Worker agents 部署配置
└── pyproject.toml           # 根工作区配置
```

## 数据库表
| 表名 | 用途 |
|------|------|
| `nodes` | Worker 机器（hostname, agent_address, management_ip, business_ip） |
| `task_templates` | 可复用的任务定义 |
| `task_template_nodes` | 模板中的节点定义 |
| `task_template_edges` | 模板中的 DAG 边 |
| `task_instances` | 具体的任务运行实例 |
| `task_instance_nodes` | 每个节点的 Docker 参数（image, command, env, volumes, ports, gpu, health_check） |
| `task_instance_edges` | 实例中的 DAG 边 |
| `task_events` | 状态变更、错误、日志 |
| `business_template_catalog` | 业务 task_type → 模板映射 |
| `business_objective_evaluations` | 业务目标判定结果 |
| `conversations` / `intent_drafts` / `routing_requests` | 意图对话与外部路由状态 |

## 任务/节点状态
- **任务**：`pending` → `scheduled` → `starting` → `running` → `stopping` → `stopped` | `failed` | `expired`
- **节点**：`pending` → `starting` → `running` → `ready` → `stopping` → `stopped` | `failed`

## 健康检查类型
- `port`：容器端口是否开放
- `http`：HTTP GET 返回 2xx
- `log`：容器日志中是否包含关键字
- `container`：另一个容器是否正在运行

## 常用命令
```bash
# 后端开发
cd backend && source venv/bin/activate && uvicorn main:app --reload --port 8000

# Node Agent（在每个 worker 上）
cd node_agent && source venv/bin/activate && uvicorn main:app --reload --port 8001

# Docker Compose 本地开发
docker compose up

# Docker Compose 部署 worker agents
docker compose -f docker-compose.agents.yml up -d
```

## API 端点

当前系统架构见 [`docs/architecture.md`](docs/architecture.md)，测试验收见 [`docs/testing.md`](docs/testing.md)，后续计划见 [`docs/roadmap.md`](docs/roadmap.md)。

### 部署编排
- `POST /api/templates` - 创建任务模板
- `POST /api/instances` - 创建任务实例
- `POST /api/instances/{id}/start` - 启动任务（DAG 执行）
- `POST /api/instances/{id}/stop` - 停止任务（反向 DAG）
- `POST /api/instances/batch/start` - 批量启动
- `PUT /api/instances/{id}/schedule` - 设置 start_time/end_time
- `POST /api/nodes` - 注册 worker 节点

### 业务任务与认证
- `POST /api/business-tasks` - 标准业务任务接入（含路由 placements）
- `GET /api/business-tasks` - 业务任务分页列表（含部署状态与评估摘要）
- `GET /api/business-tasks/summary` - 业务目标成功率统计
- `GET /api/orders/{id}` - 工单详情（含 business_task / instance / evaluation）
- `POST /api/auth/login|bootstrap` - 登录与初始化管理员

### 意图对话与路由（同仓）
- `POST /api/conversations` - 创建对话
- `POST /api/conversations/{id}/messages` - 发送消息并解析意图
- `POST /api/conversations/{id}/confirm-intent` - 确认意图草稿
- `POST /api/routing-requests` - 请求外部路由
- `POST /api/routing-results/{id}` - 外部路由回调（需 `X-Service-Token`）
- `POST /api/conversations/{id}/submit` - 确认提交到部署系统

### 系统边界
- **意图解析**：NL → task_type / data_profile / business_objective（不负责 node 放置）
- **外部路由**：输出 A/B/C placements
- **本系统**：物化实例、DAG 部署、指标评估、成功率统计

### 前端入口
- `/login` - 登录
- `/intent-chat` - 普通用户对话入口
- `/business-tasks` - Admin 业务任务中心（默认首页）
- `/dev/instances` - Admin 运维 / 手动部署
- `/nodes`、`/templates` - Admin 基础设施
