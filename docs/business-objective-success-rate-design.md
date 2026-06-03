# 业务目标成功率与路由结果接入设计

本文记录“业务目标成功率”的统一定义、过程性指标方案、历史基准能力判定，以及外部路由系统回写 placements 和 GPU 分配结果后的部署衔接方式。当前为设计方案，不代表已全部实现。

## 总体原则

业务目标成功率不直接评价路由算法是否全局最优，而是评价任务被路由、部署并运行后，是否达到该业务类型定义的过程性性能目标。

由于不同业务输入规模和总运行时间差异较大，平台不使用“任务总完成时间”作为统一业务目标。每类业务定义一个可持续观测的过程性指标，并与该节点在相同业务 profile 下的历史基准能力比较。

核心边界：

- 外部路由系统：根据 DAG、资源需求和路由策略选择物理节点，并为需要 GPU 的业务节点分配 GPU 编号。
- Task Manager：接收路由结果，校验节点和 GPU 分配，物化 TaskInstance，并按业务时间窗口调度部署。
- 业务目标评估：任务运行后采集过程性指标，与所部署节点对应历史基准比较，判断业务目标是否达成。

正式验收建议以“单轮压测”为统计边界。每次批量创建验收工单时生成 `benchmark_run_id`，同一轮的工单创建、路由回写、实例启动、指标上报和成功率统计均绑定该编号。这样可以重复跑多轮测试而不混淆历史数据，也便于专家根据页面截图、后端 JSON 和工单详情复核证据链。

## 任务结构假设

第一阶段默认每个任务只有一个核心业务计算节点：

```text
source -> worker -> sink
```

- `source`：数据源或任务发起角色，通常不需要 GPU。
- `worker`：核心业务计算节点，默认只分配一个，通常需要 GPU。
- `sink`：结果汇总、指标上报和归档角色，通常不需要 GPU。

默认约束：

- 一个任务只有一个 `worker`。
- 一个 `worker` 最多使用一个 GPU。
- 路由结果需要说明每个逻辑子任务放在哪台物理节点。
- 对需要 GPU 的逻辑子任务，路由结果需要返回分配的 GPU 编号。

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

当前矩阵乘法实现采用“任务结束后汇总过程性指标”的轻量方案：compute 节点在 warmup 后持续采样，sink 节点一次性上报 `effective_gflops` 中位数以及 `sample_count`、`observed_duration_sec`、`mean/min/max_effective_gflops`、`samples` 等元数据。这样既能说明指标来自运行过程，又避免为了验收页面引入实时监控系统。后续如要增强演示效果，可在 UI 中轮询工单详情和实例事件，但正式判定仍以最终上报的业务指标为准。

