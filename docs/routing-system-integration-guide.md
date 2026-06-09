# 外部路由系统数据库扫描对接规范

> 给路由算法同学看的最小对接说明。
> 当前推荐：路由系统直接扫平台数据库读取待路由工单；路由完成后调用平台 HTTP 接口回写结果。

## 接口冻结说明

本文档定义外部路由对接 v1 版本。v1 稳定字段从现在起不再改名、不改变含义：

- `task_orders.id` 等于 `routing_input_dag.job_id` 和 `routing_input_dag.order_id`。
- 路由系统读取 `task_orders.routing_input_dag`，其中逻辑节点固定为 `source`、`compute`、`sink`。
- 路由系统回写 `POST /api/routing-orders/{order_id}/result`。
- 回写 `placements` 必须包含 `source`、`compute`、`sink` 三项。
- GPU 业务的 `compute` placement 必须包含 `gpu_device`。
- `metadata` 是通用扩展字典，可新增字段，但平台不会依赖其中某个字段完成部署。

后续如果要扩展，只允许增加可选字段或新增 v2 接口；不得破坏以上 v1 字段，避免路由系统反复改适配代码。

---

## 1. 最小联调流程

1. 平台 `/benchmark` 创建 3 个压测工单。
2. 路由系统扫描 `task_orders.routing_status='pending'`。
3. 路由系统用原子 update 抢占一条工单，把它改成 `computing`。
4. 路由系统解析该工单的 `routing_input_dag` JSON。
5. 路由系统选择 compute 节点和 GPU。
6. 路由系统调用 `POST /api/routing-orders/{order_id}/result` 回写。
7. 平台自动物化实例，前端刷新后看到 `routing_status=completed`。
8. 前端点击“自动执行”，查看节点/GPU 分配、业务结果和成功率。

跑通 3 个后，再跑 30 个正式测评任务。

---

## 2. 分工边界

平台负责：

- 创建工单，并写入 `task_orders.routing_input_dag`。
- 接收路由结果，物化 TaskInstance。
- 部署、启动、停止容器。
- 采集指标并计算业务目标成功率。

路由系统负责：

- 读取 `task_orders`、`nodes`、`node_baselines`。
- 选择 source -> compute -> sink 路径中的 compute 节点和 GPU。
- 回写 placements 和 metadata。

---

## 3. 路由系统需要读的表

### 3.1 `task_orders`

待路由工单表。核心字段：

| 字段 | 用途 |
|------|------|
| `id` | 工单 ID；等于 `routing_input_dag.job_id/order_id`。 |
| `routing_status` | `pending`、`computing`、`completed`、`failed`。 |
| `routing_input_dag` | 路由系统要解析的 JSON。 |
| `source_name` / `destination_name` | 用户输入的源节点和目的节点。 |
| `business_start_time` / `business_end_time` | 业务时间窗口。 |
| `runtime_config` | 含 `benchmark.run_id`、`business_task.task_type`。 |
| `materialized_instance_id` | 非空通常表示已经物化。 |
| `deleted_at` | 非空必须跳过。 |
| `updated_at` | 可用于判断 `computing` 是否超时。 |

查询 pending 工单：

```sql
select
  id,
  routing_status,
  routing_input_dag,
  source_name,
  destination_name,
  business_start_time,
  business_end_time,
  runtime_config
from task_orders
where deleted_at is null
  and routing_status = 'pending'
order by created_at asc
limit 100;
```

### 3.2 `nodes`

平台节点表。核心字段：

| 字段 | 用途 |
|------|------|
| `id` | 节点 UUID。 |
| `hostname` | 推荐作为回写 `worker_host` 的节点名。 |
| `display_name` | 展示名，可用于匹配用户输入。 |
| `business_ip` / `business_ipv6` | 数据面地址。 |
| `node_kind` | `worker`、`terminal`、`both`、`admin` 等。 |
| `is_schedulable` | 是否可部署业务容器。 |
| `is_routable` | 是否参与路由。 |
| `deleted_at` | 非空必须跳过。 |

### 3.3 `node_baselines`

节点 benchmark 基线能力表，可以理解为 `nodes` 的性能属性扩展表。

| 字段 | 用途 |
|------|------|
| `node_id` | 关联 `nodes.id`。 |
| `task_type` | 业务类型，如 `high_throughput_matmul`、`low_latency_video_pipeline`。 |
| `metric_key` | 指标名，如 `effective_gflops`、`frame_latency_p90_ms`。 |
| `baseline_value` | 该节点该业务的历史基准能力。 |
| `operator` / `unit` | 判定方向和单位。 |
| `raw_values` | 原始多次测试值，可判断稳定性。 |

