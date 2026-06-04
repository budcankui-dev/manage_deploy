# 智联计算系统 — 需求清单

本文档固化已确定的功能需求和约束细节，作为后续开发的 single source of truth。
状态标记：✅ 已实现 | 🔧 部分实现 | ⬜ 未实现

## 当前进度快照（2026-06-04）

- ✅ 意图解析：固定数据集、规则兜底评测、真实大模型/Batch 评测入口和前端评测页已具备；当前重点转为归档正式评测报告和截图。
- ✅ 通用计算业务目标成功率：矩阵乘法任务已在四节点真实环境完成正式轮次 `gpu-formal-20260604-01`，统计口径为 `30/30` 达标、成功率 `100.0%`。
- ✅ GPU 证据链：工单详情可展示 source/compute/sink 放置、compute GPU 编号、`cupy_gpu` 执行后端、`effective_gflops` 指标和结果元数据。
- ✅ 压测运维：业务工单中心支持按 `benchmark_run_id` 筛选，支持“清理实例保留工单”和“删除本轮工单”，清理后仍保留工单、路由和评估证据。
- 🔧 扩展业务：视频 AI 推理 worker、baseline fallback 和页面入口已具备，仍需远端正式 30 任务压测；模型训练/文本生成仍是指标契约预留。
- 🔧 外部路由联调：平台侧 DAG 输入、placements/GPU 回写和物化部署接口已具备，仍需与外部路由系统做联调验收。

---

## 1. 意图解析

### 1.1 LLM 意图解析 ✅

- 模型：项目级默认 Qwen 模型，可在意图评测页从候选模型中选择正式评测模型
- 输入：用户自然语言（中文为主）
- 输出：结构化 JSON（task_type, source_name, destination_name, duration_minutes, business_start_time, business_end_time）
- 确定性验证层：LLM 输出后经 Schema 校验 + 节点存在性校验
- 多轮追问：缺少必填字段时自动追问

### 1.2 支持的表达模式 ✅

- "从X到Y"、"源X目的Y"、"source:X dest:Y"
- "现在开始跑N小时/分钟"
- "明天9点开始运行2小时"
- 时间标准化：相对时间→绝对时间（Asia/Shanghai）

### 1.3 评测要求 ✅

- 测试集固定为 360 条（当前通过模板 + 槽位替换生成 `datasets/intent_eval/multi_business.jsonl`）
- 正式验收优先使用 DashScope Batch API 跑真实大模型/智能体评测；规则解析 3 次投票仅作为兜底回归和错误定位
- 准确率 ≥ 90% 视为达标
- 评测脚本：`scripts/evaluate_intent_parser.py`
- 生成脚本：`scripts/generate_intent_dataset.py`
- 评测数据：`datasets/intent_eval/multi_business.jsonl`

---

## 2. 路由与部署

### 2.1 DAG 结构 ✅

```
source → worker → sink
```

- source：数据源/任务发起，通常不需要 GPU
- worker：核心计算节点，最多 1 个 GPU
- sink：结果汇总、指标上报

### 2.2 外部路由系统接口 ✅

- 扫表：`GET /api/routing-requests`（routing_status=pending）
- 认领：`PATCH /api/routing-requests/{id}/claim`
- 回写：`POST /api/orders/{id}/routing-result`
- 幂等性：重复回写返回 409
- 无效节点：返回 422

### 2.3 路由结果处理 ✅

- 校验 placements 覆盖 DAG 所有逻辑节点
- 匹配 node_name → 平台 nodes 表
- 保存 GPU 编号 → 容器环境变量 `CUDA_VISIBLE_DEVICES`
- 物化 TaskInstance + 注册调度 job

### 2.4 调度器 ✅

- AsyncIOScheduler（APScheduler）
- schedule_task_start / schedule_task_end
- 回调必须是 async 协程（Bug 已修复）
- 到达 business_start_time → 自动启动容器
- 到达 business_end_time → 自动停止容器

---

## 3. 端口管理

### 3.1 网络模式 ✅

- Docker host 网络模式（network_mode=host）
- 容器共享宿主机网络栈，通过端口区分
- IPv6 数据面 + IPv4/IPv6 管理面

### 3.2 端口定义（PortDefSpec）✅

```python
name: str          # 变量名，如 api / grpc / metrics
label: str         # 用途说明
default: int       # 默认端口
auto: bool         # 是否自动分配
range: [start, end]  # 自动分配范围，如 [18000, 19999]
```

### 3.3 自动端口分配流程 ✅

1. 读取模板 port_defs
2. 对 auto=true 且未显式指定的端口 → 调用 Node Agent `/ports/available`
3. 填充 port_values
4. 运行 preflight 端口冲突检查（最终防线）
5. 冲突则失败，第一阶段不自动重试

### 3.4 前端端口展示 ✅

- 实例详情：显示 IP:port 格式（business_address + port）
- 工单详情：显示 port_access_urls 表格
- 用户工单：显示端口访问信息

---

## 4. 基线测试

### 4.1 基准测试类型 ✅

| 业务类型 | 指标 | 方向 | 容忍系数 |
|---------|------|------|---------|
| 通用计算（matmul） | effective_gflops | 越高越好 | ≥ baseline × 0.8 |
| 模型训练 | tokens_per_second | 越高越好 | ≥ baseline × 0.8 |
| 视频推理 | frame_latency_p90_ms | 越低越好 | ≤ baseline × 1.2 |

