# 业务目标验收测试方案

> 最后更新：2026-06-09
> 状态：已实现基础闭环，真实远程基线执行已接入 Node Agent；前端已按“成功率 ≥90% 且已评估任务 ≥30”判定正式通过，并增加压测工单证据链详情和验收轮次 ID；矩阵乘法与视频 AI 推理均已按固定参数完成 30 个可评价工单验收轮次，当前均为 30/30 达标。视频 AI 推理工单详情可展示带中文标签的 YOLO 画框预览，用于演示业务真实执行结果。

## 目标

验证系统在真实工作负载下，业务目标成功率达到验收要求：

```text
业务目标成功率 = 业务目标达成工单数 / 已完成且可评价工单数 x 100%
验收通过条件：业务目标成功率 >= 90%
```

当前正式主验收业务类型：高吞吐矩阵乘法，系统标识为 `high_throughput_matmul`。

第二模态扩展：低时延视频 AI 推理，系统标识为 `low_latency_video_pipeline`。当前已提供轻量 worker `workers/low-latency-video/`，并在 `/benchmark` 页面开放为可选任务类型，用于工业检测抽帧推理场景：source 读取固定测试视频并抽帧，compute 加载 `yolov5n-fp32.onnx` 执行检测并统计逐帧推理时延，sink 上报 `frame_latency_p90_ms`、检测框和带框预览图。它可本地运行 baseline、构建镜像并创建验收工单，用于证明系统具备多模态扩展能力；正式留档口径同样要求当前轮次已评估任务不少于 30 且业务目标成功率不低于 90%。当前可复现留档轮次为 `video-formal-20260610-01`，30/30 达标，并可在工单详情中查看带框预览图。

## 验收指标

矩阵乘法任务使用过程性计算速率指标，不用绝对完成时间作为业务目标。

```text
单次采样 effective_gflops = 2 x matrix_size^3 x sample_batch_count / sample_elapsed_seconds / 1e9
单任务 actual_gflops = 有效观测窗口内多次采样的 median(effective_gflops)
单任务达标条件：actual_gflops >= baseline_gflops x 0.8
```

其中 `baseline_gflops` 是该节点在相同业务 profile 下的历史基准能力，`0.8` 是科研验收阶段的容忍系数。这样可以屏蔽输入数据量差异，重点评价“任务运行后的过程性能力是否达到该节点历史水平”。

矩阵乘法任务不以端到端完成时间作为目标。Worker 在启动后先执行 warmup，再在固定观测窗口内持续采样，任务结束后由 sink 上报汇总指标。若任务运行时间不足、未达到最小采样数，或未上报指标，则不能作为成功样本；正式验收页面会将其保留在工单证据链中，并通过“已评估任务数不足”或失败原因提示出来。

视频 AI 推理任务同样使用过程性指标，不以人工计时作为业务目标。

```text
单帧 latency_ms = YOLO 检测推理阶段耗时
单任务 actual_latency = 有效统计帧 latency_ms 的 P90
单任务达标条件：actual_latency <= baseline_latency_p90_ms x 1.5
```

其中 `baseline_latency_p90_ms` 是该节点在相同视频 profile 下的历史基准 P90 帧时延，`1.5` 是科研验收阶段对共享 GPU/CPU 负载波动的容忍系数。视频 worker 默认要求 compute 子任务分配 GPU；CPU 仅作为开发和故障兜底。正式演示时，工单详情应展示 compute 节点、GPU 编号、模型名称、固定视频、检测框列表和带框预览图，证明业务真实执行而不是只上报静态数值。

## 测试环境

- 管理员前端：`http://10.112.244.94:8182`
- 业务测评页：`http://10.112.244.94:8182/benchmark`
- 后端 API：`http://10.112.244.94:8181`
- 管理节点：`admin-server`，`10.112.244.94`
- 业务节点：`compute-1`、`compute-2`、`compute-3`

机器详情见 [docs/deployment/test-lab.md](/Users/yanjia/codes/manage_deploy/docs/deployment/test-lab.md)。
真实四节点迁移、构建、预检和页面验收命令见 [docs/deployment/matmul-acceptance-runbook.md](/Users/yanjia/codes/manage_deploy/docs/deployment/matmul-acceptance-runbook.md)。

## 前置条件

