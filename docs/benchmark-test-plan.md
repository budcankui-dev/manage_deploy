# 业务目标验收测试方案

> 最后更新：2026-06-16
> 状态：已实现业务目标成功率闭环、节点资源同步、按验收轮次自动补算成功率和清理实例保留证据。矩阵乘法当前可复现正式轮次为 `high_throughput_matmul-20260612095418`，30/30 达标，成功率 100.0%。视频 AI 推理链路已具备固定视频、YOLO 推理、带框预览和 4/4 联调轮次（`video-route-pool-check-20260612160633`），但正式 30 样本验收轮次仍需重新跑通并截图留档。

## 目标

验证系统在真实工作负载下，业务目标成功率达到验收要求：

```text
业务目标成功率 = 业务目标达成工单数 / 已完成且可评价工单数 x 100%
验收通过条件：业务目标成功率 >= 90%
```

当前正式主验收业务类型：高吞吐矩阵乘法，系统标识为 `high_throughput_matmul`。

第二模态扩展：低时延视频 AI 推理，系统标识为 `low_latency_video_pipeline`。当前已提供轻量 worker `workers/low-latency-video/`，并在 `/benchmark` 页面开放为可选任务类型，用于工业检测抽帧推理场景：source 读取固定测试视频并抽帧，compute 加载 `yolov5n-fp32.onnx` 执行检测并统计逐帧推理时延，sink 上报 `frame_latency_p90_ms`、检测框和带框预览图。它已跑通小批量联调轮次，可用于证明系统具备多模态扩展能力；正式留档口径同样要求当前轮次已评估任务不少于 30 且业务目标成功率不低于 90%，不能用 4/4 或其他小样本轮次替代正式验收截图。

## 验收指标

矩阵乘法任务使用过程性计算速率指标，不用绝对完成时间作为业务目标。

```text
单次采样 effective_gflops = 2 x matrix_size^3 x sample_batch_count / sample_elapsed_seconds / 1e9
单任务 actual_gflops = 有效观测窗口内多次采样的 median(effective_gflops)
单任务达标条件：actual_gflops >= baseline_gflops x 0.8
```

其中 `baseline_gflops` 是正式测评前在相同业务 profile、相同镜像和相同推理/计算路径下测出的节点基线能力。建议每个节点重复 3 次取中位数写入基线表；历史实测结果只作为系统设置推荐和异常排查参考，不能替代当前轮基线。`0.8` 是科研验收阶段的容忍系数，用于覆盖轻微环境波动，同时仍要求任务达到节点基线能力的主要水平。

矩阵乘法任务不以端到端完成时间作为目标。Worker 在启动后先执行 warmup，再在固定观测窗口内持续采样，任务结束后由 sink 上报汇总指标。若任务运行时间不足、未达到最小采样数，或未上报指标，则不能作为成功样本；正式验收页面会将其保留在测试工单列表中，并通过“已评估任务数不足”或失败原因提示出来。

视频 AI 推理任务同样使用过程性指标，不以人工计时作为业务目标。

```text
单帧 latency_ms = YOLO 检测推理阶段耗时
单任务 actual_latency = 有效统计帧 latency_ms 的 P90
单任务达标条件：baseline_latency_p90_ms / actual_latency >= 0.8

actual_latency <= baseline_latency_p90_ms * 1.5
```

等价写法：`actual_latency <= baseline_latency_p90_ms * 1.5`。

其中 `baseline_latency_p90_ms` 是正式测评前在相同视频 profile、相同固定视频、相同 YOLO 权重和 GPU 推理路径下测出的节点基线 P90 帧时延。视频时延是“越低越好”的指标，因此达标写作 `actual_latency <= baseline_latency_p90_ms * 1.5`；含义是正式任务的 P90 时延不能明显劣于当前节点基线。视频 worker 默认要求 compute 子任务分配 GPU；CPU 路径仅作为开发调试开关，不能写入正式验收基线。正式演示时，工单详情应展示 compute 节点、GPU 编号、模型名称、固定视频、检测框列表和带框预览图，证明业务真实执行而不是只上报静态数值。

