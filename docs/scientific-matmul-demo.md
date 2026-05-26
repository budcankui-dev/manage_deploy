# 科学计算矩阵乘法演示

本项目当前维护的演示业务是 **科学计算矩阵乘法**，内部 `task_type` 为 `high_throughput_matmul`。它用一个 source -> compute -> sink 的三节点 DAG 展示业务任务从创建、路由放置、容器编排、指标上报到业务目标评估的完整闭环。

这个演示的产品重点不是证明容器必须按某个业务顺序启动，而是证明外部路由算法选择的路径会承载真实业务数据。source、compute、sink 的放置来自 routing placements，矩阵 job/result 沿这些节点之间的 HTTP `PEER_*` 地址流转，这就是当前测试业务的随路计算原则。

## 运行入口

```bash
# 构建单个 worker 镜像
./scripts/build_workers.sh

# 准备演示节点、模板和业务目录项
DEMO_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/setup_matmul_demo.py

# 需 backend :8000 + node_agent :8001 + Docker
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
```

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

1. source 根据 `DATA_PROFILE` 生成矩阵规模、批次数和随机种子，并等待 compute 就绪信号。
2. compute 启动 HTTP 服务后通知 source，收到 job 后执行 NumPy batched FP32 矩阵乘法。
3. compute 通过 HTTP 将结果推给 sink。
4. sink 接收结果，向 Manager 上报 `compute_latency_ms`，并可选上传 `result.json` 到 MinIO。

节点之间的业务数据通过 HTTP 网络通信传递，不再依赖 `/scratch` 共享目录。

架构上允许平台为了健康检查按 DAG 拓扑启动容器；但验收时更要确认数据确实按 source -> compute -> sink 网络路径流转，而不是依赖启动顺序或共享文件系统“看起来跑完”。

## 命名说明

旧脚本名 `seed_demo_data.py` 表达的是“向开发库填充种子数据”。现在这个演示更准确的动作是“准备矩阵乘法演示环境”，因此新入口是 `backend/scripts/setup_matmul_demo.py`。旧脚本仍保留为兼容包装，避免已有命令立即失效。
