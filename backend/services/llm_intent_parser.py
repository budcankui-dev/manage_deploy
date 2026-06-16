"""LLM 意图解析器 — 通过 DashScope OpenAI-compatible API 调用 Qwen 模型。

每轮用户消息触发一次 LLM 调用，输出结构化 JSON + 自然语言回复。
校验是确定性的（Python 代码），不依赖 LLM 判断。
失败时 fallback 到规则解析器。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator
from zoneinfo import ZoneInfo

import httpx

from config import settings
from services.intent_parser import ParseResult, extract_routing_strategy, validate_draft_fields
from services.modality_catalog import default_objective_for_task_type, modality_for_task_type

logger = logging.getLogger(__name__)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

SYSTEM_PROMPT = """你是智联计算系统的意图解析引擎。你的唯一任务是从用户对话中提取结构化参数。

## 支持的业务类型

当前意图解析评测覆盖以下业务/模态：
- 矩阵乘法计算任务（task_type: "high_throughput_matmul"）
- 低时延视频链路/视频AI推理任务（task_type: "low_latency_video_pipeline"）
- 大模型文本生成/LLM 推理任务（task_type: "llm_text_generation"）
- 文本模型训练任务（task_type: "ai_model_training"）
- 分布式存算任务（task_type: "distributed_storage_compute"）
- 大规模连接采集任务（task_type: "massive_connection_collect"）
- 确定性转发任务（task_type: "deterministic_forwarding"）
- 高能效边缘推理任务（task_type: "energy_efficient_edge_inference"）
- 高安全传输任务（task_type: "secure_transmission"）

如果用户描述的不是上述任务，task_type 设为 null 并在 assistant_message 中告知用户当前支持矩阵计算、视频推理和八类模态测试样本。

## 必填参数

| 参数 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 源节点 | source_name | string | 数据源节点名称 |
| 目的节点 | destination_name | string | 计算结果目的节点 |
| 开始时间 | start_time | string | ISO 格式如 "2025-06-01T08:00:00"，或 "now" 表示立即 |
| 结束时间 | end_time | string | ISO 格式如 "2025-06-01T10:00:00" |
| 矩阵规模 | matrix_size | int | 矩阵任务必填，N×N 矩阵的 N 值 |
| 批次数 | batch_count | int | 矩阵任务必填，计算批次数量 |
| 视频帧数 | frame_count | int | 视频任务必填，处理多少帧 |
| 分辨率 | resolution | string | 视频任务必填，如 720p/1080p/4K |
| 帧率 | fps | int | 视频任务必填，如 30 |
| 输入token | prompt_tokens | int | LLM任务必填，输入 prompt token 数 |
| 生成token | max_new_tokens | int | LLM任务必填，最大生成 token 数 |
| 批大小 | batch_size | int | LLM任务必填 |
| 训练样本数 | sample_count | int | 文本模型训练任务必填 |
| 存算数据量 | data_size_gb | int | 分布式存算任务必填，单位 GB |
| 连接数量 | connection_count | int | 大规模连接采集任务必填 |
| 最大抖动 | max_jitter_ms | int | 确定性转发任务必填，单位 ms |
| 功耗预算 | power_budget_w | int | 高能效边缘推理任务必填，单位 W |
| 安全等级 | security_level | string | 高安全传输任务必填，固定输出 "high" |
| 路由策略 | routing_strategy | string | 见下方选项 |

## 路由策略选项（必须是以下之一）

- resource_guarantee — 资源保障（默认，用户未明确偏好时使用）
- fastest_completion — 完成时间优先（用户要求更快、高性能）
- low_latency_forwarding — 低时延转发（用户明确要求低时延转发、低时延路由、低时延策略）
- load_balance — 负载均衡（用户希望放在空闲服务器、竞争少）
- cost_priority — 成本优先（用户希望便宜、省钱）

## 输出 JSON 格式（严格遵守，不得添加额外字段）

