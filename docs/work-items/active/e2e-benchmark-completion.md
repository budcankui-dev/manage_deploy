# Work Item: 端到端验收测试完善

Status: in_progress  
Last Updated: 2026-06-02

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

### 批量压测
- task_orders.is_benchmark 字段区分测试/功能性工单
- matmul 模板端口改为 auto=true（范围 18800-19100），支持同节点并发多实例
- POST /api/orders/batch-benchmark：一键创建 N 个测试工单
- POST /api/orders/auto-route / batch-auto-route：mock 随机路由（后续对接真实路由模块）

### 前端
- 验收测试独立页面（/benchmark）：四步流程（基线管理/批量压测/路由启动/成功率统计）
- 成功率统计：按任务类型展示，进度条 + 颜色（≥90% 绿/否则红）
- 业务任务中心：工单列表显示 ID（不显示名称）、任务类型全中文
- 用户工单中心：对齐管理员详情视图（tabs: 业务/路由/部署/结果）
- 节点类型：admin=管理节点，compute-1/2/3=计算+终端，both 显示双标签

### 部署
- 后端部署在 admin-server（10.112.244.94:8181）
- 前端部署在 admin-server（10.112.244.94:8182，nginx）
- MANAGER_PUBLIC_URL=http://10.112.244.94:8181，容器上报路径正确

## 待完成

### 高优先级
- [ ] 视频推理 worker（source/compute/sink + Dockerfile，YOLO）
- [ ] LLM 文本生成 worker（Ollama，source/compute/sink）
- [ ] 前端：视频上传输入 + 推理结果抽帧展示
- [ ] 前端：LLM prompt 输入 + 生成文本展示

### 中优先级
- [ ] 真实路由系统对接（替换 mock 随机路由）
- [ ] 实例删除时同步清理 Node Agent 容器注册（当前只删 DB 记录）
- [ ] 意图解析数据集扩展到 200 条

### 验收
- matmul 批量压测 30 任务成功率 ≥ 90%（端口并发已支持）
- 意图解析准确率 ≥ 90%（需构建数据集）
