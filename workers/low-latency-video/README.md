# Low Latency Video Pipeline Worker

视频 AI 推理业务的验收演示 worker，数据流保持和矩阵乘法一致的随路计算形态：

```text
source -> compute -> sink
```

## 演示口径

- `source` 从镜像内置固定视频 `bottle-detection.mp4` 读取业务画像参数，并按 `frame_stride` 抽样帧。
- `compute` 默认要求分配 GPU，加载镜像内置 `yolov5n.onnx`，对抽样帧执行目标检测，统计每帧推理时延。
- `sink` 汇总并上报 `frame_latency_p90_ms`、检测框、类别置信度、模型信息和带框预览图。
- CPU 可作为开发兜底，但验收压测默认要求路由结果为 compute 子任务分配 GPU，且部署系统应展示 GPU 设备号。

## 固定资产

镜像内包含以下验收资产，便于迁移到新拓扑后稳定复现：

- `assets/bottle-detection.mp4`：固定测试视频，用于工业检测/货架瓶体识别场景。
- `assets/models/yolov5n.onnx`：轻量 YOLOv5n ONNX 权重。
- `assets/models/coco.names`：COCO 类别标签。

详见 `assets/README.md`。

## 关键环境变量

- `VIDEO_INFERENCE_MODE=yolo_onnx`：默认真实模型推理；设置为 `surrogate` 可用于无 OpenCV/无模型的快速开发兜底。
- `VIDEO_ASSET_DIR=/app/assets`：镜像内资产目录。
- `USE_GPU=true`：业务默认要求 GPU。
- `GPU_DEVICE` / `NVIDIA_VISIBLE_DEVICES` / `CUDA_VISIBLE_DEVICES`：由部署系统按路由结果注入，用于记录和校验 GPU 分配。
- `MEASURED_FRAMES=30`：验收默认有效统计帧数。

## Benchmark Smoke

本地或管理节点构建镜像：

```bash
WORKER_KIND=video \
WORKER_IMAGE=manage-deploy/low-latency-video \
WORKER_TAG=dev \
./scripts/build_workers.sh
```

面向 AMD64 实验节点推送到私有仓库：

```bash
WORKER_KIND=video \
WORKER_IMAGE=10.112.244.94:5000/low-latency-video \
WORKER_TAG=dev \
WORKER_PLATFORM=linux/amd64 \
WORKER_PUSH=1 \
./scripts/build_workers.sh
```

容器内快速测一次有效输出：

```bash
docker run --rm --entrypoint python3 \
  -e BENCHMARK_MODE=true \
  -e MEASURED_FRAMES=3 \
  -e VIDEO_INFERENCE_MODE=yolo_onnx \
  manage-deploy/low-latency-video:dev /app/src/compute_main.py
```

成功输出应包含：

- `frame_latency_p90_ms`
- `detector_backend`
- `model_name`
- `gpu_assigned`
- `detections`
- `annotated_frame_data_url`

这些字段会进入 `business_objective_evaluations.result_metadata`，用于管理端、用户端详情页展示带框图片和分类检测结果。
