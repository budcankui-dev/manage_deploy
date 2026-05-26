# Roadmap

本文档只保留未来待办和当前风险，不记录已完成的历史过程。

## P0：跑通并固化 matmul E2E

- [ ] 诊断 `GET /api/nodes` 500 的根因。
- [ ] 固化远程 AMD64 worker/node_agent 镜像构建、推送、拉取流程。
- [ ] 跑通真实 4 节点 `./scripts/e2e_matmul_live.sh`。
- [ ] 验证 source / compute / sink 节点均写入 `ports` 和 `port_values`。
- [ ] 验证同机重复部署触发端口冲突。
- [ ] 将 E2E 结果写入 `docs/work-items/active/matmul-e2e-stabilization.md`。

## P1：产品口径收敛

- [ ] 当前用户可见演示只保留“科学计算矩阵乘法演示”。
- [ ] 决定 intent parser 对视频/LLM 请求的策略：保留未来能力，还是提示当前仅支持 matmul。
- [ ] 清理前端任务类型列表中的未来能力展示，避免用户误以为可部署。

## P2：调度和生命周期

- [ ] 修复 APScheduler timezone 与 naive UTC 时间混用风险。
- [ ] 为到期自动 stop / 删除实例增加 E2E 验收。
- [ ] 明确 `keep_after_stop` 在业务工单中心的产品语义。

## P3：结果与对象存储

- [ ] docker-compose 增加可选 MinIO。
- [ ] 明确无 MinIO 时的结果 URI 占位策略。
- [ ] 结果 Tab 支持更稳定的 result metadata 展示。

## P4：真实路由和意图能力

- [ ] 将当前 mock/rule intent parser 替换为可插拔 workflow。
- [ ] 路由请求支持真实外部路由服务。
- [ ] IntentChat 增加更清晰的 pending / failed / retry 状态。

## P5：多 agent 工作流

- [x] 建立 `docs/agents/` 基础提示词。
- [x] 建立 `docs/work-items/` 文件交接机制。
- [ ] 用一个真实任务验证 Product Architect -> Implementation -> E2E -> Review -> Integration Fix 的闭环。
