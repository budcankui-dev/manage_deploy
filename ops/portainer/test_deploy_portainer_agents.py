import unittest
import importlib.util
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("deploy_portainer_agents.py")
SPEC = importlib.util.spec_from_file_location("deploy_portainer_agents", MODULE_PATH)
deploy = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["deploy_portainer_agents"] = deploy
SPEC.loader.exec_module(deploy)


class PortainerAgentDeployTests(unittest.TestCase):
    def test_inventory_nodes_selects_compute_and_terminal_by_default(self):
        inventory = {
            "manager": {"hostname": "admin", "acceptance_management_ip": "172.16.0.254"},
            "compute_nodes": [
                {
                    "hostname": "compute-1",
                    "acceptance_management_ip": "172.16.0.101",
                    "agent_port": 18001,
                    "docker_root_dir": "/data/hdd1/docker",
                }
            ],
            "terminal_nodes": [
                {"hostname": "h1", "management_ip": "10.112.126.124", "acceptance_management_ip": "172.16.0.151"}
            ],
        }

        nodes = deploy.inventory_nodes(inventory)

        self.assertEqual([node.hostname for node in nodes], ["compute-1", "h1"])
        self.assertEqual(nodes[0].agent_port, 18001)
        self.assertEqual(nodes[0].docker_root_dir, "/data/hdd1/docker")
        self.assertEqual(nodes[1].agent_port, deploy.DEFAULT_AGENT_PORT)

    def test_volumes_path_uses_custom_docker_root(self):
        self.assertEqual(deploy.volumes_path_for_docker_root("/data/hdd1/docker"), "/data/hdd1/docker/volumes")
        self.assertEqual(deploy.volumes_path_for_docker_root(None), "/var/lib/docker/volumes")

    def test_start_payload_mounts_docker_socket_and_volumes(self):
        payload = deploy.start_payload(
            image="registry.local/portainer-agent:latest",
            host_port=9001,
            docker_root_dir="/disk/sdb/docker",
            pull_policy="always",
        )

        self.assertEqual(payload["image"], "registry.local/portainer-agent:latest")
        self.assertEqual(payload["ports"], {"9001": "9001"})
        self.assertEqual(payload["restart_policy"], "always")
        self.assertIn(
            {
                "target": "/var/lib/docker/volumes",
                "type": "bind",
                "source": "/disk/sdb/docker/volumes",
                "auto_create": False,
            },
            payload["volume_mounts"],
        )

    def test_force_recreate_ignores_missing_old_container(self):
        node = deploy.Node(
            hostname="h1",
            management_ip="172.16.0.151",
            agent_port=18001,
            docker_root_dir=None,
        )
        calls = []

        def fake_request(url, *, method="GET", payload=None, timeout=10):
            calls.append((method, url, payload))
            if method == "DELETE":
                raise urllib.error.HTTPError(url, 404, "not found", None, None)
            return {"container_id": "new-container"}

        with patch.object(deploy, "request_json", side_effect=fake_request):
            ok, message = deploy.deploy_node(
                node,
                image="registry.local/portainer-agent:latest",
                host_port=9001,
                task_id="ops-portainer-agent",
                node_id="portainer_agent",
                pull_policy="always",
                timeout=5,
                dry_run=False,
                force_recreate=True,
            )

        self.assertTrue(ok)
        self.assertEqual(message, "container_id=new-container")
        self.assertEqual(calls[0][0], "DELETE")
        self.assertEqual(calls[1][0], "POST")


if __name__ == "__main__":
    unittest.main()
