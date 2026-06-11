# 外部路由系统对接说明

正式交接材料只保留两份：

- 讲解版 PPT：[外部路由系统对接讲解.pptx](presentations/routing-integration/外部路由系统对接讲解.pptx)
- 接口说明本文档：[routing-system-integration-guide.md](routing-system-integration-guide.md)

本文档分两部分：

- **第一部分：路由同学只需要看这里**。照这一部分实现即可完成最小联调。
- **第二部分：平台背景说明**。用于理解本系统内部设计，可选阅读。

---

# 第一部分：路由同学只需要看这里

## 1. 你们要做什么

实现一个外部路由服务，部署在管理节点或能访问管理节点的平台后端和 MySQL 的机器上，循环执行：

```text
读取待路由工单
 -> claim 工单，防止重复路由
 -> 解析 routing_input_dag
 -> 读取 nodes / node_baselines / 自己维护的资源占用表
 -> 选择 compute 节点和 GPU
 -> 调平台接口回写路由结果
 -> 扫描平台 release 事件，把已释放 GPU 加回自己的资源表
```

路由系统只负责 **选择算力节点、GPU、路径和算法侧解释信息**。是否给某个 DAG 节点部署容器，是平台内部决策，路由系统不要关心。

## 2. v1 冻结约定

这些字段和语义后续不再改，路由同学可以按这个实现：

| 项 | 约定 |
|----|------|
| 统一任务 ID | `task_orders.id = routing_input_dag.job_id = routing_input_dag.order_id = order_id` |
| 输入 DAG | 从 `task_orders.routing_input_dag` 或 `GET /api/routing-orders` 响应中读取 |
| 回写接口 | `POST /api/routing-orders/{order_id}/result` |
| 逻辑节点 ID | `routing_input_dag.nodes[].node_id`，常见为 `source`、`compute`、`sink` |
| 真实端点 | `source/sink` 的真实节点名看 `fixed_node_name` |
| 算力选择 | 路由系统只需要回写 `compute.worker_host` 和可选 `compute.gpu_device` |
| GPU 独占 | 同一 `worker_host + gpu_device` 同一时刻只能分配给一个未释放任务 |
| 扩展信息 | 算法版本、路径、成本、租金、解释等统一放到 `metadata` 字典 |

## 3. 推荐部署方式

推荐把外部路由服务部署在管理节点：

```text
管理节点
  ├─ 平台后端 Task Manager: 8181
  ├─ 平台前端: 8182
  ├─ MySQL
  └─ 外部路由系统后端: 建议 8190

业务节点
  └─ Node Agent + Docker Worker
```

建议环境变量：

```bash
PLATFORM_API_BASE=http://127.0.0.1:8181
ROUTER_DB_URL=<平台 MySQL 连接串>
ROUTER_POLL_INTERVAL_SEC=5
ROUTER_PORT=8190
ROUTER_HTTP_TIMEOUT_SEC=120
```

## 4. 平台已提供的 HTTP 接口

这些接口是验收演示用内部接口，当前不需要 token 或签名。路由服务只要能访问平台后端地址即可。

建议路由系统把 HTTP 超时设置为 **不少于 60 秒，推荐 120 秒**。`/result` 会物化实例并预分配端口，偶尔比普通查询慢；如果请求超时，先查询该工单状态，看到已进入 `network_binding_ready` 或 `completed` 就不要重复扣资源。

