# 智联计算系统测试方案（修订版）

本文档为智联计算系统验收测试方案，作为项目子模块提交专家评审。

## 1. 测试指标定义

### 表 0-1 考核指标定义

| 指标名称 | 定义 | 计算/测量方法 | 评估标准 |
|----------|------|--------------|----------|
| 用户意图解析参数提取准确率 | 针对用户自然语言业务需求，系统能够正确识别业务意图类型，并抽取出满足任务创建要求的关键业务参数。只有当意图类型正确、必填参数完整且参数值正确时，判定该样本解析成功。 | Accuracy = N_correct / N_total × 100%。N_total 为测试集样本总数；N_correct 为解析完全正确的样本数。解析完全正确需满足：(1) 意图类型正确；(2) 必填参数无遗漏；(3) 参数值与标注一致；(4) 输出结构化结果符合 Schema。时间/时长/数值等字段先标准化再比对（如"2小时"="120分钟"）。 | 固定使用 360 条 multi-business 测试集，覆盖不同业务类型、表达方式和参数组合。正式验收优先采用 Qwen 大模型/智能体解析链路，通过 DashScope Batch API 异步评测并与人工标注结果比对；准确率 ≥ 90% 视为达标。规则解析仅作为兜底回归和错误定位工具。 |
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
| 前置条件 | 1. 依据组网拓扑搭建测试网络，确保管理面网络连通。2. 各计算节点部署 Node Agent 并通过健康检查。3. 在 AMD64 环境构建矩阵乘法 Worker 镜像并推送至 `10.112.244.94:5000/scientific-matmul:dev`。4. 部署并启动 Task Manager 后端服务和管理员前端。5. 完成各节点 baseline 基准测试（见 2.4 节），确认 `node_baselines` 表中有对应记录且稳定性满足要求。6. 外部路由系统可用；验收闭环调试阶段可使用管理后台 mock 路由写回 placements。 |
| 测试参数 | 业务 profile：matrix_size=1024, batch_count=50, seed=42。warmup：前 3 批不计入指标。观测窗口：10 秒；采样间隔：1 秒；单次采样 batch_count=5；最少有效样本数：5。正式测试次数：30 次独立可评价任务。路由策略：由外部路由系统或验收 mock 路由生成节点放置结果；业务目标成功率只评价部署与业务指标达标，不证明路由算法全局最优。 |
| 测试步骤 | 1. 管理员进入 `/benchmark` 验收测试页，确认当前任务类型为“矩阵乘法计算任务”。2. 执行 Step 1，对 `compute-1/2/3` 批量运行远程 baseline，确认所有节点均有稳定基线。3. 执行 Step 2，创建 30 个带 `is_benchmark=true` 标记的压测工单，系统生成本轮 `benchmark_run_id` 并写入每个工单。4. 执行 Step 3，由外部路由系统或页面验收 mock 路由为本轮工单写回 source/compute/sink placements 和 compute GPU 编号，然后一键启动本轮已路由实例。5. Worker 按 source -> compute -> sink 的随路计算数据流执行矩阵乘法，先 warmup，再在固定观测窗口内持续采集吞吐样本。6. 单次采样计算 effective_gflops = (2 × N³ × sample_batch_count) / sample_elapsed_seconds / 1e9；单任务 actual_gflops 取有效样本中位数。7. Sink 节点将 actual_gflops 和采样元数据上报至 Task Manager。8. Task Manager 根据 routing_result 中的 compute/worker placement 查询该节点 baseline_gflops。9. 判定：actual_gflops ≥ baseline_gflops × 0.8 → 达标；指标缺失、无 baseline 或样本数不足需保留工单证据并重跑补足。10. Step 4 按当前 `benchmark_run_id` 统计成功率、达标数、已评估数和样本是否充足；工单证据链可展开查看业务参数、路由结果、节点/GPU 分配和指标 JSON。 |
| 预期结果 | 已评估任务数 ≥ 30，业务目标成功率 ≥ 90%（即至少 27 个任务达标） |
| 测试结果 | 当前本地页面与 API 闭环已验证；真实四节点 30 任务压测待执行并附截图/报告。 |

---

### 2.2 视频AI推理业务目标成功率测试

### 表 1-2 视频AI推理业务目标成功率测试