{
  "task_type": "high_throughput_matmul|low_latency_video_pipeline|llm_text_generation|ai_model_training|distributed_storage_compute|massive_connection_collect|deterministic_forwarding|energy_efficient_edge_inference|secure_transmission" 或 null,
  "source_name": "string 或 null",
  "destination_name": "string 或 null",
  "start_time": "ISO格式时间字符串 或 'now' 或 null",
  "end_time": "ISO格式时间字符串 或 null",
  "matrix_size": number 或 null,
  "batch_count": number 或 null,
  "frame_count": number 或 null,
  "resolution": "string 或 null",
  "fps": number 或 null,
  "prompt_tokens": number 或 null,
  "max_new_tokens": number 或 null,
  "batch_size": number 或 null,
  "sample_count": number 或 null,
  "data_size_gb": number 或 null,
  "connection_count": number 或 null,
  "max_jitter_ms": number 或 null,
  "power_budget_w": number 或 null,
  "security_level": "high" 或 null,
  "routing_strategy": "resource_guarantee|fastest_completion|low_latency_forwarding|load_balance|cost_priority" 或 null,
  "assistant_message": "string - 用中文回复用户",
  "confidence": number 0-1
}

## 解析规则

1. "现在开始"/"立即" → start_time = "now"
2. "明天上午9点开始" → start_time = 对应ISO格式
3. "到下午5点结束" / "结束时间17:00" → end_time = 对应ISO格式
4. "跑2小时" → 根据 start_time 推算 end_time（start_time + 2h）
5. "从X到Y" / "源X目的Y" → source_name=X, destination_name=Y
6. "N阶矩阵" / "NxN" / "规模N" → matrix_size = N
7. "N批" / "N次" / "batch N" → batch_count = N
8. "N帧" / "frames=N" → frame_count = N；"30fps" → fps = 30；"1080p/720p/4K" → resolution
9. "prompt_tokens=N" / "prompt N tokens" → prompt_tokens = N；"max_new_tokens=N" / "生成 N tokens" → max_new_tokens = N；"batch_size=N" → batch_size = N
10. "训练 N 条样本" / "样本数 N" / "samples=N" → sample_count = N
11. "NGB 数据" / "data=NGB" / "数据规模 NGB" → data_size_gb = N
12. "接入 N 个终端" / "连接数 N" / "并发连接 N" → connection_count = N
13. "抖动 Nms" / "jitter=Nms" / "抖动上限 Nms" → max_jitter_ms = N
14. "功耗 N W" / "功耗预算 N W" / "能耗预算 N W" → power_budget_w = N
15. "高安全传输" / "安全级别 high" / "加密传输" / "敏感数据" → security_level = "high"
16. 路由策略推断：
   - "快/高性能/尽快完成" → fastest_completion
   - "低时延转发/低时延路由/低时延策略" → low_latency_forwarding
   - "空闲/负载低/竞争少" → load_balance
   - "便宜/省钱/成本低" → cost_priority
   - 其他/未提及 → resource_guarantee

## assistant_message 规则

- 如果 task_type 为 null：告知用户当前支持矩阵乘法、低时延视频链路、LLM文本生成三类任务
- 如果有缺失参数：用自然语言询问缺失的参数（按优先级：源节点→目的节点→开始时间→结束时间→矩阵规模→批次数→路由策略）
- 如果所有参数完整：总结所有参数并告知用户"参数已完整，请确认提交"
- 保持简洁，2-3句话
- 不要自由发挥，不要提及系统不支持的功能

## 多轮对话

