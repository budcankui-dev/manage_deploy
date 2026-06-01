# 智联计算系统测试方案（修订版）

本文档为智联计算系统验收测试方案，作为项目子模块提交专家评审。

## 1. 测试指标定义

### 表 0-1 考核指标定义

| 指标名称 | 定义 | 计算/测量方法 | 评估标准 |
|----------|------|--------------|----------|
| 用户意图解析参数提取准确率 | 针对用户自然语言业务需求，系统能够正确识别业务意图类型，并抽取出满足任务创建要求的关键业务参数。只有当意图类型正确、必填参数完整且参数值正确时，判定该样本解析成功。 | Accuracy = N_correct / N_total × 100%。N_total 为测试集样本总数；N_correct 为解析完全正确的样本数。解析完全正确需满足：(1) 意图类型正确；(2) 必填参数无遗漏；(3) 参数值与标注一致；(4) 输出结构化结果符合 Schema。时间/时长/数值等字段先标准化再比对（如"2小时"="120分钟"）。 | 构建覆盖不同业务类型、表达方式和参数组合的测试集（≥200条），自动化解析并与人工标注结果比对。准确率 ≥ 90% 视为达标。每条样本评测 3 次取多数投票，消除模型随机性影响。 |
| 业务目标成功率（通用计算） | 通用计算（矩阵乘法）业务在运行过程中，其计算节点的实际有效浮点运算吞吐量（effective_gflops）满足该节点在相同业务 profile 下的历史基准能力要求。 | Success Rate = N_success / N_total × 100%。对单个任务：actual_gflops ≥ baseline_gflops × 0.8 则达标。其中 baseline_gflops 为该计算节点在相同 profile 下的历史基准中位数（3 次测量取中位），0.8 为容忍系数。 | 执行 ≥30 次独立任务，统计达标比例。成功率 ≥ 90% 视为满足性能要求。 |
| 业务目标成功率（视频AI推理） | 视频AI推理业务在运行过程中，其推理节点的帧推理时延 P90 不超过该节点历史基准能力的 1.2 倍。 | Success Rate = N_success / N_total × 100%。对单个任务：P90(frame_latency_ms) ≤ baseline_p90 × 1.2 则达标。其中 baseline_p90 为该节点在相同视频 profile 下的历史基准 P90 帧时延中位数。 | 执行 ≥30 次独立任务，统计达标比例。成功率 ≥ 90% 视为满足性能要求。 |
| 业务目标成功率（模型训练） | 模型训练业务在运行过程中，其训练节点的实际训练吞吐量（tokens_per_second）满足该节点在相同模型和数据集 profile 下的历史基准能力要求。 | Success Rate = N_success / N_total × 100%。对单个任务：actual_tps ≥ baseline_tps × 0.8 则达标。其中 baseline_tps 为该节点在相同训练 profile 下的历史基准中位数。 | 执行 ≥30 次独立任务，统计达标比例。成功率 ≥ 90% 视为满足性能要求。 |

---

## 2. 测试用例

### 2.1 通用计算（矩阵乘法）业务目标成功率测试

### 表 1-1 通用计算业务目标成功率测试

| 项目 | 内容 |
|------|------|
| 用例编号 | 1-1 |
| 测试目的 | 验证通用计算（矩阵乘法）业务场景下的业务目标成功率 |
| 组网拓扑 | 3 台计算节点（compute-1/2/3），1 台管理节点（Task Manager），通过管理面网络互联。正式验收时增加数据面（IPv6）网络。 |
| 前置条件 | 1. 依据组网拓扑搭建测试网络，确保管理面网络连通。2. 各计算节点部署 Node Agent 并通过健康检查。3. 构建并分发矩阵乘法 Worker 镜像至各节点。4. 部署并启动 Task Manager 后端服务。5. 完成各节点 baseline 基准测试（见 2.4 节），确认 node_baselines 表中有对应记录。6. 外部路由系统可用或使用管理后台手动路由功能。 |
| 测试参数 | 业务 profile：matrix_size=1024, batch_count=50, seed=42。warmup：前 3 批不计入指标。有效计算：后 47 批。测试次数：30 次独立任务。路由策略：随机分配（4 种策略各约 25%）。 |
| 测试步骤 | 1. 启动 Task Manager，读取当前算网资源状态。2. 通过对话系统或 API 提交 30 次矩阵乘法任务请求，每次指定不同路由策略。3. 外部路由系统（或手动路由）为每个任务分配计算节点。4. 平台自动部署 Worker 容器，按业务时间窗口启动。5. Worker 执行矩阵乘法：前 3 批 warmup，后 47 批有效计算。6. 计算 effective_gflops = (2 × N³ × effective_batch_count) / elapsed_seconds / 1e9。7. Sink 节点将 effective_gflops 上报至 Task Manager。8. Task Manager 查询该 Worker 所在节点的 baseline_gflops。9. 判定：effective_gflops ≥ baseline_gflops × 0.8 → 达标。10. 统计 30 次任务的业务目标成功率。 |
| 预期结果 | 业务目标成功率 ≥ 90%（即 30 次中至少 27 次达标） |
| 测试结果 | （待填写，附截图） |

