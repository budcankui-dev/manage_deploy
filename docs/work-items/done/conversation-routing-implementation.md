# Work Item: 对话式工单 + 意图解析 + 外部路由 DAG + 自动调度

## Goal

实现从"普通用户对话提交业务需求"到"外部路由系统计算路径并自动部署"的完整闭环。
核心变更：用户确认意图后先创建 TaskOrder（直接关联 user_id），再生成 RoutingRequest 供外部路由系统扫描。

## Non-goals

- 用户上传文件链路（第二阶段）
- 多策略路由对比 UI
- 外部路由系统本身的实现（只做接口契约）
- LLM API 真实接入（第一阶段用 rule + mock，预留 LLM 接口）

## Context

当前状态：
- Conversation / IntentDraft / RoutingRequest 模型已存在，但以 conversation 为中心
- TaskOrder 缺少 user_id、source/destination、business_time、routing_status
- IntentDraft 缺少 source/destination、business_time、parser 元数据
- RoutingRequest 缺少 order_id、input_payload（DAG JSON）、result_payload
- Node 缺少 node_kind、display_name、is_schedulable、is_routable
- 意图解析是纯规则正则，不支持 source/destination/time 提取
- 前端 IntentChatView 存在但缺少参数确认卡片和路由结果展示

设计文档：docs/conversation-order-routing-design.md

## Phase 1: 数据模型对齐（后端）

### 1.1 Node 扩展
- `node_kind` enum: worker | terminal | router | switch | storage | unknown
- `display_name` nullable
- `is_schedulable` bool default true
- `is_routable` bool default true
- `deleted_at` nullable

### 1.2 TaskOrder 扩展
- `user_id` FK -> users.id, NOT NULL
- `conversation_id` nullable FK -> conversations.id
- `intent_draft_id` nullable FK -> intent_drafts.id
- `routing_request_id` nullable FK -> routing_requests.id
- `source_name` varchar(255)
- `destination_name` varchar(255)
- `business_start_time` datetime
- `business_end_time` datetime
- `routing_status` enum: not_required | pending | computing | completed | failed | cancelled
- `deleted_at` nullable

### 1.3 IntentDraft 扩展
- `source_name` nullable
- `destination_name` nullable
- `business_start_time` nullable datetime
- `business_end_time` nullable datetime
- `parser_name` varchar(64)
- `parser_version` varchar(32)
- `raw_llm_response` JSON nullable
- `normalized_intent` JSON nullable
- `confidence` float nullable

### 1.4 RoutingRequest 扩展
- `order_id` nullable FK -> task_orders.id（新增，与 conversation_id 并存过渡）
- `source_name` varchar(255)
- `destination_name` varchar(255)
- `business_start_time` datetime
- `business_end_time` datetime
- `input_payload` JSON（外部路由 DAG JSON）
- `result_payload` JSON
- `requested_strategies` JSON
- `selected_strategy` varchar(255)
- `error_message` text nullable
- `deleted_at` nullable

## Phase 2: 意图解析模块化 + source/destination/time 提取

### 2.1 IntentParser 接口定义
```python
class IntentParser(Protocol):
    def parse(self, message: str, context: dict | None) -> ParseResult: ...
    def validate(self, parsed: ParseResult) -> list[str]: ...
    def to_routing_payload(self, parsed: ParseResult, order: TaskOrder) -> dict: ...
```

### 2.2 扩展 ParseResult
- 新增 source_name, destination_name, business_start_time, business_end_time
- 新增 parser_name, parser_version

### 2.3 RuleBasedIntentParser 升级
- 提取 source/destination（关键词："从X到Y"、"源X目的Y"）
- 提取时间（"明天上午9点开始跑2小时"、"现在开始"）
- 校验必填字段完整性

### 2.4 MockIntentParser
- 用于单测和离线评测
- 接受固定输入输出映射

### 2.5 批量评测 CLI
- `backend/scripts/evaluate_intent_parser.py`
- 输入 JSONL 数据集，输出准确率报告

## Phase 3: 工单创建 + 路由 DAG Payload 生成

### 3.1 工作流变更（核心）
当前流程：confirm-intent -> routing -> submit -> business-task
新流程：confirm-intent -> TaskOrder(pending) -> RoutingRequest(input_payload) -> 外部扫描 -> 回写 -> scheduled

