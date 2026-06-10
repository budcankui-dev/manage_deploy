FROM python:3.11-slim

WORKDIR /app

COPY low-latency-video/assets/wheels /tmp/wheels
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    opencv-python-headless==4.10.0.84 \
    onnxruntime-gpu==1.18.0 \
    nvidia-cuda-runtime-cu11==11.8.89 \
    nvidia-cuda-nvrtc-cu11==11.8.89 \
    nvidia-cublas-cu11==11.11.3.6 \
    nvidia-cudnn-cu11==8.9.6.50 \
    nvidia-cufft-cu11==10.9.0.58 \
    nvidia-curand-cu11==10.3.0.86 \
    nvidia-cusolver-cu11==11.4.1.48 \
    nvidia-cusparse-cu11==11.7.5.86 \
    nvidia-nvtx-cu11==11.8.86 \
    pillow==11.3.0 \
    httpx==0.28.1 \
    minio==7.2.15 && \
    rm -rf /tmp/wheels

COPY _common /app/_common
COPY low-latency-video/src /app/src
COPY low-latency-video/assets /app/assets
ENV PYTHONPATH=/app/src:/app
ENV USE_GPU=true
ENV VIDEO_ASSET_DIR=/app/assets
ENV VIDEO_INFERENCE_MODE=yolo_onnx
ENV VIDEO_DNN_TARGET=auto
ENV VIDEO_MODEL_PATH=models/yolov5n-fp32.onnx
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib:/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cuda_runtime/lib:/usr/local/lib/python3.11/site-packages/nvidia/cuda_nvrtc/lib:/usr/local/lib/python3.11/site-packages/nvidia/cufft/lib:/usr/local/lib/python3.11/site-packages/nvidia/curand/lib:/usr/local/lib/python3.11/site-packages/nvidia/cusolver/lib:/usr/local/lib/python3.11/site-packages/nvidia/cusparse/lib:/usr/local/lib/python3.11/site-packages/nvidia/nvtx/lib
CMD ["python3", "/app/src/source_main.py"]