你会收到已有的 draft 信息。本轮只需提取用户新补充的信息，null 表示本轮未提及（保留旧值）。"""


MODALITY_MAP = {
    "high_throughput_matmul": modality_for_task_type("high_throughput_matmul"),
    "low_latency_video_pipeline": modality_for_task_type("low_latency_video_pipeline"),
    "llm_text_generation": modality_for_task_type("llm_text_generation"),
    "ai_model_training": modality_for_task_type("ai_model_training"),
    "distributed_storage_compute": modality_for_task_type("distributed_storage_compute"),
    "massive_connection_collect": modality_for_task_type("massive_connection_collect"),
    "deterministic_forwarding": modality_for_task_type("deterministic_forwarding"),
    "energy_efficient_edge_inference": modality_for_task_type("energy_efficient_edge_inference"),
    "secure_transmission": modality_for_task_type("secure_transmission"),
}


def _extract_relative_duration_minutes(utterance: str | None) -> int | None:
    if not utterance:
        return None
    hour_match = re.search(r"(\d+)\s*(?:小时|h|hour)", utterance, re.IGNORECASE)
    if hour_match:
        return int(hour_match.group(1)) * 60
    minute_match = re.search(r"(\d+)\s*(?:分钟|min|minute)", utterance, re.IGNORECASE)
    if minute_match:
        return int(minute_match.group(1))
    return None


def _has_immediate_start(utterance: str | None) -> bool:
    if not utterance:
        return False
    if re.search(r"(?:不要|别|不|暂不|先不).{0,8}(?:现在开始|立即|马上)", utterance):
        return False
    return bool(re.search(r"现在开始|立即|马上", utterance))


async def call_qwen(messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
    """调用 DashScope OpenAI-compatible chat completions API。"""
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or settings.dashscope_model,
        "messages": messages,
        "temperature": settings.dashscope_temperature,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.dashscope_base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=settings.dashscope_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)


async def stream_qwen_tokens(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Stream assistant_message tokens from Qwen, yield each text chunk."""
    payload = {
        "model": settings.dashscope_model,
        "messages": messages,
        "temperature": settings.dashscope_temperature,
        "stream": True,
        # No response_format for streaming — parse JSON separately after
    }
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{settings.dashscope_base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=60.0,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


CHAT_SYSTEM_PROMPT = """你是智算意图解析助手。你的任务是按照系统指令引导用户提供智联计算业务工单参数。

## 严格规则
- 当前用户端可演示提交两类任务："矩阵乘法计算任务" 和 "视频AI推理任务"
- 意图解析评测数据集还覆盖八类模态样本，但用户端真实部署演示优先引导到矩阵乘法和视频AI推理两类任务
- 你只能询问系统指令中要求你询问的参数，不要问其他内容
- 不要提及"运行时长"这个概念，必须分别询问"开始时间"和"结束时间"
- 用自然友好的中文回复，2-3句话
- 不要输出JSON或技术格式
- 不要自由联想系统不支持的功能
- 如果用户询问当前不可部署的任务，告知当前演示部署支持矩阵乘法计算任务和视频AI推理任务

## 路由策略（固定选项，不要追问细节）
- 资源保障（默认）：用户说"资源保障"、"保障资源"等
- 完成时间优先：用户说"快"、"高性能"、"尽快完成"等
- 低时延转发：用户说"低时延转发"、"低时延路由"、"低时延策略"等
- 负载均衡：用户说"空闲"、"负载低"、"均衡"等
- 成本优先：用户说"便宜"、"省钱"、"成本低"等

当用户提到上述任何一种策略的关键词时，直接确认该策略已记录，不要反问"具体是指哪种方式"。如果用户未提及路由策略，默认使用"资源保障"。"""


# Parameter definitions for deterministic workflow
PARAM_QUESTIONS = {
    "source_name": "源节点（数据从哪个节点发出）",
    "destination_name": "目的节点（计算结果发往哪个节点）",
    "business_start_time": "开始时间（什么时候开始，例如：明天上午9点、2025-06-01 08:00）",
    "business_end_time": "结束时间（什么时候结束，例如：下午5点、2025-06-01 17:00）",
    "matrix_size": "矩阵规模（N×N 矩阵的 N 值，例如：1024、2048）",
    "batch_count": "批次数（计算多少批，例如：10、100）",
    "routing_strategy": "路由策略（资源保障/完成时间优先/低时延转发/负载均衡/成本优先，默认资源保障）",
}


def _build_chat_messages(utterance: str, existing_draft: dict | None, valid_nodes: list[str] | None = None) -> list[dict]:
    """Build messages for conversational streaming with deterministic parameter guidance."""
    # Determine which parameters are already filled
    filled = set()
    if existing_draft:
        if existing_draft.get("source_name"):
            filled.add("source_name")
        if existing_draft.get("destination_name"):
            filled.add("destination_name")
        if existing_draft.get("business_start_time"):
            filled.add("business_start_time")
        if existing_draft.get("business_end_time"):
            filled.add("business_end_time")
        dp = existing_draft.get("data_profile") or {}
        if dp.get("matrix_size"):
            filled.add("matrix_size")
        if dp.get("batch_count"):
            filled.add("batch_count")
        rp = existing_draft.get("runtime_plan") or {}
        if rp.get("routing_strategy"):
            filled.add("routing_strategy")

    # Determine missing parameters (in priority order)
    all_params = ["source_name", "destination_name", "business_start_time",
                  "business_end_time", "matrix_size", "batch_count", "routing_strategy"]
    missing = [p for p in all_params if p not in filled]

    # Build dynamic instruction
    if not missing:
        instruction = "所有参数已完整。请列出参数摘要并告知用户'参数已完整，请点击确认提交工单'。"
    else:
        # Ask for next 1-2 missing params
        ask_params = missing[:2]
        ask_desc = "、".join(PARAM_QUESTIONS[p] for p in ask_params)
        instruction = f"请向用户询问以下缺失参数：{ask_desc}。只问这些，不要问其他参数。"
        if ("source_name" in missing or "destination_name" in missing) and valid_nodes:
            instruction += f" 可用节点有：{', '.join(valid_nodes)}。"

    # Build filled summary
    filled_parts = []
    if existing_draft:
        if existing_draft.get("source_name"):
            filled_parts.append(f"源节点: {existing_draft['source_name']}")
        if existing_draft.get("destination_name"):
            filled_parts.append(f"目的节点: {existing_draft['destination_name']}")
        if existing_draft.get("business_start_time"):
            filled_parts.append(f"开始时间: {existing_draft['business_start_time']}")
        if existing_draft.get("business_end_time"):
            filled_parts.append(f"结束时间: {existing_draft['business_end_time']}")
        dp = existing_draft.get("data_profile") or {}
        if dp.get("matrix_size"):
            filled_parts.append(f"矩阵规模: {dp['matrix_size']}")
        if dp.get("batch_count"):
            filled_parts.append(f"批次数: {dp['batch_count']}")
        rp = existing_draft.get("runtime_plan") or {}
        if rp.get("routing_strategy"):
            filled_parts.append(f"路由策略: {rp['routing_strategy']}")

    msgs = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    if filled_parts:
        msgs.append({"role": "system", "content": f"已收集的参数：{', '.join(filled_parts)}"})
    msgs.append({"role": "system", "content": f"本轮指令：{instruction}"})
    msgs.append({"role": "user", "content": utterance})
    return msgs


VALID_ROUTING_STRATEGIES = {
    "resource_guarantee",
    "fastest_completion",
    "low_latency_forwarding",
    "load_balance",
    "cost_priority",
}


def _validate_and_clean(raw: dict, valid_nodes: list[str]) -> dict:
    """Validate LLM output fields. Invalid fields are set to None (won't overwrite existing draft)."""
    cleaned = dict(raw)

    allowed_task_types = {
        None,
        "high_throughput_matmul",
        "low_latency_video_pipeline",
        "llm_text_generation",
        "ai_model_training",
        "distributed_storage_compute",
        "massive_connection_collect",
        "deterministic_forwarding",
        "energy_efficient_edge_inference",
        "secure_transmission",
    }
    if cleaned.get("task_type") not in allowed_task_types:
        cleaned["task_type"] = None

    # source_name: must be in valid_nodes (if provided and nodes list is non-empty)
    src = cleaned.get("source_name")
    if src and valid_nodes and src not in valid_nodes:
        cleaned["source_name"] = None

    # destination_name: same
    dst = cleaned.get("destination_name")
    if dst and valid_nodes and dst not in valid_nodes:
        cleaned["destination_name"] = None

    # start_time: must be "now" or valid ISO datetime string
    st = cleaned.get("start_time")
    if st and st != "now":
        try:
            datetime.fromisoformat(str(st))
        except (ValueError, TypeError):
            cleaned["start_time"] = None

    # end_time: must be valid ISO datetime string
    et = cleaned.get("end_time")
    if et:
        try:
            datetime.fromisoformat(str(et))
        except (ValueError, TypeError):
            cleaned["end_time"] = None

    for key in (
        "matrix_size",
        "batch_count",
        "frame_count",
        "fps",
        "prompt_tokens",
        "max_new_tokens",
        "batch_size",
        "sample_count",
        "data_size_gb",
        "connection_count",
        "max_jitter_ms",
        "power_budget_w",
    ):
        value = cleaned.get(key)
        if value is None:
            continue
        try:
            value_int = int(value)
            cleaned[key] = value_int if value_int > 0 else None
        except (ValueError, TypeError):
            cleaned[key] = None

    security_level = cleaned.get("security_level")
    if security_level is not None:
        normalized_security = str(security_level).strip().lower()
        cleaned["security_level"] = "high" if normalized_security in {"high", "高", "高安全", "高级", "secure"} else None

    # routing_strategy: must be one of the valid values
    rs = cleaned.get("routing_strategy")
    if rs and rs not in VALID_ROUTING_STRATEGIES:
        cleaned["routing_strategy"] = None

    # Validate end_time > start_time if both present
    if cleaned.get("start_time") and cleaned.get("end_time"):
        try:
            now = datetime.now(SHANGHAI_TZ).replace(tzinfo=None)
            s = now if cleaned["start_time"] == "now" else datetime.fromisoformat(str(cleaned["start_time"]))
            e = datetime.fromisoformat(str(cleaned["end_time"]))
            if e <= s:
                cleaned["end_time"] = None
        except Exception:
            pass

    return cleaned


async def parse_intent_llm(
    utterance: str,
    existing_draft: dict[str, Any] | None = None,
    valid_nodes: list[str] | None = None,
) -> tuple[ParseResult, dict[str, Any]]:
    """LLM 解析入口。返回 (ParseResult, raw_llm_response)。"""
    messages = _build_messages(utterance, existing_draft, valid_nodes)
    raw = await call_qwen(messages)
    raw = _validate_and_clean(raw, valid_nodes or [])
    result = _raw_to_parse_result(raw, existing_draft, utterance=utterance)
    return result, raw


def _build_messages(utterance: str, existing_draft: dict[str, Any] | None, valid_nodes: list[str] | None = None) -> list[dict[str, str]]:
    now_str = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%dT%H:%M:%S")
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]

    context_parts = [f"当前时间: {now_str}。用户提到的相对时间（如'明天上午9点'）请转换为ISO格式输出。"]
    if valid_nodes:
        context_parts.append(f"系统中可用的节点: {', '.join(valid_nodes)}。source_name和destination_name必须是这些节点之一，否则设为null。")
    msgs.append({"role": "system", "content": " ".join(context_parts)})
    if existing_draft:
        draft_summary = {
            k: v for k, v in existing_draft.items()
            if k in ("task_type", "source_name", "destination_name",
                     "business_start_time", "business_end_time", "data_profile",
                     "runtime_plan") and v
        }
        if draft_summary:
            ctx = json.dumps(draft_summary, ensure_ascii=False, default=str)
            msgs.append({"role": "system", "content": f"当前已提取的草稿：{ctx}"})
    msgs.append({"role": "user", "content": utterance})
    return msgs


