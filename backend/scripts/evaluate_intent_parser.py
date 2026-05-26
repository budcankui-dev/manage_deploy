"""意图解析批量评测脚本。

用法：
    python backend/scripts/evaluate_intent_parser.py \
        --dataset datasets/intent_eval/matmul.jsonl \
        --output reports/intent_eval.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.intent_parser import parse_intent


def evaluate(dataset_path: str, output_path: str | None = None) -> dict:
    results = []
    correct = 0
    total = 0

    with open(dataset_path) as f:
        for line in f:
            if not line.strip():
                continue
            sample = json.loads(line)
            utterance = sample["utterance"]
            expected = sample.get("expected", {})

            parsed = parse_intent(utterance)
            total += 1

            match = True
            details = {}
            for key in ("task_type", "source_name", "destination_name"):
                exp_val = expected.get(key)
                got_val = getattr(parsed, key, None)
                details[key] = {"expected": exp_val, "got": got_val}
                if exp_val and got_val != exp_val:
                    match = False

            if expected.get("parse_status"):
                details["parse_status"] = {
                    "expected": expected["parse_status"],
                    "got": parsed.parse_status,
                }
                if parsed.parse_status != expected["parse_status"]:
                    match = False

            if match:
                correct += 1

            results.append({
                "utterance": utterance,
                "match": match,
                "details": details,
            })

    report = {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total > 0 else 0,
        "results": results,
    }

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    report = evaluate(args.dataset, args.output)
    print(f"Accuracy: {report['correct']}/{report['total']} = {report['accuracy']:.2%}")