## 测试环境

- 管理员前端：`http://10.112.244.94:8182`
- 业务测评页：`http://10.112.244.94:8182/benchmark`
- 后端 API：`http://10.112.244.94:8181`
- 管理节点：`admin-server`，`10.112.244.94`
- 业务节点：`compute-1`、`compute-2`、`compute-3`
- 用户终端节点：`h1-h13`，当前作为用户接入源/目的端点和 route-only/轻量 source/sink 演示终端

机器详情见 [docs/deployment/测试部署机器清单.md](/Users/yanjia/codes/manage_deploy/docs/deployment/测试部署机器清单.md)。
真实拓扑迁移、构建、预检和页面验收命令见 [docs/deployment/matmul-acceptance-runbook.md](/Users/yanjia/codes/manage_deploy/docs/deployment/matmul-acceptance-runbook.md)。

## 前置条件

1. `admin-server` 已部署前端、后端、数据库、对象存储和私有镜像仓库。
2. `compute-1/2/3` 已注册为可调度计算节点，`h1-h13` 已注册为终端节点。业务目标成功率测评中，平台可在可管控测试设备上部署 source / compute / sink 容器，用于自动化统计成功率；真实用户接入演示中，source/sink 默认是用户自行控制的终端端点，平台通常只部署 compute。
3. 业务节点已运行 Node Agent，管理面能访问各节点 Agent API。
4. 矩阵乘法 worker 镜像已在 AMD64 环境构建并推送到 `10.112.244.94:5000/scientific-matmul:dev`。
5. 每个参与测试的节点已完成相同 profile 的 baseline 测试，且 `stable=true`。

## 默认参数

### 矩阵乘法默认参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 任务数量 | `30` | 正式验收固定 30；少于 30 只作为调试，不判定正式通过 |
| 矩阵规模 | `1024` | 与 baseline profile 保持一致 |
| 批次数 | `50` | 与 baseline profile 保持一致 |
| warmup | `3` | 前 3 批不计入有效吞吐 |
| 观测窗口 | `10s` | 与 baseline profile 保持一致 |
| 采样间隔 | `1s` | 每秒最多采集一组吞吐样本 |
| 单次采样批次 | `5` | 每个采样点执行 5 批矩阵乘法 |
| 最少样本数 | `5` | 少于 5 个有效样本不作为正式成功证据 |
| 随机种子 | `42` | 保持重复性 |

### 视频 AI 推理默认参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 任务数量 | `30` | 正式验收固定 30；少于 30 只作为调试，不判定正式通过 |
| 固定测试视频 | `bottle-detection.mp4` | 打包进 worker 镜像，模拟工业检测/瓶体识别场景 |
| 检测模型 | `yolov5n-fp32.onnx` | 打包进 worker 镜像，生成分类检测框和帧推理时延 |
| 分辨率 | `720p` | 页面展示 profile 名称，实际测试视频为 640x360，按固定资产复现 |
| fps | `30` | 用于解释抽帧间隔和业务画像 |
| 抽帧间隔 | `30` | 约每秒抽 1 帧，避免批量测评产生过高数据面流量 |
| warmup_frames | `10` | 前 10 帧用于模型和 OpenCV DNN 预热 |
| measured_frames | `30` | 统计 30 帧的 P90 时延，兼顾演示速度和稳定性 |
| 置信度阈值 | `0.25` | 固定检测参数，避免不同批次人为调参 |
| NMS 阈值 | `0.45` | 固定检测参数 |

## 页面流程

### Step 1 基线

业务测评页直接列出所有可调度节点：

- 未测试节点显示红色“未测试”。
- 已测试节点显示 `baseline_value`、稳定性和上次更新时间。
- 自动分配计算节点时，有同任务基线的计算节点均可参与；稳定基线节点优先，波动较大的节点作为低优先级候选，避免因单节点波动导致测评资源闲置。
- 每行支持单节点“测试/重测”。
- 底部操作支持“批量测试所有节点”。

### Step 2 批量测评

