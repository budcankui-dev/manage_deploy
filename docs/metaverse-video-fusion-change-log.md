# 元宇宙视频融合业务变更记录

## 目标与边界

本次以 `manage_deploy` 为底座，新增独立业务 `metaverse_video_fusion`（元宇宙沉浸式交互）。

- 业务链路：`source -> compute -> sink`。
- `source` 通过业务面 HTTP 流提供双路输入视频，并发送资产描述和融合画像触发 compute。
- `compute` 在 GPU 上通过 MODNet 执行前景/背景视频融合。
- `compute` 将 MP4、JPEG 预览和 JSON 摘要归档至 MinIO；`sink` 只上报 P90 和对象 URI。
- 不替换、不删除矩阵乘法和低延迟视频 AI 业务的模板、镜像或 worker 源码。

## 本机演示验证后的修正

| 修改 | 原因与作用 |
| --- | --- |
| 元宇宙模板端口采用自动分配 | 与低延迟视频业务一致：默认端口为 `18821`、`18822`、`18823`，但实际部署使用 `auto=true` 与 `18000-19999` 范围。 |
| 元宇宙正式画像统一为 `720p` / `metaverse_offline_fusion_720p` | `cam0.mp4` 与 `cam1.mp4` 的实际分辨率为 1280x720。此前基线标为 1080p、工单标为 720p，导致已上报指标无法匹配基线而不能评估。 |
| 元宇宙 P90 采用视频时延基线容差，并要求 `torch_cuda` + `cuda:*` | 使融合任务按 GPU MODNet 的正式基线评估；CPU 回退不能错误判定为达标。 |
| Manager 的运行手册增加输入视频只读挂载 | Manager 可访问 `cam0.mp4` 与 `cam1.mp4` 输入预览；融合结果不再依赖 Manager 本地持久卷。 |
| `.runtime/` 与各层 `venv*/` 加入忽略规则 | 运行帧缓存和误建虚拟环境属于本机生成物，不能进入 Git。 |
| 融合结果改为 MinIO 耐久归档 | Compute 必须将 `fusion-result.mp4`、`fusion-preview.jpg`、`result.json` 写入 `task-results/<instance>/metaverse/`；归档失败会使任务失败，避免出现“成功但没有可播放结果”。 |
| 融合 MP4 改为 H.264 | OpenCV `mp4v` 生成的 MPEG-4 Part 2 文件在 Chrome 无法加载 metadata。Compute 现在使用 `ffmpeg/libx264` 输出 `yuv420p` H.264 MP4，并用 `ffprobe` 断言编码为 `h264`；任务不会归档不可播放的视频。 |
| Source → Compute 输入改为视频字节流 | Source 仅公开白名单 `cam0.mp4`、`cam1.mp4` 的 `/assets/<name>` 流式接口；Compute 必须通过 `PEER_SOURCE_URL` 下载两路 MP4 后融合，不再在 Compute 本地读取同一份输入或传递 Base64 帧序列。 |
| 前端改为 URI 播放 | 工单详情使用 Manager 的只读代理 URI 播放 MP4，浏览器不接触 MinIO 密钥，也不再加载 Base64 帧序列。 |
| 元宇宙详情展示修正 | 结果页改为融合 MP4、MODNet/GPU/时延证据文案；输入参数移除重复的前景视频、背景视频、融合模式，并按要求不展示分辨率。 |
| 补齐 receiver 入口并去除旧仓库地址 | 新增 `receiver_main.py`，并由运行时部署画像提供 endpoint 镜像；前端不再为元宇宙写死旧的 `10.112.244.94:5000` 仓库。 |
| 三角色节点放置修正 | 模板将 Source 放在 `h1`、Compute 放在 GPU 节点 `compute-2`、Sink 放在 `h2`。 |

## 新增文件

