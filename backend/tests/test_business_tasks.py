import pytest

from api.business_tasks import (
    build_instance_create_from_business_task,
    evaluate_business_objective,
)
from enums import DeploymentMode
from schemas import BusinessObjective, BusinessTaskCreate, RoutingResult


@pytest.mark.asyncio
async def test_build_instance_create_maps_routing_and_runtime_env():
    payload = BusinessTaskCreate(
        external_task_id="intent-001",
        task_type="low_latency_video_pipeline",
        modality="low_latency_forwarding",
        name="低时延视频转发",
        data_profile={"profile_id": "video_720p_frame_stream"},
        business_objective=BusinessObjective(
            metric_key="end_to_end_latency_ms",
            operator="<=",
            target_value=200,
            unit="ms",
        ),
        runtime_plan={"codec": "h264", "preset": "ultrafast"},
        routing_result=RoutingResult(
            strategy="completion_time_first",
            placements={
                "source": "node-a",
                "compute": "node-b",
                "sink": "node-c",
            },
            estimated_metric={
                "metric_key": "end_to_end_latency_ms",
                "metric_value": 180,
                "unit": "ms",
            },
        ),
        result_storage={
            "backend": "minio",
            "bucket": "task-results",
            "prefix": "intent-001/",
        },
    )

    # Use valid UUIDs to bypass hostname resolution in test
    uuid_a = "11111111-1111-1111-1111-111111111111"
    uuid_b = "22222222-2222-2222-2222-222222222222"
    uuid_c = "33333333-3333-3333-3333-333333333333"
    payload.routing_result.placements = {
        "source": uuid_a,
        "compute": uuid_b,
        "sink": uuid_c,
    }

    instance = await build_instance_create_from_business_task(
        db=None,
        payload=payload,
        template_id="template-video",
        role_node_names={
            "source": "source",
            "compute": "compute",
            "sink": "sink",
        },
    )

    assert instance.template_id == "template-video"
    assert instance.name == "低时延视频转发"
    # Business tasks always use SCHEDULED mode with APScheduler (auto_start=False)
    assert instance.deployment_mode == DeploymentMode.SCHEDULED
    assert instance.auto_start is False
    assert instance.scheduled_start_time is not None
    assert instance.scheduled_end_time is not None
    assert instance.keep_after_stop is False
    overrides = {item.template_node_name: item for item in instance.node_overrides}
    assert overrides["source"].node_id == uuid_a
    assert overrides["compute"].node_id == uuid_b
    assert overrides["sink"].node_id == uuid_c
    assert overrides["compute"].env["TASK_TYPE"] == "low_latency_video_pipeline"
    assert overrides["compute"].env["BUSINESS_OBJECTIVE"] == payload.business_objective.model_dump_json()
    assert overrides["compute"].env["RUNTIME_PLAN"] == '{"codec":"h264","preset":"ultrafast"}'


def test_evaluate_business_objective_handles_lower_is_better():
    evaluation = evaluate_business_objective(
        BusinessObjective(
            metric_key="end_to_end_latency_ms",
            operator="<=",
            target_value=200,
            unit="ms",
        ),
        actual_metric_key="end_to_end_latency_ms",
        actual_value=186.4,
        object_uris=["s3://task-results/instance-1/result.json"],
    )

    assert evaluation.business_success is True
    assert evaluation.failure_reason is None
    assert evaluation.object_uris == ["s3://task-results/instance-1/result.json"]


def test_evaluate_business_objective_rejects_metric_key_mismatch():
    evaluation = evaluate_business_objective(
        BusinessObjective(
            metric_key="end_to_end_latency_ms",
            operator="<=",
            target_value=200,
            unit="ms",
        ),
        actual_metric_key="compute_latency_ms",
        actual_value=100,
        object_uris=[],
    )

    assert evaluation.business_success is False
    assert "Metric key mismatch" in evaluation.failure_reason


