# SPEC.md - Docker DAG 任务编排系统规格说明

## 1. 项目概述

**项目名称：** manage_deploy
**类型：** 通用多节点 Docker 任务编排系统（DAG 执行器）

**核心功能：** 用户通过前端创建任务模板和任务实例。每个任务是一个由多个节点组成的 DAG，每个节点在一台远程机器上启动一个 Docker 容器。Task Manager 通过 HTTP API 与部署在各机器上的 Node Agent 通信，实现 DAG 的编排执行。

**目标用户：** DevOps 工程师、运行分布式容器工作负载的数据科学家

---

## 2. 系统架构

### 2.1 组件

1. **Task Manager (backend/)**
   - 技术栈：FastAPI + SQLAlchemy（异步）+ APScheduler + Docker SDK
   - 职责：
     - DAG 编排（拓扑排序执行）
     - 状态机管理
     - 调度（通过 APScheduler 实现 start_time/end_time）
     - 批量操作
     - 幂等性保证
     - 失败回滚

2. **Node Agent (node_agent/)**
   - 技术栈：FastAPI + docker-py
   - 部署在每个 worker 机器上
   - 接收 Task Manager 的 HTTP 命令
   - 控制本地 Docker 容器

3. **Frontend (frontend/)**
   - 技术栈：Vue3 + Element Plus

### 2.2 网络架构

- **管理网络**：Task Manager ↔ Node Agents 使用独立的管理接口
  - 通过 IPv4 管理网络进行 API 调用
  - 每个 Node Agent 注册时携带其管理 IP
  - Manager 通过 `http://{management_ip}:{port}` 调用 agents

- **业务网络**：容器间通过 Docker host 网络模式通信
  - IPv6：2001:db8:1::/64（可配置）
  - IPv4：10.0.1.0/24（可配置）

---

## 3. 功能规格

### 3.1 任务模板

- [x] 任务模板的 CRUD 操作
- [x] 模板包含：name, description, nodes（Docker 配置）, edges（依赖关系）
- [x] 节点配置：image, command, env, volumes, ports, gpu_id, network_mode, restart_policy, health_check
- [x] 边配置：from_node_id → to_node_id（DAG 边）

### 3.2 任务实例

- [x] 从模板创建实例
- [x] 实例状态：pending → scheduled → starting → running → stopping → stopped | failed | expired
- [x] 节点状态：pending → starting → running → ready → stopping → stopped | failed

### 3.3 DAG 执行

- [x] **启动任务**：拓扑排序 - 先启动根节点，等上游节点 ready 后再启动下游节点
- [x] **停止任务**：反向拓扑排序 - 先停止叶子节点，再停止上游节点
- [x] **健康检查**：等待节点状态变为 ready（不仅仅是 running）
- [x] **幂等性**：重复调用 start_task 如果已 running/starting 返回成功；重复调用 stop_task 如果已 stopped/not exists 返回成功
- [x] **失败回滚**：如果某个节点启动失败，停止所有已启动的上游节点，标记任务为 failed

### 3.4 健康检查类型

- [x] `port`：容器端口是否开放
- [x] `http`：HTTP GET 返回 2xx
- [x] `log`：容器日志中是否包含关键字
- [x] `container`：另一个容器是否正在运行

### 3.5 批量操作

- [x] 批量启动多个实例
- [x] 批量停止多个实例
- [x] 批量删除多个实例

### 3.6 定时调度

- [x] 可选的 start_time（APScheduler 在指定时间触发启动）
- [x] 可选的 end_time（APScheduler 在指定时间触发停止）
- [x] 设置 start_time 后状态变为 "scheduled"

### 3.7 Worker 节点管理

- [x] Worker 节点的 CRUD 操作
- [x] 节点信息：hostname, agent_address, management_ip, business_ip

---

## 4. 数据库 schema

### 4.1 表结构

| 表名 | 用途 |
|------|------|
| `nodes` | Worker 机器（hostname, agent_address, management_ip, business_ip） |
| `task_templates` | 可复用的任务定义 |
| `task_template_nodes` | 模板中的节点定义 |
| `task_template_edges` | 模板中的 DAG 边 |
| `task_instances` | 具体的任务运行实例 |
| `task_instance_nodes` | 每个节点的 Docker 参数 |
| `task_instance_edges` | 实例中的 DAG 边 |
| `task_events` | 状态变更、错误、日志 |

### 4.2 状态流转

**任务状态：**
`pending` → `scheduled` → `starting` → `running` → `stopping` → `stopped` | `failed` | `expired`

**节点状态：**
`pending` → `starting` → `running` → `ready` → `stopping` → `stopped` | `failed`

---

## 5. API 端点

### 5.1 Task Manager → Node Agent（Agent HTTP API）

