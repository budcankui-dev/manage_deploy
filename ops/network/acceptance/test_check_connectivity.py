import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("check_connectivity.py")
SPEC = importlib.util.spec_from_file_location("check_connectivity", MODULE_PATH)
check_connectivity = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules["check_connectivity"] = check_connectivity
SPEC.loader.exec_module(check_connectivity)


class ConnectivitySourceTests(unittest.TestCase):
    def test_plane_scope_uses_all_management_sources_but_only_data_capable_sources(self):
        inventory = {
            "manager": {
                "hostname": "admin",
                "management_ip": "10.112.244.94",
                "acceptance_management_ip": "172.16.0.254",
                "ssh_user": "bupt",
                "ssh_port": 22,
            },
            "compute_nodes": [
                {
                    "hostname": "compute-1",
                    "management_ip": "10.112.38.25",
                    "acceptance_management_ip": "172.16.0.101",
                    "acceptance_business_ipv6": "3012:3::1",
                    "ssh_user": "chengyubin",
                    "ssh_port": 2345,
                }
            ],
            "terminal_nodes": [
                {
                    "hostname": "h1",
                    "management_ip": "10.112.126.124",
                    "acceptance_management_ip": "172.16.0.151",
                    "acceptance_business_ipv6": "3012:3::250:56ff:fe8b:7127",
                    "ssh_user": "switchpc1",
                    "ssh_port": 22,
                }
            ],
        }

        management_sources = check_connectivity._sources_for_scope(
            inventory,
            plane="management",
            scope="plane",
            profile="acceptance",
            connect_timeout=3,
        )
        data_sources = check_connectivity._sources_for_scope(
            inventory,
            plane="data",
            scope="plane",
            profile="acceptance",
            connect_timeout=3,
        )

        self.assertEqual(set(management_sources), {"admin", "compute-1", "h1"})
        self.assertIn("172.16.0.254", management_sources["admin"])
        self.assertIn("-p 2345", management_sources["compute-1"])
        self.assertEqual(set(data_sources), {"compute-1", "h1"})
        self.assertNotIn("admin", data_sources)

    def test_source_probe_error_is_counted_without_stopping_matrix(self):
        output = io.StringIO()
        with redirect_stdout(output):
            target_count = check_connectivity._print_matrix_source_error(
                "h1",
                check_connectivity.RemoteProbeError(255, "ssh: connect failed\n"),
                16,
            )

        self.assertEqual(target_count, 16)
        self.assertIn("SOURCE_FAIL", output.getvalue())


if __name__ == "__main__":
    unittest.main()
