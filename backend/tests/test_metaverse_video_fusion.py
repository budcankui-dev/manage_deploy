from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from api.business_tasks import _apply_video_gpu_success_guard, _result_matches_baseline_profile
from api.orders import BatchBenchmarkRequest
from schemas.task import BusinessObjectiveEvaluationResult
from services.baseline_runner import BENCHMARK_PROFILES, _validate_benchmark_result
from services.business_env import build_business_env
from services.intent_parser import parse_intent
from services.llm_intent_parser import _raw_to_parse_result
from services.modality_catalog import default_objective_for_task_type, modality_for_task_type
from services.resource_estimator import estimate_bandwidth_mbps, estimate_resources
from services.routing_payload_builder import build_routing_payload


def test_metaverse_intent_uses_fixed_dual_video_profile():
    result = parse_intent("元宇宙双路视频融合，从 h1 到 h2，1080p，180帧，30fps，现在开始跑2小时")

    assert result.task_type == "metaverse_video_fusion"
    assert result.modality == "低时延转发模态"
    assert result.data_profile["video0_asset"] == "cam0.mp4"
    assert result.data_profile["video1_asset"] == "cam1.mp4"
    assert result.data_profile["fusion_mode"] == "modnet_offline"
    assert result.data_profile["resolution"] == "720p"
    assert result.runtime_plan["routing_strategy"] == "low_latency_forwarding"


def test_llm_metaverse_intent_receives_fixed_dual_video_defaults():
    result = _raw_to_parse_result(
        {
            "task_type": "metaverse_video_fusion",
            "source_name": "h1",
            "destination_name": "h2",
            "start_time": "now",
            "duration_hours": 2,
        },
        existing_draft=None,
        utterance="元宇宙视频融合，从 h1 到 h2，现在开始跑2小时",
    )

    assert result.data_profile["frame_count"] == 180
    assert result.data_profile["video0_asset"] == "cam0.mp4"
    assert result.data_profile["fusion_mode"] == "modnet_offline"
    assert result.runtime_plan["routing_strategy"] == "low_latency_forwarding"


def test_metaverse_catalog_and_routing_resources_are_isolated():
    profile = {"frame_count": 180, "resolution": "1080p", "fps": 30, "frame_stride": 1}
    now = datetime(2026, 7, 18, 9, 0, 0)
    payload = build_routing_payload(
        order_id="metaverse-order",
        order_name="元宇宙融合",
        task_type="metaverse_video_fusion",
        modality=None,
        source_name="h1",
        destination_name="h2",
        business_start_time=now,
        business_end_time=now + timedelta(hours=2),
        data_profile=profile,
    )

    assert modality_for_task_type("metaverse_video_fusion") == "低时延转发模态"
    assert default_objective_for_task_type("metaverse_video_fusion")["metric_key"] == "frame_latency_p90_ms"
    assert estimate_resources("metaverse_video_fusion", profile)["compute"]["gpu_units"] == 1
    assert estimate_bandwidth_mbps("metaverse_video_fusion", profile) == 90
    assert payload["edges"][0]["bandwidth_mbps"] == 90
    assert payload["job_name"] == "元宇宙沉浸式交互"
    assert payload["modal"] == "低时延转发模态"
    assert payload["routing_strategy"] == "low_latency_forwarding"
    assert payload["policy_type"] == "LATENCY_CONSTRAINED"


def test_metaverse_720p_bandwidth_supports_concurrent_routes_and_explicit_override():
    profile = {"frame_count": 180, "resolution": "720p", "fps": 30, "frame_stride": 1}

    assert estimate_bandwidth_mbps("metaverse_video_fusion", profile) == 40
    assert estimate_bandwidth_mbps(
        "metaverse_video_fusion",
        {**profile, "bandwidth_mbps": 64},
    ) == 64


def test_metaverse_baseline_requires_cuda_modnet():
    valid = {
        "frame_latency_p90_ms": 42.1,
        "actual_backend": "torch_cuda",
        "device": "cuda:0",
        "model_name": "MODNet",
    }
    _validate_benchmark_result(valid, "frame_latency_p90_ms", "metaverse_video_fusion")

    invalid = {**valid, "actual_backend": "torch_cpu", "device": "cpu"}
    with pytest.raises(RuntimeError, match="GPU MODNet"):
        _validate_benchmark_result(invalid, "frame_latency_p90_ms", "metaverse_video_fusion")


def test_metaverse_profile_match_and_gpu_guard():
    env = BENCHMARK_PROFILES["metaverse_video_fusion"]["env"]
    metadata = {
        "frame_count": 180,
        "resolution": "720p",
        "fps": 30,
        "frame_stride": 1,
        "measured_frames": 170,
        "video0_asset": "cam0.mp4",
        "video1_asset": "cam1.mp4",
        "fusion_mode": "modnet_offline",
    }
    assert _result_matches_baseline_profile("metaverse_video_fusion", metadata)
    assert env["METAVERSE_VIDEO0_ASSET"] == metadata["video0_asset"]
    assert env["GPU_DEVICE"] == "0"

    evaluation = BusinessObjectiveEvaluationResult(
        task_type="metaverse_video_fusion",
        metric_key="frame_latency_p90_ms",
        actual_value=40,
        target_value=50,
        operator="<=",
        unit="ms",
        business_success=True,
    )
    _apply_video_gpu_success_guard(evaluation, {"actual_backend": "torch_cpu", "device": "cpu"})
    assert evaluation.business_success is False
    assert "GPU+MODNet" in evaluation.failure_reason


def test_compute_only_metaverse_receives_external_source_asset_url():
    order = SimpleNamespace(
        id="metaverse-order",
        runtime_config={
            "platform_deployment": {
                "mode": "user_access_demo",
                "deployable_roles": ["compute"],
                "external_endpoints": {
                    "source": {"business_ipv6": "3012:9::11", "business_port": 18821},
                },
            }
        },
    )

    env = build_business_env(
        order=order,
        business_task={"task_type": "metaverse_video_fusion"},
        task_role="compute",
    )

    assert env["PEER_SOURCE_URL"] == "http://[3012:9::11]:18821"


def test_metaverse_benchmark_defaults_to_latency_constrained_routing():
    request = BatchBenchmarkRequest(task_type="metaverse_video_fusion")

    assert request.routing_strategy == "low_latency_forwarding"