| 动作 | 方法与路径 | 说明 |
|------|------------|------|
| 获取待路由工单 | `GET /api/routing-orders?status=pending&limit=100` | 平台返回 pending 工单和 DAG。也可以直接读 MySQL，但推荐先用接口联调。 |
| 领取工单 | `PATCH /api/routing-orders/{order_id}/claim` | 平台把 `pending -> computing`，并发时只有一个路由进程能成功。 |
| 回写路由结果 | `POST /api/routing-orders/{order_id}/result` | 平台保存结果、校验 GPU 冲突、物化部署实例，并返回实际端口绑定 `network_bindings`。 |
| 确认网络就绪 | `POST /api/routing-orders/{order_id}/network-ready` | 路由系统下发流表/QoS 后调用，平台才启动或注册启动计划。 |
| 临时资源不足 | `PATCH /api/routing-orders/{order_id}/requeue` | 把 `computing -> pending`，稍后重试，不要丢工单。 |
| 确定无法路由 | `PATCH /api/routing-orders/{order_id}/fail` | 把工单标记为 `failed`，需要写清失败原因。 |
| 查询释放事件 | `GET /api/routing-resource-events?event_type=release&unacked=true&limit=100` | 平台告诉路由系统哪些 GPU 已释放。 |
| 确认释放事件 | `POST /api/routing-resource-events/ack` | 路由系统把资源加回后，确认这些事件已处理。 |

## 5. 最小主循环

伪代码：

```python
while True:
    releases = GET("/api/routing-resource-events?event_type=release&unacked=true")
    for event in releases:
        router_resource_pool.release(
            host=event["node_hostname"],
            resource_kind=event["resource_kind"],
            resource_id=event["resource_id"],
            amount=event["amount"],
        )
    POST("/api/routing-resource-events/ack", {"ids": [event["id"] for event in releases]})

    orders = GET("/api/routing-orders?status=pending&limit=100")
    for order in orders:
        claimed = PATCH(f"/api/routing-orders/{order['order_id']}/claim")
        if claimed.status_code == 409:
            continue

        claimed_order = claimed.json()
        order_id = claimed_order["order_id"]
        dag = claimed_order["routing_input_dag"]
        placement = choose_compute_node_and_gpu(dag, nodes, node_baselines, router_resource_pool)

        if placement.temporarily_unavailable:
            PATCH(f"/api/routing-orders/{order_id}/requeue", {"reason": "GPU slots temporarily full"})
            continue

        if placement.impossible:
            PATCH(f"/api/routing-orders/{order_id}/fail", {"reason": placement.reason})
            continue

        router_resource_pool.reserve(placement.worker_host, "gpu", placement.gpu_device)
        result = POST(f"/api/routing-orders/{order_id}/result", placement.to_payload())
        if result.status_code == 409:
            router_resource_pool.release(placement.worker_host, "gpu", placement.gpu_device)
            PATCH(f"/api/routing-orders/{order_id}/requeue", {"reason": result.text})
            continue

        bindings = result.json()["network_bindings"]
        install_flow_rules(bindings)
        POST(
            f"/api/routing-orders/{order_id}/network-ready",
            {"metadata": {"flow_rule_count": len(bindings)}},
        )
```

## 6. 需要读取的 MySQL 表

第一阶段只需要这些表。平台对接只使用 MySQL。

### 6.1 `task_orders`

工单表。推荐通过 HTTP 获取和 claim，直接读 MySQL 也可以辅助排查。

| 字段 | 用途 |
|------|------|
| `id` | 统一工单 ID，也是 `job_id/order_id`。 |
| `routing_status` | `pending`、`computing`、`network_binding_ready`、`completed`、`failed`。 |
| `routing_input_dag` | 路由算法输入 DAG。 |
| `source_name` / `destination_name` | 用户输入的源节点和目的节点。 |
| `business_start_time` / `business_end_time` | 业务时间窗口。 |
| `runtime_config` | 业务类型、benchmark 轮次、路由结果等扩展信息。 |
| `materialized_instance_id` | 平台物化后的任务实例 ID。 |
| `deleted_at` | 非空表示已逻辑删除，必须跳过。 |

### 6.2 `nodes`

节点表。路由时只考虑未删除且可路由的节点。

