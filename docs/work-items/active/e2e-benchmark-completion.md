# Work Item: 端到端验收测试完善

Status: in_progress  
Last Updated: 2026-06-08

## 已完成

### 核心链路（matmul 端到端）
- 意图解析 → 工单创建 → 路由 → 容器部署 → 执行 → sink 上报 → 评估 → 前端展示 全链路跑通
- 修复 conversations.py flush→commit 导致 draft/order 不持久化的 bug
- 修复 routing-result 端点未注入 DATA_PROFILE/BUSINESS_OBJECTIVE 到容器 env 的 bug
- 修复 baseline lookup placements 格式解析 bug（list vs dict）
- 修复 routing_result 读取路径 bug（runtime_config.routing_result）
- MySQL schema 修复：business_objective_evaluations.target_value/business_success 允许 NULL
- matmul worker 镜像重建推送（支持 BENCHMARK_MODE、BUSINESS_OBJECTIVE env）
- 端到端验证结果：actual=2200+ GFLOPS，target=192 GFLOPS (baseline×0.8)，success=True

### 基线管理
- baseline_runner.py：容器化执行 + 本地 fallback
- baselines API：std_dev/stable 字段，BENCHMARK_PROFILES 对齐
- 前端基线表格：稳定性列（σ 值）、编辑按钮（直接修改 baseline_value）
- 本机快速测试脚本：backend/scripts/run_baseline_local.py（不依赖 Docker/节点）
- POST /api/baselines/batch-run：对所有可调度节点批量跑基线

### 批量测评
- task_orders.is_benchmark 字段区分测试/功能性工单
- matmul 模板端口改为 auto=true（范围 18800-19100），支持同节点并发多实例
- POST /api/orders/batch-benchmark：一键创建 N 个测试工单
- POST /api/orders/auto-route / batch-auto-route：内置验收路由流程（后续对接真实路由模块）

### 前端
- 验收测试独立页面（/benchmark）：四步流程（基线管理/批量测评/路由启动/成功率统计）
- 成功率统计：按任务类型展示，进度条 + 颜色（≥90% 绿/否则红）
- 业务任务中心：工单列表显示 ID（不显示名称）、任务类型全中文
- 用户工单中心：对齐管理员详情视图（tabs: 业务/路由/部署/结果）
- 节点类型：admin=管理节点，compute-1/2/3=计算+终端，both 显示双标签

### 部署
- 后端部署在 admin-server（10.112.244.94:8181）
- 前端部署在 admin-server（10.112.244.94:8182，nginx）
- MANAGER_PUBLIC_URL=http://10.112.244.94:8181，容器上报路径正确

### 视频AI推理真实验收轮次（2026-06-08）
- 远端视频 worker 镜像已重建并推送：`10.112.244.94:5000/low-latency-video:dev`。
- `compute-3` 当前 Node Agent 已恢复可达，静态 IP 为 `10.112.59.209`；路由与部署可继续使用该节点。
- 视频 baseline 已在可调度节点重跑并稳定：
  - compute-1：`frame_latency_p90_ms=9.38037 ms`，`stable=true`
  - compute-2：`frame_latency_p90_ms=9.32026 ms`，`stable=true`
- 视频 smoke：`video-smoke-20260608102101`，2 个工单均完成指标上报，2/2 达标。
- 视频 30 任务验收轮次：`video-acceptance-20260608102409`，30 个工单全部创建、内置随机路由、启动、指标上报成功；`evaluated_count=30`，`success_count=30`，业务目标成功率 `100%`。
- 验收轮次执行后已调用“清理实例保留工单”，释放远端容器和实例运行态；工单、路由结果、GPU 分配、业务指标、结果摘要仍保留用于页面回看，列表中 `instance_exists=false`。
- 抽查工单详情可见：
  - `routing_input_dag.edges[]` 包含 `data_mb` 和 `bandwidth_mbps`
  - compute placement 包含 `gpu_device: "0"`
  - evaluation.result_metadata 包含 `profile_id=video_industrial_inspection_720p`、`resolution=720p`、`fps=30`、`measured_frames=30`、`frame_latency_p90_ms`、`detections` 和带框预览图

## 待完成

