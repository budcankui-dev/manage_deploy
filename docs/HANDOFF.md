# 开发交接文档（测试 / Code Review）

> 交接日期：2026-05-25  
> 仓库：`git@github.com:budcankui-dev/manage_deploy.git`  
> 基线提交：`b59dccb` — `feat: 业务任务中心与 matmul 实跑演示闭环`

本文档供 **Codex / Claude（或后续接手人）** 做功能测试、回归、Code Review 与 Review 跟进实现。请先读 [`AGENTS.md`](../AGENTS.md)、[`DEVELOPMENT_ACCEPTANCE.md`](../DEVELOPMENT_ACCEPTANCE.md)。

---

## 1. 项目一句话

多节点 Docker **DAG 编排**（Task Manager + Node Agent）+ **业务任务**接入（工单、业务目标评估、意图对话、外部路由回调）。当前**可演示主线**是 Admin **科学计算 matmul**（`high_throughput_matmul`）。

---

## 2. 本阶段已完成（相对旧版）

| 领域 | 内容 |
|------|------|
| Admin UI | [`BusinessTasksHubView.vue`](../frontend/src/views/BusinessTasksHubView.vue) 替代旧 Batch/BusinessTasks；默认首页 `/business-tasks` |
| 列表 API | `GET /api/business-tasks`（曾出现 405：需 **reload 后端** 加载新路由） |
| 聚合统计 | **按现存工单**计数；成功率 = 达标数 / **已评估数**（未评估不计入分母） |
| 详情展示 | matmul **结果 Tab 四块**（做什么 / 输入 / 输出 / 耗时验收）；不展示 checksum；列表列「耗时达标」 |
| 结果 metadata | sink `tags.result` 全量上报 → `_extract_result_metadata` 白名单落库；业务成功仍为耗时 ≤ 目标 |
| 一键演示 | `auto_start` + 轮询 evaluation + 打开「结果」Tab |
| 删工单 | 级联删除 `BusinessObjectiveEvaluation` / `TaskResultObject`（[`order_sync.py`](../backend/services/order_sync.py)） |
| Worker | `workers/high-throughput-matmul/` 三镜像 + `scripts/e2e_matmul_live.sh`（**当前为 `/scratch` 文件 IPC，节点间无网络通信、未声明 `ports`，与设计原则不符，详 §7 P0 / roadmap P2+**） |
| 意图串联 | Admin 在 IntentChat 提交后跳转 `?orderId=` 打开中心详情 |
| 生命周期 | SCHEDULED 强制 `scheduled_end_time`（默认 start+2h，可配置）；到期自动 stop → 默认删除实例 + 工单标 `COMPLETED`；新增 `keep_after_stop` 开关、`restore_pending_jobs` 启动重注册。详 §6.3、roadmap P3+ |
| 测试 | 后端 62 passed（含 8 项 lifecycle 单测）；`npm run test:display`；E2E matmul 脚本 |

**刻意不做 / 未验收：**

- `low_latency_video_pipeline` 本地镜像未齐，**不要**用旧视频示例做工演示
- MinIO 结果文件 **内联预览**（结果 Tab 展示输入/输出/耗时验收；原始 JSON 可折叠）
- P5 路由状态 SSE/轮询（IntentChat 侧仅有 pending 轮询）
- P6 真实 LLM 意图解析
- 普通 user 角色跳转业务中心（路由守卫会拦 Admin 页）

---

## 3. 架构与数据流（matmul 演示）

```text
UI 一键演示 / e2e_matmul_live.sh
    → POST /api/business-tasks
    → TaskOrder + TaskInstance (pending)
    → POST /api/instances/{id}/start  (DAG)
    → Node Agent 起 source → compute → sink 容器
    → sink 上报 POST /api/instances/{id}/metrics
    → evaluate_and_store_business_metric → BusinessObjectiveEvaluation
    → GET /api/business-tasks/summary | GET /api/orders/{id}
```

