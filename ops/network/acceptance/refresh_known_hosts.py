#!/usr/bin/env python3
"""Generate a project-local known_hosts file for acceptance SSH probes."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INVENTORY = ROOT / "ops" / "inventory" / "topology_nodes.json"
DEFAULT_OUTPUT = ROOT / "ops" / "secrets" / "acceptance_known_hosts"

DEFAULT_SSH_PORTS = {
    "admin": 22,
    "compute-1": 2345,
    "compute-2": 2345,
    "compute-3": 22,
}


@dataclass(frozen=True)
class Host:
    name: str
    address: str
    fallback_address: str | None
    port: int


def _load_inventory(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _address_for_profile(item: dict, profile: str) -> str | None:
    if profile == "acceptance":
        return item.get("acceptance_management_ip") or item.get("management_ip")
    return item.get("management_ip") or item.get("acceptance_management_ip")


def _fallback_address_for_profile(item: dict, profile: str) -> str | None:
    if profile == "acceptance":
        return item.get("management_ip")
    return item.get("acceptance_management_ip")


def _host_port(item: dict) -> int:
    hostname = item.get("hostname")
    if item.get("ssh_port"):
        return int(item["ssh_port"])
    return DEFAULT_SSH_PORTS.get(str(hostname), 22)


def _hosts(inventory: dict, profile: str) -> list[Host]:
    items = []
    manager = inventory.get("manager")
    if manager:
        items.append(manager)
    items.extend(inventory.get("compute_nodes") or [])
    items.extend(inventory.get("terminal_nodes") or [])

    hosts: list[Host] = []
    for item in items:
        hostname = item.get("hostname")
        address = _address_for_profile(item, profile)
        if not hostname or not address:
            continue
        fallback_address = _fallback_address_for_profile(item, profile)
        hosts.append(
            Host(
                name=str(hostname),
                address=str(address),
                fallback_address=str(fallback_address) if fallback_address else None,
                port=_host_port(item),
            )
        )
    return hosts


def _normalize_keyscan_output(raw: str, *, scanned_address: str, target_address: str, port: int) -> str:
    lines: list[str] = []
    scanned_token = f"[{scanned_address}]:{port}" if port != 22 else scanned_address
    target_token = f"[{target_address}]:{port}" if port != 22 else target_address
    for line in raw.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith(scanned_token + " "):
            lines.append(target_token + line[len(scanned_token):])
        else:
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                lines.append(f"{target_token} {parts[1]}")
            else:
                lines.append(line)
    return "\n".join(lines)


def _scan_address(address: str, *, port: int, timeout: int) -> tuple[str, str | None]:
    command = ["ssh-keyscan", "-T", str(timeout), "-p", str(port), address]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = completed.stdout.strip()
    if completed.returncode != 0 and not output:
        message = completed.stderr.strip() or f"ssh-keyscan exited {completed.returncode}"
        return "", message
    if not output:
        return "", "ssh-keyscan returned no keys"
    return output, None


def _scan_host(host: Host, timeout: int) -> tuple[str, str | None, str]:
    output, error = _scan_address(host.address, port=host.port, timeout=timeout)
    if output:
        return _normalize_keyscan_output(
            output,
            scanned_address=host.address,
            target_address=host.address,
            port=host.port,
        ), None, host.address

    first_error = error
    if host.fallback_address and host.fallback_address != host.address:
        output, error = _scan_address(host.fallback_address, port=host.port, timeout=timeout)
        if output:
            return _normalize_keyscan_output(
                output,
                scanned_address=host.fallback_address,
                target_address=host.address,
                port=host.port,
            ), None, host.fallback_address

    return "", first_error or error or "ssh-keyscan returned no keys", host.address


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh project-local SSH known_hosts for acceptance nodes")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--profile", choices=["acceptance", "current"], default="acceptance")
    parser.add_argument("--timeout", type=int, default=5)
    args = parser.parse_args()

    inventory = _load_inventory(args.inventory)
    hosts = _hosts(inventory, args.profile)
    if not hosts:
        raise SystemExit("no hosts found in inventory")

    chunks = [
        "# Generated by ops/network/acceptance/refresh_known_hosts.py",
        f"# profile={args.profile}",
        "# Do not commit this file; ops/secrets/ is ignored.",
    ]
    failures: list[str] = []

    for host in hosts:
        keys, error, scanned_address = _scan_host(host, args.timeout)
        if error:
            failures.append(f"{host.name} {host.address}:{host.port} {error}")
            continue
        source_suffix = "" if scanned_address == host.address else f" scanned_via={scanned_address}"
        chunks.append(f"# {host.name} {host.address}:{host.port}{source_suffix}")
        chunks.extend(keys.splitlines())

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(chunks) + "\n", encoding="utf-8")
    args.output.chmod(0o600)

    print(f"wrote {args.output}")
    print(f"hosts_ok={len(hosts) - len(failures)} hosts_failed={len(failures)} total={len(hosts)}")
    for item in failures:
        print(f"FAIL {item}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
