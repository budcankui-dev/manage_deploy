#!/usr/bin/env python3
"""Matmul pipeline sink: wait for result from compute via POST, then report metric."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.http_server import (
    get_listen_port,
    get_peer_url,
    post_json_to_peer,
    PostDataHandler,
    start_server,
    wait_for_data_handler,
)
from _common.reporter import report_metric


def _parse_objective() -> dict:
    raw = os.environ.get("BUSINESS_OBJECTIVE", "{}")
    return json.loads(raw) if raw else {}


def _maybe_upload_minio(instance_id: str, body: dict) -> str:
    """若配置了 MINIO_ACCESS_KEY 则上传 result.json，否则返回占位 URI。"""
    access = os.environ.get("MINIO_ACCESS_KEY") or os.environ.get("MINIO_ROOT_USER")
    secret = os.environ.get("MINIO_SECRET_KEY") or os.environ.get("MINIO_ROOT_PASSWORD")
    endpoint = os.environ.get("MINIO_ENDPOINT", "http://host.docker.internal:9000")
    bucket = os.environ.get("MINIO_BUCKET", "task-results")
    if not access or not secret:
        return f"s3://{bucket}/{instance_id}/result.json"

    try:
        from minio import Minio
    except ImportError:
        return f"s3://{bucket}/{instance_id}/result.json"

    host = endpoint.replace("http://", "").replace("https://", "")
    secure = endpoint.startswith("https://")
    client = Minio(host, access_key=access, secret_key=secret, secure=secure)
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    key = f"{instance_id}/result.json"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    from io import BytesIO

    client.put_object(bucket, key, BytesIO(data), length=len(data), content_type="application/json")
    return f"{endpoint.rstrip('/')}/{bucket}/{key}"


def main() -> int:
    port = get_listen_port("sink")
    print(f"SINK_STARTING port={port}", flush=True)

    # 启动 HTTP server 等待 compute 发来 result
    start_server(port, PostDataHandler)

    # 等待 compute POST result
    result = wait_for_data_handler(port, timeout_sec=180.0)
    print(f"SINK_GOT_RESULT latency_ms={result.get('compute_latency_ms')}", flush=True)

    objective = _parse_objective()
    metric_key = objective.get("metric_key") or "compute_latency_ms"
    latency_ms = float(result["compute_latency_ms"])
    instance_id = os.environ["TASK_INSTANCE_ID"]

    # 上报 metric（业务验收关键路径），MinIO 上传失败不阻塞
    # 白名单字段进入 metric.tags.result，用于前端展示
    METRIC_METADATA_KEYS = ("compute_latency_ms", "matrix_size", "batch_count", "seed", "result_preview")
    result_meta = {k: result[k] for k in METRIC_METADATA_KEYS if k in result}

    # MinIO 上传完整 result（用于前端展示），上传失败不阻塞
    try:
        upload_uri = _maybe_upload_minio(instance_id, result)
        print(f"SINK_MINIO uri={upload_uri}", flush=True)
    except Exception as exc:
        upload_uri = f"s3://{os.environ.get('MINIO_BUCKET', 'task-results')}/{instance_id}/result.json"
        print(f"SINK_MINIO_SKIP {exc}", flush=True)

    report_metric(
        metric_key,
        latency_ms,
        unit=objective.get("unit") or "ms",
        tags={
            "objects": [
                {
                    "name": "result.json",
                    "uri": upload_uri,
                    "content_type": "application/json",
                }
            ],
            "result": result_meta,
        },
    )
    print(f"SINK_DONE metric={metric_key} value={latency_ms}", flush=True)

    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"SINK_FAILED {exc}", flush=True)
        sys.exit(1)