from services.intent_parser import parse_intent


def test_parse_video_pipeline_extracts_latency():
    result = parse_intent("部署低时延视频转发，720p H264，端到端时延低于 200ms")
    assert result.task_type == "low_latency_video_pipeline"
    assert result.parse_status == "valid"
    assert result.business_objective["target_value"] == 200


def test_parse_rejects_unreasonable_latency():
    result = parse_intent("视频转发任务，端到端时延低于 1ms")
    assert result.parse_status == "rejected"
