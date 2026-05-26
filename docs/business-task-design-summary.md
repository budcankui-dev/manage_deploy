# 业务任务设计与验收需求总结

## 1. 验收需求概括

本项目需要构建一个从自然语言意图到业务任务部署与指标验证的闭环系统。

整体流程为：

1. 用户通过对话系统输入自然语言需求。
2. 意图解析系统解析任务类型、数据画像、业务目标、资源需求。
3. 不合理目标在意图解析阶段被拒绝，不提交数据库。
4. 外部路由系统根据任务需求、硬件画像、网络画像和策略选择 A/B/C 三个部署节点。
5. 当前部署系统接收标准化任务和路由结果，部署三节点随路计算任务。
6. 任务自动执行 A -> B -> C 单向数据流转。
7. C 节点汇总结果文件和业务指标，上报管理节点。
8. 系统判断实际指标是否满足业务目标，并统计业务目标成功率。

## 2. 系统边界

当前部署系统不负责自然语言解析和路由决策。

外部系统负责：

- 自然语言解析
- 任务参数生成
- 资源需求估算
- 目标值合法性校验
- 路由策略计算
- A/B/C 节点放置决策

当前部署系统负责：

- 接收入库后的标准化任务
- 根据路由结果部署容器
- 执行三节点 DAG
- 收集业务指标
- 存储结果文件
- 判断业务目标是否成功
- 统计业务目标成功率

## 3. 业务目标成功率定义

不合理目标不会进入部署数据库。

因此业务目标成功率定义为：

```text
业务目标成功率 =
已入库并部署的任务中，实际业务指标满足目标值的任务数
/
已入库并部署的任务总数
```

前提：

```text
已入库任务均已通过意图解析系统的目标合法性检查和资源可行性检查。
```

业务成功判断：

```text
actual_metric <= target_value
```

第一版建议统一使用“越小越好”的指标，降低实现复杂度。

## 4. 三节点业务协议

所有测试业务统一抽象为三节点单向随路计算：

```text
A Source -> B Compute -> C Sink
```

### A Source

负责准备输入数据。

数据可以来自：

- 镜像内置预置数据集
- 参数化合成数据
- 后续扩展的外部对象存储 URI

A 节点根据任务类型和数据画像选择或生成输入，并发送给 B。

### B Compute

负责执行业务处理。

例如：

- 图片推理
- 视频流随路处理
- 大模型文本生成
- 高通量矩阵计算
- 音频处理

B 节点处理完成后，将业务结果、统计信息、结果文件发送给 C。

### C Sink

负责业务结果汇聚。

C 节点职责：

- 接收 `result.json`
- 接收可选结果文件
- 上传结果到 MinIO
- 计算该任务唯一业务指标
- 上报指标到 Task Manager

### 4.4 节点间通信约束（强约束）

A→B→C 三节点是分布在不同 Worker 主机上的容器，节点间数据流必须按"分布式部署"的方式实现：

1. **必须通过网络通信**：节点间业务数据必须经由业务网络（Docker host 网络模式 + IPv6/IPv4 PEER URL）传输。
   - 上游节点作为服务端开放 listen 端口；下游节点通过平台注入的 PEER URL 主动拉取或被推送。
   - 协议建议 HTTP/gRPC，明确单向 A→B→C，不允许反向调用业务接口。
   - 不允许通过共享卷（NFS、`/scratch` bind mount 等）、宿主机文件、对象存储中转等方式传递**业务数据**。MinIO 仅用于 C Sink 归档结果文件。
2. **必须如实声明 `ports`**：每个业务节点的模板节点配置必须显式声明监听端口，让 [`backend/api/instances.py`](../backend/api/instances.py) preflight 与 [`node_agent/port_utils.py`](../node_agent/port_utils.py) 的端口占用检测覆盖到，避免同机重复部署或与其他业务发生端口冲突。
3. **平台职责**：Task Manager 在物化实例时根据模板 `port_defs` + 路由 placements 生成 PEER URL 宏（如 `PEER_SOURCE_URL_*`、`PEER_COMPUTE_URL_*`），注入下游容器的环境变量。