1. `admin-server` 已部署前端、后端、数据库、对象存储和私有镜像仓库。
2. `compute-1/2/3` 已注册为可调度节点，可作为 source / compute / sink。
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
| 抽帧间隔 | `30` | 约每秒抽 1 帧，避免批量压测产生过高数据面流量 |
| warmup_frames | `10` | 前 10 帧用于模型和 OpenCV DNN 预热 |
| measured_frames | `30` | 统计 30 帧的 P90 时延，兼顾演示速度和稳定性 |
| 置信度阈值 | `0.25` | 固定检测参数，避免不同批次人为调参 |
| NMS 阈值 | `0.45` | 固定检测参数 |

## 页面流程

### Step 1 基线

业务测评页直接列出所有可调度节点：

- 未测试节点显示红色“未测试”。
- 已测试节点显示 `baseline_value`、稳定性和上次更新时间。
- 每行支持单节点“测试/重测”。
- 底部操作支持“批量测试所有节点”。

### Step 2 批量压测

在一行内配置任务数和当前任务类型的固定 profile 参数，然后点击“创建压测工单”。矩阵乘法展示矩阵规模、批次数、观测秒数和最少样本数；视频 AI 推理展示帧数、抽帧间隔、有效帧数和计算强度。

创建出的工单应带 `is_benchmark=true` 标记，只用于验收成功率统计，避免和普通用户工单混在一起。压测工单会自动写入业务开始/结束时间，保证路由回写后可以稳定物化为 scheduled 实例。

每次创建批量压测都会生成一个 `benchmark_run_id`，并写入工单 `runtime_config.benchmark.run_id`。页面顶部展示“当前验收轮次”，后续工单列表、生成随机路由、自动执行和 Step 4 结果默认只统计当前轮次。验收页支持用 `/benchmark?benchmark_run_id=<run_id>` 直接打开指定轮次，便于截图留档和复核。旧版本历史工单没有轮次标记时，页面会退回到“全部历史压测工单”口径，仅用于调试回看，不建议作为正式验收截图。

### Step 3 执行

执行区实时展示工单状态分布：

```text
待路由 / 已路由 / 运行中 / 已完成 / 失败
```

操作按钮：

- “生成随机路由”：使用平台内置随机路由策略，为当前 `benchmark_run_id` 和当前任务类型的 `is_benchmark=true` 待路由工单随机选择可调度节点并生成 placements。它可作为外部路由系统未接入时的 fallback 策略，用于验证部署与评价闭环。
- “自动执行”：按计算节点和 GPU 编号形成执行槽位，同一槽位默认同一时刻只运行 1 个验收任务；任务上报指标后，系统停止并删除容器实例，保留工单、路由结果、业务指标和结果证据，再启动下一批。
- “刷新”：重新拉取状态。

正式演示时，Step 3 的内置随机路由策略和启动操作只应作用于当前 `benchmark_run_id`。如果需要重新跑一轮验收，应重新点击 Step 2 创建新的压测工单，让新旧结果分离，避免把历史失败或历史成功样本混入本轮统计。

自动执行是矩阵计算验收的默认执行口径。原因是节点 baseline 反映单任务在同 profile 下的历史能力；如果把 30 个矩阵任务一次性并发启动，测到的是资源争抢后的吞吐，不再能和单任务基线直接比较，容易把平台执行方式的过载误判成业务目标不达标。自动执行不会调宽达标阈值，只是让验收执行方式与 baseline 定义保持一致。

### 工单证据链

页面在执行区后展示“验收工单证据链”表：

- 列出最近压测工单的任务状态、路由状态、部署状态、实例 ID 和 placements 摘要。
- 点击“详情”可查看业务参数 JSON、路由结果 JSON、source/compute/sink 实际部署节点、compute GPU 编号、业务目标评估结果和指标采集元数据；视频任务还应展示带框预览图、检测类别、置信度和画框坐标。
- 该区域用于专家复核“成功率不是静态造数”，而是由每个真实工单、实例、路由放置和指标上报汇总而来。

### 压测数据与实例清理

验收页面和业务工单中心提供两类清理动作：

- “清理实例保留工单”：停止并删除远端容器、实例节点记录和调度残留，但保留工单、路由结果、业务目标评估、结果文件 URI 和指标 JSON。清理后页面应显示 `实例已删除`，该工单仍可作为历史验收证据和成功率统计依据。
- “删除工单”：删除工单及其关联实例、评估和结果证据。该动作只适合清理废弃测试轮次或错误数据，正式验收成功轮次应先截图或导出 JSON 后再删除。

