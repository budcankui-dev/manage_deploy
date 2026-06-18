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

路由系统判断运行模式时只看下面这些字段，不要自行推断平台会部署哪些容器：

| 场景 | 判断字段 | 路由系统处理 |
|------|----------|--------------|
| 用户端接入演示 | `runtime_config.platform_deployment.deployable_roles=["compute"]` | 只回写 `compute` placement；source/sink 是用户端点。 |
| 只生成路由方案 | `runtime_config.platform_deployment.mode="route_only"` 或 `deployable_roles=[]` | 仍回写 `compute` placement 和 `metadata`；平台不物化实例，不分配容器端口。 |
| 自动化测评 | `task_orders.is_benchmark=true` 或 `deployable_roles=["source","compute","sink"]` | 回写 source/compute/sink 或至少 compute placement；平台部署三类容器。当前不要求 `mode=automated_benchmark` 一定存在。 |

## 2. v1 冻结约定

这些字段和语义后续不再改，路由同学可以按这个实现：

| 项 | 约定 |
|----|------|
| 统一任务 ID | `task_orders.id = routing_input_dag.job_id = routing_input_dag.order_id = order_id` |
| 输入 DAG | 从 `task_orders.routing_input_dag` 或 `GET /api/routing-orders` 响应中读取 |
| 回写接口 | `POST /api/routing-orders/{order_id}/result` |
| 子任务节点 ID | `routing_input_dag.nodes[].task_node_id`，常见为 `source`、`compute`、`sink` |
| 固定拓扑节点 | `routing_input_dag.nodes[].fixed_topology_node_id`，表示用户已指定源/目的真实节点 |
| 算力选择 | 路由系统回写 `placements[].task_node_id=compute`、`topology_node_id=<nodes.hostname>`、可选 `gpu_device` |
| 端点部署 | 是否部署由 `runtime_config.platform_deployment.deployable_roles` 决定；用户演示通常只部署 `compute`，自动化测评会部署 `source/compute/sink` |
| GPU 独占 | 同一 `topology_node_id + gpu_device` 同一时刻只能分配给一个未释放任务 |
| 业务优先级 | `routing_input_dag.priority`，取值 `1-8`，由平台系统设置中的模态优先级字典生成 |
| 资源需求 | `routing_input_dag.nodes[].resources`，由平台确定性生成；路由系统直接读取，不需要调用大模型 |
| 扩展信息 | 算法版本、路径、成本、租金、解释等统一放到 `metadata` 字典 |

平台默认按 `task_type` 映射业务模态，再由模态优先级字典生成 `priority` 和 `edges[].flow.priority`。如果平台管理员在系统设置中启用“任务模态映射覆盖”，新建工单的 `modal/priority` 会按覆盖后的模态生成；路由系统仍然只消费 DAG 中已经写好的 `modal/priority`，不需要自己推断。

最容易混淆的是下面两组字段，它们不是同一件事：

| 字段 | 含义 | 路由系统怎么用 |
|------|------|----------------|
| `modal` / `priority` | 业务属于哪类模态，以及该模态对应的业务流优先级。 | 可用于 QoS、路径等级或日志解释。 |
| `routing_strategy` / `policy_type` | 用户本次希望采用的选路偏好。 | 决定算法目标函数或候选节点排序。 |

一句话：**模态回答“这是什么业务流”，路由策略回答“这次希望怎么选路”。二者可以相关，但不能互相替代。**

路由策略数据字典如下，路由系统只需要识别这些键：

| `routing_strategy` | `policy_type` | 展示名 | 含义 |
|------|------|------|------|
| `cost_priority` | `COST_CONSTRAINED` | 成本开销保障 | 优先选择成本较低的可用资源。 |
| `low_latency_forwarding` | `LATENCY_CONSTRAINED` | 低时延转发 | 优先选择链路时延较低、跳数更少或网络更稳定的路径。 |
| `resource_guarantee` | `RESOURCE_GUARANTEE` | 资源预留保障 | 默认策略，先保证资源满足需求和 GPU 独占。 |
| `fastest_completion` | `TIME_CONSTRAINED` | 完成时间优先 | 优先选择预计完成更快的节点。 |
| `load_balance` | `LOAD_BALANCE` | 资源负载均衡 | 优先把任务分散到负载较低的节点。 |

平台只会为上表中的有效 `routing_strategy` 生成对应 `policy_type`。如果用户没有表达特殊偏好，新建工单默认使用 `resource_guarantee / RESOURCE_GUARANTEE`。平台内部会把少量旧别名规范化到上表，例如 `completion_time_first` 会输出为 `fastest_completion`；路由系统只需要消费上表中的冻结键。旧版本历史数据不作为兼容目标；联调前应清理旧工单，并按当前策略字典重新创建。

业务模态与默认优先级字典如下。`1` 表示最高业务流优先级，`8` 表示最低；平台系统设置可以调整该映射。

| 业务模态 | 默认优先级 |
|----------|------------|
| 低时延转发模态 | 1 |
| 确定性转发模态 | 2 |
| 高安全传输模态 | 3 |
| 智算中心模态 | 4 |
| 高通量计算模态 | 5 |
| 高能效边缘计算模态 | 6 |
| 分布式存算模态 | 7 |
| 大规模连接模态 | 8 |

命名规则只保留三套概念，分别服务不同边界：

```text
task_node_id              任务 DAG 内部子任务角色，例如 source / compute / sink
nodes.hostname            平台节点别名，例如 h1 / compute-1；路由回写 placement 必须用它
nodes.topology_node_id    拓扑/资产节点 ID，例如 h18001001；固定用户端点会写入 DAG
```

不要把 `task_node_id` 当成物理机器，也不要把物理节点名写进 DAG 的 `edges.from/to`。`edges.from/to` 永远引用 `task_node_id`。

路由回写只接受当前 placement 字段：`task_node_id`、`topology_node_id`、`gpu_device`。其中 `placements[].topology_node_id` 当前必须填写 `nodes.hostname`，不要填写数据库内部 `nodes.id`，也不要填写资产字段 `nodes.topology_node_id`。历史测试数据不迁移，清理后按当前格式重新创建。

