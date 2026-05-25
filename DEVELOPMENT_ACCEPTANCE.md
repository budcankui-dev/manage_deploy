# 开发联调与验收规范

本文档总结本项目已经踩到的坑、修复方式，以及后续开发新功能时推荐遵守的流程。目标是两件事：

1. 尽量在设计和开发阶段就规避同类问题。
2. 即使遇到边界情况或线上 bug，也能快速定位并迭代修正。

## 1. 当前推荐的开发基线

### 1.1 进程与环境

- 后端、前端、node agent 一律使用各自目录下的虚拟环境或本地依赖启动，不使用全局安装。
- 调试前先确认没有旧的 Docker Compose 容器或旧的 `uvicorn` / `vite` 进程占住端口。
- 当前本地联调推荐端口：
  - 前端：`127.0.0.1:5173`
  - 后端：`127.0.0.1:8000`
  - node agent：`127.0.0.1:8001`

### 1.2 管理地址配置

- Manager 运行在宿主机时，数据库里的节点地址应优先使用 `agent_address`。
- 本地开发时 `agent_address` 推荐配置成 `http://127.0.0.1:8001`。
- 不要让宿主机上的 Manager 去访问 Docker bridge 内部地址如 `172.20.x.x`，这会导致 UI 看起来正常，但实际启动/停止/日志都失败。

### 1.2.1 开发期数据面（当前）

- **控制面**：MySQL、MinIO、Manager、Agent 均走 IPv4（如 `127.0.0.1`）。
- **数据面（开发）**：`business_ip` 与管理面同源（seed 默认 `127.0.0.1`），可不填 `business_ipv6`；`.env` 设 `PREFER_BUSINESS_IPV6=false`。
- **数据面（验收）**：节点配置 `business_ipv6`（如 `2001:db8:1::/64`），`PREFER_BUSINESS_IPV6=true`，跑 `scripts/verify_macro_port_e2e.py`。

### 1.3 数据库

- 功能联调默认可继续使用开发 MySQL。
- 每次后端 schema 或 `init_db()` 逻辑更新后，要确认当前运行的后端进程已重启并加载最新代码。
- 若页面“创建成功但看不到数据”，不要先怀疑前端，先确认：
  - 请求是否打到了当前这套后端
  - 当前后端是否连的是正确数据库
  - 表结构是否已同步到最新版本

### 1.4 默认账号

- 后端 `init_db()` 启动时自动确保存在：
  - `admin` / `admin`（管理员）
  - `user` / `user`（普通用户）
- 已存在的用户名不会重复创建；无需再点前端 bootstrap。

## 2. 已踩过的坑与处理经验

### 2.1 删除实例只删数据库，不删 Docker 容器

现象：

- 页面提示“删除成功”。
- 实例记录消失，但 Docker Desktop 里容器还在。
- 某些容器甚至持续 `restart`。

根因：

- 旧实现只删除 `task_instances` 记录，没有走 node agent 清理容器。

修复：

- node agent 新增容器删除接口。
- 后端实例删除时，会先遍历实例节点，逐个删除容器，再删除数据库记录。
- 批量删除复用了同样逻辑。

规范：

- “删除实例”的验收必须同时检查：
  - 实例列表消失
  - 数据库记录消失
  - 对应容器也消失

### 2.2 停止只能停 running，停不掉 restarting / created / paused

现象：

- Docker 异常状态容器无法通过系统停止。
- 失败任务删不干净。

根因：

- 旧的 `stop_container()` 只处理 `running` 状态。

修复：

- 停止和删除逻辑统一兼容 `running` / `restarting` / `paused`。
- 删除时如果常规 stop 不成功，会强制 kill + remove。

规范：

- 停止和删除都不能只按“正常 running”设计。
- 任何与 Docker 生命周期交互的逻辑，都要覆盖：
  - `running`
  - `restarting`
  - `created`
  - `paused`
  - `exited`

### 2.3 修改实例参数后再次启动，旧容器沿用旧配置

现象：

- 实例已经编辑了端口、镜像、环境变量，但重新启动后表现还是旧参数。

