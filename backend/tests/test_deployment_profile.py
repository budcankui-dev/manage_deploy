import importlib


def test_current_profile_defaults_to_acceptance_management_addresses(monkeypatch):
    monkeypatch.delenv("NETWORK_PROFILE", raising=False)
    monkeypatch.delenv("PRIVATE_REGISTRY", raising=False)
    monkeypatch.delenv("MANAGER_API_BASE", raising=False)
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)

    module = importlib.import_module("services.deployment_profile")
    module = importlib.reload(module)

    profile = module.current_deployment_profile()

    assert profile.name == "acceptance"
    assert profile.registry == "172.16.0.254:5000"
    assert profile.manager_api_base == "http://172.16.0.254:8181"
    assert profile.minio_endpoint == "http://172.16.0.254:9000"
    assert module.image_ref("scientific-matmul") == "172.16.0.254:5000/scientific-matmul:dev"


def test_current_profile_alias_keeps_development_management_addresses(monkeypatch):
    monkeypatch.setenv("NETWORK_PROFILE", "current")
    monkeypatch.delenv("PRIVATE_REGISTRY", raising=False)
    monkeypatch.delenv("MANAGER_API_BASE", raising=False)
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)

    module = importlib.import_module("services.deployment_profile")
    module = importlib.reload(module)

    profile = module.current_deployment_profile()

    assert profile.name == "current"
    assert profile.registry == "10.112.244.94:5000"
    assert profile.manager_api_base == "http://10.112.244.94:8181"
    assert profile.minio_endpoint == "http://10.112.244.94:9000"


def test_acceptance_profile_defaults_to_management_network_addresses(monkeypatch):
    monkeypatch.setenv("NETWORK_PROFILE", "acceptance")
    monkeypatch.delenv("PRIVATE_REGISTRY", raising=False)
    monkeypatch.delenv("MANAGER_API_BASE", raising=False)
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)

    module = importlib.import_module("services.deployment_profile")
    module = importlib.reload(module)

    profile = module.current_deployment_profile()

    assert profile.name == "acceptance"
    assert profile.registry == "172.16.0.254:5000"
    assert profile.manager_api_base == "http://172.16.0.254:8181"
    assert profile.minio_endpoint == "http://172.16.0.254:9000"
    assert module.image_ref("low-latency-video", tag="dev") == "172.16.0.254:5000/low-latency-video:dev"


def test_explicit_profile_name_does_not_require_environment_switch(monkeypatch):
    monkeypatch.delenv("NETWORK_PROFILE", raising=False)
    monkeypatch.delenv("PRIVATE_REGISTRY", raising=False)
    monkeypatch.delenv("MANAGER_API_BASE", raising=False)
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)

    module = importlib.import_module("services.deployment_profile")
    module = importlib.reload(module)

    profile = module.deployment_profile("acceptance")

    assert profile.name == "acceptance"
    assert profile.registry == "172.16.0.254:5000"
    assert profile.manager_api_base == "http://172.16.0.254:8181"
    assert profile.minio_endpoint == "http://172.16.0.254:9000"


def test_explicit_environment_overrides_profile_defaults(monkeypatch):
    monkeypatch.setenv("NETWORK_PROFILE", "acceptance")
    monkeypatch.setenv("PRIVATE_REGISTRY", "registry.example:5000")
    monkeypatch.setenv("MANAGER_API_BASE", "http://manager.example:8181")
    monkeypatch.setenv("MINIO_ENDPOINT", "http://minio.example:9000")

    module = importlib.import_module("services.deployment_profile")
    module = importlib.reload(module)

    profile = module.current_deployment_profile()

    assert profile.registry == "registry.example:5000"
    assert profile.manager_api_base == "http://manager.example:8181"
    assert profile.minio_endpoint == "http://minio.example:9000"
    assert module.image_repo("node-agent") == "registry.example:5000/node-agent"