用户端接入演示里，source/sink 是用户自行控制的业务端点。平台会在 DAG 节点中给出 `fixed_topology_node_id`，该字段优先使用 `nodes.topology_node_id` 这类资产拓扑 ID，同时附带 `topology_alias=nodes.hostname`、数据面 `business_ipv6` / `business_ip`，sink 还会给出用户登记的 `business_port` / `callback_url`。正式验收以 `business_ipv6` 作为业务数据面地址；如果 URL 中直接出现 IPv6，必须写成 `http://[IPv6]:port/...`。这些字段用于路由系统识别 A->B->C 业务流和下发 B->C 规则；路由系统不要替用户分配 sink 端口，也不要把用户端 receiver 是否启动作为路由成功条件。

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

当前管理节点联调状态：

| 项 | 当前值 |
|----|--------|
| 平台后端 | `http://10.112.244.94:8181`，路由服务部署在管理节点时使用 `http://127.0.0.1:8181` |
| 平台前端 | `http://10.112.244.94:8182` |
| 路由模式 | 系统设置已切换为 `外部路由系统`，平台不会自动消费 pending 工单 |
| 清理状态 | 历史测评工单、任务实例、未确认 release 事件已清理；可直接创建新工单联调 |

## 4. 平台已提供的 HTTP 接口

这些接口是验收演示用内部接口，当前不需要 token 或签名。路由服务只要能访问平台后端地址即可。

建议路由系统把 HTTP 超时设置为 **不少于 60 秒，推荐 120 秒**。`/result` 会物化实例并预分配端口，偶尔比普通查询慢；如果请求超时，先查询该工单状态，看到已进入 `network_binding_ready` 或 `completed` 就不要重复扣资源。

平台系统设置中“业务测评路由”应选择 **外部路由系统**。该模式下平台会等待路由系统回写结果，并拒绝内置自动路由接口，避免测评工单绕过外部路由服务。

核心联调只需要下面 4 个接口：

| 动作 | 方法与路径 | 说明 |
|------|------------|------|
| 获取待路由工单 | `GET /api/routing-orders?status=pending&limit=100` | 平台返回 pending 工单和 DAG。也可以直接读 MySQL，但推荐先用接口联调。 |
| 领取工单 | `PATCH /api/routing-orders/{order_id}/claim` | 平台把 `pending -> computing`，并发时只有一个路由进程能成功。 |
| 回写路由结果 | `POST /api/routing-orders/{order_id}/result` | 平台保存结果、校验 GPU 冲突、物化部署实例，并返回实际端口绑定 `network_bindings`。该接口要求先 claim，pending 工单直接回写会返回 409。 |
| 确认网络就绪 | `POST /api/routing-orders/{order_id}/network-ready` | 路由系统下发流表/QoS 后调用，平台才启动或注册启动计划。 |

`/result` 最小请求示例：

```json
{
  "placements": [
    {"task_node_id": "compute", "topology_node_id": "compute-1", "gpu_device": "0"}
  ],
  "metadata": {
    "algorithm_version": "router-v1",
    "selected_reason": "compute-1 当前 GPU 可用，且该业务 baseline 较稳定",
    "candidate_scores": [
      {"topology_node_id": "compute-1", "score": 0.91}
    ]
  },
  "require_network_ready": true
}
```

典型响应会包含 `routing_status=network_binding_ready` 和 `network_bindings`。如果是 `route_only` 工单，平台会保存 placements/metadata，但不会物化实例；响应以 `deployment_required=false` 和 `deployment_mode=route_only` 为准，`network_bindings=[]`，通常无需再调用 `/network-ready`。`route_only=true` 只作为平台内部 `runtime_config.routing_result` 的辅助标记，不作为顶层响应字段依赖。

`/result` 请求字段已冻结，额外字段会被平台拒绝：

| 字段 | 说明 |
|------|------|
| `placements` | 路由结果列表。每项只接受 `task_node_id`、`topology_node_id`、`gpu_device`。 |
| `strategy` / `selected_strategy` | 可选，路由策略和算法侧具体策略名。 |
| `external_routing_id` | 可选，路由系统自己的结果 ID。 |
| `metadata` | 可选，算法版本、路径、成本、解释、候选评分等扩展字典。 |
| `estimated_metric` / `result_payload` | 可选，算法侧估计值和原始结果。 |
| `require_network_ready` | 是否要求路由系统下发网络规则后再调用 `/network-ready`，默认 `true`。 |

`/result` 成功响应的关键字段如下：

| 字段 | 普通部署 | `route_only` | 路由系统怎么用 |
|------|----------|--------------|----------------|
| `status` | `ok` | `ok` | 接口调用成功。 |
| `order_id` | 当前工单 ID | 当前工单 ID | 用于日志关联。 |
| `routing_status` | 通常为 `network_binding_ready` | `completed` | 普通部署需要继续下发网络规则；只路由不部署到这里已结束。 |
| `instance_id` | 平台物化后的实例 ID | `null` | 普通部署可用于排障；路由系统通常不用。 |
| `network_bindings` | 非空数组 | `[]` | 下发 A->B、B->C 流表/QoS 的最终依据。 |
| `network_ready_required` | `true` 或请求指定值 | `false` | 为 `true` 时下发网络后必须调用 `/network-ready`。 |
| `network_ready` | `false` | `true` | 表示平台是否认为网络阶段已完成。 |

`network_bindings[]` 常用字段如下。下发真实业务流规则时优先使用这些字段，而不是提前猜测容器端口：

| 字段 | 含义 | 是否重点使用 |
|------|------|--------------|
| `flow_id` | 平台生成的业务流 ID，通常形如 `<order_id>:source->compute`。 | 是，用于日志和幂等。 |
| `from` / `to` | DAG 子任务角色名，引用 `task_node_id`，例如 `source -> compute`。 | 是，用于识别流向。 |
| `src_topology_node_id` / `dst_topology_node_id` | 源/目的资产拓扑 ID；缺失时回退为平台节点别名。 | 是，用于映射拓扑节点。 |
| `src_ip` / `dst_ip` | 源/目的数据面 IP。 | 是，用于生成业务流规则。 |
| `dst_port` / `dst_named_ports` | 下游目的端实际监听端口。 | 是，端口以这里为准。 |
| `dst_access_url` | 可访问目的端服务的 URL。 | 可选，便于调试。 |
| `src_external` / `dst_external` | 是否为用户自行控制的外部端点。 | 是，用于区分平台容器和用户端点。 |
| `binding_source` | 绑定来源说明。 | 可选，便于排障。 |

