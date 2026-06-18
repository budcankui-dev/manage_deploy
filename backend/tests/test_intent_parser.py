import pytest

from services.intent_parser import parse_intent
from services.intent_workflow import run_intent_workflow
from services.llm_intent_parser import _raw_to_parse_result


def test_parse_video_pipeline_uses_baseline_objective_even_when_user_mentions_latency():
    result = parse_intent("部署低时延视频转发，从 compute-1 到 compute-2，处理90帧，720p，30fps，现在开始跑2小时，端到端时延低于 200ms")
    assert result.task_type == "low_latency_video_pipeline"
    assert result.data_profile["frame_count"] == 90
    assert result.data_profile["resolution"] == "720p"
    assert result.data_profile["fps"] == 30
    assert result.business_objective["metric_key"] == "frame_latency_p90_ms"
    assert "target_value" not in result.business_objective
    assert result.parse_status == "valid"


def test_parse_low_latency_forwarding_strategy_is_distinct_from_fastest_completion():
    result = parse_intent("视频AI推理任务，从 compute-1 到 compute-2，处理90帧，720p，30fps，现在开始跑2小时，低时延策略")

    assert result.task_type == "low_latency_video_pipeline"
    assert result.modality == "低时延转发模态"
    assert result.runtime_plan["routing_strategy"] == "low_latency_forwarding"
    assert result.parse_status == "valid"


def test_task_type_forces_modality_mapping_even_if_user_mentions_other_modality():
    result = parse_intent("我想按高通量计算模态做一个视频AI推理任务，从 compute-1 到 compute-2，100帧，720p，30fps，现在开始跑2小时")

    assert result.task_type == "low_latency_video_pipeline"
    assert result.modality == "低时延转发模态"
    assert result.parse_status == "valid"


@pytest.mark.asyncio
async def test_runtime_settings_can_override_task_modality_mapping():
    runtime_settings = {
        "intent_parser_mode": "rule",
        "intent_rule_fallback_enabled": True,
        "task_modality_override_enabled": True,
        "task_modality_overrides": {
            "low_latency_video_pipeline": "确定性转发模态",
        },
    }

    result, _trace = await run_intent_workflow(
        "视频AI推理任务，从 compute-1 到 compute-2，100帧，720p，30fps，现在开始跑2小时",
        runtime_settings=runtime_settings,
    )

    assert result.task_type == "low_latency_video_pipeline"
    assert result.modality == "确定性转发模态"
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


def test_parse_half_hour_duration():
    result = parse_intent(
        "矩阵乘法任务，从 compute-1 到 compute-2，512阶矩阵，20批，立即执行半小时，希望成本更低",
        valid_nodes=["compute-1", "compute-2"],
    )

    assert result.parse_status == "valid"
    assert result.business_start_time is not None
    assert result.business_end_time is not None
    assert (result.business_end_time - result.business_start_time).total_seconds() == 30 * 60


def test_parse_rejects_unknown_node_and_keeps_draft_incomplete():
    result = parse_intent(
        "矩阵乘法任务，从 unknown-node 到 h2，1024阶矩阵，50批，现在开始跑2小时，资源保障策略",
        valid_nodes=["h1", "h2", "compute-1"],
    )

    assert result.parse_status == "incomplete"
    assert result.source_name is None
    assert result.destination_name == "h2"
    assert "源节点不存在：unknown-node" in result.validation_errors


def test_parse_multiturn_completion_merges_existing_draft():
    first = parse_intent(
        "视频AI推理任务，从 h1 到 h2，720p视频，100帧，现在开始跑2小时，低时延策略",
        valid_nodes=["h1", "h2"],
    )
    assert first.parse_status == "incomplete"
    assert any("帧率" in item for item in first.validation_errors)

    second = parse_intent(
        "补充帧率 30fps",
        existing_draft={
            "task_type": first.task_type,
            "modality": first.modality,
            "source_name": first.source_name,
            "destination_name": first.destination_name,
            "business_start_time": first.business_start_time,
            "business_end_time": first.business_end_time,
            "data_profile": first.data_profile,
            "business_objective": first.business_objective,
            "runtime_plan": first.runtime_plan,
        },
        valid_nodes=["h1", "h2"],
    )

    assert second.parse_status == "valid"
    assert second.data_profile["fps"] == 30
    assert second.source_name == "h1"
    assert second.destination_name == "h2"


def test_parse_rejects_unsupported_absolute_time_in_rule_parser():
    result = parse_intent(
        "矩阵乘法任务，从 h1 到 h2，1024阶矩阵，50批，2026-06-20 09:00开始，2026-06-20 11:00结束，资源保障策略",
        valid_nodes=["h1", "h2"],
    )

    assert result.parse_status == "incomplete"
    assert "业务开始时间（如：现在开始跑2小时）" in result.validation_errors
    assert "业务结束时间" in result.validation_errors


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


@pytest.mark.parametrize(
    ("utterance", "expected_strategy"),
    [
        ("从compute-1到h8跑 matmul，512x512，batch 20，现在开始跑2小时，成本优先省钱", "cost_priority"),
        ("创建低功耗边缘推理业务，业务源节点 compute-1，业务目的节点 h6，120帧，50W，立即运行60分钟，希望走低时延路由", "low_latency_forwarding"),
        ("提交一条随路计算工单：从业务源节点 compute-2 到业务目的节点 h11，执行 512 阶矩阵乘法 20 批，现在开始跑2小时，希望转发时延更低", "low_latency_forwarding"),
        ("创建高安全传输业务，业务源节点 compute-2，业务目的节点 h1，安全级别 high，马上开始跑3小时，优先保障端到端时延", "low_latency_forwarding"),
        ("帮我安排一条训练类智算任务，源终端 compute-1，目的终端 h2，数据集 5000 条样本，现在开始跑2小时，选择空闲节点负载均衡", "load_balance"),
        ("配电线路巡检稳定转发 source=compute-1 dest=h5, jitter=3ms, 现在开始跑2小时, 尽快完成", "fastest_completion"),
        ("请提交通用计算任务 source: compute-3 dest: h5, matrix_size=512, batch_count=20, 现在开始跑2小时, 优先完成计算", "fastest_completion"),
        ("大规模连接采集任务，从 compute-1 到 h4，接入 20000 个终端，马上开始跑3小时，没有特别偏好", "resource_guarantee"),
        ("高能效边缘推理任务，从 compute-2 到 h9，处理 120 帧，功耗 50W，立即运行60分钟，只要资源满足就行", "resource_guarantee"),
        ("智算中心模型训练任务，从 compute-3 到 compute-1，训练 5000 条样本，现在开始跑2小时，不需要额外倾向", "resource_guarantee"),
    ],
)
def test_llm_parse_result_uses_user_utterance_for_routing_strategy(utterance, expected_strategy):
    raw = {
        "task_type": "high_throughput_matmul",
        "source_name": "compute-1",
        "destination_name": "h1",
        "start_time": "now",
        "end_time": "2099-06-03T23:30:00",
        "matrix_size": 512,
        "batch_count": 20,
        "routing_strategy": "fastest_completion" if expected_strategy != "fastest_completion" else "cost_priority",
    }

    result = _raw_to_parse_result(raw, None, utterance=utterance)

    assert result.runtime_plan["routing_strategy"] == expected_strategy
