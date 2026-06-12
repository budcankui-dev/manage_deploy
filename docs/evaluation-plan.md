# 智联计算系统评测方案

## 1. 评测目标

本方案验证智联计算系统两项核心能力指标：

| 指标 | 定义 | 验收标准 |
|------|------|----------|
| 意图参数解析准确率 | 用户自然语言输入 → 结构化参数字段匹配率 | ≥ 90% |
| 业务目标成功率 | 任务部署运行后过程性指标达到节点历史基准能力 | ≥ 90% |

## 2. 系统边界与前提

### 2.1 系统组成

- Task Manager（后端）：意图解析、工单管理、DAG 编排、调度、业务评估
- Node Agent：部署在 worker 节点，通过 Docker SDK 控制本地容器
- 外部路由系统：根据 DAG 资源需求选择物理节点，分配 GPU 编号
- Worker 容器：执行业务计算，上报过程性指标

### 2.2 评测前提

- 所有参与评测的物理节点已完成 baseline 基准测试
- Node Agent 已部署且健康检查通过
- Worker 镜像已构建并可拉取
- 外部路由系统可用（或使用手动路由替代）

## 3. 意图参数解析准确率评测

### 3.1 指标定义

```
意图参数解析准确率 = 所有字段均正确的样本数 / 总样本数 × 100%
```

单条样本"正确"的判定：LLM 输出的每个结构化字段与 ground-truth 完全匹配。

评估字段：

| 字段 | 类型 | 判定规则 |
|------|------|----------|
| task_type | enum | 精确匹配 |
| source_name | string | 精确匹配 |
| destination_name | string | 精确匹配 |
| start_time | datetime | 允许 ±2 分钟误差 |
| end_time | datetime | 允许 ±2 分钟误差 |
| matrix_size | int | 精确匹配 |
| batch_count | int | 精确匹配 |
| routing_strategy | enum | 精确匹配 |
| parse_status | enum | 精确匹配（valid/incomplete/rejected） |

### 3.2 样本集设计

总样本数：**30 条**（覆盖以下类别）

| 类别 | 数量 | 说明 |
|------|------|------|
| 完整输入（一句话包含所有参数） | 8 | 验证一次性提取能力 |
| 部分输入（缺 1-3 个参数） | 8 | 验证 parse_status=incomplete 判定 |
| 模糊/口语化表达 | 6 | "跑快点"→fastest_completion 等 |
| 时间推理 | 4 | "现在开始跑2小时"、"明天上午9点到下午3点" |
| 无关/拒绝类输入 | 4 | "帮我订外卖"→task_type=null |

样本格式（JSONL）：

```json
{
  "utterance": "我要做一个矩阵计算任务，从 compute-1 到 compute-3，现在开始跑2小时，矩阵规模1024，10批，资源保障策略",
  "expected": {
    "task_type": "high_throughput_matmul",
    "source_name": "compute-1",
    "destination_name": "compute-3",
    "start_time": "now",
    "end_time": "+2h",
    "matrix_size": 1024,
    "batch_count": 10,
    "routing_strategy": "resource_guarantee",
    "parse_status": "valid"
  }
}
```

### 3.3 评测方法

1. 使用离线评测脚本 `backend/scripts/evaluate_intent_parser.py`
2. 每条样本独立调用解析器（无多轮上下文）
3. 对比输出字段与 ground-truth
4. 统计准确率

### 3.4 可复现性保证

- 样本集固定存储在 `datasets/intent_eval/` 目录
- 解析器版本锁定（记录 model name + temperature）
- 由于 LLM 存在随机性，每条样本评测 **3 次**，取多数投票结果
- 报告中记录每条样本的 3 次结果和最终判定

### 3.5 验收标准

```
准确率 ≥ 90%（即 30 条中至少 27 条全字段正确）
```

## 4. 业务目标成功率评测

### 4.1 指标定义

```
业务目标成功率 = 业务目标达成的任务数 / 已完成且可评价的任务数 × 100%
```

单任务"业务目标达成"的判定：

```
任务部署成功
AND 指标采集完整（满足最小统计窗口）
AND 实测过程性指标达到该节点、该业务 profile 的历史基准阈值
```

### 4.2 过程性指标定义

| 业务类型 | 负载 | 过程性指标 | 方向 | 达标条件 |
|----------|------|-----------|------|----------|
| 通用计算 | 矩阵乘法批处理 | effective_gflops | 越高越好 | actual ≥ baseline × 0.8 |
| 模型训练 | 固定文本模型训练 | tokens_per_second | 越高越好 | actual ≥ baseline × 0.8 |
| 视频推理 | 固定视频帧推理 | frame_latency_p90_ms | 越低越好 | baseline / actual ≥ 0.8，即 actual ≤ baseline / 0.8 |