> **节点间数据流偏差**：source→compute→sink 之间 job.json / result.json 走的是同一台 Worker 上 `/scratch` 共享卷（[`apply_scratch_bind_mount`](../backend/services/platform_runtime.py)），**不是网络通信**，模板也未声明 `ports` → preflight 在 matmul 上完全不生效。设计目标是节点间走业务网络 PEER URL + 显式 ports（详 [`docs/business-task-design-summary.md`](business-task-design-summary.md) §4.4），改造计划见 §7 P0 与 [`docs/development-roadmap.md`](development-roadmap.md) P2+。

关键文件：

| 层级 | 路径 |
|------|------|
| 列表/聚合查询 | [`backend/services/business_task_query.py`](../backend/services/business_task_query.py) |
| 业务任务 API | [`backend/api/business_tasks.py`](../backend/api/business_tasks.py) |
| 工单详情 | [`backend/api/orders.py`](../backend/api/orders.py) |
| 前端展示常量 | [`frontend/src/constants/businessTaskDisplay.js`](../frontend/src/constants/businessTaskDisplay.js) |
| 中心页面 | [`frontend/src/views/BusinessTasksHubView.vue`](../frontend/src/views/BusinessTasksHubView.vue) |

---

## 4. 环境启动（测试前必做）

### 4.1 进程

```bash
# 终端 1 — Task Manager
cd backend && source venv/bin/activate && uvicorn main:app --reload --host 127.0.0.1 --port 8000

# 终端 2 — Node Agent（本机 Docker）
cd node_agent && source venv/bin/activate && uvicorn main:app --reload --host 127.0.0.1 --port 8001

# 终端 3 — 前端
cd frontend && npm install && npm run dev
```

macOS Docker Desktop：Worker 回调 Manager 需 `MANAGER_PUBLIC_URL=http://host.docker.internal:8000`（见 [`backend/.env.example`](../backend/.env.example)）。

### 4.2 Seed 与镜像

```bash
./scripts/build_workers.sh   # 首次或 Worker 代码变更后
SEED_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/seed_demo_data.py
```

默认账号：`admin/admin`（Admin）、`user/user`（普通用户）。

### 4.3 清理演示数据（可选）

```bash
./scripts/cleanup_stale_business_orders.sh
```

---

## 5. 推荐测试清单（给 Claude）

### 5.1 自动化（必须通过）

```bash
cd backend && source venv/bin/activate && PYTHONPATH=. pytest tests/ -q
cd frontend && npm run test:display
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
```

期望：`pytest` ≥40 passed；E2E 末尾 `OK matmul live e2e passed`；summary 中 `high_throughput_matmul` 的 `business_success_rate` 合理。

### 5.2 API 冒烟

```bash
curl -s http://127.0.0.1:8000/api/business-tasks/summary | jq .
curl -s 'http://127.0.0.1:8000/api/business-tasks?page=1' | jq '.total, .items[0].task_type'
# GET /api/business-tasks 若 405 → 后端未 reload，重启 uvicorn
```

### 5.3 UI 手工（Admin）

1. 登录 `admin/admin` → 进入 **业务任务中心**
2. 点击 **一键演示矩阵乘法** → 等待提示成功 → 详情 **结果** Tab：
   - **本任务在做什么**（source → compute → sink）
   - **输入**（matrix_size、batch_count、seed 等）
   - **输出**（规模、batch、compute_latency_ms）
   - **耗时验收**（实际 vs 目标，达标/未达标；不验矩阵数值）
   - 新跑任务需重建 worker 后 sink 才带完整 `tags.result`；旧评估可能缺 `result_metadata`
3. 聚合表：**工单数**、**已评估**、成功率 `x/y` 与列表一致
4. 删除一条工单 → summary 数量减少；`GET .../evaluation` 对该 instance 为 404
5. （可选）`/intent-chat`：走完 确认意图 → 请求路由 → mock 回调 → 提交（Admin）→ 应跳转中心并带 `orderId`

### 5.4 回归注意点

- 批量删除/停止实例：前端超时已加长（180s），见 DEVELOPMENT_ACCEPTANCE §2.9
- DAG 失败回滚：容器可能残留，见 §2.7、`scripts/verify_rollback_cleanup.sh`
- 列表与 summary **不一致**：查是否有已删工单遗留 evaluation（删工单级联应已修复）