### 4.2 基准测试参数 ✅

- matmul：matrix_size=1024, batch_count=50, seed=42
- warmup：前 3 批不计入
- 基准取 3 次测量中位数

### 4.3 UI 触发基线测试 ✅

- 管理后台"基线管理"面板 → "运行基线测试"按钮
- 选择：节点 + 任务类型 + 运行次数
- API：`POST /baselines/run`（timeout 120s）
- 结果写入 node_baselines 表
- 当前 API 已接入 Node Agent 远程执行 benchmark 容器；矩阵乘法 baseline 已在四节点真实环境完成验证

### 4.4 基线数据模型 ✅

```
node_baselines:
  node_id, task_type, profile_id, accelerator,
  baseline_value, unit, raw_values, measured_at
```

---

## 5. 业务目标评估

### 5.1 单任务判定 ✅

- 任务部署成功 AND 指标采集完整 AND 实测达标
- 指标不足 → business_success=false, failure_reason=metrics_incomplete
- 评估结果存入 business_objective_evaluations 表
- 矩阵乘法任务已验证：sink 上报 `effective_gflops`，Task Manager 按 compute 节点 baseline 判定业务目标

### 5.2 成功率统计 ✅

```
业务目标成功率 = 达标工单数 / 已完成可评价工单数 × 100%
验收标准：≥ 90%（30 次中至少 27 次达标）
```

### 5.3 指标采集时机 ✅

- 业务运行过程中采集过程性指标，sink 节点汇总上报
- Sink 节点上报指标 → Task Manager 存储
- Task Manager 查询 baseline → 比较 → 写入评估结果

---

## 6. 前端功能

### 6.1 对话式工单创建 ✅

- 自然语言输入 → 意图解析 → 参数确认 → 创建工单
- 展示：意图类型、源/目的节点、时间窗口
- 状态流转：draft → awaiting_routing → materialized → completed

### 6.2 管理后台（BusinessTasksHubView）✅

- 业务任务列表（筛选、状态标签）
- 工单详情抽屉（部署 tab、结果 tab）
- 按 `benchmark_run_id` 筛选正式压测轮次，列表和统计口径一致
- 批量清理实例并保留工单证据，或删除废弃压测轮次
- 工单详情展示 GPU 分配、执行后端、业务指标和结果元数据
- 端口访问表格（IP:port 格式）

### 6.3 用户工单页（MyOrdersView）✅

- 工单列表 + 详情抽屉
- 端口访问信息展示
- 调度时间展示（scheduled_start/end）

### 6.4 实例详情（InstanceDetailView）✅

- 节点列表 + 容器状态
- 端口显示为 IP:port（business_address）
- 环境变量展示（GPU_DEVICE, TASK_ROLE 等）

---

## 7. 多节点部署运维 🔧

### 7.1 Node Agent 部署

- 实验拓扑已使用 `admin-server + compute-1/2/3` 四节点部署
- admin-server 部署前后端和私有 registry
- compute 节点部署 Node Agent，支持远端容器创建、端口检查和 GPU 分配
- 仍需沉淀为更稳定的批量部署/巡检脚本

### 7.2 Node Agent API（已实现）

- `POST /preflight/ports` — 端口冲突检查
- `POST /ports/available` — 查找可用端口
- `POST /containers/create` — 创建容器
- `POST /containers/{id}/start|stop|remove`
- `GET /health` — 健康检查

---

## 8. 验收指标

| 指标 | 标准 | 测试方法 |
|------|------|---------|
| 意图解析准确率 | ≥ 90% | 360 条固定测试集，DashScope Batch API 大模型/智能体评测 |
| 通用计算成功率 | ≥ 90% | 30 次独立任务；当前正式轮次 `gpu-formal-20260604-01` 为 `100.0%` |
| 视频推理成功率 | ≥ 90% | 30 次独立任务；待远端正式压测 |
| 模型训练成功率 | ≥ 90% | 30 次独立任务；指标契约预留 |

---

## 9. 已知约束与风险

- RoutingPlacement.node_id 语义依赖外部路由系统约定（必须传 role 名称）
- business_start/end_time 为 None 时不注册调度 job，实例停留在 scheduled
- `/ports/available` 不是强锁，查到可用到启动之间有竞态
- 第一阶段不做端口预约表，冲突则失败
- LLM 意图解析有随机性，正式评测固定数据集、模型、温度与 Batch 输入文件；规则兜底回归可多次投票辅助定位

---

## 10. 待完成事项（按优先级）

1. **P0** 归档意图解析真实大模型 Batch 评测报告、截图和数据文件
2. **P0** 将矩阵乘法正式轮次 `gpu-formal-20260604-01` 的截图/API 输出整理进正式测试方案
3. **P1** 与外部路由系统联调 DAG 输入、placements/GPU 回写和部署触发
4. **P1** 视频 AI 推理业务完成远端 30 任务正式压测
5. **P1** 多节点批量部署/巡检 node_agent 脚本化
6. **P2** Playwright/Codex Browser E2E 测试脚本化，覆盖验收页和业务工单中心
7. **P3** 端口冲突自动重试（2-3 次）
8. **P3** 资源监控面板作为演示增强项（不作为当前验收主判据）
