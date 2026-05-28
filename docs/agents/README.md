# Agent 协作手册

本目录保存子 agent 的固定提示词。主会话负责产品与架构决策，子 agent 负责执行。

## 角色体系（5 角色）

```text
Architect → Coder → Reviewer → Tester → Deployer
```

| 角色 | 文件 | 适用场景 |
|------|------|----------|
| Base | `base.md` | 所有 agent 必读的通用规则 |
| Architect | `architect.md` | 需求分析、架构决策、任务拆分、验收标准 |
| Coder | `coder.md` | 按 work item 写代码或脚本 |
| Reviewer | `reviewer.md` | 代码审查，找 bug 和回归风险 |
| Tester | `tester.md` | UI → API → 执行 → 指标，完整闭环验证 |
| Deployer | `deployer.md` | SSH 多节点运维、镜像分发、节点注册 |

## 调用顺序

**新功能开发：**
```text
主会话 → Architect → Coder → Reviewer → Tester
```

**部署上线：**
```text
主会话 → Deployer → Tester（验证闭环）
```

**Bug 修复：**
```text
主会话 → Tester（复现）→ Coder（修复）→ Reviewer → Tester（复验）
```

## Work Item 原则

`docs/work-items/active/*.md` 是 agent 之间的交接协议：
- 子 agent 会话短生命周期，不能依赖聊天记忆传递状态
- 不同角色需要同一份 Goal / Non-goals / Acceptance Criteria
- 测试命令、失败原因、剩余风险必须落文件

## 调用方式

```bash
claude --agent architect
claude --agent coder
claude --agent reviewer
claude --agent tester
claude --agent deployer
```

或在会话中：
```text
Use the coder subagent to implement the active work item.
Use the tester subagent to verify the deployment loop.
Use the deployer subagent to set up node agents on all machines.
```