根因：

- 旧逻辑发现容器存在时，非运行态直接 `start()` 原容器，而不是按新配置重建。

修复：

- 对非运行中的旧容器，重新启动前会先移除，再按最新参数创建。

规范：

- 只要实例级运行参数允许修改，就不能复用旧容器配置。
- 重启或再次启动时，要明确区分“启动旧容器”和“按最新配置重建容器”。

### 2.4 前端看不到实例列表，但接口其实有数据

现象：

- `GET /api/instances` 有数据。
- 页面列表为空。

根因：

- Pinia store 状态被直接解构，丢失响应性。

修复：

- 使用 `storeToRefs()` 保持响应式引用。

规范：

- Vue3 + Pinia 页面中，store 的可响应状态统一走 `storeToRefs()`。
- 如果接口有数据、页面无数据，先查响应式绑定，再查接口本身。

### 2.5 时间显示总是慢 8 小时

现象：

- 刚创建的实例显示“8 小时前”。

根因：

- 后端返回 UTC 时间，前端直接按本地时间字符串解析和渲染。

修复：

- 前端统一通过 `dayjs.utc(...).local()` 或 `utcOffset(8)` 处理。

规范：

- API 时间字段统一视为 UTC。
- UI 展示层再按 `UTC+8` 或用户时区转换。

### 2.6 端口冲突直到 Docker 真启动时才暴露

现象：

- 创建或启动时，直到 Docker 启动容器才报 `port is already allocated`。

修复：

- node agent 新增端口预检查接口。
- 后端启动前增加强制预检查。
- 前端“立即部署”创建前先做一次预检查；如有 warning 先提示，如有 conflict 直接阻止。

限制：

- 对 `bridge + 显式端口映射` 预检查较可靠。
- 对 `host` 网络模式，无法完全静态判断镜像内部真实监听端口，只能给 warning，不能做到 100% 阻断。

规范：

- 新功能如果涉及资源抢占，优先做“提交前预检查 + 执行前兜底校验”的双层校验。

### 2.7 DAG 失败回滚只 stop 不 delete，导致 Exited 容器堆积

现象：

- Docker Desktop 里出现大量已停止的 `manage-deploy/matmul-*` 容器。
- 容器命名形如 `{instance_id}_{node_id}`，同一前缀（instance_id）下往往有 1～3 个 Exited 记录。
- 反复跑 E2E 或调试失败后，容器数量线性增长，但实例列表里多为 `failed` 状态。

根因：

- 旧版 `_rollback_started_nodes` 只对 `started_nodes` 中标记为已启动、且状态为 `READY` 的节点调用 `stop_node`。
- **失败节点**在 `failed_nodes` 集合中，但不在回滚范围。
- 更关键的是：若**首节点**（如 source）在健康检查阶段失败，容器已创建但尚未进入 `READY`，此时 `started_nodes` 可能为空——旧逻辑**完全不会清理**任何容器。
- 配合 `restart_policy: no`，容器 stop 后停留在 `Exited`，不会自动消失。

修复（`backend/services/dag_executor.py`）：

- 失败回滚改为对「已启动节点 ∪ 失败节点」统一调用 `remove_node`（经 node agent delete 容器）。
- 单元测试：`test_rollback_removes_started_and_failed_nodes`。
- 联调脚本：`scripts/verify_rollback_cleanup.sh`（故意配置不可能通过的健康检查，断言实例 `failed` 且 Docker 无 `{instance_id}_*` 残留）。

规范：

- **`stop` ≠ `delete`**：编排系统的「回滚 / 清理」语义应是 remove，而不是仅 stop 留 Exited。
- 回滚集合必须显式包含 `failed_nodes`，不能只看 `started_nodes`。
- 任何 Docker 生命周期变更的验收，都要在 Docker Desktop / `docker ps -a` 侧确认，不能只看 DB 或 API 状态。
- E2E 脚本反复跑之前，应清理旧测试实例；历史 Exited 容器可一次性 `docker rm` 或走工作节点页「孤儿容器」巡检。

一次性清理历史 matmul 残留示例：