---

### 2.2 视频AI推理业务目标成功率测试

### 表 1-2 视频AI推理业务目标成功率测试

| 项目 | 内容 |
|------|------|
| 用例编号 | 1-2 |
| 测试目的 | 验证视频AI推理业务场景下的业务目标成功率 |
| 组网拓扑 | 同 1-1 |
| 前置条件 | 1. 同 1-1 前置条件 1-4。2. 构建并分发视频推理 Worker 镜像（含预训练模型权重）。3. 完成各节点视频推理 baseline 基准测试。4. 准备固定测试视频序列（720p，100 帧）。 |
| 测试参数 | 业务 profile：resolution=720p, frames=100, model=yolov8。warmup：前 10 帧不计入指标。有效推理：后 90 帧。测试次数：30 次独立任务。 |
| 测试步骤 | 1. 提交 30 次视频推理任务请求。2. 路由系统分配推理节点。3. 平台部署推理容器并启动。4. 推理节点接收视频帧，逐帧执行 AI 推理。5. 前 10 帧为 warmup，后 90 帧统计帧推理时延。6. 计算 P90 帧推理时延（frame_latency_p90_ms）。7. Sink 节点上报 frame_latency_p90_ms 至 Task Manager。8. Task Manager 查询该节点的 baseline_p90。9. 判定：frame_latency_p90_ms ≤ baseline_p90 × 1.2 → 达标。10. 统计成功率。 |
| 预期结果 | 业务目标成功率 ≥ 90% |
| 测试结果 | （待填写，附截图） |

---

### 2.3 模型训练业务目标成功率测试

### 表 1-3 模型训练业务目标成功率测试

| 项目 | 内容 |
|------|------|
| 用例编号 | 1-3 |
| 测试目的 | 验证模型训练业务场景下的业务目标成功率 |
| 组网拓扑 | 同 1-1 |
| 前置条件 | 1. 同 1-1 前置条件 1-4。2. 构建并分发模型训练 Worker 镜像（含小文本模型和训练数据集）。3. 完成各节点模型训练 baseline 基准测试。4. 训练数据集：wikitext-2，模型：GPT-2 small。 |
| 测试参数 | 业务 profile：model=gpt2-small, dataset=wikitext-2, steps=100。warmup：前 5 step 不计入指标。有效训练：后 95 step。测试次数：30 次独立任务。 |
| 测试步骤 | 1. 提交 30 次模型训练任务请求。2. 路由系统分配训练节点。3. 平台部署训练容器并启动。4. 训练节点加载模型和数据集，执行训练。5. 前 5 step 为 warmup，后 95 step 统计训练吞吐。6. 计算 tokens_per_second = total_tokens_processed / elapsed_seconds。7. 上报 tokens_per_second 至 Task Manager。8. Task Manager 查询该节点的 baseline_tps。9. 判定：tokens_per_second ≥ baseline_tps × 0.8 → 达标。10. 统计成功率。 |
| 预期结果 | 业务目标成功率 ≥ 90% |
| 测试结果 | （待填写，附截图） |

---

### 2.4 节点 Baseline 基准测试方法

### 表 1-4 节点基准能力测试

| 项目 | 内容 |
|------|------|
| 用例编号 | 1-4 |
| 测试目的 | 为各计算节点建立历史基准能力数据，作为业务目标判定的参照阈值 |
| 前置条件 | 1. 目标节点 Node Agent 正常运行。2. Benchmark 容器镜像已构建（复用业务 Worker 镜像，MODE=benchmark）。3. 节点处于空闲状态（无其他业务容器运行）。 |
| 测试参数 | 每种业务类型使用固定 profile（见下表）。每个节点每种业务重复 3 次，取中位数。 |
| Baseline Profile | 通用计算：matrix_size=1024, batch_count=50, seed=42, warmup=3。视频推理：resolution=720p, frames=100, warmup=10。模型训练：model=gpt2-small, dataset=wikitext-2, steps=100, warmup=5。 |
| 测试步骤 | 1. 对目标节点部署 benchmark 容器。2. 容器执行固定 profile 负载，跳过 warmup 阶段。3. 采集有效阶段的过程性指标。4. 重复 3 次。5. 取 3 次结果的中位数作为该节点的 baseline。6. 写入 node_baselines 表，记录 node_id、business_type、profile_id、baseline_metric_value、measured_at。 |
| 自动化命令 | `python backend/scripts/run_baseline.py --node <hostname> --business-type matmul --profile cpu_standard --repeat 3` |
| 有效性规则 | 新节点加入必须执行 baseline。节点硬件变更后需重新测试。建议每季度复测。Baseline 为纯本地计算指标，不受网络拓扑变化影响。 |
| 预期结果 | 各节点 baseline 数据写入数据库，3 次测量结果标准差 < 中位数的 10%（确认测量稳定性） |

