from datetime import datetime, timedelta
import json

import services.intent_batch_eval as intent_batch_eval
from services.intent_batch_eval import batch_diagnostic, latest_status, score_batch_output, score_parsed_result
from services.intent_parser import ParseResult


def _parsed(**overrides):
    now = datetime(2026, 6, 8, 10, 0, 0)
    data = {
        "task_type": "high_throughput_matmul",
        "modality": "high_throughput_compute",
        "source_name": "compute-1",
        "destination_name": "compute-2",
        "business_start_time": now,
        "business_end_time": now + timedelta(minutes=120),
        "data_profile": {"matrix_size": 512, "batch_count": 20},
        "runtime_plan": {"routing_strategy": "resource_guarantee"},
        "parse_status": "valid",
    }
    data.update(overrides)
    return ParseResult(**data)


def test_score_normalizes_legacy_modality_code():
    result = score_parsed_result(
        _parsed(),
        {
            "task_type": "high_throughput_matmul",
            "modality": "高通量计算模态",
            "source_name": "compute-1",
            "destination_name": "compute-2",
            "parse_status": "valid",
            "data_profile": {"matrix_size": 512, "batch_count": 20},
            "runtime_plan": {"routing_strategy": "resource_guarantee"},
            "expected_time": {"duration_minutes": 120},
        },
    )

    assert result["match"] is True
    assert result["details"]["modality"] == {
        "expected": "高通量计算模态",
        "got": "high_throughput_compute",
    }


def test_score_ignores_top_level_fields_missing_from_expected():
    result = score_parsed_result(
        _parsed(),
        {
            "task_type": "high_throughput_matmul",
            "source_name": "compute-1",
            "destination_name": "compute-2",
            "parse_status": "valid",
            "data_profile": {"matrix_size": 512, "batch_count": 20},
            "runtime_plan": {"routing_strategy": "resource_guarantee"},
            "expected_time": {"duration_minutes": 120},
        },
    )

    assert result["match"] is True
    assert "modality" not in result["details"]


def test_batch_diagnostic_flags_long_running_zero_progress_job():
    now = datetime(2026, 6, 16, 12, 0, 0)
    diagnostic = batch_diagnostic(
        {
            "status": "in_progress",
            "created_at": (now - timedelta(hours=3)).isoformat(timespec="seconds"),
            "request_counts": {"total": 360, "completed": 0, "failed": 0},
        },
        now=now,
    )

    assert diagnostic is not None
    assert diagnostic["code"] == "dashscope_batch_zero_progress"
    assert diagnostic["level"] == "warning"


def test_batch_diagnostic_ignores_active_job_with_progress():
    now = datetime(2026, 6, 16, 12, 0, 0)
    diagnostic = batch_diagnostic(
        {
            "status": "in_progress",
            "created_at": (now - timedelta(hours=3)).isoformat(timespec="seconds"),
            "request_counts": {"total": 360, "completed": 12, "failed": 0},
        },
        now=now,
    )

    assert diagnostic is None


def test_latest_status_uses_matching_llm_report_summary_for_batch_job(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    batch_dir = reports_dir / "intent_eval_batches"
    batch_dir.mkdir(parents=True)
    batch_job = {
        "job_id": "intent-eval-test",
        "batch_id": "batch-1",
        "status": "completed",
        "request_counts": {"total": 360, "completed": 360, "failed": 0},
        "summary": {"total": 360, "correct": 74, "accuracy": 0.20555555555555555, "passed": False},
    }
    llm_report = {
        "evaluation_id": "intent-eval-test",
        "batch_id": "batch-1",
        "total": 360,
        "correct": 360,
        "accuracy": 1.0,
        "passed": True,
    }
    (batch_dir / "latest.json").write_text(json.dumps(batch_job), encoding="utf-8")
    llm_report_path = reports_dir / "intent_eval_llm.json"
    llm_report_path.write_text(json.dumps(llm_report), encoding="utf-8")
    rule_report_path = reports_dir / "intent_eval.json"
    rule_report_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(intent_batch_eval, "BATCH_DIR", batch_dir)
    monkeypatch.setattr(intent_batch_eval, "LLM_REPORT_PATH", llm_report_path)
    monkeypatch.setattr(intent_batch_eval, "RULE_REPORT_PATH", rule_report_path)

    status = latest_status()

    assert status["llm_report"]["accuracy"] == 1.0
    assert status["batch_job"]["summary"] == {
        "total": 360,
        "correct": 360,
        "accuracy": 1.0,
        "passed": True,
    }


def test_score_batch_output_reports_final_accuracy_with_raw_llm_diagnostics(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    batch_dir = reports_dir / "intent_eval_batches"
    dataset_path = tmp_path / "datasets" / "multi_business.jsonl"
    output_path = batch_dir / "job-1" / "output.jsonl"
    dataset_path.parent.mkdir(parents=True)
    output_path.parent.mkdir(parents=True)

    sample = {
        "case_type": "valid",
        "utterance": "矩阵乘法任务，从 compute-1 到 compute-2，512阶矩阵，20批，现在开始跑2小时，希望成本更低",
        "expected": {
            "task_type": "high_throughput_matmul",
            "modality": "高通量计算模态",
            "source_name": "compute-1",
            "destination_name": "compute-2",
            "parse_status": "valid",
            "data_profile": {"matrix_size": 512, "batch_count": 20},
            "runtime_plan": {"routing_strategy": "cost_priority"},
            "expected_time": {"duration_minutes": 120},
        },
    }
    dataset_path.write_text(json.dumps(sample, ensure_ascii=False) + "\n", encoding="utf-8")

    # Simulate an LLM that got the route strategy wrong. The final product
    # parser can still deterministically recover it from the original utterance.
    raw_llm = {
        "task_type": "high_throughput_matmul",
        "source_name": "compute-1",
        "destination_name": "compute-2",
        "start_time": "now",
        "duration_hours": 2,
        "matrix_size": 512,
        "batch_count": 20,
        "routing_strategy": "resource_guarantee",
    }
    output_line = {
        "custom_id": "sample-0000",
        "response": {
            "body": {
                "choices": [
                    {"message": {"content": json.dumps(raw_llm, ensure_ascii=False)}}
                ]
            }
        },
    }
    output_path.write_text(json.dumps(output_line, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(intent_batch_eval, "DATASET_PATH", dataset_path)
    monkeypatch.setattr(intent_batch_eval, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(intent_batch_eval, "BATCH_DIR", batch_dir)
    monkeypatch.setattr(intent_batch_eval, "LLM_REPORT_PATH", reports_dir / "intent_eval_llm.json")

    report = score_batch_output({"job_id": "job-1", "batch_id": "batch-1", "model": "qwen-test"}, output_path)

    assert report["correct"] == 1
    assert report["accuracy"] == 1.0
    assert report["llm_raw_summary"]["correct"] == 0
    assert report["llm_raw_summary"]["accuracy"] == 0.0
    run = report["results"][0]["runs"][0]
    assert run["match"] is True
    assert run["llm_raw_match"] is False
    assert run["final_source"] == "rule_fallback"
    assert run["final_parser_name"] == "rule_based"