| 字段 | 用途 |
|------|------|
| `id` | 平台内部节点 ID。 |
| `hostname` | 回写 `worker_host` 时使用这个值。 |
| `display_name` | 展示名，可用于辅助匹配。 |
| `business_ip` / `business_ipv6` | 数据面地址。 |
| `node_kind` | `worker`、`terminal`、`both`、`admin` 等。 |
| `is_schedulable` | 是否可部署业务容器。 |
| `is_routable` | 是否参与路由。 |
| `deleted_at` | 非空必须跳过。 |

### 6.3 `node_baselines`

节点基线表，存放不同业务在不同节点上的历史指标，供路由算法参考。

| 字段 | 用途 |
|------|------|
| `node_id` | 关联 `nodes.id`。 |
| `task_type` | 业务类型，如 `high_throughput_matmul`、`low_latency_video_pipeline`。 |
| `metric_key` | 指标名，如 `effective_gflops`、`frame_latency_p90_ms`。 |
| `baseline_value` | 节点历史基准值。 |
| `operator` / `unit` | 判定方向和单位。 |
| `raw_values` | 原始测试值，可辅助判断稳定性。 |

使用建议：

| 业务 | `task_type` | 推荐指标 | 趋势 |
|------|-------------|----------|------|
| 矩阵乘法计算 | `high_throughput_matmul` | `effective_gflops` | 越高越好 |
| 视频 AI 推理 | `low_latency_video_pipeline` | `frame_latency_p90_ms` | 越低越好 |

### 6.4 `routing_resource_events`

资源释放事件表。平台在任务停止、失败、删除、清理实例后写入 release 事件，路由系统处理后调用 ack。

| 字段 | 用途 |
|------|------|
| `id` | 自增事件 ID。 |
| `event_type` | 第一阶段只用 `release`。 |
| `order_id` / `job_id` | 统一工单 ID。 |
| `benchmark_run_id` | 验收轮次，可选。 |
| `task_type` | 业务类型。 |
| `node_hostname` | 被释放资源所在节点。 |
| `resource_kind` | 第一阶段主要是 `gpu`。 |
| `resource_id` | GPU 编号，如 `0`。 |
| `amount` | 释放数量，GPU 默认 `1`。 |
| `reason` | `completed`、`cleanup_instance`、`delete_order`、`failed` 等。 |
| `router_ack_at` | 路由系统确认处理时间。 |

## 7. 输入 DAG 格式

三节点常规业务示例：

```json
{
  "job_id": "order-uuid-001",
  "order_id": "order-uuid-001",
  "job_name": "视频AI推理",
  "source_name": "terminal-a",
  "destination_name": "terminal-b",
  "policy_type": "LATENCY_CONSTRAINED",
  "business_start_ts_ms": 1777341600000,
  "business_end_ts_ms": 1777345200000,
  "nodes": [
    {
      "node_id": "source",
      "role": "source",
      "node_type": "endpoint",
      "fixed_node_name": "terminal-a",
      "network": {
        "port_requirements": [
          {"name": "source", "protocol": "tcp", "auto": true, "range": [18800, 19100], "direction": "inbound"}
        ]
      },
      "resources": {"cpu_units": 2, "mem_mb": 512, "disk_mb": 512, "gpu_units": 0}
    },
    {
      "node_id": "compute",
      "role": "compute",
      "node_type": "compute",
      "network": {
        "port_requirements": [
          {"name": "compute", "protocol": "tcp", "auto": true, "range": [18800, 19100], "direction": "inbound"}
        ]
      },
      "resources": {"cpu_units": 10, "mem_mb": 2048, "disk_mb": 1024, "gpu_units": 1}
    },
    {
      "node_id": "sink",
      "role": "sink",
      "node_type": "endpoint",
      "fixed_node_name": "terminal-b",
      "network": {
        "port_requirements": [
          {"name": "sink", "protocol": "tcp", "auto": true, "range": [18800, 19100], "direction": "inbound"}
        ]
      },
      "resources": {"cpu_units": 2, "mem_mb": 512, "disk_mb": 512, "gpu_units": 0}
    }
  ],
  "edges": [
    {
      "from": "source",
      "to": "compute",
      "data_mb": 20,
      "bandwidth_mbps": 20,
      "flow": {
        "flow_id": "order-uuid-001:source->compute",
        "protocol": "tcp",
        "dst_port_ref": "compute.compute",
        "traffic_class": "low_latency",
        "priority": 90
      }
    },
    {
      "from": "compute",
      "to": "sink",
      "data_mb": 20,
      "bandwidth_mbps": 20,
      "flow": {
        "flow_id": "order-uuid-001:compute->sink",
        "protocol": "tcp",
        "dst_port_ref": "sink.sink",
        "traffic_class": "low_latency",
        "priority": 90
      }
    }
  ]
}
```

