import pytest

from services.baseline_runner import _parse_benchmark_result, run_benchmark


def test_parse_benchmark_result_accepts_plain_json_line():
    logs = '{"benchmark_result": {"effective_gflops": 42.5, "backend": "cupy_gpu"}}\n'

    assert _parse_benchmark_result(logs) == 42.5


def test_parse_benchmark_result_accepts_docker_timestamp_prefix():
    logs = (
        '2026-06-03T15:29:00.659831763Z '
        '{"benchmark_result": {"effective_gflops": 39.8174, "backend": "cupy_gpu"}}\n'
    )

    assert _parse_benchmark_result(logs) == 39.8174


def test_parse_matmul_rejects_cpu_baseline():
    logs = '{"benchmark_result":{"effective_gflops":12.5,"backend":"numpy_cpu"}}'

    with pytest.raises(RuntimeError, match="矩阵计算基线未使用 GPU"):
        _parse_benchmark_result(logs, "effective_gflops")


def test_parse_video_benchmark_metric_accepts_gpu_yolo():
    logs = (
        '{"benchmark_result":{'
        '"frame_latency_p90_ms":12.5,'
        '"actual_backend":"onnxruntime_cuda",'
        '"device":"cuda:0",'
        '"model_name":"yolov5n"'
        "}}"
    )

    assert _parse_benchmark_result(logs, "frame_latency_p90_ms") == 12.5


def test_parse_video_rejects_cpu_or_surrogate_baseline():
    logs = (
        '{"benchmark_result":{'
        '"frame_latency_p90_ms":12.5,'
        '"actual_backend":"deterministic_surrogate",'
        '"device":"cpu",'
        '"model_name":"yolov5n"'
        "}}"
    )

    with pytest.raises(RuntimeError, match="视频基线未使用 GPU YOLO"):
        _parse_benchmark_result(logs, "frame_latency_p90_ms")


def test_matmul_baseline_local_fallback_requires_gpu(monkeypatch):
    monkeypatch.setenv("USE_GPU", "false")

    with pytest.raises(RuntimeError, match="矩阵计算基线未使用 GPU"):
        run_benchmark("high_throughput_matmul", runs=1)


def test_video_baseline_local_fallback_requires_gpu_yolo_path():
    with pytest.raises(RuntimeError, match="视频基线未使用 GPU YOLO"):
        run_benchmark("low_latency_video_pipeline", runs=1)


def test_video_baseline_metadata_is_lower_is_better():
    from services.baseline_runner import BENCHMARK_PROFILES

    profile = BENCHMARK_PROFILES["low_latency_video_pipeline"]
    assert profile["metric_key"] == "frame_latency_p90_ms"
    assert profile["operator"] == "<="
    assert profile["unit"] == "ms"
