# 开发进度追踪

## Phase 1: 数据模型对齐 ✅
- enums.py: 新增 NodeKind, RoutingStatus, 扩展 RoutingRequestStatus(+COMPUTING, +CANCELLED)
- models/__init__.py: Node 新增 node_kind/display_name/is_schedulable/is_routable/deleted_at
- models/__init__.py: TaskOrder 新增 user_id/conversation_id/intent_draft_id/routing_request_id/source_name/destination_name/business_start_time/business_end_time/routing_status/deleted_at
- models/__init__.py: IntentDraft 新增 source_name/destination_name/business_start_time/business_end_time/parser_name/parser_version/raw_llm_response/normalized_intent/confidence
- models/__init__.py: RoutingRequest 新增 order_id/source_name/destination_name/business_start_time/business_end_time/input_payload/result_payload/requested_strategies/selected_strategy/error_message/deleted_at
- database.py: 对应 _ensure_column 调用
- schemas/conversation.py: 更新 IntentDraftUpdate/IntentDraftResponse/RoutingRequestResponse/RoutingResultCallback
- api/routing.py: 新增 GET /api/routing-requests (外部扫描), PATCH /api/routing-requests/{id}/claim

## Phase 2: 意图解析模块化 ✅
- services/intent_parser.py: 重写，定义 IntentParser Protocol, 扩展 ParseResult
- 新增 _extract_source_destination(): 支持"从X到Y"、"源X目的Y"、"source:X dest:Y"
- 新增 _extract_time(): 支持"现在开始跑N小时/分钟"
- validate_draft_fields(): 新增 source_name/destination_name/business_start_time/business_end_time 必填校验
- services/intent_workflow.py: 更新 trace 步骤
- api/conversations.py: draft 创建时写入新字段, _draft_to_dict 包含新字段
- scripts/evaluate_intent_parser.py: 批量评测 CLI
- datasets/intent_eval/matmul.jsonl: 5 条测试用例, 100% 通过

## Phase 3: 工单创建 + 路由 DAG Payload 生成 ✅
- services/routing_payload_builder.py: 新建，生成外部路由 DAG JSON
- api/conversations.py confirm_intent(): 重写，确认后创建 TaskOrder + RoutingRequest + DAG payload
- services/order_materialize.py: 新建，路由完成后物化实例
- api/routing.py receive_routing_result(): 路由回写后自动触发物化

## Phase 4: 前端对话流程升级 ✅
- IntentChatView.vue: 意图面板新增 source/destination/time 展示
- IntentChatView.vue: 路由面板展示 DAG payload、routing status、placements
- IntentChatView.vue: 简化工作流（确认即创建工单+路由，无需单独"请求路由"）
- IntentChatView.vue: 路由轮询支持 computing 状态
- 前端构建通过

## Phase 5: 调度集成 + E2E 验证 ✅
- 调度器已有 schedule_task_start/end，实例创建时自动注册
- scripts/e2e_conversation_routing.py: 完整 E2E 验证脚本
- 全链路导入验证通过