---

## 6. Code Review 关注点

### 6.1 历史项（基线 `b59dccb` 及之前）

| 优先级 | 项 | 说明 |
|--------|-----|------|
| P0 | `list_business_tasks` 全表扫描 + 内存过滤 | 工单量大时需改为 SQL 过滤/分页 |
| P0 | `business_tasks` 路由顺序 | `/summary` 须在 `/{instance_id}` 之前（当前 OK） |
| P1 | 删工单是否应同时删 `TaskInstance` | 当前只删 order + evaluation/result_objects，实例可能仍在 |
| P1 | `batch_delete_orders` 参数名 `instance_ids` 实际传的是 order_id | 历史命名，易误解 |
| P2 | `object_uris` JSON 混存 `uris` + `result_metadata` | 与纯 URI 列表的 schema 文档对齐 |
| P2 | IntentChat 非 Admin 提交后无法进中心 | 产品预期还是待补链接/权限 |

建议 Review 顺序：`business_task_query.py` → `business_tasks.py` / `orders.py` → `BusinessTasksHubView.vue` → `sink_main.py` / `reporter.py`。

### 6.2 matmul 结果 Tab 改动 Review（2026-05-25，**本地未提交**）

**审查范围（6 个文件）：**

| 文件 | 变更要点 |
|------|----------|
| [`workers/high-throughput-matmul/src/sink_main.py`](../workers/high-throughput-matmul/src/sink_main.py) | `tags` 改为 `"result": result`（整份 result.json），不再扁平传 checksum |
| [`backend/api/business_tasks.py`](../backend/api/business_tasks.py) | `_extract_result_metadata`：优先 `tags.result`，白名单 `compute_latency_ms/matrix_size/batch_count/seed`；兼容旧扁平 tags |
| [`frontend/src/constants/businessTaskDisplay.js`](../frontend/src/constants/businessTaskDisplay.js) | `MATMUL_PIPELINE_STEPS`、`buildMatmulInput/Output/Consistency/Verdict`；移除 checksum 展示 |
| [`frontend/src/views/BusinessTasksHubView.vue`](../frontend/src/views/BusinessTasksHubView.vue) | 结果 Tab 四块布局；URI 表折叠；列表「耗时达标」 |
| [`frontend/scripts/test-businessTaskDisplay.mjs`](../frontend/scripts/test-businessTaskDisplay.mjs) | 断言改为 matmul 分块 helper |
| [`README.md`](../README.md) | 演示说明补充结果 Tab |

**结论：Approve with minor changes** — 与产品意图一致（仅耗时验收，不验数值正确性）；分层清晰；向后兼容旧 sink 扁平 tags。

**做得好的地方：**

- evaluation 侧 `result_metadata` 白名单落库，不把 checksum 带入 UI 路径。
- matmul 未评估时仍展示流水线 + 输入 + pending 验收，空态优于旧 `detailComputeSummary.length` 判断。
- `npm run test:display` + `pytest tests/test_business_tasks*.py` 已通过（审查时）。

**数据流（审查用）：**

```text
source(job.json) → compute(result.json) → sink(report_metric)
  tags.result（全量，含 checksum）→ TaskMetric.tags（全量 JSON）
  → _extract_result_metadata（白名单）→ evaluation.result_metadata
  → BusinessTasksHubView 四块展示
```

**P1 — 建议 Codex 合并前处理：**

| 项 | 说明 | 建议改法 |
|----|------|----------|
| UI 文案不一致 | 列表列已是「耗时达标 / 达标 / 超标」，筛选仍为 placeholder「业务结果」、选项「成功 / 失败」 | [`BusinessTasksHubView.vue`](../frontend/src/views/BusinessTasksHubView.vue) 筛选与列表对齐 |
| `TaskMetric.tags` 仍存 checksum | `evaluation.result_metadata` 已过滤，但 metrics 表仍写入完整 `tags.result`（含 checksum） | sink 只上报白名单子集，或 reporter 裁剪后再 POST |
| 无 `_extract_result_metadata` 单测 | 仅靠间接 API 测试，回归脆弱 | 在 `backend/tests/test_business_tasks.py` 增加 parametrized：`tags.result` / 旧扁平 tags / 空 tags |

