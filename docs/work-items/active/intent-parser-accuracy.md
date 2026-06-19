# Work Item: 意图解析准确率验收闭环

Status: in_progress
Last Updated: 2026-06-08

## 当前目标

业务目标成功率相关工作暂缓。当前优先完成意图解析指标：

```text
用户意图解析参数提取准确率 >= 90%
```

验收口径：

- 数据集固定为 360 条 multi-business 样本。
- 正式验收优先运行真实 Qwen 大模型/智能体 Batch 评测；规则解析 3 次投票仅作为兜底回归和错误定位。
- 完全正确才算成功：任务类型、源节点、目的节点、开始时间、结束时间、业务 data_profile 字段、路由策略、parse_status 均符合期望。

## 当前业务边界

系统端到端真实部署演示优先支持两类业务：

```text
task_type = high_throughput_matmul
task_type = low_latency_video_pipeline
```

意图解析准确率数据集可以覆盖更多业务和模态，但这些扩展样本仅用于验证自然语言参数提取能力，不要求每一种模态都具备完整部署镜像。

模态命名与数据集扩展方案见 `docs/modality-taxonomy-and-intent-expansion.md`。后续数据集应覆盖图中记录的模态名称，建议直接覆盖 8 种；若验收口径最终只要求 7 种，则保证至少 7 种模态有有效样本。

## 已完成

- 新增模板生成脚本：`backend/scripts/generate_intent_dataset.py`
- 扩展评测脚本：`backend/scripts/evaluate_intent_parser.py`
- 生成 360 条多业务 JSONL 数据集：`datasets/intent_eval/multi_business.jsonl`
- 本地规则解析评测：`360/360 = 100.00%`
- 评测报告：`reports/intent_eval.json`
- 后端规则解析补齐：`matrix_size`、`batch_count`、`routing_strategy`、必填参数完整性校验。
- 后端规则解析增强：合法节点列表校验，错误节点不会被计为成功提取。
- 后端规则解析增强：支持口语化、中英文混写、箭头表达、字段顺序打乱和无关噪声文本。
- 前端示例问题优先展示可部署的矩阵乘法和视频 AI 推理任务；其他模态仅用于意图解析评测覆盖。
- 对话流式接口改为先结构化解析，再输出确定性回复，避免 LLM 自由回复在参数完整时继续追问。
- 对话 API E2E 测试改为矩阵任务：创建对话 → 发送消息 → draft valid → confirm-intent → routing-result → submit。
- 前端可视化 E2E 已补充：打开 `/intent-chat` → 输入完整矩阵任务 → 查看右侧参数面板 → 点击确认提交任务 → 验证工单进入待路由状态。
- `order_materialize` 修复：同一模板存在多个 catalog 时，按工单 `task_type` 精确选择 catalog。
- 新增管理员意图评测页面：`/intent-evaluation`
- 新增固定数据集评测 API：
  - `GET /api/admin/intent-parser/evaluations/latest`
  - `GET /api/admin/intent-parser/evaluations/reports/{rule|llm}`
  - `POST /api/admin/intent-parser/evaluations/rule/run`
  - `POST /api/admin/intent-parser/evaluations/llm-batch/submit`
  - `POST /api/admin/intent-parser/evaluations/llm-batch/refresh`
- 新增 DashScope/OpenAI-compatible Batch API 支持：
  - 固定读取 `datasets/intent_eval/multi_business.jsonl`
  - 生成 Batch input JSONL
  - 上传 `/files`，创建 `/batches`
  - 刷新状态后下载 output file
  - 将 LLM 输出重新按固定数据集评分并写入 `reports/intent_eval_llm.json`
- 支持在管理员评测页面选择正式评测模型，候选模型由 `DASHSCOPE_EVAL_MODELS` 配置；候选模型必须先通过 `backend/scripts/smoke_dashscope_batch_models.py` 的 1 条样例 Batch smoke 测试。
- 前端意图评测页已展示：
  - 固定数据集样本分布
  - 规则评测准确率
  - LLM Batch 任务状态
  - 评测编号、生成时间、Batch 请求计数，以及运行中自动同步状态
  - 按 case_type 的准确率进度条
  - 成功/失败样本明细表
- 单条解析检测卡片
- 扩展到 8 个模态标签和 9 类意图任务，正式可部署业务仍为矩阵计算、视频 AI 推理。
- 数据集路由策略表达从固定枚举改为自然倾向表达：无特殊偏好、性能/完成时间优先、空闲/负载均衡、成本/资源节省。
- 单条解析检测支持选择评测样本作为输入，并展示字段判定、中文模态标签和路由 DAG JSON 预览。
- 用户端意图解析结果、管理端意图评测样本和业务任务中心已展示“所属模态”。
- 路由 DAG 预览的 `edges[]` 已补充 `bandwidth_mbps`，与 `data_mb` 一起提供给外部路由系统。

## 数据集覆盖

当前固定数据集为 `datasets/intent_eval/multi_business.jsonl`，共 360 条，真实分布如下：

- valid：288 条
- valid_default_strategy：36 条
- valid_colloquial：21 条
- missing_source：3 条
- missing_destination：3 条
- missing_time：3 条
- wrong_source_node：3 条
- wrong_destination_node：3 条