---

### 2.5 用户意图解析参数提取准确率测试

### 表 2-1 用户意图解析参数提取准确率测试

| 项目 | 内容 |
|------|------|
| 用例编号 | 2-1 |
| 测试目的 | 验证用户意图参数解析准确率 |
| 前置条件 | 1. 测试终端可在线调用 qwen-plus 大模型，API Key 具备足够调用额度。2. 完成测试数据集构建（≥200 条样本）。 |
| 数据集构建 | 1. 设计样本模板，采用大模型填充模板生成样本，人工审核标注。2. 样本按 7:3 比例分为完整样本（所有必填参数齐全）和不完整样本（缺失 ≥1 个参数）。3. 覆盖三种业务类型：通用计算、视频推理、模型训练。4. 覆盖多种表达方式：正式/口语/模糊/含噪声。5. 样本核心字段：text（用户输入）、label（标注结果含业务类型、各参数值、parse_status、missing_params）。 |
| 样本示例 | 完整样本：`{"text": "矩阵计算任务，从compute-1到compute-3，1024阶矩阵50批，现在开始跑2小时，资源保障策略", "label": {"task_type": "high_throughput_matmul", "source_name": "compute-1", "destination_name": "compute-3", "matrix_size": 1024, "batch_count": 50, "start_time": "now", "end_time": "+2h", "routing_strategy": "resource_guarantee", "parse_status": "valid"}}`。不完整样本：`{"text": "我想跑个矩阵乘法", "label": {"task_type": "high_throughput_matmul", "source_name": null, ..., "parse_status": "incomplete", "missing_params": ["source_name", "destination_name", ...]}}`。 |
| 测试步骤 | 1. 使用自动化评测脚本 `backend/scripts/evaluate_intent_parser.py` 加载数据集。2. 对每条样本独立调用意图解析模块（无多轮上下文）。3. 每条样本评测 3 次，取多数投票结果。4. 对比系统输出与人工标注：完整样本要求所有字段精确匹配；不完整样本要求非空参数精确匹配，缺失参数输出为 null。5. 时间/时长字段标准化后比对（"2小时"="120分钟"，允许 ±2 分钟误差）。6. 计算准确率 = 完全正确样本数 / 总样本数。 |
| 测试时间 | 单次评测约 200 条 × 3 次 = 600 次 API 调用，预计耗时 30-60 分钟 |
| 预期结果 | 参数提取准确率 ≥ 90% |
| 测试结果 | （待填写，附截图及评测报告 JSON） |

---

## 3. 关键术语说明

| 术语 | 定义 |
|------|------|
| effective_gflops | 有效浮点运算吞吐量 = (2 × N³ × batch_count) / elapsed_seconds / 1e9，其中 N 为矩阵维度 |
| tokens_per_second | 训练吞吐量 = 有效训练阶段处理的 token 总数 / 有效训练耗时（秒） |
| frame_latency_p90_ms | 帧推理时延 P90 = 有效推理阶段所有帧推理时延的第 90 百分位值（毫秒） |
| baseline | 节点历史基准能力值，通过在空闲状态下执行固定 profile 负载 3 次取中位数获得 |
| warmup | 预热阶段，用于排除容器启动、JIT 编译、缓存冷启动等干扰，不计入指标统计 |
| success_ratio (0.8) | 越高越好指标的容忍系数，actual ≥ baseline × 0.8 即达标 |
| tolerance_ratio (1.2) | 越低越好指标的容忍系数，actual ≤ baseline × 1.2 即达标 |
| 过程性指标 | 任务运行过程中可持续观测的性能指标，区别于端到端完成时间 |

---

## 4. 与旧版方案的主要差异

| 维度 | 旧版 | 新版 | 改进原因 |
|------|------|------|----------|
| 业务目标定义 | 用户设定目标值（如"完成时间 ≤ 60s"） | 节点历史基准 × 容忍系数 | 用户无法准确预估完成时间，导致目标不合理 |
| 指标类型 | 端到端完成时间 | 过程性吞吐/时延指标 | 过程性指标可持续观测，不受任务总时长影响 |
| 达标判定 | actual ≤ user_target | actual vs baseline × ratio | 基于节点实际能力判定，更科学 |
| 模型训练指标 | 训练完成时间 | tokens_per_second | 吞吐量不受数据集大小影响，可横向比较 |
| 视频推理指标 | 用户预期时延 | P90 帧时延 vs 节点基准 | 消除用户设定不合理目标的风险 |
| 意图解析样本 | 未明确数量 | ≥200 条，3 次投票 | 满足统计显著性，消除随机性 |