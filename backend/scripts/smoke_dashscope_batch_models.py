#!/usr/bin/env python3
"""Smoke test DashScope Batch support for candidate chat models.

The script submits one JSON-only chat completion request per model and records
whether the Batch job reaches `completed`. It intentionally writes under a
separate smoke directory and does not update the official intent-eval latest job.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from services.intent_batch_eval import DashScopeBatchClient  # noqa: E402


DEFAULT_MODELS = [
    "qwen3.7-plus",
    "qwen3.7-max",
    "qwen3.6-plus",
    "qwen3.6-flash",
    "qwen3.5-plus",
    "qwen3.5-flash",
    "qwen3-max",
    "qwen-plus",
    "qwen-plus-latest",
    "qwen-flash",
    "qwen-long",
]


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_model_name(model: str) -> str:
    return model.replace("/", "_").replace(":", "_")


def _input_line(model: str) -> dict:
    return {
        "custom_id": "smoke-0001",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是一个只输出 JSON 的助手。"},
                {"role": "user", "content": '请严格输出 {"ok": true, "answer": 4}'},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        },
    }


async def _submit_model(client: DashScopeBatchClient, run_dir: Path, model: str) -> dict:
    model_dir = run_dir / _safe_model_name(model)
    model_dir.mkdir(parents=True, exist_ok=True)
    input_path = model_dir / "input.jsonl"
    input_path.write_text(json.dumps(_input_line(model), ensure_ascii=False) + "\n", encoding="utf-8")

    result = {
        "model": model,
        "status": "submit_failed",
        "supported": False,
        "input_jsonl_path": str(input_path.relative_to(REPO_ROOT)),
        "submitted_at": datetime.now().isoformat(timespec="seconds"),
        "batch_id": None,
        "file_id": None,
        "request_counts": None,
        "error": None,
    }
    try:
        upload = await client.upload_file(input_path)
        result["file_id"] = upload.get("id")
        batch = await client.create_batch(
            result["file_id"],
            metadata={
                "purpose": "model_batch_smoke",
                "model": model,
                "run_dir": str(run_dir.relative_to(REPO_ROOT)),
            },
        )
        result["batch_id"] = batch.get("id")
        result["status"] = batch.get("status", "submitted")
        result["request_counts"] = batch.get("request_counts")
        result["raw_batch"] = batch
    except Exception as exc:
        result["error"] = str(exc)
    return result


async def _poll_model(
    client: DashScopeBatchClient,
    run_dir: Path,
    result: dict,
    interval_seconds: int,
    max_wait_seconds: int,
) -> dict:
    batch_id = result.get("batch_id")
    if not batch_id:
        return result

    deadline = asyncio.get_running_loop().time() + max_wait_seconds
    while True:
        try:
            batch = await client.retrieve_batch(batch_id)
            result["status"] = batch.get("status", result["status"])
            result["request_counts"] = batch.get("request_counts")
            result["output_file_id"] = batch.get("output_file_id")
            result["error_file_id"] = batch.get("error_file_id")
            result["raw_batch"] = batch
        except Exception as exc:
            result["status"] = "retrieve_failed"
            result["error"] = str(exc)
            return result

        if result["status"] in {"completed", "failed", "expired", "cancelled"}:
            break
        if asyncio.get_running_loop().time() >= deadline:
            result["status"] = "timed_out"
            result["error"] = f"Batch did not finish within {max_wait_seconds}s"
            try:
                cancel = await client.cancel_batch(batch_id)
                result["cancel_status"] = cancel.get("status")
                result["raw_cancel"] = cancel
            except Exception as exc:
                result["cancel_error"] = str(exc)
            break
        await asyncio.sleep(interval_seconds)

    if result["status"] == "completed" and result.get("output_file_id"):
        output_path = run_dir / _safe_model_name(result["model"]) / "output.jsonl"
        try:
            await client.download_file(result["output_file_id"], output_path)
            result["output_jsonl_path"] = str(output_path.relative_to(REPO_ROOT))
            output_lines = [
                json.loads(line)
                for line in output_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            first = output_lines[0] if output_lines else {}
            result["supported"] = not first.get("error")
            result["sample_response_status_code"] = (first.get("response") or {}).get("status_code")
            result["sample_error"] = first.get("error")
        except Exception as exc:
            result["supported"] = False
            result["error"] = str(exc)
    return result


async def run(args: argparse.Namespace) -> dict:
    run_id = f"model-smoke-{_now_id()}-{uuid4().hex[:8]}"
    run_dir = REPO_ROOT / "reports" / "intent_eval_batches" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    client = DashScopeBatchClient()

    report_path = run_dir / "report.json"
    submitted = []
    for model in args.models:
        print(f"submit {model}", flush=True)
        submitted.append(await _submit_model(client, run_dir, model))
        report_path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "max_wait_seconds": args.max_wait_seconds,
                    "models": args.models,
                    "supported_models": [],
                    "results": submitted,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    async def poll_and_print(item: dict) -> dict:
        print(f"poll {item['model']} batch={item.get('batch_id')}", flush=True)
        result = await _poll_model(
                client,
                run_dir,
                item,
                interval_seconds=args.interval_seconds,
                max_wait_seconds=args.max_wait_seconds,
            )
        status = "PASS" if result.get("supported") else "FAIL"
        print(
            f"{status} {result['model']} status={result['status']} "
            f"counts={result.get('request_counts')} error={result.get('error') or result.get('sample_error')}",
            flush=True,
        )
        return result

    results = await asyncio.gather(*(poll_and_print(item) for item in submitted))

    report = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "max_wait_seconds": args.max_wait_seconds,
        "models": args.models,
        "supported_models": [item["model"] for item in results if item.get("supported")],
        "results": results,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "run_id": run_id,
        "report_path": str(report_path.relative_to(REPO_ROOT)),
        "supported_models": report["supported_models"],
        "summary": [
            {
                "model": item["model"],
                "status": item["status"],
                "supported": item["supported"],
                "request_counts": item.get("request_counts"),
                "error": item.get("error") or item.get("sample_error"),
            }
            for item in results
        ],
    }, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--max-wait-seconds", type=int, default=240)
    parser.add_argument("--interval-seconds", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
