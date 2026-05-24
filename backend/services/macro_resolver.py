"""宏变量解析与占位符替换。"""

from __future__ import annotations

import re
from typing import Any, Optional

_MACRO_PATTERN = re.compile(r"\$\{([^}]+)\}|\{\{([^}]+)\}\}")


def merge_macro_values(
    macro_defs: Optional[list],
    macro_values: Optional[dict],
) -> dict[str, str]:
    """合并模板宏定义与实例填值，实例值优先。"""
    result: dict[str, str] = {}
    for item in macro_defs or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            default = item.get("default")
            result[name] = "" if default is None else str(default)
        elif isinstance(item, str) and item.strip():
            result[item.strip()] = ""
    for key, value in (macro_values or {}).items():
        if value is not None and str(key).strip():
            result[str(key).strip()] = str(value)
    return {k: v for k, v in result.items() if v != "" or k in (macro_values or {})}


def substitute_macros(text: Optional[str], values: dict[str, str]) -> Optional[str]:
    if not text:
        return text

    def repl(match: re.Match) -> str:
        key = (match.group(1) or match.group(2) or "").strip()
        return values.get(key, match.group(0))

    return _MACRO_PATTERN.sub(repl, text)


def apply_macros_to_env(env: Optional[dict[str, Any]], values: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, raw in (env or {}).items():
        if raw is None:
            continue
        text = str(raw)
        out[str(key)] = substitute_macros(text, values) or text
    return out
