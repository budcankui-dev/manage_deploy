FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir httpx==0.28.1

COPY _common /app/_common
COPY low-latency-video/src /app/src
ENV PYTHONPATH=/app/src:/app
CMD ["python3", "/app/src/source_main.py"]