关键理解：

- `node_id` 是 DAG 逻辑角色，不是物理节点名。
- 用户输入的源节点和目的节点写在 `fixed_node_name`。
- 源节点和目的节点可以是物理计算节点；在本 DAG 中它们仍然只是 endpoint 角色。
- `compute` 是路由系统需要选择真实部署节点的位置。
- `edges[].bandwidth_mbps` 是带宽需求估计，可作为选路参考。
- `nodes[].network.port_requirements` 是逻辑端口需求，路由系统不要提前分配真实端口。
- `edges[].flow` 用于识别业务流、优先级和目标端口引用；真实目标 IP/端口在 `/result` 响应的 `network_bindings` 中返回。

## 8. 支持的 DAG 形态

### 8.1 `source -> compute -> sink`

默认演示业务。路由系统选择 `compute` 的 `worker_host/gpu_device`，路径可放到 `metadata.path`。

### 8.2 `source -> sink`

两个节点都是终端，只需要计算路径，不需要部署业务容器。

回写时 `placements` 可以为空：

```json
{
  "strategy": "resource_guarantee",
  "placements": [],
  "metadata": {
    "path": ["terminal-a", "terminal-b"],
    "selected_reason": "terminal path is reachable"
  }
}
```

### 8.3 `source -> compute`

源节点是终端，目的侧承担计算角色。路由系统只需要回写 compute：

```json
{
  "strategy": "resource_guarantee",
  "placements": [
    {"node_id": "compute", "worker_host": "compute-node-a", "gpu_device": "0"}
  ],
  "metadata": {
    "path": ["terminal-a", "compute-node-a"]
  }
}
```

## 9. 回写路由结果

接口：

```http
POST /api/routing-orders/{order_id}/result
Content-Type: application/json
```

常规回写示例：

```json
{
  "strategy": "resource_guarantee",
  "selected_strategy": "GPU_EXCLUSIVE_RESOURCE_FIT",
  "external_routing_id": "route-20260610-0001",
  "placements": [
    {"node_id": "compute", "worker_host": "compute-node-a", "gpu_device": "0"}
  ],
  "metadata": {
    "path": ["terminal-a", "compute-node-a", "terminal-b"],
    "selected_reason": "compute-node-a GPU 0 is available and baseline is stable",
    "algorithm_version": "router-v1",
    "cost": {"estimated_price": 1.25, "currency": "CNY"}
  }
}
```

平台处理规则：

- 平台会保存 `placements`、`metadata`、`external_routing_id`。
- 平台会根据业务模板决定哪些逻辑节点要物化为容器。
- 如果 source/sink 是固定端点且平台需要部署对应容器，平台会自动补齐，不要求路由系统回写。
- 如果没有任何节点需要部署，平台只保存结果并把工单标记完成，不创建容器实例。
- 如果需要部署容器，平台会物化实例、动态分配端口，并返回 `network_bindings`。
- 默认返回后工单进入 `routing_status=network_binding_ready`，等待路由系统下发流表/QoS。
- 如果 GPU 冲突，平台返回 `409`，路由系统需要撤销本次资源扣减并重新路由或 requeue。
- 回写接口是幂等的；如果 HTTP 超时，路由系统可以重新 POST 同一结果，平台会返回已有 `instance_id` 和 `network_bindings`。

典型响应：

