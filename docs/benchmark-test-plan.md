# 业务目标验收测试方案

> 最后更新：2026-06-02  
> 状态：已实现，可执行

## 目标
验证系统在真实工作负载下，业务目标成功率 ≥ 90%。

## 验收指标
- 成功条件：`actual_value >= baseline_value × 0.8`（higher-is-better 指标）
- 通过标准：`成功工单数 / 已评估工单数 ≥ 90%`

## 测试范围
当前支持业务类型：高吞吐矩阵乘法（`high_throughput_matmul`）

## 访问地址
- 管理员前端：http://10.112.244.94:8182（登录：admin/admin）
- 验收测试页：http://10.112.244.94:8182/benchmark
- 后端 API：http://10.112.244.94:8181

## 前置条件
1. 三个计算节点已注册（compute-1/2/3，均为计算+终端双角色）
2. 每个参与测试的节点已完成 baseline 测试（stable=true，参数：matrix_size=1024, batch_count=50, seed=42, warmup=3）
3. matmul worker 镜像已推送到 `10.112.244.94:5000/scientific-matmul:dev`

## 测试参数
| 参数 | 值 | 说明 |
|------|-----|------|
| 任务数量 | 10 | 可调整，最多 30；3个节点并发可同时跑多个 |
| 矩阵规模 | 1024 × 1024 | 固定，与 baseline 一致 |
| 批次数 | 50 | 固定，与 baseline 一致 |
| 随机种子 | 42 | 固定 |

## 测试流程（全部在验收测试页操作）

### Step 1: 基线管理
验收测试页 → 基线管理 section：
- 查看所有节点的当前基线状态（未测试节点标红）
- 点击 [批量测试所有节点] 对所有可调度节点跑基线（约 30-60 秒/节点）
- 等待每个节点显示 stable=true

### Step 2: 批量创建测试工单
验收测试页 → 批量压测 section：
- 配置任务数（推荐 10）、矩阵大小（1024）、批次数（50）
- 点击 [创建压测工单]
- 工单带 `is_benchmark=true` 标记，与日常功能性工单区分

### Step 3: 路由与启动
验收测试页 → 路由与启动 section：
- 点击 [一键路由]：随机分配可调度节点（当前 mock 策略，后续接入真实路由模块）
- 点击 [一键启动]：所有已路由实例批量启动
- 状态格子显示：待路由 / 待启动 / 运行中 / 已完成 / 失败

### Step 4: 查看成功率
验收测试页 → 成功率统计 section：
- 实时显示成功率百分比 + 进度条
- 绿色 = ≥ 90%（验收通过）；红色 = 未达标
- 点击 [刷新] 获取最新数据

## 并发说明
matmul 模板端口已配置为动态分配（source: 18800-18900，compute: 18900-19000，sink: 19000-19100），同一节点可同时运行多个实例，支持 3 节点并发压测。

## 验收判定
`GET /api/business-tasks/summary` 返回的 `business_success_rate` 字段：
- ≥ 0.90 → 验收通过 ✓
- < 0.90 → 不通过，检查失败原因（baseline 过期、节点性能不稳定、容器启动失败等）

## 与路由系统对接说明
当前 mock 路由策略为随机选择可调度节点。对接真实路由模块时：
- 外部路由系统调用 `POST /api/orders/{order_id}/routing-result` 写入路由结果
- 路由输入 DAG 在工单创建时自动生成，路径：`task_orders.routing_input_dag`
- 字段格式：见 `docs/dag.json` 示例

## is_benchmark 字段说明
测试工单与功能性工单通过 `task_orders.is_benchmark` 字段区分：
- `is_benchmark=true`：通过批量压测创建的测试工单
- `is_benchmark=false`：用户正常使用创建的工单（不纳入成功率统计）


## 目标
验证系统在真实工作负载下，业务目标成功率 ≥ 90%。

## 验收指标
- 成功条件：`actual_value >= baseline_value × 0.8`（higher-is-better 指标）
- 通过标准：`成功工单数 / 已评估工单数 ≥ 90%`

## 测试范围
当前支持业务类型：高吞吐矩阵乘法（`high_throughput_matmul`）

## 前置条件
1. 至少 1 个计算节点已注册并可调度
2. 每个参与测试的节点已完成 baseline 测试（stable=true，参数：matrix_size=1024, batch_count=50, seed=42, warmup=3）
3. 管理系统后端正常运行

## 测试参数
| 参数 | 值 | 说明 |
|------|-----|------|
| 任务数量 | 10 | 可调整，最多 30 |
| 矩阵规模 | 1024 × 1024 | 固定，与 baseline 一致 |
| 批次数 | 50 | 固定，与 baseline 一致 |
| 随机种子 | 42 | 固定 |

## 测试流程

### Step 1: 运行节点基线（管理员界面）
进入「基线性能」面板 → 对每个计算节点点击「运行基线测试」→ 等待 stable=true

### Step 2: 批量创建测试工单
点击「批量压测」→ 配置参数 → 创建 N 个 is_benchmark=true 的工单

### Step 3: 一键路由
点击「一键路由」→ 系统自动为每个测试工单分配节点（当前为随机策略，后续接入真实路由模块）

### Step 4: 一键启动
点击「一键启动」→ 所有已路由工单的容器实例自动启动

### Step 5: 等待完成并查看结果
等待所有任务运行完成（约 2-5 分钟/任务），在「业务目标成功率」面板查看实时统计

## 验收判定
`GET /api/business-tasks/summary` 返回的 `business_success_rate` 字段：
- ≥ 0.90 → 验收通过 ✓
- < 0.90 → 不通过，检查失败原因（baseline 过期、节点性能不稳定等）

## 与路由系统对接说明
当前 mock 路由策略为随机选择可调度节点。对接真实路由模块时：
- 外部路由系统调用 `POST /api/orders/{order_id}/routing-result` 写入路由结果
- 路由输入 DAG 在工单创建时自动生成，路径：`task_orders.routing_input_dag`
- 字段格式：见 `docs/dag.json` 示例

## is_benchmark 字段说明
测试工单与功能性工单通过 `task_orders.is_benchmark` 字段区分：
- `is_benchmark=true`：通过批量压测创建的测试工单，用于成功率统计
- `is_benchmark=false`：用户正常使用创建的工单，不纳入成功率统计（可选，统计时支持按此过滤）
