#!/usr/bin/env python3
"""验收达标门禁。

二档稳定回归只能证明基础功能没有明显回退；正式验收还需要证明
意图解析和业务测评指标达到约定阈值。本脚本只读现有报告/API，
不创建工单、不启动容器。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib import parse, request


DEFAULT_INTENT_TOTAL = 360
DEFAULT_MIN_ACCURACY = 0.9
DEFAULT_BUSINESS_EVALUATED = 30
DEFAULT_MIN_SUCCESS_RATE = 0.9


class AcceptanceGateError(RuntimeError):
    """验收指标未达标。"""


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def check_intent_report(
    report: dict[str, Any],
    *,
    min_total: int = DEFAULT_INTENT_TOTAL,
    min_accuracy: float = DEFAULT_MIN_ACCURACY,
) -> dict[str, Any]:
    total = _as_int(report.get("total"))
    correct = _as_int(report.get("correct"))
    accuracy = _as_float(report.get("accuracy"))
    if total < min_total:
        raise AcceptanceGateError(f"意图解析样本数不足：{total}/{min_total}")
    if accuracy < min_accuracy:
        raise AcceptanceGateError(f"意图解析准确率未达标：{accuracy:.2%} < {min_accuracy:.2%}")
    return {
        "passed": True,
        "evaluation_id": report.get("evaluation_id"),
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "min_total": min_total,
        "min_accuracy": min_accuracy,
    }


def check_business_summary(
    summary: list[dict[str, Any]],
    task_type: str,
    *,
    min_evaluated: int = DEFAULT_BUSINESS_EVALUATED,
    min_success_rate: float = DEFAULT_MIN_SUCCESS_RATE,
) -> dict[str, Any]:
    rows = [row for row in summary if row.get("task_type") == task_type]
    if not rows:
        raise AcceptanceGateError(f"未找到业务测评统计：{task_type}")
    qualified_rows: list[dict[str, Any]] = []
    for row in rows:
        evaluated = _as_int(row.get("evaluated_count"))
        success = _as_int(row.get("success_count"))
        rate = success / evaluated if evaluated else 0.0
        if evaluated >= min_evaluated and rate >= min_success_rate:
            qualified_rows.append(row)
    if not qualified_rows:
        total_evaluated = sum(_as_int(row.get("evaluated_count")) for row in rows)
        strategies = ", ".join(str(row.get("routing_strategy") or "-") for row in rows)
        raise AcceptanceGateError(
            f"{task_type} 没有单个路由策略分组达标："
            f"总可评价 {total_evaluated}，要求同一策略分组 ≥ {min_evaluated} 且成功率 ≥ {min_success_rate:.2%}；"
            f"当前策略分组：{strategies}"
        )
    best = max(qualified_rows, key=lambda row: _as_int(row.get("evaluated_count")))
    count = _as_int(best.get("count"))
    evaluated_count = _as_int(best.get("evaluated_count"))
    success_count = _as_int(best.get("success_count"))
    success_rate = success_count / evaluated_count if evaluated_count else 0.0
    return {
        "passed": True,
        "task_type": task_type,
        "routing_strategy": best.get("routing_strategy"),
        "count": count,
        "evaluated_count": evaluated_count,
        "success_count": success_count,
        "success_rate": success_rate,
        "min_evaluated": min_evaluated,
        "min_success_rate": min_success_rate,
    }


def check_business_items(
    items: list[dict[str, Any]],
    task_type: str,
    *,
    min_evaluated: int = DEFAULT_BUSINESS_EVALUATED,
) -> dict[str, Any]:
    """复核已评价工单的单任务指标方向，避免只看汇总百分比。"""
    checked = 0
    failures: list[str] = []
    for item in items:
        if item.get("task_type") != task_type or item.get("business_success") is None:
            continue
        checked += 1
        order_id = item.get("order_id") or item.get("external_task_id") or "unknown"
        metric_key = item.get("metric_key")
        actual = item.get("actual_value")
        target = item.get("target_value")
        if actual is None or target is None:
            failures.append(f"{order_id}: 缺少实际值或阈值")
            continue
        actual_f = _as_float(actual)
        target_f = _as_float(target)
        if metric_key == "frame_latency_p90_ms":
            metric_passed = actual_f <= target_f
        else:
            metric_passed = actual_f >= target_f
        if bool(item.get("business_success")) != metric_passed:
            failures.append(
                f"{order_id}: business_success 与指标方向不一致 actual={actual_f}, target={target_f}"
            )
    if failures:
        raise AcceptanceGateError("单任务指标复核失败：" + "；".join(failures[:5]))
    if checked < min_evaluated:
        raise AcceptanceGateError(f"{task_type} 可复核工单不足：{checked}/{min_evaluated}")
    return {"passed": True, "checked_count": checked}


def _read_json(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _request_json(url: str, token: str | None = None) -> Any:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, headers=headers)
    with request.urlopen(req, timeout=30) as resp:  # noqa: S310 - local/admin验收脚本
        return json.loads(resp.read().decode("utf-8"))


def _login(base_url: str, username: str, password: str) -> str:
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = request.Request(
        base_url.rstrip("/") + "/api/auth/login",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=30) as resp:  # noqa: S310 - local/admin验收脚本
        data = json.loads(resp.read().decode("utf-8"))
    return str(data["access_token"])


def _business_summary_url(base_url: str, task_type: str, benchmark_run_id: str | None) -> str:
    query = {"is_benchmark": "true", "task_type": task_type}
    if benchmark_run_id:
        query["benchmark_run_id"] = benchmark_run_id
    return base_url.rstrip("/") + "/api/business-tasks/summary?" + parse.urlencode(query)


def _business_items_url(base_url: str, task_type: str, benchmark_run_id: str | None) -> str:
    query = {"is_benchmark": "true", "task_type": task_type, "page_size": "100"}
    if benchmark_run_id:
        query["benchmark_run_id"] = benchmark_run_id
    return base_url.rstrip("/") + "/api/business-tasks?" + parse.urlencode(query)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查验收指标是否达标")
    parser.add_argument("--intent-report", help="意图评测 JSON 报告路径")
    parser.add_argument("--intent-min-total", type=int, default=DEFAULT_INTENT_TOTAL)
    parser.add_argument("--intent-min-accuracy", type=float, default=DEFAULT_MIN_ACCURACY)
    parser.add_argument("--api-base-url", help="后端 API 地址，例如 http://127.0.0.1:8181")
    parser.add_argument("--task-type", action="append", default=[], help="业务任务类型，可重复传入")
    parser.add_argument("--benchmark-run-id", help="业务测评轮次 ID")
    parser.add_argument("--business-summary-file", help="离线业务 summary JSON 文件")
    parser.add_argument("--business-items-file", help="离线业务列表 JSON 文件")
    parser.add_argument("--business-min-evaluated", type=int, default=DEFAULT_BUSINESS_EVALUATED)
    parser.add_argument("--business-min-success-rate", type=float, default=DEFAULT_MIN_SUCCESS_RATE)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--skip-item-check", action="store_true")
    args = parser.parse_args(argv)

    results: dict[str, Any] = {}
    try:
        if args.intent_report:
            results["intent"] = check_intent_report(
                _read_json(args.intent_report),
                min_total=args.intent_min_total,
                min_accuracy=args.intent_min_accuracy,
            )

        if args.task_type:
            if args.business_summary_file:
                summary = _read_json(args.business_summary_file)
            elif args.api_base_url:
                summary = None
            else:
                raise AcceptanceGateError("检查业务测评时必须提供 --api-base-url 或 --business-summary-file")

            token = None
            if args.api_base_url and not args.business_items_file and not args.skip_item_check:
                token = _login(args.api_base_url, args.username, args.password)

            business_results = []
            for task_type in args.task_type:
                task_summary = summary
                if task_summary is None:
                    task_summary = _request_json(
                        _business_summary_url(args.api_base_url, task_type, args.benchmark_run_id)
                    )
                result = check_business_summary(
                    task_summary,
                    task_type,
                    min_evaluated=args.business_min_evaluated,
                    min_success_rate=args.business_min_success_rate,
                )
                if not args.skip_item_check:
                    if args.business_items_file:
                        raw_items = _read_json(args.business_items_file)
                    elif args.api_base_url:
                        raw_items = _request_json(
                            _business_items_url(args.api_base_url, task_type, args.benchmark_run_id),
                            token=token,
                        )
                    else:
                        raw_items = {}
                    items = raw_items.get("items", raw_items) if isinstance(raw_items, dict) else raw_items
                    result["item_check"] = check_business_items(
                        items or [],
                        task_type,
                        min_evaluated=args.business_min_evaluated,
                    )
                business_results.append(result)
            results["business"] = business_results

        print(json.dumps({"passed": True, "results": results}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc), "results": results}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
