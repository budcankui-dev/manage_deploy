from pathlib import Path

import video_core
from video_core import run_video_profile


def test_video_profile_reports_p90_latency():
    result = run_video_profile(
        {
            "frame_count": 90,
            "frame_stride": 30,
            "profile_id": "video_industrial_inspection_720p",
            "resolution": "720p",
            "fps": 30,
            "warmup_frames": 1,
            "measured_frames": 4,
            "work_units": 100,
            "seed": 7,
        }
    )

    assert result["frame_latency_p90_ms"] > 0
    assert result["frame_latency_max_ms"] >= result["frame_latency_p90_ms"]
    assert result["measured_frames"] == 4
    assert result["profile_id"] == "video_industrial_inspection_720p"
    assert result["resolution"] == "720p"
    assert result["fps"] == 30
    assert result["aggregation"] == "p90_after_warmup"
    assert result["actual_backend"] in {"onnxruntime_cuda", "opencv_dnn_cuda", "opencv_dnn_cpu", "cpu"}
    assert result["backend"] == result["actual_backend"]
    assert result["device"]
    assert isinstance(result["gpu_requested"], bool)
    assert isinstance(result["gpu_available"], bool)
    assert "gpu_error" in result
    assert result["annotated_frame_data_url"].startswith("data:image/")
    assert "annotated_frame_latency_ms" in result
    assert result["preview_frame_width"] > 0
    assert result["preview_frame_height"] > 0
    assert result["annotated_frame_overlay"] in {"zh_yolo_v1", "yolo_boxes_v1", "embedded_boxes_v1"}
    assert result["detection_count"] >= 1
    assert result["detections"]
    assert result["detections"][0]["label_zh"]
    assert result["detections"][0]["bbox_xyxy"]
    assert result["preview_frames"]
    assert len(result["preview_frames"]) <= 4
    assert result["preview_frames"][0]["data_url"].startswith("data:image/")
    assert "latency_ms" in result["preview_frames"][0]


def test_video_profile_emits_progress_without_changing_final_result(monkeypatch):
    events = []

    result = run_video_profile(
        {
            "inference_mode": "surrogate",
            "frame_count": 90,
            "frame_stride": 30,
            "profile_id": "video_industrial_inspection_720p",
            "resolution": "720p",
            "fps": 30,
            "warmup_frames": 1,
            "measured_frames": 3,
            "work_units": 100,
            "seed": 7,
        },
        progress_callback=events.append,
    )

    assert len(events) == 3
    assert all("latency_ms" in event for event in events)
    assert result["measured_frames"] == 3
    assert "frame_latency_p90_ms" in result


def test_asset_path_rejects_traversal(tmp_path):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()

    assert video_core._resolve_asset_path(asset_root, "demo.mp4") == asset_root / "demo.mp4"
    try:
        video_core._resolve_asset_path(asset_root, "../secret.mp4")
    except RuntimeError as exc:
        assert "escapes asset directory" in str(exc)
    else:
        raise AssertionError("expected traversal path to be rejected")


def test_dnn_backend_auto_prefers_cuda_when_gpu_requested(monkeypatch):
    class FakeDnn:
        DNN_BACKEND_CUDA = 1
        DNN_TARGET_CUDA = 2
        DNN_BACKEND_OPENCV = 3
        DNN_TARGET_CPU = 4

    class FakeCv2:
        dnn = FakeDnn()

    class FakeNet:
        def __init__(self):
            self.calls = []

        def setPreferableBackend(self, value):
            self.calls.append(("backend", value))

        def setPreferableTarget(self, value):
            self.calls.append(("target", value))

    monkeypatch.setattr(video_core, "cv2", FakeCv2())
    monkeypatch.setattr(video_core, "_gpu_available", lambda: True)
    monkeypatch.setattr(video_core, "_opencv_dnn_cuda_available", lambda: True)
    monkeypatch.setenv("GPU_DEVICE", "0")

    net = FakeNet()
    info = video_core._configure_dnn_backend(net, "auto", gpu_requested=True)

    assert info["actual_backend"] == "opencv_dnn_cuda"
    assert info["device"] == "cuda:0"
    assert info["gpu_requested"] is True
    assert info["gpu_available"] is True
    assert ("backend", FakeDnn.DNN_BACKEND_CUDA) in net.calls


def test_inference_backend_prefers_onnxruntime_cuda(monkeypatch):
    fake_session = object()

    monkeypatch.setattr(video_core, "_gpu_available", lambda: True)
    monkeypatch.setattr(video_core, "_create_ort_session", lambda model_path: (fake_session, None))
    monkeypatch.setenv("GPU_DEVICE", "1")

    info = video_core._configure_inference_backend(Path("model.onnx"), "auto", gpu_requested=True)

    assert info["actual_backend"] == "onnxruntime_cuda"
    assert info["device"] == "cuda:1"
    assert info["engine"] == "onnxruntime"
    assert info["session"] is fake_session
