# 业务目标成功率与路由结果接入设计

> 历史设计归档：本文用于解释业务目标成功率口径，不作为当前路由系统接口规范。
> 当前唯一对接规范见 [routing-system-integration-guide.md](/Users/yanjia/codes/manage_deploy/docs/routing-system-integration-guide.md)。
> 当前 placement 只接受 `task_node_id`、`topology_node_id`、`gpu_device`。

本文记录“业务目标成功率”的统一定义、过程性指标方案、历史基准能力判定，以及外部路由系统回写 placements 和 GPU 分配结果后的部署衔接方式。当前矩阵乘法主链路已接入 `/benchmark` 验收页面；视频 AI 推理作为扩展业务已具备轻量 worker、baseline fallback、镜像构建入口和页面工单创建能力；模型训练/文本生成保持指标契约预留。

## 总体原则

业务目标成功率不直接评价路由算法是否全局最优，而是评价任务被路由、部署并运行后，是否达到该业务类型定义的过程性性能目标。

由于不同业务输入规模和总运行时间差异较大，平台不使用“任务总完成时间”作为统一业务目标。每类业务定义一个可持续观测的过程性指标，并与该节点在相同业务 profile 下的历史基准能力比较。

核心边界：

- 外部路由系统：根据 DAG、资源需求和路由策略选择物理节点，并为需要 GPU 的业务节点分配 GPU 编号。
- Task Manager：接收路由结果，校验节点和 GPU 分配，物化 TaskInstance，并按业务时间窗口调度部署。
- 业务目标评估：任务运行后采集过程性指标，与所部署节点对应历史基准比较，判断业务目标是否达成。

正式验收建议以“单轮测评”为统计边界。每次批量创建验收工单时生成 `benchmark_run_id`，同一轮的工单创建、路由回写、实例启动、指标上报和成功率统计均绑定该编号。这样可以重复跑多轮测试而不混淆历史数据，也便于专家根据页面截图、后端 JSON 和工单详情复核证据链。

## 任务结构假设

第一阶段默认每个任务只有一个核心业务计算节点。代码实现中核心计算角色统一使用 `compute`，文档叙事中 `worker` 与 `compute` 等价：

```text
source -> compute/worker -> sink
```

- `source`：数据源或任务发起角色，通常不需要 GPU。
- `worker`：核心业务计算节点，默认只分配一个，通常需要 GPU。
- `sink`：结果汇总、指标上报和归档角色，通常不需要 GPU。

默认约束：

- 一个任务只有一个 `worker`。
- 一个 `worker` 最多使用一个 GPU。
- 路由结果需要说明每个逻辑子任务放在哪台物理节点。
- 对需要 GPU 的逻辑子任务，路由结果需要返回分配的 GPU 编号。
- 多个业务类型可以复用同一个 source/compute/sink 模板；物化实例时必须优先使用工单中的 `task_type` 定位 `business_template_catalog`，再按模板节点名生成 overrides，避免只按 `template_id` 查询造成 catalog 歧义。

## 业务类型与过程性指标

当前业务类型收敛为三类：

| 业务类型 | 当前负载 | 过程性指标 | 判定方向 |
|---|---|---|---|
| 通用计算 | 矩阵乘法批处理 | `effective_gflops` | 越高越好 |
| 模型训练 | 固定文本模型 + 固定文本数据集训练 | `tokens_per_second` | 越高越好 |
| 视频推理 | 固定视频帧或图片序列推理 | `frame_latency_p90_ms` | 越低越好 |

文本 LLM 类任务合并到模型训练类。模型训练采用固定小文本模型和固定文本数据集，边训练边统计 `tokens_per_second`。

每类业务都需要设置最小统计窗口，避免任务太短导致指标缺失或容器启动后立即结束。

建议：

| 业务类型 | warmup | measured workload |
|---|---:|---:|
| 通用计算 | 3 批矩阵 | 至少 30 批矩阵 |
| 模型训练 | 5 step | 50-100 training steps |
| 视频推理 | 10 帧 | 90 帧 |

如果任务启动但未采集到足够指标，判定为不可达标：

```text
business_success = false
failure_reason = metrics_incomplete
```

当前矩阵乘法实现采用“任务结束后汇总过程性指标”的轻量方案：compute 节点在 warmup 后持续采样，sink 节点一次性上报 `effective_gflops` 中位数以及 `sample_count`、`observed_duration_sec`、`mean/min/max_effective_gflops`、`samples` 等元数据。这样既能说明指标来自运行过程，又避免为了验收页面引入实时 CPU/GPU 监控系统。资源监控可作为演示增强项，但正式判定仍以最终上报的业务指标、工单详情、节点/GPU 分配和指标 JSON 为准。

