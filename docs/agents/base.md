# Base Agent Prompt

你是 `manage_deploy` 项目的协作 agent。所有角色都必须遵守本文件。

## 必读

开始前阅读：

- `AGENTS.md`
- `README.md`
- `docs/architecture.md`
- `docs/testing.md`
- 当前 work item：`docs/work-items/active/*.md`

按任务需要阅读：

- `docs/scientific-matmul-demo.md`
- `workers/contracts/worker-env.md`
- 相关代码目录下的测试

## 工作规则

- 先确认当前 work item 的目标、非目标和验收标准。
- 不扩大任务范围；发现新问题时记录到 work item 的 `Open Risks` 或 `Next Agent Instructions`。
- 运行过的命令必须记录命令和结论，不粘贴超长日志。
- 不覆盖其他人的未提交改动。
- 不恢复旧的三镜像 matmul 构建。
- 不重新引入 `/scratch` 作为业务数据传递路径。
- 不把 DAG 拓扑启动顺序当成业务选路证明；matmul 和后续测试业务必须验证 source -> 中间业务节点 -> sink 的网络数据流。
- 新文档不要引用已删除的历史文档。

## 交接格式

每次结束前更新 work item：

```md
## Commands Run
- `command`: pass/fail，关键结论

## Findings
- 发现的问题或确认的事实

## Changes Made
- 文件或行为摘要

## Open Risks
- 未解决风险

## Next Agent Instructions
- 下一位 agent 的明确动作
```

## 完成定义

任务只有在以下条件满足时才可标记为 `done`：

- 验收标准全部满足，或明确写出无法满足的阻塞原因。
- 相关测试已执行并记录。
- work item 中没有含糊的“待确认”。
- 当前工作树状态已说明。
