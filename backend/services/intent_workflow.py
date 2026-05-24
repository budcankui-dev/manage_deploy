"""意图工作流入口。

当前实现仍使用规则解析器；后续接真实 LLM Agent 时只替换本模块。
"""

from __future__ import annotations

from typing import Any

from services.intent_parser import ParseResult, parse_intent


def run_intent_workflow(
    utterance: str,
    existing_draft: dict[str, Any] | None = None,
) -> tuple[ParseResult, dict[str, Any]]:
    result = parse_intent(utterance, existing_draft)
    trace = {
        "engine": "rule_parser",
        "steps": [
            "merge_existing_draft",
            "parse_task_type",
            "extract_business_objective",
            "validate_constraints",
        ],
    }
    return result, trace