注意：回写请求中的 `placements[].topology_node_id` 当前必须填写 `nodes.hostname`；响应中的 `src_topology_node_id/dst_topology_node_id` 则优先表示资产拓扑 ID。路由系统如果要拿平台节点别名，应使用响应里的 `src_host/dst_host`。

最小本地 mock 验收可以直接按下面 4 步执行。示例默认把 compute 固定选到 `compute-1` 的 `GPU 0`：

```bash
# 1. 查看待路由工单
curl -sS 'http://127.0.0.1:8181/api/routing-orders?status=pending&limit=1' | python3 -m json.tool

# 2. 领取工单，替换为上一步返回的 order_id
ORDER_ID=<order_id>
curl -sS -X PATCH "http://127.0.0.1:8181/api/routing-orders/${ORDER_ID}/claim" | python3 -m json.tool

# 3. 回写最小路由结果
curl -sS -X POST "http://127.0.0.1:8181/api/routing-orders/${ORDER_ID}/result" \
  -H 'Content-Type: application/json' \
  -d '{
    "placements": [
      {"task_node_id":"compute","topology_node_id":"compute-1","gpu_device":"0"}
    ],
    "metadata": {
      "algorithm_version":"mock-v1",
      "selected_reason":"local mock fixed placement"
    },
    "require_network_ready": true
  }' | python3 -m json.tool

# 4. 如果第 3 步返回 network_ready_required=true，则下发规则后确认网络就绪
curl -sS -X POST "http://127.0.0.1:8181/api/routing-orders/${ORDER_ID}/network-ready" \
  -H 'Content-Type: application/json' \
  -d '{"metadata":{"mock":true,"flow_rule_count":2}}' | python3 -m json.tool
```

验收判断：

- 普通部署工单：第 3 步应返回 `routing_status=network_binding_ready` 且 `network_bindings` 非空；第 4 步后应变为 `routing_status=completed`。
- `route_only` 工单：第 3 步应返回 `routing_status=completed`、`network_bindings=[]`、`network_ready=true`，通常不需要第 4 步。
- 重复 claim 同一工单应返回 `409`，证明并发领取控制生效。
- 如果第 3 步 HTTP 超时，路由系统应先查询该工单状态。平台已经物化实例的重复 `/result` 会按同一工单幂等返回，不应再次扣减路由侧资源。

下面是资源闭环接口。HTTP smoke mock 可以暂不实现；正式连续批量路由或维护 GPU 独占资源池时必须实现 release 查询与 ack，否则任务释放后资源不会回补：

| 动作 | 方法与路径 | 说明 |
|------|------------|------|
| 临时资源不足 | `PATCH /api/routing-orders/{order_id}/requeue` | 把 `computing -> pending`，稍后重试，不要丢工单。 |
| 确定无法路由 | `PATCH /api/routing-orders/{order_id}/fail` | 把工单标记为 `failed`，需要写清失败原因。 |
| 查询释放事件 | `GET /api/routing-resource-events?event_type=release&unacked=true&limit=100` | 平台告诉路由系统哪些 GPU 已释放。 |
| 确认释放事件 | `POST /api/routing-resource-events/ack` | 路由系统把资源加回后，确认这些事件已处理。 |

平台仓库提供一个最小 mock 路由器用于接口自检。它不会替代路由算法，只用于证明 pending、claim、result、network-ready 和端口返回链路可用：

```bash
cd /home/bupt/manage_deploy
python3 scripts/mock_external_router.py \
  --base-url http://127.0.0.1:8181 \
  --limit 3 \
  --compute-nodes compute-1,compute-2,compute-3 \
  --gpu-device 0
```

如果只想查看待路由工单而不回写：

```bash
python3 scripts/mock_external_router.py \
  --base-url http://127.0.0.1:8181 \
  --dry-run
```

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
        task_type = dag["task_type"]
        baseline_map = load_node_baselines(task_type)
        placement = choose_compute_node_and_gpu(dag, nodes, baseline_map, router_resource_pool)

        if placement.temporarily_unavailable:
            PATCH(f"/api/routing-orders/{order_id}/requeue", {"reason": "GPU slots temporarily full"})
            continue

        if placement.impossible:
            PATCH(f"/api/routing-orders/{order_id}/fail", {"reason": placement.reason})
            continue

        router_resource_pool.reserve(placement.topology_node_id, "gpu", placement.gpu_device)
        result = POST(f"/api/routing-orders/{order_id}/result", placement.to_payload())
        if result.status_code == 409:
            router_resource_pool.release(placement.topology_node_id, "gpu", placement.gpu_device)
            PATCH(f"/api/routing-orders/{order_id}/requeue", {"reason": result.text})
            continue

        result_body = result.json()
        bindings = result_body["network_bindings"]
        if result_body.get("network_ready_required"):
            install_flow_rules(bindings)
            POST(
                f"/api/routing-orders/{order_id}/network-ready",
                {"metadata": {"flow_rule_count": len(bindings)}, "auto_start": True},
            )
