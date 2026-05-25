"""HTTP server utilities for worker containers — serves local data and polls peer endpoints."""

from __future__ import annotations

import json
import os
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


def poll_url(url: str, timeout_sec: float = 120.0, interval_sec: float = 0.5) -> Any:
    """Poll a URL until it returns 200, then return parsed JSON. Raises TimeoutError on timeout."""
    import httpx

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=10.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        time.sleep(interval_sec)
    raise TimeoutError(f"Timed out polling {url} after {timeout_sec}s")


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


def start_server(port: int, handler_class: type[BaseHTTPRequestHandler]) -> Thread:
    """Start an HTTP server on the given port in a background thread."""
    for attempt in range(3):
        try:
            server = HTTPServer(("0.0.0.0", port), handler_class)
            server.allow_reuse_address = True
            break
        except OSError:
            if attempt < 2:
                time.sleep(0.5)
            else:
                raise
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t
