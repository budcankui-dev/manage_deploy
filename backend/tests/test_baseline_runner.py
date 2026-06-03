from services.baseline_runner import _parse_benchmark_result


def test_parse_benchmark_result_accepts_plain_json_line():
    logs = '{"benchmark_result": {"effective_gflops": 42.5}}\n'

    assert _parse_benchmark_result(logs) == 42.5


def test_parse_benchmark_result_accepts_docker_timestamp_prefix():
    logs = (
        '2026-06-03T15:29:00.659831763Z '
        '{"benchmark_result": {"effective_gflops": 39.8174}}\n'
    )

    assert _parse_benchmark_result(logs) == 39.8174
