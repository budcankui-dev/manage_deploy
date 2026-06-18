# Base Agent Prompt

你是 `manage_deploy` 项目的协作 agent。所有角色都必须遵守本文件。

## 必读

开始前阅读：

- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/business-objective-success-rate-design.md`
- 当前 work item：`docs/work-items/active/*.md`

按任务需要阅读：

- `docs/routing-system-integration-guide.md`
- `docs/worker-data-io-design.md`
- `docs/deployment/测试部署机器清单.md`

## 项目现状

- 唯一业务类型：矩阵乘法计算任务 (`high_throughput_matmul`)
- 意图解析：qwen3-max + 确定性验证层 + 节点名校验
- 时区：全部使用 Asia/Shanghai
- DAG 拓扑：source → compute → sink（三节点）
- 路由：外部系统扫 `routing_status=pending`，回写 placements
- 前端：Vue3 + Element Plus，聊天式交互

## 工作规则

- 先确认当前 work item 的目标、非目标和验收标准。
- 不扩大任务范围；发现新问题时记录到 work item 的 `Open Risks`。
- 运行过的命令必须记录命令和结论。
- 不覆盖其他人的未提交改动。
- 不新增业务类型（当前只做矩阵乘法）。
- 不使用 UTC 时间，统一 Asia/Shanghai。
- 不让 LLM 自由发挥参数——所有业务参数必须通过确定性验证层。
- 业务数据必须沿 source → compute → sink 网络链路流转。

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