```

## 6. MySQL 扫表和 HTTP 接口怎么配合

第一阶段平台只使用 MySQL。路由系统可以直接读 MySQL，但建议遵守下面的分工：

| 动作 | 推荐方式 | 原因 |
|------|----------|------|
| 发现待路由工单 | MySQL 扫 `task_orders` 或 `GET /api/routing-orders` | 数据量小，两种都可以。 |
| 领取工单 | 必须调用 `PATCH /api/routing-orders/{order_id}/claim` | 平台用行锁保证并发只成功一次，避免重复扣 GPU。 |
| 读取节点和 baseline | MySQL 读 `nodes`、`node_baselines` | 算法侧查询方便，字段稳定。 |
| 回写路由结果 | 必须调用 `POST /api/routing-orders/{order_id}/result` | 平台要校验 GPU 冲突、物化实例、分配端口。 |
| 下发流表后确认 | 必须调用 `POST /api/routing-orders/{order_id}/network-ready` | 平台收到确认后才启动或注册调度。 |
| 处理资源释放 | MySQL 或 HTTP 读 `routing_resource_events`，ack 走 HTTP | 资源加回后需要平台记录确认时间。 |

不要让路由系统直接 `UPDATE task_orders.routing_status` 或直接写 `runtime_config.routing_result`。这些字段由平台接口维护，否则容易绕过 GPU 冲突校验、端口分配和网络就绪状态。

路由系统第一阶段只需要读下面这些表。

### 6.1 `task_orders`

工单表。直接扫表时只把它当作“候选队列”，真正处理前仍要调用 claim。

| 字段 | 用途 |
|------|------|
| `id` | 统一工单 ID，也是 `job_id/order_id`。 |
| `routing_status` | 路由状态，路由系统主要处理 `pending`。完整状态见下表。 |
| `routing_input_dag` | 路由算法输入 DAG。JSON 内使用 `task_node_id/topology_node_id` 语义。 |
| `source_name` / `destination_name` | 用户输入的源节点和目的节点。 |
| `business_start_time` / `business_end_time` | 业务时间窗口。 |
| `runtime_config` | 业务类型、benchmark 轮次、路由结果等扩展信息。 |
| `materialized_instance_id` | 平台物化后的任务实例 ID。 |
| `deleted_at` | 非空表示已逻辑删除，必须跳过。 |

`routing_status` 状态含义：

| 状态 | 含义 | 路由系统动作 |
|------|------|--------------|
| `pending` | 待路由 | 可 claim。 |
| `computing` | 已被某个路由进程领取 | 不要重复处理；超时恢复后续可再加。 |
| `network_binding_ready` | 平台已物化实例并返回端口，等待网络就绪 | 下发流表/QoS 后调用 `network-ready`。 |
| `completed` | 路由闭环完成 | 不再处理。 |
| `failed` | 路由失败 | 不再处理，除非人工重置。 |
| `cancelled` | 工单已取消 | 不再处理。 |

如果直接扫表读取待路由工单，推荐 SQL：

```sql
SELECT id, name, routing_status, source_name, destination_name,
       business_start_time, business_end_time, routing_input_dag, runtime_config
FROM task_orders
WHERE deleted_at IS NULL
  AND routing_status = 'pending'
ORDER BY created_at ASC
LIMIT 100;
```

并发注意：扫表只负责发现候选工单，真正处理前必须调用 `PATCH /api/routing-orders/{order_id}/claim`。claim 成功才计算路由，claim 返回 `409` 表示别的进程已抢到，直接跳过。

`routing_input_dag` 最少要读取这些字段：

| JSON 字段 | 用途 |
|-----------|------|
| `job_id` / `order_id` | 与 `task_orders.id` 一致，用于日志和回写。 |
| `task_type` | 查询对应业务 baseline。 |
| `modal` / `priority` | 模态和业务优先级，可辅助路径/QoS 决策。 |
| `nodes[].task_node_id` | 子任务角色名，例如 `source/compute/sink`。 |
| `nodes[].task_node_type` | 子任务类型，例如 `terminal/worker`。 |
| `nodes[].resources` | 平台给出的 CPU、内存、磁盘、GPU 需求。 |
| `nodes[].fixed_topology_node_id` | 用户输入并固定的真实拓扑端点，通常在 source/sink；优先为 `nodes.topology_node_id`。 |
| `nodes[].topology_alias` | 平台节点别名，对应 `nodes.hostname`，便于展示和回查。 |
| `nodes[].resources.gpu_units` | 判断该子任务是否需要 GPU。 |
| `edges[].from/to` | 业务流两端，引用 `task_node_id`。 |
| `edges[].bandwidth_mbps` | 带宽需求估计，供选路参考。 |
| `edges[].flow.priority` | 业务流优先级，取值 `1-8`。 |

### 6.2 `nodes`

节点表。路由时只考虑未删除且可路由的节点。

| 字段 | 用途 |
|------|------|
| `id` | 平台内部节点 ID。 |
| `hostname` | 平台节点别名，回写 `placements[].topology_node_id` 必须使用这个值，如 `h1`、`compute-1`。 |
| `display_name` | 真实主机名或展示名，如 `s15-Ubuntu-Host-1`。 |
| `topology_node_id` | 实验拓扑或资产主机 ID，如 `h18001001`；用户固定端点会在 DAG 的 `fixed_topology_node_id` 中使用它，但路由回写 placement 不使用它。 |
| `topology_zone` | 拓扑区域，如 `h180`、`h400`、`h410`、`compute`。 |
| `business_ip` / `business_ipv6` | 数据面地址。 |
| `node_kind` | `worker`、`terminal`、`both`、`admin` 等。 |
| `is_schedulable` | 是否可部署业务容器。 |
| `is_routable` | 是否参与路由。 |
| `deleted_at` | 非空必须跳过。 |

推荐查询：

```sql
SELECT id, hostname, display_name, topology_node_id, topology_zone,
       business_ip, business_ipv6, node_kind, is_schedulable, is_routable
FROM nodes
WHERE deleted_at IS NULL
  AND is_routable = 1;
```

节点筛选建议：

- `node_kind in ('worker', 'both')` 且 `is_schedulable=1` 的节点可作为 `compute` 候选。
- `node_kind in ('terminal', 'both', 'worker')` 且 `is_routable=1` 的节点可参与路径计算。
- 新增终端节点时推荐也部署 Docker 和 Node Agent，并设置 `is_schedulable=1, is_routable=1`，这样同一台终端既能承载 source/sink 容器，也能只作为路由端点。
- 当前最终拓扑包含 `admin-server`、`compute-1~compute-3` 和 `h1~h13`。用户源/目的端点优先来自 `h1~h13` 终端节点；`compute-1~compute-3` 是算力候选节点，通常由路由系统回写到 `compute` placement。
- 是否为 source/sink 创建容器由平台工单的 `platform_deployment.deployable_roles` 决定，不由路由系统决定。
- 如果 DAG 的 `fixed_topology_node_id` 指向某个节点，路由系统可先按 `nodes.topology_node_id` 匹配，匹配不到再按 `nodes.hostname` 兜底；平台生成的新 DAG 会同时给出 `topology_alias` 方便回查。
- 回写 `placements[].topology_node_id` 时必须使用 `nodes.hostname`，不要使用 `nodes.id` 或资产字段 `nodes.topology_node_id`。

扩展拓扑节点时按下面规则配置即可：

| 场景 | 推荐配置 | 是否可用于业务目标测评 | 说明 |
|------|----------|------------------------|------|
| 终端节点需要承载 source/sink 容器 | `node_kind=terminal` 或 `both`，`is_schedulable=1`，`is_routable=1` | 可以 | 需要部署 Node Agent、Docker，并能拉取/运行业务镜像。 |
| 终端节点参与某些任务但该任务不部署 source/sink 容器 | 通常仍为 `node_kind=terminal` 或 `both`，`is_schedulable=1`，`is_routable=1` | 视任务而定 | 机器具备部署能力，但当前任务可用 `deployable_roles=["compute"]` 或 `[]` 只建立路由路径。 |
| 少数纯网络节点确实没有容器环境 | `node_kind=terminal`，`is_schedulable=0`，`is_routable=1` | 不可以 | 仅用于 route-only 路径检查，不用于需要业务容器的测评。 |
| 特殊情况下计算节点也作为用户输入的源/目的节点 | `node_kind=worker` 或 `both`，`is_schedulable=1`，`is_routable=1` | 可以，但不是默认演示口径 | 在 DAG 里仍写成 `source/sink` 角色，真实机器名放在 `fixed_topology_node_id`。默认用户端演示仍建议使用 `h1~h13`。 |
| 专用计算节点 | `node_kind=worker`，`is_schedulable=1`，`is_routable=1` | 可以 | 路由系统可把它作为 `compute` placement，并按 GPU 独占规则扣减资源。 |

### 6.3 `node_baselines`

节点基线表，存放不同业务在不同节点上的历史指标，供路由算法参考。正式测评前平台应先在业务测评页面完成基线测试；路由系统查询时如果缺少当前 `task_type` 对应基线，不要硬路由该节点。

| 字段 | 用途 |
|------|------|
| `node_id` | 关联 `nodes.id`，这是数据库内部外键，不是 DAG 的 `task_node_id`。 |
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

推荐查询：

```sql
SELECT n.hostname AS topology_node_id,
       b.task_type,
       b.metric_key,
       b.baseline_value,
       b.operator,
       b.unit,
       b.raw_values
