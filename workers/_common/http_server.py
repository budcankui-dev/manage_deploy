"""HTTP server utilities for worker containers — serves local data and polls peer endpoints."""

from __future__ import annotations

import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any


def get_listen_port(role: str) -> int:
    """Read the peer's assigned port from environment (set by platform via port_defs)."""
    env_names = {
        "source": ["PEER_SOURCE_PORT", "PORT_SOURCE"],
        "compute": ["PEER_COMPUTE_PORT", "PORT_COMPUTE"],
        "sink": ["PEER_SINK_PORT", "PORT_SINK"],
    }
    for name in env_names.get(role, []):
        val = os.environ.get(name)
        if val:
            try:
                return int(val)
            except ValueError:
                pass
    return int(os.environ.get(f"PORT_{role.upper()}", 8801))


def get_peer_url(role: str) -> str | None:
    """Get the peer's base URL for push mode.

    Role maps to where THIS node pushes TO (the downstream node).
    - source pushes TO compute -> PEER_COMPUTE_URL
    - compute pushes TO sink   -> PEER_SINK_URL
    - sink is terminal, no downstream
    """
    env_map = {
        "source": "PEER_COMPUTE_URL",   # source pushes job to compute
        "compute": "PEER_SINK_URL",     # compute pushes result to sink
        "sink": None,                   # sink is terminal
    }
    key = env_map.get(role)
    if key is None:
        return None
    val = os.environ.get(key, "")
    if val:
        return val.rstrip("/")
    return None


def get_peer_url_by_name(peer_name: str) -> str | None:
    key = f"PEER_{peer_name.upper()}_URL"
    val = os.environ.get(key, "")
    if val:
        return val.rstrip("/")
    return None


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def peer_connect_timeout(default: float = 600.0) -> float:
    """Long retry window for route/flow-table propagation after network-ready."""
    return max(1.0, _env_float("PEER_CONNECT_TIMEOUT_SEC", default))


def peer_wait_timeout(default: float = 600.0) -> float:
    """Long receive window so upstream/downstream can tolerate delayed connectivity."""
    return max(1.0, _env_float("PEER_WAIT_TIMEOUT_SEC", default))


def _post_json(
    peer_url: str,
    path: str,
    data: dict,
    timeout_sec: float = 120.0,
    interval_sec: float = 2.0,
) -> None:
    import httpx

    timeout_sec = max(float(timeout_sec), peer_connect_timeout())
    url = f"{peer_url}{path}"
    deadline = time.time() + timeout_sec
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            resp = httpx.post(url, json=data, timeout=min(30.0, timeout_sec))
            resp.raise_for_status()
            return
        except (httpx.HTTPError, OSError) as exc:
            last_error = exc
            time.sleep(interval_sec)
    raise TimeoutError(f"Timed out posting to {url}: {last_error}")


def post_json_to_peer(
    role: str,
    path: str,
    data: dict,
    timeout_sec: float = 120.0,
    interval_sec: float = 0.5,
) -> None:
    """Push JSON data to the next node in the pipeline."""
    peer_url = get_peer_url(role)
    if not peer_url:
        raise RuntimeError(f"No downstream peer URL configured for role={role}")
    _post_json(peer_url, path, data, timeout_sec, interval_sec)


def post_json_to_named_peer(
    peer_name: str,
    path: str,
    data: dict,
    timeout_sec: float = 120.0,
    interval_sec: float = 0.5,
) -> None:
    """Push JSON data to an explicit peer role such as source or sink."""
    peer_url = get_peer_url_by_name(peer_name)
    if not peer_url:
        raise RuntimeError(f"No peer URL configured for peer={peer_name}")
    _post_json(peer_url, path, data, timeout_sec, interval_sec)