**P2 — 可后续小 PR：**

| 项 | 说明 |
|----|------|
| 死代码 | `buildComputeResultSummary` 已无引用，仅 `@deprecated`，可删 |
| 输出重复 | `buildMatmulOutputRows` 同时展示「result.json 耗时」与「上报指标」，正常应相等；可合并或加 hint |
| `seed` 白名单无效 | `compute_main` 的 result.json 不含 seed，`result_metadata.seed` 几乎永远为空 |
| 文档漂移 | [`docs/development-roadmap.md`](development-roadmap.md) 仍写「checksum 入库」，需改一句与现实现一致 |

**P3 — 运维约束（非缺陷）：**

- 新 UI 依赖新 sink 的 `tags.result` → Worker 变更后须 `./scripts/build_workers.sh` 再跑任务。
- 旧评估无 `result_metadata` 时：一致性条隐藏，输出区仅「上报指标」。

### 6.3 调度模式生命周期自动收尾（2026-05-25，**本地未提交**）

**审查范围（新增/修改）：**

| 文件 | 变更要点 |
|------|----------|
| [`backend/enums.py`](../backend/enums.py) | `OrderStatus` 新增 `COMPLETED`（区别 `CANCELLED`） |
| [`backend/config.py`](../backend/config.py) | 新增 `default_scheduled_duration_hours: int = 2` |
| [`backend/models/__init__.py`](../backend/models/__init__.py) | `TaskInstance` / `TaskOrder` 新增 `keep_after_stop`（默认 False） |
| [`backend/schemas/task.py`](../backend/schemas/task.py) | `TaskInstanceCreate` / `TaskOrderCreate` 加 `model_validator`：SCHEDULED 缺 `scheduled_end_time` 自动填 start+`default_scheduled_duration_hours` 小时；`TaskInstanceSchedule`/`Update`/`Response`/`Simple` / `BusinessTaskListItem` 透传 `keep_after_stop` 与 scheduled 时间 |
| [`backend/database.py`](../backend/database.py) | `init_db` 给两张表加 `keep_after_stop BOOLEAN NOT NULL DEFAULT 0` |
| [`backend/services/instance_lifecycle.py`](../backend/services/instance_lifecycle.py) | 新文件：`auto_cleanup_instance`（容器清理 + `purge_order_instance_artifacts` 物理删除实例；失败写 TaskEvent + 日志，不阻塞调度器） |
| [`backend/services/order_sync.py`](../backend/services/order_sync.py) | 新增 `mark_orders_completed_for_instance`（仅作用于 MATERIALIZED 工单） |
| [`backend/services/scheduler.py`](../backend/services/scheduler.py) | `_run_stop` 流程：`execute_dag_stop → mark_orders_completed → if not keep_after_stop: auto_cleanup`；新增 `restore_pending_jobs(session_maker=None)`，启动时扫描未到期 start/end 重注册 |
| [`backend/main.py`](../backend/main.py) | lifespan 启动后调 `restore_pending_jobs()` |
| [`backend/api/business_tasks.py`](../backend/api/business_tasks.py) | `build_instance_create_from_business_task` 强制 `deployment_mode=SCHEDULED` + `scheduled_start_time=now` + `scheduled_end_time = payload 或 now+default`；`TaskOrder` 同步写入字段 |
| [`backend/api/conversations.py`](../backend/api/conversations.py) | `/submit` 支持透传 `scheduled_end_time` / `keep_after_stop` 查询参数 |
| [`backend/api/instances.py`](../backend/api/instances.py) | `_create_instance_from_template` 透传 `keep_after_stop`；SCHEDULED 通路在 `schedule_task_start` 前 `await db.commit()` 防止竞态；`update_instance` / `schedule_instance` 支持更新 `keep_after_stop` |
| [`backend/services/business_task_query.py`](../backend/services/business_task_query.py) | `BusinessTaskListItem` 新增 `scheduled_start_time / scheduled_end_time / keep_after_stop` 字段填充 |
| [`backend/tests/test_lifecycle_auto_cleanup.py`](../backend/tests/test_lifecycle_auto_cleanup.py) | 新增 8 项单测（schema validator、`mark_orders_completed`、`auto_cleanup_instance`、`restore_pending_jobs`、业务任务默认 SCHEDULED + end_time、IMMEDIATE 不被自动填充） |
| [`backend/tests/test_business_tasks.py`](../backend/tests/test_business_tasks.py) / `test_business_tasks_api.py` | 适配业务任务 IMMEDIATE → SCHEDULED 行为变更 |
| [`frontend/src/utils/deployJson.js`](../frontend/src/utils/deployJson.js) | JSON 粘贴导入支持 `keep_after_stop` |
| [`frontend/src/views/InstancesView.vue`](../frontend/src/views/InstancesView.vue) | IMMEDIATE / SCHEDULED 模式副标题文案；SCHEDULED 时 `scheduled_end_time` required；新增 `keep_after_stop` 开关；列表加「计划停止 + 倒计时」列 |
| [`frontend/src/views/InstanceDetailView.vue`](../frontend/src/views/InstanceDetailView.vue) | 调度区块显示 `keep_after_stop` 与到期倒计时；schedule 表单允许修改 `keep_after_stop` |
| [`frontend/src/views/BusinessTasksHubView.vue`](../frontend/src/views/BusinessTasksHubView.vue) | 部署 Tab 展示 `scheduled_start_time/scheduled_end_time/keep_after_stop/工单状态`；倒计时；一键演示固定 `keep_after_stop=false` |
| [`frontend/src/api/index.js`](../frontend/src/api/index.js) | `conversationApi.submit` 透传 `scheduled_end_time / keep_after_stop` |
| [`frontend/src/constants/routingPolicy.js`](../frontend/src/constants/routingPolicy.js) | `ORDER_STATUS_LABELS` 增 `completed: '已完成'` |

