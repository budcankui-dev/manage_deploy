# 元宇宙视频融合业务变更记录

## 目标与边界

本次以 `manage_deploy` 为底座，新增独立业务 `metaverse_video_fusion`（元宇宙沉浸式交互）。

- 业务链路：`source -> compute -> sink`。
- `source` 读取内置的两路视频并通过 HTTP 发送帧对。
- `compute` 在 GPU 上通过 MODNet 执行前景/背景视频融合。
- `sink` 上报 `frame_latency_p90_ms`、融合结果元数据和预览帧。
- 不替换、不删除矩阵乘法和低延迟视频 AI 业务的模板、镜像或 worker 源码。

## 本机演示验证后的修正

| 修改 | 原因与作用 |
| --- | --- |
| 元宇宙模板端口采用自动分配 | 与低延迟视频业务一致：默认端口为 `18821`、`18822`、`18823`，但实际部署使用 `auto=true` 与 `18000-19999` 范围。 |
| 元宇宙正式画像统一为 `720p` / `metaverse_offline_fusion_720p` | `cam0.mp4` 与 `cam1.mp4` 的实际分辨率为 1280x720。此前基线标为 1080p、工单标为 720p，导致已上报指标无法匹配基线而不能评估。 |
| 元宇宙 P90 采用视频时延基线容差，并要求 `torch_cuda` + `cuda:*` | 使融合任务按 GPU MODNet 的正式基线评估；CPU 回退不能错误判定为达标。 |
| Manager 的运行手册增加帧序列持久卷和输入视频只读挂载 | 重建 Manager 后仍能播放融合结果，也能访问 `cam0.mp4` 与 `cam1.mp4` 输入预览。 |
| `.runtime/` 与各层 `venv*/` 加入忽略规则 | 运行帧缓存和误建虚拟环境属于本机生成物，不能进入 Git。 |

## 新增文件

| 位置 | 作用 |
| --- | --- |
| `workers/metaverse-video-fusion/` | 独立 worker、Dockerfile、MODNet 源码、权重和双路视频素材。 |
| `workers/metaverse-video-fusion/src/source_main.py` | 从 `cam0.mp4`、`cam1.mp4` 读取帧对，并发送至 compute。 |
| `workers/metaverse-video-fusion/src/compute_main.py` | 调用 MODNet 融合帧对，统计 P90 融合时延。 |
| `workers/metaverse-video-fusion/src/sink_main.py` | 接收融合结果，保存帧序列并向平台上报指标。 |
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
| 结果资产 | 新增受服务 token 保护的融合帧序列上传/读取接口；结果保存在 `platform_scratch_root/<instance>/results/`。 |
| 前端 | 意图对话、业务中心、工单详情、测评页和系统资源配置均可识别与展示新业务。 |

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
  tests/test_business_tasks.py \
  tests/test_routing_payload_builder.py
```

结果：`51 passed`。

前端构建已完成：

```bash
cd frontend
npm run build
```

说明：当前本机 `backend/venv311` 缺少 `numpy`，会使既有矩阵“本地回退基线”测试在导入旧 worker 时失败；这不是元宇宙业务造成的回归。安装开发依赖后应运行完整测试集。

## 运行前提

- Docker 和 NVIDIA Container Toolkit 可用；`docker run --gpus all ... nvidia-smi` 应成功。
- compute 节点可拉取或已加载 `metaverse-video-fusion` 镜像。
- Manager、Node Agent、数据库和 MinIO 按项目既有方式启动。
- 注册模板前，正式拓扑中的 `compute-1/2/3` 与终端节点应已登记。
