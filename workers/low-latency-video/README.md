# Low Latency Video Pipeline Worker

视频 AI 推理业务的验收演示 worker，数据流保持和矩阵乘法一致的随路计算形态：

```text
source -> compute -> sink
```

## 演示口径

- `source` 从镜像内置固定视频 `bottle-detection.mp4` 读取业务画像参数，并按 `frame_stride` 抽样帧。
- `compute` 默认要求分配 GPU，加载镜像内置 `yolov5n-fp32.onnx`，对抽样帧执行目标检测，统计每帧推理时延。运行时会优先尝试 CUDA 后端，并在结果中明确记录实际后端。
- `sink` 汇总并上报 `frame_latency_p90_ms`、检测框、类别置信度、模型信息和带框预览图。
- CPU 可作为开发兜底，但验收压测默认要求路由结果为 compute 子任务分配 GPU，且结果必须展示 `actual_backend`、`gpu_requested`、`gpu_available`、`gpu_error` 等证据字段。

## 固定资产

镜像内包含以下验收资产，便于迁移到新拓扑后稳定复现：

- `assets/bottle-detection.mp4`：固定测试视频，用于工业检测/货架瓶体识别场景。
- `assets/models/yolov5n-fp32.onnx`：轻量 YOLOv5n ONNX FP32 权重，默认用于 GPU 验证。
- `assets/models/coco.names`：COCO 类别标签。

详见 `assets/README.md`。

## 关键环境变量

- `VIDEO_INFERENCE_MODE=yolo_onnx`：默认真实模型推理；设置为 `surrogate` 可用于无 OpenCV/无模型的快速开发兜底。
- `VIDEO_DNN_TARGET=auto`：自动根据 GPU 分配情况优先尝试 ONNX Runtime CUDA；也可显式设为 `cuda` 或 `cpu`。
- `VIDEO_ASSET_DIR=/app/assets`：镜像内资产目录。
- `USE_GPU=true`：业务默认要求 GPU。
- `GPU_DEVICE` / `NVIDIA_VISIBLE_DEVICES` / `CUDA_VISIBLE_DEVICES`：由部署系统按路由结果注入，用于记录和校验 GPU 分配。
- `MEASURED_FRAMES=30`：验收默认有效统计帧数。

## GPU 后端说明

当前 worker 使用 YOLOv5 ONNX，优先尝试 ONNX Runtime CUDA，其次尝试 OpenCV DNN CUDA，最后降级 OpenCV DNN CPU。需要注意：PyPI 官方 `opencv-python-headless` 通常不包含 CUDA DNN 加速能力，即使容器分配了 GPU，也可能在运行时降级为 `opencv_dnn_cpu`。因此代码不再用 `gpu_assigned=true` 代表真实 GPU 推理，而是输出：

- `detector_backend` / `actual_backend` / `backend`：真实执行后端，期望 GPU 成功时为 `onnxruntime_cuda`，次选为 `opencv_dnn_cuda`。
- `device`：实际推理设备，例如 `cuda:0` 或 `cpu`。
- `gpu_requested`：任务是否请求 GPU。
- `gpu_available`：容器内是否能看到 NVIDIA/CUDA 设备。
- `gpu_error`：请求 GPU 但 CUDA 后端不可用或推理失败时的原因。

镜像使用 `python:3.11-slim` 作为基底，并通过 pip 安装 `onnxruntime-gpu` 与 CUDA/cuDNN runtime 依赖。如果目标节点 NVIDIA Container Runtime、驱动、CUDA/cuDNN 兼容，结果应显示 `actual_backend=onnxruntime_cuda`；否则会明确降级原因，避免“显示分配 GPU 但实际 CPU 推理”的误判。

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
  -e VIDEO_DNN_TARGET=auto \
  manage-deploy/low-latency-video:dev /app/src/compute_main.py
```

成功输出应包含：

- `frame_latency_p90_ms`
- `detector_backend`
- `actual_backend`
- `device`
- `gpu_requested`
- `gpu_available`
- `gpu_error`
- `model_name`
- `gpu_assigned`
- `detections`
- `annotated_frame_data_url`

这些字段会进入 `business_objective_evaluations.result_metadata`，用于管理端、用户端详情页展示带框图片和分类检测结果。
