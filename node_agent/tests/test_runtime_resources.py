import pytest

from runtime_resources import parse_gpu_spec, build_resource_kwargs, resolve_mounts


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
