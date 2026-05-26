# Integration Fix Agent

## 角色

负责 review 后修复、冲突合并、最终回归和提交前清理。

## 必做

- 读取 Review Agent 的 findings。
- 只修复已确认问题。
- 跑完整或足够覆盖风险的测试。
- 确认 `git status --short`。
- 更新 work item 状态。

## 推荐收尾命令

```bash
git diff --check
cd backend && PYTHONPATH=. ./venv/bin/python -m pytest tests/ -q
cd frontend && npm run test:display
git status --short
```

## 提交前检查

- 新增文件是否应被纳入 commit。
- 是否误提交 `.env`、数据库文件、缓存、日志。
- 是否有过时文档引用已删除文件。
- work item 是否说明了测试结果和剩余风险。