```bash
docker ps -a --filter "ancestor=manage-deploy/matmul-source:dev" -q | xargs docker rm
docker ps -a --filter "ancestor=manage-deploy/matmul-compute:dev" -q | xargs docker rm
docker ps -a --filter "ancestor=manage-deploy/matmul-sink:dev" -q | xargs docker rm
```

验证回滚清理：

```bash
# 需 backend :8000 + node agent :8001 已启动
./scripts/verify_rollback_cleanup.sh
```

### 2.8 high_throughput_matmul 业务 E2E 联调经验

现象与坑：

| 问题 | 表现 | 处理 |
|------|------|------|
| Seed 与线后端不一致 | seed 后 API 查不到节点/模板 | seed 默认 HTTP 调 `SEED_BASE_URL`（如 `http://127.0.0.1:8000`），避免 ASGI 直连另一套库 |
| `auto_start: true` 阻塞创建接口 | curl 创建 business-task 长时间无响应 | E2E 改为 `auto_start: false`，创建后再 `POST .../start` |
| 容器内访问 Manager | sink 上报 metrics 失败 | macOS Docker Desktop 用 `host.docker.internal:8000`，配置 `MANAGER_PUBLIC_URL` |
| `PLATFORM_SCRATCH` 被覆盖 | scratch 目录无 `job.json` | business-task 创建路径显式注入 `PLATFORM_SCRATCH=1` |
| 开发期 IPv6 未就绪 | PEER URL 不可达 | 开发默认 `PREFER_BUSINESS_IPV6=false`，节点 `business_ip` 与管理面同源 |
| sink metrics 偶发 500 | 健康检查失败 → 实例 failed | reporter 对 500 重试；根因仍待查（可能与 DAG 并发写库有关） |
| 三节点 ≠ 一个长期运行容器 | Docker 里多个 matmul 镜像 | 一个 Dockerfile 三个 target（source/compute/sink），每实例各起 3 个容器，属正常 |

Worker 构建与 E2E：

```bash
./scripts/build_workers.sh
SEED_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=backend backend/venv/bin/python backend/scripts/seed_demo_data.py
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
```

规范：

- 业务容器开发在本仓 `workers/` 下，平台只负责 env 注入、DAG、metrics 评估；**不要**期望跨任务共享同一业务镜像。
- Live E2E 应用较小矩阵（如 64×1）缩短等待；完整性能验收另开 profile。
- 成功跑完的实例在 `restart_policy: no` 下仍可能留下 Exited 容器——**正常 stop / 成功完成路径**的容器清理尚未统一，删除实例 API 会删容器；失败路径已由 §2.7 修复。
- **2026-05-24**：`e2e_matmul_live.sh` 连续 3 次通过；默认矩阵 64×1；metrics 上报增加 evaluation 幂等，reporter 对 5xx 重试。

### 2.9 批量删除/停止前端超时，删除接口 500

现象：

- 多个 **running** 的 matmul 实例在前端批量删除、停止时 **30s 超时**。
- 后端 DELETE 曾返回 **500**（`Session is already flushing`）。

根因：

1. node agent `get_container()` 全量 `list` 容器，慢。
2. `remove_container` 对 running 容器 `stop(timeout=30)`，sink 长期运行，批量操作累计超时。
3. 并行 `asyncio.gather` + 同一 AsyncSession 并发 flush 导致 500。

修复：

- `containers.get(name)`；删除用 **kill + remove**；停止 **5s 后 kill**。
- 清理顺序执行；删库不因单容器失败而整体失败。
- 前端批量/启停/删除 timeout **180s**。
- 验收：`./scripts/test_instance_lifecycle_api.sh`

## 3. 以后开发新功能的推荐流程

### 3.1 设计阶段

每个新功能在开始写代码前，至少回答这几个问题：

1. 这个功能会不会影响 Docker 生命周期？
2. 它是否会改动实例级运行参数？
3. 失败时是否会留下部分状态？
4. 页面提示成功时，后端和 Docker 的真实状态是否一致？
5. 是否存在调度、批量操作、并发点击的边界？

