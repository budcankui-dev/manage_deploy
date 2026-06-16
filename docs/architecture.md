# 系统架构

`manage_deploy` 是一个多节点 Docker DAG 编排系统。当前产品主线是在通用编排能力之上，演示两类业务闭环：对话/业务任务 -> 路由放置 -> DAG 部署 -> 指标上报 -> 业务目标评估。

## 组件

| 组件 | 路径 | 职责 |
|------|------|------|
| Task Manager | `backend/` | FastAPI 后端，负责模板、实例、DAG 编排、调度、工单、业务评估 |
| Node Agent | `node_agent/` | 部署在 worker 机器上，通过 Docker SDK 控制本地容器 |
| Frontend | `frontend/` | Vue3 + Element Plus 管理端和意图对话入口 |
| Workers | `workers/` | 业务容器代码，当前维护矩阵乘法计算任务和视频AI推理任务 |

## 核心概念

- **Node**：一台可部署 worker 机器，包含管理地址和业务地址。
- **TaskTemplate**：DAG 蓝图，包含模板节点、边、镜像、命令、端口、健康检查和资源限制。
- **TaskInstance**：模板的一次具体运行，实例节点会绑定到实际 Node。
- **TaskOrder**：业务层工单，关联业务输入、路由结果和物化后的实例。
- **BusinessObjectiveEvaluation**：业务目标评估结果。当前统一口径见 `docs/business-objective-success-rate-design.md`，按业务类型采集过程性指标并与节点历史基准比较。
- **Conversation / IntentDraft / RoutingRequest**：普通用户从自然语言到部署请求的前置工作流。
- **Endpoint Deployment Policy**：source / sink 是否由平台部署容器由工单 `runtime_config.platform_deployment.deployable_roles` 决定。测评模式可部署 source / compute / sink 三类容器；真实用户接入模式默认只部署 compute，source / sink 是外部端点。详见 `docs/端点部署与用户接入模型.md`。

## DAG 生命周期

任务状态：

```text
pending -> scheduled -> starting -> running -> stopping -> stopped | failed | expired
```

节点状态：

```text
pending -> starting -> running -> ready -> stopping -> stopped | failed
```

启动时，Task Manager 按拓扑顺序启动根节点，等待上游节点 `ready` 后启动下游节点。停止时按反向拓扑顺序执行。节点启动失败时，已创建容器应被 remove，而不是只 stop 后留下 exited 容器。

## 编排 DAG 与业务数据流

DAG 边在平台层主要表达容器生命周期依赖：谁先启动、谁等待上游 `ready`、停止时如何反向清理。它保证部署安全和回滚一致性，但不是产品要展示的核心能力。

业务演示要突出的是外部路由算法的选路效果，因此测试业务遵循 **随路计算** 原则：数据从 source 端点产生，经过一个或多个中间业务节点处理，再到 sink 端点汇总或接收结果。常用最小形态是 source -> compute -> sink。外部路由输出的 placements 决定核心计算角色落在哪些 Node 上，业务数据实际沿 `PEER_*` 或 `network_bindings` 返回的业务面地址流转。

因此：

- 容器启动顺序可以服务于健康检查和依赖安全，不应被当成业务价值本身。
- 数据流转顺序必须清晰体现路由路径，即 source -> 中间业务节点 -> sink。
- 逻辑 source/sink 可以是平台可控测试容器，也可以是真实用户外部接入端点；是否部署容器由当前工单的部署策略决定。
- 测试业务要避免“所有节点各自本地完成后汇总”的形态，因为那不能证明外部路由选路。

## 网络模型

控制面：

- Task Manager、数据库、MinIO、Node Agent API 走管理网络。
- 本地开发常用 `127.0.0.1:8000` / `127.0.0.1:8001`。

业务面：

- 业务容器使用 host 网络模式。
- 业务节点之间必须通过网络通信传递业务数据。
- 模板节点必须声明 `port_defs` 或 `ports`，让平台生成端口映射和 `PEER_*` 环境变量。
- 不允许通过共享卷、宿主机文件或对象存储中转业务数据。MinIO 只用于结果归档。

开发默认：