**设计要点：**

- **IMMEDIATE 仅供管理员/开发/测试**：保留手动 stop/delete；不强制 end_time；不参与自动收尾。
- **SCHEDULED 是默认业务通路**（业务任务 / 意图提交）：必有 `scheduled_end_time`；到点自动 stop；`keep_after_stop=false`（默认）触发 `auto_cleanup_instance`。
- `OrderStatus.COMPLETED`：自然到期完成（区别于人工 `CANCELLED`）；前端 `ORDER_STATUS_LABELS` 已识别。
- `restore_pending_jobs`：APScheduler 内存调度，backend 重启会丢 jobs；启动时扫描未到期实例重注册 start/end。

**验收（plan §"验收"）：**

- ✅ SCHEDULED 不填 end_time → schema 自动填 start + 2h（由 `test_task_instance_create_scheduled_*` 覆盖）
- ✅ `mark_orders_completed_for_instance` 仅作用于 MATERIALIZED；幂等
- ✅ `auto_cleanup_instance` 删 instance；工单 COMPLETED 保留
- ✅ `restore_pending_jobs` 重注册未到期 end job
- ✅ POST `/api/business-tasks` 不传 end_time 默认 +2h；deployment_status=`scheduled`
- ✅ IMMEDIATE 行为不变（不被自动填充 end_time / start_time）
- 🕒 `e2e_matmul_live.sh`：因业务任务强制 SCHEDULED，需要随 P0 matmul 网络改造一起更新（end_time = now+短窗口、断言到期清理）；本次未跑。
- 🕒 真实"到点自动删除"行为：依赖 APScheduler 启动 + 跑通容器；单机环境推荐 `scheduled_end_time = now + 60s` 手动验证。

**待跟进（plan §"风险与缓解"）：**