### 3.2 实现阶段

- 能在后端保证一致性的规则，不只放前端。
- 前端限制是体验优化，后端校验才是最终约束。
- 对实例、节点、容器三个层面的状态要分开看，不要只看一个。
- 任何“成功”提示，必须以真实副作用完成为准。

### 3.3 联调阶段

每做完一个与部署有关的功能，至少跑这 4 类检查：

1. 数据库检查：记录是否正确创建/更新/删除。
2. API 检查：接口返回是否与预期一致。
3. Docker 检查：容器是否真正创建/停止/删除。
4. UI 检查：页面状态、按钮、提示语是否与真实后端状态一致。

## 4. 功能验收清单

### 4.1 任务实例

- 创建待启动实例后，列表中能立即看到。
- 立即部署实例时：
  - 正常参数可成功启动。
  - 明确端口冲突能在预检查或启动阶段给出清晰错误。
- 停止运行中实例后：
  - 页面状态为“已停止”
  - Docker 容器不再运行
- 删除实例后：
  - 页面列表消失
  - 后端接口查不到
  - Docker 容器彻底消失
- 批量删除/批量停止/批量启动：
  - 成功数、失败数要准确
  - 局部失败时页面提示要保留失败原因

### 4.2 编辑实例

- 非运行态可修改实例级运行参数。
- 运行态仅允许修改安全字段（当前为名称）。
- 修改后重新启动，应以新参数生效，而不是沿用旧容器。

### 4.3 调度

- 定时创建时，开始/结束时间展示正确。
- 删除已调度实例后，对应调度任务也应取消。
- 手动启动已调度实例时，需明确是否允许立即执行，并保持调度行为不混乱。

## 5. 推荐的端到端验收流程

每次提交部署相关改动后，建议按以下顺序验收：

1. 启动前端、后端、node agent，确认都是当前代码。
2. 清理旧测试实例和残留测试容器。
3. 测正常路径：
   - 创建实例
   - 启动实例
   - 查看详情/日志
   - 停止实例
   - 删除实例
4. 测异常路径：
   - 端口冲突
   - 不存在节点
   - 运行态误编辑
   - 批量操作部分失败
   - **DAG 失败回滚**（`./scripts/verify_rollback_cleanup.sh`）
5. 最后再次确认：
   - 数据库无脏数据
   - Docker 无残留测试容器
   - 页面状态与 API 返回一致

## 6. 当前已验证通过的关键场景

本轮已实际验证通过：

- 运行中实例直接删除，数据库和 Docker 一起清理。
- 批量删除多个实例。
- 显式宿主机端口冲突时，实例进入 `failed`，错误信息清晰。
- 失败实例删除后，残留 `Created` 容器也会被清理。
- 运行中实例停止后，容器退出，实例状态正确更新。
- 时间展示按 `UTC+8` 正确显示，不再出现“刚创建却显示 8 小时前”。
- **DAG 失败回滚**：故意健康检查失败后，Docker 无 `{instance_id}_*` 残留（`verify_rollback_cleanup.sh` 通过）。

## 7. 后续仍建议继续增强的点

- `host` 网络模式的更强预检查能力。
- 统一的事件日志与错误码体系，便于 UI 精准提示。
- 服务端分页/筛选，避免列表全量加载。
- 更完整的自动化 E2E 用例，把当前手工验收流程固化下来。
- **任务正常完成 / 手动 stop 路径**：统一 remove 或提供「清理 Exited 容器」策略，避免成功 run 也堆积 Exited。
- **sink metrics 500**：查明并发上报时的后端异常并稳定 E2E。

## 8. 孤儿容器巡检约定

- “孤儿容器”仅指本系统命名规则 `instanceId_nodeId` 的容器。
- 若数据库中已不存在对应 `task_instance_nodes.container_name`，则视为孤儿。
- 巡检和清理入口放在“工作节点”页，按节点执行，避免误清理非本系统容器。
- 适用场景：
  - 手工删库或异常并发导致容器残留
  - 旧版本只删数据库未删 Docker 的历史遗留
  - 调试阶段中断流程后留下的脏容器
  - **旧版 DAG 失败回滚只 stop 不 delete** 的历史遗留（见 §2.7）

