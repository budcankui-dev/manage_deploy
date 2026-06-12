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
from zoneinfo import ZoneInfo

from services.modality_catalog import default_objective_for_task_type, modality_for_task_type, task_name_for_task_type


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
        rf"从\s*[\"']?({NODE_TOKEN})[\"']?\s*发起到\s*[\"']?({NODE_TOKEN})[\"']?\s*汇总",
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
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
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
    if any(k in lower for k in ("最快", "更快", "尽快", "完成时间", "高性能", "性能更高", "性能优先", "处理速度", "吞吐性能", "少排队", "尽早跑完", "低时延", "fast")):
        return "fastest_completion"
    if any(k in lower for k in ("负载", "空闲", "均衡", "竞争少", "低负载", "避开高负载", "抢资源", "均摊", "更平衡", "load")):
        return "load_balance"
    if any(k in lower for k in ("成本", "省钱", "便宜", "少占资源", "低成本", "费用", "省资源", "经济型", "cost")):
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

    if any(k in lower for k in ("矩阵", "matmul", "matrix_size", "matrix", "乘法")):
        result.task_type = result.task_type or "high_throughput_matmul"
        result.modality = result.modality or modality_for_task_type(result.task_type)
        result.data_profile.setdefault("profile_id", "matmul_synthetic")
        result.data_profile.setdefault("source", "synthetic")
        matrix_size = _extract_matrix_size(text)
        batch_count = _extract_batch_count(text)
        if matrix_size is not None:
            result.data_profile["matrix_size"] = matrix_size
        if batch_count is not None:
            result.data_profile["batch_count"] = batch_count
        result.runtime_plan.setdefault("routing_strategy", _extract_routing_strategy(text))
        if not result.business_objective:
            result.business_objective = {
                "metric_key": "effective_gflops",
                "operator": ">=",
                "unit": "GFLOPS",
            }
    elif any(k in lower for k in ("视频", "video", "帧", "fps", "低时延视频", "低延时视频")) and not any(
        k in lower for k in (
            "高能效", "边缘计算", "边缘推理", "低功耗", "输电线路巡检", "就近处理",
            "功耗", "能耗", "轻量识别", "巡检图片", "高安全", "安全传输", "加密", "敏感", "安全等级",
        )
    ):
        result.task_type = result.task_type or "low_latency_video_pipeline"
        result.modality = result.modality or modality_for_task_type(result.task_type)
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
        result.business_objective = {
            "metric_key": "frame_latency_p90_ms",
            "operator": "<=",
            "unit": "ms",
        }
    elif any(k in lower for k in ("llm", "大模型", "文本生成", "token", "prompt")):
        result.task_type = result.task_type or "llm_text_generation"
        result.modality = result.modality or modality_for_task_type(result.task_type)
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
    elif any(k in lower for k in ("智算中心", "智算", "模型训练", "训练任务", "训练类", "样本数", "训练样本", "神经网络训练", "训练吞吐")):
        result.task_type = result.task_type or "ai_model_training"
        result.modality = result.modality or modality_for_task_type(result.task_type)
        result.data_profile.setdefault("profile_id", "ai_training_default")
        result.data_profile.setdefault("source", "synthetic")
        result.data_profile.setdefault("sample_count", int(_extract_number(text, [
            r"(\d{2,7})\s*(?:条)?样本",
            r"样本数\s*[:：]?\s*(\d{2,7})",
            r"训练样本\s*[:：]?\s*(\d{2,7})",
            r"samples?\s*[:=]?\s*(\d{2,7})",
        ]) or 10000))
        result.runtime_plan.setdefault("routing_strategy", _extract_routing_strategy(text))
        result.business_objective = result.business_objective or default_objective_for_task_type(result.task_type)
    elif any(k in lower for k in ("分布式存算", "存算", "视联网", "就近计算", "多节点存储", "数据拉取")):
        result.task_type = result.task_type or "distributed_storage_compute"
        result.modality = result.modality or modality_for_task_type(result.task_type)
        result.data_profile.setdefault("profile_id", "distributed_storage_default")
        result.data_profile.setdefault("source", "synthetic")
        result.data_profile.setdefault("data_size_gb", int(_extract_number(text, [r"(\d{1,5})\s*(?:gb|GB|g|G|吉)"]) or 100))
        result.runtime_plan.setdefault("routing_strategy", _extract_routing_strategy(text))
        result.business_objective = result.business_objective or default_objective_for_task_type(result.task_type)
    elif any(k in lower for k in ("大规模连接", "大规模接入", "海量连接", "海量接入", "虚拟电厂", "终端接入", "连接数", "并发连接", "终端上报", "设备连接")):
        result.task_type = result.task_type or "massive_connection_collect"
        result.modality = result.modality or modality_for_task_type(result.task_type)
        result.data_profile.setdefault("profile_id", "massive_connection_default")
        result.data_profile.setdefault("source", "synthetic")
        result.data_profile.setdefault("connection_count", int(_extract_number(text, [
            r"(\d{2,7})\s*(?:个)?(?:终端|连接|用户|设备)",
            r"连接数\s*[:：]?\s*(\d{2,7})",
            r"并发连接\s*[:：]?\s*(\d{2,7})",
        ]) or 10000))
        result.runtime_plan.setdefault("routing_strategy", _extract_routing_strategy(text))
        result.business_objective = result.business_objective or default_objective_for_task_type(result.task_type)
    elif any(k in lower for k in ("确定性转发", "确定性", "抖动", "配电线路", "稳定转发")):
        result.task_type = result.task_type or "deterministic_forwarding"
        result.modality = result.modality or modality_for_task_type(result.task_type)
        result.data_profile.setdefault("profile_id", "deterministic_forwarding_default")
        result.data_profile.setdefault("source", "synthetic")
        result.data_profile.setdefault("max_jitter_ms", int(_extract_number(text, [
            r"抖动.*?(\d{1,4})\s*ms",
            r"jitter\s*(?:[:=]?|控制在)\s*(\d{1,4})\s*ms",
        ]) or 5))
        result.runtime_plan.setdefault("routing_strategy", _extract_routing_strategy(text))
        result.business_objective = result.business_objective or default_objective_for_task_type(result.task_type)
    elif any(k in lower for k in ("高能效", "边缘计算", "边缘推理", "低功耗", "输电线路巡检", "就近处理", "轻量识别", "巡检图片", "能耗")):
        result.task_type = result.task_type or "energy_efficient_edge_inference"
        result.modality = result.modality or modality_for_task_type(result.task_type)
        result.data_profile.setdefault("profile_id", "edge_inference_default")
        result.data_profile.setdefault("source", "synthetic")
        result.data_profile.setdefault("frame_count", int(_extract_frame_count(text) or 90))
        result.data_profile.setdefault("power_budget_w", int(_extract_number(text, [r"(\d{1,4})\s*w", r"功耗.*?(\d{1,4})", r"能耗.*?(\d{1,4})"]) or 50))
        result.runtime_plan.setdefault("routing_strategy", _extract_routing_strategy(text))
        result.business_objective = result.business_objective or default_objective_for_task_type(result.task_type)
    elif any(k in lower for k in ("高安全", "安全传输", "加密", "低空远程", "敏感数据", "安全回传")):
        result.task_type = result.task_type or "secure_transmission"
        result.modality = result.modality or modality_for_task_type(result.task_type)
        result.data_profile.setdefault("profile_id", "secure_transmission_default")
        result.data_profile.setdefault("source", "synthetic")
        result.data_profile.setdefault("security_level", "high")
        result.runtime_plan.setdefault("routing_strategy", _extract_routing_strategy(text))
        result.business_objective = result.business_objective or default_objective_for_task_type(result.task_type)
    if not result.task_type:
        result.validation_errors.append("无法识别为已支持的业务任务")
        result.parse_status = "incomplete"
        result.assistant_message = "当前可解析矩阵计算、视频推理和八类模态测试样本。请说明任务类型、源节点、目的节点和开始/结束时间。"
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
            f"已解析：任务类型 {task_name_for_task_type(result.task_type)}，"
            f"所属模态 {result.modality or '-'}，"
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
