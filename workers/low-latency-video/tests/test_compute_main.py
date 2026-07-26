import json

import compute_main


class FakeMinio:
    def __init__(self):
        self.objects = {}

    def bucket_exists(self, bucket):
        return True

    def put_object(self, bucket, key, data, length, content_type):
        self.objects[(bucket, key)] = {
            "content": data.read(),
            "content_type": content_type,
            "length": length,
        }

    def presigned_get_object(self, bucket, key, expires):
        return f"http://minio.example/{bucket}/{key}?expires={int(expires.total_seconds())}"


def test_upload_video_evidence_writes_manifest_and_every_measured_frame(monkeypatch):
    client = FakeMinio()
    monkeypatch.setenv("MINIO_BUCKET", "task-results")
    monkeypatch.setattr(compute_main, "_build_minio_client_from_env", lambda: client)
    result = {
        "frame_latency_p90_ms": 12.3,
        "measured_frames": 2,
        "annotated_frame_data_url": "data:image/jpeg;base64,should-not-leave-worker",
        "evidence_frames": [
            {
                "frame_index": 12,
                "latency_ms": 10.0,
                "label": "bottle",
                "label_zh": "瓶子",
                "confidence": 0.9,
                "content_type": "image/jpeg",
                "content": b"frame-12",
            },
            {
                "frame_index": 42,
                "latency_ms": 11.0,
                "label": "none",
                "label_zh": "无目标",
                "confidence": 0.0,
                "content_type": "image/jpeg",
                "content": b"frame-42",
            },
        ],
    }

    uploaded = compute_main.upload_video_evidence(result, "instance-1")

    assert uploaded["evidence_upload_status"] == "uploaded"
    assert uploaded["evidence_manifest_uri"] == "s3://task-results/instance-1/video/result.json"
    assert uploaded["evidence_frame_count"] == 2
    assert "annotated_frame_data_url" not in uploaded
    assert [(item["frame_index"], item["uri"]) for item in uploaded["evidence_frames"]] == [
        (12, "s3://task-results/instance-1/video/frames/000012.jpg"),
        (42, "s3://task-results/instance-1/video/frames/000042.jpg"),
    ]
    assert uploaded["evidence_frames"][0]["preview_url"].startswith("http://minio.example/")
    assert client.objects[("task-results", "instance-1/video/frames/000012.jpg")]["content"] == b"frame-12"
    manifest = json.loads(client.objects[("task-results", "instance-1/video/result.json")]["content"])
    assert manifest["schema_version"] == "video-evidence/v1"
    assert len(manifest["evidence_frames"]) == 2
    assert "annotated_frame_data_url" not in manifest["result"]


def test_progress_callback_payload_never_sends_base64_preview_frames():
    payload = compute_main._progress_callback_payload(
        {
            "frame_index": 12,
            "latency_ms": 10.0,
            "label": "bottle",
            "confidence": 0.9,
            "preview_frame": {"data_url": "data:image/jpeg;base64,not-for-network"},
        }
    )

    assert "preview_frames" not in payload["result"]
