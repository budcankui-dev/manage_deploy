# manage_deploy

通用多节点 Docker 任务编排系统（DAG 执行器）。

## 业务任务中心演示

```bash
# 清理旧工单（可选）
./scripts/cleanup_stale_business_orders.sh

# 实容器 matmul E2E（生成可演示工单）
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
```

前端 Admin → **业务任务中心** → **一键演示矩阵乘法**（自动启动并轮询评估）。

## 科学计算 Worker（matmul）

```bash
./scripts/build_workers.sh
SEED_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/seed_demo_data.py
# 需 backend :8000 + node_agent :8001
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
# 可选：E2E_DELETE_INSTANCE=1 跑完删实例；MATMUL_MATRIX_SIZE=256 大矩阵
```

默认账号（`init_db` 自动创建）：`admin/admin`（管理员）、`user/user`（普通用户）。

说明见 [`workers/high-throughput-matmul/README.md`](workers/high-throughput-matmul/README.md)。

## 后续规划

- 后台 UI 重组见 [`docs/planned-admin-ui-restructure.md`](docs/planned-admin-ui-restructure.md)（业务任务中心、侧边栏合并等，**待做**）。

## 前置要求

- Python 3.11+
- Node.js 18+
- Docker 和 Docker Compose
- MySQL 8.0+（开发阶段也可使用 SQLite）

## 数据库设置

创建 MySQL 数据库：

```bash
mysql -h 10.112.204.7 -u root -p'Bupt@1234' -e "CREATE DATABASE IF NOT EXISTS task_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

或使用提供的 SQL 文件：
```bash
mysql -h 10.112.204.7 -u root -p'Bupt@1234' < backend/create_db.sql
```

## 后端服务

```bash
cd backend
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -e .

# 启动服务
uvicorn main:app --reload --port 8000
```

API 访问地址：http://localhost:8000
API 文档地址：http://localhost:8000/docs

## 前端

```bash
cd frontend
npm install
npm run dev
```

前端访问地址：http://localhost:5173

## 节点 Agent（部署在各 worker 机器上）

```bash
cd node_agent
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

pip install -e .
uvicorn main:app --reload --port 8001
```

## Docker Compose（本地开发）

```bash
# 完整开发环境（Task Manager + Node Agent）
docker compose up -d

# 仅 Worker agents
docker compose -f docker-compose.agents.yml up -d
```

## 系统架构

- **Task Manager** (backend/)：FastAPI 应用，负责 DAG 编排、调度、批量操作
- **Node Agent** (node_agent/)：部署在每个 worker 机器上，通过 HTTP API 控制本地 Docker 容器
- **Frontend** (frontend/)：Vue3 + Element Plus UI，用于管理任务

## 业务任务闭环

系统支持从自然语言意图到三节点部署与业务指标评估的闭环，详见 [`docs/business-task-design-summary.md`](docs/business-task-design-summary.md) 与 [`docs/development-roadmap.md`](docs/development-roadmap.md)。

### 快速验证（L1 测试）

```bash
cd backend && PYTHONPATH=. ./venv/bin/python -m pytest tests/ -q
```

### 种子数据与 E2E 脚本

```bash
PYTHONPATH=backend backend/venv/bin/python backend/scripts/seed_demo_data.py
./scripts/e2e_business_task.sh
./scripts/mock_router_callback.sh <routing_request_id>
```

### 前端入口

- 普通用户：`/intent-chat`（对话 + 解析 + 路由 + 提交）
- 管理员：`/business-tasks`（成功率与评估结果）

## 开发与验收

- 规格说明：[`SPEC.md`](/Users/yanjia/codes/manage_deploy/SPEC.md)
- 开发联调与验收规范：[`DEVELOPMENT_ACCEPTANCE.md`](/Users/yanjia/codes/manage_deploy/DEVELOPMENT_ACCEPTANCE.md)

### 网络架构

- **管理网络**：Task Manager ↔ Node Agents 通过 HTTP 通信（独立的管理接口）
- **业务网络**：Docker 容器通过 host 网络模式通信
  - IPv6：2001:db8:1::/64（可配置）
  - IPv4：10.0.1.0/24（可配置）

## 项目结构

```
manage_deploy/
├── backend/                    # Task Manager
│   ├── main.py                # FastAPI 入口
│   ├── config.py              # 配置项
│   ├── database.py            # SQLAlchemy 异步配置
│   ├── enums.py              # 枚举类型
│   ├── models/                # SQLAlchemy 模型
│   ├── schemas/               # Pydantic schemas
│   ├── api/                   # 路由处理
│   ├── services/              # DAG 执行器、健康检查、调度器
│   └── agents/                # AgentClient（HTTP 调用 Node Agents）
├── node_agent/                # Node Agent
│   ├── main.py                # Agent API
│   ├── docker_handler.py       # Docker SDK 封装
│   └── health_checks.py        # 健康检查实现
├── frontend/                  # Vue3 前端
├── docker-compose.yml         # 本地开发环境
├── docker-compose.agents.yml  # Worker agents 部署
└── SPEC.md                    # 完整规格说明
```

## 主要功能

1. **任务模板管理**：创建可复用的任务定义，支持多节点 DAG 结构
2. **任务实例管理**：从模板创建实例，启动/停止/重启任务
3. **DAG 执行**：拓扑排序执行，保证节点依赖顺序
4. **健康检查**：支持端口检测、HTTP 检测、日志关键字、容器状态检测
5. **失败回滚**：节点启动失败时自动停止已启动的上游节点
6. **批量操作**：批量启动、停止、删除任务实例
7. **定时调度**：支持 start_time 和 end_time 定时执行
8. **孤儿容器巡检**：按节点扫描和清理已脱离数据库管理的任务容器

## 数据库表

| 表名 | 用途 |
|------|------|
| `nodes` | Worker 机器信息 |
| `task_templates` | 任务模板定义 |
| `task_instances` | 任务实例 |
| `task_instance_nodes` | 每个节点的 Docker 配置 |
| `task_edges` | DAG 边（依赖关系） |
| `task_events` | 状态变更和日志 |

## 任务状态流转

- **任务**：`pending` → `scheduled` → `starting` → `running` → `stopping` → `stopped` | `failed` | `expired`
- **节点**：`pending` → `starting` → `running` → `ready` → `stopping` → `stopped` | `failed`

## 环境变量配置

参考 `backend/.env.example`：

```
DATABASE_URL=mysql+aiomysql://root:Bupt%401234@10.112.204.7:3306/task_manager
IPV6_NETWORK=2001:db8:1::/64
IPV4_NETWORK=10.0.1.0/24
```
