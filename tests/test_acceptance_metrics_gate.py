import pytest

from scripts.acceptance_metrics_gate import (
    AcceptanceGateError,
    check_business_summary,
    check_intent_report,
)


def test_intent_gate_requires_full_dataset_and_target_accuracy():
    report = {"total": 359, "correct": 359, "accuracy": 1.0}

    with pytest.raises(AcceptanceGateError, match="样本数不足"):
        check_intent_report(report, min_total=360, min_accuracy=0.9)

    report = {"total": 360, "correct": 323, "accuracy": 323 / 360}

    with pytest.raises(AcceptanceGateError, match="准确率未达标"):
        check_intent_report(report, min_total=360, min_accuracy=0.9)


def test_intent_gate_accepts_qualified_report():
    result = check_intent_report(
        {"evaluation_id": "intent-eval-demo", "total": 360, "correct": 348, "accuracy": 348 / 360},
        min_total=360,
        min_accuracy=0.9,
    )

    assert result["passed"] is True
    assert result["evaluation_id"] == "intent-eval-demo"
    assert result["total"] == 360


def test_business_gate_requires_evaluable_count_and_success_rate():
    summary = [{"task_type": "high_throughput_matmul", "count": 30, "evaluated_count": 29, "success_count": 29}]

    with pytest.raises(AcceptanceGateError, match="没有单个路由策略分组达标"):
        check_business_summary(summary, "high_throughput_matmul", min_evaluated=30, min_success_rate=0.9)

    summary = [{"task_type": "high_throughput_matmul", "count": 30, "evaluated_count": 30, "success_count": 26}]

    with pytest.raises(AcceptanceGateError, match="没有单个路由策略分组达标"):
        check_business_summary(summary, "high_throughput_matmul", min_evaluated=30, min_success_rate=0.9)


def test_business_gate_accepts_qualified_summary():
    summary = [
        {
            "task_type": "high_throughput_matmul",
            "routing_strategy": "resource_guarantee",
            "count": 30,
            "evaluated_count": 30,
            "success_count": 27,
        },
    ]

    result = check_business_summary(summary, "high_throughput_matmul", min_evaluated=30, min_success_rate=0.9)

    assert result["passed"] is True
    assert result["routing_strategy"] == "resource_guarantee"
    assert result["evaluated_count"] == 30
    assert result["success_count"] == 27
    assert result["success_rate"] == 0.9


def test_business_gate_does_not_merge_multiple_strategy_groups():
    summary = [
        {
            "task_type": "high_throughput_matmul",
            "routing_strategy": "resource_guarantee",
            "count": 15,
            "evaluated_count": 15,
            "success_count": 15,
        },
        {
            "task_type": "high_throughput_matmul",
            "routing_strategy": "low_latency_forwarding",
            "count": 15,
            "evaluated_count": 15,
            "success_count": 15,
        },
    ]

    with pytest.raises(AcceptanceGateError, match="没有单个路由策略分组达标"):
        check_business_summary(summary, "high_throughput_matmul", min_evaluated=30, min_success_rate=0.9)