设计原因：

- 停止的 Docker 容器仍可能保留 writable layer、日志和元数据，批量压测多轮后会占用磁盘并干扰运维观察。
- 专家评审更关心“工单是否真实跑过、路由/GPU/指标证据是否可追溯”，不要求验收结束后容器一直留在机器上。
- 按 `benchmark_run_id` 清理能释放整轮压测资源，同时避免把历史成功/失败样本混入下一轮正式统计。

推荐流程：

```text
完成一轮压测 -> 截图 Step 1/Step 3/详情/Step 4 -> 如需释放资源，按当前 benchmark_run_id 清理实例保留工单 -> 仅删除废弃轮次
```

### Step 4 结果

结果区以进度条展示当前任务类型的业务目标成功率：

- 成功率 `>= 90%` 且已评估任务数 `>= 30` 显示绿色，判定验收通过。
- 成功率 `< 90%` 显示红色，判定未达标。
- 已评估任务数 `< 30` 显示“样本不足”，即使当前比例为 100% 也不能作为正式验收截图。
- 展示 `达标任务数 / 已评估任务数`，便于专家快速核对。
- 截图时应同时保留页面顶部的 `benchmark_run_id`，证明 Step 2、Step 3、证据链和 Step 4 属于同一轮压测。

## 路由系统边界

当前阶段路由策略可以是资源约束驱动的简单放置策略，例如选择 GPU 数量满足要求的节点。业务目标成功率不证明路由算法全局最优，而是证明平台能完成：

```text
用户/测试工单 -> DAG 生成 -> 路由放置 -> 实例部署 -> Worker 运行 -> 指标采集 -> 业务目标判定 -> 成功率统计
```

外部路由系统接入时：

- 工单创建时生成 `task_orders.routing_input_dag`。
- `routing_input_dag.edges[]` 除 `data_mb` 外还包含 `bandwidth_mbps`，表达源节点、业务计算节点、目的节点之间的链路约束。当前值由任务类型和数据画像估算，后续可替换为实测基准。
- 外部路由系统写回每个 DAG 子任务的目标节点和 GPU 编号。对话/工单主链路使用 `POST /api/routing-results/{routing_request_id}`，验收工单可直接使用 `POST /api/orders/{order_id}/routing-result`。两者都要表达 `source`、`compute/worker`、`sink` placements，compute 节点可携带 `gpu_device` 或 `gpu_indices`。
- 平台接收结果后把 `routing_result` 同步写入工单运行配置，物化实例，并按 source -> compute -> sink 的随路计算数据流部署执行。当前 `/benchmark` 内置随机路由策略写回 list 形式 placements，例如 `[{node_id:"compute", worker_host:"compute-3", gpu_device:"0"}]`；正式路由系统可使用更丰富的 dict 形式，平台按角色解析。
- 如果多个业务类型复用同一个 source/compute/sink 模板，平台会优先根据工单 `runtime_config.business_task.task_type` 定位 `business_template_catalog`，避免只按 `template_id` 查找时出现多条 catalog 歧义。
- 业务目标评估根据 `routing_result` 中的 compute/worker 放置节点查找该节点 baseline，判定任务是否达到历史基准阈值。

当前 `/benchmark` 页面的“内置随机路由策略”是平台 fallback 策略，用于跑通部署与评价闭环；它不证明外部路由算法最优，但可以作为外部路由系统未接入时的基线演示策略。

外部路由系统联调的具体接口、字段格式和最短接入路径见 [routing-system-integration-guide.md](/Users/yanjia/codes/manage_deploy/docs/routing-system-integration-guide.md)。

## 真实四节点执行要求