def post_json_to_url(
    url: str,
    data: dict,
    timeout_sec: float = 30.0,
    interval_sec: float = 2.0,
) -> None:
    """Best-effort compatible helper for posting JSON to an external callback URL."""
    if not url:
        raise RuntimeError("No callback URL configured")
    import httpx

    deadline = time.time() + max(1.0, float(timeout_sec))
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            resp = httpx.post(url, json=data, timeout=min(10.0, timeout_sec))
            resp.raise_for_status()
            return
        except (httpx.HTTPError, OSError) as exc:
            last_error = exc
            time.sleep(interval_sec)
    raise TimeoutError(f"Timed out posting callback to {url}: {last_error}")


def poll_and_post_json(
    get_url: str,
    post_url: str,
    timeout_sec: float = 120.0,
    interval_sec: float = 0.5,
) -> dict:
    """Poll get_url for JSON, then POST it to post_url. Returns the fetched JSON."""
    data = poll_url(get_url, timeout_sec, interval_sec)
    import httpx

    resp = httpx.post(post_url, json=data, timeout=30.0)
    resp.raise_for_status()
    return data


class PostDataHandler(BaseHTTPRequestHandler):
    """Accepts POST /data and optionally serves the latest result via GET /result."""

    received_data: dict | None = None
    result_data: dict | None = None

    def do_POST(self):
        if self.path == "/data":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                PostDataHandler.received_data = json.loads(body.decode("utf-8"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/result" and PostDataHandler.result_data is not None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(PostDataHandler.result_data, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # quiet


class JobDataHandler(BaseHTTPRequestHandler):
    """Serves GET /job as JSON from the local job data written by source."""

    job_data: dict | None = None

    def do_GET(self):
        if self.path == "/job" and JobDataHandler.job_data is not None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(JobDataHandler.job_data).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # quiet


class ResultDataHandler(BaseHTTPRequestHandler):
    """Serves GET /result as JSON from the local result data computed by compute."""

    result_data: dict | None = None

    def do_GET(self):
        if self.path == "/result" and ResultDataHandler.result_data is not None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(ResultDataHandler.result_data).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # quiet


class _ReuseIPv4HTTPServer(HTTPServer):
    allow_reuse_address = True


class _DualStackHTTPServer(HTTPServer):
    """IPv6 listener that also accepts IPv4 when the host kernel allows it."""

    address_family = socket.AF_INET6
    allow_reuse_address = True

    def server_bind(self):
        if hasattr(socket, "IPV6_V6ONLY"):
            try:
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except OSError:
                # Some kernels disallow changing this flag. IPv6 still works; IPv4
                # health checks may require the fallback listener in non-IPv6 envs.
                pass
        super().server_bind()


def wait_for_data_handler(port: int, timeout_sec: float = 120.0, interval_sec: float = 0.5) -> dict:
    """Wait for POST /data to be received by the handler. Returns the received data."""
    timeout_sec = max(float(timeout_sec), peer_wait_timeout())
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if PostDataHandler.received_data is not None:
            data = PostDataHandler.received_data
            PostDataHandler.received_data = None  # clear for next use
            return data
        time.sleep(interval_sec)
    raise TimeoutError(f"Timed out waiting for data after {timeout_sec}s")


def start_server(port: int, handler_class: type[BaseHTTPRequestHandler]) -> Thread:
    """Start a dual-stack HTTP server for business-plane peer traffic."""
    candidates: tuple[tuple[type[HTTPServer], tuple[str, int]], ...] = (
        (_DualStackHTTPServer, ("::", port)),
        (_ReuseIPv4HTTPServer, ("0.0.0.0", port)),
    )
    last_error: OSError | None = None

    for server_cls, address in candidates:
        for attempt in range(3):
            try:
                server = server_cls(address, handler_class)
                t = Thread(target=server.serve_forever, daemon=True)
                t.start()
                return t
            except OSError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5)
        # If IPv6 is unavailable, keep compatibility with IPv4-only hosts.
        continue

    if last_error is not None:
        raise last_error
    raise OSError(f"Failed to start HTTP server on port {port}")