当前科学计算矩阵乘法演示（`high_throughput_matmul`）已按该约束通过 HTTP 传递 source -> compute -> sink 的业务数据，并在模板节点上声明端口。演示说明见 [`scientific-matmul-demo.md`](scientific-matmul-demo.md)。

## 5. 数据画像设计原则

数据画像由任务类型决定。

不要只使用通用 `size_mb`，而应为每类任务定义专属数据画像。

### 预置数据型

适用于演示性强的多模态任务：

- 图片推理
- 视频流随路处理
- 大模型文本生成
- 音频处理

示例：

```json
{
  "task_type": "low_latency_video_pipeline",
  "data_profile": {
    "profile_id": "video_720p_frame_stream",
    "source": "preset",
    "dataset": "demo_videos",
    "file": "traffic_720p_5s.mp4",
    "resolution": "1280x720",
    "fps": 30,
    "clip_duration_sec": 5
  }
}
```

### 合成数据型

适用于可控计算任务：

- 科学计算
- 矩阵计算
- FFT
- CUDA benchmark

示例：

```json
{
  "task_type": "high_throughput_matmul",
  "data_profile": {
    "profile_id": "matmul_4096_batch",
    "source": "generated",
    "matrix_size": 4096,
    "batch_count": 8,
    "seed": 42
  }
}
```

## 6. 业务设计原则

每类业务必须提前定义一张业务卡片，包括：

1. 任务类型 `task_type`
2. 数据画像 `data_profile`
3. 核心业务指标 `metric_key`
4. 指标方向，第一版统一为 `<=`
5. 默认档位：`loose`、`normal`、`strict`
6. 合法目标范围 `valid_range`
7. 业务内部固定参数
8. 容器环境变量映射
9. 结果文件格式
10. 成功判断规则
11. 自然语言映射规则
12. 可评估的解析字段清单
13. 用户示例输入与标准解析结果

原则：

- 每个任务只保留一个核心业务指标。
- 指标尽量选择稳定、容易复现、容易解释的指标。
- 不合理目标在意图解析阶段拒绝。
- 部署系统只接收已标准化、已校验的任务。
- 演示型任务优先使用预置真实样例数据。
- 科学计算类任务优先使用参数化合成数据。
- 业务结果文件统一落到 MinIO，方便前端展示。
- 设计业务卡片时必须同步设计自然语言如何映射到任务参数，避免后续无法计算意图参数解析准确率。
- 每个业务至少准备一组标注样例，包含用户输入、标准任务类型、标准数据画像和标准业务目标。
- 用户意图参数、系统调优参数和硬件部署参数必须分层，避免把系统自动决策字段错误纳入意图解析准确率。

## 7. 参数分层设计

为降低自然语言解析难度，并提升业务目标成功率，任务参数分为三层。

### 用户意图参数

用户意图参数来自自然语言输入，用于计算意图参数解析准确率。

典型字段：

- `task_type`
- `data_profile`
- `business_objective`

示例：

```json
{
  "task_type": "llm_text_generation",
  "data_profile": {
    "profile_id": "prompt_batch_128"
  },
  "business_objective": {
    "metric_key": "seconds_per_100_tokens",
    "operator": "<=",
    "target_value": 5,
    "unit": "s/100_tokens"
  }
}
```

### 系统调优参数

系统调优参数由意图解析系统或任务规划模块根据用户目标自动生成，不要求用户直接输入。

这些参数用于达成业务目标，但不直接参与自然语言字段解析准确率。

典型字段：

- 大模型任务：`model_profile`、`quantization`、`batch_size`、`concurrency`、`max_output_tokens`
- 视频随路处理任务：`codec`、`preset`、`gop`、`frame_batch_size`、`process_mode`
- 图片推理任务：`model_profile`、`precision`、`batch_size`
- 科学计算任务：`algorithm`、`precision`、`iterations`

示例：

```json
{
  "runtime_plan": {
    "model_profile": "llm_7b_int4",
    "quantization": "int4",
    "batch_size": 4,
    "concurrency": 2,
    "max_output_tokens": 256
  }
}
```

业务卡片需要声明可调参数空间和不可调约束，防止系统为了达成指标而改变业务语义。

示例：

