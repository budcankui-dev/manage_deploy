# 项目文档导航

本目录只把当前可执行的规范放在入口位置。历史方案、过程记录和带日期的巡检报告统一放在 `archive/`，可追溯但不作为部署、联调或验收的依据。

## 当前规范

- [架构概览](architecture/overview.md)：Task Manager、Node Agent、任务实例和网络边界。
- [端点部署与用户接入模型](architecture/端点部署与用户接入模型.md)：平台受控计算节点与用户自启端点的职责边界。
- [新业务接入交接说明](business/新业务接入交接说明.md)：接入任务所需参数和流程。
- [路由接口速查](routing/课题五-路由接口速查.md)：路由服务调用顺序、基线与资源释放闭环。
- [完整路由对接手册](routing/integration-guide.md)：字段、SQL 参考、联调与异常处理。
- [部署与运维](deployment/标准化部署与运维流程.md)：当前部署、更新、健康检查和排障流程。
- [测试与验收入口](testing/README.md)：本地、生产和端到端验证。
- [正式验收测试方案](testing/acceptance/evaluation-plan-formal.md)：意图、业务目标、步骤和截图证据。
- [稳定版回归测试](testing/acceptance/稳定版回归测试说明.md)：验收前的仓库级回归入口。

## 按职责查阅

- `architecture/`：系统边界、角色与部署模型。
- `business/`：新业务的参数契约、模态和用户端演示设计。
- `deployment/`：生产、旁路、网络、跳板和节点接入运维。
- `guides/`：面向演示人员和用户的操作手册。
- `operations/`：日常运维设计，例如端口分配。
- `routing/`：外部路由服务联调和课题五接口说明。
- `testing/`：测试入口、正式方案、回归说明和意图评测维护。
- `project/`：需求清单和后续计划。
- `presentations/`：汇报和交接材料。
- `work-items/`：进行中事项与已完成的技术记录。

## 历史材料

- `archive/`：旧版验收方案、早期设计草案、旧演示和历史巡检报告；仅用于回溯。
- 根目录中的验收 `.docx` 原件：保留原始交接材料，不修改其内容和命名。
- `assets/`、`images/`、`examples/`：文档截图、示例数据和图片资源。