源/目的节点槽位覆盖 `h1-h13` 运营商端点；`compute-1`、`compute-2`、`compute-3` 仅作为系统/路由选择的计算节点，不进入用户源/目的槽位。路由策略覆盖 `resource_guarantee` 101 条、`low_latency_forwarding` 66 条、`fastest_completion` 65 条、`load_balance` 64 条、`cost_priority` 64 条。

样本字段覆盖矩阵规模/批次数、视频帧数/分辨率/fps、LLM prompt tokens/max_new_tokens/batch_size、训练样本数、存算数据量、连接数、抖动上限、边缘推理功耗预算、安全等级、路由策略、节点名称写错和缺失时间等场景。相对时间表达额外标注 `expected_time.duration_minutes`，仅用于评测时校验 `business_end_time - business_start_time`，不是业务工单字段。

## 本轮验证

```bash
cd backend
./venv/bin/python scripts/generate_intent_dataset.py --count 360 --output ../datasets/intent_eval/multi_business.jsonl
./venv/bin/python -c "from services.intent_batch_eval import run_rule_evaluation; r=run_rule_evaluation(); print(r['correct'], r['total'])"
# 360 360

./venv/bin/python -m pytest tests/test_intent_parser.py tests/test_conversations_api.py tests/test_business_tasks.py tests/test_business_tasks_api.py tests/test_order_sync.py
# 41 passed

cd ../frontend
npm run build
# built successfully, only existing chunk-size warning

PLAYWRIGHT_NO_WEBSERVER=1 npx playwright test tests/e2e/intent-chat.spec.js
# 1 passed
```

新增意图评测页验证：

```bash
cd backend
./venv/bin/python -c "from services.intent_batch_eval import run_rule_evaluation; r=run_rule_evaluation(); print(r['correct'], r['total'])"
# 360 360

cd ../frontend
npm run build
# built successfully
```

浏览器已验证 `/intent-evaluation` 可以显示固定数据集、规则评测、case_type 分布、成功/失败样本和单条解析检测入口。

当前扩展数据集真实大模型 Batch 已通过：

```text
job_id: intent-eval-20260608-174844-8ca41b57
model: qwen3.7-plus
status: completed
sample_count: 360
correct: 348
accuracy: 96.7%
passed: true
report: reports/intent_eval_llm.json
dataset_sha256: adaf5c30ffa7fd63d23cf84fed338dcb1ad2a9c7882f4d4c96b42ab794d20caa
failure_summary: 12 个失败样本均为 routing_strategy 字段，主要是“尽量少占资源”被模型判为 load_balance，而数据集标注为 cost_priority。
```

历史真实大模型 Batch 记录：

```text
job_id: intent-eval-20260603-222617-90569be4
model: qwen3.7-plus
batch_id: batch_8a23fd90-3758-44df-8598-f3c22519a1d2
status: completed
sample_count: 360
correct: 360
accuracy: 100.0%
report: reports/intent_eval_llm.json
input: reports/intent_eval_batches/intent-eval-20260603-222617-90569be4/input.jsonl
output: reports/intent_eval_batches/intent-eval-20260603-222617-90569be4/output.jsonl
time_scoring: 338/338 duration_minutes matched
```

注意：上述 `intent-eval-20260603-222617-90569be4` 是 2026-06-03 旧数据集结果。2026-06-08 数据集扩展到 8 个模态、9 类任务和更丰富的路由倾向表达后，页面会将该 LLM 报告标记为“数据集已更新”，不应作为当前扩展数据集的正式验收截图；当前有效记录以上方 `intent-eval-20260608-174844-8ca41b57` 为准。

排查记录：`batch-test-model` 官方 smoke Batch 可在约 25 秒完成；`qwen3.7-plus` 1 条 smoke Batch 可完成。2026-06-03 21:24 使用 1 条 JSON 示例请求继续测试 `qwen3.7-max`、`qwen3.6-plus`、`qwen3.6-flash`、`qwen3.5-plus`、`qwen3.5-flash`、`qwen3-max`、`qwen-plus`，600 秒内均停留在 `in_progress 0/1` 并超时取消。随后去掉 `response_format` 进行基础 Batch 推理补充测试，`qwen3.7-max`、`qwen3.6-plus` 仍在 300 秒内 `in_progress 0/1` 超时。2026-06-03 21:44 按百炼支持列表补测 `qwen3.7-plus`、`qwen-plus-latest`、`qwen-flash`、`qwen-long`、`qwen3-max`，其中 `qwen3.7-plus` 与 `qwen-long` 在 420 秒内完成 1/1；`qwen-plus-latest`、`qwen-flash`、`qwen3-max` 仍为 `0/1` 超时。因此当前正式 Batch 评测下拉框仅保留 `qwen3.7-plus`、`qwen-long`，避免把不能稳定完成的模型纳入验收流程。

前端 E2E 截图：

- `frontend/test-results/intent-chat-intent-chat-parses-matrix-task-and-submits-order-chromium/intent-chat-parsed.png`
- `frontend/test-results/intent-chat-intent-chat-parses-matrix-task-and-submits-order-chromium/intent-chat-submitted.png`

## 待完成

- 生成评审材料：数据集构造说明、样本覆盖表、准确率 JSON 报告、失败样本分析和前端截图。
- 可选增强：将 `reports/intent_eval.json` / `reports/intent_eval_llm.json` 转成更适合放入测试方案的 Markdown/图表摘要。
- 用浏览器补齐 `/intent-evaluation`、`/intent-chat`、`/business-tasks` 的演示截图。
