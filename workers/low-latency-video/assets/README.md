# Low-Latency Video Demo Assets

本目录保存视频 AI 推理业务的固定验收资产。固定输入视频和权重文件打包进镜像，是为了让业务目标成功率测试在不同实验拓扑上可复现。

## bottle-detection.mp4

- 用途：固定测试视频，模拟工业检测/瓶体识别类视频推理业务。
- 来源：Intel IoT DevKit sample-videos
- 仓库：https://github.com/intel-iot-devkit/sample-videos
- 直接地址：https://github.com/intel-iot-devkit/sample-videos/raw/master/bottle-detection.mp4
- 许可证：Creative Commons Attribution 4.0 International (CC-BY-4.0)
- 大小：约 493 KB
- 视频信息：H.264 MP4，640x360，约 39.85 秒，约 29.83 fps
- SHA256：`d52ba94aedf8a923c342fe9ea1d2bd85f712c4cc0f49a6de1bac43eebe3a48ff`

下载命令：

```bash
curl -sS -L https://raw.githubusercontent.com/intel-iot-devkit/sample-videos/master/bottle-detection.mp4 \
  -o workers/low-latency-video/assets/bottle-detection.mp4
```

## models/yolov5n-fp32.onnx

- 用途：固定轻量目标检测模型，用于生成分类检测框和帧推理时延。
- 模型：YOLOv5n ONNX FP32
- 大小：约 7.6 MB
- SHA256：`88d9096e76c0bf6ecf364041f5a218d65a3509146de36a82c22d8392d72c0500`

## models/coco.names

- 用途：COCO 类别标签映射。
- SHA256：`634a1132eb33f8091d60f2c346ababe8b905ae08387037aed883953b7329af84`

## 验收参数建议

- `frame_stride=30`：约每 1 秒抽 1 帧，避免压测时产生过高数据面流量。
- `warmup_frames=5`：预热模型和 OpenCV DNN。
- `measured_frames=30`：统计 30 帧的 P90 时延，兼顾演示速度和稳定性。
- `confidence_threshold=0.25`、`nms_threshold=0.45`、`max_detections=8`：固定检测参数，避免不同批次人为调参。
