#!/usr/bin/env python3
"""Register acceptance topology nodes as Portainer Agent environments."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import ssl
import urllib.request
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = ROOT / "ops" / "inventory" / "topology_nodes.json"
DEFAULT_URL = "https://172.16.0.254:9443"
DEFAULT_USERNAME = "admin"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _endpoint_nodes(inventory: dict[str, Any]) -> list[dict[str, str]]:
    nodes: list[dict[str, str]] = []
    for item in list(inventory.get("compute_nodes") or []) + list(inventory.get("terminal_nodes") or []):
        name = str(item.get("hostname") or "").strip()
        ip = str(item.get("acceptance_management_ip") or item.get("management_ip") or "").strip()
        if name and ip:
            nodes.append({"name": name, "ip": ip, "url": f"tcp://{ip}:9001"})
    return nodes


class PortainerClient:
    def __init__(self, base_url: str, token: str, *, verify_tls: bool):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.context = None if verify_tls else ssl._create_unverified_context()

    @classmethod
    def login(cls, base_url: str, username: str, password: str, *, verify_tls: bool) -> "PortainerClient":
        context = None if verify_tls else ssl._create_unverified_context()
        body = json.dumps({"username": username, "password": password}).encode("utf-8")
        request = urllib.request.Request(
            base_url.rstrip("/") + "/api/auth",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=20, context=context) as response:
            token = json.loads(response.read().decode("utf-8"))["jwt"]
        return cls(base_url, token, verify_tls=verify_tls)

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", **(headers or {})},
        )
        with urllib.request.urlopen(request, timeout=30, context=self.context) as response:
            text = response.read().decode("utf-8", errors="replace")
        return json.loads(text) if text else None

    def endpoints(self) -> list[dict[str, Any]]:
        return self._request("/api/endpoints")

    def create_agent_endpoint(self, *, name: str, url: str, public_url: str) -> dict[str, Any]:
        fields = {
            "Name": name,
            "EndpointCreationType": "2",
            "URL": url,
            "PublicURL": public_url,
            "GroupID": "1",
            "TLS": "true",
            "TLSSkipVerify": "true",
            "TLSSkipClientVerify": "true",
        }
        boundary = "----codex" + uuid.uuid4().hex
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return self._request(
            "/api/endpoints",
            method="POST",
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Register Portainer Agent environments for acceptance nodes")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--url", default=os.environ.get("PORTAINER_URL", DEFAULT_URL))
    parser.add_argument("--username", default=os.environ.get("PORTAINER_USERNAME", DEFAULT_USERNAME))
    parser.add_argument("--password", default=os.environ.get("PORTAINER_PASSWORD"))
    parser.add_argument("--verify-tls", action="store_true", help="Verify Portainer HTTPS certificate")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Portainer password: ")
    client = PortainerClient.login(args.url, args.username, password, verify_tls=args.verify_tls)
    existing = {item.get("Name"): item for item in client.endpoints()}
    nodes = _endpoint_nodes(_read_json(args.inventory))

    created = 0
    skipped = 0
    for node in nodes:
        found = existing.get(node["name"])
        if found:
            skipped += 1
            print(f"SKIP {node['name']} id={found.get('Id')} url={found.get('URL')} status={found.get('Status')}")
            continue
        data = client.create_agent_endpoint(name=node["name"], url=node["url"], public_url=node["ip"])
        created += 1
        print(f"CREATED {node['name']} id={data.get('Id')} url={data.get('URL')} status={data.get('Status')}")

    print(f"created={created} skipped={skipped} total={len(nodes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