推荐联表读取节点和基线：

```sql
select
  n.id as node_id,
  n.hostname,
  n.display_name,
  n.node_kind,
  n.is_schedulable,
  n.is_routable,
  b.task_type,
  b.metric_key,
  b.baseline_value,
  b.operator,
  b.unit,
  b.raw_values
from nodes n
left join node_baselines b
  on b.node_id = n.id
 and b.task_type = :task_type
where n.deleted_at is null
  and n.is_routable = 1;
```

使用建议：

- 矩阵计算：`task_type='high_throughput_matmul'`，看 `effective_gflops`，越高越好。
- 视频推理：`task_type='low_latency_video_pipeline'`，看 `frame_latency_p90_ms`，越低越好。
- 缺少对应 baseline 的节点，建议降低优先级或不选。

---

## 4. 并发控制，避免重复和丢任务

### 4.1 抢占 pending 工单

不要只 `select pending` 后直接计算。应先做原子 update：

```sql
update task_orders
set routing_status = 'computing',
    updated_at = current_timestamp
where id = :order_id
  and routing_status = 'pending'
  and deleted_at is null;
```

判断：

- 影响行数 = 1：抢占成功，可以计算。
- 影响行数 = 0：已被其他进程处理，跳过。

### 4.2 防止 computing 任务丢失

如果路由进程崩溃，工单可能卡在 `computing`。建议每分钟巡检一次，把超时任务恢复为 `pending`：

```sql
update task_orders
set routing_status = 'pending',
    updated_at = current_timestamp,
    error_message = 'routing claim timeout, reset to pending'
where routing_status = 'computing'
  and deleted_at is null
  and updated_at < current_timestamp - interval 10 minute;
```

如果数据库是 SQLite，时间表达式按 SQLite 写法改。

### 4.3 路由失败

确定无法路由时可写失败：

```sql
update task_orders
set routing_status = 'failed',
    error_message = :reason,
    updated_at = current_timestamp
where id = :order_id
  and routing_status = 'computing';
```

如果只是临时资源不足，建议保持 pending 或超时后恢复 pending，不要直接 failed。

---

## 5. `routing_input_dag` JSON

简化示例：

```json
{
  "job_id": "order-uuid-001",
  "order_id": "order-uuid-001",
  "job_name": "视频AI推理",
  "source_name": "node-a",
  "destination_name": "node-c",
  "policy_type": "LATENCY_CONSTRAINED",
  "business_start_ts_ms": 1777341600000,
  "business_end_ts_ms": 1777345200000,
  "nodes": [
    {
      "node_id": "source",
      "node_type": "endpoint",
      "fixed_node_name": "node-a",
      "resources": {"cpu_units": 2, "mem_mb": 512, "disk_mb": 512, "gpu_units": 0}
    },
    {
      "node_id": "compute",
      "node_type": "compute",
      "resources": {"cpu_units": 10, "mem_mb": 2048, "disk_mb": 1024, "gpu_units": 1}
    },
    {
      "node_id": "sink",
      "node_type": "endpoint",
      "fixed_node_name": "node-c",
      "resources": {"cpu_units": 2, "mem_mb": 512, "disk_mb": 512, "gpu_units": 0}
    }
  ],
  "edges": [
    {"from": "source", "to": "compute", "data_mb": 20, "bandwidth_mbps": 20},
    {"from": "compute", "to": "sink", "data_mb": 20, "bandwidth_mbps": 20}
  ]
}
```

关键点：

- `job_id/order_id` 必须等于 `task_orders.id`。
- `source` 和 `sink` 是固定端点，真实节点名看 `fixed_node_name`。
- `compute` 是路由系统要选择的算力节点。
- `node_id` 是逻辑节点 ID，不是物理节点 ID。
- 源节点和目的节点可以是计算节点，只是在本工单里承担 endpoint 角色。

---

## 6. 回写路由结果

路由完成后调用平台 HTTP 接口：

```http
POST /api/routing-orders/{order_id}/result
X-Service-Token: <service-token>
Content-Type: application/json
```

请求体：