FROM node_baselines b
JOIN nodes n ON n.id = b.node_id
WHERE n.deleted_at IS NULL
  AND b.task_type = '<routing_input_dag.task_type>';
```

如果要只取可作为 compute 的节点，可以加：

```sql
  AND n.is_schedulable = 1
  AND n.is_routable = 1
  AND n.node_kind IN ('worker', 'both')
```

baseline 准备规则：

- 正式测评前，平台管理员在业务测评页面对参与节点执行一次批量基线测试。
- 每个节点、每个 `task_type`、固定业务参数重复 3 次，取中位数写入 `node_baselines.baseline_value`。
- 历史多次 baseline 只作参考；镜像、GPU/CPU 路径、业务参数或硬件拓扑变化后，应重新建立当前轮基线。
- 如果某节点缺少当前 `task_type` 的 baseline，路由系统可以跳过该节点。
- 如果所有可用节点都缺少 baseline，调用 `PATCH /api/routing-orders/{order_id}/requeue`，原因写“baseline not ready”，不要丢工单。

当前管理节点历史实测参考值如下，仅供路由排序、联调解释和异常排查使用；正式测评仍以当前轮次重新测得的稳定 baseline 为准。

| 业务 | 节点 | 历史参考值 | 稳定性 | 说明 |
|------|------|------------|--------|------|
| 矩阵乘法计算 | `compute-1` | 5448.33 GFLOPS | 稳定 | GPU 路径历史基线。 |
| 矩阵乘法计算 | `compute-2` | 5283.98 GFLOPS | 稳定 | GPU 路径历史基线。 |
| 矩阵乘法计算 | `compute-3` | 5154.95 GFLOPS | 稳定 | 3 次原始值中位数。 |
| 视频 AI 推理 | `compute-1` | 131.36 ms | 稳定 | `onnxruntime_cuda`，YOLOv5n，P90 帧时延。 |
| 视频 AI 推理 | `compute-2` | 159.36 ms | 稳定 | `onnxruntime_cuda`，YOLOv5n，P90 帧时延。 |
| 视频 AI 推理 | `compute-3` | 99.63 ms | 波动较大 | 历史原始值约 71.6-106.6 ms，正式测评前建议重测。 |

### 6.4 DAG 资源需求从哪里来

路由系统只需要消费 `routing_input_dag.nodes[].resources`，不需要自己生成这些值。平台当前生成顺序如下：

1. 默认由平台资源估算器根据 `task_type + data_profile` 确定性计算。
2. 如果系统设置中启用了“任务资源要求覆盖”，对应 `task_type + task_node_id` 的覆盖值优先于默认估算。
3. 如果单个工单显式带有 `resource_requirement`，它优先级最高，用于临时专项联调。

这三种方式都由平台在创建工单或预览 DAG 时完成，最终写入 `task_orders.routing_input_dag`。大模型/智能体不会随机生成资源值。

当前默认参考值：

| 业务 | 子任务 | CPU | 内存 MB | 磁盘 MB | GPU |
|------|--------|-----|---------|---------|-----|
| 矩阵乘法计算 | source/sink | 2 | 512 | 512 | 0 |
| 矩阵乘法计算 | compute | 8 | 随矩阵规模估算，最低 1024 | 1024 | 1 |
| 视频 AI 推理 | source/sink | 2 | 512 | 512 | 0 |
| 视频 AI 推理 | compute | 4 | 2048 或 4096 | 1024 | 1 |

后续如果要更精细，可以把 worker 容器的 Docker 运行指标和业务 baseline 结果沉淀到数据库，作为系统设置推荐值或估算器校准输入。当前 v1 联调不要求路由系统实现这部分。

资源字段的运行时语义：

- `gpu_units` 用于路由系统选择 GPU 资源；路由回写的 `placements[].gpu_device` 会进入平台部署参数，并由 Node Agent 转成 Docker GPU `device_requests`。
- `cpu_units`、`mem_mb`、`disk_mb` 当前用于路由估算、前端展示和容器环境变量 `RESOURCE_REQUIREMENT`，不会自动转成 Docker `cpu_limit`、`memory_limit` 或磁盘硬限制。
- 如果后续需要强限制 CPU/内存，应由平台在模板或实例覆盖字段中显式设置 `cpu_limit`、`memory_limit` 等 Docker runtime 参数；不建议在当前联调阶段自动强限，避免因限额过紧影响业务目标成功率。

### 6.5 `routing_resource_events`

资源释放事件表。平台在任务停止、失败、删除、清理实例后写入 release 事件，路由系统处理后调用 ack。

| 字段 | 用途 |
|------|------|
| `id` | 自增事件 ID。 |
| `event_type` | 第一阶段只用 `release`。 |
| `order_id` / `job_id` | 统一工单 ID。 |
| `benchmark_run_id` | 验收轮次，可选。 |
| `task_type` | 业务类型。 |
| `node_hostname` | 被释放资源所在节点，对应 `nodes.hostname`，也就是路由回写的 `placements[].topology_node_id`。 |
| `resource_kind` | 第一阶段主要是 `gpu`。 |
| `resource_id` | GPU 编号，如 `0`。 |
| `amount` | 释放数量，GPU 默认 `1`。 |
| `reason` | `completed`、`cleanup_instance`、`delete_order`、`failed` 等。 |
| `router_ack_at` | 路由系统确认处理时间。 |

推荐查询未确认 release：

```sql
SELECT id, order_id, job_id, benchmark_run_id, task_type,
       node_hostname, resource_kind, resource_id, amount, reason, metadata, created_at
