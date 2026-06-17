"""Online LLM intent evaluation.

This is the primary evaluation path for acceptance demos.  It calls the
OpenAI-compatible chat completions API sample-by-sample instead of relying on
provider Batch jobs, while reusing the same dataset and scoring semantics.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from config import settings
from services.intent_batch_eval import (
    DATASET_PATH,
    REPORTS_DIR,
    VALID_NODES,
    _parse_result_payload,
    _summarize_results,
    available_eval_models,
    normalize_eval_model,
    score_parsed_result,
)
from services.intent_parser import parse_intent
from services.llm_intent_parser import _build_messages, _raw_to_parse_result, _validate_and_clean, call_qwen


ONLINE_REPORT_PATH = REPORTS_DIR / "intent_eval_online.json"
ONLINE_PROGRESS_PATH = REPORTS_DIR / "intent_eval_online.progress.jsonl"
ONLINE_STATUS_PATH = REPORTS_DIR / "intent_eval_online.status.json"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_online_report() -> dict[str, Any] | None:
    if not ONLINE_REPORT_PATH.exists():
        return None
    return json.loads(ONLINE_REPORT_PATH.read_text(encoding="utf-8"))


def read_online_status() -> dict[str, Any] | None:
    if not ONLINE_STATUS_PATH.exists():
        return None
    return json.loads(ONLINE_STATUS_PATH.read_text(encoding="utf-8"))


def online_evaluation_is_running() -> bool:
    status = read_online_status() or {}
    return status.get("status") == "running"


def _write_online_status(status: dict[str, Any]) -> dict[str, Any]:
    ONLINE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    status["updated_at"] = _now_iso()
    ONLINE_STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def start_online_evaluation(
    *,
    model: str | None = None,
    limit: int | None = None,
    concurrency: int = 1,
    retries: int = 3,
    retry_delay_seconds: float = 3.0,
    resume: bool = False,
) -> dict[str, Any]:
    rows = _load_online_dataset()
    if limit is not None:
        rows = rows[: max(0, limit)]
    if not rows:
        raise ValueError("Intent evaluation dataset is empty")
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    selected_model = normalize_eval_model(model)
    evaluation_id = f"online-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    started_at = _now_iso()
    if not resume and ONLINE_PROGRESS_PATH.exists():
        ONLINE_PROGRESS_PATH.unlink()
    completed_by_id = _read_progress(ONLINE_PROGRESS_PATH) if resume else {}
    return _write_online_status({
        "evaluation_id": evaluation_id,
        "engine": "llm_qwen_online",
        "model": selected_model,
        "status": "running",
        "total": len(rows),
        "completed": len(completed_by_id),
        "correct": sum(1 for item in completed_by_id.values() if item.get("match")),
        "failed": 0,
        "accuracy": None,
        "started_at": started_at,
        "finished_at": None,
        "concurrency": concurrency,
        "retries": retries,
        "limit": limit,
        "resume": resume,
    })


def fail_online_evaluation(evaluation_id: str | None, message: str) -> dict[str, Any]:
    current = read_online_status() or {}
    if evaluation_id and current.get("evaluation_id") != evaluation_id:
        current["evaluation_id"] = evaluation_id
    current["status"] = "failed"
    current["error"] = message
    current["finished_at"] = _now_iso()
    return _write_online_status(current)


def _load_online_dataset() -> list[dict[str, Any]]:
    if not DATASET_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    with DATASET_PATH.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _online_dataset_summary() -> dict[str, Any]:
    import hashlib

    rows = _load_online_dataset()
    dataset_bytes = DATASET_PATH.read_bytes() if DATASET_PATH.exists() else b""
    case_counts = Counter(row.get("case_type", "valid") for row in rows)
    task_counts = Counter((row.get("expected") or {}).get("task_type", "unknown") for row in rows)
    modality_counts = Counter((row.get("expected") or {}).get("modality", "unknown") for row in rows)
    return {
        "path": str(DATASET_PATH),
        "total": len(rows),
        "sha256": hashlib.sha256(dataset_bytes).hexdigest() if dataset_bytes else None,
        "updated_at": datetime.fromtimestamp(DATASET_PATH.stat().st_mtime).isoformat(sep=" ", timespec="seconds")
        if DATASET_PATH.exists()
        else None,
        "case_counts": dict(case_counts),
        "task_counts": dict(task_counts),
        "modality_counts": dict(modality_counts),
        "valid_nodes": VALID_NODES,
    }


def _read_progress(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    completed: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            sample_id = item.get("sample_id")
            if sample_id:
                completed[str(sample_id)] = item
    return completed


def _append_progress(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _score_raw_llm(raw: dict[str, Any], sample: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    cleaned = _validate_and_clean(raw, VALID_NODES)
    raw_parsed = _raw_to_parse_result(cleaned, None, utterance=sample["utterance"])
    # Keep raw route strategy diagnostics: deterministic extraction should not
    # hide a model's original strategy mistake.
    if raw.get("routing_strategy") in {None, ""}:
        raw_parsed.runtime_plan["routing_strategy"] = None
    elif "routing_strategy" in cleaned:
        raw_parsed.runtime_plan["routing_strategy"] = cleaned.get("routing_strategy")
    return raw_parsed, score_parsed_result(raw_parsed, sample.get("expected", {}))


async def _call_with_retries(
    messages: list[dict[str, str]],
    *,
    model: str,
    retries: int,
    retry_delay_seconds: float,
) -> tuple[dict[str, Any], int]:
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return await call_qwen(messages, model=model), attempt + 1
        except BaseException as exc:  # noqa: BLE001 - keep per-sample failure isolated.
            last_error = exc
            if attempt >= retries:
                break
            if retry_delay_seconds > 0:
                await asyncio.sleep(retry_delay_seconds * (attempt + 1))
    raise RuntimeError(str(last_error) if last_error else "online LLM call failed")


async def _evaluate_sample(
    *,
    index: int,
    sample: dict[str, Any],
    model: str,
    retries: int,
    retry_delay_seconds: float,
) -> dict[str, Any]:
    sample_id = sample.get("sample_id") or f"sample-{index:04d}"
    try:
        raw, attempts = await _call_with_retries(
            _build_messages(sample["utterance"], None, VALID_NODES),
            model=model,
            retries=retries,
            retry_delay_seconds=retry_delay_seconds,
        )
        raw_parsed, raw_scored = _score_raw_llm(raw, sample)
        if raw_scored["match"]:
            final_parsed = raw_parsed
            final_scored = raw_scored
            final_source = "llm_qwen"
        else:
            final_parsed = parse_intent(sample["utterance"], valid_nodes=VALID_NODES)
            final_scored = score_parsed_result(final_parsed, sample.get("expected", {}))
            final_source = "rule_fallback"
        run = {
            **final_scored,
            "attempts": attempts,
            "llm_raw_match": raw_scored["match"],
            "llm_raw_details": raw_scored["details"],
            "parser_name": "system_intent_parser",
            "parser_version": final_parsed.parser_version,
            "model": model,
            "final_source": final_source,
            "final_parser_name": final_parsed.parser_name,
            "final_parser_version": final_parsed.parser_version,
            "raw_llm_response": raw,
            "llm_raw_result": _parse_result_payload(raw_parsed),
            "parsed_result": _parse_result_payload(final_parsed),
            "expected_result": sample.get("expected", {}),
            "sample_payload": sample,
        }
        match = run["match"]
    except BaseException as exc:  # noqa: BLE001 - report the sample and continue.
        final_parsed = parse_intent(sample["utterance"], valid_nodes=VALID_NODES)
        final_scored = score_parsed_result(final_parsed, sample.get("expected", {}))
        run = {
            **final_scored,
            "attempts": retries + 1,
            "llm_raw_match": False,
            "llm_raw_details": {"llm_error": {"expected": None, "got": str(exc)}},
            "parser_name": "system_intent_parser",
            "parser_version": final_parsed.parser_version,
            "model": model,
            "final_source": "rule_fallback",
            "final_parser_name": final_parsed.parser_name,
            "final_parser_version": final_parsed.parser_version,
            "raw_llm_response": None,
            "llm_raw_result": None,
            "parsed_result": _parse_result_payload(final_parsed),
            "expected_result": sample.get("expected", {}),
            "sample_payload": sample,
        }
        match = run["match"]

    return {
        "sample_id": sample_id,
        "case_type": sample.get("case_type", "valid"),
        "utterance": sample["utterance"],
        "expected": sample.get("expected", {}),
        "sample_payload": sample,
        "match": match,
        "runs": [run],
    }


async def run_online_evaluation(
    *,
    model: str | None = None,
    limit: int | None = None,
    concurrency: int = 1,
    retries: int = 3,
    retry_delay_seconds: float = 3.0,
    resume: bool = False,
    evaluation_id: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    rows = _load_online_dataset()
    if limit is not None:
        rows = rows[: max(0, limit)]
    if not rows:
        raise ValueError("Intent evaluation dataset is empty")
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")

    selected_model = normalize_eval_model(model)
    evaluation_id = evaluation_id or f"online-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    started_at = started_at or _now_iso()
    completed_by_id = _read_progress(ONLINE_PROGRESS_PATH) if resume else {}
    if not resume and ONLINE_PROGRESS_PATH.exists():
        ONLINE_PROGRESS_PATH.unlink()
    _write_online_status({
        "evaluation_id": evaluation_id,
        "engine": "llm_qwen_online",
        "model": selected_model,
        "status": "running",
        "total": len(rows),
        "completed": len(completed_by_id),
        "correct": sum(1 for item in completed_by_id.values() if item.get("match")),
        "failed": 0,
        "accuracy": None,
        "started_at": started_at,
        "finished_at": None,
        "concurrency": concurrency,
        "retries": retries,
        "limit": limit,
        "resume": resume,
    })

    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    results_by_index: dict[int, dict[str, Any]] = {}

    for index, sample in enumerate(rows):
        sample_id = sample.get("sample_id") or f"sample-{index:04d}"
        if sample_id in completed_by_id:
            results_by_index[index] = completed_by_id[sample_id]

    async def run_one(index: int, sample: dict[str, Any]) -> None:
        async with sem:
            item = await _evaluate_sample(
                index=index,
                sample=sample,
                model=selected_model,
                retries=retries,
                retry_delay_seconds=retry_delay_seconds,
            )
            async with lock:
                results_by_index[index] = item
                _append_progress(ONLINE_PROGRESS_PATH, item)
                completed = len(results_by_index)
                correct = sum(1 for row in results_by_index.values() if row.get("match"))
                _write_online_status({
                    "evaluation_id": evaluation_id,
                    "engine": "llm_qwen_online",
                    "model": selected_model,
                    "status": "running",
                    "total": len(rows),
                    "completed": completed,
                    "correct": correct,
                    "failed": 0,
                    "accuracy": correct / completed if completed else None,
                    "started_at": started_at,
                    "finished_at": None,
                    "concurrency": concurrency,
                    "retries": retries,
                    "limit": limit,
                    "resume": resume,
                })

    await asyncio.gather(
        *[
            run_one(index, sample)
            for index, sample in enumerate(rows)
            if index not in results_by_index
        ]
    )

    results = [results_by_index[index] for index in sorted(results_by_index)]
    correct = sum(1 for item in results if item.get("match"))
    raw_returned = sum(1 for item in results if (item.get("runs") or [{}])[0].get("raw_llm_response") is not None)
    raw_correct = sum(1 for item in results if (item.get("runs") or [{}])[0].get("llm_raw_match"))
    final_sources = Counter((item.get("runs") or [{}])[0].get("final_source", "unknown") for item in results)
    total = len(results)
    raw_accuracy = raw_correct / total if total else 0

    report = {
        "evaluation_id": evaluation_id,
        "engine": "llm_qwen_online",
        "parser_name": "system_intent_parser",
        "parser_version": "online",
        "model": selected_model,
        "dataset": _online_dataset_summary(),
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0,
        "target_accuracy": 0.9,
        "passed": (correct / total) >= 0.9 if total else False,
        "started_at": started_at,
        "finished_at": _now_iso(),
        "generated_at": _now_iso(),
        "concurrency": concurrency,
        "retries": retries,
        "resume": resume,
        "limit": limit,
        "llm_raw_summary": {
            "returned": raw_returned,
            "total": total,
            "correct": raw_correct,
            "accuracy": raw_accuracy,
            "passed": raw_accuracy >= 0.9 if total else False,
            "note": "内部诊断：仅统计大模型原始结构化输出，不含系统确定性校验/补全。",
        },
        "final_source_counts": dict(final_sources),
        "summary": {},
        "results": results,
    }
    report["summary"] = _summarize_results(results)
    ONLINE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ONLINE_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_online_status({
        "evaluation_id": evaluation_id,
        "engine": "llm_qwen_online",
        "model": selected_model,
        "status": "completed",
        "total": total,
        "completed": total,
        "correct": correct,
        "failed": 0,
        "accuracy": report["accuracy"],
        "passed": report["passed"],
        "started_at": started_at,
        "finished_at": report["finished_at"],
        "concurrency": concurrency,
        "retries": retries,
        "limit": limit,
        "resume": resume,
        "report_path": str(ONLINE_REPORT_PATH),
    })
    return report


def online_eval_config() -> dict[str, Any]:
    return {
        "online_eval_models": available_eval_models(),
        "online_report_path": str(ONLINE_REPORT_PATH),
        "online_progress_path": str(ONLINE_PROGRESS_PATH),
        "online_status_path": str(ONLINE_STATUS_PATH),
    }
