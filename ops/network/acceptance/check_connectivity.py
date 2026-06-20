#!/usr/bin/env python3
"""Check acceptance management and data-plane connectivity.

This script is intentionally standalone so it can run from a developer laptop,
the manager node, or any host with Python 3 and ping installed.  It reads the
acceptance topology inventory and can either ping from the local machine or run
the same ping checks from a remote SSH source node.
"""

from __future__ import annotations

import argparse
import json
import platform
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INVENTORY = ROOT / "ops" / "inventory" / "topology_nodes.json"

DEFAULT_SSH_SOURCES = {
    "compute-1": "-p 2345 chengyubin@10.112.38.25",
    "compute-2": "-p 2345 chengyubin@10.112.17.51",
    "compute-3": "-p 22 compute@10.112.59.209",
}

DEFAULT_SSH_LOGIN = {
    "admin": ("bupt", 22),
    "compute-1": ("chengyubin", 2345),
    "compute-2": ("chengyubin", 2345),
    "compute-3": ("compute", 22),
}


@dataclass(frozen=True)
class Target:
    name: str
    role: str
    address: str
    iface: str | None = None


class RemoteProbeError(RuntimeError):
    def __init__(self, returncode: int, stderr: str):
        super().__init__(stderr.strip() or f"remote probe failed with exit code {returncode}")
        self.returncode = returncode
        self.stderr = stderr


