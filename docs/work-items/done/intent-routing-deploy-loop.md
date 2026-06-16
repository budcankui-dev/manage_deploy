# Work Item: 意图解析 → 路由 → 部署闭环

> 历史记录：本文记录 2026-05 至 2026-06 早期闭环开发过程，不作为当前路由系统对接规范。当前唯一对接规范见 `docs/routing-system-integration-guide.md`；当前 DAG 生成入口为 `backend/services/routing_payload_builder.py`。

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
- `backend/services/routing_payload_builder.py` — 当前 DAG 生成
- `backend/services/dag_executor.py` — 容器部署
- `docs/business-objective-success-rate-design.md` — 成功率设计

## Acceptance Criteria

- [x] 外部路由系统能扫到 routing_status=pending 的工单
- [x] 路由结果回写后 routing_status 变为 completed
- [x] 物化实例时 GPU 编号正确传入容器
- [ ] 任务执行后能采集业务指标并评估成功率

## Commands Run

- `cd /Users/yanjia/codes/manage_deploy/frontend && npm run build`: pass，1696 modules transformed，无编译错误（Integration Fix Agent 复验）
- `git diff --check`: pass，无空白错误
- `curl http://127.0.0.1:8000/health`: pass，`{"status":"healthy"}`
- `curl /api/nodes`: pass，4 节点（compute-1/2/3, admin）
- `POST /api/conversations + confirm-intent`（conv_id=c40bd656）: pass，对话状态变为 `awaiting_routing`，order_id=717eb67d
- `GET /api/orders/717eb67d`: pass，`routing_status=pending`，`routing_input_dag` 有值，`source_name=compute-1`，`destination_name=compute-3`
- `POST /api/orders/717eb67d/routing-result`（placements: compute-1/2/3）: pass，返回 `{"status":"ok","instance_id":"46cbe5ce"}`
- `GET /api/orders/717eb67d`（物化后）: pass，`routing_status=completed`，`status=materialized`，`materialized_instance_id=46cbe5ce`
- `GET /api/instances/46cbe5ce`: pass，`deployment_mode=scheduled`，3 节点，env 含 `TASK_ROLE`/`GPU_DEVICE`（compute 节点=0）/`SOURCE_NAME`/`DESTINATION_NAME`
- `POST /api/orders/717eb67d/routing-result`（重复调用）: pass，返回 409
- `POST /api/orders/fad74f87/routing-result`（worker_host=nonexistent-host）: pass，返回 422，`{"detail":"Node not found: nonexistent-host"}`

## Findings

- `backend/services/order_materialize.py` 已有完整的 `_resolve_node_id` 和 `materialize_after_routing` 逻辑，但 `POST /{order_id}/routing-result` 端点未调用它，只更新了 `routing_status`。
- `RoutingPlacement.node_id` 字段在 payload 中承载 role 名称（source/compute/sink），`worker_host` 承载实际主机标识。
- `BusinessTemplateCatalog` 通过 `template_id` 关联，字段为 `source_node_name`/`compute_node_name`/`sink_node_name`。
- 前端 `formatOrderStatus` 缺少 `orphaned` 映射；`draft.parse_status` 和实例状态直接显示英文枚举值；`el-select` 过滤选项全为英文。
- **[Integration Fix]** Review finding "TaskScheduler singleton misuse" 经核查无效：`TaskScheduler` 所有方法均操作模块级 `scheduler` 对象（`services/scheduler.py:13`），`TaskScheduler()` 是无状态代理，`instances.py` 全文同样使用 `TaskScheduler()` 模式，行为一致，无需修改。
- **[E2E Test 2026-05-28]** 完整闭环验证通过：confirm-intent → routing_status=pending → routing-result 回写 → status=materialized，instance deployment_mode=scheduled，3 节点 env 含 TASK_ROLE/GPU_DEVICE/SOURCE_NAME/DESTINATION_NAME。
- **[E2E Test 2026-05-28]** 幂等性守卫正常：重复调用 routing-result 返回 409。
- **[E2E Test 2026-05-28]** 无效节点守卫正常：worker_host=nonexistent-host 返回 422，detail="Node not found: nonexistent-host"。
- **[E2E Test 2026-05-28]** routing-result 端点无需 auth token（外部路由系统直接回调），GET /api/orders/{id} 需要 token；422 测试时误用带 token 的 GET 路径导致初次误判为 404，实际直接 POST 无 token 返回 422 正确。

## Changes Made

- `backend/api/orders.py`：
  - 新增 import：`BusinessTemplateCatalog`, `NodeModel`, `DeploymentMode`, `TaskInstanceNodeOverride`, `_resolve_node_id`, `TaskScheduler`
  - `receive_routing_result` 端点：收到 placements 后查 catalog 获取 role→template_node_name 映射，构建 `node_overrides`（含 `TASK_ROLE`/`GPU_DEVICE`/`SOURCE_NAME`/`DESTINATION_NAME` env），调用 `_create_instance_from_template` 物化实例，注册 `schedule_task_start`/`schedule_task_end`，更新 `order.materialized_instance_id` 和 `order.status = MATERIALIZED`
  - **[Integration Fix]** 幂等性守卫前移：guard 移至 fetch order 之后、任何 mutation 之前，防止 autoflush 在 409 路径上持久化脏数据
  - **[Integration Fix]** `order.routing_status` 改用 `RoutingStatus.COMPLETED.value`（新增 `RoutingStatus` import）
  - **[Integration Fix]** `_resolve_node_id` 调用包裹 `try/except ValueError`，抛出 HTTPException(422) 而非 500
  - **[2026-06-02]** 新增 `BatchBenchmarkRequest` schema 和 `POST /batch-benchmark` 端点：查 catalog 获取 template_id，批量创建 `is_benchmark=True` 的 TaskOrder，携带 routing_input_dag，返回 order_ids 列表
  - **[2026-06-02]** `Field` import 补充（来自 pydantic），`build_matmul_dag` import 补充
