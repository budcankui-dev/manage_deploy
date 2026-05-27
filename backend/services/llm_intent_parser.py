"""LLM 意图解析器 — 通过 DashScope OpenAI-compatible API 调用 Qwen 模型。

每轮用户消息触发一次 LLM 调用，输出结构化 JSON + 自然语言回复。
校验是确定性的（Python 代码），不依赖 LLM 判断。
失败时 fallback 到规则解析器。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, UTC
from typing import Any, AsyncGenerator

import httpx

from config import settings
from services.intent_parser import ParseResult, validate_draft_fields

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个计算任务部署平台的意图解析助手。用户会用自然语言描述他们想要部署的计算任务，你需要从中提取结构化参数。

## 支持的任务类型
- high_throughput_matmul：高吞吐矩阵计算（关键词：矩阵、matmul、乘法、吞吐、科学计算）
- low_latency_video_pipeline：低时延视频转发（关键词：视频、video、转发、H264、编码、流媒体）
- llm_text_generation：大模型文本生成（关键词：大模型、LLM、文本生成、推理、inference）

## 模态映射
- high_throughput_matmul → high_throughput_compute
- low_latency_video_pipeline → low_latency_stream
- llm_text_generation → inference_serving

## 输出要求
你必须输出一个严格的 JSON 对象，包含以下字段：

{
  "task_type": "string|null",
  "modality": "string|null",
  "source_name": "string|null",
  "destination_name": "string|null",
  "duration_hours": "number|null - 运行时长（小时）",
  "data_profile": {"matrix_size": null, "batch_count": null, ...},
  "business_objective": {
    "metric_key": "string|null",
    "operator": "string - <=或>=",
    "target_value": "number|null",
    "unit": "string|null"
  },
  "assistant_message": "string - 用中文回复用户",
  "confidence": "number 0-1"
}

## 解析规则
1. "现在开始"/"立即" → 标记为立即启动
2. "跑N小时/分钟" → duration_hours = N (或 N/60)
3. "从X到Y" / "源X目的Y" / "source:X dest:Y" → source_name=X, destination_name=Y
4. 业务目标：
   - "延迟/耗时不超过Nms" → metric_key="compute_latency_ms", operator="<=", target_value=N, unit="ms"
   - "吞吐不低于N" → metric_key="throughput_gflops", operator=">=", target_value=N, unit="GFLOPS"
   - "端到端时延Nms" → metric_key="end_to_end_latency_ms", operator="<=", target_value=N, unit="ms"

## assistant_message 规则
- 如果所有必填字段都已提取到（task_type, source_name, destination_name, duration, business_objective），用自然语言确认已识别的参数
- 如果缺少必填字段，用友好的中文询问用户补充，不要生硬列举字段名
- 保持简洁，2-3句话即可

## 多轮对话
你会收到已有的 draft 信息，代表之前轮次已经提取到的字段。本轮只需提取用户新补充的信息，null 表示本轮未提及（保留旧值）。"""


MODALITY_MAP = {
    "high_throughput_matmul": "high_throughput_compute",
    "low_latency_video_pipeline": "low_latency_stream",
    "llm_text_generation": "inference_serving",
}


async def call_qwen(messages: list[dict[str, str]]) -> dict[str, Any]:
    """调用 DashScope OpenAI-compatible chat completions API。"""
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.dashscope_model,
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


CHAT_SYSTEM_PROMPT = """你是智算意图解析助手，帮助用户描述和确认计算任务部署需求。

用自然、友好的中文回复用户。如果用户描述了计算任务，确认你理解的参数（任务类型、源节点、目标节点、运行时长、性能目标）。如果信息不完整，用自然语言询问缺少的关键信息。

保持简洁，2-3句话。不要输出JSON或技术格式。"""


def _build_chat_messages(utterance: str, existing_draft: dict | None) -> list[dict]:
    """Build messages for conversational streaming (no JSON schema)."""
    msgs = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    if existing_draft:
        parts = []
        if existing_draft.get("task_type"):
            parts.append(f"任务类型: {existing_draft['task_type']}")
        if existing_draft.get("source_name"):
            parts.append(f"源节点: {existing_draft['source_name']}")
        if existing_draft.get("destination_name"):
            parts.append(f"目标节点: {existing_draft['destination_name']}")
        if parts:
            msgs.append({"role": "system", "content": f"已知信息: {', '.join(parts)}"})
    msgs.append({"role": "user", "content": utterance})
    return msgs


async def parse_intent_llm(
    utterance: str,
    existing_draft: dict[str, Any] | None = None,
) -> tuple[ParseResult, dict[str, Any]]:
    """LLM 解析入口。返回 (ParseResult, raw_llm_response)。"""
    messages = _build_messages(utterance, existing_draft)
    raw = await call_qwen(messages)
    result = _raw_to_parse_result(raw, existing_draft)
    return result, raw


def _build_messages(utterance: str, existing_draft: dict[str, Any] | None) -> list[dict[str, str]]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if existing_draft:
        draft_summary = {
            k: v for k, v in existing_draft.items()
            if k in ("task_type", "modality", "source_name", "destination_name",
                     "business_start_time", "business_end_time", "data_profile",
                     "business_objective") and v
        }
        if draft_summary:
            ctx = json.dumps(draft_summary, ensure_ascii=False, default=str)
            msgs.append({"role": "system", "content": f"当前已提取的草稿：{ctx}"})
    msgs.append({"role": "user", "content": utterance})
    return msgs


def _raw_to_parse_result(raw: dict[str, Any], existing_draft: dict[str, Any] | None) -> ParseResult:
    """将 LLM JSON 输出转为 ParseResult，合并已有 draft，执行确定性校验。"""
    now = datetime.now(UTC).replace(tzinfo=None)

    start_time = None
    end_time = None
    duration = raw.get("duration_hours")
    if duration and isinstance(duration, (int, float)) and duration > 0:
        start_time = now
        end_time = now + timedelta(hours=float(duration))

    task_type = raw.get("task_type")
    modality = raw.get("modality") or MODALITY_MAP.get(task_type or "")

    data_profile = raw.get("data_profile") or {}
    if task_type and not any(v for v in data_profile.values() if v is not None):
        data_profile = _default_data_profile(task_type)

    result = ParseResult(
        task_type=task_type,
        modality=modality,
        source_name=raw.get("source_name"),
        destination_name=raw.get("destination_name"),
        business_start_time=start_time,
        business_end_time=end_time,
        data_profile=raw.get("data_profile") or {},
        business_objective=raw.get("business_objective") or {},
        runtime_plan=raw.get("runtime_plan") or {},
        resource_requirement=raw.get("resource_requirement") or {},
        assistant_message=raw.get("assistant_message", ""),
        parser_name="llm_qwen",
        parser_version=settings.dashscope_model,
    )

    result = _merge_with_draft(existing_draft, result)
    draft_dict = {
        "task_type": result.task_type,
        "source_name": result.source_name,
        "destination_name": result.destination_name,
        "business_start_time": result.business_start_time,
        "business_end_time": result.business_end_time,
        "business_objective": result.business_objective,
        "data_profile": result.data_profile,
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
    if not new.business_objective and existing.get("business_objective"):
        new.business_objective = existing["business_objective"]
    if not new.data_profile and existing.get("data_profile"):
        new.data_profile = existing["data_profile"]
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