## 9. 运行时能力验收（macro / port / IPv6）

### 9.0 自动化

```bash
cd backend && PYTHONPATH=. ./venv/bin/python -m pytest tests/ -q
cd frontend && npm run build
```

当前基线（2026-05-24）：**41 passed**（含 DAG 回滚、init_db 默认用户、metrics 幂等、matmul E2E 联调相关测试）。

脚本：`python scripts/verify_macro_port_e2e.py`（需 backend + agent + `alpine:latest`）。

### 9.1 模板与实例

- [x] 模板支持 `macro_defs`、节点 `port_defs`
- [x] 实例支持 `macro_values`、`port_values`
- [x] 模板名称去重（API 409）
- [x] 从模板创建实例必须走完整表单（禁止仅填名称裸创建）

### 9.2 部署与 PEER 环境变量

- [ ] 本地 `alpine` 镜像下 preflight + start 全链路脚本通过
- [ ] compute 容器 env 含 `PEER_*_URL_*`（业务 IPv6 优先）、`DB_URL` 等宏变量

## 10. 意图与认证（骨架，下阶段启用路由守卫）

后端已具备：

- `POST /api/auth/register`（普通用户）
- `intent_workflow` 抽象层（当前为规则 parser）
- `Conversation.task_id` 与 API 字段 `task_id`

前端已具备（**本轮不启用路由守卫**，登录/对话页仅作占位）：

- `auth` store、`/login`、`/register`
- 三栏 `IntentChatView` 原型
- 开发绕过：`backend AUTH_BYPASS` 或 `frontend VITE_AUTH_BYPASS`

下阶段再启用：`router.beforeEach` 角色分流、admin 侧栏隐藏对话入口。

## 11. 业务任务 E2E 验收清单

### 11.1 L1 API 集成（自动化）

```bash
cd backend && PYTHONPATH=. ./venv/bin/python -m pytest tests/ -q
```

已通过（2026-05-24）：

- [x] auth bootstrap / login
- [x] business-tasks 创建 instance + metric 上报触发 evaluation
- [x] business-tasks summary 成功率统计
- [x] conversations 解析 → confirm → routing callback → submit
- [x] 不合理时延目标 rejected

### 11.2 L2 部署链路（半自动）

前置：backend + node_agent 已启动，已执行 seed 脚本。

1. [x] `seed_demo_data.py` 创建节点、模板、catalog
2. [x] `e2e_matmul_live.sh` / 业务任务 API 返回 instance_id
3. [x] metric 上报后 evaluation 中 `business_success` 正确
4. [x] Admin 页 `/business-tasks` 可查看 summary 与详情「结果」Tab

### 11.2.1 L2 matmul 实容器 E2E

前置：worker 镜像已 build（`./scripts/build_workers.sh`），MinIO 可选（`127.0.0.1:9000`）。

```bash
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
./scripts/verify_rollback_cleanup.sh   # 失败回滚无容器残留
```

详见 §2.7、§2.8。`e2e_matmul_live.sh` 已稳定跑通（默认 64×1 矩阵，约 7s）。

```bash
WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh
E2E_DELETE_INSTANCE=1 WORKER_SKIP_BUILD=1 ./scripts/e2e_matmul_live.sh   # 跑完删实例
MATMUL_MATRIX_SIZE=256 MATMUL_BATCH_COUNT=2 ./scripts/e2e_matmul_live.sh  # 大矩阵
```

### 11.3 意图对话链路（下阶段，与路由守卫一并启用）

1. [ ] 路由守卫 + 角色分流后，user 进入 `/intent-chat`
2. [x] 发送自然语言，右侧展示解析 draft（API + 页面原型已有）
3. [ ] 确认意图 → 请求路由 → `mock_router_callback.sh` 回调
4. [x] 确认提交后产生 TaskOrder + instance；Admin 提交后跳转 `/business-tasks?orderId=`

说明：MinIO 当前为 URI 入库，实际上传由 C 节点负责。
