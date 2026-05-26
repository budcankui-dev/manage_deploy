import pytest

from config import settings
from schemas import ContainerStartRequest
from services.platform_runtime import (
    apply_platform_runtime,
    merge_platform_env,
    scratch_host_path,
)


@pytest.fixture(autouse=True)
def _set_manager_url(monkeypatch):
    monkeypatch.setattr(settings, "manager_public_url", "http://test-manager:8000")


def test_merge_platform_env_injects_ids():
    env = merge_platform_env("ins-1", "node-1", {"FOO": "bar"})
    assert env["FOO"] == "bar"
    assert env["TASK_INSTANCE_ID"] == "ins-1"
    assert env["TASK_NODE_INSTANCE_ID"] == "node-1"
    assert env["MANAGER_API_BASE"].startswith("http")


def test_apply_scratch_bind_mount():
    request = ContainerStartRequest(image="test:latest")
    env = apply_platform_runtime(
        request,
        "ins-abc",
        "node-xyz",
        {},
        enable_scratch=True,
    )
    assert env["TASK_INSTANCE_ID"] == "ins-abc"
    assert request.volumes["/scratch"] == scratch_host_path("ins-abc")