FROM routing_resource_events
WHERE event_type = 'release'
  AND router_ack_at IS NULL
ORDER BY created_at ASC
LIMIT 100;
```

处理规则：

- 路由系统读取 release 后，把 `node_hostname + resource_id` 对应 GPU 加回自己的资源表。
- 加回成功后调用 `POST /api/routing-resource-events/ack`，不要直接更新 `router_ack_at`。
- 这张表有唯一约束，平台会避免同一个工单、同一节点、同一 GPU 重复发 release。
- 如果 ack 请求失败，下一轮还会读到同一事件，路由系统应按事件 ID 做幂等处理。

### 6.6 路由系统自己的资源占用表

平台不限制路由系统内部怎么建表。最小版本建议维护一张本地表或内存持久化结构：

| 字段 | 含义 |
|------|------|
| `topology_node_id` | 对应平台 `nodes.hostname`。 |
| `resource_kind` | 第一阶段用 `gpu`。 |
| `resource_id` | GPU 编号，如 `0`。 |
| `order_id` | 当前占用该资源的工单 ID。 |
| `reserved_at` | 扣减时间。 |
| `external_routing_id` | 路由系统自己的决策 ID，可选。 |

扣减和释放口径：

- `/result` 调用前先在路由系统本地 reserve，防止自己并发重复分配。
- `/result` 返回 `409` 时立即撤销本地 reserve。
- `/result` 超时但平台状态已是 `network_binding_ready/completed` 时，不要再次 reserve；按已有结果继续处理。
- 收到 release 并 ack 成功后，再把资源正式释放为可用。

### 6.7 最小字段结构清单

下面不是要求路由系统建同样的表，而是说明扫平台 MySQL 时需要按这些字段理解数据：

```sql
-- 待路由工单队列表
task_orders(
  id varchar(36) primary key,              -- 统一工单 ID / job_id / order_id
  name varchar(255),
  source_name varchar(255),
  destination_name varchar(255),
  business_start_time datetime,
  business_end_time datetime,
  routing_status varchar(50),             -- pending / computing / network_binding_ready / completed / failed
  routing_input_dag json,                 -- 路由算法输入 DAG
  runtime_config json,                    -- 业务类型、测评轮次、平台运行配置
  materialized_instance_id varchar(36),
  deleted_at datetime,
  created_at datetime
);

-- 真实拓扑节点表
nodes(
  id varchar(36) primary key,              -- 平台内部节点 ID
  hostname varchar(255) unique,            -- 路由回写必须使用这个值，例如 h1 / compute-1
  display_name varchar(255),               -- 真实主机名，例如 s15-Ubuntu-Host-1
  topology_node_id varchar(255),           -- 拓扑/资产 ID，例如 h18001001
  topology_zone varchar(64),               -- h180 / h400 / h410 / compute
  business_ip varchar(45),
  business_ipv6 varchar(64),
  node_kind varchar(50),                   -- worker / terminal / both / admin
  is_schedulable boolean,
  is_routable boolean,
  deleted_at datetime
);

-- 节点业务基线表
node_baselines(
  id varchar(36) primary key,
  node_id varchar(36),                     -- 关联 nodes.id
  task_type varchar(255),                  -- high_throughput_matmul / low_latency_video_pipeline
  metric_key varchar(255),                 -- effective_gflops / frame_latency_p90_ms
  baseline_value double,
  operator varchar(8),
  unit varchar(64),
  run_count int,
  raw_values json
);

