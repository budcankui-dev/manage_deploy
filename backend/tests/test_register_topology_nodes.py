import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "register_topology_nodes.py"
SPEC = importlib.util.spec_from_file_location("register_topology_nodes", SCRIPT_PATH)
register_topology_nodes = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(register_topology_nodes)


def test_node_payload_uses_acceptance_addresses_and_registry_note():
    item = {
        "hostname": "h1",
        "topology_node_id": "h18001001",
        "management_ip": "10.112.126.124",
        "business_ip": "10.112.126.124",
        "acceptance_management_ip": "172.16.0.151",
        "acceptance_business_ip": "172.16.0.151",
        "acceptance_business_ipv6": "3012:3::250:56ff:fe8b:7127",
        "node_kind": "terminal",
        "agent_port": 8001,
    }

    payload = register_topology_nodes._node_payload(
        item,
        registry_host="172.16.0.254:5000",
        network_profile="acceptance",
    )

    assert payload["management_ip"] == "172.16.0.151"
    assert payload["agent_address"] == "http://172.16.0.151:8001"
    assert payload["business_ip"] == "172.16.0.151"
    assert payload["business_ipv6"] == "3012:3::250:56ff:fe8b:7127"
    assert "172.16.0.254:5000" in payload["resource_note"]


def test_dry_run_default_profile_uses_acceptance_registry_without_env_override(tmp_path):
    inventory = {
        "terminal_nodes": [
            {
                "hostname": "h1",
                "management_ip": "10.112.126.124",
                "acceptance_management_ip": "172.16.0.151",
                "business_ip": "10.112.126.124",
                "acceptance_business_ip": "172.16.0.151",
                "acceptance_business_ipv6": "3012:3::250:56ff:fe8b:7127",
                "node_kind": "terminal",
                "agent_port": 8001,
            }
        ]
    }
    inventory_path = tmp_path / "nodes.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    env = os.environ.copy()
    env.pop("NETWORK_PROFILE", None)
    env.pop("PRIVATE_REGISTRY", None)
    env.pop("MANAGER_API_BASE", None)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--inventory",
            str(inventory_path),
            "--dry-run",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)[0]
    assert payload["management_ip"] == "172.16.0.151"
    assert payload["agent_address"] == "http://172.16.0.151:8001"
    assert "172.16.0.254:5000" in payload["resource_note"]


def test_dry_run_acceptance_alias_env_uses_acceptance_addresses(tmp_path):
    inventory = {
        "terminal_nodes": [
            {
                "hostname": "h1",
                "management_ip": "10.112.126.124",
                "acceptance_management_ip": "172.16.0.151",
                "business_ip": "10.112.126.124",
                "acceptance_business_ip": "172.16.0.151",
                "acceptance_business_ipv6": "3012:3::250:56ff:fe8b:7127",
                "node_kind": "terminal",
                "agent_port": 8001,
            }
        ]
    }
    inventory_path = tmp_path / "nodes.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    env = os.environ.copy()
    env["NETWORK_PROFILE"] = "accept"
    env.pop("PRIVATE_REGISTRY", None)
    env.pop("MANAGER_API_BASE", None)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--inventory",
            str(inventory_path),
            "--dry-run",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)[0]
    assert payload["management_ip"] == "172.16.0.151"
    assert payload["agent_address"] == "http://172.16.0.151:8001"
    assert payload["business_ip"] == "172.16.0.151"
    assert payload["business_ipv6"] == "3012:3::250:56ff:fe8b:7127"
