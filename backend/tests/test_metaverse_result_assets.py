from __future__ import annotations

import sys
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.demo_assets import router
from config import settings


def test_metaverse_result_proxy_streams_only_allowed_minio_object(monkeypatch):
    calls: list[tuple] = []

    class FakeResponse:
        def __init__(self, data: bytes):
            self.data = data
            self.position = 0
            self.closed = False

        def read(self, length: int) -> bytes:
            chunk = self.data[self.position:self.position + length]
            self.position += len(chunk)
            return chunk

        def close(self):
            self.closed = True

        def release_conn(self):
            self.closed = True

    class FakeMinio:
        def __init__(self, host, *, access_key, secret_key, secure):
            calls.append(("init", host, access_key, secret_key, secure))

        def stat_object(self, bucket, key):
            calls.append(("stat", bucket, key))
            return types.SimpleNamespace(size=10)

        def get_object(self, bucket, key, *, offset, length):
            calls.append(("get", bucket, key, offset, length))
            return FakeResponse(b"0123456789"[offset:offset + length])

    monkeypatch.setitem(sys.modules, "minio", types.SimpleNamespace(Minio=FakeMinio))
    monkeypatch.setattr(settings, "minio_endpoint", "http://minio.example:9000")
    monkeypatch.setattr(settings, "minio_bucket", "task-results")
    monkeypatch.setattr(settings, "minio_access_key", "access")
    monkeypatch.setattr(settings, "minio_secret_key", "secret")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    instance_id = "11111111-1111-1111-1111-111111111111"
    response = client.get(f"/api/demo-assets/metaverse-results/{instance_id}/fusion-result.mp4")
    assert response.status_code == 200
    assert response.content == b"0123456789"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"].startswith("video/mp4")

    ranged = client.get(
        f"/api/demo-assets/metaverse-results/{instance_id}/fusion-result.mp4",
        headers={"Range": "bytes=2-5"},
    )
    assert ranged.status_code == 206
    assert ranged.content == b"2345"
    assert ranged.headers["content-range"] == "bytes 2-5/10"
    assert calls[-1] == ("get", "task-results", f"{instance_id}/metaverse/fusion-result.mp4", 2, 4)

    forbidden = client.get(f"/api/demo-assets/metaverse-results/{instance_id}/not-allowed.mp4")
    assert forbidden.status_code == 404