```json
{
  "tunable_parameters": {
    "model_profile": ["llm_3b_int4", "llm_7b_int4"],
    "batch_size": [1, 2, 4],
    "concurrency": [1, 2, 4]
  },
  "fixed_constraints": {
    "prompt_dataset": "prompt_batch_128",
    "max_output_tokens": 256
  }
}
```

### 默认硬件部署参数

硬件部署参数由外部路由系统根据默认策略给出，不作为用户意图解析准确率的评估字段。

典型字段：

- A/B/C 节点放置结果
- 路由策略
- 默认 CPU/GPU/内存配置
- 管理网络和业务网络路径

示例：

```json
{
  "routing_result": {
    "strategy": "resource_guarantee",
    "placements": {
      "source": "node-a-id",
      "compute": "node-gpu-default-id",
      "sink": "node-c-id"
    }
  }
}
```

推荐表述：

```text
用户自然语言只映射为业务意图参数，包括任务类型、数据画像和目标 SLO。为达成目标，系统在业务卡片定义的可调参数空间内自动选择运行方案，例如模型规格、量化方式、batch size、并发数或编码参数。硬件部署参数由外部路由系统按默认策略给出，不作为用户意图解析准确率的评估字段。业务目标成功率衡量系统在默认部署环境和自动调优参数下是否达成用户目标。
```

## 8. 自然语言映射与解析准确率

业务卡片不仅是部署配置，也应作为意图解析系统的标注规范。

每类业务需要提前定义：

1. 用户可能怎么说
2. 哪些词映射到 `task_type`
3. 哪些词映射到 `data_profile`
4. 哪些词映射到 `business_objective`
5. 哪些业务目标会触发系统调优参数生成
6. 哪些目标值应该被接受
7. 哪些目标值应该被拒绝

这样才能构造意图解析测试集，并计算参数解析准确率。

推荐把解析准确率拆成字段级指标：

```text
任务类型准确率 = task_type 解析正确数 / 样本总数
数据画像准确率 = data_profile 解析正确数 / 样本总数
业务指标准确率 = metric_key 解析正确数 / 样本总数
目标值准确率 = target_value 解析正确数 / 样本总数
整体解析准确率 = 全部关键字段均正确的样本数 / 样本总数
```

如果需要评估系统自动生成的调优参数，应单独定义“任务规划准确率”或“调优方案达标率”，不要混入自然语言解析准确率。

业务卡片中的标注样例建议采用以下格式：

```json
{
  "utterance": "部署一个低时延视频转发任务，对 720p 视频流做 H.264 编码，端到端处理时延低于 200ms",
  "expected_parse": {
    "task_type": "low_latency_video_pipeline",
    "data_profile": {
      "profile_id": "video_720p_frame_stream"
    },
    "business_objective": {
      "metric_key": "end_to_end_latency_ms",
      "operator": "<=",
      "target_value": 200,
      "unit": "ms"
    },
    "expected_runtime_plan": {
      "codec": "h264",
      "preset": "ultrafast",
      "gop": 30,
      "frame_batch_size": 1
    }
  }
}
```

其中 `expected_runtime_plan` 是系统根据业务目标生成的参考运行方案，适合用于评估任务规划效果，不计入用户意图字段解析准确率。

例如大模型文本生成任务：

```json
{
  "utterance": "部署一个大模型文本生成服务，希望吞吐达到 20 tokens/s",
  "expected_parse": {
    "task_type": "llm_text_generation",
    "data_profile": {
      "profile_id": "prompt_batch_128"
    },
    "business_objective": {
      "metric_key": "seconds_per_100_tokens",
      "operator": "<=",
      "target_value": 5,
      "unit": "s/100_tokens"
    },
    "expected_runtime_plan": {
      "model_profile": "llm_7b_int4",
      "quantization": "int4",
      "concurrency": 2
    }
  }
}
```

也可以出现目标驱动的模型降级或量化选择：