- `PREFER_BUSINESS_IPV6=false`
- `business_ip` 与管理面同源，通常为 `127.0.0.1`

验收/生产：

- 节点配置 `business_ipv6`
- `PREFER_BUSINESS_IPV6=true`
- `BACKEND_PORT` 必须与实际后端端口一致，例如管理节点以 `8181` 暴露时设为 `8181`，否则 worker 回写指标会打到错误端口
- 业务 worker 的 HTTP 服务需要支持 IPv6/IPv4 双栈监听；仅绑定 `0.0.0.0` 不能证明 IPv6 数据面可用
- 通过真实业务 E2E 验证 `PEER_*_URL=http://[IPv6]:port`、`TASK_PEERS_JSON.business_address` 和 sink 指标回写，而不只看容器 ready 状态

## 当前演示业务

| 业务 | `task_type` | 模态 | 指标 | 说明 |
|------|-------------|------|------|------|
| 矩阵乘法计算任务 | `high_throughput_matmul` | 高通量计算模态 | `effective_gflops` | source / compute / sink 使用同一镜像，通过 HTTP 传递 job/result，sink 上报有效计算吞吐量。详见 `docs/scientific-matmul-demo.md`。 |
| 视频AI推理任务 | `low_latency_video_pipeline` | 低时延转发模态 | `frame_latency_p90_ms` | source 读取固定测试视频抽帧，compute 运行 YOLO 推理并生成检测框，sink 上报 P90 帧时延和带框预览图。 |

两类业务都采用 source -> compute -> sink 的随路计算数据流。用户端 `/intent-chat` 支持从自然语言解析两类任务，确认后创建统一工单 ID 并生成提交给外部路由系统的 DAG JSON。外部路由未接入时，可在系统设置中启用平台内置自动分配流程，用于验证工单创建、实例物化和业务指标上报闭环。

## 主要 API

部署编排：

- `POST /api/templates`
- `POST /api/instances`
- `POST /api/instances/{id}/start`
- `POST /api/instances/{id}/stop`
- `POST /api/instances/preflight`
- `POST /api/instances/{id}/metrics`
- `POST /api/nodes`

业务任务：

- `POST /api/business-tasks`
- `GET /api/business-tasks`
- `GET /api/business-tasks/summary`
- `GET /api/orders/{id}`

意图与路由：

- `POST /api/conversations`
- `POST /api/conversations/{id}/messages`
- `POST /api/conversations/{id}/confirm-intent`
- `POST /api/conversations/{id}/demo-route`
- `GET /api/routing-orders?status=pending`
- `PATCH /api/routing-orders/{id}/claim`
- `POST /api/routing-orders/{id}/result`
- `POST /api/routing-orders/{id}/network-ready`
- `POST /api/conversations/{id}/submit`

## 数据表分组

基础设施：

- `nodes`
- `task_templates`
- `task_template_nodes`
- `task_template_edges`
- `task_instances`
- `task_instance_nodes`
- `task_instance_edges`
- `task_events`

业务闭环：

- `task_orders`
- `task_metrics`
- `task_result_objects`
- `business_template_catalog`
- `business_objective_evaluations`

用户和意图：

- `users`
- `conversations`
- `conversation_messages`
- `intent_drafts`
- `routing_requests`

## 设计约束

- 模板和实例的运行时字段要保持可预检：镜像、命令、端口、资源、健康检查都应能在启动前检查。
- 端口冲突必须有两层防护：Manager 侧运行中实例检查，Node Agent 侧 Docker/宿主机检查。
- 业务结果归档和业务数据传递是两个概念：MinIO 可保存结果，但不能作为 source/compute/sink 之间的数据总线。
- 演示业务必须体现随路计算：数据沿外部路由选择出的节点路径流动，而不是只展示容器拓扑启动成功。
- 演示脚本入口统一为 `backend/scripts/rebuild_matmul_template.py`。它通过 `DATABASE_URL` 或 `MYSQL_*` 环境变量解析连接信息，直接查 MySQL 的 `nodes` 表绑定真实 compute-1/2/3 UUID；旧的 `setup_matmul_demo.py` / `seed_demo_data.py` 已停用，不要再写入新文档。
