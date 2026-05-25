# Worker 容器环境变量契约

## 平台注入（`backend/services/platform_runtime.py`）

| 变量 | 说明 |
|------|------|
| `TASK_INSTANCE_ID` | 任务实例 UUID |
| `TASK_NODE_INSTANCE_ID` | 节点实例 UUID |
| `MANAGER_API_BASE` | Manager 根 URL，如 `http://127.0.0.1:8000` |
| `MINIO_ENDPOINT` | MinIO API 地址 |
| `MINIO_BUCKET` | 结果桶名 |

模板节点 env 设 `PLATFORM_SCRATCH=1` 时，额外挂载实例级目录到容器 `/scratch`。

> **DEPRECATED / 临时偏差**：`PLATFORM_SCRATCH=1` 与 `/scratch` 共享卷机制**仅用于 `high_throughput_matmul` 单机演示**，违反设计原则「业务节点间数据必须通过网络通信，每节点必须声明 `ports` 用于 preflight 防冲突」（详 [`docs/business-task-design-summary.md`](../../docs/business-task-design-summary.md) §4.4）。
>
> 新业务**不得依赖** `/scratch` 做业务数据传递，节点间数据必须经由业务网络 PEER URL（HTTP/gRPC）传输；MinIO 仅用于结果归档。matmul 重构计划见 [`docs/development-roadmap.md`](../../docs/development-roadmap.md) P2+。

## 业务任务注入（`POST /api/business-tasks`）

| 变量 | 说明 |
|------|------|
| `BUSINESS_TASK_ID` | 外部任务 ID |
| `TASK_TYPE` | 如 `high_throughput_matmul` |
| `TASK_ROLE` | `source` / `compute` / `sink` |
| `DATA_PROFILE` | JSON 字符串 |
| `BUSINESS_OBJECTIVE` | JSON 字符串 |
| `RUNTIME_PLAN` | JSON 字符串 |

## 指标上报

```http
POST {MANAGER_API_BASE}/api/instances/{TASK_INSTANCE_ID}/metrics
Content-Type: application/json

{
  "metric_key": "compute_latency_ms",
  "metric_value": 123.4,
  "unit": "ms",
  "tags": { "objects": [{ "name": "result.json", "uri": "..." }] }
}
```
