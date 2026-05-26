# syntax=docker/dockerfile:1.7
# Build from repo root: docker build -f workers/high-throughput-matmul/Dockerfile -t manage-deploy/scientific-matmul:dev workers

FROM python:3.11-slim
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install numpy==2.2.5 httpx==0.28.1 minio==7.2.15
COPY _common /app/_common
COPY high-throughput-matmul/src /app/src
ENV PYTHONPATH=/app/src:/app
CMD ["python", "/app/src/source_main.py"]
