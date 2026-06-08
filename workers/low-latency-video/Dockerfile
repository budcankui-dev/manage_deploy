FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip libglib2.0-0 libgl1 && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    numpy==2.2.5 \
    opencv-python-headless==4.12.0.88 \
    httpx==0.28.1 \
    minio==7.2.15

COPY _common /app/_common
COPY low-latency-video/src /app/src
COPY low-latency-video/assets /app/assets
ENV PYTHONPATH=/app/src:/app
ENV USE_GPU=true
ENV VIDEO_ASSET_DIR=/app/assets
ENV VIDEO_INFERENCE_MODE=yolo_onnx
CMD ["python3", "/app/src/source_main.py"]