从本地代码修改迁移到真实拓扑时，必须先提交/推送代码，再在 `admin-server` 更新部署目录并重启服务。若 `admin-server` 的 `/home/bupt/manage_deploy` 是 Git 仓库，使用 `git pull`/`git switch`；若它是手工部署目录，则使用 `git archive <commit>` 或只同步本次提交涉及的文件，避免把本地未提交改动、数据库、`.env` 或报告产物带到远端。涉及 worker、Node Agent 或 Dockerfile 变更时，还必须重新构建 AMD64 镜像并推送到 `10.112.244.94:5000`，随后让 `compute-1/2/3` 拉取最新镜像并预检查容器内代码。禁止在真实验收中沿用本地 `127.0.0.1`、ARM64 镜像、`WORKER_SKIP_BUILD=1` 或跳过远端镜像预检查。

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
WORKER_IMAGE=10.112.244.94:5000/scientific-matmul \
WORKER_TAG=dev \
DEMO_BASE_URL=http://127.0.0.1:8181 \
PYTHONPATH=backend \
/home/bupt/miniconda3/envs/manage_deploy/bin/python backend/scripts/rebuild_matmul_template.py
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

本地快速验证视频 baseline fallback：

```bash
cd backend
PYTHONPATH=. ./venv/bin/python - <<'PY'
from services.baseline_runner import run_benchmark
print(run_benchmark("low_latency_video_pipeline", runs=1))
PY
```

如果实验网络无法访问 Docker Hub、Ubuntu apt 或 NVIDIA 软件源，可以复用 registry 中已验证为 `linux/amd64` 的旧 `scientific-matmul:dev` 镜像作为基础层，只刷新 `/app/src` 和 `/app/_common` 业务代码层：

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
E2E_NODE_AGENT_HOSTS="10.112.249.191 10.112.150.166 10.112.59.209" \
MATMUL_MATRIX_SIZE=1024 \
MATMUL_BATCH_COUNT=50 \
./scripts/e2e_matmul_live.sh
```

## 可视化 E2E 要求

端到端测试需要让用户看到页面过程时，Tester Agent 应使用有头浏览器或 Codex Browser 打开 `http://10.112.244.94:8182/benchmark`，逐步操作 Step 1 到 Step 4，并在关键节点保留截图或页面状态说明。

命令行 API 校验只能作为辅助，不能替代浏览器中对验收页面布局、状态变化和结果进度条的可视化确认。

## 当前限制

- 当前验收页面的 UI 四步流程已基本具备。
- 当前 `/api/baselines/run` 已改为通过目标节点 Node Agent 运行 benchmark 容器；只有显式传入 `allow_local_fallback=true` 才允许本地 fallback。
- 当前业务目标统计接口支持按 `is_benchmark=true` 过滤，验收页面只统计压测工单，避免普通业务污染成功率。
- 当前业务目标统计接口和订单列表支持按 `benchmark_run_id` 过滤，验收页面默认按当前轮次统计，避免新旧压测结果互相污染。
- 当前验收页面支持 `POST /api/orders/start-controlled-routed` 自动执行，按计算节点/GPU 槽位限流执行，并在评估后释放容器实例、保留工单证据；正式矩阵验收不再使用一次性启动全部实例作为默认口径。
- 当前业务工单中心支持按 `benchmark_run_id` 筛选验收压测工单，并提供“清理实例保留工单”和“删除工单”两类批量操作；前者用于释放容器资源并保留证据，后者用于删除废弃轮次。
- 当前视频 AI 推理 worker 已提供本地单测、benchmark mode 和镜像构建入口，并已在 `/benchmark` 页面作为扩展业务类型开放；它使用固定测试视频 + YOLOv5n ONNX 产出带框结果，CPU 仅作为开发兜底。如需远端联调，先构建 `WORKER_KIND=video WORKER_IMAGE=10.112.244.94:5000/low-latency-video WORKER_TAG=dev WORKER_PLATFORM=linux/amd64 WORKER_PUSH=1 ./scripts/build_workers.sh`，再注册对应模板和 catalog。
- 当前正式判定不依赖实时 CPU/GPU 监控。资源监控可作为演示增强项，但验收主证据是工单详情中的实例状态、实际节点/GPU 分配、业务指标评估和指标采集 JSON，避免为了演示引入额外监控系统导致链路变复杂。
- 当前验收证据链依赖管理员视角查看全局 `is_benchmark=true` 工单；普通用户仍只能查看自己的工单，管理员页面必须能列出全部压测工单并打开详情。
- 真正面向专家验收前，需要在四节点真实环境执行一次全量 baseline 和 30 任务压测，并保存浏览器截图和 JSON 报告。
- 截图建议包含 Step 1 基线表、Step 3 状态分布、工单证据链详情抽屉和 Step 4 成功率进度条。
