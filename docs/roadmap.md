# Roadmap

本文档只保留未来待办和当前风险，不记录已完成的历史过程。

## 已完成（归档）

- [x] Matmul E2E 稳定化（live E2E passing 2026-05-26）
- [x] 产品口径收敛：只保留矩阵乘法计算任务
- [x] Intent Parser LLM 化（qwen3-max + 确定性验证层）
- [x] 时区统一 Asia/Shanghai
- [x] 路由 DAG 生成 + 外部路由结果接收接口
- [x] 前端聊天 UI 重构（滚动修复、确认按钮、参数面板）
- [x] 工单列表/详情展示修复

## P0：验收双指标闭环

- [x] `/benchmark` 四步验收页面：基线、批量压测、执行、结果
- [x] 批量验收 mock 路由：仅用于 `is_benchmark=true` 工单，不替代外部路由系统
- [x] 意图解析评测脚本支持 3 次多数投票
- [x] 模板 + 槽位替换生成 ≥200 条 matmul 意图解析数据集
- [x] 真实 compute 节点远程 baseline API/UI 接入：通过 Node Agent 在目标节点执行 benchmark 容器
- [ ] 真实 compute-1/2/3 节点远程 baseline 留档：页面显示稳定基线并保存截图
- [ ] 真实四节点环境执行 30 次 matmul 任务，业务目标成功率 ≥ 90%
- [ ] 意图解析评测报告：≥200 条，3 次投票，准确率 ≥ 90%

## P1：外部路由系统联调

- [ ] 外部路由系统对接联调（扫表 routing_status=pending → 回写 placements）
- [ ] 回写 placements 后自动物化实例并按业务时间窗口调度
- [ ] GPU 编号同时落到容器运行约束和环境变量（GPU_DEVICE / CUDA_VISIBLE_DEVICES / NVIDIA_VISIBLE_DEVICES）
- [ ] mock 路由与真实路由入口在页面和文档中清晰区分

## P2：多节点部署运维

- [ ] 批量 SSH 部署 node_agent 到多台机器
- [ ] 统一镜像分发（registry 或 SSH push）
- [ ] 节点健康检查 + 自动注册
- [ ] 节点上下线管理

## P3：测试闭环与报告

- [ ] 有头浏览器 UI 验收测试（Codex Browser / Playwright headed）
- [ ] 后端数据正确性验证（工单字段、DAG 内容、placements）
- [ ] 任务实际执行验证（容器启动 → 业务指标上报 → 评估通过）
- [ ] 生成专家评审材料：截图、JSON 报告、成功率汇总、失败样本说明

## P4：调度和生命周期

- [ ] 到期自动 stop / 删除实例 E2E 验收
- [ ] `keep_after_stop` 产品语义明确化

## P5：结果与对象存储

- [ ] docker-compose 增加可选 MinIO
- [ ] 结果 URI 占位策略