- `backend/models/__init__.py`：
  - **[2026-06-02]** `TaskOrder` 新增 `is_benchmark: Mapped[bool]`
- `backend/database.py`：
  - **[2026-06-02]** `init_db` 新增 `_ensure_column(task_orders, is_benchmark, BOOLEAN NOT NULL DEFAULT 0)`
- `backend/schemas/task.py`：
  - **[2026-06-02]** `TaskOrderResponse` 新增 `is_benchmark: bool = False`
- `frontend/src/api/index.js`：
  - **[2026-06-02]** `ordersApi` 新增 `batchBenchmark`
- `frontend/src/views/BusinessTasksHubView.vue`：
  - **[2026-06-02]** 新增"批量压测"按钮（紧挨"运行基线测试"）、`showBatchBenchmarkDialog` 对话框（任务数量/类型/矩阵大小/批次数）、`submitBatchBenchmark` 函数
- 远程 API（`http://10.112.244.94:8181`）：
  - **[2026-06-02]** PUT `templates/b1632eae-2363-44df-8ae3-456bd2d511d9`：source/compute/sink 三节点 `port_defs` 改为 `auto=true`，range 分别为 [18800,18900]/[18900,19000]/[19000,19100]
- `backend/api/conversations.py`：
  - **[Integration Fix]** `confirm_intent` 中 `db.add(order)` + `await db.flush()` 包裹 try/except，捕获 Duplicate entry / UNIQUE constraint / IntegrityError，返回 409 而非 500
- `frontend/src/views/IntentChatView.vue`：
  - 新增 `ORDER_STATUS_LABEL`/`ROUTING_STATUS_LABEL`/`TASK_STATUS_LABEL`/`PARSE_STATUS_LABEL` 常量
  - 新增 `formatTaskStatus`/`formatParseStatus` 函数，重写 `formatOrderStatus`/`formatRoutingStatus` 使用常量
  - 修复 `el-select` 过滤选项为中文标签
  - 修复 `draft.parse_status` 显示为中文（`formatParseStatus`）
  - 修复实例状态显示为中文（`formatTaskStatus`）
  - **[Integration Fix]** `ORDER_STATUS_LABEL` 补充 `awaiting_routing: '路由中'`
  - **[Integration Fix]** `orderStatusType` 更新为实际 `OrderStatus` 枚举值：`pending`/`awaiting_routing` → `warning`，`materialized` → `primary`，`completed` → `success`，`failed` → `danger`，`cancelled`/`orphaned` → `info`
  - **[Integration Fix]** 工单详情抽屉中移除重复的截断 "ID" 描述项，保留完整 UUID 的 "工单 ID" 项

## Open Risks

- `RoutingPlacement.node_id` 字段语义依赖外部路由系统约定（必须传 role 名称）；若外部系统传 UUID 则 catalog 映射失效，会 fallback 到直接用 node_id 作为 template_node_name（可能找不到模板节点）。
- `business_start_time`/`business_end_time` 为 None 时不注册调度 job，实例将停留在 SCHEDULED 状态不自动启动。
- 业务指标采集（成功率）尚未实现。

## Next Agent Instructions

**[E2E Test 2026-05-29] 完整闭环跑通，发现两个阻塞 bug，需 Implementation Agent 修复：**

### Bug 1（阻塞）：APScheduler 调度回调中 asyncio.create_task 失败

文件：`backend/services/scheduler.py` 第 59 行、第 112 行

根因：`AsyncIOScheduler` 对 sync 函数使用 `run_in_executor`（线程池），线程中调用 `asyncio.create_task()` 抛 `RuntimeError: no running event loop`，DAG start/stop 静默丢弃，实例永远停在 `scheduled` 状态，也不会自动停止。

修复方案：将 `_run_start` / `_run_stop` 改为 async 协程，APScheduler 会用 `AsyncIOExecutor` 在事件循环中直接 `create_task`：

```python
# scheduler.py schedule_task_start 中
async def _run_start():
    from database import async_session_maker
    from services.dag_executor import DAGExecutor
    async with async_session_maker() as db:
        executor = DAGExecutor(db)
        await executor.execute_dag_start(instance_id)

scheduler.add_job(_run_start, trigger=DateTrigger(run_date=run_time), id=job_id, replace_existing=True)
```

`_run_stop` 同理。

### Bug 2（已知）：业务指标采集未实现

`GET /api/orders/{id}` 的 `evaluation` 字段为 null，`GET /api/business-tasks/results/{instance_id}` 返回 404。

实现参考 `docs/business-objective-success-rate-design.md`：
- 任务停止后采集 `compute_latency_ms` 指标
- 写入 `business_objective_evaluations` 表
- `GET /api/orders/{id}` 的 `evaluation` 字段应有值

### 验收标准（修复后重跑）

1. routing-result 回写后，实例在 `business_start_time` 自动进入 `running`
2. 实例在 `business_end_time` 自动进入 `stopped`
3. 停止后 `evaluation` 字段有 `metric_key`、`actual_value`、`target_value`、`business_success`
