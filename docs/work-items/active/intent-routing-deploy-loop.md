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
- [ ] 路由结果回写后 routing_status 变为 completed
- [ ] 物化实例时 GPU 编号正确传入容器
- [ ] 任务执行后能采集业务指标并评估成功率