| 位置 | 作用 |
| --- | --- |
| `workers/metaverse-video-fusion/` | 独立 worker、Dockerfile、MODNet 源码、权重和双路视频素材。 |
| `workers/metaverse-video-fusion/src/source_main.py` | 对双路视频提供业务面 HTTP 流，并发送资产描述和融合画像至 compute。 |
| `workers/metaverse-video-fusion/src/compute_main.py` | 通过 `PEER_SOURCE_URL` 流式拉取双路视频，调用 MODNet 融合、统计 P90 并归档 MinIO 对象。 |
| `workers/metaverse-video-fusion/src/sink_main.py` | 接收轻量结果（P90、GPU/backend、对象 URI）并向平台上报。 |
| `workers/metaverse-video-fusion/src/receiver_main.py` | 元宇宙用户端回调接收器入口，供 endpoint 镜像启动。 |
| `workers/metaverse-video-fusion/assets/` | `cam0.mp4`、`cam1.mp4`、MODNet 权重 `modnet_webcam_portrait_matting.ckpt`。 |
| `backend/scripts/rebuild_metaverse_fusion_template.py` | 创建/更新元宇宙模板和 `metaverse_video_fusion` 业务目录。 |
| `backend/tests/test_metaverse_video_fusion.py` | 覆盖意图、路由资源、GPU MODNet 校验和基线画像匹配。 |
| `docs/metaverse-video-fusion-task.md` | 镜像构建、模板注册、测评和排错手册。 |

## 接入点

| 范围 | 改动与作用 |
| --- | --- |
| Worker 构建 | `scripts/build_workers.sh` 新增 `metaverse-fusion` 和 `metaverse-fusion-endpoint`，不改变已有 `matmul`、`video` 类型。 |
| 任务模板 | 新模板“元宇宙沉浸式交互”，端口与现有视频业务隔离，使用 18821/18822/18823。 |
| 意图解析 | 规则解析与 LLM 解析识别“元宇宙、沉浸式、视频融合、双路视频、MODNet”，生成固定双视频画像。 |
| 路由与资源 | 新任务映射至“低时延转发模态”，compute 需要 1 张 GPU，并独立估算数据量和带宽。 |
| 基线与评估 | 使用独立的 180 帧画像（10 帧预热、170 帧统计）；只有 `torch_cuda` 和 `MODNet` 同时满足时才接受正式基线/业务成功。 |
| 工单和会话 | 支持创建元宇宙测评工单、GPU slot 占用和默认目的端口 9200。 |
| 结果资产 | Compute 归档 `task-results/<instance>/metaverse/{fusion-result.mp4,fusion-preview.jpg,result.json}`；Manager 仅提供受限的只读对象代理。 |
| 前端 | 意图对话、业务中心、工单详情、测评页和系统资源配置均可识别与展示新业务；工单详情直接播放归档 MP4。 |

## 隔离性说明

1. 新业务有独立 `task_type`、模板名称、镜像名称、端口、worker 目录和基线画像。
2. 原有低延迟视频 AI 仍使用 YOLO 镜像、`low_latency_video_pipeline`、18811/18812/18813 端口和原有 GPU 校验规则。
3. 条件分支只在 `task_type == "metaverse_video_fusion"` 时启用 MODNet、双路视频和融合结果逻辑；其他任务沿用原分支。
4. 新增测试覆盖元宇宙分支，并应同时运行原有矩阵、视频、意图和路由测试，防止回归。

## 验证记录

已完成：

```bash
cd backend
PYTHONPATH=. ./venv311/bin/pytest -q \
  tests/test_metaverse_video_fusion.py \
  tests/test_intent_parser.py \
  tests/test_routing_payload_builder.py
```

归档链路单元测试：

```bash
cd ~/manage_deploy
backend/venv311/bin/python -m pytest -q workers/metaverse-video-fusion/tests/test_sink_main.py workers/metaverse-video-fusion/tests/test_source_main.py
```

上述两组当前结果分别为 `43 passed`、`9 passed`。另外，已用临时 Source 与 Compute 镜像完成实际业务面 MP4 传输校验：Compute 经 `PEER_SOURCE_URL` 下载两路文件，大小分别为 `1063326` 和 `503502` 字节。

前端构建应在依赖完整时执行：

```bash
cd ~/manage_deploy/frontend
npm run build
```

当前上游 `main` 的 `OrderDetailPanel.vue` 引用了缺失的 `@/utils/clipboard`，若构建报该模块不存在，则属于上游已有问题，不能通过修改非元宇宙公共代码绕过。

## 运行前提

- Docker 和 NVIDIA Container Toolkit 可用；`docker run --gpus all ... nvidia-smi` 应成功。
- compute 节点可拉取或已加载 `metaverse-video-fusion` 镜像。
- Manager、Node Agent、数据库和 MinIO 按项目既有方式启动；Manager 与三个 worker 必须使用同一可访问的 `MINIO_ENDPOINT`、bucket 和访问密钥。
- 注册模板前，正式拓扑中的 `h1`、`compute-2`（GPU）和 `h2` 应已登记。