在一行内配置任务数和当前任务类型的固定 profile 参数，然后点击“创建测评工单”。矩阵乘法展示矩阵规模、批次数、观测秒数和最少样本数；视频 AI 推理展示帧数、抽帧间隔和有效帧数。内部 CPU 调试测评参数不作为专家验收页面参数展示，仅在开发调试场景使用。

创建出的工单应带 `is_benchmark=true` 标记，只用于验收成功率统计，避免和普通用户工单混在一起。测评工单会自动写入业务开始/结束时间，保证路由回写后可以稳定物化为 scheduled 实例。

测评工单使用运营商可控测试域，运行配置中 `platform_deployment.deployable_roles=["source","compute","sink"]`。这表示平台会部署测试 source/sink 容器来产生和汇总业务数据，目的是批量、可复现地统计业务目标成功率；它不代表平台需要或应该控制真实用户终端。普通用户对话工单默认采用 `deployable_roles=["compute"]`，source/sink 作为外部接入端点。

如果不显式指定源/目的终端，后端会在 `h1-h13` 终端节点中按工单序号轮转源和目的，避免 30 个测评工单全部压到固定 `h1 -> h2`。计算节点也会按已有基线候选分散选择，优先使用稳定且基线表现更好的节点，波动节点低优先级参与。

每次创建批量测评都会生成一个 `benchmark_run_id`，并写入工单 `runtime_config.benchmark.run_id`。页面顶部展示“当前验收轮次”，后续工单列表、路由执行、运行测评和 Step 4 结果默认只统计当前轮次。验收页支持用 `/benchmark?benchmark_run_id=<run_id>` 直接打开指定轮次，便于截图留档和复核。旧版本历史工单没有轮次标记时，页面会退回到“全部历史测评工单”口径，仅用于调试回看，不建议作为正式验收截图。

### Step 3 执行

执行区实时展示工单状态分布：

```text
待路由 / 已路由 / 运行中 / 已完成 / 失败
```

操作按钮：

- “运行测评”：按当前系统设置决定路由来源。正式验收优先等待外部路由系统回写 placements；开发联调时可在系统设置页启用开发调试路由流程，由平台为当前 `benchmark_run_id` 和当前任务类型的 `is_benchmark=true` 工单生成 placements。路由完成后，系统按页面上的“并发任务数”小批次执行已路由工单，默认并发数为 3；资源暂不可用时会自动等待。任务上报指标后，系统停止并删除容器实例，保留工单、路由结果、业务指标和结果证据，再启动下一批。
- “刷新”：重新拉取状态。

正式演示时，Step 3 的路由生成和启动操作只应作用于当前 `benchmark_run_id`。如果需要重新跑一轮验收，应重新点击 Step 2 创建新的测评工单，让新旧结果分离，避免把历史失败或历史成功样本混入本轮统计。

运行测评是矩阵计算验收的默认执行口径。原因是节点 baseline 反映单任务在同 profile 下的历史能力；如果把 30 个矩阵任务一次性并发启动，测到的是资源争抢后的吞吐，不再能和单任务基线直接比较，容易把平台执行方式的过载误判成业务目标不达标。运行测评不会调宽达标阈值，只是让验收执行方式与 baseline 定义保持一致。

### 测试工单列表

页面在执行区后展示“测试工单列表”表：

- 列出最近测评工单的任务状态、路由状态、部署状态、实例 ID 和 placements 摘要。
- 点击“详情”可查看业务参数 JSON、路由结果 JSON、source/compute/sink 实际部署节点、compute GPU 编号、业务目标评估结果和指标采集元数据；视频任务还应展示带框预览图、检测类别、置信度和画框坐标。
- 该区域用于专家复核“成功率不是静态造数”，而是由每个真实工单、实例、路由放置和指标上报汇总而来。

### 测评数据与实例清理

验收页面和业务工单中心提供两类清理动作：

- “清理实例保留工单”：停止并删除远端容器、实例节点记录和调度残留，但保留工单、实例证据 ID、路由结果、业务目标评估、结果文件 URI 和指标 JSON。清理后业务任务中心可显示 `实例已删除` 或 `instance_exists=false`，该工单仍可作为历史验收证据和成功率统计依据。
- “删除工单”：删除工单及其关联实例、评估和结果证据。该动作只适合清理废弃测试轮次或错误数据，正式验收成功轮次应先截图或导出 JSON 后再删除。

