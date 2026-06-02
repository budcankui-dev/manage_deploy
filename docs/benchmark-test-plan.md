# 业务目标验收测试方案

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
