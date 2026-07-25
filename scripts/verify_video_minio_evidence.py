#!/usr/bin/env python3
"""Verify the video-worker MinIO evidence contract with a self-cleaning prefix.

Usage:
  backend/venv/bin/python scripts/verify_video_minio_evidence.py

The script uses the configured MinIO endpoint and creates a unique temporary
instance prefix. It always removes only objects beneath that prefix.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

from minio import Minio


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "workers" / "low-latency-video" / "src"))
sys.path.insert(0, str(REPO_ROOT / "workers"))

from compute_main import upload_video_evidence  # noqa: E402


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _minio_client() -> tuple[Minio, str]:
    endpoint = os.environ["MINIO_ENDPOINT"]
    client = Minio(
        endpoint.removeprefix("http://").removeprefix("https://"),
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=endpoint.startswith("https://"),
    )
    return client, os.environ.get("MINIO_BUCKET", "task-results")


def main() -> int:
    _load_env_file(REPO_ROOT / "backend" / ".env")
    client, bucket = _minio_client()
    instance_id = f"verify-video-evidence-{uuid.uuid4()}"
    prefix = f"{instance_id}/video/"
    result = {
        "frame_latency_p90_ms": 12.3,
        "measured_frames": 2,
        "profile_id": "minio_contract_verification",
        "evidence_frames": [
            {
                "frame_index": 12,
                "latency_ms": 10.1,
                "label": "bottle",
                "label_zh": "瓶子",
                "confidence": 0.9,
                "content_type": "image/jpeg",
                "content": b"video-evidence-frame-12",
            },
            {
                "frame_index": 42,
                "latency_ms": 12.3,
                "label": "none",
                "label_zh": "无目标",
                "confidence": 0.0,
                "content_type": "image/jpeg",
                "content": b"video-evidence-frame-42",
            },
        ],
    }
    try:
        uploaded = upload_video_evidence(result, instance_id)
        keys = sorted(item.object_name for item in client.list_objects(bucket, prefix=prefix, recursive=True))
        manifest_key = f"{instance_id}/video/result.json"
        response = client.get_object(bucket, manifest_key)
        try:
            manifest = json.loads(response.read())
        finally:
            response.close()
            response.release_conn()
        expected = [
            f"{instance_id}/video/frames/000012.jpg",
            f"{instance_id}/video/frames/000042.jpg",
            manifest_key,
        ]
        assert keys == expected, keys
        assert uploaded["evidence_frame_count"] == 2
        assert manifest["schema_version"] == "video-evidence/v1"
        assert len(manifest["evidence_frames"]) == 2
        print("video_minio_evidence=ok")
        return 0
    finally:
        for item in client.list_objects(bucket, prefix=prefix, recursive=True):
            client.remove_object(bucket, item.object_name)
        if list(client.list_objects(bucket, prefix=prefix, recursive=True)):
            raise RuntimeError(f"Temporary MinIO evidence was not cleaned: {prefix}")


if __name__ == "__main__":
    raise SystemExit(main())
