# 后台管理功能重组

> 2026-05-24 完成一次性切换：业务任务中心为 Admin 默认首页。

## 当前信息架构（Admin）

| 菜单 | 路由 | 说明 |
|------|------|------|
| 业务任务中心 | `/business-tasks` | 列表 + 聚合 + 详情四 Tab |
| 工作节点 | `/nodes` | 节点注册与管理 |
| 任务模板 | `/templates` | DAG 拓扑模板 |
| 运维 / 手动部署 | `/dev/instances` | 从模板手动建实例（调试） |

旧路由重定向：`/instances` → `/dev/instances`，`/batch` → `/business-tasks`。

## 业务任务中心

- **列表 API**：`GET /api/business-tasks`（分页、筛选 task_type / routing_policy / deployment_status / business_success）
- **详情 API**：`GET /api/orders/{id}`（含 business_task、routing_result、instance、evaluation）
- **统计**：`GET /api/business-tasks/summary`
- **详情 Tab**：业务 / 路由 / 部署 / 结果

## 命名约定

- API 响应：`routing_policy`（值仍为英文枚举，如 `completion_time_first`）
- 请求体：`routing_result.strategy` 保留，`routing_policy` 为别名
- UI：`frontend/src/constants/routingPolicy.js` 中文映射

## 模型关系

```text
BusinessTask → TaskOrder → TaskInstance → BusinessObjectiveEvaluation
```

删除 `TaskInstance` 时同步将关联 `TaskOrder` 置为 `cancelled`；列表 API 默认隐藏 `cancelled`（`include_cancelled=true` 可显示）。