其中：
- `success_ratio = 0.8`（越高越好指标的容忍系数）
- 越低越好指标同样采用能力保持率口径：`baseline / actual ≥ 0.8`

### 4.3 Baseline 基准测试方法

#### 4.3.1 目的

为每个物理节点建立固定业务 profile 下的性能基准，作为业务目标判定的参照。

#### 4.3.2 测试流程

```
对每个节点 N、每种业务类型 T：
  1. 部署 benchmark 容器（复用业务 worker 镜像，MODE=benchmark）
  2. 执行固定 profile 的计算负载
  3. 跳过 warmup 阶段，采集有效指标
  4. 重复 3 次，取中位数
  5. 写入 node_baselines 表
```

#### 4.3.3 Baseline 测试参数

| 业务类型 | profile_id | 参数 | warmup | 有效负载 |
|----------|-----------|------|--------|----------|
| 通用计算 | gpu_standard | matrix_size=1024, batch_count=50, seed=42, USE_GPU=true | 前 3 批 | 固定观测窗口内多次采样，取 effective_gflops 中位数 |
| 模型训练 | small_text_model | model=gpt2-small, dataset=wikitext-2, steps=100 | 前 5 step | 后 95 step |
| 视频推理 | video_industrial_inspection_720p | fixed_video=bottle-detection.mp4, model=yolov5n-fp32.onnx, USE_GPU=true | 前 10 帧 | 30 个有效抽帧，统计 frame_latency_p90_ms |

#### 4.3.4 Baseline 有效性

- 新节点加入集群时必须执行 baseline 测试
- 节点硬件变更（如更换 GPU）后需重新测试
- Baseline 在目标节点通过 Node Agent 启动 benchmark 容器测量，要求与正式业务任务使用同一镜像、同一固定参数和同一 GPU 推理/计算路径。
- CPU 或模型调试路径仅用于开发排障，不能写入正式验收 baseline。
- 建议每季度复测一次，确认无硬件退化

#### 4.3.5 自动化

提供一键脚本：

```bash
python backend/scripts/run_baseline.py \
  --api-base http://<manager-host>:8181 \
  --node-hostname <node-hostname> \
  --task-type high_throughput_matmul \
  --runs 3
```

脚本通过管理后端调用 `/api/baselines/run`，自动完成：目标节点部署 benchmark 容器 → 执行固定负载 → 校验 GPU/业务后端 → 采集指标 → 取中位数 → 写入数据库。

### 4.4 正式评测流程

#### 4.4.1 测试拓扑

第一阶段使用 3 个计算节点（compute-1, compute-2, compute-3），每个节点均完成 baseline。

任务结构：source → worker → sink（默认三节点 DAG）

#### 4.4.2 测试任务集

总任务数：**30 次**

| 业务类型 | 任务数 | 说明 |
|----------|--------|------|
| 通用计算（matmul） | 30 | 正式主验收链路，优先用于四节点留档和专家截图 |

扩展演示：`/benchmark` 页面已支持视频推理业务类型，可按同样流程创建视频抽帧推理工单，验证多模态扩展能力。模型训练/文本生成业务在测试方案中保留指标定义和接口契约，第一阶段可先不作为四节点 30 任务主验收样本，避免现场同时引入过多变量。

#### 4.4.3 测试参数

每次任务使用固定 profile（与 baseline 相同）：

```json
{
  "task_type": "high_throughput_matmul",
  "matrix_size": 1024,
  "batch_count": 50,
  "seed": 42,
  "warmup_batches": 3
}
```

路由策略由外部路由系统或验收配置流程分配，并覆盖 resource_guarantee / fastest_completion / load_balance / cost_priority 等典型策略，验证不同路由策略下业务目标均可达成。

#### 4.4.4 单次任务评测流程

```
1. 提交任务（通过对话或 API）
2. 外部路由系统（或手动路由）分配计算节点
3. 平台自动部署容器，按时间窗口启动
4. Worker 执行计算：
   a. 前 3 批为 warmup，不计入指标
   b. 后 47 批为有效计算
   c. 计算 effective_gflops = (2 × N³ × batch_count) / elapsed_seconds / 1e9
5. Sink 节点上报指标到 Task Manager
6. Task Manager 查询该 worker 节点的 baseline
7. 判定：effective_gflops ≥ baseline × 0.8 → 达标
8. 记录结果
```

#### 4.4.5 失败场景处理

| 场景 | 判定 | failure_reason |
|------|------|----------------|
| 容器启动失败 | 不计入可评价任务 | deployment_failed |
| 指标采集不完整（< 30 批有效数据） | 不达标 | metrics_incomplete |
| 指标低于基准 × 0.8 | 不达标 | below_baseline |
| 节点无 baseline 记录 | 不计入可评价任务 | no_baseline |

