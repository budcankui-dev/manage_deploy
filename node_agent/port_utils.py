"""宿主机端口解析与占用检测。"""

from __future__ import annotations

import socket
from typing import Optional


def extract_host_ports(ports: Optional[dict[str, str]], network_mode: str = "host") -> list[int]:
    """从 ports 映射提取宿主机端口列表。

    host 模式：value 为监听端口；bridge 模式：value 为宿主机映射端口。
  """
    if not ports:
        return []

    host_ports: list[int] = []
    seen: set[int] = set()
    for container_port, host_port in ports.items():
        raw = str(host_port).strip() if host_port is not None else ""
        if not raw and network_mode == "host":
            raw = str(container_port).strip()
        if not raw:
            continue
        try:
            port_num = int(raw)
        except ValueError:
            continue
        if port_num <= 0 or port_num > 65535 or port_num in seen:
            continue
        seen.add(port_num)
        host_ports.append(port_num)
    return sorted(host_ports)


def ports_map_from_host_ports(host_ports: list[int]) -> dict[str, str]:
    return {str(port): str(port) for port in host_ports}


def is_host_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """检测宿主机端口是否已被监听（TCP）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def format_host_ports_label(host_ports: list[int]) -> str:
    return ",".join(str(port) for port in host_ports)