-- 平台发给路由系统的资源释放事件表
routing_resource_events(
  id bigint primary key auto_increment,
  event_type varchar(50),                  -- 第一阶段只看 release
  order_id varchar(36),
  job_id varchar(36),
  external_routing_id varchar(255),
  benchmark_run_id varchar(255),
  task_type varchar(255),
  node_hostname varchar(255),              -- 被释放的 nodes.hostname，即 placements[].topology_node_id
  resource_kind varchar(50),               -- 第一阶段主要是 gpu
  resource_id varchar(64),                 -- GPU 编号
  amount int,
  reason varchar(64),
  router_ack_at datetime,
  metadata json,
  created_at datetime
);
```

字段使用原则：

- 跨系统唯一 ID 只看 `task_orders.id`，它等于 DAG 里的 `job_id/order_id`。
- 路由回写真实节点只用 `nodes.hostname`，不要回写 `nodes.id` 或 `nodes.topology_node_id`。
- `node_baselines.node_id` 是平台内部外键，查询时通过 `JOIN nodes` 转成 `topology_node_id`。
- `routing_resource_events.node_hostname` 对应 `nodes.hostname`，也就是路由回写的 `placements[].topology_node_id`；它不是资产字段 `nodes.topology_node_id`。

## 7. 输入 DAG 格式

三节点常规业务示例：

```json
{
  "job_id": "order-uuid-001",
  "order_id": "order-uuid-001",
  "job_name": "视频AI推理",
  "source_name": "terminal-a",
  "destination_name": "terminal-b",
  "modal": "低时延转发模态",
  "priority": 1,
  "routing_strategy": "low_latency_forwarding",
  "policy_type": "LATENCY_CONSTRAINED",
  "business_start_ts_ms": 1777341600000,
  "business_end_ts_ms": 1777345200000,
  "nodes": [
    {
      "task_node_id": "source",
      "task_role": "source",
      "task_node_type": "terminal",
      "fixed_topology_node_id": "terminal-a",
      "network": {
        "port_requirements": [
          {"name": "source", "protocol": "tcp", "auto": true, "range": [18800, 19100], "direction": "inbound"}
        ]
      },
      "resources": {"cpu_units": 2, "mem_mb": 512, "disk_mb": 512, "gpu_units": 0}
    },
    {
      "task_node_id": "compute",
      "task_role": "compute",
      "task_node_type": "worker",
      "network": {
        "port_requirements": [
          {"name": "compute", "protocol": "tcp", "auto": true, "range": [18800, 19100], "direction": "inbound"}
        ]
      },
      "resources": {"cpu_units": 10, "mem_mb": 2048, "disk_mb": 1024, "gpu_units": 1}
    },
    {
      "task_node_id": "sink",
      "task_role": "sink",
      "task_node_type": "terminal",
      "fixed_topology_node_id": "terminal-b",
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
        "priority": 1
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
        "priority": 1
      }
    }
  ]
}
```

关键理解：

- `task_node_id` 是任务内部子任务节点名，不是物理节点名。
- 用户输入的源节点和目的节点写在 `fixed_topology_node_id`，平台同时给出 `topology_alias`、`business_ip/business_ipv6` 便于路由系统匹配和展示。
- 源节点和目的节点可以是物理终端节点，也可以是物理计算节点；在 DAG 里它们仍然只是 `source/sink` 子任务角色。
- source/sink 是否启动端点容器由平台工单的 `platform_deployment.deployable_roles` 决定；例如 `["source","compute","sink"]` 表示三类角色都部署，`["compute"]` 表示 source/sink 只作为路由端点。
- `compute` 是路由系统通常需要选择真实拓扑节点的位置。
- `edges[].bandwidth_mbps` 是带宽需求估计，可作为选路参考。
- `nodes[].network.port_requirements` 是逻辑端口需求，路由系统不要提前分配真实端口。
- 用户接入演示中，source/sink 可能额外包含 `business_ip`、`business_port`、`callback_url`。其中 `business_port` 是用户在前端登记或手动启动 receiver 时选择的目的端口，不是平台或路由系统动态分配的端口。
- `priority` 和 `edges[].flow.priority` 用于识别业务流优先级，取值 `1-8`，`1` 最高。该值由平台“系统设置 -> 模态优先级字典”维护。
- `edges[].flow` 用于识别业务流和目标端口引用；真实目标 IP/端口在 `/result` 响应的 `network_bindings` 中返回。路由系统可结合 `priority` 对不同业务流下发 QoS 或路径策略。
- 新生成的 DAG 中 `modal` 使用中文业务模态名，例如 `高通量计算模态`、`低时延转发模态`；`routing_strategy` 使用英文策略枚举，例如 `resource_guarantee`、`low_latency_forwarding`。不要把二者合并为一个字段。

## 8. 支持的 DAG 形态

### 8.1 `source -> compute -> sink`

默认业务链路。路由系统只需要选择 `compute` 的 `topology_node_id/gpu_device`，路径可放到 `metadata.path`。平台是否部署 `source/sink` 容器由 `runtime_config.platform_deployment.deployable_roles` 决定：

- 用户演示模式通常是 `["compute"]`，`source/sink` 只作为用户端数据面端点。
- 自动化测评模式通常是 `["source","compute","sink"]`，平台会在管控测试端点部署三类容器。

如果路由系统只回写 compute：

```json
{
  "strategy": "resource_guarantee",
  "placements": [
    {"task_node_id": "compute", "topology_node_id": "compute-node-a", "gpu_device": "0"}
  ],
  "metadata": {
    "path": ["terminal-a", "compute-node-a", "terminal-b"]
  }
}
```

如果当前工单需要部署 source/sink，平台会自动补齐 source/sink placement，并返回真实业务 IP/端口绑定；如果 source/sink 不部署，返回的 `network_bindings` 会把外部端点和 compute 接入地址标清楚。

用户目的端如需接收 compute 回调，可手动启动 endpoint receiver，例如 `python /app/src/receiver_main.py --port 9000`。平台会把 `callback_url=http://[<sink-business-ipv6>]:9000/callback` 注入 compute；路由系统只需按 `/result` 返回的 `network_bindings` 下发网络规则，不需要访问或管理 receiver 进程。

### 8.2 `source -> sink`

两个节点都是终端，只需要计算路径，不需要部署业务容器。该模式只用于路由联调或路径验证，不用于业务目标成功率测评。

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

源节点是终端，目的侧承担计算角色。目的节点可以是物理计算节点。若平台只部署 compute 容器，则 `platform_deployment.deployable_roles=["compute"]`；路由系统只需要回写 compute：

```json
{
  "strategy": "resource_guarantee",
  "placements": [
    {"task_node_id": "compute", "topology_node_id": "compute-node-a", "gpu_device": "0"}
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
    {"task_node_id": "compute", "topology_node_id": "compute-node-a", "gpu_device": "0"}
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
- `route_only` 工单也属于“不创建容器实例”：响应会包含 `deployment_required=false`、`deployment_mode=route_only`、`instance_id=null`。这表示“路由方案已生成”，不是“业务容器已部署完成”。
- 如果需要部署容器，平台会物化实例、动态分配端口，并返回 `network_bindings`。
- `/result` 返回后若 `network_ready_required=true`，工单进入 `routing_status=network_binding_ready`，表示“端口绑定已生成，等待路由系统下发流表/QoS”，不是业务已完成。
- 路由系统完成下发后调用 `/network-ready`，平台才把 `routing_status` 推进到 `completed`，并按需启动或注册启动计划。
- 如果 GPU 冲突，平台返回 `409`，路由系统需要撤销本次资源扣减并重新路由或 requeue。
- 如果 HTTP 超时，路由系统应先查询该工单状态；若已进入 `network_binding_ready` 或 `completed`，按平台已有结果继续处理，不要重复扣资源。若仍为 `computing` 且没有结果，再按路由系统自己的幂等策略决定是否重新回写同一结果。

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
      "task_type": "low_latency_video_pipeline",
      "modal": "低时延转发模态",
      "priority": 1,
      "src_topology_node_id": "terminal-a",
      "src_host": "terminal-a",
      "src_ip": "fd00::10",
      "dst_topology_node_id": "compute-node-a",
      "dst_host": "compute-node-a",
      "dst_ip": "fd00::21",
      "dst_port": 18842,
      "dst_named_ports": {"compute": 18842},
      "dst_port_ref": "compute.compute",
      "protocol": "tcp",
      "data_mb": 20,
      "bandwidth_mbps": 20
    }
  ]
}
```