### 3.2 confirm-intent 后创建 TaskOrder
- 校验 source_name/destination_name 匹配 nodes 表
- 校验 business_start_time/business_end_time 合法
- 创建 TaskOrder(user_id, routing_status=pending)
- 同步创建 RoutingRequest(order_id, input_payload)

### 3.3 DAG JSON 生成器
- `services/routing_payload_builder.py`
- 输入：confirmed IntentDraft + TaskOrder
- 输出：外部路由系统要求的 DAG JSON
- 字段映射：
  - job_id = f"{job_name}_{modal}_{order.id}"
  - submit_ts_ms = business_start_time epoch ms
  - constraints.deadline_ms = business_end_time epoch ms
  - nodes/edges 从 BusinessTemplateCatalog 查模板结构

### 3.4 路由结果回写 API 升级
- POST /api/routing-results/{id} 支持写入 result_payload
- 回写后更新 TaskOrder.routing_status = completed
- 触发实例物化和调度入队

### 3.5 外部路由扫描接口（供外部系统调用）
- GET /api/routing-requests?status=pending（外部系统轮询）
- PATCH /api/routing-requests/{id}/claim（标记 computing）

## Phase 4: 前端对话流程升级

### 4.1 IntentChatView 参数确认卡片
- 展示解析出的 task_type、source_name、destination_name
- 展示 business_start_time / business_end_time（日期时间选择器）
- 展示 business_objective
- 缺参字段高亮提示，支持用户手动补填

### 4.2 路由状态展示
- confirm-intent 后显示"工单已创建，等待路由计算"
- 轮询或 WebSocket 展示 routing_status 变化
- pending -> computing -> completed | failed

### 4.3 路由结果展示
- 展示 source -> compute -> sink 路径
- 展示 selected_strategy、estimated_metric
- 展示 placements（哪些逻辑节点落在哪些物理节点）

### 4.4 工单详情页
- 从 BusinessTasksHubView 跳转
- 展示部署状态、业务指标、是否达标

## Phase 5: 调度集成 + E2E 验证

### 5.1 路由完成后自动物化实例
- routing_status=completed 后，调用 instance_builder 物化
- 设置 deployment_mode=scheduled, scheduled_start/end_time

### 5.2 调度器按时间窗口自动启动
- scheduler.py 扫描 scheduled 实例
- business_start_time <= now 时自动启动
- business_end_time 到期自动停止

### 5.3 E2E 验证脚本
- 模拟完整流程：对话 -> 意图 -> 工单 -> 路由 -> 部署 -> 指标
- 可用 mock 路由结果快速验证

## Implementation Steps（执行顺序）

1. Phase 1.1-1.4: 数据模型迁移（Alembic migration）
2. Phase 2.2-2.3: 扩展 ParseResult + RuleBasedParser 升级
3. Phase 3.1-3.3: 工作流变更 + DAG payload 生成
4. Phase 3.4-3.5: 路由回写 + 外部扫描接口
5. Phase 4.1-4.3: 前端对话流程
6. Phase 5.1-5.3: 调度集成 + E2E

## Required Tests

- [ ] 意图解析：source/destination/time 提取单测
- [ ] DAG payload 生成：字段映射正确性
- [ ] 工单创建：user_id 关联、routing_status 状态机
- [ ] 路由回写：result_payload 写入、状态流转
- [ ] 节点名称解析：display_name/hostname 匹配
- [ ] 时间校验：start < end、不早于当前时间
- [ ] E2E：对话到部署完整链路

## Acceptance Criteria

- 普通用户通过对话提交工单，工单直接关联 user_id
- 意图解析提取 source_name、destination_name、business_start/end_time
- 确认后创建 TaskOrder(routing_status=pending)
- 系统生成符合外部路由格式的 DAG JSON
- 外部路由系统可通过 API 扫描 pending 请求并回写结果
- 路由完成后工单进入 scheduled，调度器按时间窗口部署
- 前端展示参数确认、路由状态、路由结果、部署状态

## Open Risks

- 外部路由系统 DAG JSON 格式可能变更（需要版本化）
- LLM parser 第一阶段不接入，规则解析覆盖有限
- 并发路由请求的幂等性（外部系统 claim 机制）
- Node display_name 数据需要管理员预先配置

## Next Agent Instructions

Implementation Agent 按 Phase 顺序执行。每个 Phase 完成后：
1. 运行相关测试
2. 更新本文件标记完成状态
3. 如遇阻塞，记录到 Open Risks 并继续下一 Phase