| 项目 | 内容 |
|------|------|
| 用例编号 | 1-2 |
| 测试目的 | 验证视频AI推理业务场景下的业务目标成功率 |
| 组网拓扑 | 同 1-1 |
| 前置条件 | 1. 同 1-1 前置条件 1-4。2. 构建并分发视频推理 Worker 镜像 `low-latency-video:dev`。3. 完成各节点视频推理 baseline 基准测试。4. 采用固定工业检测抽帧 profile；后续可将 surrogate 替换为真实模型权重。 |
| 测试参数 | 业务 profile：resolution=720p, frame_count=120, frame_stride=30, warmup_frames=2, measured_frames=30, work_units=60000。测试次数：30 次独立任务。 |
| 测试步骤 | 1. 提交 30 次视频推理任务请求。2. 路由系统分配 source/compute/sink 节点。3. 平台部署视频推理容器并启动。4. Source 节点生成固定视频帧元数据，并按 frame_stride 抽帧发送给 compute 节点，模拟工业检测场景。5. Compute 节点对抽样帧执行固定 profile 的推理 surrogate，跳过 warmup 后统计逐帧处理时延。6. 计算 P90 帧推理时延（frame_latency_p90_ms）。7. Sink 节点上报 frame_latency_p90_ms 至 Task Manager。8. Task Manager 查询该节点的 baseline_p90。9. 判定：frame_latency_p90_ms ≤ baseline_p90 × 1.2 → 达标。10. 统计成功率。 |
| 预期结果 | 业务目标成功率 ≥ 90% |
| 测试结果 | 已新增轻量视频推理 Worker 原型、benchmark mode 和本地 baseline fallback；真实四节点 30 任务视频业务压测待后续执行并附截图。 |

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
| Baseline Profile | 通用计算：matrix_size=1024, batch_count=50, seed=42, warmup=3。视频推理：resolution=720p, frame_count=120, frame_stride=30, warmup_frames=2, measured_frames=30, work_units=60000。模型训练：model=gpt2-small, dataset=wikitext-2, steps=100, warmup=5。 |
| 测试步骤 | 1. 对目标节点部署 benchmark 容器。2. 容器执行固定 profile 负载，跳过 warmup 阶段。3. 采集有效阶段的过程性指标。4. 重复 3 次。5. 取 3 次结果的中位数作为该节点的 baseline。6. 写入 node_baselines 表，记录 node_id、business_type、profile_id、baseline_metric_value、measured_at。 |
| 自动化命令 | 管理后台 `/benchmark` Step 1 调用 `/api/baselines/batch-run`，通过目标节点 Node Agent 远程启动 benchmark 容器；命令行验收可参考 `docs/benchmark-test-plan.md` 中的四节点 runbook。 |
| 有效性规则 | 新节点加入必须执行 baseline。节点硬件变更后需重新测试。建议每季度复测。Baseline 为纯本地计算指标，不受网络拓扑变化影响。 |
| 预期结果 | 各节点 baseline 数据写入数据库，3 次测量结果标准差 < 中位数的 10%（确认测量稳定性） |

---

### 2.5 用户意图解析参数提取准确率测试

### 表 2-1 用户意图解析参数提取准确率测试