- APScheduler 默认 timezone = `Asia/Shanghai`，但 `scheduled_*_time` 用 `datetime.utcnow()`（naive）写入；scheduler 视为 Asia/Shanghai 时间，与 UTC 服务器有 8 小时偏差 → 业务任务"立即启动"实际会延迟 8h。需要后续 PR 改为 timezone-aware（或统一 scheduler timezone=UTC）。
- 历史 SCHEDULED 实例若缺 `scheduled_end_time` 不会回填，仅对新建强制。
- `e2e_matmul_live.sh` 仍按旧 IMMEDIATE+auto_start 心智写；改造方案见 plan §"测试"。

**测试缺口（Codex 合并前建议补跑）：**

```bash
cd backend && source venv/bin/activate && PYTHONPATH=. pytest tests/test_business_tasks.py tests/test_business_tasks_api.py -q
cd frontend && npm run test:display
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh   # 重建镜像后去掉 SKIP 再验一遍
```

---

## 7. Codex 待办（来自 §6.2 / §6.3 Review）

按优先级勾选处理，完成后在本节或 PR 描述中注明。

### P0 调度模式生命周期收尾（已实现 → 仍需 e2e 验证 + timezone fix）

- [x] 后端单测 8 项 + 既有业务任务测试同步调整（`backend/tests/test_lifecycle_auto_cleanup.py`、`test_business_tasks*.py`）
- [x] schema + `init_db` 加 `keep_after_stop`；`OrderStatus.COMPLETED`
- [x] `auto_cleanup_instance` + `mark_orders_completed_for_instance` + `restore_pending_jobs`
- [x] 业务任务 / 意图提交强制 SCHEDULED + end_time；IMMEDIATE 仍走旧通路
- [x] 前端 `InstancesView` / `InstanceDetailView` / `BusinessTasksHubView` 文案 + 倒计时 + `keep_after_stop`
- [ ] `scripts/e2e_matmul_live.sh` 适配 SCHEDULED：缩短 end_time（60s 内）、断言到期清理（与 P0 matmul 网络改造一并做）
- [ ] APScheduler timezone 偏差修复：`scheduled_*_time` 改 timezone-aware，或 scheduler timezone 统一 UTC（影响"立即启动"语义）

### P0 matmul 节点间通信改造（违反设计原则，必须处理）

**目标**：把 matmul source/compute/sink 三节点从 `/scratch` 文件 IPC 改为**网络通信**，并让每节点**如实声明 `ports`**，使 preflight 端口冲突检测在 matmul 上生效。详细计划见 [`docs/development-roadmap.md`](development-roadmap.md) P2+。

**子任务摘要**（细节以 roadmap P2+ 为准）：

- [ ] source / compute / sink 各开 HTTP listen，分配端口（如 8801/8802/8803）
- [ ] [`backend/scripts/seed_demo_data.py`](../backend/scripts/seed_demo_data.py) matmul 模板节点声明 `ports` 与 `port_defs`
- [ ] compute 通过 `PEER_SOURCE_URL_*` 拉 job；sink 通过 `PEER_COMPUTE_URL_*` 拉 result
- [ ] 健康检查由 log 型改 `port` 型
- [ ] 移除 [`apply_scratch_bind_mount`](../backend/services/platform_runtime.py) 业务路径注入；偏差化文档（worker-env.md、matmul README、DEVELOPMENT_ACCEPTANCE §2.6/§2.8/§9.2、本节）同步清理 deprecated 标记
- [ ] 验证：preflight 报端口、同机重复部署能检出冲突、`scripts/e2e_matmul_live.sh` 通过、`pytest tests/` 全绿

**风险与影响**：

- 现有 `scripts/e2e_matmul_live.sh` 行为需同步更新（健康检查、PEER URL 注入断言）
- 必须 `./scripts/build_workers.sh` 重建 worker 镜像
- 历史 `/scratch` 实例数据迁移：建议直接清理旧工单（`scripts/cleanup_stale_business_orders.sh`），无须保留旧实现

### P1（合并 matmul UI 改动前）

- [ ] 统一筛选文案：「业务结果 / 成功 / 失败」→「耗时达标 / 达标 / 超标」（`BusinessTasksHubView.vue`）
- [ ] 避免 checksum 进入 `task_metrics.tags`：sink 白名单子集或 reporter 裁剪（`sink_main.py` / `workers/_common/reporter.py`）
- [ ] 新增 `_extract_result_metadata` 单元测试（`backend/tests/test_business_tasks.py`）
- [ ] 提交本地 6 文件 + 本 HANDOFF 更新（勿含 `.env`、`.cursor/`、`.playwright-mcp/`）