```json
{
  "utterance": "文本生成任务吞吐要尽量高，至少达到 40 tokens/s",
  "expected_parse": {
    "task_type": "llm_text_generation",
    "data_profile": {
      "profile_id": "prompt_batch_128"
    },
    "business_objective": {
      "metric_key": "seconds_per_100_tokens",
      "operator": "<=",
      "target_value": 2.5,
      "unit": "s/100_tokens"
    },
    "expected_runtime_plan": {
      "model_profile": "llm_3b_int4",
      "quantization": "int4",
      "concurrency": 4
    },
    "planning_reason": "高吞吐目标优先选择更小参数量和量化模型"
  }
}
```

如果用户指定模型能力边界，则系统调优不能随意改变业务语义：

```json
{
  "utterance": "必须使用 7B 模型做文本生成，同时吞吐达到 80 tokens/s",
  "expected_decision": {
    "accepted": false,
    "reason": "target_throughput_exceeds_model_profile_capability",
    "suggested_target": {
      "metric_key": "seconds_per_100_tokens",
      "target_value": 5,
      "equivalent_tokens_per_second": 20
    }
  }
}
```

## 9. 推荐业务类型

推荐将测试业务和验收材料中的模态命名对齐：

| 验收模态 | 推荐业务 | 核心指标 | 叙事重点 |
|----------|----------|----------|----------|
| 高通量计算模态 | 大规模矩阵乘法 | `compute_latency_ms <= target_value` | 计算密集、批量计算、大科学装置 |
| 低时延转发模态 | 视频流随路处理 | `end_to_end_latency_ms <= target_value` | 视频流、低时延、透明转发、边缘处理 |
| 智算中心模态 | 大模型文本生成 | `seconds_per_100_tokens <= target_value` | 大模型、量化、吞吐、显存、智算资源 |

图片推理可以作为智算中心模态的低风险备选业务。

### 高通量计算模态：大规模矩阵乘法

```text
A: 发送矩阵任务参数或矩阵分块数据
B: 执行大规模矩阵乘法、batched GEMM 或 FFT
C: 接收 checksum、耗时、计算结果摘要
```

业务指标：

```text
compute_latency_ms <= target_value
```

特点：

- 对应大科学装置场景和高通量计算模态。
- 计算密集、参数可控、容易复现实验。
- 适合作为资源估算、策略对比和业务成功率统计的基准任务。

示例用户输入：

```text
运行一个高通量矩阵计算任务，矩阵规模 4096，要求计算完成时间小于 3 秒。
```

标准解析重点：

```json
{
  "task_type": "high_throughput_matmul",
  "modality": "high_throughput_compute",
  "data_profile": {
    "profile_id": "matmul_4096_batch",
    "matrix_size": 4096,
    "batch_count": 8,
    "precision": "fp32"
  },
  "business_objective": {
    "metric_key": "compute_latency_ms",
    "operator": "<=",
    "target_value": 3000,
    "unit": "ms"
  },
  "runtime_plan": {
    "algorithm": "batched_matmul",
    "precision": "fp32",
    "use_gpu": true,
    "tile_size": 128
  }
}
```

### 低时延转发模态：视频流随路处理

```text
A: 发送预置视频片段或帧流
B: 做随路处理，例如编码、压缩、抽帧、轻量推理或转码
C: 接收处理后视频/帧和延迟统计
```

业务指标：

```text
end_to_end_latency_ms <= target_value
```

注意：

- 该业务重点不是追求压缩后文件最小，而是体现低时延转发和随路处理。
- 视频质量、编码器、分辨率、处理方式由业务卡片固定或由系统调优参数选择。
- C 节点保存处理后预览视频、延迟轨迹和 `result.json`，方便前端展示。

示例用户输入：

```text
部署一个低时延视频转发任务，对 720p 视频流做 H.264 编码，端到端处理时延低于 200ms。
```

标准解析重点：

```json
{
  "task_type": "low_latency_video_pipeline",
  "modality": "low_latency_forwarding",
  "data_profile": {
    "profile_id": "video_720p_frame_stream",
    "resolution": "1280x720",
    "fps": 30,
    "clip_duration_sec": 5
  },
  "business_objective": {
    "metric_key": "end_to_end_latency_ms",
    "operator": "<=",
    "target_value": 200,
    "unit": "ms"
  },
  "runtime_plan": {
    "codec": "h264",
    "preset": "ultrafast",
    "gop": 30,
    "frame_batch_size": 1,
    "process_mode": "streaming"
  }
}
```