| 项目 | 内容 |
|------|------|
| 用例编号 | 2-1 |
| 测试目的 | 验证用户意图参数解析准确率 |
| 前置条件 | 1. 测试终端可在线调用 Qwen 大模型，API Key 具备足够调用额度。2. 管理员后台已配置可选评测模型，默认使用项目级模型配置。3. 完成固定测试数据集构建（当前实现 360 条）。 |
| 数据集构建 | 1. 采用“模板 + 槽位替换”自动构造样本，生成后抽样人工审核。2. 样本按约 7:3 比例分为完整样本（所有必填参数齐全）和不完整样本（缺失 ≥1 个参数或节点名错误）。3. 覆盖三种业务类型：矩阵乘法计算、低时延视频链路、LLM 文本生成。4. 覆盖中文、英文键值、中英文混写、箭头链路、口语化策略表达。5. 样本核心字段：utterance（用户输入）、expected（标注结果含 task_type、source/destination、data_profile、runtime_plan、expected_time、parse_status）。 |
| 样本示例 | 完整样本：`{"utterance": "矩阵乘法任务，从 compute-1 到 compute-3，1024阶矩阵，50批，现在开始跑2小时，资源保障策略", "expected": {"task_type": "high_throughput_matmul", "source_name": "compute-1", "destination_name": "compute-3", "data_profile": {"matrix_size": 1024, "batch_count": 50}, "runtime_plan": {"routing_strategy": "resource_guarantee"}, "parse_status": "valid"}}`。不完整样本：`{"utterance": "低时延视频推理任务，目的节点 compute-2，90帧，720p，30fps，现在开始跑2小时", "expected": {"task_type": "low_latency_video_pipeline", "source_name": null, "destination_name": "compute-2", "parse_status": "incomplete", "missing_params": ["source_name"]}}`。 |
| 测试步骤 | 1. 管理员进入 `/intent-evaluation` 页面，确认固定数据集总数为 360。2. 在“验收评测入口”选择评测模型，点击“运行智能体/大模型意图解析评测”。3. 系统将数据集转换为 DashScope Batch JSONL 请求文件并异步提交。4. 通过“同步大模型评测进度”刷新状态，Batch 完成后下载模型返回 JSONL 并生成评分报告。5. 对比系统输出与人工标注：完整样本要求所有字段精确匹配；不完整样本要求非空参数精确匹配，并正确输出缺失字段键。6. 时间/时长字段标准化后比对。7. 计算准确率 = 完全正确样本数 / 总样本数。 |
| 测试时间 | 本地规则回归约 1 分钟内完成；正式 LLM 评测通过 DashScope Batch API 异步提交 360 条样本，完成后刷新状态下载结果并评分。 |
| 预期结果 | 参数提取准确率 ≥ 90% |
| 测试结果 | 已使用 `qwen3.7-plus` 通过 DashScope Batch API 完成 360 条固定数据集评测，正确 360 条，准确率 100.0%，达到 ≥90% 验收目标。评分已纳入相对时间严格校验：对“现在开始跑2小时/立即运行60分钟/马上开始跑3小时”等表达，数据集标注 `expected_time.duration_minutes`，系统按 `business_end_time - business_start_time` 与期望时长比对，容差 2 分钟；本次报告中 338 条含时长期望样本全部匹配。Batch ID：`batch_8a23fd90-3758-44df-8598-f3c22519a1d2`；评测编号：`intent-eval-20260603-222617-90569be4`；报告：`reports/intent_eval_llm.json`；输入/输出：`reports/intent_eval_batches/intent-eval-20260603-222617-90569be4/input.jsonl`、`reports/intent_eval_batches/intent-eval-20260603-222617-90569be4/output.jsonl`。 |

---

### 2.6 意图解析评测自动化实现

为保证评测集可复现，第一阶段采用“模板 + 槽位替换”的方式构造数据集，并锁定为 `datasets/intent_eval/multi_business.jsonl`：

1. 模板覆盖完整请求、缺源节点、缺目的节点、缺开始/结束时间、错误源节点、错误目的节点等场景。
2. 槽位覆盖 `compute-1/2/3`、矩阵规模/批次数、视频帧数/分辨率/fps、LLM prompt tokens/max_new_tokens/batch_size、路由策略和相对时间表达。
3. 生成脚本输出 JSONL，每条样本包含用户表达 `utterance` 和人工标注的 `expected` 结构化结果；相对时间表达使用 `expected_time.duration_minutes` 标注期望运行时长，不把它作为业务工单字段。
5. 正式提交前抽样人工审核标注，避免模板生成的期望值与文本不一致。

当前实现命令：

```bash
cd backend
./venv/bin/python scripts/generate_intent_dataset.py --count 360 --output ../datasets/intent_eval/multi_business.jsonl
./venv/bin/python -c "from services.intent_batch_eval import run_rule_evaluation; r=run_rule_evaluation(); print(r['correct'], r['total'], r['accuracy'])"
```

如果评测链路需要批量调用 Qwen 大模型 API，应优先采用阿里云百炼/DashScope 的 Batch API 或 Batch File API，而不是对实时 chat completions 接口进行高频串行请求。Batch API 适合离线评测任务，可降低限流和长时间占用交互接口的风险。

管理员后台 `/intent-evaluation` 固定展示当前数据集、规则评测、大模型/智能体 Batch 状态、按样本类型准确率、成功/失败样本明细，并提供单条解析检测能力。当前不开放数据集选择，避免验收口径漂移；评测模型可在页面选择，候选模型由项目级配置 `DASHSCOPE_EVAL_MODELS` 控制，提交后写入 Batch job 和评测报告。候选模型不直接照搬模型广场列表，需先通过 `python scripts/smoke_dashscope_batch_models.py` 提交 1 条 DashScope Batch 示例请求并在限定时间内完成，完成后才进入前端下拉框。2026-06-03 smoke 结果显示 `qwen3.7-plus` 与 `qwen-long` 可在本项目 Batch File API 链路中完成，因此正式评测候选保留 `qwen3.7-plus,qwen-long`；`qwen-plus-latest`、`qwen-flash`、`qwen3-max` 在 420 秒内均停留在 `0/1` 未完成，不进入验收页面候选。