```json
{
  "strategy": "resource_guarantee",
  "selected_strategy": "GPU_EXCLUSIVE_RESOURCE_FIT",
  "external_routing_id": "route-20260609-0001",
  "placements": [
    {"node_id": "source", "worker_host": "node-a"},
    {"node_id": "compute", "worker_host": "compute-3", "gpu_device": "0"},
    {"node_id": "sink", "worker_host": "node-c"}
  ],
  "metadata": {
    "path": ["node-a", "compute-3", "node-c"],
    "selected_reason": "compute-3 GPU 0 is available",
    "algorithm_version": "router-v1"
  }
}
```

要求：

- `source.worker_host` 等于 source 的 `fixed_node_name`。
- `sink.worker_host` 等于 sink 的 `fixed_node_name`。
- `compute.worker_host/gpu_device` 由路由系统选择。
- GPU 业务必须回写 `gpu_device`。
- `metadata` 可放路径、解释、租金、算法版本、trace id。
- 返回 `409` 表示已被处理，视为幂等冲突，跳过即可。

成功响应：

```json
{
  "status": "ok",
  "order_id": "order-uuid-001",
  "routing_status": "completed",
  "instance_id": "task-instance-uuid-001"
}
```

---

## 7. GPU 独占规则

验收业务默认 GPU 独占：

- 一张物理 GPU 同一时刻只能分配给一个运行任务。
- 即使显存没占满，也不能把同一 GPU 分给多个并发任务。
- 这是为了避免矩阵计算吞吐和视频推理时延波动，影响 90% 业务目标成功率。

第一阶段可按以下方式判断占用：

- 查看未结束工单的 `runtime_config.routing_result.placements`。
- 找到 compute placement 的 `worker_host + gpu_device`。
- 同一 `worker_host + gpu_device` 不再分配给新任务。

---

## 8. 当前系统是否可以直接对接

可以先对接，小规模联调条件已经具备：

- 前端已有 `mock演示路由 | 外部路由系统` 模式。
- `task_orders` 已保存 `routing_input_dag`。
- 平台已有路由结果回写接口。
- 回写后会自动物化实例。
- 工单详情能展示节点/GPU 分配和业务结果。
- 矩阵计算、视频推理已有可用于路由参考的 `node_baselines`。

建议第一轮只做 3 个工单联调，确认数据库扫描、claim、回写、前端刷新、自动执行都通，再跑 30 个正式测评工单。

当前仍需注意：

- GPU 占用目前没有独立锁表，先按工单路由结果和运行状态判断；后续可升级为独立 GPU 占用表。
- 路由失败状态可先由路由系统直接更新 `task_orders.routing_status='failed'` 和 `error_message`。
- 真实拓扑机器变更后，要先确认 `nodes.hostname`、`node_baselines`、Node Agent 状态都是最新的。

---

## 9. 建议部署联调方式

推荐部署在管理节点。

原因：

- 平台后端、数据库、前端入口都在管理节点或管理节点可直接访问的位置。
- 路由系统可以直接访问数据库，不需要把数据库暴露到业务节点。
- 路由系统回写平台后端走本机或内网地址，延迟低、故障点少。
- 后续演示时只需要确认管理节点上的平台和路由服务都在运行。

建议拓扑：

```text
管理节点
  ├─ 平台后端 Task Manager: 8181
  ├─ 平台前端: 8182
  ├─ 数据库: MySQL/SQLite，按实际部署
  └─ 外部路由系统后端: 例如 8190

业务节点
  └─ Node Agent + Docker Worker
```

路由系统部署要求：

| 项目 | 建议 |
|------|------|
| 部署位置 | 管理节点。 |
| 服务端口 | 建议 `8190`，仅用于 `/health`、状态查看或调试；平台当前不依赖主动调用该端口。 |
| 数据库权限 | 至少需要读 `task_orders`、`nodes`、`node_baselines`；需要更新 `task_orders.routing_status/error_message/updated_at`。 |
| 平台回写地址 | 推荐使用管理节点本机地址，例如 `http://127.0.0.1:8181`；如果容器网络不通，则使用管理节点内网地址。 |
| 回写鉴权 | 调用 `POST /api/routing-orders/{order_id}/result` 时带 `X-Service-Token`。 |
| 运行方式 | Docker Compose、systemd 或普通后台进程都可以；验收阶段优先选最稳定、最容易重启的方式。 |
| 轮询间隔 | 建议 3-10 秒扫描一次 pending 工单。 |
| claim 超时 | 建议 10 分钟未完成则恢复 pending。 |
| 日志 | 至少记录 order_id、claim 结果、选择节点/GPU、回写状态、失败原因。 |

推荐环境变量：

