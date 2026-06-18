"""意图解析批量评测脚本。

用法：
    python backend/scripts/evaluate_intent_parser.py \
        --dataset datasets/intent_eval/matmul.jsonl \
        --output reports/intent_eval.json
"""

import argparse
from collections import Counter
from datetime import datetime
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.intent_parser import parse_intent
from services.intent_batch_eval import sample_expected, score_parsed_result
from services.topology_catalog import TERMINAL_NODE_ALIASES

VALID_NODES = TERMINAL_NODE_ALIASES


def _parsed_payload(parsed) -> dict:
    return {
        "task_type": parsed.task_type,
        "modality": parsed.modality,
        "source_name": parsed.source_name,
        "destination_name": parsed.destination_name,
        "business_start_time": str(parsed.business_start_time) if parsed.business_start_time else None,
        "business_end_time": str(parsed.business_end_time) if parsed.business_end_time else None,
        "data_profile": parsed.data_profile,
        "runtime_plan": parsed.runtime_plan,
        "business_objective": parsed.business_objective,
        "parse_status": parsed.parse_status,
        "validation_errors": parsed.validation_errors,
    }


def _evaluate_once(utterance: str, expected: dict) -> dict:
    parsed = parse_intent(utterance, valid_nodes=VALID_NODES)
    scored = score_parsed_result(parsed, expected)
    return {
        **scored,
        "parsed_result": _parsed_payload(parsed),
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
            expected = sample_expected(sample)

            run_results = [_evaluate_once(utterance, expected) for _ in range(repeats)]
            match = _majority_vote(run_results)
            total += 1

            if match:
                correct += 1

            results.append({
                "sample_id": sample.get("sample_id", f"sample-{total - 1:04d}"),
                "case_type": sample.get("case_type", "valid"),
                "utterance": utterance,
                "expected": expected,
                "sample_payload": sample,
                "match": match,
                "runs": run_results,
            })

    report = {
        "evaluation_id": f"cli-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}",
        "engine": "rule_parser_cli",
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
