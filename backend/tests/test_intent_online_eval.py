import json

import pytest

import services.intent_online_eval as intent_online_eval
import services.intent_batch_eval as intent_batch_eval
import api.admin as admin_api
from enums import UserRole
from tests.test_business_tasks_api import _auth_headers


def _sample(expected_strategy: str = "cost_priority") -> dict:
    return {
        "case_type": "valid",
        "utterance": "矩阵乘法任务，从 compute-1 到 compute-2，512阶矩阵，20批，现在开始跑2小时，希望成本更低",
        "expected": {
            "task_type": "high_throughput_matmul",
            "modality": "高通量计算模态",
            "source_name": "compute-1",
            "destination_name": "compute-2",
            "parse_status": "valid",
            "data_profile": {"matrix_size": 512, "batch_count": 20},
            "runtime_plan": {"routing_strategy": expected_strategy},
            "expected_time": {"duration_minutes": 120},
        },
    }


def _raw(strategy: str = "cost_priority") -> dict:
    return {
        "task_type": "high_throughput_matmul",
        "source_name": "compute-1",
        "destination_name": "compute-2",
        "start_time": "now",
        "duration_hours": 2,
        "matrix_size": 512,
        "batch_count": 20,
        "routing_strategy": strategy,
    }


def _patch_online_paths(monkeypatch, tmp_path):
    dataset_path = tmp_path / "dataset.jsonl"
    report_path = tmp_path / "intent_eval_online.json"
    progress_path = tmp_path / "intent_eval_online.progress.jsonl"
    status_path = tmp_path / "intent_eval_online.status.json"
    monkeypatch.setattr(intent_online_eval, "DATASET_PATH", dataset_path)
    monkeypatch.setattr(intent_online_eval, "ONLINE_REPORT_PATH", report_path)
    monkeypatch.setattr(intent_online_eval, "ONLINE_PROGRESS_PATH", progress_path)
    monkeypatch.setattr(intent_online_eval, "ONLINE_STATUS_PATH", status_path)
    return dataset_path, report_path, progress_path, status_path


@pytest.mark.asyncio
async def test_online_eval_generates_report(tmp_path, monkeypatch):
    dataset_path, report_path, progress_path, status_path = _patch_online_paths(monkeypatch, tmp_path)
    dataset_path.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")

    async def fake_call_qwen(_messages, **_kwargs):
        return _raw()

    monkeypatch.setattr(intent_online_eval, "call_qwen", fake_call_qwen)

    report = await intent_online_eval.run_online_evaluation(concurrency=1, retries=0)

    assert report["engine"] == "llm_qwen_online"
    assert report["total"] == 1
    assert report["correct"] == 1
    assert report["accuracy"] == 1.0
    assert report["llm_raw_summary"]["correct"] == 1
    assert report_path.exists()
    assert progress_path.exists()
    assert status_path.exists()


@pytest.mark.asyncio
async def test_online_eval_uses_rule_fallback_for_wrong_raw_llm(tmp_path, monkeypatch):
    dataset_path, _report_path, _progress_path, _status_path = _patch_online_paths(monkeypatch, tmp_path)
    dataset_path.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")

    async def fake_call_qwen(_messages, **_kwargs):
        return _raw(strategy="resource_guarantee")

    monkeypatch.setattr(intent_online_eval, "call_qwen", fake_call_qwen)

    report = await intent_online_eval.run_online_evaluation(concurrency=1, retries=0)
    run = report["results"][0]["runs"][0]

    assert report["accuracy"] == 1.0
    assert report["llm_raw_summary"]["accuracy"] == 0.0
    assert run["llm_raw_match"] is False
    assert run["final_source"] == "rule_fallback"
    assert run["final_parser_name"] == "rule_based"


