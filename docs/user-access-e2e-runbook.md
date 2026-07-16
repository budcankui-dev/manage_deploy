# 用户接入模式端到端验收流程

本文用于验收“用户端外部接入”模式：平台只部署计算节点，用户在源端和目的端手动启动业务容器，最终在工单详情和目的端 receiver 页面复核结果。

## 1. 页面验收目标

- 用户提交自然语言任务后，可以在“我的工单”详情看到源端、目的端、计算节点和业务面地址。
- 工单详情不展示 `docker login` 或 `docker run` 命令；镜像仓库登录应由现场提前准备或在运行手册中说明。
- 目的端 receiver 页面展示用户登录目的节点的 SSH 命令、管理面/数据面 IP、目的端 receiver 容器启动命令和结果接收页面地址。
- 路由完成后，工单详情“路由与节点”页必须展示 `network_bindings` 返回的真实计算服务接入地址。
- “结果”页必须展示业务目标是否达标、核心指标、输入参数和输出证据。
- 矩阵乘法和视频AI推理两类任务都要可演示，不允许只跑通其中一种。

## 2. 用户手动容器流程

1. 在用户端 `/intent-chat` 输入任务，例如“矩阵乘法任务，从 h1 到 h2，1024阶矩阵，50批，现在开始跑2小时，资源保障策略”。
2. 参数完整后点击“确认提交任务”，等待外部路由回写 placement；开发联调可启用系统自动分配。
3. 打开“我的工单”或对话内工单详情，确认“路由与节点”页展示计算服务接入地址和目的端接收地址。
4. 按运行手册或 receiver 页面提示，先在目的端启动 receiver 容器。
5. 浏览器打开目的端接收页面，确认页面展示节点登录命令、管理面/数据面 IP 和固定接收端口。
6. 路由完成并生成计算服务接入地址后，在源端按业务脚本提交输入。
7. 打开工单详情“结果”页和目的端 receiver 页面，确认指标、输出证据和业务目标判定。

现场可提前登录验收管理网私有仓库，或由 Docker 预置凭据：

```bash
docker login 172.16.0.254:5000
```

目的端 receiver 页面默认展示 `172.16.0.254:5000/<endpoint-image>:dev`，可通过容器环境变量 `ENDPOINT_IMAGE`、`ENDPOINT_IMAGE_REGISTRY`、`ENDPOINT_IMAGE_TAG` 覆盖。

## 3. 两类任务应展示的结果证据

矩阵乘法计算任务：

- 输入：矩阵规模、批次数、随机种子。
- 输出：有效计算吞吐量、目标阈值、是否达标、运行矩阵规模、采样次数、执行后端、GPU 设备。
- 结果判定：同一任务详情页中能看到实际 GFLOPS 和目标 GFLOPS，且成功/失败状态明确。

视频AI推理任务：

- 输入：固定测试视频、分辨率、fps、视频片段帧范围、抽帧间隔、预热帧数、参与统计帧数、模型名称。
- 输出：P90 帧推理时延、平均帧时延、参与统计帧数、检测类别、置信度、画框坐标、带框预览图、GPU/推理后端。
- 结果判定：同一任务详情页中能看到实际 P90 时延和目标阈值，且成功/失败状态明确。

注意：“视频片段帧范围”表示源视频候选帧范围；“参与统计帧数”才是 P90 统计样本数。

## 4. 可复用端到端脚本

真实拓扑上可用该脚本验证用户端手动容器闭环。脚本通过 Node Agent 启动源端和目的端容器，等价于演示人员复制页面命令执行，但更适合批量回归。

```bash
cd /Users/yanjia/codes/manage_deploy/backend
NETWORK_PROFILE=acceptance \
PYTHONPATH=. ./venv/bin/python scripts/e2e_user_endpoint_manual_containers.py \
  --base-url http://172.16.0.254:8181 \
  --username user \
  --password user \
  --task-type high_throughput_matmul \
  --source-node h1 \
  --destination-node h2
```

视频任务：

```bash
cd /Users/yanjia/codes/manage_deploy/backend
NETWORK_PROFILE=acceptance \
PYTHONPATH=. ./venv/bin/python scripts/e2e_user_endpoint_manual_containers.py \
  --base-url http://172.16.0.254:8181 \
  --username user \
  --password user \
  --task-type low_latency_video_pipeline \
  --source-node h3 \
  --destination-node h4
```

期望输出包含：

```text
OK 用户端手动容器演示 E2E passed
```

并打印 `order_id`、`instance_id`、`compute_url`、`receiver_page`、`metric_key`、`metric_value`。

## 5. 30 任务稳定性验收

业务目标成功率验收以 `/benchmark` 页面为准，用户接入演示不能替代批量测评。正式稳定版要求：

- 矩阵乘法计算任务创建并完成 30 个同轮次测评工单。
- 视频AI推理任务创建并完成 30 个同轮次测评工单。
- 两类任务各自已评估任务数不少于 30。
- 两类任务业务目标成功率均不低于 90%，即至少 27 个任务达标。
- 运行完成后系统自动停止并删除本轮测评容器实例，保留工单、路由、指标和结果证据。

页面验收步骤详见 [benchmark-test-plan.md](benchmark-test-plan.md)。

## 6. 常见失败排查

- 工单详情没有真实计算服务接入地址：先确认路由系统已回写 placement，并且工单 `routing_result.network_bindings` 中存在 `source -> compute` 的 `dst_access_url`。
- receiver 页面打不开：确认目的端容器已启动、端口未冲突、业务面 IPv6/IPv4 可达，且本机没有 VPN 抢路由。
- 结果页一直等待：检查源端容器是否成功 POST 到 compute，compute 日志是否收到 job，compute 是否能 POST 到目的端 `/callback`。
- 镜像拉取失败：确认每台节点 Docker 已允许 `172.16.0.254:5000` insecure registry，并已 `docker login` 或预置凭据。
- 视频任务参数被质疑：统一解释为“视频片段帧范围”和“参与统计帧数”两个概念，P90 只使用参与统计帧数计算。
