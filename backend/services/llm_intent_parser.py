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

SYSTEM_PROMPT = """你是智联计算系统的意图解析引擎。你的唯一任务是从用户对话中提取结构化参数。

## 支持的业务类型

当前系统仅支持一种业务：
- 矩阵乘法计算任务（task_type: "high_throughput_matmul"）

如果用户描述的不是矩阵乘法相关任务，task_type 设为 null 并在 assistant_message 中告知用户当前仅支持矩阵乘法计算任务。

## 必填参数

| 参数 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 源节点 | source_name | string | 数据源节点名称 |
| 目的节点 | destination_name | string | 计算结果目的节点 |
| 开始时间 | start_time | string | "now" 表示立即，或 ISO 格式 |
| 结束时间/时长 | duration_hours | number | 运行时长（小时） |
| 矩阵规模 | matrix_size | int | N×N 矩阵的 N 值 |
| 批次数 | batch_count | int | 计算批次数量 |
| 路由策略 | routing_strategy | string | 见下方选项 |

## 路由策略选项（必须是以下之一）

- resource_guarantee — 资源保障（默认，用户未明确偏好时使用）
- fastest_completion — 完成时间优先（用户要求更快、高性能）
- load_balance — 负载均衡（用户希望放在空闲服务器、竞争少）
- cost_priority — 成本优先（用户希望便宜、省钱）

## 输出 JSON 格式（严格遵守，不得添加额外字段）

{
  "task_type": "high_throughput_matmul" 或 null,
  "source_name": "string 或 null",
  "destination_name": "string 或 null",
  "duration_hours": number 或 null,
  "matrix_size": number 或 null,
  "batch_count": number 或 null,
  "routing_strategy": "resource_guarantee|fastest_completion|load_balance|cost_priority" 或 null,
  "assistant_message": "string - 用中文回复用户",
  "confidence": number 0-1
}

## 解析规则

1. "现在开始"/"立即" → start_time = "now"
2. "跑N小时" → duration_hours = N
3. "跑N分钟" → duration_hours = N/60
4. "从X到Y" / "源X目的Y" → source_name=X, destination_name=Y
5. "N阶矩阵" / "NxN" / "规模N" → matrix_size = N
6. "N批" / "N次" / "batch N" → batch_count = N
7. 路由策略推断：
   - "快/高性能/尽快完成" → fastest_completion
   - "空闲/负载低/竞争少" → load_balance
   - "便宜/省钱/成本低" → cost_priority
   - 其他/未提及 → resource_guarantee

## assistant_message 规则

- 如果 task_type 为 null：告知用户当前仅支持矩阵乘法计算任务
- 如果有缺失参数：用自然语言询问缺失的参数（按优先级：源节点→目的节点→时长→矩阵规模→批次数→路由策略）
- 如果所有参数完整：总结所有参数并告知用户"参数已完整，请确认提交"
- 保持简洁，2-3句话
- 不要自由发挥，不要提及系统不支持的功能

## 多轮对话

你会收到已有的 draft 信息。本轮只需提取用户新补充的信息，null 表示本轮未提及（保留旧值）。"""


MODALITY_MAP = {
    "high_throughput_matmul": "high_throughput_compute",
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


CHAT_SYSTEM_PROMPT = """你是智算意图解析助手，帮助用户配置矩阵乘法计算任务的部署参数。

## 你的职责
- 引导用户提供矩阵乘法计算任务所需的全部参数
- 当前系统仅支持"矩阵乘法计算任务"一种业务类型
- 如果用户询问其他类型任务，礼貌告知当前仅支持矩阵乘法计算

## 需要收集的参数（按优先级）
1. 源节点（数据从哪个节点来）
2. 目的节点（计算结果发往哪个节点）
3. 运行时长（跑多久）
4. 矩阵规模（N×N 的 N 值）
5. 批次数（计算多少批）
6. 路由策略：
   - 资源保障（默认）
   - 完成时间优先（追求速度）
   - 负载均衡（选空闲节点）
   - 成本优先（省钱）

## 回复规则
- 用自然、友好的中文回复
- 每次只问1-2个缺失参数，不要一次全问
- 当所有参数都已收集完毕时，列出参数摘要并告知"参数已完整，请点击确认提交"
- 保持简洁，2-3句话
- 不要输出JSON或技术格式
- 不要自由联想系统不支持的功能"""


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
        dp = existing_draft.get("data_profile") or {}
        if dp.get("matrix_size"):
            parts.append(f"矩阵规模: {dp['matrix_size']}")
        if dp.get("batch_count"):
            parts.append(f"批次数: {dp['batch_count']}")
        rp = existing_draft.get("runtime_plan") or {}
        if rp.get("routing_strategy"):
            parts.append(f"路由策略: {rp['routing_strategy']}")
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
            if k in ("task_type", "source_name", "destination_name",
                     "business_start_time", "business_end_time", "data_profile",
                     "runtime_plan") and v
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
    modality = MODALITY_MAP.get(task_type or "")

    # Build data_profile from top-level matrix_size / batch_count
    data_profile = {
        "matrix_size": raw.get("matrix_size"),
        "batch_count": raw.get("batch_count"),
    }

    # Build runtime_plan from routing_strategy
    runtime_plan = {
        "routing_strategy": raw.get("routing_strategy"),
    }

    result = ParseResult(
        task_type=task_type,
        modality=modality,
        source_name=raw.get("source_name"),
        destination_name=raw.get("destination_name"),
        business_start_time=start_time,
        business_end_time=end_time,
        data_profile=data_profile,
        business_objective={},
        runtime_plan=runtime_plan,
        resource_requirement={},
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
