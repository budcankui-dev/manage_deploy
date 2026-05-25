#!/usr/bin/env python3
"""Matmul pipeline sink: read result.json, report metric, optional MinIO upload."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

SCRATCH = Path("/scratch")
RESULT_FILE = SCRATCH / "result.json"

# 便于从 workers/ 目录直接 python 调试
if "/app" not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, "/app")

from _common.reporter import report_metric  # noqa: E402


def _wait_for_result(timeout_sec: int = 180) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if RESULT_FILE.is_file():
            return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
        time.sleep(0.5)
    raise TimeoutError(f"result.json not found under {SCRATCH}")


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
    SCRATCH.mkdir(parents=True, exist_ok=True)
    result = _wait_for_result()
    objective = _parse_objective()
    metric_key = objective.get("metric_key") or "compute_latency_ms"
    latency_ms = float(result["compute_latency_ms"])
    instance_id = os.environ["TASK_INSTANCE_ID"]

    # 先上报指标（业务验收关键路径），MinIO 上传失败不阻塞
    placeholder_uri = f"s3://{os.environ.get('MINIO_BUCKET', 'task-results')}/{instance_id}/result.json"
    report_metric(
        metric_key,
        latency_ms,
        unit=objective.get("unit") or "ms",
        tags={
            "objects": [
                {
                    "name": "result.json",
                    "uri": placeholder_uri,
                    "content_type": "application/json",
                }
            ],
            "result": result,
        },
    )
    print(f"SINK_DONE metric={metric_key} value={latency_ms}", flush=True)
    try:
        uri = _maybe_upload_minio(instance_id, result)
        print(f"SINK_MINIO uri={uri}", flush=True)
    except Exception as exc:
        print(f"SINK_MINIO_SKIP {exc}", flush=True)
    while True:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"SINK_FAILED {exc}", flush=True)
        sys.exit(1)