### 智算中心模态：大模型文本生成

```text
A: 发送预置 prompt 集合
B: 部署指定规格的大模型并生成文本
C: 接收 generated_outputs.jsonl 和统计信息
```

业务指标：

```text
seconds_per_100_tokens <= target_value
```

特点：

- 对应智算中心模态。
- 可以体现模型规格、量化方式、显存需求和吞吐目标之间的关系。
- 适合验证系统能否从用户目标映射出模型大小、量化方式、并发参数等调优方案。

说明：

用户通常会说“达到多少 tokens/s”。为保持第一版业务成功判断统一使用 `actual_metric <= target_value`，可以将吞吐目标转换为等价的耗时目标：

```text
seconds_per_100_tokens = 100 / tokens_per_second
```

例如用户要求 `20 tokens/s`，则标准化目标为：

```text
seconds_per_100_tokens <= 5
```

资源映射原则：

- 若用户要求高吞吐，可以选择更小参数模型、量化模型或更高并发配置。
- 若用户要求更强模型能力，可以选择更大参数模型，但对应吞吐目标必须更宽松。
- 意图解析阶段需要校验目标吞吐是否和模型规格、硬件画像匹配，不合理目标直接拒绝。

示例用户输入：

```text
部署一个大模型文本生成服务，用 7B 量化模型处理一批 prompt，希望吞吐达到 20 tokens/s。
```

标准解析重点：

```json
{
  "task_type": "llm_text_generation",
  "modality": "intelligent_computing_center",
  "data_profile": {
    "profile_id": "prompt_batch_128",
    "prompt_count": 128,
    "avg_input_tokens": 128,
    "avg_output_tokens": 256
  },
  "business_objective": {
    "metric_key": "seconds_per_100_tokens",
    "operator": "<=",
    "target_value": 5,
    "unit": "s/100_tokens"
  },
  "runtime_plan": {
    "model_profile": "llm_7b_int4",
    "quantization": "int4",
    "concurrency": 2,
    "max_output_tokens": 256
  }
}
```

### 智算中心模态备选：图片推理

```text
A: 发送预置图片
B: 执行图片分类或目标检测
C: 接收预测结果和标注图
```

业务指标：

```text
p90_inference_latency_ms <= target_value
```

特点：

- 工程风险低于大模型部署。
- 仍然可以体现 AI 推理、GPU 和显存需求。
- 可以作为智算中心模态的低成本演示或 fallback。

示例用户输入：

```text
用 GPU 跑一批 224 分辨率的图片分类，要求单帧 P90 推理时延低于 120ms。
```

标准解析重点：

```json
{
  "task_type": "image_inference",
  "modality": "intelligent_computing_center",
  "data_profile": {
    "profile_id": "image_demo_224_100",
    "image_count": 100,
    "resolution": "224x224"
  },
  "business_objective": {
    "metric_key": "p90_inference_latency_ms",
    "operator": "<=",
    "target_value": 120,
    "unit": "ms"
  },
  "runtime_plan": {
    "model_profile": "mobilenet_v3",
    "precision": "fp16",
    "batch_size": 1
  }
}
```

## 10. 低时延视频随路处理业务卡片示例

```json
{
  "task_type": "low_latency_video_pipeline",
  "modality": "low_latency_forwarding",
  "metric": {
    "metric_key": "end_to_end_latency_ms",
    "operator": "<=",
    "unit": "ms",
    "direction": "lower_is_better"
  },
  "data_profiles": [
    {
      "profile_id": "video_720p_frame_stream",
      "source": "preset",
      "file": "traffic_720p_5s.mp4",
      "resolution": "1280x720",
      "fps": 30,
      "clip_duration_sec": 5
    },
    {
      "profile_id": "video_1080p_frame_stream",
      "source": "preset",
      "file": "traffic_1080p_5s.mp4",
      "resolution": "1920x1080",
      "fps": 30,
      "clip_duration_sec": 5
    }
  ],
  "runtime_plan": {
    "codec": "h264",
    "preset": "ultrafast",
    "gop": 30,
    "frame_batch_size": 1,
    "process_mode": "streaming"
  },
  "target_levels": {
    "loose": 500,
    "normal": 300,
    "strict": 200
  },
  "valid_range": {
    "min": 100,
    "max": 1000
  }
}
```