字段契约：

| 字段 | 含义 |
|------|------|
| `src_topology_node_id` / `dst_topology_node_id` | 真实拓扑资产 ID；若节点没有资产 ID，则退化为 `nodes.hostname`。 |
| `src_host` / `dst_host` | 平台节点别名，对应 `nodes.hostname`。 |
| `src_ip` / `dst_ip` | 数据面 IP，受平台 `PREFER_BUSINESS_IPV6` 配置影响。 |
| `dst_port` / `dst_named_ports` | 目的端实际监听端口。平台部署的容器端口由平台动态分配；用户外部 sink 端口来自用户登记的 `business_port`。 |
| `dst_access_url` | 平台建议的访问地址；如果用户提供 `callback_url`，这里会等于该回调地址。 |
| `src_external` / `dst_external` | `true` 表示该端点不是本次平台部署的容器，而是用户或外部端点。 |

路由系统拿到 `network_bindings` 后，应按其中的源/目的 IP、目的端口下发真实网络规则；如需差异化 QoS，可结合工单模态、`priority`、`routing_strategy` 和路由系统自身策略处理。策略字典见本文档第 2 节冻结约定，避免把“低时延转发模态”和“低时延转发策略”混为一个字段。

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
- `auto_start` 默认 `true`。如果只想联调接口、不启动容器，可以传 `"auto_start": false`。
- 如果业务结束时间已过，平台不会启动实例，会标记为过期/失败，避免过期工单误运行。

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

业务容器还有连接等待机制：`PEER_CONNECT_TIMEOUT_SEC` 和 `PEER_WAIT_TIMEOUT_SEC` 默认 600 秒。即使路由系统确认后流表传播有延迟，worker 也会持续重试一段时间，不会立即失败。

## 10. GPU 独占和资源释放

验收业务默认 GPU 独占：

```text
同一 topology_node_id + gpu_device
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

路由同学或 AI 实现完最小版本后，按下面测试用例自测。测试前建议在平台前端新建一轮“外部路由系统”模式的 benchmark 工单，并只处理当前轮次的 pending 工单。

通用环境变量：

```bash
export PLATFORM_API_BASE=http://10.112.244.94:8181
```

### 用例 1：能读取并领取待路由工单

目的：验证路由系统能拿到平台生成的新 DAG，并用 claim 防止重复处理。

最短自检命令：

```bash
python3 scripts/mock_external_router.py \
  --base-url "$PLATFORM_API_BASE" \
  --dry-run
```

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

最短自检命令：

```bash
python3 scripts/mock_external_router.py \
  --base-url "$PLATFORM_API_BASE" \
  --limit 1 \
  --compute-nodes compute-1,compute-2,compute-3 \
  --gpu-device 0
```

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
      {"task_node_id": "compute", "topology_node_id": "<chosen-topology-node-id>", "gpu_device": "0"}
    ],
    "metadata": {
      "path": ["<source>", "<chosen-topology-node-id>", "<sink>"],
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
- `network_bindings` 中能看到每条业务流的 `src_ip`、`dst_ip`、`dst_port` 和端口名。
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

目的：验证平台部署前校验生效，防止路由系统误把同一 GPU 分给多个未释放任务。

步骤：

1. 创建两个时间窗口重叠的 GPU 工单。
2. 第一个工单回写 `topology_node_id=A, gpu_device=0` 并成功。
3. 第二个工单也回写同一个 `topology_node_id=A, gpu_device=0`。

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
3. source/sink 的真实节点名来自 routing_input_dag.nodes[].fixed_topology_node_id，不要改；是否部署端点容器只看平台工单里的 platform_deployment.deployable_roles。
4. GPU 任务必须独占 GPU，同一 topology_node_id + gpu_device 不能分配给多个未释放任务。
5. 资源暂时不足要 requeue，不要 failed；确定无法满足才 failed。
6. 平台路由接口不需要 token；HTTP 超时建议设置为 120 秒。
7. POST /result 后必须读取响应里的 network_bindings，并按其中 src_ip/dst_ip/dst_port 下发网络规则。
8. 网络规则下发完成后必须调用 POST /api/routing-orders/{order_id}/network-ready。
9. 终端机器通常也具备容器部署能力；某个任务是否部署 source/sink 容器由平台工单决定，路由系统不要自行推断。

需要实现：
1. 调 GET /api/routing-resource-events?event_type=release&unacked=true 读取释放事件，把 GPU 加回自己的资源表，再调 POST /api/routing-resource-events/ack。
2. 调 GET /api/routing-orders?status=pending&limit=100 获取待路由工单。
3. 对每个工单调 PATCH /api/routing-orders/{order_id}/claim，409 表示别人抢到了，跳过。
4. 解析 routing_input_dag，读取 nodes 和 node_baselines，选择 compute 的 topology_node_id/gpu_device。
5. 成功时调 POST /api/routing-orders/{order_id}/result，业务 placements 只需要回写 compute；平台会补齐 source/sink。未 claim 直接回写会返回 409。
6. 如果 /result 返回 409，撤销本地资源扣减，requeue 或重新计算。
7. 如果 /result 超时，查询该 order 状态；如果已经 network_binding_ready/completed，不要重复扣资源，直接继续读取已有 network_bindings。
8. 根据 network_bindings 下发流表；如需要 QoS，可结合业务模态 `modal/priority` 和选路偏好 `routing_strategy` 决定。
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

## 16. 路由模式与开发调试开关

平台前端有两种路由方式：

| 模式 | 用途 |
|------|------|
| 外部路由系统 | 平台只创建 pending 工单，等待外部路由回写。该模式用于与路由服务联调。 |
| 系统自动路由 | 平台内置的节点放置流程，可通过系统设置页切换，用于快速验证部署闭环。 |

系统自动路由不是外部路由算法，不用于验证路由策略效果；与路由同学联调时请使用“外部路由系统”配置。

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
- 平台系统设置为“外部路由系统”时，会拒绝 `/api/orders/batch-auto-route` 和 `/api/orders/{order_id}/auto-route` 内置自动路由接口。
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
5. 前端确认工单变为已分配，能看到 compute/GPU。
6. 平台启动任务并完成业务指标评估。
7. 清理实例，确认路由系统能处理 release 事件。
8. 扩展到 30 个工单的正式业务目标成功率测评。
