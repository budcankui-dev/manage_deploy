# 元宇宙沉浸式交互任务运行说明

本文档说明新增业务 `metaverse_video_fusion`（元宇宙沉浸式交互）的代码位置、运行方式和测评流程。

## 任务模型

该任务与视频 AI 推理任务保持同一类平台契约：

- 任务类型：`metaverse_video_fusion`
- 业务名称：元宇宙沉浸式交互
- 模态：低时延转发模态
- DAG：`source -> compute -> sink`
- 输入：两路固定视频 `cam0.mp4`、`cam1.mp4`；Source 将视频资产描述和 180 帧画像发送到 Compute，Compute 从随镜像内置的素材读取同名输入
- 计算：`compute` 节点使用 MODNet 在 GPU 上做视频融合
- 输出：Compute 将 `fusion-result.mp4`、`fusion-preview.jpg`、`result.json` 写入 MinIO；Sink 仅上报 `frame_latency_p90_ms`、GPU/backend 摘要和对象 URI
- 统计口径：前 10 对帧预热，后 170 对帧全部计入 P90 单帧融合时延
- 业务目标：P90 单帧融合时延 `<= target_value ms`

## 关键文件

- `workers/metaverse-video-fusion/`：新业务 worker 镜像源码和内置资源
- `workers/metaverse-video-fusion/src/source_main.py`：发送双路视频资产描述和融合画像；支持与低延迟视频一致的外部终端手动启动参数
- `workers/metaverse-video-fusion/src/compute_main.py`：运行 MODNet 融合、统计时延并归档 MinIO
- `workers/metaverse-video-fusion/src/sink_main.py`：接收轻量结果摘要并回传 Manager
- `workers/metaverse-video-fusion/src/receiver_main.py`：用户端回调接收器入口
- `workers/metaverse-video-fusion/src/fusion_core.py`：MODNet 加载、GPU 检查、融合核心逻辑
- `backend/scripts/rebuild_metaverse_fusion_template.py`：注册任务模板和业务目录
- `scripts/build_workers.sh`：已支持 `WORKER_KIND=metaverse_fusion`

## 1. 构建 worker 镜像

```bash
cd ~/manage_deploy

WORKER_KIND=metaverse-fusion \
WORKER_IMAGE=manage-deploy/metaverse-video-fusion \
WORKER_TAG=dev \
./scripts/build_workers.sh
```

如果首次构建，Docker 需要下载 PyTorch CUDA 基础镜像，时间会比较长。

## 2. GPU 单容器自检

```bash
docker run --rm --gpus all --entrypoint python3 \
  -e BENCHMARK_MODE=true \
  -e FRAME_COUNT=180 \
  -e FRAME_STRIDE=1 \
  -e WARMUP_FRAMES=10 \
  -e MEASURED_FRAMES=170 \
  manage-deploy/metaverse-video-fusion:dev /app/src/compute_main.py
```

期望输出包含：

- `benchmark_result`
- `frame_latency_p90_ms`
- `actual_backend: "torch_cuda"`
- `device: "cuda:0"`
- `model_name: "MODNet"`

如果提示没有 CUDA 或不是 `torch_cuda`，说明容器没有拿到 GPU，需要先检查 Docker GPU 支持。

## 3. 注册模板

确保后端使用 MySQL 启动，然后执行：

```bash
cd ~/manage_deploy

DEMO_BASE_URL=http://127.0.0.1:8000 \
DATABASE_URL='mysql+aiomysql://root:manage123456@127.0.0.1:3306/task_manager' \
WORKER_IMAGE=manage-deploy/metaverse-video-fusion \
WORKER_TAG=dev \
PYTHONPATH=backend \
backend/venv/bin/python backend/scripts/rebuild_metaverse_fusion_template.py
```

该脚本会创建或更新：

- 任务模板：元宇宙沉浸式交互
- 业务目录：`metaverse_video_fusion -> template_id`
- 默认三节点放置：`source -> compute -> sink`

