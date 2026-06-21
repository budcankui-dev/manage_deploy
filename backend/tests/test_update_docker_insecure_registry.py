import json
import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "update_docker_insecure_registry.py"
SPEC = importlib.util.spec_from_file_location("update_docker_insecure_registry", SCRIPT_PATH)
update_docker_insecure_registry = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(update_docker_insecure_registry)


def test_update_daemon_config_appends_registry_and_preserves_existing_fields(tmp_path):
    path = tmp_path / "daemon.json"
    path.write_text(
        json.dumps(
            {
                "data-root": "/mnt/data/docker",
                "runtimes": {"nvidia": {"path": "nvidia-container-runtime"}},
                "insecure-registries": ["10.112.244.94:5000"],
            }
        ),
        encoding="utf-8",
    )

    changed = update_docker_insecure_registry.update_daemon_config(
        path,
        ["172.16.0.254:5000"],
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert changed is True
    assert data["data-root"] == "/mnt/data/docker"
    assert data["runtimes"]["nvidia"]["path"] == "nvidia-container-runtime"
    assert data["insecure-registries"] == [
        "10.112.244.94:5000",
        "172.16.0.254:5000",
    ]
    assert list(tmp_path.glob("daemon.json.bak.*"))


def test_update_daemon_config_is_idempotent(tmp_path):
    path = tmp_path / "daemon.json"
    path.write_text(
        json.dumps({"insecure-registries": ["172.16.0.254:5000"]}),
        encoding="utf-8",
    )

    changed = update_docker_insecure_registry.update_daemon_config(
        path,
        ["172.16.0.254:5000"],
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert changed is False
    assert data["insecure-registries"] == ["172.16.0.254:5000"]
    assert not list(tmp_path.glob("daemon.json.bak.*"))


def test_update_daemon_config_rejects_invalid_json_without_overwriting(tmp_path):
    path = tmp_path / "daemon.json"
    path.write_text("{ invalid json", encoding="utf-8")

    try:
        update_docker_insecure_registry.update_daemon_config(
            path,
            ["172.16.0.254:5000"],
        )
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("invalid daemon.json must fail before writing")

    assert path.read_text(encoding="utf-8") == "{ invalid json"
    assert not list(tmp_path.glob("daemon.json.bak.*"))