```json
{
  "status": "ok",
  "order_id": "order-uuid-001",
  "routing_status": "network_binding_ready",
  "instance_id": "instance-uuid-001",
  "network_ready_required": true,
  "network_ready": false,
  "network_bindings": [
    {
      "flow_id": "order-uuid-001:source->compute",
      "from": "source",
      "to": "compute",
      "src_host": "terminal-a",
      "src_ip": "fd00::10",
      "dst_host": "compute-node-a",
      "dst_ip": "fd00::21",
      "dst_port": 18842,
      "dst_named_ports": {"compute": 18842},
      "dst_port_ref": "compute.compute",
      "protocol": "tcp",
      "traffic_class": "low_latency",
      "priority": 90,
      "data_mb": 20,
      "bandwidth_mbps": 20
    }
  ]
}
```

路由系统拿到 `network_bindings` 后，应按其中的源/目的 IP、目的端口、`traffic_class`、`priority` 下发真实网络规则。

## 9.1 网络就绪确认

路由系统完成流表/QoS 下发后，调用：

```http
POST /api/routing-orders/{order_id}/network-ready
Content-Type: application/json
```

请求体：

```json
{
  "metadata": {
    "flow_rule_count": 2,
    "switch_batch_id": "batch-20260611-001"
  },
  "auto_start": true
}
```

语义：

- 平台把 `routing_status` 从 `network_binding_ready` 置为 `completed`。
- 如果业务开始时间已到且结束时间未过，平台会自动启动实例。
- 如果业务开始时间在未来，平台会注册定时启动/停止。
- 如果业务结束时间已过，平台不会启动实例，会标记为过期/失败，避免过期工单误运行。
- 如果只想联调接口、不启动容器，可以传 `"auto_start": false`。

响应示例：

```json
{
  "status": "ok",
  "order_id": "order-uuid-001",
  "routing_status": "completed",
  "instance_id": "instance-uuid-001",
  "network_ready": true,
  "auto_start": true,
  "start_action": "started"
}
```

业务容器还有第二层兜底：`PEER_CONNECT_TIMEOUT_SEC` 和 `PEER_WAIT_TIMEOUT_SEC` 默认 600 秒。即使路由系统确认后流表传播有延迟，worker 也会持续重试一段时间，不会立即失败。

## 10. GPU 独占和资源释放

验收业务默认 GPU 独占：

```text
同一 worker_host + gpu_device
同一时刻
只能被一个未释放任务占用
```

原因是并发争用同一张 GPU 会导致矩阵计算吞吐下降、视频推理时延升高，业务目标成功率可能低于 90%。

路由系统需要维护自己的资源表：

```text
回写成功前 reserve/扣减
任务结束后收到 release 事件再 release/加回
```

30 个任务、10 个 GPU 的正确执行方式：

```text
平台创建 30 个 pending 工单
 -> 路由系统先路由 10 个，后 20 个保持 pending
 -> 平台执行这 10 个任务
 -> 任务完成并清理实例，平台写 release 事件
 -> 路由系统 ack release，把 GPU 加回
 -> 继续路由下一批 pending 工单
 -> 直到 30 个工单全部完成
```

资源不足处理：

| 情况 | 路由系统动作 |
|------|--------------|
| GPU 暂时占满，稍后可能释放 | 调 `PATCH /api/routing-orders/{order_id}/requeue`，不要 failed。 |
| 所有节点都不满足资源约束 | 调 `PATCH /api/routing-orders/{order_id}/fail`，写清原因。 |
| 回写结果时平台返回 GPU 冲突 `409` | 撤销本地资源扣减，requeue 或重新计算。 |

## 11. 最小联调验收标准

先用 3 个 benchmark 工单联调，通过后再跑 30 个正式测评工单。

完成标准：