其中 Source 固定在终端节点 `h1`，Compute 固定在 GPU 节点 `compute-2`，Sink 固定在终端节点 `h2`。注册前请确认这三个 hostname 已在 Manager 节点表登记。

## 4. 后端启动建议

本地开发时建议禁止基线测试拉远端镜像，直接使用本地构建的镜像：

```bash
cd ~/manage_deploy/backend
source venv/bin/activate

MANAGER_PUBLIC_URL=http://127.0.0.1:8000 \
DATABASE_URL='mysql+aiomysql://root:manage123456@127.0.0.1:3306/task_manager' \
BENCHMARK_METAVERSE_IMAGE=manage-deploy/metaverse-video-fusion:dev \
BENCHMARK_PULL_POLICY=never \
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Node Agent 和前端按原项目方式启动即可。

### MinIO 是必需项

元宇宙任务不会把完整帧序列写入数据库，也不会降级为 Manager 本地缓存。启动 Manager 和三个节点 Agent/worker 时，必须让它们能访问相同的 MinIO：

```bash
export MINIO_ENDPOINT=http://<minio-host>:9000
export MINIO_BUCKET=task-results
export MINIO_ACCESS_KEY=<access-key>
export MINIO_SECRET_KEY=<secret-key>
```

完成一次任务后，应在 bucket 中看到：

```text
<task-instance-id>/metaverse/fusion-result.mp4
<task-instance-id>/metaverse/fusion-preview.jpg
<task-instance-id>/metaverse/result.json
```

工单详情中的播放器请求 `/api/demo-assets/metaverse-results/<task-instance-id>/fusion-result.mp4`。这是 Manager 的同源只读代理，支持 HTTP Range 请求以便浏览器流式播放和拖动进度，也不会把 MinIO 密钥暴露给浏览器。

## 5. 业务测评页面运行

进入前端业务测评页面：

1. 任务类型选择 `元宇宙沉浸式交互`
2. 点击 `批量测试计算节点`
3. 点击 `创建测评工单`
4. 使用本地 mock 路由给工单回写节点放置
5. 点击 `运行测评`
6. 查看详情页中的融合 MP4 播放器和 P90 时延结果

mock 路由命令示例：

```bash
cd ~/manage_deploy

backend/venv/bin/python scripts/mock_external_router.py \
  --base-url http://127.0.0.1:8000 \
  --task-type metaverse_video_fusion \
  --compute-nodes compute-1,compute-2,compute-3 \
  --gpu-device 0 \
  --limit 3
```

GPU 任务默认一个工单占用一张 GPU 的一个 slot。如果一次创建 30 个工单，不能一次性全部路由到同一个 `gpu0`；需要分批运行、释放后再路由下一批，或者使用不同 `--gpu-device`。

## 6. 排错命令

查看节点资源：

```bash
curl -s http://127.0.0.1:8000/api/nodes | python3 -m json.tool
```

查看工单：

```bash
curl -s 'http://127.0.0.1:8000/api/business-tasks?task_type=metaverse_video_fusion' | python3 -m json.tool
```

查看实例容器：

```bash
docker ps -a --filter label=manage_deploy.task_id --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

查看容器日志：

```bash
docker logs <container_name_or_id> --tail 100
```

常见问题：

- `待分配`：外部路由还没有回写 placements，先运行 mock router。
- `GPU slot conflict`：同一节点同一 GPU 已被其他任务占用，先清理实例或换 `--gpu-device`。
- `actual_backend` 不是 `torch_cuda`：容器没有拿到 GPU，检查 `docker run --gpus all ... nvidia-smi`。
- `MinIO credentials are required` 或结果对象不存在：检查 Manager 与 Compute 的四个 `MINIO_*` 环境变量、网络连通性和 bucket 权限；归档失败时任务会明确失败。
- `Business evaluation not found`：任务还没运行完或 sink 没有上报指标，先查容器日志。
