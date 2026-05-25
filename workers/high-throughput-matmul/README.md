# high_throughput_matmul workers

三节点镜像（source / compute / sink），对应业务类型 `high_throughput_matmul`。

## 构建

```bash
./scripts/build_workers.sh
# 或 WORKER_TAG=dev ./scripts/build_workers.sh
```

产出：

- `manage-deploy/matmul-source:dev`
- `manage-deploy/matmul-compute:dev`
- `manage-deploy/matmul-sink:dev`

## 数据流

1. **source** 根据 `DATA_PROFILE` 写 `/scratch/job.json`，日志含 `SOURCE_READY`
2. **compute** 执行 NumPy batched matmul，写 `/scratch/result.json`，日志含 `COMPUTE_DONE`
3. **sink** 读 result，POST `compute_latency_ms` 到 Manager，可选上传 MinIO

模板需设置 `env.PLATFORM_SCRATCH=1` 与 log 型 `health_check`（见 `backend/scripts/seed_demo_data.py`）。

## 本地 E2E

```bash
# backend :8000 + node_agent :8001 + Docker
./scripts/e2e_matmul_live.sh
```
