from services.baseline_runner import _parse_benchmark_result, run_benchmark


def test_parse_benchmark_result_accepts_plain_json_line():
    logs = '{"benchmark_result": {"effective_gflops": 42.5}}\n'

    assert _parse_benchmark_result(logs) == 42.5


def test_parse_benchmark_result_accepts_docker_timestamp_prefix():
    logs = (
        '2026-06-03T15:29:00.659831763Z '
        '{"benchmark_result": {"effective_gflops": 39.8174}}\n'
    )

    assert _parse_benchmark_result(logs) == 39.8174


def test_parse_video_benchmark_metric():
    logs = '{"benchmark_result":{"frame_latency_p90_ms":12.5}}'

    assert _parse_benchmark_result(logs, "frame_latency_p90_ms") == 12.5


def test_video_baseline_local_fallback_reports_lower_is_better_metric():
    result = run_benchmark("low_latency_video_pipeline", runs=1)

    assert result["metric_key"] == "frame_latency_p90_ms"
    assert result["operator"] == "<="
    assert result["unit"] == "ms"
    assert result["baseline_value"] > 0
