# Worker 容器环境变量契约

## 平台注入（`backend/services/platform_runtime.py`）

| 变量 | 说明 |
|------|------|
| `TASK_INSTANCE_ID` | 任务实例 UUID |
| `TASK_NODE_INSTANCE_ID` | 节点实例 UUID |
| `MANAGER_API_BASE` | Manager 根 URL，如 `http://127.0.0.1:8000` |
| `MINIO_ENDPOINT` | MinIO API 地址 |
| `MINIO_BUCKET` | 结果桶名 |

业务节点之间的数据必须通过网络通信传递。模板节点应声明 `port_defs`，平台会在实例物化时生成端口映射与 `PEER_*` 环境变量；MinIO 仅用于结果归档。

`PLATFORM_SCRATCH=1` 只保留为历史兼容能力，新演示和新业务不应使用它传递业务数据。

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