用户输入映射规则：

```text
“端到端时延低于 200ms” -> target_value = 200
“低时延视频转发” -> strict -> target_value = 200
“普通实时转发” -> normal -> target_value = 300
“稳定转发优先” -> loose -> target_value = 500
```

如果用户输入：

```text
端到端时延低于 10ms
```

则意图解析系统拒绝：

```text
目标低于当前视频画像和默认硬件环境下的合法范围，不提交部署。
```

## 11. 推荐任务传递格式

外部系统传给部署系统的标准化任务：

```json
{
  "external_task_id": "intent-20260524-001",
  "task_type": "low_latency_video_pipeline",
  "modality": "low_latency_forwarding",
  "data_profile": {
    "profile_id": "video_720p_frame_stream",
    "source": "preset",
    "dataset": "demo_videos",
    "file": "traffic_720p_5s.mp4",
    "resolution": "1280x720",
    "fps": 30,
    "clip_duration_sec": 5
  },
  "business_objective": {
    "metric_key": "end_to_end_latency_ms",
    "operator": "<=",
    "target_value": 200,
    "unit": "ms"
  },
  "runtime_plan": {
    "codec": "h264",
    "preset": "ultrafast",
    "gop": 30,
    "frame_batch_size": 1,
    "process_mode": "streaming"
  },
  "resource_requirement": {
    "source": {
      "cpu_cores": 1,
      "memory_mb": 512
    },
    "compute": {
      "cpu_cores": 4,
      "memory_mb": 4096,
      "gpu_required": false,
      "bandwidth_mbps": 1000
    },
    "sink": {
      "cpu_cores": 1,
      "memory_mb": 512
    }
  },
  "routing_result": {
    "strategy": "completion_time_first",
    "placements": {
      "source": "node-a-id",
      "compute": "node-b-id",
      "sink": "node-c-id"
    },
    "estimated_metric": {
      "metric_key": "end_to_end_latency_ms",
      "metric_value": 180,
      "unit": "ms"
    }
  },
  "result_storage": {
    "backend": "minio",
    "bucket": "task-results",
    "prefix": "intent-20260524-001/"
  }
}
```

## 12. C 节点结果格式

C 节点生成并上传：

```json
{
  "instance_id": "xxx",
  "task_type": "low_latency_video_pipeline",
  "metric": {
    "metric_key": "end_to_end_latency_ms",
    "metric_value": 186.4,
    "unit": "ms"
  },
  "business_success": true,
  "target": {
    "operator": "<=",
    "target_value": 200
  },
  "objects": [
    {
      "name": "result.json",
      "uri": "s3://task-results/xxx/result.json"
    },
    {
      "name": "processed_preview.mp4",
      "uri": "s3://task-results/xxx/outputs/processed_preview.mp4"
    },
    {
      "name": "latency_trace.json",
      "uri": "s3://task-results/xxx/outputs/latency_trace.json"
    }
  ]
}
```

## 13. MinIO 存储规范

建议路径：

```text
task-results/{instance_id}/result.json
task-results/{instance_id}/outputs/{filename}
```

示例：

```text
task-results/instance-001/result.json
task-results/instance-001/outputs/processed_preview.mp4
task-results/instance-001/outputs/latency_trace.json
task-results/instance-002/outputs/annotated_image.jpg
task-results/instance-003/outputs/generated_outputs.jsonl
```

数据库只保存指标和对象 URI，不保存大文件。

## 14. 最终推荐表述

本系统面向受控任务画像和已知硬件环境，完成自然语言任务解析后的自动部署与业务目标验证。每个任务被标准化为 A→B→C 三节点单向随路计算流水线，**节点间业务数据通过业务网络（PEER URL）传输，每个节点必须如实声明监听端口供 preflight 防冲突**。Source 根据数据画像准备输入，Compute 执行业务处理，Sink 汇聚结果、上传 MinIO 并上报唯一业务指标。业务目标成功率统计范围仅包含已通过意图解析和可行性校验、并提交部署系统的任务。系统通过实际业务指标是否满足目标值来判断任务是否成功。
