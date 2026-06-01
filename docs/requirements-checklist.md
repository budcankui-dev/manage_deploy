# 智联计算系统 — 需求清单

本文档固化已确定的功能需求和约束细节，作为后续开发的 single source of truth。
状态标记：✅ 已实现 | 🔧 部分实现 | ⬜ 未实现

---

## 1. 意图解析

### 1.1 LLM 意图解析 ✅

- 模型：qwen3-max（通义千问）
- 输入：用户自然语言（中文为主）
- 输出：结构化 JSON（task_type, source_name, destination_name, duration_minutes, business_start_time, business_end_time）
- 确定性验证层：LLM 输出后经 Schema 校验 + 节点存在性校验
- 多轮追问：缺少必填字段时自动追问

### 1.2 支持的表达模式 ✅

- "从X到Y"、"源X目的Y"、"source:X dest:Y"
- "现在开始跑N小时/分钟"
- "明天9点开始运行2小时"
- 时间标准化：相对时间→绝对时间（Asia/Shanghai）

### 1.3 评测要求 🔧

- 测试集 ≥200 条（当前 5 条，需扩充）
- 每条评测 3 次取多数投票
- 准确率 ≥ 90% 视为达标
- 评测脚本：`scripts/evaluate_intent_parser.py`
- 评测数据：`datasets/intent_eval/matmul.jsonl`

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

### 4.4 基线数据模型 ✅

```
node_baselines:
  node_id, task_type, profile_id, accelerator,
  baseline_value, unit, raw_values, measured_at
```

---

## 5. 业务目标评估

### 5.1 单任务判定 🔧

- 任务部署成功 AND 指标采集完整 AND 实测达标
- 指标不足 → business_success=false, failure_reason=metrics_incomplete
- 评估结果存入 business_objective_evaluations 表

### 5.2 成功率统计 ⬜

```
业务目标成功率 = 达标工单数 / 已完成可评价工单数 × 100%
验收标准：≥ 90%（30 次中至少 27 次达标）
```

### 5.3 指标采集时机 ⬜

- 任务停止后（business_end_time 到达）
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
- 基线管理面板（列表 + 运行测试）
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

## 7. 多节点部署运维 ⬜

### 7.1 Node Agent 部署

- 批量 SSH 部署 node_agent 到多台机器
- 统一镜像分发（registry 或 SSH push）
- 节点健康检查 + 自动注册
- 节点上下线管理

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
| 意图解析准确率 | ≥ 90% | 200 条测试集，每条 3 次投票 |
| 通用计算成功率 | ≥ 90% | 30 次独立任务 |
| 视频推理成功率 | ≥ 90% | 30 次独立任务 |
| 模型训练成功率 | ≥ 90% | 30 次独立任务 |

---

## 9. 已知约束与风险

- RoutingPlacement.node_id 语义依赖外部路由系统约定（必须传 role 名称）
- business_start/end_time 为 None 时不注册调度 job，实例停留在 scheduled
- `/ports/available` 不是强锁，查到可用到启动之间有竞态
- 第一阶段不做端口预约表，冲突则失败
- LLM 意图解析有随机性，需多次投票消除

---

## 10. 待完成事项（按优先级）

1. **P0** 业务指标采集闭环（sink 上报 → 评估 → 写入 evaluation）
2. **P0** 意图解析测试集扩充至 200 条
3. **P1** 多节点批量部署 node_agent
4. **P1** 统一镜像分发
5. **P2** Playwright E2E 浏览器测试
6. **P2** 业务目标成功率统计 API + 前端展示
7. **P3** 端口冲突自动重试（2-3 次）
8. **P3** 到期自动 stop/删除实例 E2E 验收
