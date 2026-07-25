from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


SINK_PATH = Path(__file__).resolve().parents[1] / "src" / "sink_main.py"
SRC_DIR = SINK_PATH.parent
WORKERS_DIR = SINK_PATH.parents[3]


def _load_sink_module():
    sys.path.insert(0, str(SRC_DIR))
    sys.path.insert(0, str(WORKERS_DIR))
    spec = importlib.util.spec_from_file_location("metaverse_sink_main", SINK_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upload_frame_sequence_to_minio_writes_expected_object(monkeypatch):
    sink = _load_sink_module()
    calls: dict[str, object] = {}

    class FakeMinio:
        def __init__(self, host, *, access_key, secret_key, secure):
            calls["client"] = (host, access_key, secret_key, secure)

        def bucket_exists(self, bucket):
            calls["bucket_exists"] = bucket
            return False

        def make_bucket(self, bucket):
            calls["made_bucket"] = bucket

        def put_object(self, bucket, key, data, *, length, content_type):
            calls["put"] = (bucket, key, data.read(), length, content_type)

    monkeypatch.setitem(sys.modules, "minio", types.SimpleNamespace(Minio=FakeMinio))
    monkeypatch.setenv("MINIO_ENDPOINT", "http://minio.example:9000")
    monkeypatch.setenv("MINIO_BUCKET", "task-results")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")

    result = sink._upload_frame_sequence_to_minio(
        "instance-123",
        {"fps": 30, "frame_count": 1, "frames": [{"data_url": "data:image/jpeg;base64,AA=="}]},
    )

    assert result == {
        "fusion_frame_sequence_uri": "s3://task-results/instance-123/metaverse-fusion-frames.json",
        "fusion_frame_sequence_storage": "minio",
    }
    bucket, key, raw, length, content_type = calls["put"]
    assert (bucket, key, content_type) == (
        "task-results",
        "instance-123/metaverse-fusion-frames.json",
        "application/json",
    )
    assert length == len(raw)
    assert json.loads(raw) == {
        "fps": 30,
        "frame_count": 1,
        "frames": [{"data_url": "data:image/jpeg;base64,AA=="}],
    }


def test_upload_frame_sequence_to_minio_skips_without_credentials(monkeypatch):
    sink = _load_sink_module()
    monkeypatch.delenv("MINIO_ACCESS_KEY", raising=False)
    monkeypatch.delenv("MINIO_ROOT_USER", raising=False)
    monkeypatch.delenv("MINIO_SECRET_KEY", raising=False)
    monkeypatch.delenv("MINIO_ROOT_PASSWORD", raising=False)

    assert sink._upload_frame_sequence_to_minio("instance-123", {"frames": []}) == {}
