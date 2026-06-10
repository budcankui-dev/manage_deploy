# Build from repo root: docker build -f workers/high-throughput-matmul/Dockerfile -t matmul-worker:latest workers
#
# GPU mode: docker run --gpus all -e USE_GPU=true matmul-worker:latest
# CPU mode: docker run matmul-worker:latest

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip3 install --no-cache-dir \
    numpy==2.2.5 \
    cupy-cuda12x==13.4.1 \
    httpx==0.28.1 \
    minio==7.2.15

COPY _common /app/_common
COPY high-throughput-matmul/src /app/src
ENV PYTHONPATH=/app/src:/app
ENV USE_GPU=true
CMD ["python3", "/app/src/source_main.py"]
