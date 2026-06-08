from datetime import datetime, timedelta

from services.intent_batch_eval import score_parsed_result
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
