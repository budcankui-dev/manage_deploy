# 对话式工单与外部路由设计草案

本文记录主会话关于“普通用户通过对话提交业务工单，外部路由系统计算路径，平台自动部署”的产品与架构讨论。当前是设计草案，不代表已实现。

## 目标

- 普通用户通过前端对话系统提交业务需求。
- 后端调用大模型 API 解析用户意图，生成结构化任务参数。
- 后端校验参数完整性、格式和取值范围，不合法时通过对话追问或拒绝。
- 用户确认后先创建工单，工单立即可见，并进入待路由状态。
- 平台为工单生成外部路由系统可消费的 DAG JSON。
- 外部路由系统读取待路由工单/路由请求，计算业务节点选取与路径结果。
- 路由结果回写后，平台将工单转入 scheduled 调度队列，并可按业务时间窗口自动部署。
- 管理员保留完整后台能力：用户管理、工单管理、部署系统、节点/模板/实例管理、路由与评测审计。

## 核心原则

- `TaskOrder` 必须直接关联 `User`，不能只通过 `Conversation` 间接归属。
- `Conversation` 建议保留，作为普通用户对话入口、审计链路和追问上下文。
- 工单可来自会话，也可来自未来的非会话入口，因此 `conversation_id` 应为可选来源字段。
- 后端意图解析应模块化，支持线上调用和离线批量评测复用同一套解析方法。
- 业务数据流验收仍遵循随路计算：source -> 中间业务节点 -> sink。
- 外部路由算法价值通过 placements/path 决定业务角色落点，并让业务数据沿该路径流转来体现。
- 科研验收阶段优先采用数据库扫描交互，API 回调作为可选实现预留。
- 用户强制填写业务开始和结束时间后，平台应优先创建 scheduled 工单，由调度器自动在时间窗口内启动和停止，不要求用户提交后立刻运行。
- 采用方案 B：用户确认后先创建 `TaskOrder`，再由外部路由系统扫描新增待路由工单/路由请求并计算路径。`RoutingRequest` 是工单的路由计算子任务，而不是工单创建前置对象。

## 节点类型

现有 `nodes` 表可以扩展一个类型字段，用于区分拓扑角色：

```text
node_kind = worker | terminal | router | switch | storage | unknown
```

第一阶段最少需要：

- `worker`：可部署 Node Agent 和业务容器的工作节点。
- `terminal`：用户源终端或目的终端，只参与路由语义，不一定运行容器。

这样可以避免新增一整套拓扑实体表，同时满足“源终端和目的节点名称必须由用户填写”的验收需求。

建议 `nodes` 增量字段：

- `node_kind`
- `display_name` nullable
- `is_schedulable` bool，是否可部署业务容器
- `is_routable` bool，是否参与外部路由图
- `deleted_at` nullable，逻辑删除

节点名称解析规则：

- 用户输入的 `source_name` / `destination_name` 先按 `display_name` 匹配。
- 再按 `hostname` 匹配。
- 多个匹配时要求用户确认。
- 未匹配时不创建路由请求，进入追问或参数校验失败。

## 用户必填参数

普通用户最终提交工单前必须补齐：

- `task_type`：业务类型，例如 `high_throughput_matmul`。
- `source_name`：源终端或源节点名称。
- `destination_name`：目的节点名称。
- `business_start_time`：用户期望业务开始时间。
- `business_end_time`：用户期望业务结束时间。
- `business_objective`：业务目标，例如 `compute_latency_ms <= 60000ms`。
- `data_profile`：业务输入画像，例如矩阵规模、批次数、随机种子等。

可选或后续待定：

- 用户上传输入数据。
- 用户指定资源偏好或禁用节点。
- 用户选择路由策略集合。

## 时间字段语义

需要区分业务时间窗口和平台调度时间：

- `business_start_time` / `business_end_time`：用户业务语义时间窗口，供外部路由系统做资源可用性与路径选择。
- `scheduled_start_time` / `scheduled_end_time`：Task Manager 实际部署调度时间，用于容器启停。

