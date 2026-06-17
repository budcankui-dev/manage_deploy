#!/usr/bin/env python3
"""Run online LLM intent evaluation.

Examples:
    cd backend
    PYTHONPATH=. ./venv/bin/python scripts/run_intent_online_eval.py --limit 5 --concurrency 2
    PYTHONPATH=. ./venv/bin/python scripts/run_intent_online_eval.py --concurrency 8 --retries 5 --retry-delay-seconds 5
"""

from __future__ import annotations

import argparse
import asyncio
import json

from services.intent_online_eval import (
    DEFAULT_ONLINE_EVAL_CONCURRENCY,
    DEFAULT_ONLINE_EVAL_RETRIES,
    DEFAULT_ONLINE_EVAL_RETRY_DELAY_SECONDS,
    run_online_evaluation,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run online chat/completions intent evaluation")
    parser.add_argument("--model", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_ONLINE_EVAL_CONCURRENCY)
    parser.add_argument("--retries", type=int, default=DEFAULT_ONLINE_EVAL_RETRIES)
    parser.add_argument("--retry-delay-seconds", type=float, default=DEFAULT_ONLINE_EVAL_RETRY_DELAY_SECONDS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    report = asyncio.run(
        run_online_evaluation(
            model=args.model,
            limit=args.limit,
            concurrency=args.concurrency,
            retries=args.retries,
            retry_delay_seconds=args.retry_delay_seconds,
            resume=args.resume,
        )
    )
    print(json.dumps({
        "evaluation_id": report["evaluation_id"],
        "engine": report["engine"],
        "model": report["model"],
        "total": report["total"],
        "correct": report["correct"],
        "accuracy": report["accuracy"],
        "passed": report["passed"],
        "llm_raw_summary": report.get("llm_raw_summary"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
