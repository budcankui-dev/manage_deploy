import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParseResult:
    task_type: str | None = None
    modality: str | None = None
    data_profile: dict[str, Any] = field(default_factory=dict)
    business_objective: dict[str, Any] = field(default_factory=dict)
    runtime_plan: dict[str, Any] = field(default_factory=dict)
    resource_requirement: dict[str, Any] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)
    parse_status: str = "incomplete"
    assistant_message: str = ""


def _extract_number(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _merge_draft(existing: dict[str, Any] | None, result: ParseResult) -> ParseResult:
    if not existing:
        return result
    if existing.get("task_type"):
        result.task_type = existing["task_type"]
    if existing.get("modality"):
        result.modality = existing["modality"]
    if existing.get("data_profile"):
        result.data_profile = {**result.data_profile, **existing["data_profile"]}
    if existing.get("business_objective"):
        result.business_objective = {**result.business_objective, **existing["business_objective"]}
    if existing.get("runtime_plan"):
        result.runtime_plan = {**result.runtime_plan, **existing["runtime_plan"]}
    if existing.get("resource_requirement"):
        result.resource_requirement = {**result.resource_requirement, **existing["resource_requirement"]}
    return result


def parse_intent(utterance: str, existing_draft: dict[str, Any] | None = None) -> ParseResult:
    text = utterance.strip()
    lower = text.lower()
    result = ParseResult()
    result = _merge_draft(existing_draft, result)

    if any(k in lower for k in ("视频", "video", "转发", "h264", "h.264", "编码")):
        result.task_type = result.task_type or "low_latency_video_pipeline"
        result.modality = result.modality or "low_latency_forwarding"
        result.data_profile.setdefault("profile_id", "video_720p_frame_stream")
        result.data_profile.setdefault("source", "preset")
        result.runtime_plan.setdefault("codec", "h264")
        result.runtime_plan.setdefault("preset", "ultrafast")
        result.runtime_plan.setdefault("process_mode", "streaming")
        latency = _extract_number(
            text,
            [
                r"(\d+(?:\.\d+)?)\s*ms",
                r"低于\s*(\d+(?:\.\d+)?)\s*毫秒",
                r"时延.*?(\d+(?:\.\d+)?)",
            ],
        )
        if latency is not None:
            result.business_objective = {
                "metric_key": "end_to_end_latency_ms",
                "operator": "<=",
                "target_value": latency,
                "unit": "ms",
            }
        elif not result.business_objective:
            result.validation_errors.append("缺少业务目标：端到端时延（如 200ms）")

    elif any(k in lower for k in ("矩阵", "matmul", "乘法", "吞吐")):
        result.task_type = result.task_type or "high_throughput_matmul"
        result.modality = result.modality or "high_throughput_compute"
        result.data_profile.setdefault("profile_id", "matmul_synthetic")
        result.data_profile.setdefault("source", "synthetic")
        throughput = _extract_number(
            text,
            [
                r"(\d+(?:\.\d+)?)\s*gflops",
                r"吞吐.*?(\d+(?:\.\d+)?)",
            ],
        )
        if throughput is not None:
            result.business_objective = {
                "metric_key": "throughput_gflops",
                "operator": "<=",
                "target_value": throughput,
                "unit": "GFLOPS",
            }
        elif not result.business_objective:
            result.validation_errors.append("缺少业务目标：吞吐（如 500 GFLOPS）")

    elif any(k in lower for k in ("大模型", "llm", "文本生成", "推理")):
        result.task_type = result.task_type or "llm_text_generation"
        result.modality = result.modality or "llm_inference"
        result.data_profile.setdefault("profile_id", "llm_prompt_synthetic")
        result.data_profile.setdefault("source", "synthetic")
        latency = _extract_number(
            text,
            [
                r"(\d+(?:\.\d+)?)\s*ms",
                r"首 token.*?(\d+(?:\.\d+)?)",
            ],
        )
        if latency is not None:
            result.business_objective = {
                "metric_key": "first_token_latency_ms",
                "operator": "<=",
                "target_value": latency,
                "unit": "ms",
            }
        elif not result.business_objective:
            result.validation_errors.append("缺少业务目标：首 token 时延（如 500ms）")

    if not result.task_type:
        result.validation_errors.append("无法识别任务类型，请说明视频转发、矩阵计算或大模型推理")
        result.parse_status = "incomplete"
        result.assistant_message = "我还不能确定任务类型。请说明是要做视频转发、矩阵计算还是大模型推理。"
        return result

    objective = result.business_objective
    if objective:
        target = objective.get("target_value")
        metric_key = objective.get("metric_key")
        if metric_key == "end_to_end_latency_ms" and target is not None and target < 10:
            result.parse_status = "rejected"
            result.validation_errors.append("端到端时延目标低于 10ms，当前不可行")
            result.assistant_message = "该时延目标不合理，请调整为更现实的目标（建议 >= 50ms）。"
            return result
        if metric_key == "first_token_latency_ms" and target is not None and target < 5:
            result.parse_status = "rejected"
            result.validation_errors.append("首 token 时延目标低于 5ms，当前不可行")
            result.assistant_message = "该时延目标不合理，请调整后再试。"
            return result

    if result.validation_errors:
        result.parse_status = "incomplete"
        result.assistant_message = "已识别部分参数，请补充：" + "；".join(result.validation_errors)
    else:
        result.parse_status = "valid"
        result.assistant_message = (
            f"已解析任务类型 {result.task_type}，业务目标 "
            f"{objective.get('metric_key')} <= {objective.get('target_value')}{objective.get('unit', '')}。"
            "请确认或补充参数后请求路由。"
        )

    return result


def validate_draft_fields(draft: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not draft.get("task_type"):
        errors.append("task_type 不能为空")
    if not draft.get("data_profile"):
        errors.append("data_profile 不能为空")
    objective = draft.get("business_objective") or {}
    if not objective.get("metric_key") or objective.get("target_value") is None:
        errors.append("business_objective 不完整")
    return errors
