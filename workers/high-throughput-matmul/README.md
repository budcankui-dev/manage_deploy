# high_throughput_matmul workers

三节点镜像（source / compute / sink），对应业务类型 `high_throughput_matmul`。

> **现状偏差（临时实现）**：当前三节点之间通过 `/scratch` 共享卷做文件 IPC，**节点间没有真实网络通信，也未声明 `ports`**，因此 preflight 端口冲突检测在 matmul 上完全不生效。这违反系统设计原则「业务节点间必须通过网络通信，每节点必须如实声明监听端口」（详 [`docs/business-task-design-summary.md`](../../docs/business-task-design-summary.md) §4.4）。
>
> 仅供单机演示使用；多机部署会因 `/scratch` 不共享而失败。完整改造计划见 [`docs/development-roadmap.md`](../../docs/development-roadmap.md) P2+。

## 构建

```bash
./scripts/build_workers.sh
# 或 WORKER_TAG=dev ./scripts/build_workers.sh
```

产出：

- `manage-deploy/matmul-source:dev`
- `manage-deploy/matmul-compute:dev`
- `manage-deploy/matmul-sink:dev`

## 数据流（临时实现，待 P2+ 重构）

1. **source** 根据 `DATA_PROFILE` 写 `/scratch/job.json`，日志含 `SOURCE_READY`
2. **compute** 执行 NumPy batched matmul，写 `/scratch/result.json`，日志含 `COMPUTE_DONE`
3. **sink** 读 result，POST `compute_latency_ms` 到 Manager，可选上传 MinIO

模板需设置 `env.PLATFORM_SCRATCH=1` 与 log 型 `health_check`（见 `backend/scripts/seed_demo_data.py`）。

> 三节点之间的 job.json / result.json 走的是同一台宿主机上的 `/scratch` bind mount，**不是网络通信**；这是 P2+ 改造前的临时演示路径。设计目标是 source/compute/sink 各自开 HTTP 监听端口，通过平台注入的 PEER URL 互相调用。

## 本地 E2E

```bash
# backend :8000 + node_agent :8001 + Docker
./scripts/e2e_matmul_live.sh
```