def _load_inventory(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _management_targets(inventory: dict) -> list[Target]:
    targets: list[Target] = []
    manager = inventory.get("manager") or {}
    if manager.get("acceptance_management_ip"):
        targets.append(
            Target(
                name=manager["hostname"],
                role=manager.get("node_kind") or "admin",
                address=manager["acceptance_management_ip"],
                iface=manager.get("management_iface"),
            )
        )
    for group_name in ("compute_nodes", "terminal_nodes"):
        for item in inventory.get(group_name) or []:
            if item.get("acceptance_management_ip"):
                targets.append(
                    Target(
                        name=item["hostname"],
                        role=item.get("node_kind") or group_name.removesuffix("_nodes"),
                        address=item["acceptance_management_ip"],
                        iface=item.get("management_iface"),
                    )
                )
    return targets


def _data_targets(inventory: dict) -> list[Target]:
    targets: list[Target] = []
    for group_name in ("compute_nodes", "terminal_nodes"):
        for item in inventory.get(group_name) or []:
            if item.get("acceptance_business_ipv6"):
                targets.append(
                    Target(
                        name=item["hostname"],
                        role=item.get("node_kind") or group_name.removesuffix("_nodes"),
                        address=item["acceptance_business_ipv6"],
                        iface=item.get("business_iface"),
                    )
                )
    return targets


def _profiled_management_ip(item: dict[str, Any], profile: str) -> str | None:
    if profile == "acceptance" and item.get("acceptance_management_ip"):
        return item["acceptance_management_ip"]
    return item.get("management_ip") or item.get("acceptance_management_ip")


def _source_items_for_plane(inventory: dict, plane: str, scope: str) -> list[dict[str, Any]]:
    if scope == "default":
        return []

    manager = inventory.get("manager") or {}
    compute_nodes = list(inventory.get("compute_nodes") or [])
    terminal_nodes = list(inventory.get("terminal_nodes") or [])

    if scope == "compute":
        return compute_nodes
    if scope != "plane":
        raise ValueError(f"unsupported source scope: {scope}")
    if plane == "management":
        return [manager, *compute_nodes, *terminal_nodes] if manager else [*compute_nodes, *terminal_nodes]
    if plane == "data":
        return [
            item
            for item in [*compute_nodes, *terminal_nodes]
            if item.get("acceptance_business_ipv6") or item.get("business_ipv6")
        ]
    raise ValueError(f"unsupported plane for sources: {plane}")


def _source_ssh_args(item: dict[str, Any], *, profile: str, connect_timeout: int) -> str | None:
    hostname = item.get("hostname")
    if not hostname:
        return None
    address = _profiled_management_ip(item, profile)
    if not address:
        return None
    default_user, default_port = DEFAULT_SSH_LOGIN.get(hostname, ("switchpc1", 22))
    user = item.get("ssh_user") or default_user
    port = int(item.get("ssh_port") or default_port)
    return (
        f"-o BatchMode=yes -o ConnectTimeout={connect_timeout} "
        f"-p {port} {user}@{address}"
    )


def _sources_for_scope(
    inventory: dict,
    *,
    plane: str,
    scope: str,
    profile: str,
    connect_timeout: int,
) -> dict[str, str]:
    if scope == "default":
        return dict(DEFAULT_SSH_SOURCES)

    sources: dict[str, str] = {}
    for item in _source_items_for_plane(inventory, plane, scope):
        hostname = item.get("hostname")
        ssh_args = _source_ssh_args(item, profile=profile, connect_timeout=connect_timeout)
        if hostname and ssh_args:
            sources[hostname] = ssh_args
    return sources


def _ping_command(address: str, *, timeout: int) -> list[str]:
    is_ipv6 = ":" in address
    system = platform.system().lower()
    if is_ipv6:
        command = ["ping6", "-c", "1", address]
        if system != "darwin":
            command = ["ping", "-6", "-c", "1", "-W", str(timeout), address]
        return command
    if system == "darwin":
        return ["ping", "-c", "1", "-W", str(timeout * 1000), address]
    return ["ping", "-c", "1", "-W", str(timeout), address]


def _remote_probe_script(targets: Iterable[Target], *, timeout: int) -> str:
    lines = [
        "set -u",
        "if command -v ping6 >/dev/null 2>&1; then PING6=ping6; else PING6='ping -6'; fi",
    ]
    for target in targets:
        quoted_addr = shlex.quote(target.address)
        quoted_name = shlex.quote(target.name)
        if ":" in target.address:
            lines.append(
                "if $PING6 -c 1 -W {timeout} {addr} >/dev/null 2>&1; "
                "then echo OK {name} {addr}; else echo FAIL {name} {addr}; fi".format(
                    timeout=timeout,
                    addr=quoted_addr,
                    name=quoted_name,
                )
            )
        else:
            lines.append(
                "if ping -c 1 -W {timeout} {addr} >/dev/null 2>&1; "
                "then echo OK {name} {addr}; else echo FAIL {name} {addr}; fi".format(
                    timeout=timeout,
                    addr=quoted_addr,
                    name=quoted_name,
                )
            )
    return "\n".join(lines)


def _targets_for_plane(inventory: dict, plane: str) -> list[Target]:
    if plane == "management":
        return _management_targets(inventory)
    if plane == "data":
        return _data_targets(inventory)
    raise ValueError(f"unsupported plane for targets: {plane}")


def _run_local(targets: list[Target], *, timeout: int) -> list[tuple[Target, bool]]:
    results: list[tuple[Target, bool]] = []
    for target in targets:
        command = _ping_command(target.address, timeout=timeout)
        completed = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        results.append((target, completed.returncode == 0))
    return results


def _run_remote(targets: list[Target], *, ssh: str, timeout: int) -> list[tuple[Target, bool]]:
    by_name = {target.name: target for target in targets}
    command = ["ssh", *shlex.split(ssh), _remote_probe_script(targets, timeout=timeout)]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        raise RemoteProbeError(completed.returncode, completed.stderr)

    results: list[tuple[Target, bool]] = []
    seen: set[str] = set()
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[0] not in {"OK", "FAIL"}:
            continue
        name = parts[1]
        target = by_name.get(name)
        if not target:
            continue
        seen.add(name)
        results.append((target, parts[0] == "OK"))

    for target in targets:
        if target.name not in seen:
            results.append((target, False))
    return results


def _print_results(title: str, results: list[tuple[Target, bool]]) -> int:
    ok = 0
    fail = 0
    print(f"=== {title} ===")
    for target, passed in results:
        status = "OK" if passed else "FAIL"
        if passed:
            ok += 1
        else:
            fail += 1
        iface = f" iface={target.iface}" if target.iface else ""
        print(f"{status:4} {target.name:10} {target.role:9} {target.address}{iface}")
    print(f"summary ok={ok} fail={fail} total={ok + fail}")
    return fail


def _print_matrix_row(source: str, results: list[tuple[Target, bool]]) -> int:
    ok = sum(1 for _, passed in results if passed)
    fail = len(results) - ok
    failed_names = ", ".join(target.name for target, passed in results if not passed)
    suffix = f" failed=[{failed_names}]" if failed_names else ""
    print(f"{source:10} ok={ok:2} fail={fail:2} total={len(results):2}{suffix}")
    return fail


def _print_matrix_source_error(source: str, exc: RemoteProbeError, target_count: int) -> int:
    message = str(exc).splitlines()[0] if str(exc) else f"ssh exit={exc.returncode}"
    print(f"{source:10} SOURCE_FAIL fail={target_count:2} total={target_count:2} reason={message}")
    return target_count


def _selected_sources(source_args: list[str] | None) -> dict[str, str]:
    if not source_args:
        return dict(DEFAULT_SSH_SOURCES)
    sources: dict[str, str] = {}
    for item in source_args:
        if "=" not in item:
            raise SystemExit("--source must be NAME=SSH_ARGS, for example compute-1='-p 2345 user@host'")
        name, ssh = item.split("=", 1)
        name = name.strip()
        ssh = ssh.strip()
        if not name or not ssh:
            raise SystemExit("--source must include both name and SSH args")
        sources[name] = ssh
    return sources


def _run_matrix(
    inventory: dict,
    *,
    plane: str,
    source_args: list[str] | None,
    source_scope: str,
    source_profile: str,
    timeout: int,
    ssh_connect_timeout: int,
    list_sources: bool = False,
) -> int:
    failures = 0
    planes = ["management", "data"] if plane == "both" else [plane]
    for current_plane in planes:
        targets = _targets_for_plane(inventory, current_plane)
        sources = (
            _selected_sources(source_args)
            if source_args
            else _sources_for_scope(
                inventory,
                plane=current_plane,
                scope=source_scope,
                profile=source_profile,
                connect_timeout=ssh_connect_timeout,
            )
        )
        if not sources:
            raise SystemExit(f"no SSH sources selected for {current_plane} plane")
        print(f"=== {current_plane} matrix ===")
        if list_sources:
            for source_name, ssh in sources.items():
                print(f"{source_name:10} {ssh}")
            continue
        for source_name, ssh in sources.items():
            try:
                results = _run_remote(targets, ssh=ssh, timeout=timeout)
            except RemoteProbeError as exc:
                failures += _print_matrix_source_error(source_name, exc, len(targets))
                continue
            failures += _print_matrix_row(source_name, results)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Check acceptance topology connectivity")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument(
        "--plane",
        choices=["management", "data", "both"],
        default="both",
        help="management checks 172.16 targets; data checks acceptance_business_ipv6 targets",
    )
    parser.add_argument(
        "--ssh",
        help=(
            "Run probes from a remote source via ssh. Example: "
            "'-p 2345 chengyubin@10.112.38.25'"
        ),
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Run probes from multiple SSH source nodes and print one summary row per source",
    )
    parser.add_argument(
        "--source",
        action="append",
        help=(
            "Matrix source in NAME=SSH_ARGS format. Can be repeated. "
            "Defaults to compute-1/2/3 when omitted."
        ),
    )
    parser.add_argument(
        "--source-scope",
        choices=["default", "compute", "plane"],
        default="default",
        help=(
            "Which inventory nodes become SSH sources when --source is omitted. "
            "default keeps the historical compute-1/2/3 quick check; compute "
            "uses all inventory compute nodes; plane uses all nodes that should "
            "participate in the selected plane."
        ),
    )
    parser.add_argument(
        "--source-profile",
        choices=["current", "acceptance"],
        default="current",
        help="SSH endpoint profile for generated sources: current=10.112, acceptance=172.16",
    )
    parser.add_argument("--timeout", type=int, default=1, help="ping timeout in seconds")
    parser.add_argument(
        "--ssh-connect-timeout",
        type=int,
        default=5,
        help="SSH ConnectTimeout used for generated matrix sources",
    )
    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="Print generated matrix SSH sources without running ping probes",
    )
    args = parser.parse_args()

    inventory = _load_inventory(args.inventory)
    failures = 0

    if args.matrix:
        if args.ssh:
            raise SystemExit("--matrix cannot be combined with --ssh; use --source instead")
        return (
            1
            if _run_matrix(
                inventory,
                plane=args.plane,
                source_args=args.source,
                source_scope=args.source_scope,
                source_profile=args.source_profile,
                timeout=args.timeout,
                ssh_connect_timeout=args.ssh_connect_timeout,
                list_sources=args.list_sources,
            )
            else 0
        )

    if args.plane in {"management", "both"}:
        targets = _management_targets(inventory)
        if args.ssh:
            try:
                results = _run_remote(targets, ssh=args.ssh, timeout=args.timeout)
            except RemoteProbeError as exc:
                sys.stderr.write(exc.stderr)
                raise SystemExit(exc.returncode) from exc
        else:
            results = _run_local(targets, timeout=args.timeout)
        failures += _print_results("management plane", results)

    if args.plane in {"data", "both"}:
        targets = _data_targets(inventory)
        if args.ssh:
            try:
                results = _run_remote(targets, ssh=args.ssh, timeout=args.timeout)
            except RemoteProbeError as exc:
                sys.stderr.write(exc.stderr)
                raise SystemExit(exc.returncode) from exc
        else:
            results = _run_local(targets, timeout=args.timeout)
        failures += _print_results("data plane", results)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
