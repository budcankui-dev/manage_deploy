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

## P0：意图解析 → 路由 → 部署闭环

- [ ] 外部路由系统对接联调（扫表 routing_status=pending → 回写 placements）
- [ ] 收到路由结果后自动物化实例（materialize_after_routing）
- [ ] GPU 编号落到容器环境变量（NVIDIA_VISIBLE_DEVICES）
- [ ] 业务目标成功率采集（见 `docs/business-objective-success-rate-design.md`）

## P1：多节点部署运维

- [ ] 批量 SSH 部署 node_agent 到多台机器
- [ ] 统一镜像分发（registry 或 SSH push）
- [ ] 节点健康检查 + 自动注册
- [ ] 节点上下线管理

## P2：测试闭环

- [ ] 浏览器 UI 功能测试（Playwright E2E）
- [ ] 后端数据正确性验证（工单字段、DAG 内容）
- [ ] 任务实际执行验证（容器启动 → 业务指标上报 → 评估通过）
- [ ] LLM 意图解析准确率回归测试

## P3：调度和生命周期

- [ ] 到期自动 stop / 删除实例 E2E 验收
- [ ] `keep_after_stop` 产品语义明确化

## P4：结果与对象存储

- [ ] docker-compose 增加可选 MinIO
- [ ] 结果 URI 占位策略
