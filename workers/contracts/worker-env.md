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
| `DATA_PROFILE` | JSON 字符串，synthetic 数据画像 |
| `INPUT_OBJECTS` | JSON array，S3 URI 列表，下载并合并到 DATA_PROFILE |
| `INPUT_MANIFEST_URI` | MinIO URI（如 `s3://bucket/path/manifest.json`），包含 profile 和 objects |
| `BUSINESS_OBJECTIVE` | JSON 字符串 |
| `RUNTIME_PLAN` | JSON 字符串 |

### INPUT_OBJECTS 与 INPUT_MANIFEST_URI 优先级

当两者同时存在时，`INPUT_MANIFEST_URI` 优先。三个变量均不存在时，回退到 `DATA_PROFILE` synthetic 行为。

**INPUT_OBJECTS 示例：**

```json
["s3://task-inputs/user-123/order-456/job.json", "s3://task-inputs/user-123/order-456/profile.json"]
```

**INPUT_MANIFEST_URI 指向的 manifest.json 示例：**

```json
{
  "objects": [
    { "name": "matrix-a.npy", "uri": "s3://task-inputs/user-123/order-456/matrix-a.npy" },
    { "name": "matrix-b.npy", "uri": "s3://task-inputs/user-123/order-456/matrix-b.npy" }
  ],
  "profile": {
    "matrix_size": 1024,
    "batch_count": 1,
    "seed": 42,
    "profile_id": "matmul_prod"
  }
}
```

manifest 中的 `profile` 字段（matrix_size, batch_count, seed）覆盖 DATA_PROFILE。若 manifest 中无 `profile`，从 manifest 顶层字段读取。

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