def test_evaluate_higher_is_better_success():
    """effective_gflops >= target passes."""
    evaluation = evaluate_business_objective(
        BusinessObjective(
            metric_key="effective_gflops",
            operator=">=",
            target_value=100,
            unit="GFLOPS",
        ),
        actual_metric_key="effective_gflops",
        actual_value=120,
        object_uris=["s3://results/run-1/output.json"],
    )

    assert evaluation.business_success is True
    assert evaluation.failure_reason is None


def test_evaluate_higher_is_better_failure():
    """effective_gflops < target fails."""
    evaluation = evaluate_business_objective(
        BusinessObjective(
            metric_key="effective_gflops",
            operator=">=",
            target_value=100,
            unit="GFLOPS",
        ),
        actual_metric_key="effective_gflops",
        actual_value=80,
        object_uris=["s3://results/run-2/output.json"],
    )

    assert evaluation.business_success is False
    assert evaluation.failure_reason is not None


def test_evaluate_with_baseline_higher_is_better():
    """With baseline=200, actual=170 should pass (170 >= 200*0.8=160)."""
    evaluation = evaluate_business_objective(
        BusinessObjective(
            metric_key="effective_gflops",
            operator=">=",
            target_value=100,
            unit="GFLOPS",
        ),
        actual_metric_key="effective_gflops",
        actual_value=170,
        object_uris=["s3://results/run-3/output.json"],
        baseline_value=200,
    )

    assert evaluation.business_success is True
    assert evaluation.failure_reason is None
    assert evaluation.target_value == 160.0  # 200 * 0.8


def test_evaluate_with_baseline_higher_is_better_fail():
    """With baseline=200, actual=150 should fail (150 < 200*0.8=160)."""
    evaluation = evaluate_business_objective(
        BusinessObjective(
            metric_key="effective_gflops",
            operator=">=",
            target_value=100,
            unit="GFLOPS",
        ),
        actual_metric_key="effective_gflops",
        actual_value=150,
        object_uris=["s3://results/run-4/output.json"],
        baseline_value=200,
    )

    assert evaluation.business_success is False
    assert evaluation.failure_reason is not None
    assert evaluation.target_value == 160.0  # 200 * 0.8


def test_evaluate_with_baseline_lower_is_better():
    """With baseline=100, actual=110 should pass (110 <= 100/0.8=125)."""
    evaluation = evaluate_business_objective(
        BusinessObjective(
            metric_key="end_to_end_latency_ms",
            operator="<=",
            target_value=200,
            unit="ms",
        ),
        actual_metric_key="end_to_end_latency_ms",
        actual_value=110,
        object_uris=["s3://results/run-5/output.json"],
        baseline_value=100,
    )

    assert evaluation.business_success is True
    assert evaluation.failure_reason is None
    assert evaluation.target_value == 125.0  # 100 / 0.8


def test_evaluate_with_baseline_lower_is_better_fail():
    """With baseline=100, actual=130 should fail (130 > 100/0.8=125)."""
    evaluation = evaluate_business_objective(
        BusinessObjective(
            metric_key="end_to_end_latency_ms",
            operator="<=",
            target_value=200,
            unit="ms",
        ),
        actual_metric_key="end_to_end_latency_ms",
        actual_value=130,
        object_uris=["s3://results/run-6/output.json"],
        baseline_value=100,
    )

    assert evaluation.business_success is False
    assert evaluation.failure_reason is not None
    assert evaluation.target_value == 125.0  # 100 / 0.8


def test_evaluate_video_latency_uses_unified_capability_retention():
    """Video P90 latency uses the same >=80% capability retention rule."""
    evaluation = evaluate_business_objective(
        BusinessObjective(
            metric_key="frame_latency_p90_ms",
            operator="<=",
            target_value=200,
            unit="ms",
        ),
        actual_metric_key="frame_latency_p90_ms",
        actual_value=124,
        object_uris=["s3://results/run-video/output.json"],
        task_type="low_latency_video_pipeline",
        baseline_value=100,
    )

    assert evaluation.business_success is True
    assert evaluation.failure_reason is None
    assert evaluation.target_value == 125.0  # 100 / 0.8
