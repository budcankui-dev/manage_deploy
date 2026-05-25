# syntax=docker/dockerfile:1
# Build from repo root: docker build -f workers/high-throughput-matmul/Dockerfile --target source -t manage-deploy/matmul-source:dev workers

FROM python:3.11-slim AS base
WORKDIR /app
RUN pip install --no-cache-dir numpy==2.2.5 httpx==0.28.1 minio==7.2.15
COPY _common /app/_common
COPY high-throughput-matmul/src /app/src
ENV PYTHONPATH=/app/src:/app

FROM base AS source
CMD ["python", "/app/src/source_main.py"]

FROM base AS compute
CMD ["python", "/app/src/compute_main.py"]

FROM base AS sink
CMD ["python", "/app/src/sink_main.py"]