视频推理业务可以采用轻量“工业检测抽帧”负载，不强制真实传输完整视频流。推荐 source 节点生成固定视频帧元数据或小尺寸合成图片，并按 `frame_stride=30` 抽帧发送给 worker；worker 模拟或执行固定模型推理，记录每帧处理时延；sink 汇总有效阶段 `frame_latency_p90_ms`。这样符合“低时延视频 AI 推理/工业检测”模态，又避免批量压测时完整视频流量压垮实验网络。

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
compute-1 / matmul / cpu_standard / cpu / effective_gflops / 60
compute-2 / matmul / gpu_high / gpu / effective_gflops / 420
compute-3 / training_text / small_text_model / gpu / tokens_per_second / 12000
compute-3 / video_infer / video_720p / gpu / frame_latency_p90_ms / 35
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
actual_metric <= baseline_metric * tolerance_ratio
```

第一阶段建议：

```text
tolerance_ratio = 1.2
```

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

## 外部路由结果接收接口

建议提供接口：

```http
POST /api/routing-results/{routing_request_id}
X-Service-Token: <service-token>
Content-Type: application/json
```

成功结果示例：

```json
{
  "external_routing_id": "route-20260527-0001",
  "status": "completed",
  "strategy": "GPU_RESOURCE_FIT",
  "computed_at": "2026-05-27T15:30:00+08:00",
  "placements": {
    "source": {
      "node_name": "compute-1",
      "node_id": "optional-platform-node-id",
      "gpu_indices": [],
      "allocated_resources": {
        "cpu_units": 2,
        "mem_mb": 512,
        "disk_mb": 512,
        "gpu_units": 0
      }
    },
    "worker": {
      "node_name": "compute-3",
      "node_id": "optional-platform-node-id",
      "gpu_indices": [0],
      "allocated_resources": {
        "cpu_units": 10,
        "mem_mb": 2048,
        "disk_mb": 1024,
        "gpu_units": 1
      }
    },
    "sink": {
      "node_name": "compute-2",
      "node_id": "optional-platform-node-id",
      "gpu_indices": [],
      "allocated_resources": {
        "cpu_units": 2,
        "mem_mb": 512,
        "disk_mb": 512,
        "gpu_units": 0
      }
    }
  },
  "estimated_metric": {
    "metric_key": "estimated_runtime_ms",
    "metric_value": 600000,
    "unit": "ms"
  },
  "decision_trace": {
    "reason": "worker requires 1 GPU; compute-3 has available GPU 0",
    "candidate_count": 3,
    "selected_worker": "compute-3"
  },
  "raw_result": {}
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
1. 校验 routing_request 是否存在，状态是否 pending/computing。
2. 校验 placements 覆盖 DAG 中所有逻辑节点。第一阶段平台兼容 `{"compute": "compute-3"}` 简单格式，也兼容 `{"compute": {"node_name": "compute-3", "gpu_indices": [0]}}` 完整格式。
3. 根据 node_name、worker_host、hostname 或平台 node_id 匹配平台 nodes 表。
4. 校验 worker 节点可调度、Node Agent 可达、GPU 编号格式合法。
5. 保存 result_payload、placements、selected_strategy、external_routing_id。
6. 将 routing_request.status 置为 completed。
7. 将 task_order.routing_status 置为 completed。
8. 将 routing_result 同步写入 task_order.runtime_config，便于后续业务目标评估按 compute/worker 节点查找 baseline。
9. 根据 placements 创建或更新 TaskInstance。
10. 将业务时间窗口映射为 scheduled_start_time / scheduled_end_time。
11. 如果已到开始时间，则进入调度启动流程；否则等待调度器扫描启动。
```

收到 `failed`：

```text
routing_request.status = failed
task_order.routing_status = failed
task_order.error_message = error_message
不创建 TaskInstance
```

## GPU 分配落地

平台兼容两类 placements 格式。调试或 mock 路由可以使用简单格式：

```json
{
  "source": "compute-1",
  "compute": "compute-3",
  "sink": "compute-2"
}
```

正式外部路由对接建议使用完整格式：

```json
{
  "compute": {
    "node_name": "compute-3",
    "gpu_indices": [0],
    "allocated_resources": {
      "gpu_units": 1
    }
  }
}
```

路由结果中的：

```json
"gpu_indices": [0]
```

平台部署 worker 容器时可转换为：

```text
CUDA_VISIBLE_DEVICES=0
```

或 Docker GPU device request。

如果 `gpu_indices` 为空：

```text
不分配 GPU
CUDA_VISIBLE_DEVICES 可以为空或不注入
```

## 最终故事

用户通过对话提交业务工单，系统解析业务类型、源节点、目的节点、时间窗口和资源需求，生成外部路由系统可消费的 DAG。外部路由系统根据 DAG 中每个子任务的资源需求选择物理节点，并为需要 GPU 的 worker 分配 GPU 编号。平台接收路由结果后，将逻辑 DAG 物化为可部署任务实例，并按业务时间窗口自动调度运行。任务运行过程中采集业务类型对应的过程性性能指标，并与该节点历史基准能力比较，判断业务目标是否达成。最终通过业务目标成功率统计平台对业务需求的满足程度。
