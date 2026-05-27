"""意图工作流入口。

支持 LLM（Qwen via DashScope）和规则解析器两种引擎，通过配置切换。
LLM 失败时自动 fallback 到规则解析器。
"""

from __future__ import annotations

import logging
from typing import Any

from config import settings
from services.intent_parser import ParseResult, parse_intent

logger = logging.getLogger(__name__)


async def run_intent_workflow(
    utterance: str,
    existing_draft: dict[str, Any] | None = None,
) -> tuple[ParseResult, dict[str, Any]]:
    if settings.intent_parser_engine == "llm" and settings.dashscope_api_key:
        try:
            from services.llm_intent_parser import parse_intent_llm

            result, raw_response = await parse_intent_llm(utterance, existing_draft)
            trace = {
                "engine": "llm_qwen",
                "model": settings.dashscope_model,
                "parser_name": result.parser_name,
                "parser_version": result.parser_version,
                "raw_llm_response": raw_response,
            }
            return result, trace
        except Exception as exc:
            logger.warning(f"LLM intent parse failed, falling back to rule parser: {exc}")

    result = parse_intent(utterance, existing_draft)
    trace = {
        "engine": "rule_parser",
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
        "steps": [
            "merge_existing_draft",
            "extract_source_destination",
            "extract_time",
            "parse_task_type",
            "extract_business_objective",
            "validate_constraints",
            "check_required_fields",
        ],
    }
    return result, trace