### P2（可单独 PR）

- [ ] 删除未使用的 `buildComputeResultSummary`（`businessTaskDisplay.js`）
- [ ] 合并或标注 matmul 输出区双耗时行（`buildMatmulOutputRows`）
- [ ] 更新 `development-roadmap.md` 中 checksum 相关表述

### 验证

- [ ] `pytest tests/ -q`
- [ ] `npm run test:display`
- [ ] `e2e_matmul_live.sh` + Admin 手工打开结果 Tab（§5.3 第 2 条）

---

## 8. 已知问题 / 技术债

1. **matmul 节点间是文件 IPC（违反设计原则）**：三节点走 `/scratch` 共享卷，未声明 `ports`，preflight 不生效，仅能单机演示；改造见 §7 P0 / roadmap P2+。
2. **视频 pipeline 示例**：历史工单可能部署失败；演示请只用 matmul。
3. **README** 中「后台 UI 重组待做」与 `planned-admin-ui-restructure.md` 状态略旧（中心已落地，可改文案）。
4. **MySQL 连接串** 在 README 含示例密码，Review 时勿提交真实 `.env`。
5. **评估指标**：仅支持 `operator: <=`（[`business_evaluator.py`](../backend/services/business_evaluator.py)）。
6. **业务任务"立即启动"被 APScheduler timezone 偏差延迟**：业务任务现在强制 SCHEDULED 模式，`scheduled_start_time = utcnow()` (naive) 被 scheduler timezone `Asia/Shanghai` 解读为本地时间，实际触发时间会晚 8 小时。需要后续 PR 修复（详 §6.3）。

---

## 9. 文档索引

| 文档 | 用途 |
|------|------|
| [`DEVELOPMENT_ACCEPTANCE.md`](../DEVELOPMENT_ACCEPTANCE.md) | 踩坑、§11 E2E 勾选 |
| [`docs/development-roadmap.md`](development-roadmap.md) | P2/P3/P4/P5 进度 |
| [`docs/business-task-design-summary.md`](business-task-design-summary.md) | 业务 JSON 契约 |
| [`workers/high-throughput-matmul/README.md`](../workers/high-throughput-matmul/README.md) | Worker 行为 |
| [`docs/planned-admin-ui-restructure.md`](planned-admin-ui-restructure.md) | Admin 信息架构 |

---

## 10. 给 Codex / Claude 的 Prompt 模板

```text
你是接手 manage_deploy 的开发助手。先读 docs/HANDOFF.md。

若处理 matmul 节点间通信改造（强约束补齐）：按第 7 节 **P0**，对照 [`docs/development-roadmap.md`](development-roadmap.md) P2+ 子任务与验收清单；改造完成后清理偏差文档（worker-env.md、matmul README、DEVELOPMENT_ACCEPTANCE §2.6/§2.8/§9.2、§7 P0、§8 已知问题）。
若处理 matmul 结果 Tab 后续：按第 7 节「Codex 待办」勾选 P1（文案、tags 裁剪、单测、提交），再跑第 7 节验证清单。
若做测试/Review：按第 5 节自动化 + 5.3 UI；对照第 6.1（历史 P0/P1）与第 6.2（matmul Review 结论）。
不要修改计划文件；提交前确认未包含 .env、.cursor/、.playwright-mcp/。
```

---

## 11. 交接人备注

- 远程基线：`origin/main` @ `b59dccb`（2026-05-25 已推送）。
- **本地另有未提交改动**：matmul 结果 Tab 四块 + `tags.result` metadata（见 §6.2、§7）。
- 基线验证：pytest 43 passed、`e2e_matmul_live.sh` 通过、summary 与 UI 一致。
- 下一迭代：§7 P1 收尾 → §7 P2；另见 MinIO 预览、Intent mock 路由、列表 SQL 分页（§8）。
