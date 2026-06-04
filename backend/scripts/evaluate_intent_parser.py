"""意图解析批量评测脚本。

用法：
    python backend/scripts/evaluate_intent_parser.py \
        --dataset datasets/intent_eval/matmul.jsonl \
        --output reports/intent_eval.json
"""

import argparse
from collections import Counter
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.intent_parser import parse_intent

VALID_NODES = ["compute-1", "compute-2", "compute-3"]


def _field_value(parsed, key: str):
    if key in ("matrix_size", "batch_count"):
        return (parsed.data_profile or {}).get(key)
    if key == "routing_strategy":
        return (parsed.runtime_plan or {}).get(key)
    return getattr(parsed, key, None)


def _evaluate_once(utterance: str, expected: dict) -> dict:
    parsed = parse_intent(utterance, valid_nodes=VALID_NODES)
    details = {}
    match = True

    for key in ("task_type", "source_name", "destination_name", "parse_status"):
        exp_val = expected.get(key)
        got_val = getattr(parsed, key, None)
        details[key] = {"expected": exp_val, "got": got_val}
        if exp_val != got_val:
            match = False

    expected_profile = expected.get("data_profile") or {}
    for key in ("matrix_size", "batch_count"):
        exp_val = expected_profile.get(key)
        got_val = _field_value(parsed, key)
        details[key] = {"expected": exp_val, "got": got_val}
        if exp_val != got_val:
            match = False

    expected_runtime = expected.get("runtime_plan") or {}
    if "routing_strategy" in expected_runtime:
        exp_val = expected_runtime.get("routing_strategy")
        got_val = _field_value(parsed, "routing_strategy")
        details["routing_strategy"] = {"expected": exp_val, "got": got_val}
        if exp_val != got_val:
            match = False

    if expected.get("parse_status") == "valid":
        for key in ("business_start_time", "business_end_time"):
            got_val = getattr(parsed, key, None)
            details[key] = {"expected": "present", "got": str(got_val) if got_val else None}
            if got_val is None:
                match = False

    return {
        "match": match,
        "details": details,
        "parser_name": parsed.parser_name,
        "parser_version": parsed.parser_version,
    }


def _majority_vote(run_results: list[dict]) -> bool:
    votes = Counter(result["match"] for result in run_results)
    return votes[True] >= votes[False]


def evaluate(dataset_path: str, output_path: str | None = None, repeats: int = 3) -> dict:
    results = []
    correct = 0
    total = 0

    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            sample = json.loads(line)
            utterance = sample["utterance"]
            expected = sample.get("expected", {})

            run_results = [_evaluate_once(utterance, expected) for _ in range(repeats)]
            match = _majority_vote(run_results)
            total += 1

            if match:
                correct += 1

            results.append({
                "utterance": utterance,
                "match": match,
                "runs": run_results,
            })

    report = {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total > 0 else 0,
        "repeats": repeats,
        "results": results,
    }

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    report = evaluate(args.dataset, args.output, args.repeats)
    print(f"Accuracy: {report['correct']}/{report['total']} = {report['accuracy']:.2%}")