def _raw_to_parse_result(
    raw: dict[str, Any],
    existing_draft: dict[str, Any] | None,
    utterance: str | None = None,
) -> ParseResult:
    """将 LLM JSON 输出转为 ParseResult，合并已有 draft，执行确定性校验。"""
    now = datetime.now(SHANGHAI_TZ).replace(tzinfo=None)

    start_time = None
    end_time = None
    raw_start = raw.get("start_time")
    raw_end = raw.get("end_time")
    duration = raw.get("duration_hours")

    immediate_start = _has_immediate_start(utterance)

    if immediate_start:
        start_time = now
    elif raw_start == "now":
        start_time = now
    elif raw_start:
        try:
            start_time = datetime.fromisoformat(str(raw_start)).replace(tzinfo=None)
        except (ValueError, TypeError):
            pass

    if raw_end:
        try:
            end_time = datetime.fromisoformat(str(raw_end)).replace(tzinfo=None)
        except (ValueError, TypeError):
            pass
    elif duration and isinstance(duration, (int, float)) and duration > 0 and start_time:
        end_time = start_time + timedelta(hours=float(duration))

    relative_duration_minutes = _extract_relative_duration_minutes(utterance)
    if relative_duration_minutes:
        if not start_time and _has_immediate_start(utterance):
            start_time = now
        if start_time:
            end_time = start_time + timedelta(minutes=relative_duration_minutes)

    task_type = raw.get("task_type")
    modality = MODALITY_MAP.get(task_type or "")

    data_profile_keys = (
        "matrix_size",
        "batch_count",
        "frame_count",
        "resolution",
        "fps",
        "prompt_tokens",
        "max_new_tokens",
        "batch_size",
        "sample_count",
        "data_size_gb",
        "connection_count",
        "max_jitter_ms",
        "power_budget_w",
        "security_level",
    )
    data_profile = {key: raw.get(key) for key in data_profile_keys if raw.get(key) is not None}

    routing_strategy = raw.get("routing_strategy")
    if utterance:
        routing_strategy = extract_routing_strategy(str(utterance), default=routing_strategy or "resource_guarantee")

    # Build runtime_plan from routing_strategy
    runtime_plan = {
        "routing_strategy": routing_strategy,
    }

    # Build business_objective from task_type defaults
    business_objective = {}
    if task_type == "high_throughput_matmul":
        business_objective = {
            "metric_key": "effective_gflops",
            "operator": ">=",
            "unit": "GFLOPS",
        }
    elif task_type == "low_latency_video_pipeline":
        business_objective = {
            "metric_key": "frame_latency_p90_ms",
            "operator": "<=",
            "unit": "ms",
        }
    else:
        business_objective = default_objective_for_task_type(task_type)

    result = ParseResult(
        task_type=task_type,
        modality=modality,
        source_name=raw.get("source_name"),
        destination_name=raw.get("destination_name"),
        business_start_time=start_time,
        business_end_time=end_time,
        data_profile=data_profile,
        business_objective=business_objective,
        runtime_plan=runtime_plan,
        resource_requirement={},
        assistant_message=raw.get("assistant_message", ""),
        parser_name="llm_qwen",
        parser_version=settings.dashscope_model,
    )

    result = _merge_with_draft(existing_draft, result)
    fixed_modality = modality_for_task_type(result.task_type)
    if fixed_modality:
        result.modality = fixed_modality
    draft_dict = {
        "task_type": result.task_type,
        "source_name": result.source_name,
        "destination_name": result.destination_name,
        "business_start_time": result.business_start_time,
        "business_end_time": result.business_end_time,
        "data_profile": result.data_profile,
        "runtime_plan": result.runtime_plan,
    }
    result.validation_errors = validate_draft_fields(draft_dict)
    result.parse_status = "valid" if not result.validation_errors else "incomplete"
    return result