视频推理业务采用轻量“工业检测抽帧”负载，不强制真实传输完整视频流。当前已提供 `workers/low-latency-video/` 最小 worker：source 节点读取固定测试视频并按 `frame_stride=30` 抽帧发送给 worker；worker 默认执行 YOLOv5n ONNX 推理，必要时可退回本地兜底路径，记录每帧处理时延；sink 汇总有效阶段 `frame_latency_p90_ms` 并上报。这样符合“低时延视频 AI 推理/工业检测”模态，又避免批量测评时完整视频流量压垮实验网络。后续如果替换真实模型，只需要保持 `frame_latency_p90_ms` 指标契约不变。

文本模型训练业务建议使用固定小文本模型和固定 token 序列，指标为 `tokens_per_second`。第一阶段可使用轻量训练 surrogate：worker 以固定 batch_size 和 sequence_length 执行若干 training step，跳过 warmup 后统计有效 token 数和耗时；如果后续需要更强真实性，再替换为小型 Transformer/GPT-2 训练容器。验收口径不依赖训练是否达到某个 loss，而是评价该节点在固定 profile 下的训练吞吐是否达到历史基准。

## 历史基准能力

每台节点需要提前在固定业务 profile 下进行基准测试，形成历史基准能力表。

建议字段：

```text
node_id
business_type
profile_id
accelerator
baseline_metric_key
baseline_metric_value
baseline_stat
measured_at
```

示例：

```text
compute-1 / matmul / gpu_standard / gpu / effective_gflops / 420
compute-2 / matmul / gpu_standard / gpu / effective_gflops / 410
compute-3 / training_text / small_text_model / gpu / tokens_per_second / 12000
compute-3 / video_infer / video_industrial_inspection_720p / gpu / frame_latency_p90_ms / 35
```

历史基准用于两件事：

- 给外部路由系统提供节点能力依据。
- 给业务目标评估提供达标阈值。

## 单任务业务目标判定

越高越好的指标：

```text
actual_metric >= baseline_metric * success_ratio
```

第一阶段建议：

```text
success_ratio = 0.8
```

适用指标：

- `effective_gflops`
- `tokens_per_second`

越低越好的指标：

```text
baseline_metric / actual_metric >= success_ratio
```

第一阶段建议：

```text
success_ratio = 0.8
```

等价为 `actual_metric <= baseline_metric / 0.8`。这样矩阵、视频等业务都统一解释为“端到端运行后的业务能力至少保持历史基线能力的 80%”。视频 AI 推理的正式 baseline 必须来自同一节点、同一视频参数、同一 YOLO 权重和 GPU 推理路径；CPU 或兜底模拟推理只用于开发排障，不参与正式成功率判定。

适用指标：

- `frame_latency_p90_ms`

单个工单业务目标达成条件：

```text
任务部署成功
AND 指标采集完整
AND 实测过程性指标达到该节点、该业务 profile 的历史基准阈值
```

## 业务目标成功率

任务书名称保持为：

```text
业务目标成功率
```

统一定义：

```text
业务目标成功率 = 业务目标达成工单数 / 已完成且可评价工单数 × 100%
```

验收口径：

```text
在预设测试任务集中，业务目标成功率 >= 90%，则认为满足验收要求。
```

例如测试 30 个任务，至少 27 个业务目标达成即通过。

## 路由策略与业务目标关系

路由策略决定任务放在哪里运行，业务目标评估判断任务运行后是否达标。两者不冲突。

当前阶段路由策略可以是资源约束驱动的简单放置策略，例如选择 GPU 数量满足要求的节点。业务目标成功率不评价该策略是否全局最优，只评价任务在选定节点运行后是否达到该节点历史基准能力要求。

推荐表述：

```text
当前阶段验证的是平台能否按不同路由策略完成放置、部署、运行和指标评估闭环；业务目标成功率评价的是运行效果是否达到历史基准能力，而不是评价路由算法全局最优性。
```

## DAG 资源需求口径

意图解析和工单创建阶段生成的 DAG 中，每个逻辑节点都需要填写 `resources`，供外部路由系统进行容量过滤和放置决策。这里的资源值采用“估算资源契约”，不是运行时实时监控值。

生成原则：

- 根据 `task_type`、`data_profile` 和固定业务 profile 模板估算 CPU、内存、磁盘和 GPU 数量。
- 估算值应保证业务能稳定运行，并保留少量余量；不追求精确反映每次任务的瞬时资源占用。
- 需要 GPU 的核心计算节点默认声明 `gpu_units=1`，并由外部路由结果返回具体 `gpu_device`。
- source 和 sink 默认声明轻量 CPU/内存资源，通常不需要 GPU。
- 业务目标判定不使用这些估算资源值，而使用任务实际运行后上报的过程性指标和所部署节点 baseline。

这样可以讲通系统边界：DAG 资源需求负责“能不能放、放哪里”，业务目标成功率负责“放上去跑完以后效果是否达标”。后续如果接入真实资源监控，可以把监控数据用于优化估算模型，但不改变当前验收口径。