@pytest.mark.asyncio
async def test_online_eval_retries_failed_llm_call(tmp_path, monkeypatch):
    dataset_path, _report_path, _progress_path, _status_path = _patch_online_paths(monkeypatch, tmp_path)
    dataset_path.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")
    calls = {"count": 0}

    async def flaky_call_qwen(_messages, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary rate limit")
        return _raw()

    monkeypatch.setattr(intent_online_eval, "call_qwen", flaky_call_qwen)

    report = await intent_online_eval.run_online_evaluation(concurrency=1, retries=1, retry_delay_seconds=0)

    assert calls["count"] == 2
    assert report["correct"] == 1
    assert report["results"][0]["runs"][0]["attempts"] == 2


@pytest.mark.asyncio
async def test_online_eval_resume_skips_completed_samples(tmp_path, monkeypatch):
    dataset_path, _report_path, progress_path, _status_path = _patch_online_paths(monkeypatch, tmp_path)
    dataset_path.write_text(
        json.dumps(_sample(), ensure_ascii=False) + "\n" + json.dumps(_sample(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    completed = {
        "sample_id": "sample-0000",
        "case_type": "valid",
        "utterance": "done",
        "expected": _sample()["expected"],
        "match": True,
        "runs": [{"match": True, "llm_raw_match": True, "details": {}}],
    }
    progress_path.write_text(json.dumps(completed, ensure_ascii=False) + "\n", encoding="utf-8")
    calls = {"count": 0}

    async def fake_call_qwen(_messages, **_kwargs):
        calls["count"] += 1
        return _raw()

    monkeypatch.setattr(intent_online_eval, "call_qwen", fake_call_qwen)

    report = await intent_online_eval.run_online_evaluation(concurrency=1, retries=0, resume=True)

    assert calls["count"] == 1
    assert report["total"] == 2
    assert report["correct"] == 2


def test_read_online_report(tmp_path, monkeypatch):
    report_path = tmp_path / "intent_eval_online.json"
    report_path.write_text(json.dumps({"accuracy": 1.0}), encoding="utf-8")
    monkeypatch.setattr(intent_online_eval, "ONLINE_REPORT_PATH", report_path)

    assert intent_online_eval.read_online_report() == {"accuracy": 1.0}


def test_latest_status_includes_online_report(tmp_path, monkeypatch):
    report_path = tmp_path / "intent_eval_online.json"
    report_path.write_text(json.dumps({"evaluation_id": "online-1", "accuracy": 1.0}), encoding="utf-8")
    monkeypatch.setattr(intent_online_eval, "ONLINE_REPORT_PATH", report_path)

    status = intent_batch_eval.latest_status()

    assert status["online_report"] == {"evaluation_id": "online-1", "accuracy": 1.0}


@pytest.mark.asyncio
async def test_online_eval_api_rejects_invalid_concurrency(client, db_session, tmp_path, monkeypatch):
    dataset_path, _report_path, _progress_path, _status_path = _patch_online_paths(monkeypatch, tmp_path)
    dataset_path.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")
    headers, _admin = await _auth_headers(client, db_session, username="online-eval-admin", role=UserRole.ADMIN)

    response = await client.post(
        "/api/admin/intent-parser/evaluations/llm-online/run",
        json={"concurrency": 0},
        headers=headers,
    )

    assert response.status_code == 400
    assert "concurrency" in response.json()["detail"]


@pytest.mark.asyncio
async def test_online_eval_api_parses_false_resume_string(client, db_session, tmp_path, monkeypatch):
    dataset_path, _report_path, progress_path, _status_path = _patch_online_paths(monkeypatch, tmp_path)
    dataset_path.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")
    progress_path.write_text(
        json.dumps({"sample_id": "sample-0000", "match": True, "runs": [{"match": True}]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    headers, _admin = await _auth_headers(client, db_session, username="online-eval-resume-admin", role=UserRole.ADMIN)

    async def fake_run_online_evaluation(**_params):
        return {}

    monkeypatch.setattr(admin_api, "run_online_evaluation", fake_run_online_evaluation)

    response = await client.post(
        "/api/admin/intent-parser/evaluations/llm-online/run",
        json={"limit": 1, "resume": "false", "concurrency": 1, "retries": 0},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["resume"] is False
    assert response.json()["completed"] == 0


@pytest.mark.asyncio
async def test_online_eval_api_rejects_duplicate_running_job(client, db_session, tmp_path, monkeypatch):
    dataset_path, _report_path, _progress_path, status_path = _patch_online_paths(monkeypatch, tmp_path)
    dataset_path.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")
    status_path.write_text(json.dumps({"status": "running", "evaluation_id": "online-running"}), encoding="utf-8")
    headers, _admin = await _auth_headers(client, db_session, username="online-eval-duplicate-admin", role=UserRole.ADMIN)

    response = await client.post(
        "/api/admin/intent-parser/evaluations/llm-online/run",
        json={"limit": 1},
        headers=headers,
    )

    assert response.status_code == 409
    assert "正在运行" in response.json()["detail"]