设计原因：

- 停止的 Docker 容器仍可能保留 writable layer、日志和元数据，批量测评多轮后会占用磁盘并干扰运维观察。
- 专家评审更关心“工单是否真实跑过、路由/GPU/指标证据是否可追溯”，不要求验收结束后容器一直留在机器上。
- 按 `benchmark_run_id` 清理能释放整轮测评资源，同时避免把历史成功/失败样本混入下一轮正式统计。

推荐流程：

```text
完成一轮测评 -> 截图 Step 1/Step 3/详情/Step 4 -> 如需释放资源，按当前 benchmark_run_id 清理实例保留工单 -> 仅删除废弃轮次
```

### Step 4 结果

结果区以进度条展示当前任务类型的业务目标成功率：

- 成功率 `>= 90%` 且已评估任务数 `>= 30` 显示绿色，判定验收通过。
- 成功率 `< 90%` 显示红色，判定未达标。
- 已评估任务数 `< 30` 显示“样本不足”，即使当前比例为 100% 也不能作为正式验收截图。
- 展示 `达标任务数 / 已评估任务数`，便于专家快速核对。
- 截图时应同时保留页面顶部的 `benchmark_run_id`，证明 Step 2、Step 3、测试工单列表和 Step 4 属于同一轮测评。

## 路由系统边界

当前阶段路由算法实现可以先采用资源约束驱动的简单放置算法，例如选择 GPU 数量满足要求且已有同任务基线的节点；稳定基线节点排序靠前，波动较大的节点作为低优先级候选。该算法在 DAG 中通常对应 `routing_strategy=resource_guarantee`。业务目标成功率不证明路由算法全局最优，而是证明平台能完成：

```text
用户/测试工单 -> DAG 生成 -> 路由放置 -> 实例部署 -> Worker 运行 -> 指标采集 -> 业务目标判定 -> 成功率统计
```

外部路由系统接入时：

- 工单创建时生成 `task_orders.routing_input_dag`。
- `routing_input_dag.edges[]` 除 `data_mb` 外还包含 `bandwidth_mbps`，表达源节点、业务计算节点、目的节点之间的链路约束。当前值由任务类型和数据画像估算，后续可替换为实测基准。
- `routing_input_dag.nodes[].resources` 由平台资源估算器根据任务类型和固定 profile 生成；如某轮基线或实测表明默认值需要调整，可在系统设置中启用任务资源要求覆盖，覆盖值优先写入 DAG。
- DAG 资源字段中，GPU 需求会通过路由回写的 GPU 编号进入实际容器部署；CPU、内存和磁盘当前作为路由估算、展示和容器环境变量，不自动作为容器硬限制。若后续需要强限制 CPU/内存，应在模板或实例运行参数中显式设置。
- 外部路由系统写回每个 DAG 子任务的目标节点和 GPU 编号。冻结联调接口使用 `POST /api/routing-orders/{order_id}/result`，业务 placements 通常只需要回写 `compute`，compute 节点可携带 `gpu_device`；source/sink 固定端点由平台根据 DAG 与工单配置补齐。
- 平台接收结果后把 `routing_result` 同步写入工单运行配置，并根据 `platform_deployment.deployable_roles` 物化实例。测评工单按 source -> compute -> sink 三容器随路计算数据流部署执行；普通用户接入工单默认只部署 compute，并返回外部 source 访问 compute 的业务链路。冻结 placement 格式为 `{"task_node_id":"compute","topology_node_id":"compute-3","gpu_device":"0"}`；历史测试数据不迁移，清理后按当前格式重新跑通。
- 如果多个业务类型复用同一个 source/compute/sink 模板，平台会优先根据工单 `runtime_config.business_task.task_type` 定位 `business_template_catalog`，避免只按 `template_id` 查找时出现多条 catalog 歧义。
- 业务目标评估根据 `routing_result` 中的 compute/worker 放置节点查找该节点 baseline，判定任务是否达到历史基准阈值。

