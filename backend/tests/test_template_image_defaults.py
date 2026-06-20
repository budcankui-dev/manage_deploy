import importlib


def test_matmul_template_defaults_to_private_registry(monkeypatch):
    monkeypatch.delenv("WORKER_IMAGE", raising=False)
    monkeypatch.delenv("MATMUL_COMPUTE_IMAGE", raising=False)
    monkeypatch.delenv("MATMUL_ENDPOINT_IMAGE", raising=False)
    monkeypatch.delenv("WORKER_TAG", raising=False)

    module = importlib.import_module("scripts.rebuild_matmul_template")
    module = importlib.reload(module)

    assert module.MATMUL_COMPUTE_IMAGE == "10.112.244.94:5000/scientific-matmul:dev"
    assert module.MATMUL_ENDPOINT_IMAGE == "10.112.244.94:5000/scientific-matmul-endpoint:dev"


def test_video_template_defaults_to_private_registry(monkeypatch):
    monkeypatch.delenv("WORKER_IMAGE", raising=False)
    monkeypatch.delenv("VIDEO_COMPUTE_IMAGE", raising=False)
    monkeypatch.delenv("VIDEO_ENDPOINT_IMAGE", raising=False)
    monkeypatch.delenv("WORKER_TAG", raising=False)

    module = importlib.import_module("scripts.rebuild_video_template")
    module = importlib.reload(module)

    assert module.VIDEO_COMPUTE_IMAGE == "10.112.244.94:5000/low-latency-video:dev"
    assert module.VIDEO_ENDPOINT_IMAGE == "10.112.244.94:5000/low-latency-video-endpoint:dev"
