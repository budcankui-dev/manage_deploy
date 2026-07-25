from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


COMPUTE_PATH = Path(__file__).resolve().parents[1] / "src" / "compute_main.py"
SRC_DIR = COMPUTE_PATH.parent
WORKERS_DIR = COMPUTE_PATH.parents[3]


def _load_compute_module():
    sys.path.insert(0, str(SRC_DIR))
    sys.path.insert(0, str(WORKERS_DIR))
    spec = importlib.util.spec_from_file_location("metaverse_compute_main", COMPUTE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compute_archives_durable_metaverse_objects(monkeypatch, tmp_path):
    compute = _load_compute_module()
    calls: dict[str, object] = {}

    class FakeMinio:
        def __init__(self, host, *, access_key, secret_key, secure):
            calls["client"] = (host, access_key, secret_key, secure)

        def bucket_exists(self, bucket):
            calls["bucket_exists"] = bucket
            return False

        def make_bucket(self, bucket):
            calls["made_bucket"] = bucket

        def put_object(self, bucket, key, data, length, *, content_type):
            calls.setdefault("put", []).append((bucket, key, data.read(), length, content_type))

    monkeypatch.setitem(sys.modules, "minio", types.SimpleNamespace(Minio=FakeMinio))
    monkeypatch.setenv("MINIO_ENDPOINT", "http://minio.example:9000")
    monkeypatch.setenv("MINIO_BUCKET", "task-results")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")

    monkeypatch.setenv("TASK_INSTANCE_ID", "instance-123")
    monkeypatch.setenv("MANAGER_API_BASE", "http://manager:8181")
    archive = tmp_path / "fusion.mp4"
    archive.write_bytes(b"mp4")
    result = compute._archive_to_minio({
        "frame_latency_p90_ms": 12.3,
        "fps": 30,
        "fusion_archive_path": str(archive),
        "fusion_preview_jpeg": b"jpeg",
    })

    assert result["fusion_video_uri"] == "s3://task-results/instance-123/metaverse/fusion-result.mp4"
    assert result["fusion_preview_uri"] == "s3://task-results/instance-123/metaverse/fusion-preview.jpg"
    assert result["fusion_result_uri"] == "s3://task-results/instance-123/metaverse/result.json"
    assert result["fusion_video_url"] == "/api/demo-assets/metaverse-results/instance-123/fusion-result.mp4"
    assert not archive.exists()
    keys = [item[1] for item in calls["put"]]
    assert keys == [
        "instance-123/metaverse/fusion-result.mp4",
        "instance-123/metaverse/fusion-preview.jpg",
        "instance-123/metaverse/result.json",
    ]
    assert json.loads(calls["put"][2][2])["fusion_video_uri"] == result["fusion_video_uri"]


def test_compute_requires_minio_credentials(monkeypatch):
    compute = _load_compute_module()
    monkeypatch.delenv("MINIO_ACCESS_KEY", raising=False)
    monkeypatch.delenv("MINIO_ROOT_USER", raising=False)
    monkeypatch.delenv("MINIO_SECRET_KEY", raising=False)
    monkeypatch.delenv("MINIO_ROOT_PASSWORD", raising=False)

    with __import__("pytest").raises(RuntimeError, match="MinIO credentials"):
        compute._archive_to_minio({})