当前 `/benchmark` 页面优先接收外部路由系统回写结果；系统设置页可切换开发调试路由流程，用于路由系统联调前验证部署与评价闭环。正式验收留档应明确记录所用路由模式，业务目标成功率本身不等同于证明路由算法全局最优。

外部路由系统联调的具体接口、字段格式和最短接入路径见 [routing-system-integration-guide.md](/Users/yanjia/codes/manage_deploy/docs/routing-system-integration-guide.md)。

## 真实拓扑执行要求

从本地代码修改迁移到真实拓扑时，必须先提交/推送代码，再按 [标准化部署与运维流程](/Users/yanjia/codes/manage_deploy/docs/deployment/标准化部署与运维流程.md) 更新 `admin-server` 的 `/home/bupt/manage_deploy` 并重启服务。当前管理节点按拷贝式部署目录使用，不在远端 `git pull`；同步时必须排除数据库、`.env`、虚拟环境和报告产物。涉及 worker、Node Agent 或 Dockerfile 变更时，还必须重新构建 AMD64 镜像并推送到 `10.112.244.94:5000`，随后让 `compute-1/2/3` 拉取最新镜像并预检查容器内代码。禁止在真实验收中沿用本地 `127.0.0.1`、ARM64 镜像、`WORKER_SKIP_BUILD=1` 或跳过远端镜像预检查。

完整操作清单见 [matmul-acceptance-runbook.md](/Users/yanjia/codes/manage_deploy/docs/deployment/matmul-acceptance-runbook.md)。

推荐正式验收执行命令：

```bash
# admin-server 构建并推送 AMD64 worker
cd /home/bupt/manage_deploy
WORKER_IMAGE=10.112.244.94:5000/scientific-matmul \
WORKER_TAG=dev \
WORKER_PLATFORM=linux/amd64 \
WORKER_PUSH=1 \
./scripts/build_workers.sh

# admin-server 重建模板，确保模板 image 指向私有 registry
cd /home/bupt/manage_deploy/backend
WORKER_IMAGE=10.112.244.94:5000/scientific-matmul \
WORKER_TAG=dev \
DEMO_BASE_URL=http://127.0.0.1:8181 \
PYTHONPATH=. /home/bupt/miniconda3/bin/python3.13 scripts/rebuild_matmul_template.py
```

视频推理 worker 构建命令：

```bash
WORKER_KIND=video \
WORKER_IMAGE=10.112.244.94:5000/low-latency-video \
WORKER_TAG=dev \
WORKER_PLATFORM=linux/amd64 \
WORKER_PUSH=1 \
./scripts/build_workers.sh
```

本地快速验证视频 baseline 开发调试路径：

```bash
cd backend
PYTHONPATH=. ./venv/bin/python - <<'PY'
from services.baseline_runner import run_benchmark
print(run_benchmark("low_latency_video_pipeline", runs=1))
PY
```

网络不可用应急说明：如果实验网络无法访问 Docker Hub、Ubuntu apt 或 NVIDIA 软件源，可以复用 registry 中已验证为 `linux/amd64` 的旧 `scientific-matmul:dev` 镜像作为基础层，只刷新 `/app/src` 和 `/app/_common` 业务代码层。该方式不是默认正式路径；使用前应记录镜像 digest，并确认旧镜像依赖、CUDA/GPU 路径和当前业务代码兼容。

```bash
cd /home/bupt/manage_deploy
docker pull localhost:5000/scientific-matmul:dev
docker tag localhost:5000/scientific-matmul:dev scientific-matmul:base-cache
cat >/tmp/Dockerfile.matmul-refresh <<'EOF'
FROM scientific-matmul:base-cache
COPY _common /app/_common
COPY high-throughput-matmul/src /app/src
ENV PYTHONPATH=/app/src:/app
ENV USE_GPU=true
CMD ["python3", "/app/src/source_main.py"]
EOF
docker build --pull=false --platform linux/amd64 \
  -f /tmp/Dockerfile.matmul-refresh \
  -t localhost:5000/scientific-matmul:dev workers
docker run --rm --entrypoint python3 localhost:5000/scientific-matmul:dev \
  -c 'import pathlib; t=pathlib.Path("/app/src/compute_main.py").read_text(); print("observation_duration_sec" in t, "sample_count" in t)'
docker push localhost:5000/scientific-matmul:dev
```

