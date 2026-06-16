from datetime import datetime, timedelta

from services.intent_batch_eval import batch_diagnostic, score_parsed_result
from services.intent_parser import ParseResult


def _parsed(**overrides):
    now = datetime(2026, 6, 8, 10, 0, 0)
    data = {
        "task_type": "high_throughput_matmul",
        "modality": "high_throughput_compute",
        "source_name": "compute-1",
        "destination_name": "compute-2",
        "business_start_time": now,
        "business_end_time": now + timedelta(minutes=120),
        "data_profile": {"matrix_size": 512, "batch_count": 20},
        "runtime_plan": {"routing_strategy": "resource_guarantee"},
        "parse_status": "valid",
    }
    data.update(overrides)
    return ParseResult(**data)


def test_score_normalizes_legacy_modality_code():
    result = score_parsed_result(
        _parsed(),
        {
            "task_type": "high_throughput_matmul",
            "modality": "高通量计算模态",
            "source_name": "compute-1",
            "destination_name": "compute-2",
            "parse_status": "valid",
            "data_profile": {"matrix_size": 512, "batch_count": 20},
            "runtime_plan": {"routing_strategy": "resource_guarantee"},
            "expected_time": {"duration_minutes": 120},
        },
    )

    assert result["match"] is True
    assert result["details"]["modality"] == {
        "expected": "高通量计算模态",
        "got": "high_throughput_compute",
    }


def test_score_ignores_top_level_fields_missing_from_expected():
    result = score_parsed_result(
        _parsed(),
        {
            "task_type": "high_throughput_matmul",
            "source_name": "compute-1",
            "destination_name": "compute-2",
            "parse_status": "valid",
            "data_profile": {"matrix_size": 512, "batch_count": 20},
            "runtime_plan": {"routing_strategy": "resource_guarantee"},
            "expected_time": {"duration_minutes": 120},
        },
    )

    assert result["match"] is True
    assert "modality" not in result["details"]


def test_batch_diagnostic_flags_long_running_zero_progress_job():
    now = datetime(2026, 6, 16, 12, 0, 0)
    diagnostic = batch_diagnostic(
        {
            "status": "in_progress",
            "created_at": (now - timedelta(hours=3)).isoformat(timespec="seconds"),
            "request_counts": {"total": 360, "completed": 0, "failed": 0},
        },
        now=now,
    )

    assert diagnostic is not None
    assert diagnostic["code"] == "dashscope_batch_zero_progress"
    assert diagnostic["level"] == "warning"


def test_batch_diagnostic_ignores_active_job_with_progress():
    now = datetime(2026, 6, 16, 12, 0, 0)
    diagnostic = batch_diagnostic(
        {
            "status": "in_progress",
            "created_at": (now - timedelta(hours=3)).isoformat(timespec="seconds"),
            "request_counts": {"total": 360, "completed": 12, "failed": 0},
        },
        now=now,
    )

    assert diagnostic is None
