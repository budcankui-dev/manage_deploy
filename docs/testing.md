# 测试与验收

本文档是唯一的测试入口。新增功能、修复和 agent 交接都应记录实际执行过的命令和结果。

系统页面操作和截图说明见 [智联计算系统使用说明书](智联计算系统使用说明书.md)。

## 基础服务

远程测试部署机器见 [测试部署机器清单](deployment/测试部署机器清单.md)。部署、同步、重启和健康检查流程见 [标准化部署与运维流程](deployment/标准化部署与运维流程.md)。该清单不记录密码；凭据只应保存在本地 ignored 文件或密码管理器中。

启动 Task Manager：

```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

启动 Node Agent：

```bash
cd node_agent
source venv/bin/activate
uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

健康检查：

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8000/api/nodes | python3 -m json.tool
```

## 自动化测试

稳定版候选发布前，优先执行 [稳定版回归测试说明](稳定版回归测试说明.md) 中的仓库级回归入口：

```bash
cd /Users/yanjia/codes/manage_deploy
./scripts/stable_regression.sh
```

该入口会串联前端构建、展示逻辑单测、UI 截图巡检、Playwright 主流程 E2E 和后端关键 API 单测，并把截图与日志输出到 `reports/stable-regression/`。小修可以只跑相关测试；准备稳定版、验收演示或迁移真实网络前必须跑全量回归。

验收网络切换或拓扑变更前，还必须按 [验收网络互通检测与 IP 更新流程](deployment/验收网络互通检测与IP更新流程.md) 检查管理面和数据面的两两互通，并确认 `ops/inventory/topology_nodes.json` 与平台 `nodes` 表一致。

### 脚本运行环境约束

后端服务、评测脚本和报告重评分脚本都依赖后端虚拟环境与仓库相对路径。执行这类脚本时遵守以下约定：

- 本地执行后端测试或导入 `services.*` 模块时，先进入 `backend` 目录，并使用 `PYTHONPATH=. ./venv/bin/python` 或 `PYTHONPATH=. ./venv/bin/pytest`。
- 不要在仓库根目录用系统 `python3` 直接执行会导入后端模块的脚本；容易缺少 `httpx` 等依赖，也可能让报告、数据集相对路径不一致。
- 如果必须从仓库根目录读取文件，再调用后端服务函数，优先写成 `cd backend && PYTHONPATH=. ./venv/bin/python - <<'PY' ... PY`，文件路径使用绝对路径。
- 管理节点执行后端脚本时，进入 `/home/bupt/manage_deploy/backend`，使用 `PYTHONPATH=. /home/bupt/miniconda3/bin/python3.13`。

后端：

```bash
cd backend
PYTHONPATH=. ./venv/bin/python -m pytest tests/ -q
```

前端展示逻辑：

```bash
cd frontend
npm run test:display
```

前端 UI 排版巡检：

```bash
cd frontend
npm run ui:smoke
```

`ui:smoke` 会登录普通用户和管理员，访问用户对话、业务工单、业务测评、拓扑节点、任务模板、系统设置、意图评测等主要页面，自动截图并检查横向溢出、中文标签被挤成竖排、明显超出视口等问题。截图和报告默认输出到 `frontend/output/ui-smoke/`。如需检查线上部署：

```bash
cd frontend
UI_SMOKE_BASE_URL=http://10.112.244.94:8182 npm run ui:smoke
```

前端浏览器 E2E：

```bash
cd frontend
npm run test:e2e
```

可视化有头浏览器 E2E：

```bash
cd frontend
npm run test:e2e:headed
```

如果本机未安装 Playwright 浏览器，先运行：

```bash
cd frontend
npx playwright install chromium
```

如果本机已有 Chrome，也可以避免下载 Playwright Chromium：

```bash
cd frontend
PLAYWRIGHT_CHANNEL=chrome npm run test:e2e:headed
```

可选触发 UI 上的“一键演示矩阵乘法”按钮：

```bash
cd frontend
E2E_TRIGGER_MATMUL_DEMO=1 npm run test:e2e:headed
```

用户端意图对话 E2E 覆盖两类演示业务，并与业务测评域分开理解：

- 用户端接入演示：自然语言输入 -> 参数完整 -> 确认生成工单。系统设置为“系统自动分配”时会直接完成 compute 节点分配并生成接入信息；设置为“外部路由系统”时进入待分配，等待路由系统回写。平台默认只部署 compute，source/sink 是用户自行接入的外部端点。
- 自动化测评域：`/benchmark` 为批量业务目标成功率测评，source/compute/sink 都由平台部署，便于稳定复现指标。

该 E2E 可在系统设置页启用开发调试路由流程，只验证用户端链路和 compute 物化能力；正式路由系统仍通过 `/api/routing-orders/{order_id}/result` 回写 placements。

Worker 和脚本语法：

```bash
python3 -m py_compile \
  backend/scripts/rebuild_matmul_template.py \
  backend/scripts/seed_demo_data.py \
  workers/_common/http_server.py \
  workers/high-throughput-matmul/src/*.py
```

格式/空白：

```bash
git diff --check
```

## 科学计算矩阵乘法 E2E

正式业务目标成功率验收以 [/benchmark](benchmark-test-plan.md) 为主入口。命令行 E2E 用于验证镜像、Node Agent、端口、网络通信和指标上报链路；专家演示时必须结合浏览器页面查看基线、测试工单列表、任务工单详情和最终成功率。

构建 worker 镜像：

```bash
./scripts/build_workers.sh
```

准备演示数据：脚本通过 `DATABASE_URL`（或 `MYSQL_HOST` / `MYSQL_USER` /
`MYSQL_PASSWORD` / `MYSQL_PORT` / `MYSQL_DATABASE`）读取 MySQL 凭据，并要求
`nodes` 表里至少已有 `compute-1/2/3` 三个计算节点；当前完整拓扑还应包含 `h1-h13` 终端节点。用户端源/目的槽位优先使用 `h1-h13`，业务测评中的 compute 候选来自计算节点。

```bash
DEMO_BASE_URL=http://127.0.0.1:8000 \
PYTHONPATH=backend \
backend/venv/bin/python backend/scripts/rebuild_matmul_template.py
```

运行 live E2E：

```bash
./scripts/e2e_matmul_live.sh
```

可选参数：

```bash
MATMUL_MATRIX_SIZE=256 ./scripts/e2e_matmul_live.sh
E2E_DELETE_INSTANCE=1 ./scripts/e2e_matmul_live.sh
```

`WORKER_SKIP_BUILD=1` 只允许在已经确认目标节点可拉取正确 tag、正确 registry、正确 CPU 架构的镜像后使用。远程 AMD64 节点测试前必须验证镜像是 `linux/amd64`，不能复用 macOS Docker Desktop 上默认构建出的本地镜像。

真实拓扑测试时，优先使用 admin-server 私有仓库镜像，例如 `10.112.244.94:5000/scientific-matmul:dev`，并确保各业务节点 Docker 已配置可拉取该 registry。

期望：

- 脚本末尾输出 `OK matmul live e2e passed`
- 实例状态进入 `running`
- 验收环境启用业务 IPv6 时，还必须抽查容器环境变量，确认 `PEER_*_URL` 为 `http://[IPv6]:port`，`TASK_PEERS_JSON.business_address` 为 IPv6，且 sink 日志出现指标回写完成标记。
- evaluation 返回 `metric_key=effective_gflops`
- `business_success=true`
- source / compute / sink 均有非空 `ports` 和 `port_values`

## 业务目标成功率页面验收

页面入口：

```text
http://10.112.244.94:8182/benchmark
```

正式验收步骤：

1. Step 1 批量测试计算节点 baseline，确认 `compute-1/2/3` 都有同任务基线值；稳定节点会优先参与，波动较大节点仍可作为低优先级候选。
2. Step 2 创建 30 个测评工单，矩阵 profile 与 baseline 保持一致，默认使用 10 秒观测窗口和最少 5 个有效样本；未指定源/目的时系统会在 `h1-h13` 终端节点中轮转，避免固定压到 `h1 -> h2`。
3. 记录页面顶部显示的当前 `benchmark_run_id`；后续列表、路由、启动和 Step 4 统计都应限定在该轮次。
4. Step 3 使用外部路由系统回写 placements；联调阶段可在系统设置页启用开发调试路由流程生成 placements，用于验证部署与评价闭环。
5. Step 3 设置合适的“并发任务数”（默认 3，可按现场资源情况调整），启动已路由实例，等待状态进入已评估完成；资源暂不可用时系统会自动等待。
6. 打开“测试工单列表”中若干任务工单详情，核对业务参数 JSON、路由结果 JSON、source/compute/sink 节点、compute GPU 编号、实测指标和采集元数据。
7. Step 4 截图最终结果，要求同一 `benchmark_run_id` 下已评估任务数 >= 30 且业务目标成功率 >= 90%。

管理员验收页面应能看到全部 `is_benchmark=true` 测评工单；普通用户页面仍只展示自己的工单。如果 Step 4 有 30 个已评估任务但测试工单列表为空，应优先检查 `/api/orders` 的管理员可见性、登录 token 和 nginx `/api` 代理，而不是只截图成功率进度条。

如果出现部署失败、无 baseline、指标缺失或有效样本数不足，应先通过工单详情和实例日志定位并修复，然后重新创建测评工单补足 30 个可评价样本，不能只截取临时 100% 小样本结果作为正式验收。

## 意图参数解析准确率评测

正式演示和验收使用在线大模型接口逐条运行固定数据集，不再依赖百炼 Batch 队列。Batch 相关接口仅保留为历史诊断能力；页面主入口和测试方案口径均以“在线逐条评测”为准。

本地规则回归：

```bash
cd backend
PYTHONPATH=. ./venv/bin/python - <<'PY'
from services.intent_batch_eval import run_rule_evaluation
r = run_rule_evaluation(repeats=1)
print(r["correct"], r["total"], r["accuracy"], r["passed"])
PY
```

在线模型 smoke：

```bash
cd backend
PYTHONPATH=. ./venv/bin/python scripts/run_intent_online_eval.py --limit 5 --concurrency 2
```

在线模型全量评测：

```bash
cd backend
PYTHONPATH=. ./venv/bin/python scripts/run_intent_online_eval.py --concurrency 8 --retries 5 --retry-delay-seconds 5
```

期望：生成 `reports/intent_eval_online.json`，`total=360`，`passed=true`，页面 `/intent-evaluation` 展示“意图参数解析准确率”不低于 90%。正式验收建议使用并发 8、单条最多重试 5 次、失败间隔 5 秒的参数；在当前固定数据集规模下，正常应在 10 多分钟内完成。若评测中断，可追加 `--resume` 续跑已完成样本。报告内部保留模型原始输出诊断，专家主页面只展示统一准确率。

正式展示以管理节点页面为准。`reports/intent_eval_online.json` 是文件产物，不写入 MySQL；本地 `127.0.0.1` 运行出的报告不会自动出现在管理节点页面。准备让验收方或用户查看时，应在管理节点页面运行评测，或显式同步本地 `reports/intent_eval_online.json`、`reports/intent_eval_online.status.json` 和对应 `reports/intent_eval_runs/*.json` 到 `/home/bupt/manage_deploy/reports/` 后再刷新 `http://10.112.244.94:8182/intent-evaluation`。

## 用户端意图对话闭环

页面入口：

```text
http://<manager-host>/intent-chat
```

矩阵乘法任务示例输入：

```text
矩阵乘法任务，从 h1 到 h2，1024阶矩阵，50批，现在开始跑2小时，资源保障策略
```

视频AI推理任务示例输入：

```text
视频AI推理任务，从 h3 到 h4，720p视频，100帧，30fps，现在开始跑2小时，低时延策略
```

验证要点：

1. 对话气泡返回解析说明，右侧“意图参数”显示任务类型、所属模态、源节点、目的节点、开始/结束时间和对应业务参数。
2. 缺少源节点、目的节点、开始/结束时间或任务关键参数时，系统应以中文追问补全；输入不存在的源/目的端点或把 `compute-1/2/3` 当作用户源/目的时，应提示参数不合法，不创建工单。
3. 点击“确认提交任务”后，系统创建工单。若系统设置页选择“系统自动分配”，确认后应直接完成计算节点分配并进入已提交状态；若选择“外部路由系统”，工单进入待分配，等待路由系统回写 placements。
4. 打开“我的工单”详情，确认“业务”页展示业务类型、模态和参数，“路由与节点”页展示部署模式为用户端外部接入，平台受控角色为计算节点，并展示业务链路接入地址。
5. 业务运行并上报指标后，在“结果”页查看矩阵计算数字结果，或视频AI推理的检测类别、画框坐标、P90 帧时延和带框预览图。用户端接入模式由计算节点上报平台业务指标；三容器测评模式由汇总节点上报。

路由 DAG JSON 属于管理员调试和路由对接信息，不作为普通用户端意图解析功能性验证的页面观察点。

测评与用户演示的边界见 `docs/端点部署与用户接入模型.md`：`/benchmark` 使用可控测试设备模拟 source/sink 以批量统计成功率；`/intent-chat` 展示真实用户端自行接入，平台不控制用户终端。

### compute-only 用户接入 E2E

在已启动后端、已注册业务节点且 compute worker 镜像可用时，可跑对话式 compute-only 验证：

```bash
cd backend
PYTHONPATH=. ./venv/bin/python scripts/e2e_compute_only_access.py --base-url http://127.0.0.1:8000
```

脚本会创建对话工单、确认 `user_access_demo` + `deployable_roles=["compute"]`、模拟仅 compute 的路由回写，并断言 `network_bindings` 含 `src_external=true` 与 `dst_access_url`。

如需演示外部目的端回调，用户端对话页会按任务类型固定目的端接收端口：矩阵计算 `9000`，视频推理 `9100`。确认意图和路由回写后，工单详情应展示 `compute -> sink` 链路的 `dst_access_url`，默认形式为 `http://<目的端数据面IP>:<端口>`，浏览器直接打开该地址即可查看 receiver 页面。后台注入 compute 的 `CALLBACK_URL` / `SINK_CALLBACK_URL` 会使用内部接口 `http://<目的端数据面IP>:<端口>/callback`，该路径不需要在用户页面展示。compute-only 容器默认注入 `PEER_WAIT_TIMEOUT_SEC=3600`，允许外部用户端在工单启动后稍晚提交输入；无受控 sink 时，compute 会先上报平台指标，再短超时 best-effort POST 外部回调。

目的端 receiver 冒烟可在本机或终端节点上运行：

```bash
ENDPOINT_NODE_ALIAS=h2 \
ENDPOINT_TOPOLOGY_NODE_ID=h18015002 \
ENDPOINT_BUSINESS_IPV6=2001:da8:215:6a01:xxxx:xxxx:xxxx:xxxx \
PYTHONPATH=workers python3 workers/high-throughput-matmul/src/receiver_main.py --port 9000
```

视频推理 receiver 冒烟使用：

```bash
ENDPOINT_NODE_ALIAS=h2 \
ENDPOINT_TOPOLOGY_NODE_ID=h18015002 \
ENDPOINT_BUSINESS_IPV6=2001:da8:215:6a01:xxxx:xxxx:xxxx:xxxx \
PYTHONPATH=workers python3 workers/low-latency-video/src/receiver_main.py --port 9100
```

矩阵 receiver 另开终端发送回调：

```bash
curl -sS -X POST http://127.0.0.1:9000/callback \
  -H 'Content-Type: application/json' \
  -d '{"order_id":"demo-order","metric_key":"effective_gflops","result":{"effective_gflops":123.4}}'
curl -sS http://127.0.0.1:9000/latest | python3 -m json.tool
```

视频 receiver 另开终端发送回调：

```bash
curl -sS -X POST http://127.0.0.1:9100/callback \
  -H 'Content-Type: application/json' \
  -d '{"order_id":"demo-video-order","metric_key":"frame_latency_p90_ms","result":{"frame_latency_p90_ms":12.3}}'
curl -sS http://127.0.0.1:9100/latest | python3 -m json.tool
```

期望：`POST /callback` 返回 `status=ok`。浏览器打开矩阵 receiver 的 `http://127.0.0.1:9000/` 或视频 receiver 的 `http://127.0.0.1:9100/`，能看到“用户端结果接收器”、工单 ID、节点别名、拓扑节点 ID、数据面 IPv6/IPv4、监听端口和指标值；视频回调如果包含 `annotated_frame_data_url` / `preview_frames` / `samples` / `detections`，首页会展示带框预览图、原始测试视频、抽帧检测证据、推理时延趋势和检测目标列表。同一固定端口接收多个工单时，首页默认展示最近结果，页面顶部“切换已接收工单”下拉可切换历史结果；脚本排查使用 `/latest` 或 `/orders/{order_id}`。

视频 compute-only 用户演示模式支持 `event_type=progress` 实时进度回调和 `event_type=final` 最终回调。receiver 页面可以用 progress 展示运行中增长的样本，但平台业务目标成功率、工单最终指标和验收结论只以 final 结果为准。

验收环境必须额外确认业务数据面使用 IPv6：`nodes.business_ipv6` 已登记、后端 `PREFER_BUSINESS_IPV6=true`，并抽查 `network_bindings` / `PEER_*_URL` 中的业务地址为 IPv6。`10.112` IPv4 可用于管理面和阶段性页面访问，但不应作为正式业务数据流口径。

若 compute 容器已运行且业务面可达，可用轻量用户端客户端提交任务：

```bash
# 直接指定 compute 接入基址
python scripts/user_source_client.py \
  --compute-url 'http://[<compute-business-ipv6>]:<port>' \
  --matrix-size 256 --batch-count 10 --wait-result

# 或从工单 API 解析 network_bindings
python scripts/user_source_client.py \
  --base-url http://127.0.0.1:8000 \
  --order-id <order-uuid> \
  --token <access_token> \
  --wait-result
```

成功时客户端输出 `GET /result` 的 JSON；平台上报指标后，工单详情「结果」页应展示业务评估。

## 视频推理扩展业务验证

当前视频业务是轻量工业检测抽帧推理，主要用于扩展模态演示和后续联调。它不上载完整视频流，而是让 source 读取固定测试视频并抽帧，compute 运行 `yolov5n-fp32.onnx` 统计逐帧推理时延，sink 上报 `frame_latency_p90_ms`、检测框和带框预览图。

本地单测：

```bash
PYTHONPATH=workers/low-latency-video/src backend/venv/bin/python -m pytest -q workers/low-latency-video/tests
```

本地 baseline 开发调试路径：

```bash
cd backend
PYTHONPATH=. ./venv/bin/python - <<'PY'
from services.baseline_runner import run_benchmark
print(run_benchmark("low_latency_video_pipeline", runs=1))
PY
```

远端镜像构建：

```bash
WORKER_KIND=video \
WORKER_IMAGE=10.112.244.94:5000/low-latency-video \
WORKER_TAG=dev \
WORKER_PLATFORM=linux/amd64 \
WORKER_PUSH=1 \
./scripts/build_workers.sh
```

注册视频业务模板和 catalog：

```bash
cd backend
WORKER_IMAGE=10.112.244.94:5000/low-latency-video \
WORKER_TAG=dev \
DEMO_BASE_URL=http://127.0.0.1:8181 \
PYTHONPATH=. \
/home/bupt/miniconda3/envs/manage_deploy/bin/python scripts/rebuild_video_template.py
```

## 端口冲突验收

目的：确认 matmul 已进入 preflight 检查，不再绕过端口冲突。

步骤：

1. 启动一个 matmul 实例并保持 running。
2. 使用同一组 placements 再创建/启动第二个 matmul 实例。
3. 观察启动前 preflight 是否报告 `18801` / `18802` / `18803` 冲突。

期望：第二个实例启动失败，错误信息包含端口冲突，不能静默进入 running。

## 回滚清理验收

```bash
./scripts/verify_rollback_cleanup.sh
```

期望：

- 故意失败的实例进入 `failed`
- Docker 中没有残留 `{instance_id}_*` 容器

## 常见排查

查看镜像和容器：

```bash
docker images | grep 'manage-deploy'
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
```

清理旧演示工单：

```bash
./scripts/cleanup_stale_business_orders.sh
```

如果 `GET /api/nodes` 返回 500，优先检查：

- backend 是否重启并执行过 `init_db()`
- 当前数据库是否缺少新增列，如 `nodes.business_ipv6`
- 验收环境 `.env` 是否设置 `PREFER_BUSINESS_IPV6=true` 与正确的 `BACKEND_PORT`，避免 worker 数据面走 IPv6 但指标回写到错误端口
- backend 控制台完整 traceback
- 当前服务是否连接到验收 MySQL 数据库

## 提交前最低要求

- 后端改动：跑相关单测；共享行为变更跑全量 `backend/tests`。
- 前端展示改动：跑 `npm run test:display`、`npm run ui:smoke` 和 `npm run build`；涉及页面流程时跑 `npm run test:e2e`，需要人工观察时跑 `npm run test:e2e:headed`。
- Worker/Docker 改动：跑 `./scripts/build_workers.sh`，能跑 E2E 时跑 `e2e_matmul_live.sh`。
- 文档/agent 提示词改动：跑 `git diff --check`，确认 README 链接不指向已删除文件。