```
POST /containers/{task_id}/{node_id}/start   # 启动容器
POST /containers/{task_id}/{node_id}/stop    # 停止容器
GET  /containers/{task_id}/{node_id}/status  # 获取容器状态
GET  /containers/{task_id}/{node_id}/logs    # 获取容器日志
GET  /health-check/port/{task_id}/{node_id}?port={port}       # 端口检测
GET  /health-check/http/{task_id}/{node_id}?url={url}          # HTTP 检测
GET  /health-check/log/{task_id}/{node_id}?keyword={keyword}   # 日志检测
GET  /health-check/container/{task_id}?container={container_name}  # 容器检测
```

### 5.2 Frontend → Task Manager（Task Manager API）

```
# 模板
POST   /api/templates              创建模板
GET    /api/templates              列表模板
GET    /api/templates/{id}        获取模板详情
PUT    /api/templates/{id}        更新模板
DELETE /api/templates/{id}        删除模板

# 实例
POST   /api/instances              创建实例
GET    /api/instances             列表实例
GET    /api/instances/{id}        获取实例详情
DELETE /api/instances/{id}        删除实例
POST   /api/instances/{id}/start   启动任务
POST   /api/instances/{id}/stop    停止任务
POST   /api/instances/{id}/restart 重启任务
PUT    /api/instances/{id}/schedule 设置定时调度
GET    /api/instances/{id}/events  获取事件日志
GET    /api/instances/{id}/nodes/{node_id}/logs 获取节点日志

# 批量操作
POST   /api/instances/batch/start  批量启动
POST   /api/instances/batch/stop   批量停止
POST   /api/instances/batch/delete 批量删除

# 节点
POST   /api/nodes                  注册节点
GET    /api/nodes                  列表节点
PUT    /api/nodes/{id}            更新节点
DELETE /api/nodes/{id}            删除节点
```

---

## 6. 配置

### 环境变量（backend/.env）

```
DATABASE_URL=mysql+aiomysql://root:Bupt%401234@10.112.204.7:3306/task_manager
AGENT_REQUEST_TIMEOUT=30
HEALTH_CHECK_INTERVAL=5
HEALTH_CHECK_TIMEOUT=30
HEALTH_CHECK_MAX_RETRIES=3
IPV6_NETWORK=2001:db8:1::/64
IPV4_NETWORK=10.0.1.0/24
APSCHEDULER_TIMEZONE=UTC
```

---

## 7. 项目结构

```
manage_deploy/
├── backend/
│   ├── main.py                 # FastAPI 应用入口
│   ├── config.py               # 配置
│   ├── database.py             # SQLAlchemy 异步配置
│   ├── enums.py                # 枚举类型
│   ├── models/                 # SQLAlchemy 模型
│   ├── schemas/                # Pydantic schemas
│   ├── api/                    # 路由处理器
│   ├── services/               # DAG 执行器、健康检查、调度器
│   └── agents/                 # AgentClient
├── node_agent/
│   ├── main.py                 # Agent API
│   ├── docker_handler.py       # Docker SDK 封装
│   ├── health_checks.py        # 健康检查实现
│   └── config.py               # Agent 配置
├── frontend/
│   ├── src/
│   │   ├── views/             # Vue 页面
│   │   ├── stores/             # Pinia 状态管理
│   │   └── api/                # 前端 API 客户端
│   └── package.json
├── docker-compose.yml          # 本地开发环境
├── docker-compose.agents.yml  # Worker agents 部署配置
└── README.md
```

---

## 8. 实现状态

| 组件 | 状态 |
|------|------|
| 后端模型 | ✅ 已完成 |
| 后端 schemas | ✅ 已完成 |
| 后端 API 路由 | ✅ 已完成 |
| DAG 执行器 | ✅ 已完成 |
| 健康检查器 | ✅ 已完成 |
| Agent 客户端 | ✅ 已完成 |
| 调度器 | ✅ 已完成 |
| Node Agent | ✅ 已完成 |
| 前端页面 | ✅ 已完成 |
| 前端 API 客户端 | ✅ 已完成 |
| 前端状态管理 | ✅ 已完成 |
| Docker 配置 | ✅ 已完成 |
| 文档 | ✅ 已完成 |

---

## 9. 环境搭建

### 前置要求
- Python 3.11+
- Node.js 18+
- MySQL 8.0+

### 后端搭建
```bash
cd backend

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -e .

# 创建数据库（如尚未创建）
mysql -h 10.112.204.7 -u root -p'Bupt@1234' -e "CREATE DATABASE IF NOT EXISTS task_manager CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 运行
uvicorn main:app --reload --port 8000
```

### 前端搭建
```bash
cd frontend
npm install
npm run dev
```

---

## 10. 验证

### 测试场景

1. **单元测试**：`pytest` 测试后端服务
2. **API 测试**：使用 curl 测试各端点
3. **DAG 测试**：创建多节点任务，验证拓扑排序执行
4. **回滚测试**：强制失败一个节点，验证上游回滚
5. **幂等性测试**：两次调用 start，验证容器不重复创建
6. **健康检查测试**：启动带健康检查的容器，验证检测功能