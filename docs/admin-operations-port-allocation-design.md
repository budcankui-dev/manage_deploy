# 运维实例筛选与端口自动分配设计草案

本文记录主会话关于“运维实例管理筛选/多选”和“Node Agent 可用端口 API”的设计讨论。当前是设计草案，不代表已实现。

## 目标

- 管理员在实例管理页能按节点、任务/模板、状态等条件快速筛选实例。
- 前端实例表格支持多选，批量启动、停止、删除等操作更顺手。
- Node Agent 提供查找可用宿主机端口的 API，部署任务时可自动分配端口，提前降低冲突概率。
- 保留现有 preflight 端口冲突检查作为最终防线，不能因为“找过可用端口”就跳过 preflight。

## 实例管理筛选

后端 `GET /api/instances` 建议支持查询参数：

- `status`
- `template_id`
- `template_name`
- `node_id`
- `node_hostname`
- `source_order_id`
- `q`：按实例名、模板名、工单号模糊搜索
- `created_from`
- `created_to`
- `scheduled_from`
- `scheduled_to`

第一阶段优先实现：

- 按状态筛选。
- 按模板/任务筛选。
- 按节点筛选，只要实例任意节点部署在该 Node 上即可命中。
- 按实例名搜索。

查询语义：

- 多个筛选条件之间使用 AND。
- 节点筛选需要 join `task_instance_nodes`。
- 列表返回仍包含节点摘要，避免前端再逐个查详情。

## 前端多选与批量操作

现有实例页已经有 `selectedIds` 和批量启动/停止/删除能力。建议改进：

- 列表模式使用 Element Plus 原生 `<el-table-column type="selection" />`。
- 卡片模式保留现有 checkbox。
- 切换筛选条件或分页时，默认保留仍在过滤结果中的已选项，移除不可见且不再匹配的选择。
- 批量操作前弹出确认，展示选中实例数量和危险提示。
- 批量删除默认只删除 stopped/failed/pending/scheduled，running 实例需要二次确认或先停止。

第一阶段不做跨页“选择全部查询结果”，只支持当前已加载数据中的多选。后续如果后端分页变大，再考虑服务端 selection token。

## Node Agent 可用端口 API

现有 Node Agent 已有：

```text
POST /preflight/ports
```

它用于判断指定端口是否冲突。新增 API 用于找可用端口：

```text
POST /ports/available
```

请求：

```json
{
  "count": 3,
  "start": 18000,
  "end": 19999,
  "exclude": [18801, 18802],
  "network_mode": "host"
}
```

响应：

```json
{
  "ports": [18001, 18002, 18003],
  "range": {
    "start": 18000,
    "end": 19999
  },
  "warnings": []
}
```

检查规则：

- 跳过 `exclude`。
- 跳过已被当前进程监听的端口。
- 跳过 Node Agent 从 Docker 容器 label / port bindings 收集到的已声明端口。
- 返回端口数量不足时，返回 409 或 `ok=false`，并说明可用数量。

## 自动端口分配流程

模板节点的 `port_defs` 可扩展：

```json
[
  {
    "name": "SOURCE_PORT",
    "default": 18801,
    "auto": true,
    "range": [18000, 19999]
  }
]
```

部署物化时：

```text
Task Manager 读取 port_defs
 -> 对未显式指定 port_values 且 auto=true 的端口分组
 -> 按目标 Node 调用 Node Agent /ports/available
 -> 填充 instance node port_values / ports
 -> 运行现有 preflight
 -> 通过后创建/启动容器
```

如果 preflight 仍然冲突：

- 不应静默启动。
- 第一阶段可以直接失败，提示用户重试。
- 后续可做自动重试：重新申请端口，最多 2-3 次。

## 并发与一致性

“查找可用端口”不是强锁，查到可用到真正启动之间仍有竞态。因此：

- `/ports/available` 只能降低冲突概率，不能替代 `/preflight/ports`。
- 启动前必须保留 Manager 侧运行中实例检查和 Node Agent 侧宿主机检查。
- 如果需要更强保证，后续可以引入端口预约表：
  - `node_port_reservations`
  - `node_id`
  - `port`
  - `instance_id`
  - `expires_at`
  - `status`

科研验收阶段暂不建议实现预约表，先用“查可用端口 + preflight + 冲突失败可重试”即可。

## 建议拆分 Work Items

- `admin-instance-filtering-selection.md`
  - 后端实例列表增加筛选参数。
  - 前端实例页增加节点/模板筛选和原生多选表格。
  - 批量操作确认体验完善。

- `node-agent-available-port-api.md`
  - Node Agent 增加 `/ports/available`。
  - 增加端口工具函数和单测。
  - 不改变现有 preflight 行为。

- `instance-auto-port-allocation.md`
  - 模板 `port_defs` 支持 `auto` 与 `range`。
  - Task Manager 物化实例时自动填充端口。
  - 自动分配后仍跑 preflight。

## Review 重点

- 是否绕过现有端口 preflight。
- 是否在并发场景错误地把“查到可用”当成“已保留”。
- 批量删除是否可能误删 running 实例。
- 节点筛选是否漏掉多节点实例。
- 前端多选在筛选/分页后是否残留不可见选择导致误操作。