第一阶段可以默认：

```text
scheduled_start_time = business_start_time
scheduled_end_time = business_end_time
```

后续可支持预部署与延迟回收：

```text
scheduled_start_time = business_start_time - warmup_margin
scheduled_end_time = business_end_time + cleanup_margin
```

基础校验：

- `business_start_time` 必填。
- `business_end_time` 必填。
- `business_end_time > business_start_time`。
- `business_start_time` 不应早于当前时间太多。
- 业务持续时间应在允许范围内，例如 1 分钟到 24 小时，具体阈值由产品配置决定。
- 如果用户说“现在开始跑 2 小时”，可解析为 `start=now`、`end=now+2h`。
- 如果用户只说“明天上午跑”，应追问明确结束时间，或使用明确的产品默认策略。

科研验收阶段推荐：

- 用户确认意图后，创建 `TaskOrder` 时使用 `deployment_mode=scheduled`。
- `scheduled_start_time` 和 `scheduled_end_time` 来自业务时间窗口。
- 如果 `business_start_time <= now`，可以允许调度器立即启动，仍然视为 scheduled 模式。
- 路由完成后若 `auto_start=true`，含义应改为“自动进入调度队列”，而不是立即无视时间窗口运行。

## 推荐数据关系

```text
User
 -> Conversation 可选
 -> IntentDraft 可选
 -> TaskOrder 必须
 -> RoutingRequest 可选
 -> TaskInstance
```

建议增量字段：

`task_orders`：

- `user_id`
- `conversation_id` nullable
- `intent_draft_id` nullable
- `routing_request_id` nullable
- `source_name`
- `destination_name`
- `business_start_time`
- `business_end_time`
- `routing_status`，例如 `not_required | pending | computing | completed | failed | cancelled`
- `deleted_at` nullable，用于逻辑删除和外部路由巡检跳过

`intent_drafts`：

- `source_name`
- `destination_name`
- `business_start_time`
- `business_end_time`
- `parser_name`
- `parser_version`
- `raw_llm_response` JSON
- `normalized_intent` JSON
- `confidence` nullable

`routing_requests`：

- `order_id`
- `source_name`
- `destination_name`
- `business_start_time`
- `business_end_time`
- `input_payload` JSON
- `result_payload` JSON
- `requested_strategies` JSON
- `selected_strategy`
- `error_message`
- `deleted_at` nullable，用于外部路由系统巡检时忽略逻辑删除记录

待定用户上传数据：

`user_uploaded_objects`：

- `user_id`
- `conversation_id` nullable
- `order_id` nullable
- `object_uri`
- `filename`
- `content_type`
- `size_bytes`
- `status`

## 外部路由交互

第一阶段以数据库扫描为主，API 回调作为可选能力预留。

数据库扫描模式：

- 本系统在用户确认意图后先写入 `task_orders`，工单状态对用户可见。
- 本系统同步或异步为该工单写入 `routing_requests`，并在 `task_orders.routing_status` 标记为 `pending`。
- 外部路由系统定时扫描新增待计算记录。
- 推荐扫描 `routing_requests where status=pending and deleted_at is null`；如果外部系统只方便扫订单，也可扫描 `task_orders where routing_status=pending and deleted_at is null` 后再读取关联 routing request。
- 外部路由系统领取任务后把状态更新为 `computing`，避免重复计算。
- 计算完成后写回 `routing_requests.result_payload`、`placements`、`estimated_metric`、`selected_strategy`，并将 `routing_requests.status` 与 `task_orders.routing_status` 置为 `completed`。
- 计算失败时状态置为 `failed`，写入 `error_message`。
- 逻辑删除记录不物理删除，外部系统巡检时跳过。

建议 `RoutingRequestStatus` 扩展：

```text
pending -> computing -> completed | failed | cancelled
```

API 预留模式：