### 4.5 验收标准

```
业务目标成功率 ≥ 90%（即 30 次可评价任务中至少 27 次达标）
```

## 5. 评测环境

### 5.1 第一阶段（当前）

- 网络：单一管理面网络，节点直连
- 节点：3 台计算节点（compute-1/2/3）
- 路由：手动路由或简单自动分配
- 业务：matmul 作为主验收业务，视频推理作为页面可选扩展演示业务

### 5.2 第二阶段（正式验收）

- 网络：管理面 + 数据面（IPv6）
- 节点：按实际部署规模
- 路由：外部路由系统根据 CPU/GPU 资源选择节点，建立数据面路由
- 业务：matmul + 视频推理扩展演示；模型训练/文本生成按相同 `tokens_per_second` 契约预留

### 5.3 环境差异对指标的影响

过程性指标（effective_gflops / tokens_per_second / frame_latency_p90_ms）均为**节点本地计算性能指标**，不包含网络传输时间。因此：

- 网络拓扑变化不影响 baseline 有效性
- 管理面/数据面分离不影响业务指标评估
- 节点硬件不变的情况下，两阶段的 baseline 可复用

## 6. 评测报告格式

### 6.1 意图解析评测报告

```json
{
  "evaluation_id": "intent-eval-20260603-222617-90569be4",
  "model": "qwen3.7-plus",
  "temperature": 0.1,
  "dataset": "datasets/intent_eval/multi_business.jsonl",
  "total": 360,
  "correct": 330,
  "accuracy": 0.917,
  "passed": true,
  "batch_id": "batch_8a23fd90-3758-44df-8598-f3c22519a1d2",
  "report_path": "reports/intent_eval_llm.json",
  "results": [
    {
      "sample_id": "sample-0000",
      "utterance": "...",
      "expected": {...},
      "parsed_result": {...},
      "match": true,
      "details": {...}
    }
  ]
}
```

### 6.2 业务目标成功率报告

```json
{
  "eval_id": "business-eval-20260601",
  "total_tasks": 30,
  "evaluable_tasks": 30,
  "successful_tasks": 28,
  "success_rate": 0.933,
  "pass": true,
  "baseline_info": {
    "compute-1": {"effective_gflops": 58.2, "measured_at": "2026-06-01"},
    "compute-2": {"effective_gflops": 61.5, "measured_at": "2026-06-01"},
    "compute-3": {"effective_gflops": 55.8, "measured_at": "2026-06-01"}
  },
  "results": [
    {
      "task_id": "...",
      "node": "compute-2",
      "baseline": 61.5,
      "threshold": 49.2,
      "actual": 59.3,
      "success": true
    }
  ]
}
```

## 7. 可复现性保证

| 维度 | 措施 |
|------|------|
| 意图解析 | 固定 360 条样本集 + 固定模型版本/温度 + DashScope Batch 输入/输出留档；相对时间按 `expected_time.duration_minutes` 校验 `结束时间-开始时间`；评测模型需先通过 1 条样例 Batch smoke 测试 |
| 业务计算 | 固定 seed + 固定 profile + warmup 隔离 |
| Baseline | 固定参数 + 3 次取中位数 + 记录测试时间 |
| 环境 | 记录节点硬件信息、Docker 版本、镜像 tag |
| 脚本 | 所有评测通过自动化脚本执行，人工不干预计算过程 |

## 8. 评测执行清单

### 8.1 准备阶段

- [x] 固定意图解析样本集至 360 条
- [x] Batch 评测模型 smoke 测试完成，当前正式评测下拉保留 `qwen3.7-plus`、`qwen-long`
- [ ] 完成所有节点 baseline 测试
- [ ] Worker 镜像更新（上报 effective_gflops）
- [ ] 评估逻辑更新（基于 baseline 判定）
- [ ] 自动化评测脚本就绪

### 8.2 执行阶段

- [x] 运行意图解析真实大模型/智能体 Batch 评测（360 条，qwen3.7-plus，360/360）
- [ ] 运行业务目标评测（30 次任务部署）
- [x] 收集意图解析评测报告

### 8.3 输出物

- [x] 意图解析评测报告（JSON，含 Batch 输入/输出留档）
- [x] `/intent-evaluation` 页面截图（统计卡、Batch 状态、样本明细、评测文件下载）
- [x] Batch 任务状态、输入 JSONL、输出 JSONL 留档
- [x] 前端看板展示评测编号、生成时间、Batch 请求计数，并在 Batch 运行中自动同步状态
- [ ] 业务目标成功率报告（JSON）
- [ ] 评测环境说明
- [ ] 可复现执行命令清单
