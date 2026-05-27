"""意图解析模块。

定义 IntentParser Protocol 和多种实现：
- RuleBasedIntentParser：正则 + 关键词规则解析（当前主路径）
- MockIntentParser：单测和离线评测用
- LLMIntentParser：预留 LLM API 接口（第二阶段）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol


@dataclass
class ParseResult:
    task_type: str | None = None
    modality: str | None = None
    source_name: str | None = None
    destination_name: str | None = None
    business_start_time: datetime | None = None
    business_end_time: datetime | None = None
    data_profile: dict[str, Any] = field(default_factory=dict)
    business_objective: dict[str, Any] = field(default_factory=dict)
    runtime_plan: dict[str, Any] = field(default_factory=dict)
    resource_requirement: dict[str, Any] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)
    parse_status: str = "incomplete"
    assistant_message: str = ""
    parser_name: str = "rule_based"
    parser_version: str = "2.0"


class IntentParser(Protocol):
    def parse(self, message: str, context: dict[str, Any] | None = None) -> ParseResult: ...
    def validate(self, parsed: ParseResult) -> list[str]: ...
    def to_routing_payload(self, parsed: ParseResult, order_id: str, order_name: str) -> dict: ...


def _extract_number(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _extract_source_destination(text: str) -> tuple[str | None, str | None]:
    """从文本中提取源和目的节点名称。"""
    source = None
    destination = None
    patterns = [
        r"从\s*[\"']?(\S+?)[\"']?\s*到\s*[\"']?(\S+?)[\"']?(?:\s|$|，|,|。)",
        r"源[节点终端:：\s]*[\"']?(\S+?)[\"']?[,，\s]+目的[节点终端:：\s]*[\"']?(\S+?)[\"']?(?:\s|$|，|,|。)",
        r"source[:\s]+[\"']?(\S+?)[\"']?[,\s]+dest(?:ination)?[:\s]+[\"']?(\S+?)[\"']?(?:\s|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            source = match.group(1).strip("\"'")
            destination = match.group(2).strip("\"'")
            return source, destination

    src_patterns = [
        r"源[节点终端:：\s]*[\"']?(\S+?)[\"']?(?:\s|$|，|,|。)",
        r"source[:\s]+[\"']?(\S+?)[\"']?(?:\s|$|,)",
    ]
    dst_patterns = [
        r"目的[节点终端:：\s]*[\"']?(\S+?)[\"']?(?:\s|$|，|,|。)",
        r"dest(?:ination)?[:\s]+[\"']?(\S+?)[\"']?(?:\s|$|,)",
    ]
    for p in src_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            source = m.group(1).strip("\"'")
            break
    for p in dst_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            destination = m.group(1).strip("\"'")
            break
    return source, destination


def _extract_time(text: str) -> tuple[datetime | None, datetime | None]:
    """从文本中提取业务开始和结束时间。"""
    now = datetime.utcnow()
    start_time = None
    end_time = None

    if re.search(r"现在开始|立即|马上", text):
        start_time = now

    duration_match = re.search(r"(\d+)\s*(?:小时|h|hour)", text, re.IGNORECASE)
    if duration_match:
        hours = int(duration_match.group(1))
        if start_time:
            end_time = start_time + timedelta(hours=hours)
        else:
            start_time = now
            end_time = now + timedelta(hours=hours)

    min_match = re.search(r"(\d+)\s*(?:分钟|min|minute)", text, re.IGNORECASE)
    if min_match and not duration_match:
        minutes = int(min_match.group(1))
        if not start_time:
            start_time = now
        end_time = start_time + timedelta(minutes=minutes)

    return start_time, end_time


def _merge_draft(existing: dict[str, Any] | None, result: ParseResult) -> ParseResult:
    if not existing:
        return result
    if existing.get("task_type"):
        result.task_type = result.task_type or existing["task_type"]
    if existing.get("modality"):
        result.modality = result.modality or existing["modality"]
    if existing.get("source_name"):
        result.source_name = result.source_name or existing["source_name"]
    if existing.get("destination_name"):
        result.destination_name = result.destination_name or existing["destination_name"]
    if existing.get("business_start_time"):
        result.business_start_time = result.business_start_time or existing["business_start_time"]
    if existing.get("business_end_time"):
        result.business_end_time = result.business_end_time or existing["business_end_time"]
    if existing.get("data_profile"):
        result.data_profile = {**existing["data_profile"], **result.data_profile}
    if existing.get("business_objective"):
        result.business_objective = {**existing["business_objective"], **result.business_objective}
    if existing.get("runtime_plan"):
        result.runtime_plan = {**existing["runtime_plan"], **result.runtime_plan}
    if existing.get("resource_requirement"):
        result.resource_requirement = {**existing["resource_requirement"], **result.resource_requirement}
    return result


def parse_intent(utterance: str, existing_draft: dict[str, Any] | None = None) -> ParseResult:
    text = utterance.strip()
    lower = text.lower()
    result = ParseResult()
    result = _merge_draft(existing_draft, result)

    # 提取 source / destination
    src, dst = _extract_source_destination(text)
    if src:
        result.source_name = src
    if dst:
        result.destination_name = dst

    # 提取时间
    start_t, end_t = _extract_time(text)
    if start_t:
        result.business_start_time = start_t
    if end_t:
        result.business_end_time = end_t

    # 任务类型识别
    if any(k in lower for k in ("视频", "video", "转发", "h264", "h.264", "编码")):
        result.task_type = result.task_type or "low_latency_video_pipeline"
        result.modality = result.modality or "low_latency_forwarding"
        result.data_profile.setdefault("profile_id", "video_720p_frame_stream")
        result.data_profile.setdefault("source", "preset")
        result.runtime_plan.setdefault("codec", "h264")
        result.runtime_plan.setdefault("preset", "ultrafast")
        result.runtime_plan.setdefault("process_mode", "streaming")
        latency = _extract_number(text, [
            r"(\d+(?:\.\d+)?)\s*ms",
            r"低于\s*(\d+(?:\.\d+)?)\s*毫秒",
            r"时延.*?(\d+(?:\.\d+)?)",
        ])
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
        throughput = _extract_number(text, [
            r"(\d+(?:\.\d+)?)\s*gflops",
            r"吞吐.*?(\d+(?:\.\d+)?)",
        ])
        latency = _extract_number(text, [
            r"(\d+(?:\.\d+)?)\s*ms",
            r"延迟.*?(\d+(?:\.\d+)?)",
            r"时延.*?(\d+(?:\.\d+)?)",
        ])
        if throughput is not None:
            result.business_objective = {
                "metric_key": "throughput_gflops",
                "operator": "<=",
                "target_value": throughput,
                "unit": "GFLOPS",
            }
        elif latency is not None:
            result.business_objective = {
                "metric_key": "compute_latency_ms",
                "operator": "<=",
                "target_value": latency,
                "unit": "ms",
            }
        elif not result.business_objective:
            result.validation_errors.append("缺少业务目标：吞吐（如 500 GFLOPS）或延迟（如 60000ms）")

    elif any(k in lower for k in ("大模型", "llm", "文本生成", "推理")):
        result.task_type = result.task_type or "llm_text_generation"
        result.modality = result.modality or "llm_inference"
        result.data_profile.setdefault("profile_id", "llm_prompt_synthetic")
        result.data_profile.setdefault("source", "synthetic")
        latency = _extract_number(text, [
            r"(\d+(?:\.\d+)?)\s*ms",
            r"首 token.*?(\d+(?:\.\d+)?)",
        ])
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

    # 业务目标合理性校验
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

    # 必填字段检查
    missing = []
    if not result.source_name:
        missing.append("源节点名称（如：从 nodeA 到 nodeB）")
    if not result.destination_name:
        missing.append("目的节点名称")
    if not result.business_start_time:
        missing.append("业务开始时间（如：现在开始跑2小时）")
    if not result.business_end_time:
        missing.append("业务结束时间")

    all_errors = result.validation_errors + missing
    if all_errors:
        result.parse_status = "incomplete"
        result.validation_errors = all_errors
        result.assistant_message = "已识别部分参数，请补充：" + "；".join(all_errors)
    else:
        result.parse_status = "valid"
        obj = result.business_objective
        result.assistant_message = (
            f"已解析：任务类型 {result.task_type}，"
            f"从 {result.source_name} 到 {result.destination_name}，"
            f"业务目标 {obj.get('metric_key')} <= {obj.get('target_value')}{obj.get('unit', '')}。"
            "请确认或补充参数后请求路由。"
        )

    return result


def validate_draft_fields(draft: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not draft.get("task_type"):
        errors.append("task_type 不能为空")
    dp = draft.get("data_profile") or {}
    if not dp.get("matrix_size"):
        errors.append("矩阵规模(matrix_size)不能为空")
    if not dp.get("batch_count"):
        errors.append("批次数(batch_count)不能为空")
    if not draft.get("source_name"):
        errors.append("源节点不能为空")
    if not draft.get("destination_name"):
        errors.append("目的节点不能为空")
    if not draft.get("business_start_time"):
        errors.append("开始时间不能为空")
    if not draft.get("business_end_time"):
        errors.append("结束时间不能为空")
    rp = draft.get("runtime_plan") or {}
    if not rp.get("routing_strategy"):
        errors.append("路由策略不能为空")
    return errors