- 路由系统能获取 pending 工单并成功 claim。
- 路由系统能解析 `routing_input_dag`。
- 路由系统能读取 `nodes`、`node_baselines` 并选择 compute 节点。
- GPU 业务能回写 `gpu_device`。
- 回写 `/result` 后能拿到 `network_bindings`，前端能看到 `routing_status=network_binding_ready`。
- 路由系统下发网络规则后调用 `/network-ready`，前端能看到 `routing_status=completed`。
- 工单详情能看到 compute 节点和 GPU 编号。
- 平台启动任务后能完成业务指标评估。
- 同一 GPU 不会被多个未释放任务同时占用。
- 任务清理后平台写 release 事件，路由系统 ack 后能继续路由下一批。

## 12. 联调测试用例

路由同学或 AI 实现完最小版本后，按下面测试用例自测。测试前建议在平台前端新建一轮“外部路由系统”模式的 benchmark 工单，避免扫到历史旧格式数据。

通用环境变量：

```bash
export PLATFORM_API_BASE=http://10.112.244.94:8181
```

### 用例 1：能读取并领取待路由工单

目的：验证路由系统能拿到平台生成的新 DAG，并用 claim 防止重复处理。

步骤：

```bash
curl -sS \
  "$PLATFORM_API_BASE/api/routing-orders?status=pending&limit=3"

curl -sS -X PATCH \
  "$PLATFORM_API_BASE/api/routing-orders/<order_id>/claim"
```

预期结果：

- 第一个接口返回 pending 工单列表。
- `routing_input_dag.job_id`、`routing_input_dag.order_id`、`order_id` 三者一致。
- `routing_input_dag.nodes` 至少能解析出 `source`、`compute`、`sink` 或文档支持的两节点 DAG。
- claim 成功后返回 `routing_status=computing`。
- 如果并发进程重复 claim，同一个工单只能有一个成功，其他应收到 `409`。

### 用例 2：能回写 compute placement 并完成物化

目的：验证路由系统只回写 compute 节点，平台能自动补齐固定端点并物化实例。

步骤：

```bash
curl -sS -X POST \
  -H "Content-Type: application/json" \
  "$PLATFORM_API_BASE/api/routing-orders/<order_id>/result" \
  -d '{
    "strategy": "resource_guarantee",
    "selected_strategy": "GPU_EXCLUSIVE_RESOURCE_FIT",
    "external_routing_id": "router-selftest-001",
    "placements": [
      {"node_id": "compute", "worker_host": "<chosen-worker-host>", "gpu_device": "0"}
    ],
    "metadata": {
      "path": ["<source>", "<chosen-worker-host>", "<sink>"],
      "selected_reason": "self-test placement",
      "algorithm_version": "router-selftest"
    }
  }'

curl -sS -X POST \
  -H "Content-Type: application/json" \
  "$PLATFORM_API_BASE/api/routing-orders/<order_id>/network-ready" \
  -d '{
    "metadata": {"flow_rule_count": 2, "switch_batch_id": "router-selftest-001"},
    "auto_start": true
  }'
```

预期结果：

- `/result` 返回 `routing_status=network_binding_ready`，并返回 `network_bindings`。
- `network_bindings` 中能看到每条业务流的 `dst_ip`、`dst_port`、`traffic_class`、`priority`。
- `/network-ready` 返回 `routing_status=completed`。
- 如果该业务需要部署容器，响应中有非空 `instance_id`。
- 平台工单详情能看到 compute 节点和 GPU 编号。
- `runtime_config.routing_result.router_placements` 保留路由系统原始回写的 compute placement。
- `runtime_config.routing_result.placements` 是平台最终用于部署/展示的完整 placement。

### 用例 3：临时资源不足时不能丢工单

目的：验证 GPU 暂时占满时，工单会回到 pending 等待下一轮，而不是被误标 failed。

步骤：

```bash
curl -sS -X PATCH \
  -H "Content-Type: application/json" \
  "$PLATFORM_API_BASE/api/routing-orders/<order_id>/requeue" \
  -d '{"reason": "GPU slots temporarily full"}'
```

预期结果：

