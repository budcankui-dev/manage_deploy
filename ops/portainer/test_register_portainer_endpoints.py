import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("register_portainer_endpoints.py")
SPEC = importlib.util.spec_from_file_location("register_portainer_endpoints", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["register_portainer_endpoints"] = module
SPEC.loader.exec_module(module)


class RegisterPortainerEndpointsTests(unittest.TestCase):
    def test_endpoint_nodes_uses_compute_and_terminal_management_ips(self):
        inventory = {
            "manager": {"hostname": "admin", "acceptance_management_ip": "172.16.0.254"},
            "compute_nodes": [{"hostname": "compute-1", "acceptance_management_ip": "172.16.0.101"}],
            "terminal_nodes": [{"hostname": "h1", "acceptance_management_ip": "172.16.0.151"}],
        }

        self.assertEqual(
            module._endpoint_nodes(inventory),
            [
                {"name": "compute-1", "ip": "172.16.0.101", "url": "tcp://172.16.0.101:9001"},
                {"name": "h1", "ip": "172.16.0.151", "url": "tcp://172.16.0.151:9001"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