## 外部路由结果接收接口

> 注：本节是早期设计说明。当前实际对接以
> [routing-system-integration-guide.md](/Users/yanjia/codes/manage_deploy/docs/routing-system-integration-guide.md)
> 为准；演示验收阶段的路由接口不加 token，路由系统通过工单 ID 回写结果。

当前推荐接口：

```http
POST /api/routing-orders/{order_id}/result
Content-Type: application/json
```

成功结果示例：

```json
{
  "external_routing_id": "route-20260527-0001",
  "strategy": "resource_guarantee",
  "placements": [
    {"task_node_id": "compute", "topology_node_id": "compute-3", "gpu_device": "0"}
  ],
  "metadata": {
    "path": ["compute-1", "compute-3", "compute-2"],
    "selected_reason": "compute-3 GPU 0 is available"
  },
  "estimated_metric": {
    "metric_key": "estimated_runtime_ms",
    "metric_value": 600000,
    "unit": "ms"
  }
}
```

失败结果示例：

```json
{
  "external_routing_id": "route-20260527-0002",
  "status": "failed",
  "error_message": "No node has enough available GPU resources",
  "decision_trace": {
    "required_gpu_units": 1,
    "candidate_count": 0
  }
}
```

## 接收结果后的平台行为

收到 `completed`：

```text
1. 校验 task_order 是否存在，状态是否 pending/computing。
2. 校验 placements 使用数组格式，且只包含 `task_node_id/topology_node_id/gpu_device`。
3. 根据 `topology_node_id` 匹配平台 `nodes.hostname`。
4. 校验 compute 节点可调度、Node Agent 可达、GPU 编号格式合法。
5. 保存 placements、metadata、selected_strategy、external_routing_id。
6. 将 routing_result 同步写入 task_order.runtime_config，便于后续业务目标评估按 compute 节点查找 baseline。
7. 根据 placements 创建或更新 TaskInstance，并返回 `network_bindings`。
8. 路由系统下发流表后调用 `network-ready`，平台再启动或注册调度。
```

收到 `failed`：

```text
task_order.routing_status = failed
task_order.error_message = error_message
不创建 TaskInstance
```

## GPU 分配落地

当前外部路由对接统一使用 `placements[]` 数组格式。source/sink 固定端点由平台根据 DAG 补齐，路由系统通常只回写 compute：

```json
[
  {"task_node_id": "compute", "topology_node_id": "compute-3", "gpu_device": "0"}
]
```

路由结果中的：

```json
"gpu_device": "0"
```

平台部署 worker 容器时可转换为：

```text
CUDA_VISIBLE_DEVICES=0
```

或 Docker GPU device request。

如果 `gpu_device` 为空：

```text
不分配 GPU
CUDA_VISIBLE_DEVICES 可以为空或不注入
```

## GPU 槽位占用与路由职责边界

真实外部路由系统接入后，GPU 是否可分配应由路由/资源分配逻辑优先判断。路由系统需要基于节点资源、任务开始/结束时间、已运行实例和已预约资源，避免把新的 GPU 任务分配到已占用的 `节点 + GPU 编号` 槽位。

平台侧不能完全信任路由结果，必须做部署前兜底：

- 接收 placements 后校验节点可调度、Node Agent 可达、GPU 编号格式合法。
- 校验 `节点 + GPU 编号` 在目标时间窗口内没有被运行中任务或已预约任务占用。
- 校验通过后写入资源预约/锁定记录，并在启动容器时注入 `GPU_DEVICE`、`CUDA_VISIBLE_DEVICES` 或 Docker GPU device request。
- 如果路由计算后到实际启动前发生资源冲突，平台应拒绝启动该实例，并将工单标记为需要重路由、等待资源或失败，而不是静默抢占 GPU。
- 任务结束、失败清理或手动清理实例后，平台释放对应 GPU 槽位；工单、路由结果和业务评估证据可以继续保留。

当前 `/benchmark` 页面的“执行槽位设置”属于验收测评工具链的受控执行限流，用于在内置随机路由策略阶段避免多个测评任务争用同一节点/GPU 导致业务目标误判。它不替代真实路由算法，也不改变正式对接时“路由负责选择，平台负责校验和执行兜底”的职责划分。

## 最终故事

用户通过对话提交业务工单，系统解析业务类型、源节点、目的节点、时间窗口和资源需求，生成外部路由系统可消费的 DAG。外部路由系统根据 DAG 中每个子任务的资源需求选择物理节点，并为需要 GPU 的 worker 分配 GPU 编号。平台接收路由结果后，将逻辑 DAG 物化为可部署任务实例，并按业务时间窗口自动调度运行。任务运行过程中采集业务类型对应的过程性性能指标，并与该节点历史基准能力比较，判断业务目标是否达成。最终通过业务目标成功率统计平台对业务需求的满足程度。
