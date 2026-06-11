from services.intent_parser import parse_intent
from services.llm_intent_parser import _raw_to_parse_result


def test_parse_video_pipeline_extracts_latency():
    result = parse_intent("部署低时延视频转发，从 compute-1 到 compute-2，处理90帧，720p，30fps，现在开始跑2小时，端到端时延低于 200ms")
    assert result.task_type == "low_latency_video_pipeline"
    assert result.data_profile["frame_count"] == 90
    assert result.data_profile["resolution"] == "720p"
    assert result.data_profile["fps"] == 30
    assert result.business_objective["metric_key"] == "frame_latency_p90_ms"
    assert result.business_objective["target_value"] == 200
    assert result.parse_status == "valid"


def test_parse_llm_text_generation_extracts_tokens():
    result = parse_intent("大模型文本生成任务，从 compute-2 到 compute-3，prompt 512 tokens，生成 256 tokens，batch 2，现在开始跑2小时，成本优先")
    assert result.task_type == "llm_text_generation"
    assert result.data_profile["prompt_tokens"] == 512
    assert result.data_profile["max_new_tokens"] == 256
    assert result.data_profile["batch_size"] == 2
    assert result.runtime_plan["routing_strategy"] == "cost_priority"
    assert result.parse_status == "valid"


def test_parse_unknown_task_is_incomplete():
    result = parse_intent("帮我订外卖")
    assert result.task_type is None
    assert result.parse_status == "incomplete"
    assert "八类模态" in result.assistant_message


def test_parse_matmul_extracts_required_fields():
    result = parse_intent("矩阵乘法任务，从 compute-1 到 compute-3，1024阶矩阵，50批，现在开始跑2小时，完成时间优先")
    assert result.task_type == "high_throughput_matmul"
    assert result.parse_status == "valid"
    assert result.source_name == "compute-1"
    assert result.destination_name == "compute-3"
    assert result.data_profile["matrix_size"] == 1024
    assert result.data_profile["batch_count"] == 50
    assert result.runtime_plan["routing_strategy"] == "fastest_completion"


def test_llm_parse_result_normalizes_relative_duration_from_utterance():
    raw = {
        "task_type": "high_throughput_matmul",
        "source_name": "compute-1",
        "destination_name": "compute-2",
        "start_time": "2099-06-03T21:30:00",
        "end_time": "2099-06-03T23:30:00",
        "matrix_size": 512,
        "batch_count": 20,
        "routing_strategy": "resource_guarantee",
    }

    result = _raw_to_parse_result(raw, None, utterance="现在开始跑2小时")

    assert result.business_start_time is not None
    assert result.business_end_time is not None
    assert (result.business_end_time - result.business_start_time).total_seconds() == 2 * 60 * 60


def test_llm_parse_result_keeps_explicit_future_time_when_immediate_is_negated():
    raw = {
        "task_type": "high_throughput_matmul",
        "source_name": "compute-1",
        "destination_name": "compute-2",
        "start_time": "2099-06-03T21:30:00",
        "end_time": "2099-06-03T23:30:00",
        "matrix_size": 512,
        "batch_count": 20,
        "routing_strategy": "resource_guarantee",
    }

    result = _raw_to_parse_result(raw, None, utterance="不要立即开始，改成明天9点跑2小时")

    assert result.business_start_time.isoformat() == "2099-06-03T21:30:00"
    assert result.business_end_time.isoformat() == "2099-06-03T23:30:00"