- 返回 `routing_status=pending`。
- 下一轮扫描 `status=pending` 时还能看到该工单。
- 路由系统日志能记录 requeue 原因。

### 用例 4：确定不可路由时能写失败原因

目的：验证源节点不存在、无任何可用 GPU 等确定不可满足场景有明确失败状态。

步骤：

```bash
curl -sS -X PATCH \
  -H "Content-Type: application/json" \
  "$PLATFORM_API_BASE/api/routing-orders/<order_id>/fail" \
  -d '{"reason": "no routable worker has required GPU"}'
```

预期结果：

- 返回 `routing_status=failed`。
- 平台前端能看到失败状态和失败原因。
- 路由系统不会继续重复处理该工单。

### 用例 5：能消费资源释放事件

目的：验证平台清理任务后，路由系统能收到 release 事件并把 GPU 加回自己的资源表。

步骤：

```bash
curl -sS \
  "$PLATFORM_API_BASE/api/routing-resource-events?event_type=release&unacked=true&limit=10"

curl -sS -X POST \
  -H "Content-Type: application/json" \
  "$PLATFORM_API_BASE/api/routing-resource-events/ack" \
  -d '{"ids": [<event_id>]}'
```

预期结果：

- release 事件包含 `order_id`、`node_hostname`、`resource_kind=gpu`、`resource_id`。
- 路由系统本地资源表把对应 GPU 从占用状态改回可用。
- ack 后同一个事件不再出现在 `unacked=true` 查询结果中。

### 用例 6：GPU 冲突时平台返回 409

目的：验证平台兜底校验生效，防止路由系统误把同一 GPU 分给多个未释放任务。

步骤：

1. 创建两个时间窗口重叠的 GPU 工单。
2. 第一个工单回写 `worker_host=A, gpu_device=0` 并成功。
3. 第二个工单也回写同一个 `worker_host=A, gpu_device=0`。

预期结果：

- 第一个工单回写成功。
- 第二个工单返回 `409`，错误信息包含 GPU 冲突。
- 路由系统应撤销第二个工单的本地资源扣减，并 requeue 或重新计算。

## 13. 可直接交给 AI 的实现提示词

```text
你要实现一个外部路由系统最小联调版本，对接平台 MySQL 和平台 HTTP 接口。

硬性约定：
1. 统一任务 ID 是 task_orders.id，也等于 routing_input_dag.job_id 和 routing_input_dag.order_id。
2. 路由系统只负责选择 compute 节点、GPU 和路径解释，不要判断平台是否给 source/sink/compute 部署容器。
3. source/sink 的真实节点名来自 routing_input_dag.nodes[].fixed_node_name，不要改。
4. GPU 任务必须独占 GPU，同一 worker_host + gpu_device 不能分配给多个未释放任务。
5. 资源暂时不足要 requeue，不要 failed；确定无法满足才 failed。
6. 平台路由接口不需要 token；HTTP 超时建议设置为 120 秒。
7. POST /result 后必须读取响应里的 network_bindings，并按其中 dst_ip/dst_port/traffic_class/priority 下发网络规则。
8. 网络规则下发完成后必须调用 POST /api/routing-orders/{order_id}/network-ready。

需要实现：
1. 调 GET /api/routing-resource-events?event_type=release&unacked=true 读取释放事件，把 GPU 加回自己的资源表，再调 POST /api/routing-resource-events/ack。
2. 调 GET /api/routing-orders?status=pending&limit=100 获取待路由工单。
3. 对每个工单调 PATCH /api/routing-orders/{order_id}/claim，409 表示别人抢到了，跳过。
4. 解析 routing_input_dag，读取 nodes 和 node_baselines，选择 compute 的 worker_host/gpu_device。
5. 成功时调 POST /api/routing-orders/{order_id}/result，placements 只需要回写 compute。
6. 如果 /result 返回 409，撤销本地资源扣减，requeue 或重新计算。
7. 如果 /result 超时，查询该 order 状态；如果已经 network_binding_ready/completed，不要重复扣资源，直接继续读取已有 network_bindings。
8. 根据 network_bindings 下发流表或业务优先级规则。
9. 下发完成后调 POST /api/routing-orders/{order_id}/network-ready。
10. 临时资源不足调 PATCH /api/routing-orders/{order_id}/requeue。
11. 确定无法路由调 PATCH /api/routing-orders/{order_id}/fail。
12. 日志至少记录 order_id、claim 结果、选中节点/GPU、network_bindings、network-ready 结果、失败原因。

先跑通 3 个工单，再跑 30 个正式测评工单。
```