该方式不改变运行环境依赖，只更新业务代码层，适合验收现场外网不可用但旧镜像已验证可运行的场景。

```bash
# 本地或 admin-server 运行真实远程 E2E preflight，不能跳过镜像/架构/agent 检查
BASE_URL=http://10.112.244.94:8181 \
E2E_REMOTE=1 \
WORKER_IMAGE=10.112.244.94:5000/scientific-matmul \
WORKER_TAG=dev \
E2E_REMOTE_NODES="manage-compute-1 manage-compute-2 manage-compute-3" \
E2E_NODE_AGENT_HOSTS="10.112.38.25 10.112.17.51 10.112.59.209" \
MATMUL_MATRIX_SIZE=1024 \
MATMUL_BATCH_COUNT=50 \
./scripts/e2e_matmul_live.sh
```

## 可视化 E2E 要求

端到端测试需要让用户看到页面过程时，Tester Agent 应使用有头浏览器或 Codex Browser 打开 `http://10.112.244.94:8182/benchmark`，逐步操作 Step 1 到 Step 4，并在关键节点保留截图或页面状态说明。

命令行 API 校验只能作为辅助，不能替代浏览器中对验收页面布局、状态变化和结果进度条的可视化确认。

## 当前限制

- 当前验收页面的 UI 四步流程已基本具备。
- 当前 `/api/baselines/run` 已改为通过目标节点 Node Agent 运行 benchmark 容器；只有显式传入兼容参数 `allow_local_fallback=true` 才允许本地开发调试路径，该参数不用于正式验收。
- 当前业务目标统计接口支持按 `is_benchmark=true` 过滤，验收页面只统计测评工单，避免普通业务污染成功率。
- 当前业务目标统计接口和订单列表支持按 `benchmark_run_id` 过滤，验收页面默认按当前轮次统计，避免新旧测评结果互相污染。
- 当前验收页面支持 `POST /api/orders/start-controlled-routed` 运行测评，按小批次限流执行，并在评估后释放容器实例、保留工单证据；正式矩阵验收不再使用一次性启动全部实例作为默认口径。
- 当前业务工单中心支持按 `benchmark_run_id` 筛选验收测评工单，并提供“清理实例保留工单”和“删除工单”两类批量操作；前者用于释放容器资源并保留证据，后者用于删除废弃轮次。
- 当前视频 AI 推理 worker 已提供本地单测、benchmark mode 和镜像构建入口，并已在 `/benchmark` 页面作为扩展业务类型开放；它使用固定测试视频 + YOLOv5n ONNX 产出带框结果，CPU 路径仅作为开发调试开关。如需远端联调，先构建 `WORKER_KIND=video WORKER_IMAGE=10.112.244.94:5000/low-latency-video WORKER_TAG=dev WORKER_PLATFORM=linux/amd64 WORKER_PUSH=1 ./scripts/build_workers.sh`，再注册对应模板和 catalog。
- 当前正式判定不依赖实时 CPU/GPU 监控。资源监控可作为演示增强项，但验收主证据是工单详情中的实例状态、实际节点/GPU 分配、业务指标评估和指标采集 JSON，避免为了演示引入额外监控系统导致链路变复杂。
- 当前测试工单列表依赖管理员视角查看全局 `is_benchmark=true` 工单；普通用户仍只能查看自己的工单，管理员页面必须能列出全部测评工单并打开详情。
- 真正面向专家验收前，需要在当前真实拓扑环境执行一次全量 baseline 和 30 任务测评，并保存浏览器截图和 JSON 报告。
- 截图建议包含 Step 1 基线表、Step 3 状态分布、测试工单列表中的任务工单详情抽屉和 Step 4 成功率进度条。
