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


NODE_TOKEN = r"[A-Za-z0-9_.-]+"


def _extract_source_destination(text: str) -> tuple[str | None, str | None]:
    """从文本中提取源和目的节点名称。"""
    source = None
    destination = None
    patterns = [
        rf"从\s*[\"']?({NODE_TOKEN})[\"']?\s*到\s*[\"']?({NODE_TOKEN})[\"']?",
        rf"({NODE_TOKEN})\s*(?:->|→)\s*({NODE_TOKEN})",
        rf"(?:业务)?源(?:节点|终端)?\s*(?:是|为|=|:|：)?\s*[\"']?({NODE_TOKEN})[\"']?.*?(?:业务)?目的(?:节点|终端|地)?\s*(?:是|为|=|:|：)?\s*[\"']?({NODE_TOKEN})[\"']?",
        rf"(?:src|source)\s*[:=]\s*[\"']?({NODE_TOKEN})[\"']?.*?(?:dst|dest|destination)\s*[:=]\s*[\"']?({NODE_TOKEN})[\"']?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            source = match.group(1).strip("\"'")
            destination = match.group(2).strip("\"'")
            return source, destination

    src_patterns = [
        rf"从\s*[\"']?({NODE_TOKEN})[\"']?\s*出发",
        rf"(?:业务)?源(?:节点|终端)?\s*(?:是|为|=|:|：)?\s*[\"']?({NODE_TOKEN})[\"']?",
        rf"(?:src|source)\s*[:=]\s*[\"']?({NODE_TOKEN})[\"']?",
    ]
    dst_patterns = [
        rf"(?:业务)?目的(?:节点|终端|地)?\s*(?:是|为|=|:|：)?\s*[\"']?({NODE_TOKEN})[\"']?",
        rf"(?:dst|dest|destination)\s*[:=]\s*[\"']?({NODE_TOKEN})[\"']?",
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


def _extract_matrix_size(text: str) -> int | None:
    patterns = [
        r"(\d{3,5})\s*(?:阶|维)\s*矩阵",
        r"矩阵\s*(?:规模|大小)?\s*[:：]?\s*(\d{3,5})",
        r"(\d{3,5})\s*[x×]\s*\1",
        r"(?:规模|大小|size)\s*[:=：]?\s*(\d{3,5})",
        r"matrix\s*[:=]?\s*(\d{3,5})",
        r"matrix[_\s-]*size\s*[:=]\s*(\d{3,5})",
    ]
    value = _extract_number(text, patterns)
    return int(value) if value is not None else None


def _extract_batch_count(text: str) -> int | None:
    patterns = [
        r"(\d{1,4})\s*(?:批|批次|个批次)",
        r"批次数\s*[:：]?\s*(\d{1,4})",
        r"batch\s+(\d{1,4})",
        r"batch(?:_count)?\s*[:=]\s*(\d{1,4})",
        r"batches\s*[:=]\s*(\d{1,4})",
    ]
    value = _extract_number(text, patterns)
    return int(value) if value is not None else None


def _extract_frame_count(text: str) -> int | None:
    patterns = [
        r"(\d{1,5})\s*帧",
        r"frames?\s*[:=]?\s*(\d{1,5})",
        r"frame_count\s*[:=]\s*(\d{1,5})",
    ]
    value = _extract_number(text, patterns)
    return int(value) if value is not None else None


def _extract_fps(text: str) -> int | None:
    patterns = [
        r"(\d{1,3})\s*fps",
        r"fps\s*[:=]\s*(\d{1,3})",
        r"帧率\s*[:：]?\s*(\d{1,3})",
    ]
    value = _extract_number(text, patterns)
    return int(value) if value is not None else None


def _extract_resolution(text: str) -> str | None:
    match = re.search(r"(720p|1080p|4k|8k)", text, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_prompt_tokens(text: str) -> int | None:
    patterns = [
        r"prompt[_\s-]*tokens\s*[:=]\s*(\d{1,6})",
        r"prompt\s*(\d{1,6})\s*tokens?",
        r"输入\s*(\d{1,6})\s*tokens?",
    ]
    value = _extract_number(text, patterns)
    return int(value) if value is not None else None


def _extract_max_new_tokens(text: str) -> int | None:
    patterns = [
        r"max[_\s-]*new[_\s-]*tokens\s*[:=]\s*(\d{1,6})",
        r"生成\s*(\d{1,6})\s*tokens?",
        r"输出\s*(\d{1,6})\s*tokens?",
    ]
    value = _extract_number(text, patterns)
    return int(value) if value is not None else None


def _extract_llm_batch_size(text: str) -> int | None:
    patterns = [
        r"batch[_\s-]*size\s*[:=]?\s*(\d{1,4})",
        r"batch\s*[:=]\s*(\d{1,4})",
        r"batch\s+(\d{1,4})",
        r"批大小\s*[:：]?\s*(\d{1,4})",
    ]
    value = _extract_number(text, patterns)
    return int(value) if value is not None else None


def _extract_routing_strategy(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in ("最快", "尽快", "完成时间", "高性能", "fast")):
        return "fastest_completion"
    if any(k in lower for k in ("负载", "空闲", "均衡", "load")):
        return "load_balance"
    if any(k in lower for k in ("成本", "省钱", "便宜", "cost")):
        return "cost_priority"
    return "resource_guarantee"


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


def parse_intent(
    utterance: str,
    existing_draft: dict[str, Any] | None = None,
    valid_nodes: list[str] | None = None,
) -> ParseResult:
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

    if any(k in lower for k in ("矩阵", "matmul", "matrix_size", "matrix", "乘法", "吞吐")):
        result.task_type = result.task_type or "high_throughput_matmul"
        result.modality = result.modality or "high_throughput_compute"
        result.data_profile.setdefault("profile_id", "matmul_synthetic")
        result.data_profile.setdefault("source", "synthetic")
        matrix_size = _extract_matrix_size(text)
        batch_count = _extract_batch_count(text)
        if matrix_size is not None:
            result.data_profile["matrix_size"] = matrix_size
        if batch_count is not None:
            result.data_profile["batch_count"] = batch_count
        result.runtime_plan.setdefault("routing_strategy", _extract_routing_strategy(text))
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
                "metric_key": "effective_gflops",
                "operator": ">=",
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
            result.business_objective = {
                "metric_key": "effective_gflops",
                "operator": ">=",
                "unit": "GFLOPS",
            }
    elif any(k in lower for k in ("视频", "video", "帧", "fps", "低时延", "低延时")):
        result.task_type = result.task_type or "low_latency_video_pipeline"
        result.modality = result.modality or "low_latency_forwarding"
        result.data_profile.setdefault("profile_id", "video_synthetic")
        result.data_profile.setdefault("source", "synthetic")
        frame_count = _extract_frame_count(text)
        fps = _extract_fps(text)
        resolution = _extract_resolution(text)
        if frame_count is not None:
            result.data_profile["frame_count"] = frame_count
        if fps is not None:
            result.data_profile["fps"] = fps
        if resolution is not None:
            result.data_profile["resolution"] = resolution
        result.runtime_plan.setdefault("routing_strategy", _extract_routing_strategy(text))
        latency = _extract_number(text, [
            r"(?:端到端)?(?:时延|延迟)\s*(?:低于|低于|不超过|小于|<=|≤)\s*(\d+(?:\.\d+)?)\s*ms",
            r"(\d+(?:\.\d+)?)\s*ms\s*(?:以内|以下)",
        ])
        result.business_objective = {
            "metric_key": "frame_latency_p90_ms",
            "operator": "<=",
            "unit": "ms",
        }
        if latency is not None:
            result.business_objective["target_value"] = latency
    elif any(k in lower for k in ("llm", "大模型", "文本生成", "token", "prompt", "模型训练", "文本模型")):
        result.task_type = result.task_type or "llm_text_generation"
        result.modality = result.modality or "llm_text"
        result.data_profile.setdefault("profile_id", "llm_synthetic")
        result.data_profile.setdefault("source", "synthetic")
        prompt_tokens = _extract_prompt_tokens(text)
        max_new_tokens = _extract_max_new_tokens(text)
        batch_size = _extract_llm_batch_size(text)
        if prompt_tokens is not None:
            result.data_profile["prompt_tokens"] = prompt_tokens
        if max_new_tokens is not None:
            result.data_profile["max_new_tokens"] = max_new_tokens
        if batch_size is not None:
            result.data_profile["batch_size"] = batch_size
        result.runtime_plan.setdefault("routing_strategy", _extract_routing_strategy(text))
        throughput = _extract_number(text, [
            r"(\d+(?:\.\d+)?)\s*tokens?/s",
            r"吞吐.*?(\d+(?:\.\d+)?)",
            r"生成速率.*?(\d+(?:\.\d+)?)",
        ])
        result.business_objective = {
            "metric_key": "tokens_per_second",
            "operator": ">=",
            "unit": "tokens/s",
        }
        if throughput is not None:
            result.business_objective["target_value"] = throughput

    if not result.task_type:
        result.validation_errors.append("无法识别为已支持的业务任务")
        result.parse_status = "incomplete"
        result.assistant_message = "当前支持矩阵乘法计算、低时延视频链路、LLM 文本生成三类任务。请说明任务类型、源节点、目的节点和开始/结束时间。"
        return result

    # 业务目标合理性校验
    objective = result.business_objective
    if objective:
        target = objective.get("target_value")
        metric_key = objective.get("metric_key")
        if metric_key == "effective_gflops" and target is not None and target <= 0:
            result.parse_status = "rejected"
            result.validation_errors.append("计算吞吐目标必须大于 0")
            result.assistant_message = "计算吞吐目标必须大于 0，请调整后再试。"
            return result
        if metric_key == "frame_latency_p90_ms" and target is not None and target < 10:
            result.parse_status = "rejected"
            result.validation_errors.append("视频帧时延目标不能低于 10ms")
            result.assistant_message = "视频帧时延目标不能低于 10ms，请调整为可验收的目标。"
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
    if result.task_type == "high_throughput_matmul":
        if not result.data_profile.get("matrix_size"):
            missing.append("矩阵规模（如：1024阶矩阵）")
        if not result.data_profile.get("batch_count"):
            missing.append("批次数（如：50批）")
    elif result.task_type == "low_latency_video_pipeline":
        if not result.data_profile.get("frame_count"):
            missing.append("视频帧数（如：90帧）")
        if not result.data_profile.get("resolution"):
            missing.append("视频分辨率（如：1080p）")
        if not result.data_profile.get("fps"):
            missing.append("帧率（如：30fps）")
    elif result.task_type == "llm_text_generation":
        if not result.data_profile.get("prompt_tokens"):
            missing.append("输入 token 数（如：prompt 512 tokens）")
        if not result.data_profile.get("max_new_tokens"):
            missing.append("生成 token 数（如：生成 256 tokens）")
        if not result.data_profile.get("batch_size"):
            missing.append("批大小（如：batch_size=2）")
    if not result.runtime_plan.get("routing_strategy"):
        result.runtime_plan["routing_strategy"] = "resource_guarantee"
    if valid_nodes:
        valid_node_set = set(valid_nodes)
        if result.source_name and result.source_name not in valid_node_set:
            missing.append(f"源节点不存在：{result.source_name}")
            result.source_name = None
        if result.destination_name and result.destination_name not in valid_node_set:
            missing.append(f"目的节点不存在：{result.destination_name}")
            result.destination_name = None

    all_errors = result.validation_errors + missing
    if all_errors:
        result.parse_status = "incomplete"
        result.validation_errors = all_errors
        result.assistant_message = "已识别部分参数，请补充：" + "；".join(all_errors)
    else:
        result.parse_status = "valid"
        obj = result.business_objective
        op = obj.get("operator", ">=")
        target = obj.get("target_value")
        target_text = f" {op} {target}{obj.get('unit', '')}" if target is not None else "按节点历史基线判定"
        result.assistant_message = (
            f"已解析：任务类型 {result.task_type}，"
            f"从 {result.source_name} 到 {result.destination_name}，"
            f"业务目标 {obj.get('metric_key')}{target_text}。"
            "请确认或补充参数后请求路由。"
        )

    return result


def validate_draft_fields(draft: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    task_type = draft.get("task_type")
    if not task_type:
        errors.append("task_type 不能为空")
    dp = draft.get("data_profile") or {}
    if task_type == "high_throughput_matmul":
        if not dp.get("matrix_size"):
            errors.append("矩阵规模(matrix_size)不能为空")
        if not dp.get("batch_count"):
            errors.append("批次数(batch_count)不能为空")
    elif task_type == "low_latency_video_pipeline":
        if not dp.get("frame_count"):
            errors.append("视频帧数(frame_count)不能为空")
        if not dp.get("resolution"):
            errors.append("分辨率(resolution)不能为空")
        if not dp.get("fps"):
            errors.append("帧率(fps)不能为空")
    elif task_type == "llm_text_generation":
        if not dp.get("prompt_tokens"):
            errors.append("输入token数(prompt_tokens)不能为空")
        if not dp.get("max_new_tokens"):
            errors.append("生成token数(max_new_tokens)不能为空")
        if not dp.get("batch_size"):
            errors.append("批大小(batch_size)不能为空")
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