def _merge_with_draft(existing: dict[str, Any] | None, new: ParseResult) -> ParseResult:
    """将已有 draft 中的非空字段合并到新结果中（新值优先，null 保留旧值）。"""
    if not existing:
        return new
    if not new.task_type and existing.get("task_type"):
        new.task_type = existing["task_type"]
        new.modality = existing.get("modality") or MODALITY_MAP.get(new.task_type or "")
    if not new.source_name and existing.get("source_name"):
        new.source_name = existing["source_name"]
    if not new.destination_name and existing.get("destination_name"):
        new.destination_name = existing["destination_name"]
    if not new.business_start_time and existing.get("business_start_time"):
        new.business_start_time = existing["business_start_time"]
    if not new.business_end_time and existing.get("business_end_time"):
        new.business_end_time = existing["business_end_time"]
    # Merge data_profile (matrix_size, batch_count)
    existing_dp = existing.get("data_profile") or {}
    if existing_dp:
        for k, v in existing_dp.items():
            if v is not None and not new.data_profile.get(k):
                new.data_profile[k] = v
    # Merge runtime_plan (routing_strategy)
    existing_rp = existing.get("runtime_plan") or {}
    if existing_rp:
        for k, v in existing_rp.items():
            if v is not None and not new.runtime_plan.get(k):
                new.runtime_plan[k] = v
    return new


def _default_data_profile(task_type: str) -> dict[str, Any]:
    """为已知任务类型提供合理的默认数据画像。"""
    defaults = {
        "high_throughput_matmul": {
            "profile_id": "matmul_default",
            "source": "synthetic",
            "matrix_size": 1024,
            "batch_count": 10,
        },
        "low_latency_video_pipeline": {
            "profile_id": "video_default",
            "source": "synthetic",
            "resolution": "1920x1080",
            "fps": 30,
        },
        "llm_text_generation": {
            "profile_id": "llm_default",
            "source": "synthetic",
            "prompt_tokens": 512,
            "max_tokens": 256,
        },
    }
    return defaults.get(task_type, {"profile_id": "generic", "source": "synthetic"})