正式大模型评测按“单任务运行”设计：系统仅跟踪最近一次正式 Batch 评测；当最近一次评测处于 `validating`、`in_progress`、`finalizing`、`submitted` 或 `cancelling` 状态时，页面禁止再次提交新的大模型评测。管理员可以点击“取消当前评测”调用 DashScope Batch cancel 接口，中途终止仍在运行的评测任务，避免重复提交造成费用和结果口径混乱。每次评测都有独立 `evaluation_id`/`job_id` 和提交时间，页面顶部准确率、按样本类型准确率、评测样本表均显示当前报告对应的评测编号；Batch 运行中页面每 15 秒自动同步状态，管理员也可手动点击“同步大模型评测进度”。

正式评测优先使用大模型/智能体解析链路。管理员点击“运行智能体/大模型意图解析评测”后，系统生成 Batch 输入文件并提交至所选 Qwen 模型；随后点击“同步大模型评测进度”刷新状态。Batch 完成后，系统下载大模型返回 JSONL，经过 Schema 校验、节点存在性校验、字段标准化和相对时间确定性后处理后，与人工标注逐字段比对，生成 `reports/intent_eval_llm.json`。样本只有在任务类型、必填参数、参数值、时间时长、解析状态和结构化 Schema 均满足要求时才判为正确，最终准确率须不低于 90%。

规则解析不作为正式验收主链路，仅作为大模型不可用、Batch 服务未配置或日常版本回归时的兜底定位工具。管理员可点击“运行规则兜底回归”快速生成 `reports/intent_eval.json`，用于判断错误来自固定数据集、确定性校验层、字段比对逻辑，还是大模型输出波动。

前端验收截图建议覆盖五处：一是 `/intent-evaluation` 顶部统计卡，展示固定数据集总数、验收目标、规则兜底准确率和大模型/智能体准确率，并包含评测编号和生成时间；二是“数据集覆盖”表，展示各样本类型数量和占比；三是“大模型/智能体异步评测进度”卡，展示评测编号、本次评测模型、Batch ID、提交/更新时间、请求计数、输入文件、输出文件和报告路径；四是“按样本类型准确率”区域，展示各样本类型的正确数、总数、准确率和当前报告编号；五是“评测样本”展开行，展示单条样本的字段判定、解析结果 JSON 与期望结果 JSON。可补充截取“单条解析检测”区域，用于说明页面具备人工抽查和问题复现实验能力。

评测留档文件通过 `/intent-evaluation` 页面“评测文件下载”区域统一下载，包括原始数据集 `intent_eval_dataset.jsonl`、规则兜底评测结果 `intent_eval_rule_report.json`、大模型/智能体评测结果 `intent_eval_llm_report.json`。Batch 相关留档包括 `intent_eval_batch_job.json`、`intent_eval_batch_input.jsonl` 和 `intent_eval_batch_output.jsonl`，分别用于复核任务状态、实际提交请求和模型原始返回。专家评审材料中应同时归档页面截图、最终 LLM 评测报告 JSON、Batch 输入/输出文件，并记录模型名称、提交时间、样本总数、正确样本数、准确率和是否达到 90% 验收阈值。

---

## 3. 关键术语说明

| 术语 | 定义 |
|------|------|
| effective_gflops | 有效浮点运算吞吐量 = (2 × N³ × batch_count) / elapsed_seconds / 1e9，其中 N 为矩阵维度 |
| tokens_per_second | 训练吞吐量 = 有效训练阶段处理的 token 总数 / 有效训练耗时（秒） |
| frame_latency_p90_ms | 帧推理时延 P90 = 有效推理阶段所有帧推理时延的第 90 百分位值（毫秒） |
| baseline | 节点历史基准能力值，通过在空闲状态下执行固定 profile 负载 3 次取中位数获得 |
| benchmark_run_id | 单轮验收压测编号，由 `/benchmark` 页面创建批量工单时生成；正式截图、工单证据链和成功率统计应保持同一编号 |
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
