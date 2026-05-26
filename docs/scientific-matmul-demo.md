# 科学计算矩阵乘法演示

本项目当前维护的演示业务是 **科学计算矩阵乘法**，内部 `task_type` 为 `high_throughput_matmul`。它用一个 source -> compute -> sink 的三节点 DAG 展示业务任务从创建、路由放置、容器编排、指标上报到业务目标评估的完整闭环。

这个演示的产品重点不是证明容器必须按某个业务顺序启动，而是证明外部路由算法选择的路径会承载真实业务数据。source、compute、sink 的放置来自 routing placements，矩阵 job/result 沿这些节点之间的 HTTP `PEER_*` 地址流转，这就是当前测试业务的随路计算原则。

## 运行入口

```bash
# 构建单个 worker 镜像
./scripts/build_workers.sh

# 准备演示节点、模板和业务目录项。脚本通过 DATABASE_URL（或 MYSQL_HOST /
# MYSQL_USER / MYSQL_PASSWORD / MYSQL_PORT / MYSQL_DATABASE 环境变量）读取
# MySQL 凭据；并要求 nodes 表里已有 compute-1/2/3 三行。
DEMO_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/rebuild_matmul_template.py

# 需 backend :8000 + node_agent :8001 + Docker
./scripts/e2e_matmul_live.sh
```

真实 4 节点测试时，先构建并推送 `linux/amd64` 镜像到 admin-server 私有仓库，再让业务节点拉取运行。`WORKER_SKIP_BUILD=1` 只适合已经验证镜像 tag、registry、架构均正确的复测场景。

前端入口：Admin -> 业务任务中心 -> 一键演示矩阵乘法。

## 镜像与模板

演示只构建一个镜像：

```text
manage-deploy/scientific-matmul:dev
```

模板中的三个节点使用同一个镜像，通过不同 `command` 启动不同角色：

| 角色 | command | 默认端口 |
|------|---------|----------|
| source | `python /app/src/source_main.py` | `18801` |
| compute | `python /app/src/compute_main.py` | `18802` |
| sink | `python /app/src/sink_main.py` | `18803` |

端口定义写在每个模板节点的 `port_defs` 中。实例物化时，平台会解析出 `ports` / `port_values`，用于端口预检、健康检查和 `PEER_*` 环境变量注入。

## 数据流

### 数据来源优先级

第一优先级：**MinIO / 对象存储**（生产路径）

- source 通过 `INPUT_MANIFEST_URI` 或 `INPUT_OBJECTS` 从 MinIO 拉取用户上传的输入对象。
- `INPUT_MANIFEST_URI` 指向 manifest.json，包含 profile 和 object URI 列表。
- `INPUT_OBJECTS` 是 S3 URI 数组，直接列出要下载的 JSON 文件，合并到 DATA_PROFILE。
- 凭据通过 `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY` 环境变量注入，不写入镜像。

第二优先级：**synthetic 合成数据**（演示 / 验收路径）

- 当没有 INPUT_* 变量时，source 根据 `DATA_PROFILE` 环境变量生成矩阵规模、批次数和随机种子。
- 适合本地 E2E 测试和验收演示，不依赖外部对象存储。

### 节点间数据传递

1. source 根据数据来源生成 job（矩阵规模、批次数、seed）。
2. source 通过 HTTP POST 将 job 发送到 compute 节点。
3. compute 执行 NumPy batched FP32 矩阵乘法。
4. compute 通过 HTTP POST 将结果发送到 sink 节点。
5. sink 上报 `compute_latency_ms` 指标，并将 result.json 可选上传到 MinIO。

节点之间的业务数据通过 HTTP 网络通信传递，不再依赖 `/scratch` 共享目录。

架构上允许平台为了健康检查按 DAG 拓扑启动容器；但验收时更要确认数据确实按 source -> compute -> sink 网络路径流转，而不是依赖启动顺序或共享文件系统“看起来跑完”。

## 命名说明

旧脚本名 `seed_demo_data.py` 表达的是“向开发库填充种子数据”，后来短暂出现过 `setup_matmul_demo.py`。这两个脚本都已停用——它们假设 SQLite 演示库里的 demo-worker UUID，而生产 MySQL 没有这些 UUID。当前唯一入口是 `backend/scripts/rebuild_matmul_template.py`：它从 `DATABASE_URL`（或 `MYSQL_*` 环境变量）解析连接信息，直接查 MySQL 的 `nodes` 表拿 compute-1/2/3 的真实 UUID，再调用 API 重建模板。