- [x] 视频AI推理 worker（source/compute/sink + Dockerfile，固定视频 + YOLOv5n ONNX + 带框预览）
- [x] 视频AI推理业务基线测试：固定 resolution=720p、frame_stride=30、warmup_frames=10、measured_frames=30，每个可调度节点重复 3 次取中位数
- [x] 视频AI推理业务目标成功率：创建不少于 30 个可评价工单，统计 P90 帧推理时延是否满足 `actual_p90 <= baseline_p90 / 0.8`（即不超过基线 1.25 倍），成功率达到 90%
- [x] 视频AI推理验收页面：展示任务类型、所属模态、源节点、推理节点、目的节点、GPU 分配、有效帧数、P90 时延、基准值、阈值、是否达标、工单详情、结果摘要和带框预览图
- [ ] LLM 文本生成 worker（Ollama，source/compute/sink）
- [ ] 前端：视频上传输入 + 推理结果抽帧展示
- [ ] 前端：LLM prompt 输入 + 生成文本展示

### 中优先级
- [ ] 真实路由系统对接（接入外部路由模式）
- [ ] 实例删除时同步清理 Node Agent 容器注册（当前只删 DB 记录）
- [ ] 意图解析固定数据集继续保持 360 条口径，扩展样本覆盖多模态命名并加入模态标签

### 验收
- matmul 批量测评 30 任务成功率 ≥ 90%（端口并发已支持）
- 视频AI推理基本链路跑通：源节点按固定视频抽帧发送数据，推理节点统计有效帧时延并生成带框结果，目的节点或结果回调能够展示输出摘要
- 视频AI推理批量测评 30 任务成功率 ≥ 90%
- 意图解析准确率 ≥ 90%（需构建数据集）

## 近期执行顺序

1. 先跑通视频AI推理单任务端到端链路，确认容器启动、数据流、指标上报、GPU 分配和带框结果展示都真实可见。
2. 再补视频AI推理基线采集与批量工单成功率统计。
3. 最后优化验收测试页面展示，使矩阵计算和视频AI推理两个演示业务都能给专家展示完整证据链。

## 视频业务真实四节点最小执行序列

```bash
# 构建并推送 AMD64 视频 worker 镜像
WORKER_KIND=video \
WORKER_IMAGE=10.112.244.94:5000/low-latency-video \
WORKER_TAG=dev \
WORKER_PUSH=1 \
WORKER_PLATFORM=linux/amd64 \
./scripts/build_workers.sh

# 重建视频模板和 catalog
DEMO_BASE_URL=http://127.0.0.1:8000 \
WORKER_IMAGE=10.112.244.94:5000/low-latency-video \
WORKER_TAG=dev \
PYTHONPATH=backend \
backend/venv/bin/python backend/scripts/rebuild_video_template.py

# 登录后执行视频 baseline
curl -H "Authorization: Bearer $TOKEN" \
  -X POST http://127.0.0.1:8000/api/baselines/batch-run \
  -H 'Content-Type: application/json' \
  -d '{"task_type":"low_latency_video_pipeline","runs":3}'

# 创建 30 个视频验收工单
curl -H "Authorization: Bearer $TOKEN" \
  -X POST http://127.0.0.1:8000/api/orders/batch-benchmark \
  -H 'Content-Type: application/json' \
  -d '{"task_type":"low_latency_video_pipeline","count":30,"benchmark_run_id":"video-acceptance-001"}'

# 内置验收路由流程；正式对接时由外部路由系统写回 placements
curl -H "Authorization: Bearer $TOKEN" \
  -X POST http://127.0.0.1:8000/api/orders/batch-auto-route \
  -H 'Content-Type: application/json' \
  -d '{"benchmark_run_id":"video-acceptance-001","task_type":"low_latency_video_pipeline"}'

# 启动本轮已路由实例
curl -H "Authorization: Bearer $TOKEN" \
  -X POST http://127.0.0.1:8000/api/orders/start-all-routed \
  -H 'Content-Type: application/json' \
  -d '{"benchmark_run_id":"video-acceptance-001","task_type":"low_latency_video_pipeline"}'
```

风险记录：

- `batch-auto-route` 是验收闭环 mock，不保证选中有 GPU 的 compute 节点；真实验收和外部路由对接应在 compute placement 中显式写入 `gpu_device: "0"` 或 `gpu_indices`。
- 视频 worker 当前是固定视频 + YOLOv5n ONNX 推理，业务目标用 `frame_latency_p90_ms <= baseline / 0.8` 判定，即时延不超过节点同 profile 基线的 1.25 倍。该 25% 裕量用于覆盖容器化运行、网络转发和系统调度波动，不用于容忍同一 GPU 多任务争用；早期放宽口径已废弃。
- 30 个任务并发会占用较多自动端口和容器 writable layer，跑新轮次前应使用“清理实例保留工单”释放远端容器，再保留工单证据用于回看。