- `POST /api/routing-requests` 创建请求。
- `GET /api/routing-requests/{id}` 查询请求。
- `POST /api/routing-results/{id}` 回写结果。
- 第一阶段可不作为主路径实现。

给外部路由系统的 DAG JSON 以外部路由系统当前接收格式为准。意图解析和参数校验完成后，后端需要把结构化 intent 转换为如下 `RoutingRequest.input_payload`：

```json
{
  "job_id": "视频AI推理_低延时转发模态_3f4a9205-c4b3-4517-b520-4e0ed9e6b71d",
  "job_name": "视频AI推理",
  "modal": "低延时转发模态",
  "_comment": "低延时转发模态",
  "policy_type": "COST_CONSTRAINED",
  "submit_ts_ms": 1777341600000,
  "constraints": {
    "budget": null,
    "deadline_ms": 1777342200000
  },
  "nodes": [
    {
      "node_id": "video",
      "resources": {
        "cpu_units": 20,
        "mem_mb": 1024,
        "disk_mb": 1024,
        "gpu_units": 0
      },
      "exec": {
        "est_runtime_ms": 600000
      }
    },
    {
      "node_id": "infer",
      "resources": {
        "cpu_units": 10,
        "mem_mb": 1024,
        "disk_mb": 1024,
        "gpu_units": 0
      },
      "exec": {
        "est_runtime_ms": 600000
      }
    }
  ],
  "edges": [
    {
      "from": "video",
      "to": "infer",
      "data_mb": 20
    }
  ]
}
```

字段映射建议：

- `job_id`：由 `job_name`、`modal` 和工单 UUID 生成，保证外部路由系统幂等识别。
- `job_name`：来自业务类型的人类可读名称，例如“视频AI推理”或“科学计算矩阵乘法演示”。
- `modal` / `_comment`：来自用户选择或意图解析出的业务模态；`_comment` 仅用于外部系统展示和调试。
- `submit_ts_ms`：第一阶段按用户填写的 `business_start_time` 转为 epoch milliseconds；如果外部路由系统后续要求真实提交时间，则新增 `order_created_ts_ms` 或调整映射。
- `constraints.deadline_ms`：用户填写的 `business_end_time` 转为 epoch milliseconds。
- `constraints.budget`：用户未填写预算时为 `null`。
- `policy_type`：由业务目标或用户偏好映射；第一阶段可用固定默认值，例如 `COST_CONSTRAINED`。
- `nodes[].node_id`：路由 DAG 内部逻辑节点名，不等于平台 `nodes.id`。例如 `video`、`infer`、`source`、`compute`、`sink`。
- `nodes[].resources`：外部路由系统需要的资源约束，单位使用 `cpu_units`、`mem_mb`、`disk_mb`、`gpu_units`。
- `nodes[].exec.est_runtime_ms`：估计运行时间，可由业务模板默认值、用户输入或规则估算得到。
- `edges[].from/to`：引用 `nodes[].node_id`，表达业务数据流向。
- `edges[].data_mb`：边上的估计数据量，可由用户上传文件大小、业务画像或默认规则估算。

该 payload 是给外部路由系统计算路径和节点选择的输入，不直接等同于 Task Manager 的 `TaskTemplate` 或 `TaskInstance`。外部路由系统回写 placements 后，平台再把逻辑节点映射到实际部署节点，并物化为可启动的 DAG 实例。

回写结果至少包含：

- `status`
- `placements`
- `selected_strategy`
- `path`
- `estimated_metric`
- `explanation` 或 `decision_trace`
- `external_routing_id`

## 后端工作流

建议流程：

```text
用户输入
 -> ConversationMessage
 -> LLM Intent Parser
 -> IntentDraft
 -> 参数校验
 -> 缺字段则追问
 -> 用户确认
 -> TaskOrder(status=pending, routing_status=pending)
 -> RoutingRequest(order_id, input_payload, status=pending)
 -> 外部路由系统扫描并置为 computing
 -> RoutingResult 回写
 -> TaskOrder(routing_status=completed, deployment_mode=scheduled)
 -> TaskInstance scheduled
 -> 调度器按业务时间窗口自动部署
 -> 指标上报与业务评估
```