---

# 第二部分：平台背景说明

## 14. 平台和路由系统的边界

平台负责：

- 用户对话和意图解析。
- 创建工单和 `routing_input_dag`。
- 接收路由结果。
- 根据模板物化容器实例。
- 启动、停止、清理容器。
- 采集指标并计算业务目标成功率。
- 展示工单详情、路由结果、GPU 分配和业务结果。

路由系统负责：

- 读取待路由工单。
- 选择 compute 节点、GPU 和路径。
- 维护算法侧资源占用。
- 处理平台 release 事件。
- 回写路由结果和算法解释。

## 15. 为什么路由系统不需要知道容器是否部署

DAG 中的 `source`、`compute`、`sink` 是业务逻辑角色。平台可能有不同模板：

- 有些业务会部署 source、compute、sink 三个容器。
- 有些业务只有 compute 容器，source/sink 是外部终端。
- 有些两端都是终端，只需要路由路径，不需要部署容器。

这些是平台的业务模板和部署策略，路由系统只需要回答：

```text
算力工作节点放在哪台机器？
用哪个 GPU？
业务路径是什么？
为什么这样选？
```

## 16. 内置随机路由策略

平台前端有两种路由方式：

| 模式 | 用途 |
|------|------|
| 内置随机路由策略 | 外部路由未接入时的 fallback，可跑通演示闭环。 |
| 外部路由系统 | 正式联调模式，平台只创建 pending 工单，等待外部路由回写。 |

内置随机路由策略不是正式路由算法，只用于兜底演示和平台自测。

## 17. 业务目标成功率和路由的关系

业务目标成功率验证的是完整闭环：

```text
工单创建
 -> DAG 生成
 -> 路由放置
 -> 容器部署
 -> 业务运行
 -> 指标采集
 -> 成功/失败判定
 -> 成功率统计
```

路由算法不需要证明全局最优，但必须避免明显资源冲突。尤其是 GPU 业务，如果多个并发任务共用同一 GPU，指标会明显波动，影响 90% 成功率验收。

## 18. 当前系统状态

目前平台侧已经具备对接条件：

- `task_orders` 保存了 `routing_input_dag`。
- 平台提供 pending 查询、claim、requeue、fail、result 回写、network-ready 确认接口，且这些演示接口不需要 token。
- 平台接收路由结果后会校验 GPU 冲突。
- 平台会在 result 回写后返回实际 `network_bindings`，供路由系统下发流表/QoS。
- 平台会等待 `network-ready` 后才启动外部路由模式的任务。
- 平台可支持 `source -> sink`、`source -> compute`、`source -> compute -> sink`。
- 平台会在任务停止、删除、清理实例时写入 `routing_resource_events`。
- 工单详情可展示路由结果、节点/GPU 分配和业务指标。

建议联调节奏：

1. 管理节点部署路由服务，确认数据库连接和平台 HTTP 地址。
2. 平台创建 3 个外部路由模式 benchmark 工单。
3. 路由系统 claim 并回写结果，拿到 `network_bindings`。
4. 路由系统下发网络规则后调用 `network-ready`。
5. 前端确认工单变为已路由，能看到 compute/GPU。
6. 平台启动任务并完成业务指标评估。
7. 清理实例，确认路由系统能处理 release 事件。
8. 扩展到 30 个工单的正式业务目标成功率测评。
