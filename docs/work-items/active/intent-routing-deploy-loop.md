# Work Item: 意图解析 → 路由 → 部署闭环

Status: in_progress
Owner Agent: Coder
Last Updated: 2026-05-28

## Goal

完成从用户对话提交工单到外部路由系统回写结果、自动物化实例的完整闭环。

## Non-goals

- 不新增业务类型（只做矩阵乘法）
- 不重构前端框架
- 不实现多租户隔离

## Context

当前状态：
- 意图解析已完成（qwen3-max + 确定性验证层 + 节点校验）
- 工单提交时生成 DAG JSON（routing_input_dag 字段）
- routing_status=pending 供外部路由系统扫表
- POST /api/orders/{id}/routing-result 接收路由结果

待完成：
- 外部路由系统联调（确认 DAG 格式兼容性）
- 收到路由结果后自动物化实例
- GPU 编号写入容器环境变量
- 业务目标成功率采集

## Files Likely Involved

- `backend/api/orders.py` — routing-result endpoint
- `backend/services/order_materialize.py` — 物化逻辑
- `backend/services/dag_builder.py` — DAG 生成
- `backend/services/dag_executor.py` — 容器部署
- `docs/business-objective-success-rate-design.md` — 成功率设计

## Acceptance Criteria

- [ ] 外部路由系统能扫到 routing_status=pending 的工单
- [x] 路由结果回写后 routing_status 变为 completed
- [x] 物化实例时 GPU 编号正确传入容器
- [ ] 任务执行后能采集业务指标并评估成功率

## Commands Run

- `cd /Users/yanjia/codes/manage_deploy/frontend && npm run build`: pass，1696 modules transformed，无编译错误（Integration Fix Agent 复验）
- `git diff --check`: pass，无空白错误

## Findings

- `backend/services/order_materialize.py` 已有完整的 `_resolve_node_id` 和 `materialize_after_routing` 逻辑，但 `POST /{order_id}/routing-result` 端点未调用它，只更新了 `routing_status`。
- `RoutingPlacement.node_id` 字段在 payload 中承载 role 名称（source/compute/sink），`worker_host` 承载实际主机标识。
- `BusinessTemplateCatalog` 通过 `template_id` 关联，字段为 `source_node_name`/`compute_node_name`/`sink_node_name`。
- 前端 `formatOrderStatus` 缺少 `orphaned` 映射；`draft.parse_status` 和实例状态直接显示英文枚举值；`el-select` 过滤选项全为英文。
- **[Integration Fix]** Review finding "TaskScheduler singleton misuse" 经核查无效：`TaskScheduler` 所有方法均操作模块级 `scheduler` 对象（`services/scheduler.py:13`），`TaskScheduler()` 是无状态代理，`instances.py` 全文同样使用 `TaskScheduler()` 模式，行为一致，无需修改。

## Changes Made

- `backend/api/orders.py`：
  - 新增 import：`BusinessTemplateCatalog`, `NodeModel`, `DeploymentMode`, `TaskInstanceNodeOverride`, `_resolve_node_id`, `TaskScheduler`
  - `receive_routing_result` 端点：收到 placements 后查 catalog 获取 role→template_node_name 映射，构建 `node_overrides`（含 `TASK_ROLE`/`GPU_DEVICE`/`SOURCE_NAME`/`DESTINATION_NAME` env），调用 `_create_instance_from_template` 物化实例，注册 `schedule_task_start`/`schedule_task_end`，更新 `order.materialized_instance_id` 和 `order.status = MATERIALIZED`
  - **[Integration Fix]** 幂等性守卫：在端点体开头（fetch order 之后）添加 `if order.materialized_instance_id` 检查，重复调用返回 409
  - **[Integration Fix]** `_resolve_node_id` 调用包裹 `try/except ValueError`，抛出 HTTPException(422) 而非 500
- `frontend/src/views/IntentChatView.vue`：
  - 新增 `ORDER_STATUS_LABEL`/`ROUTING_STATUS_LABEL`/`TASK_STATUS_LABEL`/`PARSE_STATUS_LABEL` 常量
  - 新增 `formatTaskStatus`/`formatParseStatus` 函数，重写 `formatOrderStatus`/`formatRoutingStatus` 使用常量
  - 修复 `el-select` 过滤选项为中文标签
  - 修复 `draft.parse_status` 显示为中文（`formatParseStatus`）
  - 修复实例状态显示为中文（`formatTaskStatus`）
  - **[Integration Fix]** `ORDER_STATUS_LABEL` 补充 `awaiting_routing: '路由中'`
  - **[Integration Fix]** `orderStatusType` 更新为实际 `OrderStatus` 枚举值：`pending`/`awaiting_routing` → `warning`，`materialized` → `primary`，`completed` → `success`，`failed` → `danger`，`cancelled`/`orphaned` → `info`

## Open Risks

- `RoutingPlacement.node_id` 字段语义依赖外部路由系统约定（必须传 role 名称）；若外部系统传 UUID 则 catalog 映射失效，会 fallback 到直接用 node_id 作为 template_node_name（可能找不到模板节点）。
- `business_start_time`/`business_end_time` 为 None 时不注册调度 job，实例将停留在 SCHEDULED 状态不自动启动。
- 业务指标采集（成功率）尚未实现。

## Next Agent Instructions

E2E Deploy Test Agent 复测命令：

```bash
# 1. 验证幂等性守卫（第二次调用应返回 409）
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/orders/{order_id}/routing-result \
  -H "Content-Type: application/json" \
  -d '{"placements":[{"node_id":"source","worker_host":"127.0.0.1","gpu_device":null}]}'

# 2. 验证无效 worker_host 返回 422（非 500）
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8000/api/orders/{order_id}/routing-result \
  -H "Content-Type: application/json" \
  -d '{"placements":[{"node_id":"source","worker_host":"nonexistent-host","gpu_device":null}]}'

# 3. 前端构建验证
cd /Users/yanjia/codes/manage_deploy/frontend && npm run build
```

其余待完成：
- 验证外部路由系统回调格式：确认 `placements[].node_id` 字段确实传 role 名称（source/compute/sink）。
- 实现业务目标成功率采集（参考 `docs/business-objective-success-rate-design.md`）。
