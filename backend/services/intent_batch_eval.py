"""Intent parser evaluation helpers.

This module owns the fixed-dataset evaluation flow used by the admin
acceptance UI.  It supports two paths:

- local rule evaluation for fast regression checks
- DashScope/OpenAI-compatible Batch API jobs for official LLM evaluation
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from config import settings
from services.intent_parser import ParseResult, parse_intent
from services.llm_intent_parser import _build_messages, _raw_to_parse_result, _validate_and_clean


REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = REPO_ROOT / "datasets" / "intent_eval" / "multi_business.jsonl"
REPORTS_DIR = REPO_ROOT / "reports"
RULE_REPORT_PATH = REPORTS_DIR / "intent_eval.json"
LLM_REPORT_PATH = REPORTS_DIR / "intent_eval_llm.json"
BATCH_DIR = REPORTS_DIR / "intent_eval_batches"
VALID_NODES = ["compute-1", "compute-2", "compute-3"]


def available_eval_models() -> list[str]:
    values = [item.strip() for item in settings.dashscope_eval_models.split(",")]
    return [item for item in values if item]


def normalize_eval_model(model: str | None = None) -> str:
    allowed = available_eval_models()
    selected = (model or (allowed[0] if allowed else settings.dashscope_model)).strip()
    if selected not in allowed:
        raise ValueError(f"Unsupported DashScope evaluation model: {selected}")
    return selected


ACTIVE_BATCH_STATUSES = {"validating", "in_progress", "finalizing", "submitted", "cancelling"}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _format_datetime(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.replace(microsecond=0).isoformat(sep=" ")


def _duration_minutes(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    return (end - start).total_seconds() / 60


def _parse_result_payload(parsed: ParseResult) -> dict[str, Any]:
    return {
        "task_type": parsed.task_type,
        "modality": parsed.modality,
        "source_name": parsed.source_name,
        "destination_name": parsed.destination_name,
        "business_start_time": _format_datetime(parsed.business_start_time),
        "business_end_time": _format_datetime(parsed.business_end_time),
        "data_profile": parsed.data_profile,
        "business_objective": parsed.business_objective,
        "runtime_plan": parsed.runtime_plan,
        "resource_requirement": parsed.resource_requirement,
        "validation_errors": parsed.validation_errors,
        "parse_status": parsed.parse_status,
        "assistant_message": parsed.assistant_message,
        "parser_name": parsed.parser_name,
        "parser_version": parsed.parser_version,
    }


def load_dataset() -> list[dict[str, Any]]:
    if not DATASET_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    with DATASET_PATH.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def dataset_summary() -> dict[str, Any]:
    rows = load_dataset()
    case_counts = Counter(row.get("case_type", "valid") for row in rows)
    task_counts = Counter((row.get("expected") or {}).get("task_type", "unknown") for row in rows)
    modality_counts = Counter((row.get("expected") or {}).get("modality", "unknown") for row in rows)
    dataset_bytes = DATASET_PATH.read_bytes() if DATASET_PATH.exists() else b""
    return {
        "path": str(DATASET_PATH.relative_to(REPO_ROOT)),
        "total": len(rows),
        "sha256": hashlib.sha256(dataset_bytes).hexdigest() if dataset_bytes else None,
        "updated_at": _format_datetime(datetime.fromtimestamp(DATASET_PATH.stat().st_mtime)) if DATASET_PATH.exists() else None,
        "case_counts": dict(case_counts),
        "task_counts": dict(task_counts),
        "modality_counts": dict(modality_counts),
        "valid_nodes": VALID_NODES,
    }


def _field_value(parsed: ParseResult, key: str) -> Any:
    if key in (parsed.data_profile or {}):
        return (parsed.data_profile or {}).get(key)
    if key in (parsed.runtime_plan or {}):
        return (parsed.runtime_plan or {}).get(key)
    return getattr(parsed, key, None)


def _missing_param_keys(parsed: ParseResult, expected: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    if not parsed.source_name:
        keys.append("source_name")
    if not parsed.destination_name:
        keys.append("destination_name")
    if not parsed.business_start_time:
        keys.append("business_start_time")
    if not parsed.business_end_time:
        keys.append("business_end_time")

    for key in (expected.get("data_profile") or {}):
        if _field_value(parsed, key) is None:
            keys.append(key)
    return sorted(set(keys))


def score_parsed_result(parsed: ParseResult, expected: dict[str, Any]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    match = True

    for key in ("task_type", "modality", "source_name", "destination_name", "parse_status"):
        exp_val = expected.get(key)
        got_val = getattr(parsed, key, None)
        details[key] = {"expected": exp_val, "got": got_val}
        if exp_val != got_val:
            match = False

    expected_profile = expected.get("data_profile") or {}
    for key in expected_profile:
        exp_val = expected_profile.get(key)
        got_val = _field_value(parsed, key)
        details[key] = {"expected": exp_val, "got": got_val}
        if exp_val != got_val:
            match = False

    expected_runtime = expected.get("runtime_plan") or {}
    for key in expected_runtime:
        exp_val = expected_runtime.get(key)
        got_val = _field_value(parsed, key)
        details[key] = {"expected": exp_val, "got": got_val}
        if exp_val != got_val:
            match = False

    expected_time = expected.get("expected_time") or {}
    expected_duration = expected_time.get("duration_minutes")
    if expected_duration is not None:
        got_duration = _duration_minutes(parsed.business_start_time, parsed.business_end_time)
        details["duration_minutes"] = {
            "expected": expected_duration,
            "got": round(got_duration, 3) if got_duration is not None else None,
        }
        if got_duration is None or abs(got_duration - float(expected_duration)) > 2:
            match = False

    if expected.get("parse_status") == "valid":
        for key in ("business_start_time", "business_end_time"):
            got_val = getattr(parsed, key, None)
            details[key] = {"expected": "present", "got": _format_datetime(got_val)}
            if got_val is None:
                match = False

    expected_missing = sorted(expected.get("missing_params") or [])
    if expected_missing or expected.get("parse_status") == "incomplete":
        got_missing = _missing_param_keys(parsed, expected)
        details["missing_params"] = {"expected": expected_missing, "got": got_missing}
        if expected_missing != got_missing:
            match = False

    return {"match": match, "details": details}


def _summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, dict[str, Any]] = {}
    by_field: dict[str, dict[str, int]] = {}

    for item in results:
        case_type = item.get("case_type", "valid")
        case_row = by_case.setdefault(case_type, {"total": 0, "correct": 0, "accuracy": 0})
        case_row["total"] += 1
        if item.get("match"):
            case_row["correct"] += 1

        run = (item.get("runs") or [{}])[0]
        for field, detail in (run.get("details") or {}).items():
            if detail.get("expected") == "present":
                ok = detail.get("got") is not None
            else:
                ok = detail.get("expected") == detail.get("got")
            field_row = by_field.setdefault(field, {"total": 0, "correct": 0})
            field_row["total"] += 1
            field_row["correct"] += 1 if ok else 0

    for row in by_case.values():
        row["accuracy"] = row["correct"] / row["total"] if row["total"] else 0
    field_accuracy = {
        key: {
            **row,
            "accuracy": row["correct"] / row["total"] if row["total"] else 0,
        }
        for key, row in by_field.items()
    }
    return {"by_case": by_case, "by_field": field_accuracy}


def run_rule_evaluation(repeats: int = 3) -> dict[str, Any]:
    rows = load_dataset()
    results: list[dict[str, Any]] = []
    correct = 0
    evaluation_id = f"rule-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"

    for index, sample in enumerate(rows):
        run_results = []
        for _ in range(repeats):
            parsed = parse_intent(sample["utterance"], valid_nodes=VALID_NODES)
            scored = score_parsed_result(parsed, sample.get("expected", {}))
            run_results.append({
                **scored,
                "parser_name": parsed.parser_name,
                "parser_version": parsed.parser_version,
                "parsed_result": _parse_result_payload(parsed),
                "expected_result": sample.get("expected", {}),
                "sample_payload": sample,
            })
        match = Counter(result["match"] for result in run_results)[True] >= (repeats + 1) // 2
        if match:
            correct += 1
        results.append({
            "sample_id": f"sample-{index:04d}",
            "case_type": sample.get("case_type", "valid"),
            "utterance": sample["utterance"],
            "expected": sample.get("expected", {}),
            "sample_payload": sample,
            "match": match,
            "runs": run_results,
        })

    report = {
        "evaluation_id": evaluation_id,
        "engine": "rule_parser",
        "parser_name": "rule_based",
        "parser_version": "2.0",
        "dataset": dataset_summary(),
        "total": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows) if rows else 0,
        "target_accuracy": 0.9,
        "passed": (correct / len(rows)) >= 0.9 if rows else False,
        "repeats": repeats,
        "generated_at": _now_iso(),
        "summary": {},
        "results": results,
    }
    report["summary"] = _summarize_results(results)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    RULE_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def read_report(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def latest_status() -> dict[str, Any]:
    return {
        "dataset": dataset_summary(),
        "rule_report": read_report(RULE_REPORT_PATH),
        "llm_report": read_report(LLM_REPORT_PATH),
        "batch_job": read_latest_batch_job(),
        "config": {
            "intent_parser_engine": settings.intent_parser_engine,
            "dashscope_model": settings.dashscope_model,
            "dashscope_models": available_eval_models(),
            "dashscope_configured": bool(settings.dashscope_api_key),
            "batch_base_url": settings.dashscope_base_url,
        },
    }


class DashScopeBatchClient:
    def __init__(self) -> None:
        if not settings.dashscope_api_key:
            raise ValueError("DASHSCOPE_API_KEY is not configured")
        self.base_url = settings.dashscope_base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {settings.dashscope_api_key}"}

    async def upload_file(self, path: Path) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            with path.open("rb") as f:
                response = await client.post(
                    f"{self.base_url}/files",
                    headers=self.headers,
                    data={"purpose": "batch"},
                    files={"file": (path.name, f, "application/jsonl")},
                )
        response.raise_for_status()
        return response.json()

    async def create_batch(self, input_file_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "input_file_id": input_file_id,
            "endpoint": "/v1/chat/completions",
            "completion_window": "24h",
            "metadata": metadata,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/batches",
                headers={**self.headers, "Content-Type": "application/json"},
                json=payload,
            )
        response.raise_for_status()
        return response.json()

    async def retrieve_batch(self, batch_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(f"{self.base_url}/batches/{batch_id}", headers=self.headers)
        response.raise_for_status()
        return response.json()

    async def cancel_batch(self, batch_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/batches/{batch_id}/cancel", headers=self.headers)
        response.raise_for_status()
        return response.json()

    async def download_file(self, file_id: str, output_path: Path) -> Path:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(f"{self.base_url}/files/{file_id}/content", headers=self.headers)
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        return output_path


def _batch_job_path(job_id: str) -> Path:
    return BATCH_DIR / f"{job_id}.json"


def _write_batch_job(job: dict[str, Any]) -> dict[str, Any]:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    job["updated_at"] = _now_iso()
    _batch_job_path(job["job_id"]).write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    (BATCH_DIR / "latest.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    return job


def read_latest_batch_job() -> dict[str, Any] | None:
    latest = BATCH_DIR / "latest.json"
    if not latest.exists():
        return None
    return json.loads(latest.read_text(encoding="utf-8"))


def build_batch_input(job_id: str, model: str) -> tuple[Path, list[dict[str, Any]]]:
    rows = load_dataset()
    input_path = BATCH_DIR / job_id / "input.jsonl"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open("w", encoding="utf-8") as f:
        for index, sample in enumerate(rows):
            body = {
                "model": model,
                "messages": _build_messages(sample["utterance"], None, VALID_NODES),
                "temperature": settings.dashscope_temperature,
                "response_format": {"type": "json_object"},
            }
            line = {
                "custom_id": f"sample-{index:04d}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            }
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return input_path, rows


async def submit_llm_batch_evaluation(model: str | None = None) -> dict[str, Any]:
    rows = load_dataset()
    if not rows:
        raise ValueError("Intent evaluation dataset is empty")
    latest_job = read_latest_batch_job()
    if latest_job and latest_job.get("status") in ACTIVE_BATCH_STATUSES:
        raise ValueError(
            "An LLM batch evaluation is already running. "
            "Refresh or cancel it before submitting a new evaluation."
        )
    selected_model = normalize_eval_model(model)
    job_id = f"intent-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    input_path, _rows = build_batch_input(job_id, selected_model)
    client = DashScopeBatchClient()
    upload = await client.upload_file(input_path)
    input_file_id = upload.get("id")
    if not input_file_id:
        raise ValueError(f"DashScope file upload response has no id: {upload}")

    batch = await client.create_batch(
        input_file_id,
        metadata={
            "job_id": job_id,
            "dataset": str(DATASET_PATH.relative_to(REPO_ROOT)),
            "sample_count": len(rows),
            "model": selected_model,
        },
    )
    job = {
        "job_id": job_id,
        "model": selected_model,
        "batch_id": batch.get("id"),
        "status": batch.get("status", "submitted"),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "dataset_path": str(DATASET_PATH.relative_to(REPO_ROOT)),
        "input_jsonl_path": str(input_path.relative_to(REPO_ROOT)),
        "input_file_id": input_file_id,
        "output_file_id": batch.get("output_file_id"),
        "error_file_id": batch.get("error_file_id"),
        "request_counts": batch.get("request_counts"),
        "raw_batch": batch,
        "report_path": None,
        "last_error": None,
    }
    return _write_batch_job(job)


def _extract_raw_llm_json(output_line: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if output_line.get("error"):
        return None, json.dumps(output_line["error"], ensure_ascii=False)
    response = output_line.get("response") or {}
    body = response.get("body") or {}
    try:
        content = body["choices"][0]["message"]["content"]
        return json.loads(content), None
    except Exception as exc:
        return None, f"failed to parse LLM JSON: {exc}"


def score_batch_output(job: dict[str, Any], output_path: Path) -> dict[str, Any]:
    rows = load_dataset()
    by_id = {f"sample-{index:04d}": sample for index, sample in enumerate(rows)}
    results: list[dict[str, Any]] = []
    correct = 0
    model = job.get("model") or settings.dashscope_model

    with output_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            output_line = json.loads(line)
            custom_id = output_line.get("custom_id")
            sample = by_id.get(custom_id)
            if not sample:
                continue
            raw, error = _extract_raw_llm_json(output_line)
            if raw is None:
                run = {
                    "match": False,
                    "details": {"llm_error": {"expected": None, "got": error}},
                    "parser_name": "llm_qwen",
                    "parser_version": model,
                    "raw_llm_response": None,
                    "parsed_result": None,
                    "expected_result": sample.get("expected", {}),
                    "sample_payload": sample,
                }
            else:
                cleaned = _validate_and_clean(raw, VALID_NODES)
                parsed = _raw_to_parse_result(cleaned, None, utterance=sample["utterance"])
                scored = score_parsed_result(parsed, sample.get("expected", {}))
                run = {
                    **scored,
                    "parser_name": parsed.parser_name,
                    "parser_version": model,
                    "raw_llm_response": raw,
                    "parsed_result": _parse_result_payload(parsed),
                    "expected_result": sample.get("expected", {}),
                    "sample_payload": sample,
                }
            match = run["match"]
            if match:
                correct += 1
            results.append({
                "sample_id": custom_id,
                "case_type": sample.get("case_type", "valid"),
                "utterance": sample["utterance"],
                "expected": sample.get("expected", {}),
                "sample_payload": sample,
                "match": match,
                "runs": [run],
            })

    total = len(rows)
    report = {
        "evaluation_id": job["job_id"],
        "engine": "llm_qwen_batch",
        "parser_name": "llm_qwen",
        "parser_version": model,
        "model": model,
        "dataset": dataset_summary(),
        "batch_job_id": job["job_id"],
        "batch_id": job.get("batch_id"),
        "total": total,
        "returned": len(results),
        "correct": correct,
        "accuracy": correct / total if total else 0,
        "target_accuracy": 0.9,
        "passed": (correct / total) >= 0.9 if total else False,
        "generated_at": _now_iso(),
        "summary": {},
        "results": results,
    }
    report["summary"] = _summarize_results(results)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    LLM_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


async def refresh_latest_llm_batch() -> dict[str, Any]:
    job = read_latest_batch_job()
    if not job:
        raise ValueError("No LLM batch evaluation job found")
    batch_id = job.get("batch_id")
    if not batch_id:
        raise ValueError("Latest LLM batch evaluation job has no batch_id")

    client = DashScopeBatchClient()
    batch = await client.retrieve_batch(batch_id)
    job["status"] = batch.get("status", job.get("status"))
    job["output_file_id"] = batch.get("output_file_id")
    job["error_file_id"] = batch.get("error_file_id")
    job["request_counts"] = batch.get("request_counts")
    job["raw_batch"] = batch

    if job["status"] == "completed" and job.get("output_file_id"):
        output_path = BATCH_DIR / job["job_id"] / "output.jsonl"
        await client.download_file(job["output_file_id"], output_path)
        report = score_batch_output(job, output_path)
        job["output_jsonl_path"] = str(output_path.relative_to(REPO_ROOT))
        job["report_path"] = str(LLM_REPORT_PATH.relative_to(REPO_ROOT))
        job["summary"] = {
            "total": report["total"],
            "correct": report["correct"],
            "accuracy": report["accuracy"],
            "passed": report["passed"],
        }

    return _write_batch_job(job)


async def cancel_latest_llm_batch() -> dict[str, Any]:
    job = read_latest_batch_job()
    if not job:
        raise ValueError("No LLM batch evaluation job found")
    batch_id = job.get("batch_id")
    if not batch_id:
        raise ValueError("Latest LLM batch evaluation job has no batch_id")
    if job.get("status") not in ACTIVE_BATCH_STATUSES:
        raise ValueError(f"Latest LLM batch evaluation is not running: {job.get('status')}")

    client = DashScopeBatchClient()
    batch = await client.cancel_batch(batch_id)
    job["status"] = batch.get("status", "cancelling")
    job["output_file_id"] = batch.get("output_file_id")
    job["error_file_id"] = batch.get("error_file_id")
    job["request_counts"] = batch.get("request_counts")
    job["raw_batch"] = batch
    job["cancelled_at"] = _now_iso()
    return _write_batch_job(job)