```bash
ROUTER_DB_URL=<平台数据库连接串>
PLATFORM_API_BASE=http://127.0.0.1:8181
PLATFORM_SERVICE_TOKEN=<X-Service-Token>
ROUTER_POLL_INTERVAL_SEC=5
ROUTER_CLAIM_TIMEOUT_SEC=600
ROUTER_PORT=8190
```

最小联调启动后，路由系统应循环执行：

```text
扫描 pending 工单
 -> 原子 claim 为 computing
 -> 读取 routing_input_dag
 -> 读取 nodes + node_baselines
 -> 选择 compute 节点/GPU
 -> 调平台回写接口
 -> 记录日志
```

如果路由同学已经有自己的后端服务，可以直接部署到管理节点某个端口，例如 `8190`。当前平台不要求调用他们的接口；只要求他们的服务能扫描数据库并调用平台回写接口。

---

## 10. 给路由同学 AI 的实现提示词

可以把下面这段直接交给路由同学或他们使用的 AI：

```text
你要实现一个外部路由系统的最小联调版本，对接平台数据库和平台回写接口。

目标：
1. 从平台数据库 task_orders 表扫描 routing_status='pending' 且 deleted_at is null 的工单。
2. 用原子 update 抢占工单：把 routing_status 从 pending 改成 computing。只有影响行数为 1 才能继续处理。
3. 读取并解析 task_orders.routing_input_dag JSON。
4. 读取 nodes 表和 node_baselines 表，选择 compute 节点和 gpu_device。
5. source/sink 使用 routing_input_dag.nodes 中的 fixed_node_name，不要随意改。
6. compute 必须选择 is_routable=1、is_schedulable=1、且有对应业务 baseline 的节点。
7. GPU 任务必须独占 GPU，同一 worker_host + gpu_device 不能分配给多个未结束任务。
8. 计算完成后调用平台 HTTP 接口 POST /api/routing-orders/{order_id}/result 回写 placements 和 metadata。
9. 如果路由进程崩溃，不能丢任务：需要定期把超时 computing 工单恢复为 pending。
10. 先只实现能跑通 3 个 benchmark 工单的小规模联调版本，不要过度设计。

必须使用的数据库表：
- task_orders：读取 pending 工单、claim 工单、必要时写 failed。
- nodes：读取可路由节点。
- node_baselines：读取每个节点在当前 task_type 下的历史基线能力。

必须回写的 placements 形态：
{
  "placements": [
    {"node_id": "source", "worker_host": "<source fixed_node_name>"},
    {"node_id": "compute", "worker_host": "<chosen node hostname>", "gpu_device": "0"},
    {"node_id": "sink", "worker_host": "<sink fixed_node_name>"}
  ],
  "metadata": {
    "path": ["<source>", "<compute>", "<sink>"],
    "selected_reason": "说明为什么选择该节点和 GPU",
    "algorithm_version": "router-minimal-v1"
  }
}

完成标准：
- 3 个 pending 工单都能被领取、计算、回写。
- 平台前端刷新后看到 routing_status=completed。
- 工单详情能看到 source/compute/sink 和 compute GPU 编号。
- 点击自动执行后任务能启动并完成业务指标评估。
- 不允许同一 GPU 同时分配给多个未结束任务。
```

---

## 11. 路由同学交付检查清单

交接时需要一并提供给路由同学：

- 平台数据库连接方式：host、port、database、username、password 或只读/可更新账号。
- 平台后端地址：例如 `http://<admin-server>:8181`。
- `X-Service-Token`：用于调用回写接口。
- 当前可用节点清单是否已同步到 `nodes` 表。
- 当前节点基线是否已写入 `node_baselines`。
- 管理节点部署目录、运行方式和路由服务端口。

- [ ] 能连接平台数据库。
- [ ] 能查询 `task_orders.routing_status='pending'` 的工单。
- [ ] claim 使用原子 update，影响行数为 0 时会跳过。
- [ ] 能解析 `routing_input_dag` 的 source、compute、sink、resources、edges。
- [ ] 能读取 `nodes` 和 `node_baselines`。
- [ ] 能按 `task_type` 找到节点 baseline。
- [ ] 能避免同一 GPU 被多个未结束任务占用。
- [ ] 能调用 `POST /api/routing-orders/{order_id}/result`。
- [ ] 回写后平台工单变成 `routing_status=completed`。
- [ ] 路由进程异常退出后，超时 `computing` 工单能恢复为 `pending`。