后端可以采用工作流或 Agent 范式，但边界要稳定：

- 解析：自然语言转结构化 intent。
- 校验：字段完整性、格式、范围、时间窗口、资源约束。
- 补问：生成缺失字段问题。
- 路由载荷生成：转换为外部路由 DAG JSON。
- 工单创建：消费已确认的结构化意图，先创建用户可见工单，再等待路由计算结果。

## 意图解析模块化

建议定义统一接口：

```text
IntentParser
- parse(message, context) -> ParsedIntent
- validate(parsed) -> ValidationResult
- to_routing_payload(parsed) -> RoutingDAGPayload
```

实现：

- `RuleBasedIntentParser`：当前规则解析，作为测试和兜底。
- `LLMIntentParser`：调用大模型 API。
- `HybridIntentParser`：规则抽取 + LLM 补全/纠错。
- `MockIntentParser`：单测和离线评测。

解析输出必须版本化：

- `parser_name`
- `parser_version`
- `prompt_version`
- `schema_version`
- `raw_llm_response`
- `normalized_intent`

## 意图解析评测

为了满足解析准确率验收，解析方法必须可被外部批量调用。

建议提供 CLI：

```bash
backend/venv/bin/python backend/scripts/evaluate_intent_parser.py \
  --dataset datasets/intent_eval/matmul.jsonl \
  --parser llm \
  --output reports/intent_eval.json
```

也可提供管理员 API：

```text
POST /api/admin/intent-parser/parse-one
POST /api/admin/intent-parser/evaluate
```

数据集策略：

- 第一阶段可使用项目自建数据集。
- 可用当前解析方法生成初始标签，以满足工程验收中的一致性指标。
- 需要明确区分 `parser-consistency accuracy` 与人工标注 `human-gold accuracy`。
- 自标数据集能验证系统一致性，但不能完全代表真实语义准确率；后续应补少量人工 gold set。

## 前端页面设计

普通用户：

- 对话入口：自然语言提交业务需求。
- 参数确认卡片：展示任务类型、源终端、目的节点、业务时间窗口、数据画像、业务目标。
- 缺参追问：源/目的/时间/目标缺失时引导补齐。
- 路由等待页：展示 routing status。
- 路由结果页：展示 source -> compute -> sink 路径、策略、估计指标、解释说明。
- 工单详情页：展示部署状态、业务指标、是否达标、结果对象。

管理员：

- 用户管理。
- 工单中心。
- 会话与意图草稿审计。
- 路由请求与路由结果管理。
- 节点、模板、实例管理。
- 意图解析评测集与准确率报告页面。

## 建议拆分 Work Items

后续建议由 Product Architect Agent 拆成以下 work items：

- `conversation-order-user-linking.md`
  - 为工单补用户归属和会话/草稿/路由来源关联。
  - 修正普通用户与管理员查询权限。

- `intent-parser-llm-contract.md`
  - 定义 LLM parser schema、校验规则、source/destination/time 必填。
  - 增加批量评测入口。

- `routing-request-dag-contract.md`
  - 定义外部路由 DAG JSON。
  - 增加 `input_payload`、`result_payload`、策略和错误字段。

- `conversation-ui-order-flow.md`
  - 普通用户对话 UI、参数确认、路由结果、自动部署状态展示。

- `admin-console-user-routing-audit.md`
  - 用户管理、会话审计、路由审计、评测报告等管理员能力。

## 待定问题

- 用户上传输入数据是否进入第一阶段。
- 源终端与目的节点名称来自哪张拓扑表，是否需要单独的 endpoint/catalog 表。
- 外部路由系统最终是 API 模式、数据库扫描模式，还是两者都保留。
- 自动部署是否默认开启，还是用户看到路由结果后再确认。
- 业务时间窗口的默认最小/最大持续时间。
- LLM API 的模型、超时、重试、费用控制和审计策略。
