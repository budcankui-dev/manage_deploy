# 科学计算矩阵乘法 Worker

对应演示业务：科学计算矩阵乘法，内部 `task_type` 为 `high_throughput_matmul`。

完整演示说明见 [`docs/scientific-matmul-demo.md`](../../docs/scientific-matmul-demo.md)。

## 构建

```bash
./scripts/build_workers.sh
# 或 WORKER_TAG=dev ./scripts/build_workers.sh
```

产出单个镜像：

- `manage-deploy/scientific-matmul:dev`

## 数据流

1. **source** 根据 `DATA_PROFILE` 生成 job，通过 HTTP 发给 compute。
2. **compute** 执行 NumPy batched matmul，通过 HTTP 将 result 发给 sink。
3. **sink** 上报 `compute_latency_ms` 到 Manager，可选上传 MinIO。

模板需为每个节点声明 `port_defs`，让平台生成端口映射、健康检查和 `PEER_*` 环境变量。

## 本地 E2E

```bash
# backend :8000 + node_agent :8001 + Docker
./scripts/e2e_matmul_live.sh
```
