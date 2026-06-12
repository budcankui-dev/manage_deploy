import pytest

from runtime_resources import parse_gpu_spec, build_resource_kwargs, resolve_mounts, collect_host_resources


class FakeVolumes:
    def __init__(self):
        self.created = []

    def get(self, name):
        raise KeyError(name)

    def create(self, name):
        self.created.append(name)


class FakeClient:
    def __init__(self):
        self.volumes = FakeVolumes()


def test_parse_gpu_all():
    reqs = parse_gpu_spec("all")
    assert reqs is not None
    assert reqs[0]["Count"] == -1


def test_parse_gpu_single():
    reqs = parse_gpu_spec("0")
    assert reqs[0]["DeviceIDs"] == ["0"]


def test_parse_gpu_multiple():
    reqs = parse_gpu_spec("0,1, 2")
    assert reqs[0]["DeviceIDs"] == ["0", "1", "2"]


def test_build_resource_kwargs_reservation():
    kw = build_resource_kwargs(cpu_reservation=1.5, memory_reservation="512m")
    assert kw["cpu_shares"] == 1536
    assert kw["mem_reservation"] == 512 * 1024 * 1024


def test_resolve_managed_mount(tmp_path):
    mounts = resolve_mounts(
        task_id="task-1",
        node_id="node-1",
        volume_mounts=[{"target": "/data", "type": "managed", "source": "input", "auto_create": True}],
        data_root=str(tmp_path),
    )
    assert len(mounts) == 1
    assert mounts[0]["Target"] == "/data"
    assert (tmp_path / "task-1" / "node-1" / "input").exists()


def test_resolve_volume_auto_create():
    client = FakeClient()
    mounts = resolve_mounts(
        task_id="t",
        node_id="n",
        volume_mounts=[{"target": "/out", "type": "volume", "source": "my-vol", "auto_create": True}],
        data_root="/tmp",
        docker_client=client,
    )
    assert client.volumes.created == ["my-vol"]
    assert mounts[0]["Type"] == "volume"


def test_collect_host_resources_parses_nvidia_smi(monkeypatch, tmp_path):
    cpuinfo = tmp_path / "cpuinfo"
    meminfo = tmp_path / "meminfo"
    cpuinfo.write_text("model name\t: Test Xeon\n")
    meminfo.write_text("MemTotal:       65536000 kB\n")

    class FakePath:
        def __init__(self, raw):
            self.raw = raw

        def exists(self):
            return True

        def read_text(self, errors=None):
            return cpuinfo.read_text() if self.raw == "/proc/cpuinfo" else meminfo.read_text()

    def fake_path(raw):
        return FakePath(str(raw))

    def fake_run(args, timeout=5):
        if args[:1] == ["nvidia-smi"] and "--query-gpu=name,memory.total,driver_version" in args:
            return 0, "NVIDIA TITAN Xp, 12288, 535.171.04", ""
        if args == ["nvidia-smi"]:
            return 0, "| NVIDIA-SMI 535.171.04    Driver Version: 535.171.04    CUDA Version: 12.2 |", ""
        return 127, "", "missing"

    monkeypatch.setattr("runtime_resources.Path", fake_path)
    monkeypatch.setattr("runtime_resources._run_command", fake_run)
    monkeypatch.setattr("runtime_resources.os.cpu_count", lambda: 16)

    facts = collect_host_resources()

    assert facts["cpu_cores"] == 16
    assert facts["cpu_model"] == "Test Xeon"
    assert facts["memory_mb"] == 64000
    assert facts["gpu_count"] == 1
    assert facts["gpu_model"] == "NVIDIA TITAN Xp"
    assert facts["gpu_memory_mb"] == 12288
    assert facts["driver_version"] == "535.171.04"
    assert facts["cuda_version"] == "12.2"
